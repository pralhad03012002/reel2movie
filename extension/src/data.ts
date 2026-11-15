// The movie list: cache, stale-while-revalidate reads, single-flight fetching, and the watched write-through.
// Pure of chrome.* so node tests can drive it; background.ts wires the real storage and Firestore in.
import { NotConnected, type createAuth } from './auth.ts';
import type { RawMovie, Settings } from './firestore.ts';

export interface Cache { uid: string; raws: RawMovie[]; settings: Settings; at: number }
export interface CacheStore { get(): Promise<Cache | undefined>; set(c: Cache): Promise<void> }
/** The fetch was voided by a connect/disconnect while it ran: asking again is the right move. */
export class Retry extends Error { constructor() { super('Try again'); this.name = 'Retry'; } }
export const FRESH_MS = 5 * 60_000;

export function createData({ auth, cache, load, patch, now = Date.now }: {
  auth: ReturnType<typeof createAuth>;
  cache: CacheStore;
  load(uid: string, idToken: string): Promise<{ raws: RawMovie[]; settings: Settings }>;
  patch(uid: string, idToken: string, id: string, watched: boolean): Promise<void>;
  now?: () => number;
}) {
  let gen = 0; // bumped by reset(): fetches that started earlier must not write the cache
  let fetching: Promise<Cache> | null = null; // concurrent callers share one fetch
  let chain: Promise<unknown> = Promise.resolve(); // every cache write goes through here, one at a time
  const queueCacheWrite = <T>(fn: () => Promise<T>): Promise<T> => { const p = chain.then(fn); chain = p.catch(() => {}); return p; };
  let n = 0; // watched edits made so far; a fetch that began before an edit must not undo it
  const patched = new Map<string, { watched: boolean; n: number }>();

  function fetchAll(): Promise<Cache> {
    if (fetching) return fetching;
    const g = gen, start = n;
    const p: Promise<Cache> = (async () => {
      const { uid, idToken } = await auth.getIdToken();
      const { raws, settings } = await load(uid, idToken);
      for (const r of raws) { const e = patched.get(r.id); if (e && e.n > start) r.data.watched = e.watched; }
      const c: Cache = { uid, raws, settings, at: now() };
      return queueCacheWrite(async () => {
        if (g !== gen) throw new Retry(); // connect/disconnect happened while loading
        if ((await auth.store.get())?.uid !== uid) throw new NotConnected(); // disconnected or switched account while loading
        await cache.set(c); // checks above and this call share no await, so a disconnect cannot slip between them
        return c;
      });
    })();
    fetching = p;
    const done = () => { if (fetching === p) fetching = null; };
    p.then(done, done);
    return p;
  }

  return {
    fetchAll,
    /** Call after connect or disconnect: forgets the shared fetch and voids writes of fetches in flight. */
    reset() { gen++; fetching = null; patched.clear(); },
    /** Cache first (stale:true when older than FRESH_MS, refreshing in the background); no cache, or force: wait for the fetch. */
    async getData(force: boolean): Promise<{ cache: Cache; stale: boolean }> {
      const { uid } = await auth.connection();
      const c = await cache.get();
      const have = c?.uid === uid ? c : undefined;
      if (have && !force) {
        const stale = now() - have.at >= FRESH_MS;
        if (stale) fetchAll().catch(() => {});
        return { cache: have, stale };
      }
      try {
        return { cache: await fetchAll(), stale: false };
      } catch (e) {
        if (e instanceof NotConnected || !have) throw e;
        return { cache: have, stale: true }; // offline: stale beats nothing
      }
    },
    async setWatched(id: string, watched: boolean): Promise<void> {
      const g = gen; // read before any await: a disconnect during the token await voids the whole operation
      const { uid, idToken } = await auth.getIdToken();
      if (g !== gen) throw new NotConnected();
      const prev = patched.get(id), mine = { watched, n: ++n };
      patched.set(id, mine); // recorded before the PATCH so a refresh returning pre-PATCH data cannot revert it
      try { await patch(uid, idToken, id, watched); } catch (e) {
        if (g === gen && patched.get(id) === mine) prev ? patched.set(id, prev) : patched.delete(id);
        throw e;
      }
      if (g !== gen) return;
      await queueCacheWrite(async () => {
        const c = await cache.get();
        if (c?.uid !== uid || g !== gen) return;
        for (const r of c.raws) if (r.id === id) r.data.watched = watched; // keep the cache in step so the next read does not undo it
        await cache.set(c);
      });
    },
  };
}
