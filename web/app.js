import { initializeApp } from 'https://www.gstatic.com/firebasejs/13.2.0/firebase-app.js';
import { getAuth, GoogleAuthProvider, signInWithPopup, signOut, onAuthStateChanged }
  from 'https://www.gstatic.com/firebasejs/13.2.0/firebase-auth.js';
import { getFirestore, collection, doc, getDoc, setDoc, updateDoc, deleteDoc, onSnapshot, serverTimestamp, arrayUnion, arrayRemove }
  from 'https://www.gstatic.com/firebasejs/13.2.0/firebase-firestore.js';
import { firebaseConfig } from './firebase-config.js';
import { extractUrl, httpsUrl, isReelUrl, providerSearchUrl } from './lib.js';

const app = initializeApp(firebaseConfig);
const auth = getAuth(app);
const db = getFirestore(app);

const $ = (id) => document.getElementById(id);
// Builds an element from properties (textContent, href, ...) and child nodes/strings. Never innerHTML.
function el(tag, props, ...children) {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children.filter(Boolean));
  return node;
}
const say = (text) => { $('message').textContent = text; };
const fail = (e) => say(e.message);
const seconds = (t) => t?.seconds ?? Infinity; // null while the server timestamp is pending
const UNSUPPORTED = 'Only Instagram reel/post, YouTube Shorts and TikTok video links are supported';

let userDoc = null; // users/{uid} reference while signed in
let unsubs = [];
let settings, posts, movies, moviesLoaded; // set in the auth callback before anything renders

// --- Incoming share (manifest share_target, GET). Android puts the link in `text`. ---
const params = new URLSearchParams(location.search);
if (['url', 'text', 'title'].some((k) => params.has(k))) {
  const shared = extractUrl(params.get('url'), params.get('text'), params.get('title'));
  // sessionStorage keeps it across sign-in and reload until the write is acknowledged. The address bar is cleaned
  // and the doc id is fixed here, so a reload retries the same doc instead of queueing a second one.
  if (!shared) say('No https link found in what was shared.');
  else if (!isReelUrl(shared)) say(UNSUPPORTED);
  else sessionStorage.setItem('pendingShare', JSON.stringify({ id: crypto.randomUUID(), url: shared }));
  history.replaceState(null, '', location.pathname);
}

// Settles once the server accepts or refuses the write; while offline it stays pending.
async function queue(url, source, ref = doc(collection(userDoc, 'processingPosts'))) {
  try {
    await setDoc(ref, { url, source, status: 'queued', createdAt: serverTimestamp() });
  } catch (e) {
    // A share retried after a reload is refused (posts are not updatable) if the first attempt got through: not an error.
    if (!(await getDoc(ref).catch(() => null))?.exists()) say(`Could not queue ${url}: ${e.message}`);
  }
}

// --- Auth ---
// ponytail: popup flow only. signInWithRedirect needs authDomain on the app's own origin; add that if popups prove unusable.
$('sign-in').onclick = () => {
  say('');
  signInWithPopup(auth, new GoogleAuthProvider()).catch((e) => {
    if (e.code === 'auth/popup-blocked') {
      say('Your browser blocked the sign-in popup. Allow popups for this site, then press Sign in again.');
    } else if (e.code !== 'auth/popup-closed-by-user' && e.code !== 'auth/cancelled-popup-request') {
      say(e.message);
    }
  });
};
$('sign-out').onclick = () => signOut(auth).catch(fail);

