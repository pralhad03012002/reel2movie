# Handoff: reel2movie → desktop app

Written for a fresh session picking this up cold to build a **simple desktop
application**: input = a reel link, output = the movie/TV data it recommends.
The extraction/resolution pipeline this app wraps already exists, is tested,
and works end-to-end against real reels. This doc is the "read this first"
entry point — it does not replace `brainstorm.md` (product scope), `flow.md`
(step-by-step pipeline flow), or `PROGRESS.md` (full build history/rationale,
~7800 lines) — it tells you what those are for and when to go read them.

If a `graphify-out/` directory exists at the project root, `graphify-out/GRAPH_REPORT.md`
and `graphify-out/graph.html` are a navigable map of the codebase (entities,
call graph, design-rationale nodes linked to the code they explain) — useful
for orienting quickly instead of reading every file.

## What this project already does (don't rebuild this part)

`reel2movie` is a Python package + CLI that, given an Instagram Reel URL,
extracts the movie(s)/show(s) it's recommending and resolves each against
TMDB. It is **done and working** — 9 subtasks plus one bug-fix follow-up,
all committed, 262 unit tests passing, verified end-to-end against 11 real
reels. Your job is to put a GUI in front of it, not to re-implement any of
the extraction/resolution logic.

Current git tip: `e6367df` ("Subtask 9 follow-up: tolerate per-timestamp
extraction failures in dense sampling"). Run `git log --oneline` for the
full history — every commit maps 1:1 to a `## Subtask N` section in
`PROGRESS.md` with full rationale.

## How it works today (CLI)

```bash
pip install -e .
cp .env.example .env   # fill in TMDB_API_KEY at minimum
python3 -m reel2movie "https://www.instagram.com/reel/<id>/"
```

Prints a JSON object to stdout (see "Output contract" below) and exits 0,
or prints a one-line error to stderr and exits 1 (config errors, unreachable
URL). `--frame-interval-seconds <float>` overrides the dense-sampling
interval (default 1.0s); there is currently no CLI flag for the frame-dedup
threshold (internal-only, see `pipeline/deps.py`).

## The real integration point for a GUI: don't shell out, import it

The CLI (`reel2movie/cli.py`) is a thin wrapper around two functions that are
the actual API surface:

```python
from reel2movie.pipeline.deps import build_default_pipeline_deps
from reel2movie.pipeline.waterfall import run_pipeline

deps = build_default_pipeline_deps()      # reads env vars, wires real clients
result = run_pipeline(reel_url, deps)     # -> PipelineResult dataclass
```

`PipelineResult` (see `reel2movie/core/models.py`) is a plain dataclass:
`reel_url: str`, `recommendations: list[Recommendation]`, where each
`Recommendation` has `query`, `source` (`SourceTag`: `caption` |
`creator_comment` | `frame_visual`), `confidence: float`, and
`tmdb: ResolvedMovie | None` (`id`, `title`, `year`, `poster_path`,
`overview`, `match_score`, `media_type`: `"movie"` | `"tv"`).

**Call `run_pipeline` from a background thread, not the GUI's main thread** —
see "Performance" below, this is not a sub-second call in the general case.

If you'd rather keep the GUI in a different language/runtime and treat
`reel2movie` as an external process instead of a library, see "Subprocess
gotcha" below before you do — there's a real, reproduced issue with that
approach you need to defend against.

## Output contract (if going through the CLI/subprocess route)

Exactly what `python3 -m reel2movie <url>` prints to stdout on success
(`reel2movie/cli.py::_result_to_dict`):

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

`tmdb` is `null` when a candidate was detected but failed to resolve against
TMDB — **the GUI must handle this case**, it happens routinely (see "TMDB
flakiness" below), not just on malformed input. `poster_path` is a TMDB
relative path (e.g. `/aDb548...jpg`); full image URL is
`https://image.tmdb.org/t/p/w500<poster_path>` (standard TMDB CDN pattern —
not currently built anywhere in this codebase, you'll construct it in the GUI
layer).

## Config (env vars — see `.env.example` for the authoritative list)

| Var | Required? | Notes |
|---|---|---|
| `TMDB_API_KEY` | **Required** | TMDB v4 Bearer "API Read Access Token" (not the old v3 `api_key`). Raises `RuntimeError` at startup if missing. |
| `VISION_BACKEND` | Optional | `claude_code` (default) or `anthropic_api`. See next section — this choice has real desktop-distribution consequences. |
| `ANTHROPIC_API_KEY` | Conditional | Only read/required if `VISION_BACKEND=anthropic_api` is explicitly set. Never required for the default backend. |
| `INSTAGRAM_COOKIES_FILE` | Optional | Netscape-format cookies file for yt-dlp. Anonymous/cookieless access works for many reels (confirmed in testing) but Instagram may rate-limit without it. |

Loaded via `python-dotenv` from a `.env` file at the project root (never
committed — already in `.gitignore`).

## The biggest desktop-app design constraint: the `claude` CLI dependency

By default (`VISION_BACKEND=claude_code`), **both** the visual-fallback
detector and the text-extraction fallback shell out to a locally-installed
`claude` CLI binary, authenticated against a Claude Pro/Max subscription —
not a pip package, not bundled, not something `pip install -e .` gets you.
This was the deliberate choice to avoid requiring a separate metered API key
(see `vast-wobbling-owl.md` / `PROGRESS.md`'s "claude CLI subscription vs
metered API billing" rationale), and it's correct for this project's own
development/testing use. **It is almost certainly wrong for anything you'd
ship to another person's machine** — they would need the `claude` CLI
installed and logged into their own subscription, which is not normal
end-user desktop-app behavior.

Decide this explicitly before building the GUI, don't inherit the default
silently:
- **If this is a personal tool for your own machine**: the default is fine
  as-is, zero extra work.
- **If this will ever run on someone else's machine**: set
  `VISION_BACKEND=anthropic_api` and bundle/require a real
  `ANTHROPIC_API_KEY` (metered billing, your call on who pays) — this drops
  the `claude`-CLI dependency entirely, the GUI then only needs a normal pip
  install.

## Performance — this is not a fast, synchronous call

Real durations observed testing all 9 subtasks' worth of work against 11
live reels (`DU7OQACiDtk` etc., see `PROGRESS.md`'s Subtask 9 section for the
full table):

- Caption/comment-only hits (no visual fallback reached): **10–60 seconds**
  (mostly yt-dlp metadata fetch + a couple of TMDB calls).
- Visual-fallback hits (dense 1fps sampling → Pillow dedup → one Claude CLI
  vision call per surviving unique frame): **ranged from ~50 seconds to
  ~24 minutes** in real testing, driven by video length and how much the
  dedup pass collapses (a long, visually static video still pays for many
  Claude CLI round-trips if it keeps changing frame-to-frame).

**Design the GUI around this**: background thread/process, a progress
indicator (even an indeterminate spinner — there's no cheap way to predict
completion time upfront), and don't block the UI thread on `run_pipeline()`.

## Known gotchas discovered via real-world testing (not hypothetical)

1. **Subprocess stdout gotcha, if you go the "shell out to the CLI" route
   instead of importing the package**: `yt_dlp`'s download-progress meter
   writes directly to stdout (`[download] 100% of X MiB`) even though
   `reel2movie/ingest/ytdlp_client.py` sets `quiet: True` — `quiet` silences
   yt-dlp's own logger but NOT its progress-bar writer. Reproduced directly
   during this session's live testing: naive `stdout` capture + `json.loads()`
   failed because the progress line landed on the same line as the CLI's
   opening `{`. If you capture subprocess stdout, don't assume it's pure
   JSON — find the first `{` and parse from there, same workaround used
   during this session's testing. (A cleaner fix — adding `noprogress: True`
   to the `opts` dict in `ytdlp_client.py` — was identified but not applied;
   that's a good first improvement for whoever picks this up, since it fixes
   the root cause for every caller, not just one GUI's parsing code.)
2. **TMDB connection resets are routine, not rare.** `tmdb/client.py` already
   retries transient connection errors 3x with backoff, but in real testing
   some lookups still exhausted the retry budget and came back `tmdb: null`
   for perfectly real, correctly-detected titles (e.g. "27 Dresses",
   "Failure to Launch" in one real test run). The GUI should present
   unresolved recommendations gracefully (e.g. "detected but couldn't verify
   on TMDB — try again"), not treat `tmdb: null` as an extraction failure.
3. **Ambiguous titles can resolve inconsistently across repeated detections
   in the same reel.** Dense sampling means the same on-screen text can be
   independently "seen" in multiple frames; if the title is itself ambiguous
   (e.g. "The Invitation" — several real movies share that name), different
   frames' guesses can resolve to different TMDB entries in the same result
   set. This is a known, documented limitation (`brainstorm.md`'s "Known hard
   cases"), not a new bug — the GUI will occasionally show what looks like
   the "same" title twice with different years/posters. Decide whether to
   surface that as-is or add client-side dedup-by-fuzzy-title-match if it's
   visually confusing.
4. **Sentiment isn't filtered.** A caption that mentions a movie only to say
   "not as good as X" still surfaces X as a candidate — explicitly an
   accepted v1 limitation (`brainstorm.md`), not something to silently
   "fix" by adding filtering logic unless the user asks for it.

## File map

```
reel2movie/
  core/            models.py (dataclasses), protocols.py (Ingestor,
                   CandidateExtractor, PosterDetector, TMDBClient)
  config.py        env var loading — read this first, it's short and is
                   the full list of what the app needs configured
  ingest/          yt-dlp wrapper + Instagram adapter
  text_extraction/ regex extractor (fast path) + claude-CLI fallback
  visual/          frame_sampler.py (dense 1fps + legacy sparse sampling),
                   frame_dedup.py (Pillow perceptual dedup),
                   vision_llm_detector.py (poster + on-screen-text prompt)
  tmdb/            HTTP client, scoring, resolver
  pipeline/
    deps.py        <-- build_default_pipeline_deps(), the GUI's entry point
    waterfall.py   caption -> creator-comment -> visual-fallback orchestration
  cli.py           what `python3 -m reel2movie` runs — read for the exact
                   JSON serialization shape if going the subprocess route
tests/unit/        262 tests, all fakes/fixtures, no live network — run
                   with `python3 -m pytest tests/unit -q` before any change
tests/integration/ test_live_smoke.py — ONE real end-to-end test, skipped
                   unless REEL2MOVIE_LIVE_TEST_URL + real credentials are set
```

## Suggested desktop-app architecture (not prescriptive — your call)

Two reasonable shapes, pick based on what GUI stack you want:

- **Python GUI (Tkinter/PySide6/customtkinter) importing `reel2movie`
  directly.** Simplest, typed objects, no subprocess/JSON-parsing layer, no
  gotcha #1 above. Natural fit if you're staying in Python.
- **Any GUI stack, `reel2movie` as a subprocess.** More flexible stack choice,
  but you own stdout-parsing robustness (gotcha #1) and lose typed
  `Recommendation`/`ResolvedMovie` objects in favor of the raw JSON contract
  above.

Either way: run the pipeline off the UI thread, show a progress/spinner
state, and render `tmdb: null` entries distinctly from resolved ones rather
than hiding them.

## Before you start: sanity-check the current state

```bash
cd "/Users/apple/Desktop/Movie Reccomendation Reels extraction"
python3 -m pytest tests/unit -q   # should print "262 passed"
git log --oneline -1              # should be e6367df or later
```

If either doesn't match, something changed since this handoff was written —
read `PROGRESS.md`'s most recent `## Subtask N` section to find out what.
