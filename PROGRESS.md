# Progress

Reference: see `/Users/apple/.claude/plans/vast-wobbling-owl.md` for the full
approved plan (architecture, decisions, subtask list, loop process). This file
is the running handoff log between subagent spawns — each spawn starts with no
memory of prior turns, so read this file first, and update your own section
before finishing.

Subtasks, in build order: 0 core, 1 config, 2 tmdb, 3 text_extraction,
4 ingest, 5 frame_sampler, 6 vision_llm_detector, 7 pipeline, 8 cli.

---

## Subtask 0 — core/ (models.py, protocols.py) — status: done

### What's built
Files created:
- `reel2movie/__init__.py` — package docstring only.
- `reel2movie/core/__init__.py` — package docstring only.
- `reel2movie/core/models.py` — all frozen `@dataclass(frozen=True, slots=True)`
  value objects: `Platform` (StrEnum, `INSTAGRAM` member — open enum, more
  platforms can be added later), `SourceTag` (StrEnum: `CAPTION`,
  `CREATOR_COMMENT`, `FRAME_VISUAL`), `Comment`, `IngestResult` (`video_path:
  Path | None = None`, populated later by `ensure_video()`), `FrameSample`
  (`path: Path`, `timestamp_seconds: float`), `Candidate`, `TMDBSearchResult`,
  `ResolvedMovie`, `Recommendation` (`tmdb: ResolvedMovie | None = None` —
  unresolved candidates are kept, not dropped, per flow.md), `PipelineResult`
  (`recommendations` uses `field(default_factory=list)` so instances don't
  share a list).
- `reel2movie/core/protocols.py` — `@runtime_checkable` `typing.Protocol`s:
  `Ingestor` (`fetch_metadata`, `ensure_video`), `CandidateExtractor`
  (`extract`), `PosterDetector` (`detect`, takes a `FrameSample`),
  `TMDBClient` (`search_movie`). All signatures match the task spec exactly.
- `tests/__init__.py`, `tests/unit/__init__.py`, `tests/unit/core/__init__.py`
  — empty, for pytest package discovery.
- `tests/unit/core/test_models.py` — construction, equality, immutability
  (`dataclasses.FrozenInstanceError` on mutation attempts), the
  `Recommendation(tmdb=None)` "kept not dropped" rule, and that
  `PipelineResult`'s default `recommendations` list isn't shared between
  instances.
- `tests/unit/core/test_protocols.py` — a minimal fake per Protocol, checked
  both via `isinstance(fake, Protocol)` (requires `@runtime_checkable`) and
  by actually calling the fake's methods with real model instances; also
  checks that an incomplete fake (missing a method) and a bare empty class
  both correctly fail `isinstance`.

Ran `python3 -m pip install -e ".[dev]"` then
`python3 -m pytest tests/unit/core -q`:

```
........................                                                 [100%]
24 passed in 0.09s
```

### Review findings (latest pass)

Reviewed via `/code-review` (medium), `/ponytail:ponytail-review`, a manual
spec check of every dataclass/Protocol against `vast-wobbling-owl.md`, and a
fresh `python3 -m pytest tests/unit/core -q` run (24 passed, confirmed
independently, not just trusted from the earlier report).

**From `/code-review` (correctness/cleanup):**
- **Non-blocking** — `models.py` L59/L130: `IngestResult.comments` and
  `PipelineResult.recommendations` are plain `list[...]` fields. `frozen=True`
  blocks field *reassignment* but not in-place mutation (`.append()`,
  `.sort()`), so the module docstring's "Immutable value objects" claim is
  slightly stronger than what's actually enforced. Already self-flagged as an
  open risk in this file. Could switch to `tuple[Comment, ...]` /
  `tuple[Recommendation, ...]` for real deep immutability, but the spec
  literally types these as `list[...]`, so deferring rather than silently
  changing the contract.
- **Non-blocking** — `models.py` L86-108: `TMDBSearchResult` and
  `ResolvedMovie` duplicate 5 fields verbatim (`id`, `title`, `year`,
  `poster_path`, `overview`) with no shared base. Future field
  additions/renames must be kept in sync by hand across both. Both classes
  match the plan's spec as separate types (one is a raw search row, the other
  a chosen match plus `match_score`), so not wrong, just a DRY opportunity —
  worth revisiting if a shared base adds real value once subtask 2 (tmdb/)
  shows how these are actually used.

**From `/ponytail:ponytail-review` (over-engineering/complexity):**
- **Non-blocking** — `tests/unit/core/test_models.py` L44-47, L87-97,
  L106-111, L165-168: four near-identical "construct a frozen dataclass,
  assert `FrozenInstanceError` on mutation" tests (one each for `Comment`,
  `IngestResult`, `FrameSample`, `Recommendation`). Could collapse into one
  `@pytest.mark.parametrize`-driven test, saving ~17 lines. Not wrong, just
  repetitive.
- **Non-blocking** — `models.py` L43: `Comment.like_count: int | None = None`
  is unused by anything in this subtask; speculative field for a future
  comment-ordering need that's still an open question in `brainstorm.md`.
  Cheap to keep, low-confidence flag.
- Everything else (the `StrEnum`s, the four `@runtime_checkable` Protocols,
  `field(default_factory=list)` on `PipelineResult`) is load-bearing for
  subtasks 1-8 per the plan, not speculative. No reinvented stdlib, no
  unnecessary dependencies, no dead code.

**Manual spec check (`core/models.py` + `core/protocols.py` vs.
`vast-wobbling-owl.md`):**
- Confirmed present with correct field names/types: `Platform` (StrEnum,
  `INSTAGRAM`), `SourceTag` (StrEnum, `CAPTION`/`CREATOR_COMMENT`/
  `FRAME_VISUAL`), `Comment`, `IngestResult`, `Candidate`, `TMDBSearchResult`,
  `ResolvedMovie`, `Recommendation`, `PipelineResult`, `FrameSample` — all
  `@dataclass(frozen=True, slots=True)`, matching the plan's "Core
  dataclasses" section and the task-spec field list exactly (e.g.
  `IngestResult.video_path: Path | None = None` lazily populated,
  `Recommendation.tmdb: ResolvedMovie | None = None` kept-not-dropped per
  `flow.md`, `PipelineResult.recommendations` via `default_factory=list`).
- Confirmed present with correct signatures: `Ingestor`
  (`fetch_metadata(url: str) -> IngestResult`, `ensure_video(result:
  IngestResult) -> Path`), `CandidateExtractor` (`extract(text: str, source:
  SourceTag) -> list[Candidate]`), `PosterDetector` (`detect(frame:
  FrameSample) -> list[Candidate]`), `TMDBClient` (`search_movie(query: str,
  year: int | None = None) -> list[TMDBSearchResult]`) — all
  `@runtime_checkable` `Protocol`s, matching the plan's split rationale
  (`fetch_metadata`/`ensure_video` split so video download is deferred).
- Independently re-ran `python3 -m pytest tests/unit/core -q`: `24 passed`.

No correctness bugs found. No blocking findings.

VERDICT: ACCEPTABLE

### Fixes applied
(none yet)

