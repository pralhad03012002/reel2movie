// Pure mapping from a Firestore movie doc (worker/pipeline.js toMovieDoc) to the UI `Movie`. No Firebase imports: shared with the extension.
import { httpsUrl } from './lib.js';
import type { Movie, Provider, Recommendation } from './components/types';

export type Raw = Record<string, any>; // a Firestore movie doc; written by worker/pipeline.js toMovieDoc

const trailerKey = (url: unknown) => {
  try { return new URL(String(url)).searchParams.get('v'); } catch { return null; }
};

export function toMovie(raw: Raw, id: string, region: string): Movie {
  const created = raw.createdAt as { toDate(): Date } | string | undefined; // Firestore Timestamp, or an ISO string decoded from REST
  const fallbackAt = typeof created === 'string' ? created : created?.toDate().toISOString() ?? new Date().toISOString();
  // One entry per creator (the latest reel), so "recommended by N" counts people, not reels.
  const byCreator = new Map<string, Recommendation>();
  for (const s of (raw.sources ?? []) as Raw[]) {
    const handle = s.creatorHandle ? `@${s.creatorHandle}` : '';
    const rec: Recommendation = { creator: s.creatorHandle || 'A saved reel', handle, at: s.at ?? fallbackAt, quote: s.evidence || undefined, postUrl: httpsUrl(s.postUrl) ?? undefined };
    const key = handle || s.postUrl;
    const seen = byCreator.get(key);
    if (!seen || rec.at >= seen.at) byCreator.set(key, rec);
  }
  const p = raw.providers?.[region] as { stream?: { name: string }[]; rent?: { name: string }[] } | undefined;
  const providers: Provider[] = [
    ...(p?.stream ?? []).map((x) => ({ name: x.name, kind: 'stream' as const })),
    ...(p?.rent ?? []).map((x) => ({ name: x.name, kind: 'rent' as const })),
  ];
  const poster = httpsUrl(raw.posterUrl) ?? '';
  return {
    id,
    tmdbId: raw.tmdbId,
    mediaType: raw.mediaType,
    title: raw.title ?? '',
    year: raw.year ?? 0,
    runtimeMin: raw.runtimeMin ?? null,
    seasons: raw.seasons ?? undefined,
    overview: raw.overview ?? '',
    tagline: raw.tagline || undefined,
    rating: Math.round((raw.rating ?? 0) * 10) / 10,
    genres: raw.genres ?? [],
    director: raw.director ?? null,
    cast: raw.cast ?? [],
    poster,
    backdrop: httpsUrl(raw.backdropUrl) ?? poster,
    trailerKey: trailerKey(raw.trailerUrl),
    providers,
    recommendations: [...byCreator.values()],
    watched: !!raw.watched,
  };
}
