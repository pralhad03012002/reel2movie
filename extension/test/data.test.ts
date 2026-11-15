import test from 'node:test';
import assert from 'node:assert/strict';
import { createAuth, NotConnected, type Connection, type Store } from '../src/auth.ts';
import { createData, Retry, type Cache } from '../src/data.ts';

const gate = () => { let go!: () => void; const p = new Promise<void>((r) => { go = r; }); return { p, go }; };
const conn = (uid = 'u', rt = 'R1'): Connection => ({ uid, email: 'e', refreshToken: rt, idToken: 'T', expiresAt: 9e12 });
const raw = (id: string, watched = false) => ({ id, data: { watched } as any });
const settings = { region: 'IN', services: [], localStt: false } as any;

function rig(opts: { cache?: Cache; load?: () => Promise<{ raws: any[]; settings: any }>; patch?: () => Promise<void> } = {}) {
  const st: { conn: Connection | null; cache: Cache | undefined } = { conn: conn(), cache: opts.cache };
  const store: Store = { get: async () => st.conn, set: async (c) => { st.conn = c; }, clear: async () => { st.conn = null; st.cache = undefined; } };
  const auth = createAuth({ store, now: () => 0 });
  const data = createData({
    auth, now: () => 1_000_000,
    cache: { get: async () => st.cache, set: async (c) => { st.cache = c; } },
    load: opts.load ?? (async () => ({ raws: [raw('a')], settings })),
    patch: opts.patch ?? (async () => {}),
  });
  return { st, auth, data };
}

test('fetchAll in flight during disconnect does not write the cache', async () => {
  const g = gate();
  const { st, auth, data } = rig({ load: async () => { await g.p; return { raws: [raw('a')], settings }; } });
  const p = data.fetchAll();
  await new Promise((r) => setTimeout(r, 5));
  await auth.disconnect(); data.reset();
  g.go();
  await assert.rejects(p, Retry); // voided; the overlay's retry then finds NotConnected
  assert.equal(st.cache, undefined);
  assert.equal(st.conn, null);
});

test('fetchAll for the old account does not write after the account changed', async () => {
  const g = gate();
  const { st, data } = rig({ load: async () => { await g.p; return { raws: [raw('a')], settings }; } });
  const p = data.fetchAll();
  await new Promise((r) => setTimeout(r, 5));
  st.conn = conn('other'); // connected as someone else, no reset call
  g.go();
  await assert.rejects(p, NotConnected);
  assert.equal(st.cache, undefined);
});

test('after reset a new fetch is not the old shared promise', async () => {
  const g = gate();
  let calls = 0;
  const { data } = rig({ load: async () => { calls++; if (calls === 1) await g.p; return { raws: [raw('a')], settings }; } });
  const old = data.fetchAll().catch(() => {});
  await new Promise((r) => setTimeout(r, 5));
  data.reset();
  await data.fetchAll();
  assert.equal(calls, 2);
  g.go(); await old;
});

test('getData: cache replies at once (stale when old) and refreshes in the background; no cache waits', async () => {
  const g = gate();
  const old: Cache = { uid: 'u', raws: [raw('old')], settings, at: 0 };
  let calls = 0;
  const { st, data } = rig({ cache: old, load: async () => { calls++; await g.p; return { raws: [raw('new')], settings }; } });
  const r = await data.getData(false);
  assert.equal(r.stale, true);
  assert.equal(r.cache.raws[0].id, 'old');
  g.go();
  await data.fetchAll(); // single-flight: joins the background fetch
  assert.equal(calls, 1);
  assert.equal(st.cache!.raws[0].id, 'new');
  const fresh = await data.getData(false);
  assert.equal(fresh.stale, false);
  const empty = rig();
  const w = await empty.data.getData(false);
  assert.equal(w.cache.raws[0].id, 'a');
});

test('getData(force) falls back to the cache when offline, but not when the connection is gone', async () => {
  const old: Cache = { uid: 'u', raws: [raw('old')], settings, at: 0 };
  const off = rig({ cache: old, load: async () => { throw new Error('offline'); } });
  assert.deepEqual([(await off.data.getData(true)).cache.raws[0].id, (await off.data.getData(true)).stale], ['old', true]);
  const none = rig();
  none.st.conn = null;
  await assert.rejects(none.data.getData(false), NotConnected);
});

test('a fetch that began before setWatched cannot revert watched in the cache', async () => {
  const g = gate();
  let first = true;
  const base: Cache = { uid: 'u', raws: [raw('a', false)], settings, at: 0 };
  const { st, data } = rig({ cache: base, load: async () => { const stale = first; first = false; if (stale) await g.p; return { raws: [raw('a', false)], settings }; } });
  const f = data.fetchAll(); // reads watched=false, then waits
  await new Promise((r) => setTimeout(r, 5));
  await data.setWatched('a', true);
  assert.equal(st.cache!.raws[0].data.watched, true);
  g.go();
  await f;
  assert.equal(st.cache!.raws[0].data.watched, true);
});

test('setWatched during a disconnect does not rewrite the cache', async () => {
  const g = gate();
  const { st, auth, data } = rig({ cache: { uid: 'u', raws: [raw('a')], settings, at: 0 }, patch: async () => { await g.p; } });
  const p = data.setWatched('a', true);
  await new Promise((r) => setTimeout(r, 5));
  await auth.disconnect(); data.reset();
  g.go(); await p;
  assert.equal(st.cache, undefined);
});

test('setWatched: edit is recorded before the PATCH, so a refresh with pre-PATCH data keeps it; a failed PATCH undoes it', async () => {
  const gl = gate(), gp = gate();
  const { data } = rig({ patch: async () => { await gp.p; }, load: async () => { await gl.p; return { raws: [raw('a', false)], settings }; } });
  const f = data.fetchAll(); // began before the edit
  await new Promise((r) => setTimeout(r, 5));
  const w = data.setWatched('a', true); // PATCH still pending
  await new Promise((r) => setTimeout(r, 5));
  gl.go();
  assert.equal((await f).raws[0].data.watched, true);
  gp.go(); await w;
  const bad = rig({ patch: async () => { throw new Error('x'); } });
  await assert.rejects(bad.data.setWatched('a', true));
  assert.equal((await bad.data.fetchAll()).raws[0].data.watched, false);
});

test('setWatched: a disconnect during the token await voids it (no PATCH)', async () => {
  let patched = 0;
  const { auth, data } = rig({ patch: async () => { patched++; } });
  const orig = auth.getIdToken.bind(auth);
  (auth as any).getIdToken = async () => { const t = await orig(); data.reset(); return t; };
  await assert.rejects(data.setWatched('a', true), NotConnected);
  assert.equal(patched, 0);
});

test('a fetch voided by reset rejects with Retry, not NotConnected', async () => {
  const g = gate();
  const { data } = rig({ load: async () => { await g.p; return { raws: [raw('a')], settings }; } });
  const p = data.fetchAll();
  await new Promise((r) => setTimeout(r, 5));
  data.reset(); g.go();
  await assert.rejects(p, Retry);
});