onAuthStateChanged(auth, (user) => {
  unsubs.forEach((stop) => stop());
  unsubs = [];
  settings = { region: 'IN', services: [] };
  posts = [];
  movies = [];
  moviesLoaded = false; // no "No movies yet" before the first movies snapshot
  renderPosts(); // clear the previous account's data from the page
  renderMovies();
  $('signed-out').hidden = !!user;
  $('signed-in').hidden = !user;
  $('sign-out').hidden = !user;
  $('user-email').textContent = user?.email || '';

  let pending = null;
  try {
    pending = JSON.parse(sessionStorage.getItem('pendingShare'));
  } catch {}
  if (typeof pending?.url !== 'string' || typeof pending.id !== 'string') { // malformed or old format: no pending share
    pending = null;
    sessionStorage.removeItem('pendingShare');
  }
  if (!user) {
    userDoc = null;
    if (pending) say('Sign in to save the reel you shared.');
    return;
  }
  userDoc = doc(db, 'users', user.uid);
  if (pending) {
    say('');
    queue(pending.url, 'share_target', doc(userDoc, 'processingPosts', pending.id))
      .then(() => sessionStorage.removeItem('pendingShare'));
  }
  const rows = (snap) => snap.docs.map((d) => ({ ...d.data(), id: d.id }));
  unsubs = [
    onSnapshot(userDoc, (snap) => {
      settings = { region: 'IN', services: [], ...snap.data() };
      renderMovies();
    }, fail),
    // ponytail: listens to every post, including finished ones the worker leaves behind; delete or filter them if the collection grows large.
    onSnapshot(collection(userDoc, 'processingPosts'), (snap) => {
      posts = rows(snap).sort((a, b) => seconds(a.createdAt) - seconds(b.createdAt));
      renderPosts();
    }, fail),
    onSnapshot(collection(userDoc, 'movies'), (snap) => {
      // updatedAt, so a movie recommended again by a new reel moves to the top.
      movies = rows(snap).sort((a, b) => seconds(b.updatedAt) - seconds(a.updatedAt));
      moviesLoaded = true;
      renderMovies();
    }, fail),
  ];
});

// --- Paste a link (desktop path) ---
$('paste-form').onsubmit = (event) => {
  event.preventDefault();
  const url = extractUrl($('paste-url').value);
  if (!isReelUrl(url)) return say(UNSUPPORTED);
  say('');
  $('paste-url').value = '';
  queue(url, 'paste');
};

// --- Processing strip ---
const STAGES = {
  downloading: 'Downloading…',
  transcribing: 'Transcribing with ElevenLabs…',
  'transcribing-local': 'Transcribing on your computer (local Whisper)…',
  extracting: 'Finding movies…',
  matching: 'Matching titles…',
};

function renderPosts() {
  const shown = posts.filter((p) => p.status !== 'done'); // done = its movies are in the list
  $('processing').hidden = !shown.length;
  $('posts').replaceChildren(...shown.map((p) => {
    const status = p.status === 'failed' ? `Failed: ${p.error || 'unknown error'}`
      : p.status === 'processing' ? STAGES[p.stage] || 'Processing…'
      : 'Queued';
    return el('li', { className: p.status === 'failed' ? 'failed' : '' },
      el('div', {},
        el('strong', { textContent: status }),
        el('span', { className: 'muted url', textContent: p.url })),
      el('button', {
        type: 'button',
        textContent: 'Dismiss',
        onclick: () => deleteDoc(doc(userDoc, 'processingPosts', p.id)).catch(fail),
      }));
  }));
}

// --- Movies, filters, settings ---
$('filter-watched').onchange = renderMovies;
$('filter-mine').onchange = renderMovies;
$('region').onchange = (e) => setDoc(userDoc, { region: e.target.value }, { merge: true }).catch(fail);
$('local-stt').onchange = (e) => setDoc(userDoc, { localStt: e.target.checked }, { merge: true }).catch(fail);

