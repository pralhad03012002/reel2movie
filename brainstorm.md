# Brainstorm — Movie Recommendation Reels Extraction

## Problem

Given a link to a short-form video ("reel" — Instagram Reels, TikTok, YouTube Shorts),
automatically identify which movie(s) the reel is recommending/discussing, and resolve
each to a canonical record (title, year, TMDB ID, poster, overview) via TMDB.

## Scope (v1)

- Output: a title **name + year** per recommendation, resolved against TMDB.
  Both movies and TV shows are valid recommendation targets (see "Follow-up"
  in `PROGRESS.md`: a reel can recommend either, and resolving against
  movies only let an unrelated movie win over the actually-correct TV show
  when both happened to share a title) — the TMDB resolution step searches
  both and the output says which (`media_type`).
- Single reel in, one or more recommendations (movie or TV) out.
- Not in scope for v1: batch processing many reels, a UI — just the
  extraction pipeline as an importable/CLI module.

## Signal sources, in priority order

The pipeline checks sources in this order and stops as soon as a source yields a
confident match, falling through to the next source only when the current one is
empty or low-confidence. Rationale: caption and creator comments are explicit,
author-authored text — cheapest and most reliable. Visual frame analysis is the
expensive, noisier fallback for reels that rely on on-screen title cards/posters
instead of text.

1. **Caption** — the post's own caption/description text.
2. **Creator's own top-level comment** — comments authored by the same creator
   account as the post, excluding replies (a creator often can't fit all titles in
   the caption and lists them in a pinned/first-party comment instead). Replies are
   excluded because they're frequently addressed to a specific commenter ("yes it's
   at 0:32") rather than a canonical list.
3. **Frame sampling** — N equally-spaced frames across the reel's duration (not a
   dense scan) are extracted and checked for movie posters / on-screen title text.
   This is the fallback when neither text source yields a usable title.

## Known hard cases / edge cases

- Multiple movies in one reel (ranked list reels, "5 movies like X").
- Non-English titles, re-releases, remakes (same title/different year).
- Posters that are partially occluded, stylized, or fan-made (not the official
  TMDB poster art).
- Frames showing an actor or a scene without a poster/title card at all (false
  negative for visual source, not a bug).
- Captions/comments that *mention* a movie only to say "not as good as X" — i.e.
  text contains a title but it isn't a recommendation. v1 does not attempt
  sentiment/intent filtering — flagging this as a known limitation, not solving it.
- Ambiguous short titles ("It", "Up", "Her") that need the year or extra context to
  disambiguate in TMDB search.

## Candidate resolution

Every candidate title string (from whichever source) is resolved via the TMDB
search endpoint. Candidates are scored and the top-scoring result per candidate is
kept. Scoring should combine TMDB's own relevance ordering with a title
similarity check (e.g. fuzzy match against the query) so an exact/near-exact title
hit outranks a loosely related result TMDB returns first.

## Output shape (draft)

```json
{
  "reel_url": "...",
  "recommendations": [
    {
      "query": "raw candidate string",
      "source": "caption | creator_comment | frame_visual",
      "confidence": 0.0,
      "tmdb": {
        "id": 0,
        "title": "...",
        "year": 0,
        "poster_path": "...",
        "overview": "...",
        "media_type": "movie | tv"
      }
    }
  ]
}
```

## Open questions (not yet decided)

- Which downloader/extractor to use for grabbing the video + metadata + comments
  per platform (Instagram vs TikTok vs YouTube Shorts each have different access
  constraints).
- How many frames is "optimum" for the visual fallback — fixed N vs. scaled to
  reel duration.
- Whether visual detection is poster-template matching, OCR-on-frame, or a
  vision-model call — cost/accuracy tradeoff to decide during implementation.
- How confidence thresholds are tuned per source so the pipeline knows when to
  fall through to the next source.

See [flow.md](flow.md) for the step-by-step execution flow.
