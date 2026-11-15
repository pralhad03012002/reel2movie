import test from 'node:test';
import assert from 'node:assert/strict';
import { parseConnect, WEB_ORIGIN } from '../src/connect.ts';

const good = { type: 'connect', uid: 'u1', refreshToken: 'tok', email: 'a@b.c' };

test('accepts the web app origin (origin or url)', () => {
  assert.deepEqual(parseConnect(good, { origin: WEB_ORIGIN }), good);
  assert.deepEqual(parseConnect(good, { url: WEB_ORIGIN + '/?connect=x' }), good);
  assert.equal(parseConnect({ ...good, email: undefined }, { origin: WEB_ORIGIN })?.email, '');
});

test('rejects other origins', () => {
  for (const o of ['https://evil.example', 'http://reelpicks-32e42.web.app', 'https://reelpicks-32e42.web.app.evil.io', 'https://reelpicks-32e42.firebaseapp.com'])
    assert.equal(parseConnect(good, { origin: o }), null, o);
  assert.equal(parseConnect(good, {}), null);
  assert.equal(parseConnect(good, { url: 'not a url' }), null);
});

test('rejects bad shapes and sizes', () => {
  const s = { origin: WEB_ORIGIN };
  for (const m of [null, 'x', {}, { ...good, type: 'other' }, { ...good, uid: 5 }, { ...good, uid: '' }, { ...good, uid: 'x'.repeat(129) },
    { ...good, refreshToken: {} }, { ...good, refreshToken: 'x'.repeat(4097) }, { ...good, email: 7 }, { ...good, email: 'x'.repeat(321) }])
    assert.equal(parseConnect(m, s), null, JSON.stringify(m)?.slice(0, 40));
});
