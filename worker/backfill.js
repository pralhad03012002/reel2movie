// One-off: adds the fields newer than your first movies (cast, director, backdrop, runtime, tagline) to
// movies already saved. Run: npm run backfill. Safe to repeat; only those fields are written.
import { initializeApp } from "firebase-admin/app";
import { getFirestore } from "firebase-admin/firestore";
import { DETAILS_APPEND, toMovieDoc } from "./pipeline.js";

if (!process.env.TMDB_API_KEY) throw new Error("TMDB_API_KEY is not set (see .env.example)");
initializeApp();
const key = process.env.TMDB_API_KEY;
const v4 = key.startsWith("eyJ"); // same test as pipeline.js tmdb()

let done = 0;
for (const doc of (await getFirestore().collectionGroup("movies").get()).docs) {
  const m = doc.data();
  if (m.cast) continue; // already has the new fields
  const qs = new URLSearchParams({ append_to_response: DETAILS_APPEND, ...(!v4 && { api_key: key }) });
  const res = await fetch(`https://api.tmdb.org/3/${m.mediaType}/${m.tmdbId}?${qs}`, { headers: v4 ? { Authorization: `Bearer ${key}` } : {} });
  if (!res.ok) { console.error(`${doc.ref.path}: TMDB ${res.status}`); continue; }
  const { backdropUrl, tagline, runtimeMin, seasons, director, cast } = toMovieDoc(await res.json(), m.mediaType, {});
  await doc.ref.update({ backdropUrl, tagline, runtimeMin, seasons, director, cast });
  done++;
}
console.log(`Updated ${done} movie(s).`);