### Open questions / risks
- `runtime_checkable` Protocol `isinstance` checks only confirm method
  *names* are present, not their signatures/arity/types. The tests compensate
  by also invoking each fake with real model objects, but a later subtask's
  real implementation could still technically satisfy `isinstance` while
  having a subtly wrong signature (e.g. wrong parameter name for a keyword
  arg like `year` in `TMDBClient.search_movie`) — worth a human/type-checker
  (mypy/pyright) look when real implementations land, since isinstance alone
  won't catch it.
- `IngestResult.comments` and `PipelineResult.recommendations` are
  `list[...]` per the spec, so the dataclasses are frozen (can't reassign
  the field) but the lists themselves are still mutable in place. This
  matches the task's literal field types; flagging in case a later subtask
  assumes full deep immutability.
- `Platform` and `SourceTag` are `StrEnum` (stdlib, Python 3.11+, matches
  `requires-python = ">=3.11"` in pyproject.toml) rather than a plain `Enum`
  — chosen so values serialize/compare naturally as plain strings (useful
  for JSON output per brainstorm.md's output shape) without needing `.value`
  everywhere. No other mechanism was considered necessary.
- Did not add `__init__.py` files beyond what's needed for pytest discovery
  under `tests/` — no `tests/unit/core/__init__.py`-style namespace packages
  elsewhere were assumed since this is a fresh repo with no prior tests/
  convention.

---

## Subtask 1 — config.py — status: done

### What's built
Files created:
- `reel2movie/config.py` — three env-var-backed getters, no secret values
  hardcoded anywhere:
  - `get_tmdb_token() -> str` — reads `TMDB_API_KEY` from `os.environ`,
    raises `RuntimeError` (message points at `.env.example`) if unset or
    empty (empty string treated the same as unset).
  - `get_anthropic_key() -> str` — same pattern for `ANTHROPIC_API_KEY`.
  - `get_instagram_cookies_file() -> Path | None` — reads
    `INSTAGRAM_COOKIES_FILE`; optional, returns `None` if unset/empty
    rather than raising (not every pipeline run needs live Instagram
    access, e.g. unit tests use recorded fixtures); returns a
    `pathlib.Path` if set. Deliberately does **not** validate the file
    exists — per the subtask spec, that's the `ingest/` module's job when
    it actually tries to use the file.
- `tests/unit/test_config.py` — sits directly under `tests/unit/` (no
  `core`-style subpackage, since `config.py` isn't part of a subpackage).
  Covers, for each getter: the set/returns-expected-value case, the
  unset/raises-`RuntimeError`-with-message case (`pytest.raises(...,
  match=...)`), and an explicit empty-string case treated as unset. For
  the optional getter, also covers the unset-and-empty → `None` cases and
  the set → `Path` case. All env var manipulation goes through
  `monkeypatch.setenv` / `monkeypatch.delenv`; no real credentials appear
  anywhere in the test file or `config.py` itself.

Verified `.env.example` and `.gitignore` (written during scaffolding, not
by me) rather than rewriting them: `.gitignore` excludes `.env` (and does
**not** exclude `.env.example`, so the example file stays tracked);
`.env.example` documents exactly `TMDB_API_KEY`, `ANTHROPIC_API_KEY`,
`INSTAGRAM_COOKIES_FILE` with no real values. Both already correct — no
changes made to either file.

Ran `python3 -m pytest tests/unit -q` (runs Subtask 0's existing tests
plus the new ones):

```
.................................                                        [100%]
33 passed in 0.07s
```

(24 from Subtask 0's `tests/unit/core/` + 9 new in `tests/unit/test_config.py`,
confirming nothing added here broke Subtask 0's tests.)

### Review findings (latest pass)

Reviewed via `/code-review` (medium) on the current diff (`reel2movie/config.py`,
`tests/unit/test_config.py`, plus this file's own doc update), `/ponytail:ponytail-review`
on the same diff, a manual read of `config.py` against the subtask spec and
`vast-wobbling-owl.md`, a repo-wide grep for hardcoded secrets, and a fresh
`python3 -m pytest tests/unit -q` run (33 passed, confirmed independently).

**From `/code-review` (correctness):**
- No defect found. The three getters are straightforward `os.environ.get`
  reads with consistent empty-string-as-unset handling, each covered by a
  matching test; no existing callers yet so no cross-file breakage is
  possible. One edge case noted but deemed not actionable: a whitespace-only
  env var (e.g. `TMDB_API_KEY=" "`) passes the `if not value` check and would
  be returned as a seemingly-valid token — **non-blocking**, speculative and
  low-consequence for local dev config.

**From `/ponytail:ponytail-review` (over-engineering/complexity):**
- **Non-blocking** — `config.py` L16-41: `get_tmdb_token()` and
  `get_anthropic_key()` are two copies of the identical 6-line "read env var,
  raise `RuntimeError` if empty" pattern, differing only in the variable name.
  Could collapse into one `_require_env(name: str) -> str` helper called by
  both, saving ~8 lines. Not wrong, just duplicated.
- **Non-blocking** — `tests/unit/test_config.py` L20-51: 6 near-identical
  tests (3 patterns × 2 getters: set/returns, unset/raises, empty/raises)
  differing only in the var name and function under test. Could collapse via
  `@pytest.mark.parametrize`. Same pattern already flagged (and deferred) in
  Subtask 0's review.
- Everything else (the optional-getter's distinct None-returning logic, the
  `Path` wrapping, the module/function docstrings) is load-bearing per spec,
  not speculative.

**Manual spec check (`config.py` vs. subtask spec + `vast-wobbling-owl.md`):**
- Confirmed `get_tmdb_token() -> str` reads `TMDB_API_KEY`, raises
  `RuntimeError` (pointing at `.env.example`) on unset or empty.
- Confirmed `get_anthropic_key() -> str` reads `ANTHROPIC_API_KEY`, same
  raise-on-unset/empty behavior.
- Confirmed `get_instagram_cookies_file() -> Path | None` reads
  `INSTAGRAM_COOKIES_FILE`, returns `None` on unset/empty, **never raises**,
  returns a `pathlib.Path` when set, does not validate file existence (left
  to `ingest/`, per spec).
- Confirmed `.env.example` documents exactly the three expected var names
  with no real values, and `.gitignore` excludes `.env` but not
  `.env.example`.

**Secret-hardcoding check (critical, given the earlier real-token leak in
chat):**
- Ran `grep -rEn "eyJ[A-Za-z0-9_-]{10,}"` (JWT-header-shaped strings, matching
  the structure of the TMDB v4 token that was pasted into chat earlier) and
  `grep -rEn "\b[0-9a-fA-F]{32}\b"` (literal 32-char hex, a common raw-API-key
  shape) across the entire repo, excluding `.git`. **Zero matches.** No
  hardcoded secret/token of either shape exists anywhere in the codebase.
  `config.py` and `test_config.py` only ever use fake placeholder strings
  (e.g. `"fake-tmdb-token-value"`) via `monkeypatch`, never real credentials.

**Independent test run:**
- `python3 -m pytest tests/unit -q` → `33 passed` (24 from Subtask 0 +
  9 from `test_config.py`), run directly, not just trusted from the
  build-subagent's report.

No blocking findings.

VERDICT: ACCEPTABLE

### Fixes applied
(none yet)

### Open questions / risks
- `get_instagram_cookies_file()` treats an empty-string env var the same
  as unset (returns `None`). This matches `get_tmdb_token()` /
  `get_anthropic_key()`'s empty-string-is-unset handling for consistency,
  but wasn't explicitly specified for the optional getter — flagging in
  case a later subtask wants a stricter distinction between "var unset"
  and "var set to empty string".
- Open question for `ingest/` (subtask 4): `get_instagram_cookies_file()`
  returns a `Path` with zero validation (doesn't check existence,
  readability, or Netscape-cookie-file format). The ingest module's
  `InstagramIngestor` / `ytdlp_client.py` wrapper needs to decide what to
  do when the configured path doesn't exist or isn't readable — e.g.
  raise a clear error before handing it to `yt_dlp.YoutubeDL`, rather than
  letting yt-dlp's own error surface opaquely. Also unresolved: what
  happens when `get_instagram_cookies_file()` returns `None` entirely —
  presumably `ingest/` should allow cookie-less operation for any ingest
  path that doesn't need authenticated access (if any), or raise its own
  clear error if cookies are mandatory for all Instagram ingestion.
- No live/real env vars were touched by this subtask's tests — every test
  uses `monkeypatch`, which pytest automatically reverts after each test,
  so there's no risk of leaking a fake value into the environment of
  later test runs in the same process.

---

## Subtask 2 — tmdb/ — status: done

### What's built
Files created:
- `reel2movie/tmdb/__init__.py` — package docstring only.
- `reel2movie/tmdb/client.py` — `TMDBHttpClient` (deliberately not named
  `TMDBClient`, to avoid colliding with the Protocol of that name in
  `core/protocols.py`). Takes a bearer token in `__init__`; does **not**
  call `config.get_tmdb_token()` itself, so it stays constructible with
  any token string for testability (per spec — that's a later
  `build_default_pipeline_deps()`'s job). `search_movie(query, year=None)`
  calls `GET https://api.themoviedb.org/3/search/movie` via `requests.get`
  with `Authorization: Bearer <token>` header, `query` param always, `year`
  param only when given. Maps each `results[]` item to a `TMDBSearchResult`
  with `original_rank` = 0-indexed position in the response array. A
  module-level `_parse_year()` helper extracts just the year out of TMDB's
  `release_date` string (`"1999-03-30"` → `1999`), returning `None` on an
  empty/unparseable string rather than raising. Calls
  `response.raise_for_status()` unconditionally — HTTP errors propagate to
  the caller rather than being swallowed.
- `reel2movie/tmdb/scoring.py` — `score_result(query, year_hint, result)`
  implements the plan's exact formula: `0.65 * title_similarity + 0.25 *
  rank_bonus + 0.10 * year_bonus`, with `title_similarity =
  rapidfuzz.fuzz.WRatio(query, result.title) / 100`, `rank_bonus = 1 / (1 +
  result.original_rank)`, `year_bonus = 1.0 if year_hint and result.year ==
  year_hint else 0.0`. `pick_best(query, year_hint, results)` returns the
  argmax by `score_result`, or `None` if `results` is empty or the best
  score is below `MIN_MATCH_SCORE = 0.5` (named constant, one-line comment:
  "a reasonable floor, not derived from any real data").
- `reel2movie/tmdb/resolver.py` — `resolve_candidate(candidate, client)`,
  typed against the `TMDBClient` Protocol from `core/protocols.py`
  (structural typing), not the concrete `TMDBHttpClient`, so tests/later
  callers can pass any fake. A local `_extract_year_hint()` helper uses a
  simple `\((\d{4})\)` regex to pull an obvious parenthesized year out of
  `candidate.raw_text` (e.g. `"The Matrix (1999)"` → `1999`); this is
  intentionally not real date parsing, just a cheap hint for the TMDB query
  + scoring. Calls `client.search_movie(candidate.raw_text, year=year_hint)`,
  then `pick_best()`, then maps the winning `TMDBSearchResult` to a
  `ResolvedMovie` (dropping `popularity`/`original_rank`, adding
  `match_score` from `score_result()`). Returns `None` when nothing
  resolves — per flow.md, it's the caller's (a later pipeline subtask's)
  job to decide to keep the candidate with `tmdb=None` rather than
  dropping it; this function only signals "nothing resolved."
- `tests/unit/tmdb/__init__.py` — empty, for pytest package discovery.
- `tests/unit/tmdb/test_client.py` — mocks `reel2movie.tmdb.client.requests.get`
  (via `unittest.mock.patch`; no new dev dependency added, plain
  `unittest.mock` was sufficient) with canned TMDB-shaped JSON. Covers: the
  `Authorization: Bearer <token>` header is set correctly, `query` param is
  always passed, `year` param is passed only when given, the correct
  endpoint URL is hit, field mapping into `TMDBSearchResult` (including year
  parsing from `release_date`, and the empty-`release_date` → `year=None`
  case), `original_rank` correctness across multiple results, and that an
  HTTP error (`raise_for_status` side effect) propagates as `requests.HTTPError`
  rather than being swallowed.
- `tests/unit/tmdb/test_scoring.py` — pure function tests, no mocking:
  exact title match scores higher than a loose match; a matching year hint
  boosts the score relative to no hint; a wrong year hint gives no bonus
  (same score as no hint); earlier rank scores higher than later rank;
  `pick_best` returns `None` on empty results and on all-low-confidence
  results; `pick_best` returns the correct argmax; a sanity check that
  `MIN_MATCH_SCORE` is a float in `(0, 1)`.
- `tests/unit/tmdb/test_resolver.py` — a `FakeTMDBClient` (not the real
  `TMDBHttpClient`) recording the `query`/`year` it was called with and
  returning a canned `TMDBSearchResult` list. Covers: year extraction from
  candidate text (`"The Matrix (1999)"` → hint `1999` passed through to
  `search_movie`), no year hint when absent, correct `ResolvedMovie`
  field mapping (including that `popularity`/`original_rank` are absent on
  the result via `hasattr` checks), `None` on an empty result list, and
  `None` when the best available result is low-confidence.

Ran `python3 -m pytest tests/unit -q` (Subtask 0 + 1's existing tests plus
the new ones):

```
....................................................                      [100%]
52 passed in 0.46s
```

(33 from Subtasks 0+1 + 19 new in `tests/unit/tmdb/`, confirming nothing
added here broke earlier subtasks' tests.)

### Review findings (latest pass)

Reviewed via `/code-review` (medium, forked) on the current diff
(`reel2movie/tmdb/{__init__,client,scoring,resolver}.py` +
`tests/unit/tmdb/`), `/ponytail:ponytail-review` on the same diff, a manual
read of `client.py`/`scoring.py`/`resolver.py` against the subtask spec,
`core/protocols.py`, and `vast-wobbling-owl.md`'s scoring formula/auth-style
decisions, and a fresh `python3 -m pytest tests/unit -q` run (52 passed,
confirmed independently, not just trusted from the build report).

**From `/code-review` (correctness/efficiency):**
- **Non-blocking** — `resolver.py` L33-35 / `scoring.py` L26: the
  parenthesized year that `_extract_year_hint()` pulls out of
  `candidate.raw_text` is never stripped from the text itself, so the same
  unstripped `raw_text` (e.g. `"The Matrix (1999)"`) is sent both as the
  TMDB search query and as the `fuzz.WRatio(query, result.title)` comparand
  against TMDB's clean title (`"The Matrix"`). Confirmed intentional/tested
  behavior, not an oversight — `test_resolver.py` L49 explicitly asserts
  `client.last_query == "The Matrix (1999)"`. `WRatio` is specifically
  designed to handle differing-length strings via partial-ratio weighting,
  so the real-world score dilution is likely small, but it's a genuine
  design tension: the year-hint extraction was meant to add signal, yet the
  unstripped text feeding `title_similarity` could quietly cost some of
  that signal back for exactly the candidates that have an explicit year.
  Flagging as a risk to watch once this is exercised against live TMDB
  data in a later subtask, not as a spec violation (the plan doesn't
  specify stripping).
- **Non-blocking** — `scoring.py` L39-41 / `resolver.py` L45:
  `score_result()` is computed redundantly — twice inside `pick_best()`
  (once per result inside `max()`'s key, once more for the winner to check
  `MIN_MATCH_SCORE`), and a third time in `resolve_candidate()` to get
  `match_score` for the same `(query, year_hint, best)` triple. Not a
  correctness bug (all three computations are deterministic and agree),
  just wasted `rapidfuzz` calls on every resolution.

**From `/ponytail:ponytail-review` (over-engineering/complexity):**
- `scoring.py:L36-42`: `shrink:` `pick_best` recomputes `score_result` for
  the winner after `max()` already found it. Score once per result and
  reuse: `scored = [(score_result(query, year_hint, r), r) for r in
  results]`; `best_score, best = max(scored, key=lambda p: p[0])`; `return
  best if best_score >= MIN_MATCH_SCORE else None`.
- `resolver.py:L45`: `yagni:` third recomputation of the same score to get
  `match_score`. Have `pick_best` (or a thin wrapper) hand back the score
  it already computed alongside the result, so `resolve_candidate` doesn't
  call `score_result` again.
- Everything else (the `TMDBHttpClient`/`_parse_year` split, the
  `_extract_year_hint` regex helper, the three test files' structure) is
  load-bearing and already minimal — no reinvented stdlib, no unneeded
  dependency, no speculative abstraction.
- `net: -3 lines possible` (mostly removes wasted computation, not bulk).

**Manual verification (`client.py`/`scoring.py`/`resolver.py` vs. spec,
`core/protocols.py`, and `vast-wobbling-owl.md`):**
- Confirmed `TMDBHttpClient.__init__(self, bearer_token: str)` takes the
  token directly as a constructor argument; confirmed by reading the whole
  module that `reel2movie.config` / `get_tmdb_token()` is never imported or
  called anywhere in `tmdb/` — loading the token from the environment stays
  the caller's job, per the plan.
- Confirmed `search_movie` sends `Authorization: Bearer <bearer_token>`
  (client.py L58) against `https://api.themoviedb.org/3/search/movie`
  (client.py L14, L56) — matches the plan's v4 Bearer auth-style decision,
  not the older v3 `api_key` query-param style, and hits `search/movie`,
  not `search/multi`.
- Confirmed the scoring formula matches the spec exactly: `0.65 *
  title_similarity + 0.25 * rank_bonus + 0.10 * year_bonus` (scoring.py
  L29), with `title_similarity = fuzz.WRatio(query, result.title) / 100`,
  `rank_bonus = 1 / (1 + result.original_rank)` (correctly decreasing with
  later rank), `year_bonus = 1.0` only when `year_hint` is truthy *and*
  `result.year == year_hint` (correctly 0.0 on mismatch or no hint).
- Confirmed `resolve_candidate(candidate: Candidate, client: TMDBClient)`
  (resolver.py L25) is typed against the `TMDBClient` Protocol imported
  from `core/protocols.py` (structural typing), never against the concrete
  `TMDBHttpClient` class — matches the plan's DI rationale and is exactly
  what lets `tests/unit/tmdb/test_resolver.py`'s `FakeTMDBClient` stand in
  without inheriting anything.
- Confirmed `_parse_year()` (client.py L17-30) handles all three named edge
  cases correctly without raising: missing `release_date` key (`.get()`
  returns `None`, caught by the `if not release_date` falsy check), empty
  string (same falsy check), and a malformed/non-numeric date string (the
  `int(year_part)` `ValueError` is caught and returns `None`). Traced by
  hand (not just by reading the one empty-string test case) against
  additional cases not in the test suite — leading/trailing whitespace
  (`int()` strips it) and a string with no `-` at all (`split("-", 1)[0]`
  degrades gracefully to the whole string) — both still behave correctly.
- **Non-blocking, newly noted** — `client.py` L56-60: `requests.get()` is
  called with no `timeout`. A stalled/unresponsive TMDB endpoint would hang
  `search_movie()` (and therefore `resolve_candidate()`) indefinitely
  rather than failing fast. Not specified in the plan, but worth adding
  before this hits a real pipeline run with many candidates.

**Independent test run:**
- `python3 -m pytest tests/unit -q` → `52 passed`, run directly in this
  review pass, not just trusted from the build-subagent's report.

No blocking findings. The formula, auth style, endpoint, Protocol typing,
and year-parsing edge cases all check out against the spec exactly;
remaining findings are efficiency/robustness polish, not deviations from
`vast-wobbling-owl.md` or incorrect behavior for any case in the current
test suite.

VERDICT: ACCEPTABLE

### Fixes applied
(none yet)

### Open questions / risks
- **TMDB response shape assumptions** (can't hit the live TMDB API from
  this sandbox to verify): assumed `results[].release_date` is always a
  string key present on every item (possibly empty `""`, handled via
  `_parse_year`'s falsy check), `results[].poster_path` can be `null`/
  absent (handled via `.get()`), and `results[].popularity` /
  `.overview` are always present with sensible defaults if missing
  (`0.0` / `""` via `.get(..., default)`). These match TMDB's documented
  `search/movie` response shape from public API docs as remembered, but
  have not been verified against a live call.
- **`year` query param type**: passed as a Python `int` straight into
  `requests`' `params` dict; `requests` will stringify it when building
  the query string, which should match TMDB's expected `year` param format,
  but this wasn't verified against a live request.
- **`MIN_MATCH_SCORE = 0.5` threshold**: picked as "a reasonable floor,"
  not tuned against any real TMDB result set. If later subtasks
  (`pipeline/`) see too many false negatives (confident real matches
  scoring just under 0.5) or false positives (wrong matches sneaking
  over 0.5), this constant is the first thing to revisit — it's isolated
  in one place (`tmdb/scoring.py`) specifically so it's easy to tune later.
- **Year-hint regex** (`\((\d{4})\)`) only catches a parenthesized year
  directly in the candidate's raw text (e.g. from `text_extraction/`'s
  `"Title (YYYY)"` pattern per the plan). It will miss a year mentioned in
  prose elsewhere in the same string (e.g. "the 1999 movie The Matrix") —
  accepted as a deliberate scope limit per the subtask spec ("a simple
  regex... don't duplicate real date parsing"), not a bug.
- `TMDBHttpClient.search_movie` does not retry or cache; every call hits
  the network fresh. No rate-limiting/backoff logic was added since it
  wasn't in scope for this subtask and the plan doesn't mention it — worth
  a look if a later subtask resolves many candidates per run and TMDB's
  rate limits become a real concern.

---

## Subtask 3 — text_extraction/regex_extractor.py — status: done

### What's built
Files created:
- `reel2movie/text_extraction/__init__.py` — package docstring only.
- `reel2movie/text_extraction/regex_extractor.py` — `RegexCandidateExtractor`
  (structurally satisfies `core.protocols.CandidateExtractor`, no
  inheritance). Pure `re`/string logic, no IO, no network, no NLP/ML
  dependency (stdlib `re` only, per spec). `extract(text, source) ->
  list[Candidate]` runs four regex passes over the text, in confidence
  order, each pass skipping any match that overlaps a span already
  claimed by an earlier (higher-priority) pass via a small `_claim()`
  helper — this is what prevents e.g. `"Parasite" (2019)` from producing
  both a HIGH `"Parasite (2019)"` candidate *and* a redundant MEDIUM
  `"Parasite"` candidate from the plain-quote pass:
  1. **Quoted `"Title" (YYYY)`** → HIGH (0.9). Matching-quote-type only
     (`"..."` or `'...'`, not mixed), capped at 100 chars, no newlines.
  2. **Unquoted `Title (YYYY)`** → HIGH (0.9). Requires every word in the
     title to start with an uppercase letter, immediately (optional
     whitespace only) followed by `(YYYY)`.
  3. **Bare quoted span, no year** → MEDIUM (0.6). Same matching-quote-type
     /length/no-newline rule as pass 1, just without the trailing-year
     requirement.
  4. **Numbered-list line (`"1. Title"` / `"2) Title"`)** → MEDIUM (0.6).
     Captures the rest of the line after the `\d+[.)]\s+` marker; strips
     whitespace, matching outer quotes, and trailing `.,;:` punctuation.
  Output format: `Candidate.raw_text` is the cleaned title with quote
  marks stripped, and for the two HIGH patterns is re-assembled as
  exactly `"Title (YYYY)"` (title + a single space + literal parens around
  the 4-digit year) — confirmed by reading `reel2movie/tmdb/resolver.py`
  first: its `_extract_year_hint()` looks for `\((\d{4})\)` via
  `re.search`, so this output is picked up correctly regardless of
  anything before it in the string. `source: SourceTag` is passed straight
  through to every returned `Candidate`, never hardcoded, so the same
  extractor instance is reusable for both `SourceTag.CAPTION` and
  `SourceTag.CREATOR_COMMENT` callers per the plan.
- `tests/unit/text_extraction/__init__.py` — empty, for pytest discovery.
- `tests/unit/text_extraction/test_regex_extractor.py` — 12 tests:
  quoted-title-with-year → HIGH; unquoted-title-with-year → HIGH; a direct
  round-trip check that `reel2movie.tmdb.resolver._extract_year_hint()`
  correctly reads the year back out of a HIGH candidate's `raw_text`
  (imports the resolver's private helper specifically to verify this
  cross-module contract, not just assert the string shape by eye); bare
  quoted title (no year) → MEDIUM, quotes stripped; a 3-line numbered list
  → all 3 titles returned as separate MEDIUM candidates; a dismissive
  sentence (`"not as good as 'The Godfather'"`) → still extracts (asserts
  the known limitation's behavior, not a filtered-out assertion); a short
  ambiguous quoted title (`"It"`) → still extracted as MEDIUM; empty string
  → `[]`; plain no-signal prose → `[]`, no crash; `source` echoed into
  every candidate for both `SourceTag` values used; multiple HIGH
  candidates in one block (`'"Parasite" (2019) and Inception (2010)'`) →
  both returned; return type is `Candidate` instances.

Ran `python3 -m pytest tests/unit -q`:

```
................................................................          [100%]
64 passed in 0.43s
```

(52 from Subtasks 0-2 + 12 new in `tests/unit/text_extraction/`, confirming
nothing added here broke any earlier subtask's tests.)

### Confidence-tiering choices and rationale

- **HIGH (0.9) for `"Title (YYYY)"`, quoted or unquoted** — per spec, this
  is the least ambiguous signal: both a title-shaped string and an
  explicit year are present together, which is exactly the hint
  `resolver.py`'s `_extract_year_hint()` + TMDB's `year` search param are
  built to exploit.
- **MEDIUM (0.6) for bare quoted spans and numbered-list lines** — both
  have an explicit structural delimiter (quote marks, or a list marker)
  that signals "this is a title-like unit," just without a year to
  disambiguate it further. Treated as equally confident to each other
  since neither has a stronger claim than the other without a year.
- **Bare, unmarked title-case runs (no quotes, no year, no list marker)
  are skipped entirely — not tagged LOW.** This was the explicitly
  open "your call" choice in the spec. Chose to skip rather than emit a
  0.3-confidence guess because: (1) this extractor is reused for both
  captions *and* raw creator comments, which are free-form natural-
  language text — any capitalized proper noun or sentence-initial phrase
  would otherwise become a "candidate," producing a high false-positive
  rate; (2) the pipeline's waterfall (subtask 7) falls through to the next
  source only when the current one yields nothing *confident* — returning
  a flood of noisy LOW candidates for ordinary prose risks the waterfall
  treating a caption with zero real signal as "handled" by a garbage
  guess, rather than correctly falling through to the creator's comment or
  the visual fallback. Skipping keeps this module's output meaningful-
  signal-only and pushes the "is there anything here at all" judgment call
  to the next pipeline stage, which has more context (e.g. whether the
  comment/visual steps found anything better). This materially affects
  waterfall behavior as the spec flagged it would — documented here per
  that instruction.

### Accepted limitation — sentiment/dismissive-mention false positives

Per `brainstorm.md`'s explicit "Known hard cases" list: a caption/comment
that *mentions* a title only to dismiss it (`"not as good as 'X'"`) is
**not** filtered out. Any quoted (or `Title (YYYY)`-shaped) span inside such
a sentence is still extracted as a normal candidate at its usual
confidence tier — this is an accepted, by-design limitation, not a bug.
No sentiment/intent analysis was attempted (out of scope per spec); the
only thing guaranteed here is that this case never crashes or produces
malformed output, which `test_dismissive_sentence_with_quoted_title_is_still_extracted`
confirms by asserting the extraction *does* happen.

### Review findings (latest pass)

This section holds two review passes, kept distinct rather than letting the
newer one overwrite the older (per handoff-logging convention: never destroy
history). **Cycle 0** (below) is the original pre-fix review; its outcome is
narrated in `### Fixes applied` above this section was written and is kept
here verbatim for the record. **Cycle 2** (further down) is a fresh,
from-scratch re-review of the current working tree — including both
`text_extraction/regex_extractor.py` and the one-line `tmdb/resolver.py`
companion fix — run independently of cycle 0/1, not a continuation of them.

#### cycle 0 review (historical — pre-fix; see "Fixes applied" above for what changed in response)

Reviewed via `/code-review` (medium, forked) on the current diff
(`reel2movie/text_extraction/{__init__,regex_extractor}.py` +
`tests/unit/text_extraction/`), `/ponytail:ponytail-review` on the same diff,
a manual read of `regex_extractor.py` against `core/protocols.py`'s
`CandidateExtractor` contract and a hand-traced round-trip against
`tmdb/resolver.py`'s `_extract_year_hint()`, and a fresh
`python3 -m pytest tests/unit -q` run (64 passed, confirmed independently —
not just trusted from the build report). Both `/code-review` findings below
were additionally reproduced by direct script execution (not just read off
the review output), since the task explicitly called for verifying rather
than trusting the build report.

**From `/code-review` (correctness):**
- **Blocking** — `regex_extractor.py` L106-137 (`_UNQUOTED_TITLE_YEAR` pass
  vs. the numbered-list pass, via shared `_claim()`): for a numbered-list
  line whose title has a lowercase connector word before the year (e.g.
  `"1. The Lord of the Rings (2001)"`), `_UNQUOTED_TITLE_YEAR` first claims
  only the trailing `"Rings (2001)"` span (confirmed by hand-trace: the
  all-caps-chain requirement breaks at "of", so the match starts fresh at
  "Rings"). The numbered-list pass's full-line span then overlaps that
  small claimed span, so `_claim()` rejects the *entire* line and the
  correct MEDIUM candidate `"The Lord of the Rings"` is never emitted at
  all. Net effect, reproduced directly:
  ```
  extractor.extract('5 movies like Inception:\n1. The Lord of the Rings (2001)\n2. Interstellar\n', SourceTag.CAPTION)
  # -> [Candidate(raw_text='Rings (2001)', confidence=0.9), Candidate(raw_text='Interstellar', confidence=0.6)]
  ```
  Only a wrong, truncated title survives, at HIGH confidence — worse than
  the existing "Open questions" note for this case (which only anticipated
  the truncated HIGH match, not that the correct MEDIUM candidate also gets
  silently dropped via the overlap-claim mechanism). This lands on exactly
  the explicitly-accepted hard case from `brainstorm.md` ("multiple movies
  in one reel / ranked list reels") and actively misleads a downstream TMDB
  resolve with a confident-but-wrong query, rather than merely missing a
  candidate (which would be an acceptable scope limit). Blocking because the
  failure mode is "wrong confident answer," not "no answer."
- **Non-blocking** — `regex_extractor.py` L91-104 /
  `tmdb/resolver.py` `_extract_year_hint()`: when a quoted title's own text
  contains a parenthesized 4-digit substring (e.g. a year mentioned inside
  the quote), `_QUOTED_TITLE_YEAR`'s capture group `[^"\n]{1,100}` happily
  includes it, and the resulting `raw_text` ends up with *two*
  `(YYYY)`-shaped substrings. `_extract_year_hint()`'s `re.search` returns
  the leftmost one, not the real trailing release year. Reproduced directly:
  ```
  extractor.extract('"Experience Paris (1920) like never before" (2023)', SourceTag.CAPTION)
  # raw_text = 'Experience Paris (1920) like never before (2023)'
  _extract_year_hint(raw_text)  # -> 1920, not 2023
  ```
  This contradicts the module docstring's claim that the HIGH-confidence
  output "is picked up correctly regardless of anything before it in the
  string." Non-blocking: narrow/rare input shape (a quoted title that
  itself contains a parenthesized number), and the consequence is a
  degraded year hint rather than a wrong confident resolution — the garbled
  `raw_text` also gets sent as the TMDB query text itself, so title
  similarity scoring is already compromised independent of the year hint.
  Worth a quick fix (e.g. anchor the year extraction/regex to the *last*
  `(YYYY)` in `raw_text`, or to the string's suffix) alongside the blocking
  fix above, but not severe enough to block alone.

**From `/ponytail:ponytail-review` (over-engineering/complexity):**
- `regex_extractor.py:L32-48`: `shrink:` the quote-matching sub-pattern
  `(?:"([^"\n]{1,100})"|'([^'\n]{1,100})')` is duplicated verbatim between
  `_QUOTED_TITLE_YEAR` and `_QUOTED_SPAN`, and the
  `match.group(1) or match.group(2) or ""` extraction is repeated at L94 and
  L122. Factor one `_QUOTE` sub-pattern constant reused by both compiled
  regexes, plus a one-line `_quoted_text(m)` helper for the group
  extraction.
- `regex_extractor.py:L84-139`: `shrink:` `extract()` is four structurally
  identical match → `_claim()` → build-`Candidate` blocks (14/12/9/9 lines),
  differing only in pattern, confidence constant, and title formatting. A
  single loop over `(pattern, confidence, title_fn)` config tuples would cut
  this to roughly a third of the lines.
- Everything else is in-scope and not flagged: pure stdlib `re`/string logic
  only, no IO/network/NLP dependency pulled in, `_claim()` is a minimal
  8-line interval-overlap check (nothing reinvented — stdlib has no
  equivalent), `_Span` is a trivial type alias, `_clean_list_title` is a
  plain 3-line helper. The 12 tests each cover a genuinely distinct
  behavior, no near-duplicate boilerplate like earlier subtasks had.
- `net: -20 lines possible` (both non-blocking).

**Manual verification (done directly, not delegated):**
- Read the whole of `regex_extractor.py`: confirmed every one of the four
  `Candidate(...)` constructions uses `source=source` (the method's
  parameter) — `source` is never hardcoded to `SourceTag.CAPTION` or any
  other fixed value anywhere in the file.
- Confirmed `extract("", source)` returns `[]` via the `if not text: return
  []` guard, and traced that no branch in any of the four passes can raise
  for ordinary string input (pure `re.finditer`/string ops, no indexing that
  could go out of bounds); re-ran
  `extractor.extract("just some plain lowercase text...", SourceTag.CREATOR_COMMENT)`
  directly and confirmed `[]` with no exception.
- Hand-traced the HIGH-confidence `raw_text` round-trip against
  `tmdb/resolver.py`'s `_extract_year_hint()` (`r"\((\d{4})\)"` via
  `re.search`): for the common case (title with no embedded parenthetical),
  `f"{title} ({year})"` round-trips correctly — confirmed with
  `'"Parasite" (2019)'` → year 2019. The round-trip breaks only in the edge
  case documented as the non-blocking finding above.
- Independently ran `python3 -m pytest tests/unit -q`: `64 passed`, matching
  the build report's count exactly, run directly in this review pass.

Cycle 0 outcome: **NEEDS FIXES** (addressed by `### Fixes applied` above —
fix cycle 1 — producing the working tree re-reviewed below).

#### cycle 2 review (current — fresh re-review of the post-fix working tree)

Scope: the full current diff — `reel2movie/text_extraction/regex_extractor.py`
(new file) plus the companion one-line change to the already-committed
`reel2movie/tmdb/resolver.py` (`_extract_year_hint()`: `.search()` →
`.findall()[-1]`). Run as a clean re-review, not a continuation of the cycle
0/1 session: fresh `/code-review` (medium) and `/ponytail:ponytail-review`
invocations against the current diff, plus independent manual verification
(the fix's own claimed repro, the resolver's existing tests, an edge case the
fix might have missed, and a from-scratch full-suite run).

**Primary question — is the cycle 0 BLOCKING bug actually fixed? Yes, confirmed by direct reproduction:**
```python
extractor.extract('5 movies like Inception:\n1. The Lord of the Rings (2001)\n2. Interstellar\n', SourceTag.CAPTION)
# -> [Candidate(raw_text='The Lord of the Rings (2001)', source=SourceTag.CAPTION, confidence=0.9),
#     Candidate(raw_text='Interstellar', source=SourceTag.CAPTION, confidence=0.6)]
```
Exactly the two candidates the fix report claims — no dropped MEDIUM
candidate, no truncated `"Rings (2001)"` HIGH candidate. The root-cause fix
(adding connector words to `_UNQUOTED_TITLE_YEAR` so it claims the full
title span itself, leaving nothing for the numbered-list pass to collide
with) holds up under direct re-execution, not just re-reading the diff.

**From `/code-review` (correctness) — three new findings, all reproduced, none blocking:**
- **Non-blocking** — `regex_extractor.py` L32-55 (`_QUOTED_TITLE_YEAR` /
  `_QUOTED_SPAN`): both quote regexes match straight ASCII quotes only
  (`"`/`'`), not Unicode curly quotes (`“ ” ‘ ’`) that iOS/many keyboards
  auto-substitute. Reproduced: `extractor.extract('Check out “Inception” (2010) tonight', SourceTag.CAPTION)`
  → `[]`, not the expected HIGH `Inception (2010)`. Not in `brainstorm.md`'s
  documented hard-case list. Judged non-blocking under the same standard
  cycle 0 used: the failure mode is "no answer" (silent `[]`), not "wrong
  confident answer" — the pipeline can still fall through to the next
  waterfall source, it just loses this specific signal. Worth a follow-up
  (add curly-quote variants to the quote character classes) but doesn't
  block this subtask.
- **Non-blocking** — `tmdb/resolver.py` `_extract_year_hint()` docstring:
  the comment's claim that `raw_text` is "always" built as
  `f"{title} ({year})"` is only true for the two HIGH-confidence candidate
  paths. The two MEDIUM paths (`_QUOTED_SPAN`, `_NUMBERED_LIST`) set
  `raw_text` to the bare title with **no** year appended at all — confirmed
  by reading `regex_extractor.py` L126-144. So the "searching from the
  right is unambiguous" justification doesn't universally hold for every
  candidate source, only for HIGH ones; it just happens to be harmless for
  MEDIUM candidates in the common case (no parenthesized year in the raw
  title → `findall` returns `[]` → `None`, same as before). A contrived
  MEDIUM candidate whose title itself contains two parenthesized years would
  still get an arbitrary (last, not "real") year hint — no worse than the
  old leftmost-match behavior, just not the clean invariant the docstring
  claims. Cosmetic/documentation-accuracy issue, not a functional regression.
- **Non-blocking** — `regex_extractor.py` L47-50 (`_UNQUOTED_TITLE_YEAR`):
  the title-run capture group can exhibit quadratic-time backtracking on
  long runs of capitalized words with no closing `(YYYY)` (measured ~2.4s on
  a synthetic 4000-word all-caps input vs. ~30ms at Instagram's actual
  ~2200-char caption cap). Latent risk only — not a demonstrated issue at
  the input sizes this module is actually fed, per `brainstorm.md`/the
  ingest subtask's caption-length bound.

**From `/ponytail:ponytail-review` (over-engineering/complexity) — same two findings as cycle 0, still present, still non-blocking:**
- `regex_extractor.py:L32-55`: `shrink:` the quote-matching sub-pattern is
  still duplicated verbatim between `_QUOTED_TITLE_YEAR` and `_QUOTED_SPAN`,
  and `match.group(1) or match.group(2) or ""` is still repeated at two
  call sites. One `_QUOTE` constant + a 1-line `_quoted_text(m)` helper
  would remove the duplication.
- `regex_extractor.py:L98-144`: `shrink:` `extract()` is still four
  structurally identical match → `_claim()` → build-`Candidate` blocks. A
  loop over `(pattern, confidence, title_fn)` tuples would cut this to
  roughly a third of the lines.
- `tmdb/resolver.py`'s `.search()` → `.findall()[-1]` change itself: lean,
  a 2-line diff, nothing to cut.
- `net: -20 lines possible` (both findings carried over unchanged from cycle
  0 — the fix report explicitly deferred them as out of scope for this fix
  cycle, and that's still a reasonable call: neither is blocking, and fixing
  the real bug took priority).

**Manual verification (done directly in this cycle, not trusted from any report):**
- Ran the exact repro from the task's instructions (above) — matches the
  fix report's claimed output exactly, confirming the BLOCKING bug from
  cycle 0 is genuinely fixed, not just re-described as fixed.
- `python3 -m pytest tests/unit/tmdb/test_resolver.py -v`: **6 passed**
  (`test_extracts_year_hint_from_candidate_text`,
  `test_no_year_hint_when_no_parenthesized_year_present`,
  `test_maps_winning_result_to_resolved_movie`,
  `test_returns_none_when_nothing_resolves`,
  `test_returns_none_when_best_result_is_low_confidence`,
  `test_year_hint_uses_last_parenthesized_year_not_first`) — the
  `resolver.py` change does not regress any of its own original tests.
- Read `_extract_year_hint()`'s new `findall()[-1]` logic for the specific
  edge case the task flagged — zero parenthesized years in `raw_text` at
  all. `matches[-1] if matches else None` guards this explicitly:
  `findall` returns `[]` on no match, the conditional short-circuits, no
  `IndexError`. Confirmed directly:
  ```python
  _extract_year_hint('Interstellar')                    # -> None
  _extract_year_hint('')                                  # -> None
  _extract_year_hint('Some title without any year')        # -> None
  ```
  No exception in any case. This was already correct in the fix as applied
  (not a residual bug) — the fix report's logic holds.
- Independently ran `python3 -m pytest tests/unit -q` from scratch (not
  trusting the reported 68): **68 passed in 0.38s**, matching the fix
  report's count exactly.

VERDICT: ACCEPTABLE

### Fixes applied

Fix cycle 1 (this pass), addressing the review findings above:

- **Blocking fix** — `regex_extractor.py`: `_UNQUOTED_TITLE_YEAR` now allows
  a small, explicit set of lowercase connector words (`of`, `the`, `and`,
  `a`, `an`, `in`, `on`, `to`, `for`, `at`, `by`, `vs`, `with`) *inside* a
  title-case run, in addition to further uppercase-leading words. Chose
  option (b) from the review's two suggested fixes (loosen the
  unquoted-HIGH pattern) over option (a) (give the numbered-list pass
  priority to re-claim/override a smaller span) because it's strictly
  simpler: no change to `_claim()`'s overlap semantics or to the
  numbered-list pass at all, and it fixes the bug at its root (the
  unquoted-HIGH pass now captures the *correct, full* span on its own
  first pass, so there's nothing left for the numbered-list pass to need
  to re-claim). For `"1. The Lord of the Rings (2001)"`, the unquoted-HIGH
  pass now matches the entire `"The Lord of the Rings (2001)"` span in one
  go (title="The Lord of the Rings", year=2001); the numbered-list pass
  then correctly sees that span already claimed and skips it, avoiding a
  duplicate rather than dropping the title. Net effect on the review's
  exact reproduction:
  ```python
  extractor.extract('5 movies like Inception:\n1. The Lord of the Rings (2001)\n2. Interstellar\n', SourceTag.CAPTION)
  # now -> [Candidate(raw_text='The Lord of the Rings (2001)', confidence=0.9),
  #         Candidate(raw_text='Interstellar', confidence=0.6)]
  ```
  Verified by hand that this does **not** reintroduce/worsen the
  documented sentence-initial-word false positive: connector words are
  lowercase literals matched case-sensitively, so they only extend a
  chain across a *lowercase* connector, never add a new *uppercase*
  leading word — `"Watch Inception (2010) tonight"` still (unchanged)
  produces `"Watch Inception (2010)"`, the same pre-existing accepted
  limitation as before, not a new or worse one. Also manually re-verified
  `"I just watched Inception (2010) last night"` still correctly yields
  just `"Inception (2010)"` (the lowercase "just"/"watched" aren't in the
  connector allowlist, so the chain still resets there as before).
- **Non-blocking fix** — `tmdb/resolver.py`: `_extract_year_hint()` now
  uses `_YEAR_IN_PARENS.findall(raw_text)` and takes the **last** match
  (`matches[-1]`) instead of `.search(...)`'s leftmost match. Fixed in
  `resolver.py` rather than `regex_extractor.py` because the real bug was
  purely which match `_extract_year_hint()` picks: `raw_text` is already
  built as `f"{title} ({year})"` with the real release year appended at
  the very end regardless of what the title itself contains, so searching
  from the right is unambiguous and required no change to
  `regex_extractor.py`'s output format at all. One-line-shaped change
  exactly as the review anticipated. Verified
  `tests/unit/tmdb/test_resolver.py` (6 tests, including a new regression
  test for this exact case) and the full suite both still pass — no
  existing resolver test assumed leftmost-match behavior.
- **Not done (ponytail non-blocking, #3)** — the duplicated quote-pattern
  sub-regex and the four near-identical match→claim→build blocks in
  `extract()` were left as-is. Neither fix fell out naturally from fixing
  #1 (the #1 fix only touched `_UNQUOTED_TITLE_YEAR`'s pattern body, not
  `extract()`'s control flow or the quote-matching patterns), and the
  instruction was explicit not to scope-creep into a refactor here.
- Added regression tests: `tests/unit/text_extraction/test_regex_extractor.py`
  — `test_numbered_list_title_with_connector_words_and_year_is_not_dropped`,
  `test_sentence_initial_word_false_positive_not_worsened`,
  `test_quoted_title_containing_own_parenthesized_year_uses_trailing_year`;
  `tests/unit/tmdb/test_resolver.py` —
  `test_year_hint_uses_last_parenthesized_year_not_first`.

Ran `python3 -m pytest tests/unit -q`:

```
....................................................................     [100%]
68 passed in 0.46s
```

(64 pre-existing + 4 new regression tests, all passing. Also ran
`python3 -m pytest tests/unit/tmdb/test_resolver.py -v` specifically per
the fix instructions: 6 passed, confirming the `resolver.py` change didn't
break any of its existing tests.)

### Open questions / risks
- **Sentence-initial capitalized word adjacent to an unquoted title is a
  real false-positive source for the unquoted `Title (YYYY)` HIGH pattern.**
  E.g. `"Watch Inception (2010) tonight"` matches `"Watch Inception"` as
  the title (both words satisfy "starts with uppercase," with no lowercase
  word between them to break the chain), not just `"Inception"`. This was
  caught while writing this subtask's own tests (first draft of
  `test_unquoted_title_with_year_is_high_confidence` used exactly this
  phrasing and failed) and worked around in the test by choosing input
  where a lowercase word naturally separates the sentence opener from the
  title (`"I just watched Inception (2010) last night"`), rather than by
  further complicating the regex. A true fix would need real sentence
  structure/POS awareness (overkill for a stdlib-`re`-only module per
  spec) — flagging as a known false-positive source for real-world
  captions phrased as imperatives/openers directly against the title
  (`"Watch Dune (2021) now"`, `"See Oppenheimer (2023) today"`), worth
  revisiting only if the resolved-movie accuracy numbers from a later
  subtask show this is a frequent real-world pattern. The **quoted**
  `"Title" (YYYY)` HIGH pattern is unaffected by this (quote marks
  unambiguously bound the title), so this only risks unquoted captions.
- **Unquoted titles with lowercase connector words** (`"The Lord of the
  Rings (2001)"`) don't fully match the unquoted HIGH pattern, since
  "of"/"the" break the all-words-capitalized chain — in that example the
  regex would end up matching just `"Rings (2001)"` as its title (the last
  all-caps-chain run immediately before the parens), losing the real
  title's first three words. Deliberately not special-cased (would need a
  connector-word allowlist, adding complexity for a stdlib-regex module
  the spec asked to keep simple) — captions phrased this way will still
  often get caught by the **quoted** pattern instead if the creator used
  quotes, or will simply miss HIGH tier and fall through unextracted
  (returns fewer candidates, not a crash or wrong-but-confident answer).
  **UPDATE (fix cycle 1):** this is now special-cased — see "Fixes
  applied" above. `_UNQUOTED_TITLE_YEAR` allows a small lowercase
  connector-word allowlist inside the title-case run, so
  `"The Lord of the Rings (2001)"` now matches as a single full span.
  Left as historical context for *why* the numbered-list cross-pass bug
  was possible in the first place.
- **Quoted-span false positives from contractions**: a stray apostrophe in
  a contraction (e.g. `"it's"`) could in principle pair with an unrelated
  later single-quote on the same line and get misread as a quoted-title
  delimiter. Mitigated (not eliminated) by capping quoted-span length at
  100 chars and disallowing the match from crossing a newline, but not
  fully solved — no test case surfaced an actual failure from this, so not
  chasing it further per the "keep simple" instruction; flagging in case a
  later real-caption smoke test (subtask 8) hits it.
- **Numbered-list titles aren't resolved-year-checked for correctness** —
  `_clean_list_title()` only strips whitespace/quotes/trailing punctuation;
  if a list line happens to contain `"Title (YYYY)"` text that for some
  reason wasn't already claimed by an earlier HIGH pass (shouldn't happen
  in the current implementation, since both HIGH regexes scan the full
  text first and claim their spans before the numbered-list pass runs),
  it would still carry the year substring through at MEDIUM confidence,
  which is harmless (resolver's year-hint regex would still find it) but
  worth noting as an implicit (not test-locked) invariant between the pass
  ordering and this behavior.
- This extractor does not attempt to deduplicate semantically-identical
  candidates that differ only in exact text (e.g. the same title appearing
  once quoted in a caption and once unquoted in a numbered list within the
  *same* text block, where the two spans don't textually overlap so both
  survive `_claim()`). Per-source dedup/aggregation across candidates is
  explicitly the pipeline's job (subtask 7), not this module's.
