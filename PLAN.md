# ReelPicks — build plan

A movie-recommendation extractor modelled on SaveToList. Share a reel from your phone; the movies
it recommends appear in your account, on phone and desktop, each with buttons that open the
streaming service that has it.

## 1. What SaveToList does (from the APK, v1.0.4)

| Step | SaveToList | Evidence |
|---|---|---|
| Receive share | `ShareActivity` reads `EXTRA_TEXT` / `EXTRA_STREAM` | `ShareActivity.onCreate` |
| Queue | Firebase callable `createPendingShare` / `saveSharedLink` with `{url, platform, source:"android_share_target", listId}`; returns `status:"queued"` | `ni/o7.smali` |
| Extract | **Server-side, not in the APK.** | no extraction code in dex |
| Progress | Client watches `processingPosts` docs: `status`, `stage`, `label`, `postUrl`, `creatorHandle`, `thumbnailUrl`, `updatedAt` | `ni/k4.smali` |
| Result | `savedItems` + `savedSources`; movie items carry `title, year, director, cast, genres, imdbRating, poster, trailerUrl, streamingUrl, caption, evidence_from_post` | `oi/g1.smali`, `vi/a.smali` |
| Account | Firebase Auth + Firestore | manifest, dex |

We copy the shape: share → queued doc → async worker → enriched items synced to the account.
The extraction step is our own, because theirs is not observable.

**Cut from SaveToList:** lists and smart lists, places/maps, recipes, products, books, music,
reminders, push notifications, paywall, analytics, screenshots, Instagram DM/mention saving,
public lists, in-app video player.

## 2. Decisions (from the interview)

- **App:** one installable web app (PWA). On Android it appears in Instagram's share sheet. On
  desktop the same account shows the same list and opens OTT sites in the browser.
- **Accounts/storage:** Firebase Auth (Google sign-in) + Firestore. Hosting: Firebase Hosting.
- **Worker:** a Node program on the owner's Mac. Reels shared while it is off wait as `queued`.
- **Extraction:** yt-dlp (audio + caption) → ElevenLabs speech-to-text → Gemini picks titles from
  transcript + caption → TMDB confirms and enriches.
- **Region:** India by default, changeable per user.
- **OTT buttons:** one per service, opening that service's search for the title.
- **Features:** watched / want-to-watch, "my services" filter, source reel link, poster + rating +
  genres + overview + trailer.

## 3. Architecture

```
phone/desktop PWA ──write──▶ Firestore users/{uid}/processingPosts/{id}  (status: queued)
                                        │ collectionGroup listener
                                        ▼
                              worker on Mac (firebase-admin)
        yt-dlp ─▶ ElevenLabs STT ─▶ Gemini ─▶ TMDB search + details/providers/videos
                                        │
                                        ▼
PWA ◀──live snapshot── Firestore users/{uid}/movies/{movie|tv}_{tmdbId}
```

No Cloud Functions (keeps Firebase on the free plan). The client writes the queue doc directly;
security rules restrict what it may write.

## 4. Data contract (both subtasks must follow this exactly)

`users/{uid}` — settings, written by client
```
{ region: "IN", services: ["Netflix", "Amazon Prime Video"] }   // services = TMDB provider_name values
```

`users/{uid}/processingPosts/{autoId}` — created by client, then updated only by worker
```
client create: { url: string (<= 500 chars), source: "share_target" | "paste",
                 status: "queued", createdAt: serverTimestamp }
worker adds:   { status: "processing" | "done" | "failed" (or back to "queued" for a retry),
                 stage: "downloading" | "transcribing" | "extracting" | "matching",
                 error?: string, creatorHandle?: string,
                 attempts: number (claims so far; fails at the 4th),
                 updatedAt: serverTimestamp }
```
The client may delete any of its own processingPosts docs but not update them.

`users/{uid}/movies/{docId}` where `docId = "{mediaType}_{tmdbId}"` — created by worker
```
{ tmdbId: number, mediaType: "movie" | "tv", title, year: number|null, overview,
  posterUrl: string|null, rating: number (TMDB vote_average), genres: string[],
  trailerUrl: string|null (YouTube), 
  providers: { [countryCode]: { stream: [{id, name}], rent: [{id, name}] } },
      // stream = flatrate + free + ads ; rent = rent + buy ; de-duplicated by id
  sources: [{ postUrl, creatorHandle, evidence }],   // arrayUnion; evidence = short quote from the reel
  watched: false, createdAt, updatedAt }
```
Worker writes in a transaction (create, or `update` on an existing doc so `providers` is replaced
rather than deep-merged) and must NOT overwrite `watched` or `createdAt` on an existing doc. The client may update only `watched`, and may delete a movie.

## 5. Subtasks

