import test from 'node:test';
import assert from 'node:assert/strict';
import { SITES, siteFor, providerOnSite } from '../src/sites.ts';

const cases: [string, string, string[]][] = [
  ['www.netflix.com', 'netflix', ['Netflix']],
  ['www.primevideo.com', 'prime', ['Amazon Prime Video', 'Amazon Video']],
  ['www.amazon.in', 'prime', ['Amazon Prime Video']],
  ['www.amazon.com', 'prime', ['Amazon Prime Video']],
  ['www.hotstar.com', 'hotstar', ['JioHotstar', 'Disney Plus Hotstar']],
  ['www.zee5.com', 'zee5', ['Zee5']],
  ['www.sonyliv.com', 'sonyliv', ['Sony LIV', 'SonyLIV']],
  ['tv.apple.com', 'apple', ['Apple TV', 'Apple TV Plus']],
  ['www.disneyplus.com', 'disney', ['Disney Plus']],
  ['mubi.com', 'mubi', ['MUBI']],
  ['play.max.com', 'max', ['Max', 'HBO Max']],
  ['www.hbomax.com', 'max', ['HBO Max']],
  ['www.hulu.com', 'hulu', ['Hulu']],
  ['www.crunchyroll.com', 'crunchyroll', ['Crunchyroll']],
  ['www.sunnxt.com', 'sunnxt', ['Sun Nxt', 'SunNXT']],
];

test('every site resolves by hostname and matches its provider names', () => {
  for (const [host, id, names] of cases) {
    const s = siteFor(host);
    assert.equal(s?.id, id, host);
    for (const n of names) assert.ok(providerOnSite(s!, n), `${n} on ${host}`);
  }
  assert.equal(new Set(cases.map((c) => c[1])).size, SITES.length);
});

test('non-matches', () => {
  assert.equal(siteFor('example.com'), null);
  assert.equal(siteFor('notnetflix.com'), null);
  assert.equal(siteFor('netflix.com.evil.io'), null);
  assert.ok(!providerOnSite(siteFor('www.disneyplus.com')!, 'Disney Plus Hotstar'));
  assert.ok(!providerOnSite(siteFor('www.netflix.com')!, 'Hulu'));
  assert.ok(!providerOnSite(siteFor('www.hbomax.com')!, 'Maxdome'));
});

test('searchUrl encodes the title', () => {
  assert.equal(siteFor('netflix.com')!.searchUrl('A & B'), 'https://www.netflix.com/search?q=A%20%26%20B');
});
