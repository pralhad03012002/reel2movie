import { type GenreSummary, type Movie, type SortKey } from './types';

/** "Today", fixed when the page loads so every screen agrees. */
export const REF_DATE = new Date();
const DAY = 86_400_000;

export interface Filters { minRating: 0 | 7 | 8; within: 0 | 7 | 30; mine: boolean }
export const NO_FILTERS: Filters = { minRating: 0, within: 0, mine: false };
export const activeFilterCount = (f: Filters) => (f.minRating ? 1 : 0) + (f.within ? 1 : 0) + (f.mine ? 1 : 0);

export const latestAt = (m: Movie) => m.recommendations.reduce((a, r) => Math.max(a, Date.parse(r.at) || 0), 0);

export function sortMovies(list: Movie[], key: SortKey): Movie[] {
  const pop = (a: Movie, b: Movie) => b.recommendations.length - a.recommendations.length;
  const rate = (a: Movie, b: Movie) => b.rating - a.rating;
  const at = key === 'recent' ? new Map(list.map((m) => [m, latestAt(m)])) : null;
  const cmp: Record<SortKey, (a: Movie, b: Movie) => number> = {
    popular: (a, b) => pop(a, b) || rate(a, b),
    rating: (a, b) => rate(a, b) || pop(a, b),
    recent: (a, b) => at!.get(b)! - at!.get(a)! || pop(a, b) || rate(a, b),
    newest: (a, b) => b.year - a.year || pop(a, b) || rate(a, b),
  };
  return [...list].sort((a, b) => cmp[key](a, b) || a.title.localeCompare(b.title));
}

export function filterMovies(list: Movie[], f: Filters, myServices: readonly string[] = []): Movie[] {
  if (!activeFilterCount(f)) return list;
  const since = REF_DATE.getTime() - f.within * DAY;
  return list.filter((m) => m.rating >= f.minRating && (!f.within || latestAt(m) >= since) && (!f.mine || m.providers.some((p) => myServices.includes(p.name))));
}

/** Genre tiles: busiest first, three posters each. */
export function buildGenres(movies: Movie[]): GenreSummary[] {
  const by = new Map<string, Movie[]>();
  for (const m of movies) for (const g of m.genres) by.set(g, [...(by.get(g) ?? []), m]);
  return [...by].map(([name, ms]) => ({ name, count: ms.length, posters: ms.slice(0, 5).map((m) => m.poster) })).sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
}

/** Recommended in the last `days` days before REF_DATE. */
export const isFresh = (m: Movie, days = 14) => latestAt(m) >= REF_DATE.getTime() - days * DAY;

/** lowercase, accent-insensitive */
export const norm = (s: string) => s.normalize('NFD').replace(/\p{M}/gu, '').toLowerCase();
const WORD = /[\p{L}\p{N}\p{M}]+/gu;
export const queryTokens = (q: string) => norm(q).match(WORD) ?? [];
const wordHit = (text: string, tokens: string[]) => {
  const words = norm(text).match(WORD) ?? [];
  return tokens.some((t) => words.some((w) => w.startsWith(t)));
};

export interface Match { label: string; text: string }
export interface Hit { movie: Movie; match: Match }

/** Every token must word-prefix-match some field; match = why the first token matched (priority order). */
export function searchMovies(movies: Movie[], query: string): Hit[] {
  const tokens = queryTokens(query);
  if (!tokens.length) return [];
  const first = tokens.slice(0, 1);
  const out: Hit[] = [];
  for (const movie of movies) {
    const fields: Match[] = [
      { label: 'Title', text: movie.title },
      ...movie.cast.map((c) => ({ label: 'Cast', text: c.name })),
      ...(movie.director ? [{ label: 'Director', text: movie.director }] : []),
      ...movie.genres.map((g) => ({ label: 'Genre', text: g })),
      ...(movie.year ? [{ label: 'Year', text: String(movie.year) }] : []),
      ...movie.recommendations.flatMap((r) => [
        { label: 'Recommended by', text: r.handle },
        { label: 'Recommended by', text: r.creator },
      ]),
    ];
    if (!tokens.every((t) => fields.some((f) => wordHit(f.text, [t])))) continue;
    out.push({ movie, match: fields.find((f) => wordHit(f.text, first))! });
  }
  return out;
}

/** [start,end) ranges in the ORIGINAL text covered by word prefixes of tokens. */
export function highlightRanges(text: string, tokens: string[]): [number, number][] {
  const r: [number, number][] = [];
  for (const m of text.matchAll(WORD)) {
    const w = norm(m[0]);
    const t = tokens.filter((t) => w.startsWith(t)).sort((a, b) => b.length - a.length)[0];
    if (!t) continue;
    // token length is in normalised units; walk original chars so accents/combining marks don't shift the span
    let n = 0, end = m.index!;
    for (const ch of m[0]) { if (n >= t.length && norm(ch)) break; n += norm(ch).length; end += ch.length; }
    r.push([m.index!, end]);
  }
  return r;
}
