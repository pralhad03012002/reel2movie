// The streaming sites the extension runs on. providerPattern is tested against a TMDB provider name lowercased with
// non-alphanumerics removed (same convention as app/src/lib.js SERVICES, whose search URLs these reuse).
export interface Site { id: string; label: string; hosts: string[]; providerPattern: RegExp; searchUrl(title: string): string }

const site = (id: string, label: string, hosts: string[], providerPattern: RegExp, search: string): Site =>
  ({ id, label, hosts, providerPattern, searchUrl: (t) => search + encodeURIComponent(t) });

export const SITES: Site[] = [
  site('prime', 'Prime Video', ['primevideo.com', 'amazon.in', 'amazon.com'], /amazon|primevideo/, 'https://www.primevideo.com/search/?phrase='),
  site('apple', 'Apple TV', ['tv.apple.com'], /appletv/, 'https://tv.apple.com/search?term='),
  site('netflix', 'Netflix', ['netflix.com'], /netflix/, 'https://www.netflix.com/search?q='),
  site('hotstar', 'Hotstar', ['hotstar.com'], /hotstar/, 'https://www.hotstar.com/in/explore?search_query='),
  site('zee5', 'ZEE5', ['zee5.com'], /zee5/, 'https://www.zee5.com/search?q='),
  site('sonyliv', 'SonyLIV', ['sonyliv.com'], /sonyliv/, 'https://www.sonyliv.com/search?searchTerm='),
  site('mubi', 'MUBI', ['mubi.com'], /mubi/, 'https://mubi.com/en/search/films?query='),
  site('disney', 'Disney+', ['disneyplus.com'], /^(?!.*hotstar).*disney/, 'https://www.disneyplus.com/browse/search?q='), // "Disney Plus Hotstar" is Hotstar
  site('max', 'Max', ['max.com', 'hbomax.com'], /^max$|hbomax/, 'https://www.hbomax.com/search/result?q='),
  site('hulu', 'Hulu', ['hulu.com'], /hulu/, 'https://www.hulu.com/search?q='),
  site('crunchyroll', 'Crunchyroll', ['crunchyroll.com'], /crunchyroll/, 'https://www.crunchyroll.com/search?q='),
  site('sunnxt', 'Sun NXT', ['sunnxt.com'], /sunnxt/, 'https://www.sunnxt.com/search?q='),
];

export function siteFor(hostname: string): Site | null {
  const h = hostname.toLowerCase().replace(/\.$/, '');
  return SITES.find((s) => s.hosts.some((d) => h === d || h.endsWith('.' + d))) ?? null;
}

export const providerOnSite = (site: Site, providerName: string): boolean =>
  site.providerPattern.test(providerName.toLowerCase().replace(/[^a-z0-9]/g, ''));
