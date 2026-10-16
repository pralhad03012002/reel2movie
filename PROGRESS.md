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

---

## Subtask 4 — ingest/ — status: done

### What's built
Files created:
- `reel2movie/ingest/__init__.py` — package docstring only.
- `reel2movie/ingest/ytdlp_client.py` — `YtDlpClient`, the **only** module
  in `reel2movie` that imports `yt_dlp` directly. `extract_info(url, *,
  cookies_file: Path | None = None, download: bool = False) -> dict`
  builds an options dict (`getcomments: True` always; `skip_download: not
  download`; `cookiefile: str(cookies_file)` only when `cookies_file` is
  given; `quiet`/`no_warnings: True` to keep stdout clean) and runs
  `with yt_dlp.YoutubeDL(opts) as ydl: return ydl.extract_info(url,
  download=download)`. Returns yt-dlp's raw dict unmodified — no
  normalization happens here, that's `instagram.py`'s job.
- `reel2movie/ingest/instagram.py` — `InstagramIngestor`, structurally
  satisfying the `Ingestor` Protocol (`fetch_metadata`, `ensure_video`),
  built on a `YtDlpClient` instance taken as a constructor param (so tests
  inject a fake, never importing `yt_dlp` themselves). Takes an optional
  `cookies_file: Path | None` constructor param and passes it through to
  `client.extract_info(...)` on every call — never calls
  `config.get_instagram_cookies_file()` itself, matching the same
  separation-of-concerns pattern `tmdb/client.py` uses for the TMDB token
  (per subtask spec and Subtask 1's own open question flagging this).
  - `fetch_metadata(url)` calls the client with `download=False`, then
    maps the raw dict to `IngestResult`: `caption` <- `description`,
    `creator_account_id` <- `uploader_id`, `comments` <- each item in
    `comments` mapped to a `Comment`, `duration_seconds` <- `duration`,
    `video_path=None`, `platform=Platform.INSTAGRAM`, `url=url` (the
    original input string, not anything yt-dlp reports back, so the
    output url always matches exactly what the caller passed in).
  - `ensure_video(result)` calls the client again for `result.url` with
    `download=True`, then reads the local path from
    `requested_downloads[0]["filepath"]` if present, falling back to the
    top-level `_filename` key, raising `IngestError` if neither is found.
  - `IngestError(RuntimeError)` — raised (a) in `fetch_metadata` if
    `uploader_id` is missing/falsy (can't identify the creator account at
    all), (b) in the per-comment mapping if a comment is missing `id` or
    `author_id` (rather than silently coercing `None` to the string
    `"None"`, which would quietly corrupt the "is this the creator's own
    comment" check downstream), and (c) in `ensure_video` if yt-dlp's
    download response has neither `requested_downloads[...].filepath` nor
    `_filename`. All three are "don't produce a garbage result" guards per
    the subtask spec, not an exhaustive validation of every field.
- `tests/fixtures/instagram_post_sample.json` — a hand-constructed,
  **not-a-real-scrape** fixture (documented as such via its own
  `_fixture_note` key, plus here), modeled on yt-dlp's documented/typical
  Instagram extractor output shape. Contains `description`, `uploader_id`,
  `duration`, and a 3-entry `comments` list: one top-level comment
  (`parent: "root"`) from the **same** `author_id` as the post's
  `uploader_id` (`cinephile_creator`) — the creator's-own-comment case the
  waterfall cares about — one top-level comment from a different author,
  and one reply (`parent` set to the second comment's `id`, not `"root"`)
  to exercise `is_reply` derivation.
- `tests/unit/ingest/__init__.py` — empty, for pytest discovery.
- `tests/unit/ingest/test_ytdlp_client.py` — 6 tests, with
  `yt_dlp.YoutubeDL` patched out entirely (a `MagicMock` configured to
  support the `with ... as ydl:` context-manager protocol) so no real
  `YoutubeDL` is ever constructed and nothing can touch the network.
  Covers: `getcomments: True` always set; `skip_download` is `True` when
  `download=False` and `False` when `download=True`; `cookiefile` is set
  to `str(cookies_file)` when given and omitted entirely when
  `cookies_file=None`; `ydl.extract_info(url, download=download)` is
  called with exactly those arguments; the raw dict yt-dlp "produces" is
  returned unchanged (identity-checked, not just equality).
- `tests/unit/ingest/test_instagram.py` — 15 tests against a
  `FakeYtDlpClient` test double (same `extract_info(url, *, cookies_file,
  download)` signature as the real client, records every call, returns a
  canned metadata or download dict depending on the `download` flag) fed
  the JSON fixture above. Covers: `caption`/`creator_account_id`/
  `duration_seconds`/`platform`/`url`/`video_path=None` field mapping;
  per-comment `author_id`/`text`/`like_count` mapping; `is_reply=False`
  for both `parent: "root"` comments; `is_reply=True` for the reply whose
  `parent` is a comment id; a missing `parent` key treated as top-level;
  `like_count` defaulting to `None` when absent; `cookies_file` passed
  through to the client on both `fetch_metadata` and `ensure_video` calls;
  `IngestError` raised (with a message-content check via
  `pytest.raises(..., match=...)`) when `uploader_id` is missing and when
  a comment is missing `author_id`; `ensure_video` resolving the path from
  `requested_downloads[0].filepath`, falling back to `_filename`, and
  raising `IngestError` when neither is present.

Ran `python3 -m pytest tests/unit -q`:

```
.................................................................... [ 80%]
.................                                                    [100%]
89 passed in 0.60s
```

(68 pre-existing from Subtasks 0-3 + 21 new in `tests/unit/ingest/` — 6 in
`test_ytdlp_client.py` + 15 in `test_instagram.py` — confirming nothing
added here broke any earlier subtask's tests.)

### Field-mapping assumptions (need live verification later — not silently baked in)

Per the subtask spec's explicit instruction to surface these rather than
assume them, and the plan's own flagged risks:

- **`caption` <- `description`, not `caption`/`edge_media_to_caption`.**
  Instagram's own API field names are `caption`/`edge_media_to_caption`,
  but yt-dlp's documented extractor-normalization convention flattens
  essentially every platform's post text to a common `description` key.
  The fixture uses `description` on this assumption. **Unverified against
  a live yt-dlp Instagram response in this sandbox** — if yt-dlp's real
  Instagram extractor instead (or additionally) emits a raw `caption` key,
  `fetch_metadata` would silently read an empty/stale `description` today
  (falls back to `""`, not an error) rather than failing loudly. Worth a
  single live `yt-dlp --dump-json` run against a real reel once the user
  has cookies, specifically checking which of `description`/`caption` is
  actually populated.
- **`creator_account_id` <- `uploader_id`.** This is yt-dlp's standard
  normalized field across most extractors for "the account that posted
  this," so confidence here is higher than for `caption`, but still
  unverified live for Instagram specifically.
- **`is_reply` <- `parent` field, YouTube-extractor convention
  (`"root"` vs. a comment id).** This is the plan's own explicitly flagged
  open risk ("the reply-vs-top-level field needs explicit handling since
  it's not guaranteed as reliable as YouTube's `parent` field"). This
  subtask does NOT resolve that risk — it only implements the
  best-available mapping (YouTube's documented convention, since that's
  the one yt-dlp extractors most commonly reuse) and a safe default for
  the missing-key case (treated as top-level, since a false "top-level"
  is less damaging to the creator's-own-comment check than a false
  "reply" would be — the former risks including a stray reply as if it
  were the creator's primary comment, which still goes through TMDB
  resolution and would likely just fail to resolve or resolve to
  something a human would audit, versus the latter which would silently
  discard a real creator top-level comment that should be checked).
  **This is unverified against Instagram specifically and is called out
  here, not assumed solved.**
- **Comment `author_id`/`text`/`id` key names** — used as given in the
  subtask spec's "likely" wording. The fixture's shape matches; a live
  response could use different key names (e.g. `author` vs `author_id`
  for the identifier used for matching), which would surface as a loud
  `IngestError` (missing `author_id`) rather than a silent wrong mapping,
  by design.
- **`ensure_video` path extraction** — `requested_downloads[0].filepath`
  is yt-dlp's modern documented convention when `download=True`;
  `_filename` is the older/alternate key some extractor paths still set.
  Checking both, in that order, is a documented hedge, not a guess — but
  neither has been exercised against a real yt-dlp download in this
  sandbox.

### Review findings (latest pass)

Reviewed via `/code-review` (medium, forked) on the current diff
(`reel2movie/ingest/{__init__,ytdlp_client,instagram}.py`,
`tests/fixtures/instagram_post_sample.json`, `tests/unit/ingest/`),
`/ponytail:ponytail-review` on the same diff, a hand-trace of
`fetch_metadata()` against `tests/fixtures/instagram_post_sample.json`
field-by-field, targeted greps for the yt-dlp import boundary and the
cookies-file separation-of-concerns rule, a grep of the test suite for any
real `yt_dlp.YoutubeDL(` construction, and a fresh, independent
`python3 -m pytest tests/unit -q` run (89 passed, run directly — twice,
once plain and once with `python3 -I` for import isolation — not just
trusted from the build report).

**From `/code-review` (correctness) — two findings, both reproduced, neither blocking:**
- **Non-blocking** — `instagram.py` L70 (`_to_comment` via the list
  comprehension in `fetch_metadata`): a `None` entry inside yt-dlp's
  `comments` list (some extractors represent a deleted/redacted comment
  this way) crashes with an unhandled `AttributeError: 'NoneType' object
  has no attribute 'get'` instead of the module's own `IngestError`.
  Verified directly: `fetch_metadata` with `comments: [None, {...}]`
  raises `AttributeError`, not `IngestError`. This is adjacent to, but
  distinct from, the explicitly-tested "missing required field inside a
  present comment dict" case (which does correctly raise `IngestError` —
  confirmed by `test_fetch_metadata_raises_ingest_error_when_comment_missing_author_id`).
  Judged non-blocking: not reproduced against any realistic Instagram
  yt-dlp shape in this sandbox (speculative edge case, same standard
  applied to other unverified-shape risks already logged below), and the
  failure mode is "loud crash," not "silent wrong data" — cheap to harden
  later with a `raw is None or` guard before the field-level checks.
- **Non-blocking** — `instagram.py` L63/76 vs. L98-99: `creator_account_id`
  is assigned straight from `info.get("uploader_id")` with no `str()`
  coercion, unlike `Comment.id`/`Comment.author_id` two lines later which
  are deliberately `str()`-wrapped. Verified directly: a canned
  `uploader_id: 12345` (int) yields `type(result.creator_account_id) is
  int`, violating `IngestResult.creator_account_id: str`'s declared type.
  Real consequence if it ever fires: the pipeline's later
  "is this the creator's own comment" waterfall step (subtask 7) would
  compare `creator_account_id` against `Comment.author_id` (always a
  `str`), and an `int != str` comparison would silently never match even
  when the IDs really are the same account — a quiet correctness bug, not
  a crash. Judged non-blocking only because the current fixture (and all
  15 `test_instagram.py` tests) always supplies a string `uploader_id`, so
  nothing in the actual test suite demonstrates this; still, flagging it
  as a cheap, worth-doing fix (`str(uploader_id)`, matching the pattern
  already used for the other two id fields) before this is exercised
  against live Instagram data.

**From `/ponytail:ponytail-review` (over-engineering/complexity):**
- `tests/unit/ingest/test_instagram.py:L43-233`: `shrink:` 12 of the 15
  tests hand-build the identical
  `fixture = _load_fixture(); client = FakeYtDlpClient(metadata_response=fixture); ingestor = InstagramIngestor(client)`
  triple before doing anything test-specific. Two `@pytest.fixture`s
  (`fixture`, `ingestor`) injected by parameter name would cut this
  boilerplate to zero lines per test for those 12 call sites.
- `tests/unit/ingest/test_instagram.py:L85,99,111`: `shrink:` the same
  `by_id = {c.id: c for c in result.comments}` lookup is rebuilt from
  scratch in three separate tests. Minor; folding it into the proposed
  `ingestor`-fixture helper (or a tiny local helper) would save a couple
  more lines.
- Everything else (`ytdlp_client.py`'s single-method wrapper, `_to_comment`
  as a static helper, `IngestError` as a plain `RuntimeError` subclass with
  no custom attributes, `test_ytdlp_client.py`'s shared
  `_patched_youtubedl()` helper already reused across 5 tests) is minimal
  and load-bearing — no reinvented stdlib, no unneeded dependency, no
  speculative abstraction.
- `net: -20 lines possible` (test-boilerplate only; both findings
  non-blocking, same deferred-duplication pattern already accepted in
  Subtasks 0-3's reviews).

**Field-mapping correctness — hand-traced against
`tests/fixtures/instagram_post_sample.json` (not just read off the test
assertions):**
- Fixture: `description = 'You need to watch "The Matrix" (1999) this
  weekend! #moviereview'`, `uploader_id = "cinephile_creator"`,
  `duration = 42.5`, 3 comments (ids `...001`/`...002`/`...003`).
- Traced `fetch_metadata()` by hand against this fixture: `caption` =
  `info.get("description") or ""` → the exact string above (confirmed
  correct, matches `test_fetch_metadata_maps_caption_from_description`).
  `creator_account_id` = `"cinephile_creator"` (correct).
  `duration_seconds` = `42.5`, `platform` = `Platform.INSTAGRAM`, `url` =
  the caller's original input string (not yt-dlp's `webpage_url`) — all
  correct per spec.
- Comment-by-comment trace of `_to_comment`: comment `...001`
  (`author_id="cinephile_creator"`, `parent="root"`) →
  `is_reply = parent is not None and parent != "root"` = `True and False`
  = `False` — correct, this is the creator's own top-level comment, the
  exact case the waterfall spec cares about. Comment `...002`
  (`author_id="random_follower_22"`, `parent="root"`) → `is_reply=False`
  — correct. Comment `...003` (`parent="17895000000000002"`, a real
  comment id, not `"root"`) → `is_reply = True and True = True` — correct,
  this is the reply. All three match what `test_instagram.py` asserts,
  and the hand-trace independently confirms the test assertions are
  checking the right thing, not just that the code and tests agree with
  each other by construction.

**Error-handling verification (missing-required-field → `IngestError`, not
a raw crash or silent garbage):**
- Confirmed `fetch_metadata` raises `IngestError` (not `KeyError`) when
  `uploader_id` is absent (`info.get` + falsy check, not direct
  indexing) — traced the code path, not just the passing test.
- Confirmed `_to_comment` raises `IngestError` (not `KeyError`) when a
  present comment dict is missing `id` or `author_id` — same pattern,
  correctly using `.get()` + an explicit `is None` check rather than `[]`
  indexing that would raise `KeyError`.
- Confirmed `ensure_video` raises `IngestError` (not `IndexError`/
  `KeyError`) when neither `requested_downloads[0].filepath` nor
  `_filename` is present — uses `requested and requested[0].get(...)`
  (short-circuits on an empty list, so no `IndexError` on `requested[0]`)
  before falling back and finally raising.
- The two gaps found above (`None` list entry, un-coerced
  `creator_account_id`) are the only cases where this guarantee doesn't
  fully hold; both logged as non-blocking for the reasons given.

**Import-boundary and cookie-separation checks (grepped directly, not
inferred from reading one file):**
- `grep -rn "import yt_dlp\|yt_dlp\." reel2movie/ingest/` → every match is
  in `ytdlp_client.py` (the `import yt_dlp` line itself, its docstring,
  and the one `yt_dlp.YoutubeDL(opts)` construction). `instagram.py` only
  *mentions* `yt_dlp`/`YtDlpClient` in prose/docstrings and imports the
  `YtDlpClient` wrapper class, never `yt_dlp` itself — confirmed the
  import boundary from the plan ("ytdlp_client.py — thin wrapper around
  yt_dlp.YoutubeDL" as the sole yt_dlp-importing module) holds exactly.
- `grep -rn "get_instagram_cookies_file" reel2movie/` → the only
  definition is in `config.py`; the only other hit is a docstring mention
  in `instagram.py` ("Does not call
  `reel2movie.config.get_instagram_cookies_file()` itself") — confirmed
  `InstagramIngestor` never calls it; `cookies_file` only ever arrives via
  the constructor parameter, matching the same separation `tmdb/client.py`
  uses for the TMDB bearer token (Subtask 2's pattern).
- `grep -rn "yt_dlp.YoutubeDL(" tests/` → zero matches anywhere in the
  test suite. The only place `yt_dlp.YoutubeDL` is referenced in tests is
  as a string target for `unittest.mock.patch(...)` in
  `test_ytdlp_client.py`, never actually constructed — confirmed no real
  `YoutubeDL` instance, and therefore no live network call, is possible
  from any unit test.

**Independent test run:**
- `python3 -m pytest tests/unit -q` → `89 passed` (68 pre-existing from
  Subtasks 0-3 + 21 new in `tests/unit/ingest/`).
- Re-ran with `python3 -I -m pytest tests/unit -q` (import-isolated, no
  reliance on an ambient `sys.path`/cwd state) → also `89 passed`, same
  count, confirming the result independent of environment.

No blocking findings. Field mapping traces out correctly against the
fixture for every case the fixture exercises; the explicit missing-field
error-handling guarantee holds for every case the spec calls out; the
yt_dlp import boundary and the cookies-file constructor-only rule both
hold exactly, confirmed by grep rather than by trusting the module
docstrings' own claims. The two new findings (null comment-list entry,
un-coerced `creator_account_id`) are real but narrow, unverified-against-
live-data edge cases with cheap fixes — logged for follow-up, not blocking
this subtask.

VERDICT: ACCEPTABLE

### Fixes applied
(none yet — no blocking findings this pass)

### Open questions / risks

- **Comment-pagination risk (per the plan's "Known risks" — explicitly
  NOT solved here, and not made worse).** Instagram's comment pagination
  may surface "top"/most-liked comments first rather than chronological
  order, so on a popular reel the creator's own pinned/top-level comment
  could sit entirely outside whatever page `yt-dlp` fetches by default.
  `YtDlpClient.extract_info` passes no explicit comment-count/sort options
  to `yt_dlp.YoutubeDL` beyond `getcomments: True` — it takes whatever
  yt-dlp's own default comment-fetch behavior returns. This subtask
  neither attempts to force a specific sort order nor to paginate further
  (yt-dlp has extractor-specific `max_comments`/sort options for some
  sites, but their availability/semantics for Instagram specifically
  were not verified live, so adding one here would itself be an unverified
  assumption). Flagging explicitly per the task instructions: **this risk
  is unsolved, not silently ignored** — a later subtask (likely
  `pipeline/waterfall.py`, when it implements the "creator's own top-level
  comment" waterfall step) needs to decide how to handle the case where
  the creator's real comment simply never arrives in the fetched set, and
  should not assume `comments` is either complete or chronologically
  ordered.
- **`is_reply` reliability is still an open risk**, not resolved by this
  subtask — see the field-mapping section above. If a later live check
  shows Instagram's yt-dlp extractor doesn't populate `parent` at all
  (always `None`/absent), every comment would be treated as top-level by
  this module's conservative default, which is safe (no crash, no wrong
  data shape) but would silently make the creator's-top-level-comment
  waterfall step see replies it shouldn't.
- **`caption`/`description` key choice is unverified live** — see above;
  flagged as the first thing to check with a real `yt-dlp --dump-json`
  call once the user supplies Instagram cookies (per the plan's note that
  live Instagram verification needs the user's own session).
- **No retry/rate-limit/backoff logic** was added to `YtDlpClient` — out
  of scope for this subtask and not mentioned in the plan; each call to
  `extract_info` is a single attempt, same posture as `tmdb/client.py`'s
  `requests.get` (also no retry logic, flagged there too).
- **`YtDlpClient.extract_info` does not validate `cookies_file` existence
  or readability before handing it to yt-dlp as `cookiefile`** — Subtask
  1's open questions asked explicitly what `ingest/` should do here; this
  subtask's answer is: nothing extra — if the path doesn't exist or isn't
  readable, yt-dlp's own `cookiefile` handling will raise when
  `extract_info` actually runs, and that error propagates to the caller
  unchanged rather than being pre-validated or swallowed. No cookies-file
  validation logic was added because yt-dlp already owns that failure
  mode and duplicating it risked getting out of sync with yt-dlp's own
  error message/behavior. `cookies_file=None` is fully supported (just
  omits `cookiefile` from the options dict) for any future ingest path
  that doesn't need authenticated access.
- **No live Instagram/yt-dlp call of any kind was made in this subtask** —
  per the hard constraint, all tests use the hand-built fixture and fakes.
  Every field-mapping assumption above is therefore a documented guess,
  not a verified fact, until the user supplies real Instagram cookies and
  a live smoke test is run (expected at/after Subtask 8 per the plan).

---

## Subtask 5 — visual/frame_sampler.py — status: fixed, pending re-review

### What's built
Files created:
- `reel2movie/visual/__init__.py` — package docstring only.
- `reel2movie/visual/frame_sampler.py` — `sample_frames(video_path: Path, n:
  int, duration_seconds: float, *, output_dir: Path | None = None) ->
  list[FrameSample]`, importing `FrameSample` from `core/models.py` (not
  redefined). A private `_compute_timestamps(n, duration_seconds) ->
  list[float]` helper computes N equally-spaced timestamps within
  `[0.05 * duration, 0.95 * duration]` inclusive of both ends (`start + i *
  (end - start) / (n - 1)` for `i in range(n)`), or just `[0.5 * duration]`
  when `n == 1`. For each timestamp, `sample_frames` shells out directly to
  the `imageio_ffmpeg`-bundled ffmpeg binary (`imageio_ffmpeg.get_ffmpeg_exe()`,
  **not** any system ffmpeg — this machine has neither Homebrew nor a system
  ffmpeg, confirmed in the plan) via `subprocess.run([ffmpeg_exe, "-ss",
  str(timestamp), "-i", str(video_path), "-frames:v", "1", "-pix_fmt",
  "yuvj420p", "-y", str(frame_path)], capture_output=True, text=True)`,
  writing one JPEG per timestamp (`frame_000.jpg`, `frame_001.jpg`, ...).
  Does not use imageio's higher-level frame-reading API (awkward for
  independent arbitrary-timestamp seeks, per spec's own suggestion) — a
  direct subprocess call is the whole implementation, no retry/parallelism.
- `reel2movie/visual/frame_sampler.py`'s `FrameExtractionError(RuntimeError)`
  — raised when the ffmpeg subprocess returns nonzero, with ffmpeg's
  captured `stderr` always included in the message (never swallowed).
  Invalid input (`n < 1` or `duration_seconds <= 0`) raises plain
  `ValueError` instead, before any ffmpeg/filesystem work happens — these
  are caller-programming-error cases, not extraction failures, so a
  different, simpler exception type than `FrameExtractionError` felt right.
- `tests/unit/visual/__init__.py` — empty, for pytest discovery.
- `tests/unit/visual/test_frame_sampler.py` — 9 tests (2 of them
  `@pytest.mark.parametrize`d into 2 cases each, so 11 actual test runs):
  N-equally-spaced-within-window + evenly-spaced + files-exist-and-nonempty
  (`n=3`, duration 6.0s); `n=1` → exactly 1 frame at the midpoint;
  `output_dir=None` → the returned path still exists and is readable
  *after* `sample_frames` returns (the specific invariant the
  temp-dir-ownership decision below depends on); `n=0`/`n=-1` →
  `ValueError`; `duration_seconds=0.0`/`-1.0` → `ValueError`; a genuinely
  nonexistent video path → `FrameExtractionError` with ffmpeg's real stderr
  in the message; and a `subprocess.run`-patched nonzero-exit-code case →
  `FrameExtractionError` with the patched stderr text present in the
  message (`pytest.raises(..., match=...)`), confirming the error path
  doesn't swallow or mangle stderr even when ffmpeg itself never actually
  ran.

### Temp-directory ownership/cleanup decision

`tempfile.mkdtemp()` is used (not `tempfile.TemporaryDirectory()` as a
context manager) when `output_dir` is omitted. Reasoning, thought through
rather than picked by default: `TemporaryDirectory()` deletes the directory
(and everything in it) the instant its `with` block's `__exit__` runs — if
`sample_frames` used it internally as `with tempfile.TemporaryDirectory() as
d: ...; return samples`, the directory would be wiped *before* the function
even returns, and every `FrameSample.path` handed back to the caller would
already point at a deleted file. That would silently violate this
subtask's own "each `FrameSample.path` actually exists on disk" contract
the moment the caller tried to use it. `mkdtemp()` has no such lifetime
tied to a context manager — it creates a plain directory that persists
until something explicitly removes it, which is exactly the "caller
receives live, readable paths" behavior required here. The documented
tradeoff: the caller now owns cleanup of a temp directory it never asked
to create (it only asked for frames). This is called out in both the
function's docstring and here rather than left implicit, since it's a real
resource-leak risk if a later caller (subtask 6's
`vision_llm_detector.py`, or `pipeline/waterfall.py`) forgets to
`shutil.rmtree()` it — flagged as an open question below for whichever
subtask ends up being the actual caller.

### Fixture approach — generated fresh, nothing committed

Chose **not** to commit a binary `.mp4` fixture to `tests/fixtures/`, even
though `.gitignore` already excludes `tests/fixtures/*.mp4` and would have
allowed it. Instead, `tests/unit/visual/test_frame_sampler.py` has its own
module-scoped `sample_video` pytest fixture that generates a tiny synthetic
test video fresh into a `tmp_path_factory`-created directory every test
run, using the same bundled ffmpeg binary (`testsrc` lavfi source,
`size=64x64`, `duration=6`) that `sample_frames` itself uses — fully
offline, no download, no reliance on a pre-existing file that could go
stale or missing. This was the spec's own explicitly offered "cleaner"
alternative; picked it because it guarantees the test video is always
generated by whatever ffmpeg binary `imageio_ffmpeg` resolves to in the
*current* environment (no version-skew risk between a committed fixture
and the installed `imageio-ffmpeg` version), and leaves zero stray files
under `tests/fixtures/` (confirmed by a directory listing after a full test
run — only the pre-existing `instagram_post_sample.json` is there).

One deviation from the task's illustrative example worth flagging: the
fixture uses `rate=10`, not `rate=1`. At 1fps a 6-second video has only 6
frames total, and the 95%-of-duration timestamp (5.7s) then lands in a gap
where ffmpeg's `-ss`-before-`-i` (input-side/fast) seek — the exact
invocation style this subtask specifies — finds no frame to encode and
silently produces a missing/zero-byte output (confirmed by hand: same
command, same timestamp, 1fps source → `returncode 0` but no file written;
10fps source → succeeds). This is a real ffmpeg quirk specific to very
sparse frame grids at exactly the tail of the seek range, not a bug in
`sample_frames`'s logic — real Instagram reels are never anywhere near
1fps, so `rate=10` for the test fixture is representative of real input
while still being tiny/deterministic/offline.

Also added `-pix_fmt yuvj420p` to the extraction command (not in the task's
literal example command list). Without it, the synthetic `testsrc` fixture
(encoded by libx264 as `yuv444p`) made ffmpeg's mjpeg encoder fail with
"Non full-range YUV is non-standard" / "Error while opening encoder" and
silently write a zero-byte file — caught directly while running this
subtask's own tests, not assumed. Forcing a pixel format the mjpeg encoder
always accepts is a one-flag fix that costs nothing for normally-encoded
real-world video (the overwhelmingly common case) and fixes the synthetic
test fixture; documented inline in `frame_sampler.py` at the point the flag
is added.

### Test results

Ran `python3 -m pytest tests/unit -q`:

```
..........................................................................
..........................
98 passed in 0.99s
```

(89 pre-existing from Subtasks 0-4 + 9 new in `tests/unit/visual/`, run
both plain and with `python3 -I -m pytest tests/unit -q` for import
isolation — both gave `98 passed`, confirming nothing added here broke any
earlier subtask's tests, and no reliance on ambient `sys.path`/cwd state.)

### Review findings (latest pass)

This section holds two review passes, kept distinct rather than letting the
newer one overwrite the older (per handoff-logging convention: never destroy
history, same pattern as Subtask 3). **Cycle 0** (below) is the original
pre-fix review; its outcome is addressed by `### Fixes applied` above (fix
cycle 1) and is kept here verbatim for the record. **Cycle 2** (further
down) is a fresh, from-scratch re-review of the current working tree —
including the post-fix `exists()`/size check and the subprocess timeout —
run independently of cycle 0/1, not a continuation of them.

#### cycle 0 review (historical — pre-fix; see "Fixes applied" above for what changed in response)

Reviewed via `/code-review` (medium) on the current diff
(`reel2movie/visual/__init__.py`, `reel2movie/visual/frame_sampler.py`,
`tests/unit/visual/__init__.py`, `tests/unit/visual/test_frame_sampler.py`),
`/ponytail:ponytail-review` on the same diff, plus independent manual
verification: re-ran the full suite and the visual tests individually
(not just trusted from the build report), ran `sample_frames` directly
outside pytest against a freshly-generated synthetic video, grepped for
`get_ffmpeg_exe` to confirm the bundled binary (not a system one) is what's
actually invoked, and specifically tried to reproduce the ffmpeg
"exit 0 but writes no file" quirk the build report's own test-fixture
commentary describes (and sidesteps via `rate=10`) rather than trusting
that it's harmless.

**From `/code-review` (correctness) — BLOCKING:**
- **Blocking** — `frame_sampler.py` L127-134: `sample_frames` only checks
  `result.returncode != 0` before trusting the output file; it never
  verifies the JPEG actually exists and is non-empty. **Reproduced
  directly, not just theorized**: generated a sparse 1fps/6s synthetic
  video (`testsrc=duration=6:size=64x64:rate=1`) and called
  `sample_frames(video, n=3, duration_seconds=6.0, output_dir=...)`
  directly. The 3rd sample (timestamp 5.7s) came back as a `FrameSample`
  whose `.path.exists()` is `False` — no exception raised. Running the
  exact underlying ffmpeg command by hand confirms `returncode == 0` while
  stderr literally says `"Output file is empty, nothing was encoded (check
  -ss / -t / -frames parameters if used)"`. This is exactly the quirk
  `tests/unit/visual/test_frame_sampler.py`'s own `sample_video` fixture
  docstring (L40-50) describes firsthand from hitting it while writing the
  tests — but the fix applied there was to make the **test fixture** denser
  (`rate=10`) so the test suite never exercises this path, rather than
  making `sample_frames` itself detect/reject it. Production input (a real,
  possibly variable-fps or metadata-slightly-off reel) can still hit this,
  silently handing a `FrameSample` with a dead path downstream to
  `vision_llm_detector.py` (subtask 6). Directly violates this task's own
  acceptance bar that every returned `FrameSample.path` be a real,
  non-trivial-sized file. Needs a post-`subprocess.run` check (file exists
  and `st_size > 0`) that raises `FrameExtractionError` when violated.
- **Non-blocking** — `frame_sampler.py` L127: the per-timestamp
  `subprocess.run(command, capture_output=True, text=True)` call has no
  `timeout=`. A stalled/corrupt input could hang `sample_frames` (and its
  caller) indefinitely with no recovery short of external process kill.
- **Non-blocking** — `frame_sampler.py` L95-96: when `output_dir` is
  omitted, the `tempfile.mkdtemp()` directory is never cleaned up by this
  module (by design, per the documented caller-ownership decision below —
  not a new issue, just restating the existing open risk as a concrete
  accumulation risk, e.g. repeated test/pipeline runs piling up
  `reel2movie_frames_*` dirs in the OS temp folder).

**From `/ponytail:ponytail-review` (over-engineering/complexity):**
- No findings. The direct ffmpeg subprocess call (vs. wrapping imageio's
  higher-level API) is the leaner choice, not bloat. `_compute_timestamps`
  is a small pure function with one caller, not a speculative abstraction.
  `output_dir` is genuinely exercised by both branches in the tests, not
  unused flexibility. The two `ValueError` tests are already collapsed via
  `@pytest.mark.parametrize`. No reinvented stdlib, no unnecessary
  dependencies, no dead code. "Lean already. Ship." `net: -0 lines possible.`

**Manual verification (not just trusting the build report's explanations):**
- **Timestamp math, independently recomputed**: `_compute_timestamps(1, 8.0)
  == [4.0]` (midpoint, matches spec's n=1 decision);
  `_compute_timestamps(2, 8.0) == [0.4, 7.6]` (exactly 5%/95% of 8.0 —
  confirms the n=2 edge case lands precisely on both window bounds, no
  off-by-one); `_compute_timestamps(5, 8.0)` gave 5 values evenly spaced
  between 0.4 and 7.6. All confirmed by direct function call, not just
  reading the code.
- **`imageio_ffmpeg` (not system ffmpeg) confirmed via grep**: `grep -rn
  "get_ffmpeg_exe\|ffmpeg" reel2movie/visual/frame_sampler.py` shows
  `imageio_ffmpeg.get_ffmpeg_exe()` is called once (L100) and its return
  value (`ffmpeg_exe`) is what's placed at `command[0]` — no literal
  `"ffmpeg"` string or system-PATH lookup anywhere in the module.
- **stderr capture, confirmed by reading the code**: `subprocess.run(...,
  capture_output=True, text=True)` followed by `result.stderr` interpolated
  directly into the `FrameExtractionError` message on nonzero exit — never
  swallowed, matches the build report's claim.
- **Temp-dir lifetime reasoning (`mkdtemp()` vs `TemporaryDirectory()`),
  confirmed correct, not just trusted**: `tempfile.TemporaryDirectory()`
  used as a `with`-block would delete the directory at `__exit__`, before
  `sample_frames` returns — and even holding a `TemporaryDirectory` object
  without entering it as a context manager still risks `__del__`-triggered
  cleanup once the object is garbage-collected. `mkdtemp()` has no such
  lifetime tied to any Python object, so it's the only one of the two that
  actually satisfies "caller receives live, readable paths after the
  function returns." The build report's stated reasoning is accurate.
- **Full test suite, re-run independently**: `python3 -m pytest tests/unit
  -q` → `98 passed` (not just trusted from the build report).
  `python3 -m pytest tests/unit/visual -v` → all 9 individual tests passed
  by name: `test_sample_frames_returns_n_evenly_spaced_frames_within_window`,
  `test_n_1_returns_exactly_one_frame_at_midpoint`,
  `test_no_output_dir_uses_a_persistent_temp_dir`,
  `test_invalid_n_raises_value_error[0]`/`[-1]`,
  `test_invalid_duration_raises_value_error[0.0]`/`[-1.0]`,
  `test_nonexistent_video_path_raises_frame_extraction_error_with_stderr`,
  `test_patched_nonzero_ffmpeg_exit_raises_frame_extraction_error_with_stderr`.
- **Manual run outside pytest**: generated a fresh synthetic video
  (`testsrc=duration=8:size=320x240:rate=24`) via `imageio_ffmpeg` directly,
  then called `sample_frames(video, n=5, duration_seconds=8.0,
  output_dir=...)` directly (no pytest, no mocks). All 5 returned
  `FrameSample.path` files exist and are non-trivial JPEGs (6817-7193
  bytes each, not zero-byte) — confirms the happy path genuinely produces
  real images, not just an artifact of permissive test assertions.
  Immediately after, reproduced the blocking finding above against a
  deliberately sparse video, showing the happy-path check and the failure
  mode are both real, not hypothetical.

Cycle 0 outcome: **NEEDS FIXES** (addressed by `### Fixes applied` below —
fix cycle 1 — producing the working tree re-reviewed in cycle 2 below).

#### cycle 2 review (current — fresh re-review of the post-fix working tree)

Scope: the full current diff — `reel2movie/visual/frame_sampler.py`
(the fix-cycle-1 changes: the post-`subprocess.run` `exists()`/`st_size > 0`
check and the `timeout=30` + `except subprocess.TimeoutExpired` handling),
plus the two new regression tests in `tests/unit/visual/test_frame_sampler.py`.
Run as a clean re-review, not a continuation of the cycle 0/1 session: fresh
`/code-review` (medium) and `/ponytail:ponytail-review` invocations against
the current diff, plus independent manual verification done by direct
reproduction outside pytest (not trusting the fix report's claims) and a
from-scratch full-suite run.

**Primary question — is the cycle 0 BLOCKING bug actually fixed? Yes, confirmed by direct reproduction:**
```python
# generated testsrc=duration=6:size=64x64:rate=1 (sparse, same shape as cycle 0's repro)
sample_frames(sparse_video, n=3, duration_seconds=6.0, output_dir=out_dir)
# -> raises FrameExtractionError:
# "ffmpeg reported success (exit code 0) extracting frame at timestamp
#  5.700s from <path>, but the output file <path>/frame_002.jpg is missing
#  or empty. ffmpeg stderr: ..."
```
Called directly, outside pytest, against a freshly-generated video — not
reusing the fix report's own transcript. The original bug (silently
returning a `FrameSample` whose `.path` didn't exist, no exception) is gone:
the function now raises cleanly instead.

Also independently confirmed the timeout handling doesn't break the happy
path: the same direct-call harness against a well-formed
`testsrc=duration=6:size=64x64:rate=10` video with `n=3` returned 3
`FrameSample`s, all with `.path.exists()` true and `.path.stat().st_size`
in the 1700-1800 byte range (real JPEG content, not empty placeholders).

**From `/code-review` (correctness) — two new findings, both non-blocking:**
- **Non-blocking** — `frame_sampler.py` L107 (and by extension the
  per-iteration loop): on a mid-loop extraction failure when `output_dir`
  is omitted, the `tempfile.mkdtemp()` directory (plus any frames already
  successfully extracted in earlier iterations) is never cleaned up and its
  path is never surfaced to the caller — it leaks permanently in the OS temp
  folder. E.g. `sample_frames(video, n=3, ...)` with `output_dir=None`
  succeeds on `frame_000.jpg`/`frame_001.jpg` then raises
  `FrameExtractionError` on the third; the caller never learns the
  `mkdtemp()` path and has no way to `rmtree` it. Judged non-blocking: this
  is a disk-space leak on an already-rare failure path (the visual fallback
  itself is rare per `flow.md`), not a silently-wrong result — and it's the
  same accepted "caller never cleans up the temp dir" design decision
  already documented in "Temp-directory ownership/cleanup decision" above
  and flagged under "Open questions / risks" below, just extended from the
  success path (already accepted) to the failure path (not previously
  spelled out). Worth tightening later (e.g. `try/finally: shutil.rmtree`
  on error when `output_dir` was auto-created), but doesn't block this
  subtask under the same "wrong confident answer vs. no answer" bar used by
  every prior cycle in this file.
- **Non-blocking** — `frame_sampler.py` L162: the `exists()`/`st_size > 0`
  check only verifies the output file's current state, not that the
  *current* subprocess call actually produced it — so a stale leftover file
  from an earlier call into a reused `output_dir` could in principle mask a
  genuine current-call failure (the check would pass on old bytes). Not
  independently re-reproduced in this pass (would require constructing a
  failure mode where ffmpeg fails without truncating/removing a
  pre-existing file at the same path, which is plausible but not confirmed
  against the real binary here). Judged non-blocking: `sample_frames` is
  documented and tested as a single-call-per-batch extraction (fresh
  `frame_NNN.jpg` names each call, `output_dir=None` gets a brand-new
  `mkdtemp()` dir by default), so hitting this requires a caller to
  deliberately reuse one `output_dir` across multiple `sample_frames` calls
  with overlapping frame indices — not the documented or tested usage
  pattern, and not something any currently-built caller does (subtasks
  6/7 don't exist yet). Worth a one-line note in the docstring if a later
  subtask ever does call `sample_frames` more than once into the same
  directory.

**From `/ponytail:ponytail-review` (over-engineering/complexity) — run manually per the skill's loaded instructions:**
- No findings on the fix-cycle delta specifically. The three failure
  branches (`TimeoutExpired` except, nonzero-exit check, `exists`/`size`
  check) each build a `FrameExtractionError` message carrying genuinely
  different diagnostic info (timeout value vs. exit code+stderr vs.
  path+stderr), so collapsing them into one helper would cost clarity for
  no real line savings. The two new regression tests
  (`test_exit_code_0_but_empty_output_raises_frame_extraction_error`,
  `test_ffmpeg_timeout_raises_frame_extraction_error`) follow the exact
  mock-`subprocess.run` pattern already established by the pre-existing
  `test_patched_nonzero_ffmpeg_exit_...` test, each covering a genuinely
  distinct branch, not boilerplate repeats. "Lean already. Ship."
  `net: -0 lines possible.`

**Manual verification (done directly in this cycle, not trusted from any report):**
- Ran a direct, outside-pytest repro matching the task's instructions:
  generated a sparse `testsrc=duration=6:size=64x64:rate=1` video and a
  well-formed `testsrc=duration=6:size=64x64:rate=10` video via
  `imageio_ffmpeg.get_ffmpeg_exe()` directly (no pytest, no mocks), then
  called `sample_frames(video, n=3, duration_seconds=6.0,
  output_dir=<tmp dir>)` on each:
  - Sparse video → `FrameExtractionError` raised cleanly (message above),
    confirming the original BLOCKING bug (silent `FrameSample` pointing at
    a missing file) is genuinely fixed, not just re-described as fixed.
  - Well-formed video → 3 valid `FrameSample`s returned, each `.path`
    confirmed to exist with non-zero size (1700-1800 bytes, real JPEG
    content) — confirming the timeout/exists-check additions don't break
    the happy path.
- Independently ran `python3 -m pytest tests/unit -q` from scratch (not
  trusting the reported 100): **100 passed in 0.98s**, matching the fix
  report's count exactly.

VERDICT: ACCEPTABLE

### Fixes applied

Fix cycle 1 of 3 (per the plan's cap). Addressed all three findings from the
review pass above:

- **Blocking, fixed** — `sample_frames` now checks the output file after
  every `subprocess.run` call, not just `result.returncode`. After the
  returncode check, it verifies `frame_path.exists() and
  frame_path.stat().st_size > 0`; if either is false it raises
  `FrameExtractionError` with a message that states the timestamp, the
  video path, and `result.stderr` (captured regardless of returncode, since
  ffmpeg's stderr often explains the real failure even on a "successful"
  exit code — e.g. `"Output file is empty, nothing was encoded"`). This
  closes the exact gap the reviewer reproduced: a sparse 1fps/6s video with
  `n=3, duration=6.0` previously returned a `FrameSample` whose `.path`
  didn't exist, with no exception.
- **Non-blocking, fixed** — the per-timestamp `subprocess.run(...)` call now
  passes `timeout=30` (module-level `_FFMPEG_TIMEOUT_SECONDS = 30`; a
  single-frame extraction should never legitimately take longer). The call
  is wrapped in `try/except subprocess.TimeoutExpired`, which is re-raised
  as `FrameExtractionError` (stating the timeout value, timestamp, and video
  path) rather than letting `TimeoutExpired` propagate raw to the caller.
- **Non-blocking, confirmed as already clear, no code change** — re-read the
  `tempfile.mkdtemp()`-not-cleaned-up docstring section and the "Temp-directory
  ownership/cleanup decision" section above: both already state plainly that
  this is a deliberate caller-ownership design (the caller receives live
  paths and owns `shutil.rmtree()`-ing the directory when done), not an
  oversight, and both are flagged again under "Open questions / risks" for
  whichever subtask becomes the actual caller. Wording was judged clear
  as-is; left untouched rather than rewritten for its own sake.

Also added two regression tests to `tests/unit/visual/test_frame_sampler.py`
(both via mocking `subprocess.run`, not the timing-sensitive real sparse-video
case, per the reviewer's own suggestion):
- `test_exit_code_0_but_empty_output_raises_frame_extraction_error` — mocks
  `subprocess.run` to return `returncode=0` with stderr
  `"Output file is empty, nothing was encoded"` while never creating the
  output file; asserts `FrameExtractionError` is raised and the message
  contains that stderr text.
- `test_ffmpeg_timeout_raises_frame_extraction_error` — mocks
  `subprocess.run` to raise `subprocess.TimeoutExpired`; asserts
  `FrameExtractionError` is raised (message contains "timed out") instead of
  the raw exception propagating.

Verification performed directly (not just trusted):
- `python3 -m pytest tests/unit -q` → **100 passed** (98 pre-existing +
  2 new regression tests above; no earlier subtask broken).
- Manually reproduced the reviewer's exact scenario outside pytest: generated
  a fresh sparse `testsrc=duration=6:size=64x64:rate=1` video via
  `imageio_ffmpeg`, called `sample_frames(video, n=3, duration_seconds=6.0,
  output_dir=...)` directly (no mocks). Confirmed it now raises
  `FrameExtractionError` — message: `"ffmpeg reported success (exit code 0)
  extracting frame at timestamp 5.700s from <path>, but the output file
  <path>/frame_002.jpg is missing or empty. ffmpeg stderr: ..."` — instead of
  silently returning a `FrameSample` pointing at a nonexistent file.

Not yet done: committing to git (per the plan, commit happens only after a
module is accepted by a fresh review pass, not by the fix subagent itself).
`reel2movie/visual/` and `tests/unit/visual/` remain untracked; `PROGRESS.md`
has unstaged changes. Next step per the loop is a fresh review subagent
(cycle 2's review, not resumed) re-checking this diff.

### Open questions / risks

- **Temp-directory cleanup is entirely the caller's responsibility when
  `output_dir` is omitted**, per the decision above. `sample_frames` itself
  never deletes anything it creates. Whichever subtask actually calls this
  in the real pipeline (most likely `visual/vision_llm_detector.py` via
  subtask 6, or `pipeline/waterfall.py` via subtask 7, once a frame has
  been sent to the vision LLM and is no longer needed) needs to decide
  when it's safe to `shutil.rmtree()` the directory — not addressed here,
  since this subtask's scope is extraction only. A reasonable default
  would be: the waterfall step that calls `sample_frames` also owns
  calling `shutil.rmtree(samples[0].path.parent, ignore_errors=True)` once
  it has the vision-LLM result in hand, but that's a call for subtask 6/7,
  not assumed or implemented here.
- **`-ss`-before-`-i` (fast/input-side seek) accuracy**: this is the
  "fast but can land on the nearest preceding keyframe rather than the
  exact frame" seek mode (vs. `-i` before `-ss`, which decodes from the
  start and is frame-exact but much slower). The subtask spec explicitly
  calls for `-ss` before `-i`, so that's what's implemented — for the
  intended use case (sampling *roughly* evenly-spaced representative
  frames for a vision-LLM poster/title-card check, not needing
  frame-perfect precision), this tradeoff is the right one, but it means
  the actual extracted frame's true timestamp can differ slightly from the
  requested one on a real (non-synthetic, keyframe-sparse) video. The
  `FrameSample.timestamp_seconds` returned is always the *requested*
  timestamp, not whatever ffmpeg actually landed on — flagging this as a
  known (accepted, per spec) imprecision, not a bug.
- **Very short videos / small `n` near duration edges**: for a very short
  `duration_seconds` (e.g. under ~1s) combined with a sparse real-world
  frame rate, the same "`-ss` lands in a gap with no frame" failure mode
  hit during this subtask's own test-fixture debugging (see above) could
  in principle recur against a real low-frame-rate or very short reel,
  surfacing as a loud `FrameExtractionError` (not a silent wrong result) —
  acceptable per "no retry logic" in the spec, but worth knowing this is
  the most likely real-world failure shape if `sample_frames` ever throws
  in production.
- **No validation that `video_path` is actually a readable video file**
  before invoking ffmpeg — a nonexistent path, a non-video file, or a
  corrupt file are all funneled through the same "ffmpeg returned nonzero,
  raise `FrameExtractionError` with its stderr" path, per spec ("if the
  ffmpeg subprocess call fails/returns nonzero"). Confirmed directly (one
  of the 9 new tests) that a nonexistent path produces a clear
  `FrameExtractionError` naming the missing path, not an unrelated
  exception type.
- `imageio_ffmpeg` was already installed in this environment (confirmed via
  `python3 -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"`
  before writing any code) — no `pip install` was needed this subtask; it's
  already a `[project.dependencies]` entry in `pyproject.toml` from an
  earlier subtask, consistent with the plan.

---

## Subtask 6 — visual/vision_llm_detector.py — status: built, pending review

### What's built
Files created (nothing in `reel2movie/visual/__init__.py` touched — it
already existed from Subtask 5):
- `reel2movie/visual/vision_llm_detector.py`:
  - A local `VisionChatClient` Protocol (`@runtime_checkable`,
    `chat(self, image_path: Path, prompt: str) -> str`) — deliberately
    defined in this module, not in `core/protocols.py`, per the plan's
    "Visual detection approach" section: this is an implementation-detail
    seam specific to how `VisionLLMPosterDetector` talks to a chat-capable
    vision backend, not a pipeline-level Protocol other subpackages need.
  - `AnthropicVisionChatClient(api_key: str, model: str =
    "claude-sonnet-5-5")` — the real `anthropic.Anthropic` client is built
    in `__init__` from the `api_key` constructor parameter; **never** calls
    `config.get_anthropic_key()` itself, matching the same
    separation-of-concerns rule `config.py`'s own docstring establishes
    (callers — later `pipeline/deps.py` — own reading the env var and
    passing the key in). `chat(image_path, prompt)` reads the image file's
    bytes, base64-encodes them (`base64.standard_b64encode`), looks up the
    Anthropic `media_type` from the file's extension via a small
    `_EXTENSION_TO_MEDIA_TYPE` dict (`.jpg`/`.jpeg` → `image/jpeg`,
    `.png` → `image/png`; anything else raises `ValueError` immediately,
    rather than silently mislabeling the image to the API) — detected from
    the real extension, not hardcoded to JPEG even though
    `frame_sampler.py`'s own output is always `.jpg` today; this is called
    out explicitly in the module docstring and in a comment at the dict
    definition. Calls `self._client.messages.create(model=self._model,
    max_tokens=1024, output_config={"effort": "low"}, messages=[...])`
    with a single user message containing one `image` content block
    (`source.type: "base64"`) followed by one `text` content block (the
    prompt). Returns the concatenation of every `type == "text"` block in
    `response.content` (not just the first — a defensive choice in case a
    future model/response ever splits text across multiple blocks).
  - `CONFIDENCE_MAP = {"high": 0.8, "medium": 0.5, "low": 0.3}` plus
    `_DEFAULT_CONFIDENCE = CONFIDENCE_MAP["medium"]` as the fallback when
    the model's own confidence label is missing/unrecognized (see
    rationale below).
  - `VisionLLMPosterDetector(chat_client: VisionChatClient)` — structurally
    satisfies `core.protocols.PosterDetector` (`detect(frame: FrameSample)
    -> list[Candidate]`), no inheritance. `detect()`:
    1. Builds a fixed prompt (`_PROMPT` module constant) asking the model
       to name any movie poster/title-card/identifiable-scene visible
       (title + optional year, multiple if present), and to respond with
       **only** a JSON array (e.g. `[{"title": "...", "year": 2010,
       "confidence": "high"}]`, or `[]` if nothing found) — no prose, no
       markdown fences — with two worked examples embedded in the prompt
       text itself.
    2. Calls `chat_client.chat(frame.path, _PROMPT)`.
    3. Parses the raw text via `json.loads(raw_response.strip())` inside a
       `try/except (json.JSONDecodeError, AttributeError)` — on failure,
       logs a `logger.warning(...)` (stdlib `logging`, no new logging
       dependency) naming the frame path and the raw text, and returns
       `[]` rather than raising.
    4. If the parsed JSON isn't a `list` (e.g. the model returned a bare
       object), logs a warning and returns `[]`.
    5. For each list item: skips (with a warning, `continue`, not a raised
       exception) any item that isn't a `dict`, or whose `"title"` isn't a
       non-empty string. Reads `"year"` leniently — accepts a real `int`,
       a digit-only `str` (converted via `int()`), treats `bool` (a
       sneaky `int` subclass in Python) as "no year", and falls back to
       `None` for anything else. Builds `raw_text` as `f"{title}
       ({year})"` when a year is present, else just `title` — the exact
       format confirmed against both
       `text_extraction/regex_extractor.py` (its two HIGH-confidence
       passes build `raw_text` the same way) and
       `tmdb/resolver.py`'s `_extract_year_hint()` (reads the **last**
       `(YYYY)`-shaped substring via `_YEAR_IN_PARENS.findall(...)[-1]`),
       by reading both files before finalizing this module, not assuming
       the format from memory.
    6. Maps `"confidence"` (lower-cased, whitespace-stripped) through
       `CONFIDENCE_MAP`, falling back to `_DEFAULT_CONFIDENCE` (0.5) for a
       missing or unrecognized label.
    7. Returns the resulting `list[Candidate]`, every one with
       `source=SourceTag.FRAME_VISUAL`.
- `tests/unit/visual/test_vision_llm_detector.py` (the package's
  `tests/unit/visual/__init__.py` already existed from Subtask 5, not
  recreated) — **no live API calls anywhere**:
  - `FakeVisionChatClient` — a plain test double implementing
    `chat(image_path, prompt) -> str`, returning a canned string and
    recording the `image_path`/`prompt` it was called with.
  - `VisionLLMPosterDetector` tests via the fake: single movie with year →
    `"Inception (2010)"` at confidence 0.8, and its `raw_text` round-trips
    through `tmdb.resolver._extract_year_hint()` (imported and called
    directly, same pattern Subtask 3 used) to get back `2010`; single
    movie without year → bare `"Interstellar"` at confidence 0.5, and its
    `raw_text` round-trips through `_extract_year_hint()` to get back
    `None` (confirming the no-year case doesn't accidentally pick up a
    stray year); a multi-movie response → two `Candidate`s in order, with
    distinct confidences (high/low → 0.8/0.3); an explicit `"[]"` →
    `[]`; five distinct malformed/edge-case responses, each asserted to
    return `[]` or a filtered/degraded-but-non-crashing result rather than
    raising: plain non-JSON prose, a JSON *object* instead of an array, a
    markdown-code-fenced JSON array (the model ignoring the "no fences"
    instruction — treated as malformed per spec, not specially unwrapped),
    a list item missing `"title"` (skipped, sibling valid item still
    returned), and an unrecognized confidence string (falls back to the
    0.5 default); and a dedicated test asserting `source is
    SourceTag.FRAME_VISUAL` on every returned `Candidate` across a
    multi-movie response.
  - `AnthropicVisionChatClient` tests, clearly separated in their own
    `TestAnthropicVisionChatClient` class — mocks
    `reel2movie.visual.vision_llm_detector.anthropic.Anthropic` itself
    (via `unittest.mock.patch`), never constructs a real
    `anthropic.Anthropic()` client and never touches the network: confirms
    a real temp-file image (`tmp_path`) is read and base64-encoded
    correctly (`image_block["source"]["data"] ==
    base64.standard_b64encode(image_bytes).decode("utf-8")`), confirms the
    prompt text is passed through unchanged as the trailing `text` content
    block, confirms the default model id is exactly `"claude-sonnet-5-5"`
    and that passing `model="custom-model"` is honored, confirms `.png` →
    `image/png` media-type detection, confirms the response text is
    correctly extracted from a response object shaped like the SDK's
    (`response.content` = a list of objects with `.type`/`.text`,
    including a non-`"text"`-type block mixed in to confirm only text
    blocks are concatenated), and confirms an unsupported extension
    (`.gif`) raises `ValueError` before any encode/API-call work happens.

Ran `python3 -m pytest tests/unit -q`:

```
...............................................................................
...........................                                              [100%]
115 passed in 3.36s
```

(100 pre-existing from Subtasks 0-5 + 15 new in
`tests/unit/visual/test_vision_llm_detector.py`, confirming nothing added
here broke any earlier subtask's tests.)

### Confidence-mapping choices and rationale

- **high → 0.8, medium → 0.5, low → 0.3.** These are the extraction-layer
  confidences the pipeline's waterfall gate checks (per
  `core/models.py`'s `Candidate.confidence` docstring: "the extraction
  layer's own confidence... independent of, and prior to, any later TMDB
  match-quality score"). Chosen relative to the two other extractors
  already built: `text_extraction/regex_extractor.py` uses `HIGH = 0.9` /
  `MEDIUM = 0.6` for its own regex-based signal strength, and
  `tmdb/scoring.py`'s `MIN_MATCH_SCORE = 0.5` is a *different* gate (TMDB
  match quality, not extraction confidence) that this module's numbers
  don't need to clear directly — but picking vision-LLM confidences in the
  same rough 0.3-0.8 neighborhood as the regex extractor's 0.6-0.9 keeps
  the three extraction sources comparable on the same scale rather than
  inventing a disjoint range.
  - `high = 0.8`: deliberately kept just *below* the regex extractor's
    `HIGH = 0.9`, not above it — a clearly-read poster/title card is
    strong signal, but a vision-LLM's own self-reported "high confidence"
    on an image classification task is still one step more fallible than
    "the caption literally contains `'Title' (YYYY)'" pattern-matched
    text, so it shouldn't outrank the most explicit text signal on the
    same comparative scale.
  - `medium = 0.5`: matches the regex extractor's own `MEDIUM` tier
    conceptually (a real but less certain signal) even though the exact
    number (0.5 vs. regex's 0.6) differs slightly — chosen to sit clearly
    above a "probably noise" floor.
  - `low = 0.3`: still non-trivial (not 0.0/dropped-looking) — the model
    flagged genuine uncertainty itself, but the signal is real enough to
    pass through to the waterfall rather than being silently discarded
    here; whether 0.3 clears whatever confidence bar `pipeline/waterfall.py`
    (subtask 7, not yet built) ends up using is an open question for that
    subtask, flagged below.
  - `_DEFAULT_CONFIDENCE = 0.5` (same as `medium`) for a missing/garbled
    confidence label: treated as a middling, not-dropped, not-maximal
    guess — consistent with "don't make it so low a genuine hit never
    clears the gate, don't inflate it either" from the subtask spec.

### Malformed-response handling

Three independent failure layers, all non-raising:
1. **Whole response isn't valid JSON at all** (plain prose, a refusal
   message, a markdown-fenced block the model added despite instructions)
   → `json.loads` raises `json.JSONDecodeError`, caught, logged via
   `logger.warning(...)`, returns `[]`.
2. **Valid JSON, but not a list** (e.g. the model wrapped its answer in an
   object) → caught by an explicit `isinstance(parsed, list)` check after
   the parse succeeds, logged, returns `[]`.
3. **A list, but an individual item is malformed** (not a dict, or missing
   a usable `"title"`) → that one item is skipped with a warning
   (`continue`), siblings in the same list are still processed — a partial
   model response degrades gracefully rather than discarding the whole
   frame's result over one bad entry.

No new logging framework/dependency was added — plain stdlib
`logging.getLogger(__name__)`, matching the subtask spec's "your call on
logging mechanism, keep it simple" instruction.

### Review findings (latest pass)

Ran `/code-review` and `/ponytail:ponytail-review` against the diff
(`reel2movie/visual/vision_llm_detector.py` +
`tests/unit/visual/test_vision_llm_detector.py`, both new/untracked files,
plus this `PROGRESS.md` update), independently re-ran
`python3 -m pytest tests/unit -q`, and did the critical manual check on the
real installed `anthropic` SDK (not from memory/assumption).

**Critical manual check — `output_config={"effort": "low"}` and the
response-parsing shape, verified against the actually-installed SDK:**

- Installed `anthropic` version in this environment: **1.15.0**
  (`python3 -c "import anthropic; print(anthropic.__file__, anthropic.__version__)"`
  → `.../site-packages/anthropic/__init__.py`, `1.15.0`).
- Inspected `anthropic/resources/messages/messages.py`'s `Messages.create()`
  signature directly: `output_config: OutputConfigParam | Omit = omit` **is**
  a real, documented keyword parameter ("Configuration options for the
  model's output, such as the output format").
- Inspected `anthropic/types/output_config_param.py`:
  `OutputConfigParam` is a `TypedDict` with
  `effort: Optional[Literal["low", "medium", "high", "xhigh", "max"]]`
  (plus an optional `format` key). `output_config={"effort": "low"}` is
  therefore a **valid, well-typed call** on this installed SDK version —
  **not a bug**. The build report's claim checks out against the real
  package, not just against memory/documentation.
- Inspected the response side: `anthropic/types/message.py` declares
  `content: List[ContentBlock]`; `anthropic/types/content_block.py` defines
  `ContentBlock` as a `Union[TextBlock, ThinkingBlock, ...]` discriminated
  on `.type`; `anthropic/types/text_block.py`'s `TextBlock` has
  `text: str` and `type: Literal["text"]`. This exactly matches
  `AnthropicVisionChatClient.chat()`'s assumption (iterate
  `response.content`, filter `block.type == "text"`, read `block.text`) —
  **also not a bug**, and the module's own "Open questions" section was
  properly cautious about this rather than overconfident.
- **Non-blocking risk found while checking this (not the thing asked about,
  but adjacent and real):** `pyproject.toml`'s `dependencies` list has
  `"anthropic"` with **no version floor**
  (`requires-python = ">=3.11"` is pinned, but the SDK itself isn't, e.g.
  `"anthropic>=1.0"` or similar). `output_config` works today because
  *this* environment happens to have resolved 1.15.0, but nothing in the
  repo pins or documents that as the minimum required version — a fresh
  install that resolves an older `anthropic` release predating
  `output_config` would hit a real `TypeError` on the first live call, and
  no test would catch it (every test mocks the SDK client entirely). Flagged
  as a **non-blocking** follow-up (add a version floor to
  `pyproject.toml`), not reopening this subtask for it, since it doesn't
  affect correctness in this actual environment today.

**Independent `pytest` re-run** (not trusting the reported 115 at face
value): `python3 -m pytest tests/unit -q` → `115 passed in 2.49s`. Matches
the build report's count exactly.

**Independent `_extract_year_hint()` round-trip check** — imported
`reel2movie.tmdb.resolver._extract_year_hint` directly and called it on
sample strings in the exact shape the detector produces
(`f"{title} ({year})"` or bare `title`):
`'Inception (2010)' -> 2010`, `'Interstellar' -> None`,
`'The Matrix (1999)' -> 1999`, `'Movie With No Year At All' -> None`,
`'Weird (abc)' -> None` (non-digit parenthetical correctly ignored). Also
checked a pathological double-`(YYYY)` string
(`'Se7en (1995) (2010)' -> 2010`, i.e. it picks the **last** match) purely
as a sanity check of `_extract_year_hint` itself — not a real concern for
this module, since `VisionLLMPosterDetector.detect()` only ever appends at
most one `(year)` suffix, so this edge case can't occur in this detector's
actual output. **Round-trip confirmed correct.**

**`/code-review` findings:**

1. **(Non-blocking)** `pyproject.toml`'s unpinned `anthropic` dependency
   (same finding as above, surfaced independently by the code-review pass
   too) — real risk for future installs, not a bug in the current
   environment/tests. Tracked as a follow-up, not reopening this subtask.
2. **(Non-blocking)** `VisionLLMPosterDetector.detect()`'s year coercion
   (lines ~222-228) handles `int`, digit-only `str`, and excludes `bool`,
   but a JSON **float** year (e.g. `"year": 2010.0`, which some models emit
   despite being asked for an integer) falls through to
   `elif not isinstance(year, int): year = None` and is silently dropped
   rather than coerced. This degrades gracefully (per spec: no crash, the
   candidate is still returned, just without the year hint — the designed
   fallback behavior for "can't make sense of this field") rather than
   corrupting anything, so it's non-blocking, but worth a one-line fix
   (`isinstance(year, (int, float)) and not isinstance(year, bool)` with
   `int(year)`) in a future pass if real traffic shows models emitting
   float years.

**`/ponytail:ponytail-review` findings:**

1. **(Non-blocking, informational)** `L58-62,79-85`: `yagni:` the
   `_EXTENSION_TO_MEDIA_TYPE` dict supports `.png` in addition to `.jpg`/
   `.jpeg`, but the only real caller (`frame_sampler.py`) only ever
   produces `.jpg` today — this is speculative generality for a second
   image format that doesn't exist yet. Replacement: could hardcode
   `image/jpeg` and drop the dict/lookup/`ValueError` branch (~8 fewer
   lines) until a second frame-producing path actually needs it. Not
   treated as blocking: the code is already explicit and self-documenting
   about this choice (module docstring + inline comment both call it out
   as deliberate forward-compatibility, not an accident), it's a handful of
   lines, and it directly prevents a real failure mode (silently mislabeling
   a non-JPEG image's media type to the API) rather than adding speculative
   behavior — a defensible judgment call either way. `net: -8 lines
   possible, not taken.`
2. No other over-engineering found — the Protocol-based DI
   (`VisionChatClient`), the three-layer malformed-response handling, and
   the confidence-mapping dict all match this codebase's established,
   plan-mandated patterns (Protocol seams throughout, graceful-degradation
   requirement explicit in the subtask spec) rather than being
   module-local speculative abstraction. Lean otherwise.

**Manual spec/Protocol-contract check:**

- `VisionLLMPosterDetector.detect(frame: FrameSample) -> list[Candidate]`
  structurally satisfies `core.protocols.PosterDetector` as required.
- `AnthropicVisionChatClient` never imports `core.models`/`core.protocols`;
  `VisionLLMPosterDetector` never imports `anthropic` — confirmed by
  reading the file's imports, matching the module docstring's claimed
  separation.
- Neither class calls `config.get_anthropic_key()` — confirmed, API key is
  a constructor parameter only, matching `config.py`'s separation-of-
  concerns rule.
- All `Candidate`s returned have `source=SourceTag.FRAME_VISUAL` —
  confirmed in code and by the dedicated test.
- No live API/network calls anywhere in the test file — confirmed; the
  `anthropic.Anthropic` class itself is patched out in
  `TestAnthropicVisionChatClient`, and `VisionLLMPosterDetector` tests only
  ever touch `FakeVisionChatClient`.

VERDICT: ACCEPTABLE

### Fixes applied
(none yet)

### Open questions / risks

- **Real Anthropic SDK response shape, not verified against a live call**
  (this sandbox has no real `ANTHROPIC_API_KEY`): `AnthropicVisionChatClient`
  assumes `response.content` is iterable, each element has a `.type`
  attribute, and text-bearing elements have a `.text` attribute holding a
  plain `str` — modeled on the `anthropic` Python SDK's documented
  `Message.content: list[ContentBlock]` shape (`TextBlock` has `.type ==
  "text"` and `.text`), and on this same skill's own README excerpt read
  before writing this module. The unit tests mock this shape with
  `types.SimpleNamespace` objects rather than the SDK's real typed
  `TextBlock`/`Message` classes, so a real response whose attribute names
  or nesting differ even slightly from this assumption would not be caught
  until an actual live call is made (deferred to whichever subtask first
  runs a real smoke test — per the plan, that's expected no earlier than
  subtask 8's CLI smoke test, once the user supplies a real
  `ANTHROPIC_API_KEY`).
- **Model id `"claude-sonnet-5-5"`**: used exactly as specified in the
  subtask instructions (a real, current Claude 5 family model id, not a
  deprecated/older name). Not independently verifiable against a live
  `models.list()`/`models.retrieve()` call from this sandbox.
- **`output_config={"effort": "low"}`**: added as a cost-conscious default
  for what's a simple, repeated, low-stakes image-classification call
  (per current Claude API cost-tuning guidance: low effort is a good fit
  for "subagents or simple tasks"). Not validated against a real response
  for quality — if a later live smoke test shows frames are frequently
  missed or misread at `low` effort, this is the first knob to try
  raising (e.g. to the model's default), isolated in one place in
  `AnthropicVisionChatClient.chat`.
- **Markdown-fenced JSON is treated as malformed (returns `[]`), not
  unwrapped.** The prompt explicitly instructs the model not to use code
  fences, so this is expected to be rare in practice; a deliberate choice
  not to add fence-stripping logic preemptively (unasked-for defensive
  complexity) — if live testing in a later subtask shows the model
  frequently ignores this instruction, stripping ```` ```json ... ``` ````
  wrappers before parsing would be a small, isolated follow-up fix in
  `VisionLLMPosterDetector.detect`.
- **Confidence-mapping numbers (0.8/0.5/0.3) are not tuned against any
  real vision-LLM output** — same caveat `tmdb/scoring.py`'s
  `MIN_MATCH_SCORE` open question already flagged for its own constant:
  picked as "sensible defaults," isolated in one `CONFIDENCE_MAP` dict
  specifically so they're easy to revisit once `pipeline/waterfall.py`
  (subtask 7) defines its actual confidence gate and real frames/responses
  are available to check against.
- **No retry/backoff logic in `AnthropicVisionChatClient`** — a transient
  network error or rate limit on one frame's vision call will raise
  straight through `chat()` to `VisionLLMPosterDetector.detect()`, which
  does **not** catch it (only JSON-parsing failures are treated as
  "graceful" here — a failed *API call* is a different failure mode than
  a malformed *response*, and the subtask spec only asked for the latter
  to degrade gracefully). Whether the caller (`pipeline/waterfall.py`,
  subtask 7) should catch/retry/skip-this-frame on a raised API error is
  an open design question for that subtask, not resolved here.
- Per the plan's loop, this subtask's `### Review findings` /
  `### Fixes applied` sections are placeholders — a `/code-review` +
  `/ponytail:ponytail-review` pass (plus the usual manual spec check and
  independent test re-run) is the next step before this can be marked
  `status: done` and committed.
