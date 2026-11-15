import test from 'node:test';
import assert from 'node:assert/strict';
import { createAuth, NotConnected, BadConnection, type Connection, type Store } from '../src/auth.ts';

const mem = (c: Connection | null): Store & { c: Connection | null } => {
  const s = { c, get: async () => s.c, set: async (n: Connection) => { s.c = n; }, clear: async () => { s.c = null; } };
  return s;
};
const conn = (expiresAt: number): Connection => ({ uid: 'u', email: 'e', refreshToken: 'R1', idToken: 'OLD', expiresAt });
const tokenRes = (extra = {}) => new Response(JSON.stringify({ id_token: 'NEW', refresh_token: 'R2', expires_in: '3600', user_id: 'u', ...extra }));

test('fresh token is returned without a request', async () => {
  let calls = 0;
  const a = createAuth({ store: mem(conn(1_000_000 + 120_000)), now: () => 1_000_000, fetch: (async () => { calls++; return tokenRes(); }) as unknown as typeof fetch });
  assert.deepEqual(await a.getIdToken(), { uid: 'u', idToken: 'OLD' });
  assert.equal(calls, 0);
});

test('expiring token refreshes, form body is right, rotated refresh token is saved', async () => {
  const store = mem(conn(1_000_000 + 30_000));
  let req: { url: string; body: string } | undefined;
  const a = createAuth({ store, now: () => 1_000_000, fetch: (async (url: string, init: RequestInit) => { req = { url, body: String(init.body) }; return tokenRes(); }) as unknown as typeof fetch });
  assert.equal((await a.getIdToken()).idToken, 'NEW');
  assert.match(req!.url, /^https:\/\/securetoken\.googleapis\.com\/v1\/token\?key=/);
  assert.equal(req!.body, 'grant_type=refresh_token&refresh_token=R1');
  assert.equal(store.c!.refreshToken, 'R2');
  assert.equal(store.c!.expiresAt, 1_000_000 + 3_600_000);
});

test('concurrent calls share one refresh', async () => {
  let calls = 0;
  const a = createAuth({ store: mem(conn(0)), now: () => 1_000_000, fetch: (async () => { calls++; await new Promise((r) => setTimeout(r, 10)); return tokenRes(); }) as unknown as typeof fetch });
  const r = await Promise.all([a.getIdToken(), a.getIdToken(), a.getIdToken()]);
  assert.equal(calls, 1);
  assert.ok(r.every((x) => x.idToken === 'NEW'));
});

test('dead refresh token clears the connection and throws NotConnected', async () => {
  for (const code of ['TOKEN_EXPIRED', 'INVALID_REFRESH_TOKEN', 'USER_NOT_FOUND']) {
    const store = mem(conn(0));
    const a = createAuth({ store, now: () => 5, fetch: (async () => new Response(JSON.stringify({ error: { message: code } }), { status: 400 })) as unknown as typeof fetch });
    await assert.rejects(a.getIdToken(), NotConnected);
    assert.equal(store.c, null);
  }
});

test('transient failure keeps the connection', async () => {
  const store = mem(conn(0));
  const a = createAuth({ store, now: () => 5, fetch: (async () => new Response('{}', { status: 503 })) as unknown as typeof fetch });
  await assert.rejects(a.getIdToken(), (e: Error) => !(e instanceof NotConnected) && /503/.test(e.message));
  assert.ok(store.c);
});

test('no connection -> NotConnected', async () => {
  await assert.rejects(createAuth({ store: mem(null) }).getIdToken(), NotConnected);
});

test('connect verifies by refreshing: saves on success, rejects bad token or uid mismatch, keeps the old connection', async () => {
  const store = mem(null);
  const ok = createAuth({ store, now: () => 1000, fetch: (async () => tokenRes()) as unknown as typeof fetch });
  await ok.connect('u', 'me@x', 'R1');
  assert.equal(store.c!.refreshToken, 'R2');
  const old = store.c;
  const bad = createAuth({ store, fetch: (async () => new Response(JSON.stringify({ error: { message: 'INVALID_REFRESH_TOKEN' } }), { status: 400 })) as unknown as typeof fetch });
  await assert.rejects(bad.connect('u', 'e', 'X'), BadConnection);
  await assert.rejects(ok.connect('other', 'e', 'R1'), BadConnection);
  assert.equal(store.c, old);
});

test('a refresh in flight while disconnect happens does not restore the connection', async () => {
  const store = mem(conn(0));
  let go!: () => void;
  const gate = new Promise<void>((r) => { go = r; });
  const a = createAuth({ store, now: () => 5, fetch: (async () => { await gate; return tokenRes(); }) as unknown as typeof fetch });
  const p = a.getIdToken();
  await new Promise((r) => setTimeout(r, 5));
  await a.disconnect();
  go();
  await assert.rejects(p, NotConnected);
  assert.equal(store.c, null);
});

test('a refresh in flight while connecting another account does not overwrite it, and the next call starts fresh', async () => {
  const store = mem(conn(0));
  let go!: () => void;
  const gate = new Promise<void>((r) => { go = r; });
  let n = 0;
  const a = createAuth({ store, now: () => 5, fetch: (async () => { if (n++ === 0) { await gate; return tokenRes(); } return tokenRes({ user_id: 'v', refresh_token: 'RV' }); }) as unknown as typeof fetch });
  const p = a.getIdToken();
  await new Promise((r) => setTimeout(r, 5));
  await a.connect('v', 'v@x', 'RX');
  go();
  await assert.rejects(p, NotConnected);
  assert.equal(store.c!.uid, 'v');
  assert.equal(store.c!.refreshToken, 'RV');
});
