import test from 'node:test';
import assert from 'node:assert/strict';
import { decodeValue, decodeFields, listMovies, getSettings, setWatched } from '../src/firestore.ts';
import { toMovie } from '../../app/src/movie.ts';

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

test('decoder handles every type', () => {
  assert.equal(decodeValue({ stringValue: 'a' }), 'a');
  assert.equal(decodeValue({ integerValue: '27205' }), 27205);
  assert.equal(decodeValue({ doubleValue: 8.4 }), 8.4);
  assert.equal(decodeValue({ booleanValue: false }), false);
  assert.equal(decodeValue({ nullValue: null }), null);
  assert.equal(decodeValue({ timestampValue: '2025-01-02T03:04:05.123Z' }), '2025-01-02T03:04:05.123Z');
  assert.deepEqual(decodeValue({ arrayValue: {} }), []);
  assert.deepEqual(decodeFields({
    cast: { arrayValue: { values: [{ mapValue: { fields: { name: { stringValue: 'X' }, n: { integerValue: '3' } } } }] } },
    providers: { mapValue: { fields: { IN: { mapValue: { fields: { stream: { arrayValue: { values: [] } } } } } } } },
    empty: { mapValue: {} },
  }), { cast: [{ name: 'X', n: 3 }], providers: { IN: { stream: [] } }, empty: {} });
});

test('listMovies paginates, takes the id from the name and sorts newest first', async () => {
  const urls: string[] = [];
  const doc = (id: string, at: string) => ({ name: `projects/p/databases/(default)/documents/users/u/movies/${id}`, fields: { updatedAt: { timestampValue: at }, title: { stringValue: id } } });
  const f = (async (url: string, init: RequestInit) => {
    urls.push(url);
    assert.equal((init.headers as Record<string, string>).Authorization, 'Bearer TOK');
    return url.includes('pageToken=P2')
      ? json({ documents: [doc('movie_2', '2025-02-01T00:00:00Z')] })
      : json({ documents: [doc('movie_1', '2025-01-01T00:00:00Z')], nextPageToken: 'P2' });
  }) as unknown as typeof fetch;
  const out = await listMovies('u', 'TOK', f);
  assert.deepEqual(out.map((m) => m.id), ['movie_2', 'movie_1']);
  assert.equal(urls.length, 2);
  assert.match(urls[0], /\/users\/u\/movies\?pageSize=300$/);
});

test('errors carry the status only', async () => {
  const f = (async () => json({}, 403)) as unknown as typeof fetch;
  await assert.rejects(listMovies('uid-secret', 'TOKSECRET', f), (e: Error) => /403/.test(e.message) && !/secret/i.test(e.message));
});

test('getSettings: defaults on 404, merges stored fields', async () => {
  const def = { region: 'IN', services: [], localStt: false };
  assert.deepEqual(await getSettings('u', 't', (async () => json({}, 404)) as unknown as typeof fetch), def);
  const f = (async () => json({ fields: { region: { stringValue: 'US' }, services: { arrayValue: { values: [{ stringValue: 'Netflix' }] } } } })) as unknown as typeof fetch;
  assert.deepEqual(await getSettings('u', 't', f), { region: 'US', services: ['Netflix'], localStt: false });
  await assert.rejects(getSettings('u', 't', (async () => json({}, 500)) as unknown as typeof fetch), /500/);
});

test('setWatched sends a masked PATCH', async () => {
  let seen: { url: string; init: RequestInit } | undefined;
  await setWatched('u', 'TOK', 'movie_1', true, (async (url: string, init: RequestInit) => { seen = { url, init }; return json({}); }) as unknown as typeof fetch);
  assert.match(seen!.url, /\/users\/u\/movies\/movie_1\?updateMask\.fieldPaths=watched/);
  assert.equal(seen!.init.method, 'PATCH');
  assert.deepEqual(JSON.parse(seen!.init.body as string), { fields: { watched: { booleanValue: true } } });
  await assert.rejects(setWatched('u', 't', 'x', true, (async () => json({}, 403)) as unknown as typeof fetch), /403/);
});

test('toMovie accepts decoded (ISO string) createdAt', () => {
  const m = toMovie({ title: 'T', createdAt: '2025-01-01T00:00:00Z', sources: [{ creatorHandle: 'a', postUrl: 'https://x.y/z' }], providers: { IN: { stream: [{ name: 'Netflix' }], rent: [] } }, posterUrl: 'https://i/p.jpg' }, 'movie_1', 'IN');
  assert.equal(m.recommendations[0].at, '2025-01-01T00:00:00Z');
  assert.deepEqual(m.providers, [{ name: 'Netflix', kind: 'stream' }]);
});