### Subtask A — worker (`worker/`)
Node ≥ 22, ESM, only dependency `firebase-admin`. Built-in `fetch`, `node --env-file=.env`,
`node:test`.
- `worker/setup.sh`: downloads the standalone `yt-dlp_macos` release binary into `worker/bin/`.
- `worker/.env.example`: `TMDB_API_KEY`, `ELEVENLABS_API_KEY`, `GEMINI_API_KEY`, `GEMINI_MODEL`,
  `GOOGLE_APPLICATION_CREDENTIALS` (path to the service-account JSON).
- `worker/index.js`: `collectionGroup("processingPosts").where("status","==","queued")` listener.
  Claims a post in a transaction (queued → processing) so two workers never double-process.
  One post at a time. A network failure or timeout puts the post back to `queued` (up to the attempts
  cap); any other error → `status:"failed"` with a short `error`. The worker keeps running.
- `worker/pipeline.js`: pure-ish steps, each taking injected `fetch` where it calls the network:
  1. `validateUrl` — trust boundary. https only; Instagram reel/post/tv, YouTube Shorts and TikTok video links (incl. vm./vt. short links). Reject otherwise.
  2. `download` — `execFile` (no shell) yt-dlp with `--` before the URL, `-f ba/w` (audio-only, else the
     smallest pre-merged file), max filesize and timeout, into a temp dir that is always removed.
     Returns the audio bytes (a Blob) + filename, caption (title + `description`) and `creatorHandle`.
  3. `transcribe` — ElevenLabs speech-to-text. Empty/failed transcript is not fatal if a caption exists.
  4. `extractTitles` — Gemini, JSON-schema output `[{title, year|null, mediaType, evidence}]`.
     Prompt: list only films/series the reel actually recommends or names; no guesses. The caption
     and transcript are untrusted data, fenced as such in the prompt.
  5. `matchTmdb` — search movie and tv by title, with and without the year; pick by same title, year within one and votes, then details with
     `append_to_response=watch/providers,videos`. Drop titles with no TMDB match. De-duplicate.
  6. `toMovieDoc` — shape per the contract above.
- `worker/pipeline.test.js`: `node --test`. Covers `validateUrl` (accept/reject), `toMovieDoc`
  provider merging, and the full pipeline with a stubbed `fetch`.
- API details (endpoints, current model names, field names) must be verified against the live
  docs, not written from memory.

### Subtask B — web app (`web/`, `firestore.rules`, `firebase.json`)
Static files, no build step, no framework. Firebase JS SDK as ES modules from the gstatic CDN.
- `web/index.html`, `web/app.js`, `web/style.css`, `web/manifest.webmanifest`, `web/sw.js`
  (minimal, for installability), `web/firebase-config.js` (placeholder config object), icons.
- Manifest `share_target` (GET, params `title/text/url`). On load, if share params are present,
  pull the first URL out of `url`/`text`, create the queued post, then clean the address bar.
- Signed out: Google sign-in button. Signed in:
  - paste-a-link box (desktop path);
  - "Processing" strip: live queued/processing/failed posts with stage text; dismiss failed ones;
  - movie grid: poster, title, year, rating, genres, overview, trailer link, source reel link(s)
    with creator handle, watched toggle, delete;
  - per-movie OTT buttons for the user's region, the user's own services first and highlighted;
    each opens that service's search URL for the title in a new tab (`rel="noopener"`). Unknown
    service → web search for "watch {title} on {service}". Rent/buy services shown smaller.
  - filters: All / Want to watch / Watched, and "On my services";
  - settings: region select, and a checklist of services (built from the providers seen in the
    user's movies for that region).
- All Firestore strings rendered with `textContent`, never `innerHTML`. URLs from Firestore are
  only used as `href`/`src` if they start with `https://`.
- `firestore.rules`: users read/write only their own subtree, with the per-collection limits in §4
  (post create must be `status == "queued"` with a short string `url`; posts not updatable by the
  client; movies: client may only change `watched`, or delete; no client create).
- `firebase.json`: hosting `web/`, rules file, and the collection-group index for
  `processingPosts.status` (`firestore.indexes.json`).
- Works at phone width and desktop width; light and dark.

### Subtask C — docs (`README.md`)
Setup steps for the owner: create Firebase project, enable Google sign-in and Firestore, paste web
config, download service-account key, fill `.env`, run `setup.sh`, deploy, start the worker,
install the PWA on the phone.

## 6. Process

Each subtask: a coding agent writes it → a separate review agent runs `/code-review` and
`/ponytail:ponytail-review` on it → a new coding agent fixes the findings → review again, until a
review comes back clean. A and B run in parallel; C after both.

## 7. Needed from the owner before the first real run

1. TMDB API key  2. ElevenLabs API key  3. Gemini API key (free, Google AI Studio)
4. Firebase project: web config object + service-account JSON
