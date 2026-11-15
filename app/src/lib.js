// Pure helpers, no browser or Firebase imports, so `node --test` can load this file.

// From the https URLs found in the given strings (share params: url, text, title): the first supported
// reel link, else the first URL, so the caller can say it is unsupported.
// Instagram puts the link in `text`, sometimes with words around it.
export function extractUrl(...parts) {
  const urls = parts.flatMap((part) => (part || '').match(/https:\/\/[^\s<>"']+/g) || [])
    .map((url) => url.replace(/[.,;:!?)\]]+$/, ''))
    .filter((url) => url.length <= 500);
  return urls.find(isReelUrl) || urls[0] || null;
}

// Same allowlist as validateUrl in worker/pipeline.js, so an unsupported link is refused when queued
// rather than hours later. Convenience only: the worker is the trust boundary.
// Copied from LINKS there ([host, path] per host family); keep the two in step.
const LINKS = [
  [/^(www\.)?instagram\.com$/, /^\/((?!share\/)[^/]+\/)?(reels?|p|tv)\/[^/]+\/?$/],
  [/^(www\.|m\.)?youtube\.com$/, /^\/shorts\/[^/]+\/?$/],
  [/^www\.tiktok\.com$/, /^\/(@[^/]+\/video\/\d+|t\/\w+)\/?$/],
  [/^(vm|vt)\.tiktok\.com$/, /^\/\w+\/?$/],
];
export function isReelUrl(raw) {
  if (typeof raw !== 'string' || raw.length > 500) return false;
  let u;
  try {
    u = new URL(raw.trim());
  } catch {
    return false;
  }
  return u.protocol === 'https:' && !u.username && !u.password && !u.port
    && LINKS.some(([host, path]) => host.test(u.hostname) && path.test(u.pathname));
}

// Firestore URLs are only usable as href/src when https.
export function httpsUrl(u) {
  return typeof u === 'string' && u.startsWith('https://') ? u : null;
}

// [pattern tested against the lowercased, alphanumeric-only TMDB provider name, search URL prefix].
// First match wins: "amazon" and "appletv" come first so "MUBI Amazon Channel" opens Prime Video,
// and "hotstar" precedes "disney" so "Disney+ Hotstar" opens Hotstar.
// ponytail: web search URLs only (Android opens the installed app when it claims the link);
// per-service app deep links if that proves unreliable.
const SERVICES = [
  [/amazon|primevideo/, 'https://www.primevideo.com/search/?phrase='],
  [/appletv/, 'https://tv.apple.com/search?term='],
  [/netflix/, 'https://www.netflix.com/search?q='],
  [/hotstar/, 'https://www.hotstar.com/in/explore?search_query='],
  [/zee5/, 'https://www.zee5.com/search?q='],
  [/sonyliv/, 'https://www.sonyliv.com/search?searchTerm='],
  [/youtube/, 'https://www.youtube.com/results?search_query='],
  [/googleplay|googletv/, 'https://play.google.com/store/search?c=movies&q='],
  [/mubi/, 'https://mubi.com/en/search/films?query='],
  [/disney/, 'https://www.disneyplus.com/browse/search?q='],
  [/^max$|hbomax/, 'https://www.hbomax.com/search/result?q='],
  [/hulu/, 'https://www.hulu.com/search?q='],
  [/crunchyroll/, 'https://www.crunchyroll.com/search?q='],
  [/sunnxt/, 'https://www.sunnxt.com/search?q='],
];

export function providerSearchUrl(name, title) {
  const key = String(name).toLowerCase().replace(/[^a-z0-9]/g, '');
  const hit = SERVICES.find(([re]) => re.test(key));
  return hit
    ? hit[1] + encodeURIComponent(title)
    : 'https://www.google.com/search?q=' + encodeURIComponent(`watch ${title} on ${name}`);
}

/**
 * The official extension id. It is derived from the `key` field in extension/manifest.json
 * (first 32 hex of SHA-256 of the public key DER, 0-f mapped to a-p), so an unpacked build has this
 * id everywhere. A Chrome Web Store build gets a different id: replace this value with it then.
 * extension/test/extension-id.test.ts keeps the two in sync.
 */
export const EXTENSION_ID = 'ckmhjoignkokcghphackjbklieekdpmm';

/** `?connect=<extensionId>` -> the id only if it is exactly EXTENSION_ID, else ''. */
export const parseConnectParam = (search) => {
  const id = new URLSearchParams(search).get('connect') ?? '';
  return id === EXTENSION_ID ? id : '';
};