// ponytail: rebuilds the whole list on every snapshot; fine for hundreds of movies, diff by doc id if it gets slow.
function renderMovies() {
  const focusId = document.activeElement?.id; // re-rendering would otherwise drop keyboard focus
  const mine = new Set(settings.services);
  const providers = (m) => {
    const p = m.providers?.[settings.region];
    return { stream: p?.stream || [], rent: p?.rent || [] };
  };
  const all = (m) => [...providers(m).stream, ...providers(m).rent];

  const want = $('filter-watched').value;
  const mineOnly = $('filter-mine').checked;
  const shown = movies.filter((m) =>
    (want === 'all' || (want === 'watched') === !!m.watched)
    && (!mineOnly || all(m).some((p) => mine.has(p.name))));

  $('empty').hidden = shown.length > 0 || !moviesLoaded;
  $('empty').textContent = movies.length
    ? 'No movies match these filters.'
    : 'No movies yet. On Android, install this app from the browser menu (Add to Home screen), then '
      + 'tap Share on an Instagram reel and choose ReelPicks. On a computer, paste the reel link above.';

  // One link per distinct search URL, the user's services first. `seen` is shared so rent skips what stream already shows.
  // `theirs` = URLs of the user's own services: another service with the same URL gives way, so the survivor is highlighted.
  const ottLinks = (m, list, small, seen, theirs) =>
    [...list].sort((a, b) => mine.has(b.name) - mine.has(a.name)).flatMap((p) => {
      const href = providerSearchUrl(p.name, m.title);
      if (seen.has(href) || (theirs.has(href) && !mine.has(p.name))) return [];
      seen.add(href);
      return el('a', {
        href, target: '_blank', rel: 'noopener', textContent: p.name,
        className: 'ott' + (mine.has(p.name) ? ' mine' : '') + (small ? ' small' : ''),
      });
    });

  $('movies').replaceChildren(...shown.map((m) => {
    const ref = doc(userDoc, 'movies', m.id);
    const poster = httpsUrl(m.posterUrl);
    const trailer = httpsUrl(m.trailerUrl);
    const seen = new Set();
    const theirs = new Set(all(m).filter((p) => mine.has(p.name)).map((p) => providerSearchUrl(p.name, m.title)));
    const stream = ottLinks(m, providers(m).stream, false, seen, theirs);
    const rent = ottLinks(m, providers(m).rent, true, seen, theirs);
    const meta = [
      typeof m.rating === 'number' && m.rating > 0 && `★ ${m.rating.toFixed(1)}`,
      ...(m.genres || []),
    ].filter(Boolean).join(' · ');

    return el('li', { className: 'movie' + (m.watched ? ' watched' : '') },
      poster ? el('img', { src: poster, alt: `Poster of ${m.title}`, loading: 'lazy', width: 92, height: 138 })
        : el('div', { className: 'no-poster' }),
      el('div', { className: 'body' },
        el('h3', {}, m.title, m.year && el('span', { className: 'muted', textContent: ` (${m.year})` })),
        meta && el('p', { className: 'muted', textContent: meta }),
        el('p', { className: 'overview', textContent: m.overview }),
        el('div', { className: 'otts' },
          ...stream,
          rent.length && el('span', { className: 'muted small', textContent: 'Rent or buy:' }),
          ...rent,
          !stream.length && !rent.length
            && el('span', { className: 'muted', textContent: `No streaming info for ${settings.region}.` })),
        trailer && el('p', {}, el('a', { href: trailer, target: '_blank', rel: 'noopener', textContent: 'Trailer' })),
        ...(m.sources || []).map((s) => {
          const label = s.creatorHandle ? `Reel by @${s.creatorHandle}` : 'Source reel';
          const href = httpsUrl(s.postUrl);
          return el('p', { className: 'muted source' },
            href ? el('a', { href, target: '_blank', rel: 'noopener', textContent: label }) : label,
            s.evidence && ` — “${s.evidence}”`);
        }),
        el('div', { className: 'row actions' },
          el('label', {},
            el('input', {
              type: 'checkbox', id: `watched_${m.id}`, checked: !!m.watched,
              onchange: (e) => updateDoc(ref, { watched: e.target.checked }).catch(fail),
            }),
            ' Watched'),
          el('button', {
            type: 'button', textContent: 'Delete', ariaLabel: `Delete ${m.title}`,
            onclick: () => confirm(`Remove "${m.title}" from your list?`) && deleteDoc(ref).catch(fail),
          }))));
  }));

  // Settings: services seen in this region's providers, plus any already chosen so they can be unchecked.
  $('region').value = settings.region;
  $('local-stt').checked = settings.localStt === true;
  const names = [...new Set([...movies.flatMap(all).map((p) => p.name), ...settings.services])].sort();
  $('services').replaceChildren(...(names.length ? names.map((name) =>
    el('label', {},
      el('input', {
        type: 'checkbox', id: `service_${name}`, checked: mine.has(name),
        onchange: (e) => setDoc(userDoc, { services: e.target.checked ? arrayUnion(name) : arrayRemove(name) },
          { merge: true }).catch(fail),
      }),
      ` ${name}`))
    : [el('p', { className: 'muted', textContent: 'Services appear here once your movies have streaming info for this region.' })]));

  if (focusId) $(focusId)?.focus();
}

navigator.serviceWorker?.register('sw.js');
