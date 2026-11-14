// Everything the UI needs from Firebase: sign-in, the queue, settings and the saved movies (as UI `Movie`s).
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { initializeApp } from 'firebase/app';
import { GoogleAuthProvider, getAuth, onAuthStateChanged, signInWithCustomToken, signInWithPopup, signOut, type User } from 'firebase/auth';
import {
  arrayRemove, arrayUnion, collection, deleteDoc, doc, getDoc, getFirestore, onSnapshot, serverTimestamp, setDoc, updateDoc,
  type DocumentReference, type Timestamp,
} from 'firebase/firestore';
import { firebaseConfig } from './firebase-config.js';
import { extractUrl, httpsUrl, isReelUrl } from './lib.js';
import type { Movie, Provider, Recommendation } from './components/types';

const app = initializeApp(firebaseConfig);
const auth = getAuth(app);
const db = getFirestore(app);
if (import.meta.env.DEV) (window as unknown as { __rp: unknown }).__rp = { auth, signInWithCustomToken }; // lets a dev script sign in; absent from the build

export const UNSUPPORTED = 'Only Instagram reel/post, YouTube Shorts and TikTok video links are supported';

export interface Settings { region: string; services: string[]; localStt: boolean }
export interface Post { id: string; url: string; status: 'queued' | 'processing' | 'done' | 'failed'; stage?: string; error?: string; createdAt?: Timestamp }

// --- Incoming share (manifest share_target, GET). Android puts the link in `text`. Runs once, at load. ---
let shareNote = '';
{
  const params = new URLSearchParams(location.search);
  if (['url', 'text', 'title'].some((k) => params.has(k))) {
    const shared = extractUrl(params.get('url'), params.get('text'), params.get('title'));
    // sessionStorage keeps it across sign-in and reload until the write is acknowledged; the doc id is fixed here,
    // so a reload retries the same doc instead of queueing a second one.
    if (!shared) shareNote = 'No https link found in what was shared.';
    else if (!isReelUrl(shared)) shareNote = UNSUPPORTED;
    else sessionStorage.setItem('pendingShare', JSON.stringify({ id: crypto.randomUUID(), url: shared }));
    history.replaceState(null, '', location.pathname);
  }
}

type Raw = Record<string, any>; // a Firestore movie doc; written by worker/pipeline.js toMovieDoc

const trailerKey = (url: unknown) => {
  try { return new URL(String(url)).searchParams.get('v'); } catch { return null; }
};

export function toMovie(raw: Raw, id: string, region: string): Movie {
  const fallbackAt = (raw.createdAt as Timestamp | undefined)?.toDate().toISOString() ?? new Date().toISOString();
  // One entry per creator (the latest reel), so "recommended by N" counts people, not reels.
  const byCreator = new Map<string, Recommendation>();
  for (const s of (raw.sources ?? []) as Raw[]) {
    const handle = s.creatorHandle ? `@${s.creatorHandle}` : '';
    const rec: Recommendation = { creator: s.creatorHandle || 'A saved reel', handle, at: s.at ?? fallbackAt, quote: s.evidence || undefined, postUrl: httpsUrl(s.postUrl) ?? undefined };
    const key = handle || s.postUrl;
    const seen = byCreator.get(key);
    if (!seen || rec.at >= seen.at) byCreator.set(key, rec);
  }
  const p = raw.providers?.[region] as { stream?: { name: string }[]; rent?: { name: string }[] } | undefined;
  const providers: Provider[] = [
    ...(p?.stream ?? []).map((x) => ({ name: x.name, kind: 'stream' as const })),
    ...(p?.rent ?? []).map((x) => ({ name: x.name, kind: 'rent' as const })),
  ];
  const poster = httpsUrl(raw.posterUrl) ?? '';
  return {
    id,
    tmdbId: raw.tmdbId,
    mediaType: raw.mediaType,
    title: raw.title ?? '',
    year: raw.year ?? 0,
    runtimeMin: raw.runtimeMin ?? null,
    seasons: raw.seasons ?? undefined,
    overview: raw.overview ?? '',
    tagline: raw.tagline || undefined,
    rating: Math.round((raw.rating ?? 0) * 10) / 10,
    genres: raw.genres ?? [],
    director: raw.director ?? null,
    cast: raw.cast ?? [],
    poster,
    backdrop: httpsUrl(raw.backdropUrl) ?? poster,
    trailerKey: trailerKey(raw.trailerUrl),
    providers,
    recommendations: [...byCreator.values()],
    watched: !!raw.watched,
  };
}

const seconds = (t?: Timestamp) => t?.seconds ?? Infinity; // null while a server timestamp is pending

