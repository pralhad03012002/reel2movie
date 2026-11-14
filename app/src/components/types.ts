export type Provider = { name: string; kind: 'stream' | 'rent' };

export interface Recommendation {
  creator: string; // display name of an (invented) influencer
  handle: string; // e.g. "@midnight.matinee"
  at: string; // ISO date the reel recommended it
  quote?: string; // short line from the reel
  postUrl?: string; // the reel itself
}

export interface Movie {
  id: string; // "movie_27205" | "tv_1396"
  tmdbId: number;
  mediaType: 'movie' | 'tv';
  title: string;
  year: number; // 0 = unknown
  runtimeMin: number | null; // tv: typical episode length
  seasons?: number; // tv only
  overview: string;
  tagline?: string;
  rating: number; // TMDB vote_average, 0-10, one decimal
  genres: string[]; // display names, e.g. "Sci-Fi"
  director: string | null; // tv: creator
  cast: { name: string; character: string }[]; // top 6
  poster: string; // image URL
  backdrop: string; // image URL ('' = none)
  trailerKey: string | null; // YouTube video id
  providers: Provider[]; // India
  recommendations: Recommendation[]; // length = how many influencers recommended it
  watched: boolean;
}

export type SortKey = 'popular' | 'rating' | 'recent' | 'newest';
export const SORT_LABELS: Record<SortKey, string> = {
  popular: 'Most recommended',
  rating: 'Highest rated',
  recent: 'Recently recommended',
  newest: 'Newest release',
};

export interface GenreSummary { name: string; count: number; posters: string[] }
export const ALL_GENRES = 'All';
