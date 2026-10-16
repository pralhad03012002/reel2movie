# Execution Flow — Reel → Movie Recommendations

Linear walkthrough of what happens between "user gives us a reel link" and
"we return resolved movie recommendations." Each numbered step names the module
responsible (see the task breakdown produced via the planning pass for exact
module boundaries).

```
Reel URL
   │
   ▼
[1] Platform detect + ingest
   - Identify platform (Instagram / TikTok / YouTube Shorts / other)
   - Fetch: video file, caption text, comment list, creator account id
   - Fail fast with a clear error if the link is private/unreachable/unsupported
   │
   ▼
[2] Caption-based extraction
   - Parse caption text for movie-title-shaped candidates (+ year if present)
   - If ≥1 confident candidate → go to [5] (skip comment + visual steps)
   - Else → go to [3]
   │
   ▼
[3] Creator-comment-based extraction
   - Filter comment list to: author == creator account, is_reply == false
   - Parse those comment(s) the same way captions are parsed
   - If ≥1 confident candidate → go to [5]
   - Else → go to [4]
   │
   ▼
[4] Visual frame extraction (fallback)
   - Get reel duration; pick N equally-spaced timestamps (not a dense scan)
   - Extract a frame at each timestamp
   - Run poster/title-card detection per frame → candidate title string(s)
   - If ≥1 candidate → go to [5]
   - Else → return "no recommendation found" with the three sources' empty results
   │
   ▼
[5] TMDB resolution
   - For each raw candidate string: query TMDB search
   - Score results (TMDB relevance + title-similarity check); keep best per candidate
   - Attach source tag (caption | creator_comment | frame_visual) + confidence
   │
   ▼
[6] Aggregate + de-duplicate
   - Merge candidates that resolved to the same TMDB id
   - Sort by confidence
   │
   ▼
Output: recommendations[] (see brainstorm.md for the JSON shape)
```

## Fallthrough rule

Steps 2 → 3 → 4 are a strict waterfall: a later step only runs if the prior step
produced nothing confident. This keeps the pipeline cheap for the common case
(caption already says the titles) and reserves frame sampling — the most
expensive step — for reels that rely purely on visuals.

## Error handling, high level

- Unreachable/unsupported link → fail immediately, don't attempt any extraction.
- A source step fails internally (e.g. comments API errors) → treat as "empty",
  fall through to the next step, don't abort the whole pipeline.
- TMDB resolution finds no match for a candidate → drop that candidate, keep
  others; if none resolve, return the raw candidate strings with no TMDB data
  rather than silently returning nothing.