export function useReelPicks() {
  const [user, setUser] = useState<User | null | undefined>(undefined); // undefined = auth not resolved yet
  const [settings, setSettings] = useState<Settings>({ region: 'IN', services: [], localStt: false });
  const [posts, setPosts] = useState<Post[]>([]);
  const [raws, setRaws] = useState<{ id: string; data: Raw }[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [message, setMessage] = useState(shareNote);
  const userDoc = useRef<DocumentReference | null>(null);
  const fail = (e: unknown) => setMessage(e instanceof Error ? e.message : String(e));

  const queue = useCallback(async (url: string, source: 'paste' | 'share_target', ref = doc(collection(userDoc.current!, 'processingPosts'))) => {
    try {
      await setDoc(ref, { url, source, status: 'queued', createdAt: serverTimestamp() });
    } catch (e) {
      // A share retried after a reload is refused (posts are not updatable) if the first attempt got through: not an error.
      if (!(await getDoc(ref).catch(() => null))?.exists()) setMessage(`Could not queue ${url}: ${e instanceof Error ? e.message : e}`);
    }
  }, []);

  useEffect(() => {
    let stops: (() => void)[] = [];
    const off = onAuthStateChanged(auth, (u) => {
      stops.forEach((s) => s());
      stops = [];
      setUser(u);
      setSettings({ region: 'IN', services: [], localStt: false });
      setPosts([]);
      setRaws([]);
      setLoaded(false);
      if (!u) { userDoc.current = null; return; }
      const ud = (userDoc.current = doc(db, 'users', u.uid));
      let pending: { id: string; url: string } | null = null;
      try { pending = JSON.parse(sessionStorage.getItem('pendingShare') ?? 'null'); } catch { /* malformed */ }
      if (typeof pending?.url !== 'string' || typeof pending.id !== 'string') { pending = null; sessionStorage.removeItem('pendingShare'); }
      if (pending) {
        setMessage('');
        queue(pending.url, 'share_target', doc(ud, 'processingPosts', pending.id)).then(() => sessionStorage.removeItem('pendingShare'));
      }
      stops = [
        onSnapshot(ud, (s) => setSettings({ region: 'IN', services: [], localStt: false, ...s.data() }), fail),
        // ponytail: listens to finished posts too; filter or delete them if the collection grows large.
        onSnapshot(collection(ud, 'processingPosts'), (s) =>
          setPosts(s.docs.map((d) => ({ ...(d.data() as Omit<Post, 'id'>), id: d.id })).sort((a, b) => seconds(a.createdAt) - seconds(b.createdAt))), fail),
        onSnapshot(collection(ud, 'movies'), (s) => {
          // newest first, so a movie recommended again by a new reel moves up
          setRaws(s.docs.map((d) => ({ id: d.id, data: d.data() })).sort((a, b) => seconds(b.data.updatedAt) - seconds(a.data.updatedAt)));
          setLoaded(true);
        }, fail),
      ];
    });
    return () => { off(); stops.forEach((s) => s()); };
  }, [queue]);

  const movies = useMemo(() => raws.map((r) => toMovie(r.data, r.id, settings.region)), [raws, settings.region]);
  const allServices = useMemo(
    () => [...new Set([...movies.flatMap((m) => m.providers.map((p) => p.name)), ...settings.services])].sort(),
    [movies, settings.services],
  );
  const merge = (data: object) => setDoc(userDoc.current!, data, { merge: true }).catch(fail);

  return {
    user, movies, loaded, settings, allServices, message, setMessage,
    posts: posts.filter((p) => p.status !== 'done'), // done = its movies are in the list
    signIn: () => {
      setMessage('');
      return signInWithPopup(auth, new GoogleAuthProvider()).catch((e) => {
        if (e.code === 'auth/popup-blocked') setMessage('Your browser blocked the sign-in popup. Allow popups for this site, then try again.');
        else if (e.code !== 'auth/popup-closed-by-user' && e.code !== 'auth/cancelled-popup-request') setMessage(e.message);
      });
    },
    signOut: () => signOut(auth).catch(fail),
    addReel: (text: string): boolean => {
      const url = extractUrl(text);
      if (!url || !isReelUrl(url)) { setMessage(UNSUPPORTED); return false; }
      setMessage('');
      void queue(url, 'paste');
      return true;
    },
    dismissPost: (id: string) => deleteDoc(doc(userDoc.current!, 'processingPosts', id)).catch(fail),
    toggleWatched: (id: string) => {
      const m = movies.find((x) => x.id === id);
      if (m) updateDoc(doc(userDoc.current!, 'movies', id), { watched: !m.watched }).catch(fail);
    },
    removeMovie: (id: string) => deleteDoc(doc(userDoc.current!, 'movies', id)).catch(fail),
    setRegion: (region: string) => merge({ region }),
    setService: (name: string, on: boolean) => merge({ services: on ? arrayUnion(name) : arrayRemove(name) }),
    setLocalStt: (localStt: boolean) => merge({ localStt }),
  };
}
