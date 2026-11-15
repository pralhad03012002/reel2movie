// Service worker. Messages from our own pages (content script, overlay, connect page):
//   {type:'status'}                      -> {ok, connected, email?}
//   {type:'getData'}                     -> {ok, movies: Movie[], settings, cachedAt, stale?}  (cache first; stale:true = a refresh is running, ask again with refresh)
//   {type:'refresh'}                     -> same as getData, forces a fetch
//   {type:'setWatched', id, watched}     -> {ok}
//   {type:'disconnect'}                  -> {ok}
// Failures reply {ok:false, error, notConnected?, retry?} (retry: a connect/disconnect voided the fetch, ask again). From the web app (onMessageExternal): {type:'connect', uid, refreshToken, email}.
import { createAuth, NotConnected, type Connection } from './auth.ts';
import { parseConnect } from './connect.ts';
import { createData, Retry, type Cache } from './data.ts';
import { getSettings, listMovies, setWatched } from './firestore.ts';
import { toMovie } from '../../app/src/movie.ts';

const local = chrome.storage.local;
try { local.setAccessLevel({ accessLevel: 'TRUSTED_CONTEXTS' }).catch(() => {}); } catch { /* API missing (old Chrome): nothing to restrict */ } // content scripts (and so the site) can never read the token
const auth = createAuth({
  store: {
    get: async () => ((await local.get('conn')).conn as Connection | undefined) ?? null,
    set: (c) => local.set({ conn: c }),
    clear: () => local.remove(['conn', 'cache']),
  },
});
const data = createData({
  auth,
  cache: { get: async () => (await local.get('cache')).cache as Cache | undefined, set: (cache) => local.set({ cache }) },
  load: async (uid, idToken) => { const [raws, settings] = await Promise.all([listMovies(uid, idToken), getSettings(uid, idToken)]); return { raws, settings }; },
  patch: setWatched,
});

const reply = ({ cache: c, stale }: { cache: Cache; stale: boolean }) =>
  ({ ok: true, movies: c.raws.map((r) => toMovie(r.data, r.id, c.settings.region)), settings: c.settings, cachedAt: c.at, ...(stale && { stale: true }) });

// RP_DEV builds only (tree-shaken otherwise): browser tests set chrome.storage.local['rp-dev'] = {connected, movies, settings, failWrites?, error?, stale?, fresh?, delay?}
// and the worker answers from it instead of Firestore.
async function handleDev(msg: any, d: any) {
  switch (msg?.type) {
    case 'status': return { ok: true, connected: d.connected, email: 'dev@example.com' };
    case 'getData': case 'refresh':
      if (msg.type === 'refresh' && d.delay) await new Promise((r) => setTimeout(r, d.delay)); // lets tests watch the quiet swap
      if (msg.type === 'refresh' && d.offline) return { ok: true, movies: d.movies, settings: d.settings, cachedAt: Date.now() - 36e5, stale: true };
      if (d.error) return { ok: false, error: d.error };
      if (!d.connected) return { ok: false, error: 'Not connected', notConnected: true };
      if (msg.type === 'getData' && d.stale) return { ok: true, movies: d.movies, settings: d.settings, cachedAt: Date.now() - 36e5, stale: true }; // d.fresh is what the follow-up refresh returns
      return { ok: true, movies: msg.type === 'refresh' && d.fresh ? d.fresh : d.movies, settings: d.settings, cachedAt: Date.now() };
    case 'setWatched':
      if (!d.connected) return { ok: false, error: 'Not connected', notConnected: true };
      if (d.failWrites) throw new Error('Write failed');
      for (const m of d.movies) if (m.id === msg.id) m.watched = msg.watched;
      await local.set({ 'rp-dev': d });
      return { ok: true };
    case 'disconnect': await local.set({ 'rp-dev': { ...d, connected: false } }); return { ok: true };
    default: throw new Error('Unknown message');
  }
}

async function handle(msg: any) {
  if (__RP_DEV__) { const d = (await local.get('rp-dev'))['rp-dev']; if (d) return handleDev(msg, d); }
  switch (msg?.type) {
    case 'status': {
      const c = await auth.store.get();
      return { ok: true, connected: !!c, email: c?.email };
    }
    case 'getData': return reply(await data.getData(false));
    case 'refresh': return reply(await data.getData(true));
    case 'setWatched':
      if (typeof msg.id !== 'string' || typeof msg.watched !== 'boolean') throw new Error('Bad request');
      await data.setWatched(msg.id, msg.watched);
      return { ok: true };
    case 'disconnect': await auth.disconnect(); data.reset(); return { ok: true };
    default: throw new Error('Unknown message');
  }
}

const run = (p: Promise<unknown>, send: (r: unknown) => void) =>
  p.then(send, (e) => send({ ok: false, error: e instanceof Error ? e.message : 'Failed', notConnected: e instanceof NotConnected, ...(e instanceof Retry && { retry: true }) }));

chrome.runtime.onMessage.addListener((msg, sender, send) => {
  if (sender.id !== chrome.runtime.id) return false;
  run(handle(msg), send);
  return true;
});

chrome.runtime.onMessageExternal.addListener((msg, sender, send) => {
  const m = parseConnect(msg, sender);
  if (!m) { send({ ok: false, error: 'Rejected' }); return false; }
  // reset + cache removal come first too: the old account's cache must never sit beside the new connection, and a fetch starting in the gap must not be voided by the reset after the write
  run((async () => { data.reset(); await local.remove('cache'); await auth.connect(m.uid, m.email, m.refreshToken); data.reset(); await local.remove('cache'); return { ok: true }; })(), send);
  return true;
});
