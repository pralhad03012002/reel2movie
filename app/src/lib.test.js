// Run: node --test web/lib.test.js
import test from 'node:test';
import assert from 'node:assert/strict';
import { extractUrl, httpsUrl, isReelUrl, providerSearchUrl } from './lib.js';

test('extractUrl', () => {
  const reel = 'https://www.instagram.com/reel/Cabc123/?igsh=xyz';
  assert.equal(extractUrl('', `Watch this! ${reel}. so good`, 'title'), reel);
  assert.equal(extractUrl(reel, 'ignored https://other.example'), reel);
  assert.equal(extractUrl(null, undefined, `(${reel})`), reel);
  // several links: the supported one wins; none supported: the first, so the caller can say so
  assert.equal(extractUrl(`https://linktr.ee/someone ${reel}`), reel);
  assert.equal(extractUrl('https://a.example/x https://b.example/y'), 'https://a.example/x');
  assert.equal(extractUrl('http://insecure.example/x', 'no link here'), null);
  assert.equal(extractUrl('https://a.example/' + 'x'.repeat(500)), null);
});

// Same cases as validateUrl in worker/pipeline.test.js.
test('isReelUrl', () => {
  for (const ok of [
    'https://www.instagram.com/reel/C8abc123/',
    'https://www.instagram.com/reels/C8abc123/',
    'https://www.instagram.com/someone/reel/C8abc123/',
    'https://instagram.com/p/C8abc123/',
    'https://www.instagram.com/tv/C8abc123/',
    'https://www.youtube.com/shorts/abcdefghijk',
    'https://www.tiktok.com/@someone/video/7300000000000000000',
    'https://www.tiktok.com/t/ZMabcdef/',
    'https://vm.tiktok.com/ZMabcdef/',
    'https://vt.tiktok.com/ZMabcdef/',
    // the worker strips query and fragment, so they do not matter
    'https://www.instagram.com/reel/C8abc123/?igsh=xyz#frag',
    'https://www.youtube.com/shorts/abcdefghijk?si=xyz&feature=share',
    'https://www.tiktok.com/@a/video/73?_r=1&_t=abc',
  ]) assert.equal(isReelUrl(ok), true, ok);
  for (const bad of [
    'http://www.instagram.com/reel/abc/',
    'https://evil.com/reel/abc/',
    'https://instagram.com.evil.com/reel/abc/',
    'https://evilinstagram.com/reel/abc/',
    'https://user:pass@www.instagram.com/reel/abc/',
    'https://www.instagram.com:8443/reel/abc/',
    'https://www.youtube.com/watch?v=abcdefghijk',
    'https://www.instagram.com/someone/',
    'https://www.instagram.com/accounts/login/?next=/reel/abc/',
    'https://www.instagram.com/stories/someone/123/',
    'https://www.instagram.com/reel/',
    'https://www.instagram.com/share/reel/BAabc123',
    'https://m.instagram.com/reel/abc/',
    'https://www.tiktok.com/@someone',
    'https://www.tiktok.com/login',
    'https://m.tiktok.com/@someone/video/7300000000000000000',
    'https://vm.tiktok.com/',
    'file:///etc/passwd',
    '--exec=touch /tmp/pwned',
    'not a url',
    '',
    null,
    42,
    'https://www.instagram.com/reel/' + 'a'.repeat(500),
  ]) assert.equal(isReelUrl(bad), false, String(bad));
});

test('httpsUrl', () => {
  assert.equal(httpsUrl('https://image.tmdb.org/p.jpg'), 'https://image.tmdb.org/p.jpg');
  for (const bad of ['http://x.example', 'javascript:alert(1)', ' https://x.example', '', null, 5, {}]) {
    assert.equal(httpsUrl(bad), null);
  }
});

test('providerSearchUrl', () => {
  const prime = 'https://www.primevideo.com/search/?phrase=Am%C3%A9lie%20%26%20Co';
  assert.equal(providerSearchUrl('Amazon Prime Video', 'Amélie & Co'), prime);
  assert.equal(providerSearchUrl('Amazon Prime Video with Ads', 'Amélie & Co'), prime);
  assert.equal(providerSearchUrl('MUBI Amazon Channel', 'Amélie & Co'), prime);
  assert.match(providerSearchUrl('Netflix basic with Ads', 'Up'), /^https:\/\/www\.netflix\.com\/search\?q=Up$/);
  assert.match(providerSearchUrl('JioHotstar', 'Up'), /hotstar\.com/);
  assert.match(providerSearchUrl('Disney Plus', 'Up'), /disneyplus\.com/);
  assert.match(providerSearchUrl('Max', 'Up'), /hbomax\.com/);
  // "max" must not match as a substring
  assert.match(providerSearchUrl('Cinemax', 'Up'), /^https:\/\/www\.google\.com\/search/);
  assert.equal(
    providerSearchUrl('Some New Service', 'Up?'),
    'https://www.google.com/search?q=watch%20Up%3F%20on%20Some%20New%20Service',
  );
});
