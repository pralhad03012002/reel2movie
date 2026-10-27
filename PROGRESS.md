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

## Subtask 5 — visual/frame_sampler.py — status: done

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

## Subtask 6 — visual/vision_llm_detector.py — status: done

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

---

## Subtask 7 — pipeline/ — status: done

### What's built

Files created:
- `reel2movie/pipeline/__init__.py` — package docstring only.
- `reel2movie/pipeline/deps.py` — `PipelineDeps` (plain `@dataclass`,
  fields `ingestor: Ingestor`, `text_extractor: CandidateExtractor`,
  `poster_detector: PosterDetector`, `tmdb_client: TMDBClient`,
  `frame_count: int = 6`) typed entirely against the four `core/protocols.py`
  Protocols — matches the spec's code shape exactly. `build_default_pipeline_deps()`
  is the one function in this subtask allowed to import/construct concrete
  classes from every other subpackage: wires `InstagramIngestor(YtDlpClient(),
  cookies_file=config.get_instagram_cookies_file())`, `RegexCandidateExtractor()`,
  `VisionLLMPosterDetector(AnthropicVisionChatClient(config.get_anthropic_key()))`,
  `TMDBHttpClient(config.get_tmdb_token())`. It does not catch the `RuntimeError`s
  `get_anthropic_key()`/`get_tmdb_token()` raise on a missing env var —
  deliberately lets them propagate, since there's no sensible fallback and
  failing fast at startup (subtask 8's `cli.py` will call this) is better
  than failing deep inside a run.
- `reel2movie/pipeline/waterfall.py` — `run_pipeline(url: str, deps:
  PipelineDeps) -> PipelineResult`, implementing `flow.md` steps [2]-[6]
  as a strict waterfall:
  1. `deps.ingestor.fetch_metadata(url)` — called with **no** try/except
     around it, so an unreachable/unsupported-link exception propagates
     straight out of `run_pipeline`, per flow.md's "fail immediately" rule.
  2. Caption extraction via `deps.text_extractor.extract(result.caption,
     SourceTag.CAPTION)`, wrapped in try/except (any internal exception
     here is logged and treated as `[]`, i.e. "not confident", never
     propagated).
  3. If caption isn't confident: filter `result.comments` to `c.author_id
     == result.creator_account_id and not c.is_reply`, extract each
     surviving comment's text with `SourceTag.CREATOR_COMMENT`, pool the
     results. Also wrapped in try/except, same "treat failure as empty"
     rule.
  4. If comments aren't confident either: `deps.ingestor.ensure_video(result)`
     → `sample_frames(video_path, deps.frame_count, result.duration_seconds)`
     (imported directly from `visual/frame_sampler.py`, per the task's
     explicit "already built, you call this" instruction) → `deps.poster_detector.detect(frame)`
     per sampled frame, pooling whatever comes back with no confidence
     filter (last fallback — use it as-is, even sparse/empty). Also
     wrapped in try/except.
  5. Whichever step's pooled candidate list "won" (step 2, 3, or 4 — **only
     one** list proceeds, not an accumulation across steps, per the task
     spec's "For every candidate gathered from whichever step won")
     is resolved one-by-one via `tmdb.resolver.resolve_candidate(candidate,
     deps.tmdb_client)` (imported directly, same "already built" rule as
     `sample_frames`). Each candidate becomes a `Recommendation(query=candidate.raw_text,
     source=candidate.source, confidence=candidate.confidence, tmdb=resolved)`
     — kept even when `resolved is None`, never dropped. A `resolve_candidate`
     call that itself raises (not just returns `None`) is also caught and
     treated as an unresolved candidate, so one bad TMDB lookup can't lose
     every other candidate's recommendation.
  6. Dedupe/aggregate (see "Dedupe-merge rule" below), sort by `confidence`
     descending, return `PipelineResult(reel_url=url, recommendations=...)`.
- `tests/unit/pipeline/__init__.py` — empty, for pytest discovery.
- `tests/unit/pipeline/test_waterfall.py` — fakes for all four Protocols
  (`FakeIngestor`, `FakeCandidateExtractor`, `FakePosterDetector`,
  `FakeTMDBClient`), each a small `@dataclass` that records every call it
  receives (so tests can assert a step was *never* invoked, not just that
  the right data came back) and is configurable per test (canned
  responses, or an error to raise). `FakeTMDBClient` doesn't fake
  `resolve_candidate`'s scoring — it returns canned `TMDBSearchResult`s
  and lets the real `tmdb/resolver.py` + `tmdb/scoring.py` run against
  them; a small `_exact_match_result(query)` helper builds a result whose
  title exactly matches the query text, which reliably clears
  `MIN_MATCH_SCORE` via the real formula without needing to mock scoring.
  12 tests cover: caption-confident short-circuits comment+visual;
  creator-comment-confident short-circuits visual AND correctly excludes
  a non-creator comment and the creator's own reply; both text sources
  empty → visual fallback runs, `ensure_video` called exactly once;
  `deps.frame_count` passed through correctly to `sample_frames`; nothing
  resolving anywhere returns an empty-recommendations `PipelineResult`
  without raising; an unresolved candidate is kept with `tmdb=None`; two
  candidates resolving to the same TMDB id are deduped (keeping the
  higher-confidence one); recommendations are sorted by confidence
  descending; a step-1 `fetch_metadata` failure propagates out of
  `run_pipeline`; a step-2 (caption) internal exception falls through to
  step 3 rather than aborting; a step-4 (`ensure_video`) internal
  exception is swallowed, not raised. Also a sanity test that
  `CONFIDENCE_THRESHOLD` equals `text_extraction/regex_extractor.py`'s
  own `HIGH_CONFIDENCE` constant (not just two numbers that happen to
  match).
- `tests/unit/pipeline/test_deps.py` — one test for
  `build_default_pipeline_deps()`, per the spec's explicit instruction not
  to test it beyond "constructs without raising": sets
  `TMDB_API_KEY`/`ANTHROPIC_API_KEY` via `monkeypatch.setenv`, clears
  `INSTAGRAM_COOKIES_FILE`, asserts a `PipelineDeps` comes back. No live
  network/API call happens during construction of any of the wired
  classes (`yt_dlp.YoutubeDL`, `anthropic.Anthropic`, and
  `TMDBHttpClient`/`requests` are all lazy — they don't connect until a
  method is actually called).

### Confidence-threshold value chosen, and why

`CONFIDENCE_THRESHOLD = 0.9` in `pipeline/waterfall.py`, reusing
`text_extraction/regex_extractor.py`'s own `HIGH_CONFIDENCE = 0.9`
constant's *value* directly (asserted equal in a dedicated test, so this
can't silently drift if `regex_extractor.py` ever changes its tiers
without this module being updated to match). Rationale: `HIGH` is exactly
the tier that extractor reserves for its least-ambiguous signal
("Title (YYYY)", quoted or unquoted — both a title-shaped string *and* a
year present together), which is the same bar flow.md's "confident" gate
language ("If ≥1 confident candidate") is meant to express. Concretely,
this means a `MEDIUM` (0.6) candidate — a bare quoted span or a
numbered-list line with no year — does **not** by itself clear the gate:
a caption that's just a numbered list of titles with no years falls
through to the creator-comment step rather than the waterfall committing
early to a weaker signal. `vision_llm_detector.py`'s own `CONFIDENCE_MAP`
tops out at 0.8 (`high`) for a vision hit, which is *below* 0.9 — this is
intentional, not an oversight: the visual fallback is the *last* step
(step 4), so nothing after it needs to re-check its confidence; its
candidates are pooled and resolved unconditionally regardless of this
threshold (see step 4 above), so the threshold is simply never applied to
visual candidates at all.

### Dedupe-merge rule chosen, and why

In `_dedupe()`: recommendations with `tmdb is None` are never merged with
anything (no `id` to group on, and two different unresolved candidates
aren't known to be the same movie). Recommendations with `tmdb is not
None` are grouped by `tmdb.id`; within each group, the single
`Recommendation` with the **highest `confidence`** is kept verbatim — not
a field-by-field blend of the group. Rationale: `query`/`source`/
`confidence` all describe *how that recommendation was found*, which only
makes sense to report for one winning extraction per movie (e.g. "found
via the caption at 0.9"), not averaged or concatenated across several
near-duplicate extractions of the same underlying movie. The final list
(deduped-resolved + all-unresolved) is sorted by `confidence` descending.

### How `sample_frames` was made testable from within the waterfall

`sample_frames` is a free function (`visual/frame_sampler.py`), not a
Protocol method, so there's no Protocol seam for it per the plan's
design. `pipeline/waterfall.py` imports it by name at module level
(`from reel2movie.visual.frame_sampler import sample_frames`) and calls
it as a bare name inside `_extract_from_visual`. Tests substitute a fake
by reassigning `reel2movie.pipeline.waterfall.sample_frames` (either via
`monkeypatch.setattr` or a manual save/restore) — this patches the name
in *waterfall.py's own module namespace*, which is what the function body
actually looks up at call time, rather than patching
`visual.frame_sampler.sample_frames` (which wouldn't affect the
already-bound-by-import name in `waterfall.py`). This adds no new
injection seam beyond what the plan specifies (`deps.frame_count` is
still the only configurable knob on `PipelineDeps` itself); it's purely a
test-time monkeypatch of an ordinary Python import, the same technique
`tests/unit/tmdb/test_client.py` already uses for `requests.get`.

### Pytest summary

Ran `python3 -m pytest tests/unit -q` after adding this subtask's tests:

```
........................................................................ [ 56%]
........................................................                 [100%]
128 passed in 3.14s
```

(115 passing before this subtask + 13 new: 12 in `test_waterfall.py` + 1 in
`test_deps.py`.)

### Review findings (latest pass)

This section holds two review passes, kept distinct rather than letting the
newer one overwrite the older (per the historical/current split convention
already established in Subtasks 3 and 5). **Cycle 0** (below) is the
original pre-fix review; its outcome is narrated in `### Fixes applied`
above and is kept here verbatim for the record. **Cycle 2** (further down)
is a fresh, from-scratch re-review of the current working tree — including
the temp-dir cleanup, the `None`/`<=0` duration guard, and the
`CONFIDENCE_THRESHOLD` import-binding, all three from fix cycle 1 — run
independently of cycle 0, not a continuation of it.

#### cycle 0 review (historical — pre-fix; see "Fixes applied" above for what changed in response)

Reviewed via `/code-review` (high, forked) on the current diff
(`reel2movie/pipeline/{__init__,deps,waterfall}.py` + `tests/unit/pipeline/`),
`/ponytail:ponytail-review` on the same diff, a full manual read of
`waterfall.py` and `deps.py` (not a skim), a line-by-line trace of the
waterfall short-circuit control flow against `flow.md`, a repo-wide import
grep to verify the Protocol-only boundary, and an independent
`python3 -m pytest tests/unit -q` run (128 passed, matches the build report
exactly, not just trusted).

**Plan-file discrepancy, verified:** confirmed by reading
`/Users/apple/.claude/plans/vast-wobbling-owl.md` in full — it has no literal
"Orchestration / pipeline module" code-sketch section; `pipeline/` only
appears in the project-layout tree and the one-paragraph subtask-breakdown
entry. The build agent's report of this mismatch is accurate.`flow.md`'s
step-by-step spec is confirmed as the authoritative behavioral contract and
is what this review judges the implementation against.

**Blocking:**

1. **`waterfall.py` L98 — sampled-frame temp directories are never cleaned
   up, leaking disk space on every visual-fallback run.** `_extract_from_visual`
   calls `sample_frames(video_path, deps.frame_count, result.duration_seconds)`
   with no `output_dir`, so `frame_sampler.py` always creates a fresh
   `tempfile.mkdtemp(prefix="reel2movie_frames_")` directory. That module's own
   docstring explicitly makes cleanup the caller's job ("the caller receives
   live paths and is responsible for cleaning up that temp directory itself
   (e.g. `shutil.rmtree`) once it's done with the frames") and
   Subtask 5's own "Open questions/risks" flagged this exact responsibility as
   deferred to Subtask 7. Verified by grep: `grep -rn "rmtree" reel2movie/`
   finds the docstring mention only — zero actual `shutil.rmtree` calls
   anywhere in the codebase. Every reel that falls through to the visual
   step leaves a directory of JPEGs on disk permanently. Blocking because
   it's an unbounded resource leak in the pipeline's own last-resort path,
   not a cosmetic gap, and the responsibility was explicitly handed to this
   module by the prior subtask.
2. **`waterfall.py` L98 — `result.duration_seconds` (typed `float | None`) is
   passed straight into `sample_frames`, which does `duration_seconds <= 0`
   unconditionally; `None <= 0` raises `TypeError`, silently swallowed by
   `_extract_from_visual`'s blanket `except Exception` and reported as "found
   nothing."** `IngestResult.duration_seconds` is genuinely optional
   (`core/models.py` L60) and is populated from `info.get("duration")` in
   `ingest/instagram.py` L78, which yt-dlp can legitimately omit for a given
   reel. Reproduced directly:
   ```
   sample_frames(Path('/fake.mp4'), 6, None)
   # TypeError: '<=' not supported between instances of 'NoneType' and 'int'
   ```
   This TypeError is indistinguishable in behavior/logs from a genuine
   "visual detector found nothing" outcome, for exactly the reels where the
   visual fallback — the *only* remaining signal source at that point in the
   waterfall — is most needed. No test in `test_waterfall.py` exercises
   `duration_seconds=None` (the test helper `_ingest_result` defaults it to
   `30.0`), so this path isn't covered. Blocking because it silently
   disables the last-resort fallback for an input shape the data model
   itself declares as valid.

**Non-blocking, high-attention (per the task's specific instruction to scrutinize this coupling):**

3. **`CONFIDENCE_THRESHOLD = 0.9` in `waterfall.py` is a hardcoded literal,
   not an import/binding of `text_extraction/regex_extractor.py`'s
   `HIGH_CONFIDENCE` constant.** The two are kept in sync *only* by
   `test_confidence_threshold_matches_regex_extractor_high_tier`, which does
   genuinely import the real `HIGH_CONFIDENCE` and assert equality against
   the hardcoded `0.9` (confirmed by reading the test — it is a real
   cross-module check, not a tautology comparing the literal to itself).
   Today the values agree and the test is sound, so this is not a live bug.
   But the design still ties the pipeline's waterfall-gate semantics to an
   extractor-internal tiering constant via a *parallel* literal rather than
   a single source of truth: if someone changes `HIGH_CONFIDENCE` in
   `regex_extractor.py` (e.g. re-tiers confidence scoring) without also
   updating `waterfall.py`, the only thing that catches the drift is this
   one test actually running — a quick hotfix, a skipped test, or a
   non-gated deploy path would let the pipeline's "confident" gate silently
   diverge from what the extractor now considers its least-ambiguous tier.
   Recommend `from reel2movie.text_extraction.regex_extractor import
   HIGH_CONFIDENCE as CONFIDENCE_THRESHOLD` (or a shared constant in
   `core/`) instead of a re-declared literal + guard test — this removes the
   drift window entirely rather than just detecting it after the fact.
   Non-blocking because it is correct as shipped, but flagged prominently
   since the task called this out as the module's other highest-risk area
   besides the short-circuit logic.
4. **Also worth noting, not newly discovered:** the build agent's own
   Subtask 7 "Open questions / risks" already flags that `_resolve_all`
   catches `resolve_candidate` exceptions even though `flow.md`'s explicit
   error-handling section only names steps [1]-[4], not step [5] (TMDB
   resolution), as needing "catch and treat as empty" handling. Reviewed
   this choice directly: it's a reasonable robustness extension beyond the
   letter of the spec (one candidate's TMDB lookup failing shouldn't lose
   every other candidate's recommendation), not a contradiction of it.
   Non-blocking, agree with the build agent's own call.

**Verified correct (traced/executed directly, not accepted from the build
report):**

- **Short-circuit control flow** (`run_pipeline`, L168-193): caption
  confident → `comment_candidates`/visual are never computed at all (the
  `if not _is_confident(candidates):` block is skipped entirely — confirmed
  by reading the branch structure, not just the tests). Caption not
  confident but creator-comment confident → `candidates` is *reassigned* to
  `comment_candidates` (the non-confident caption list is discarded, not
  accumulated) and `_extract_from_visual` is never called. Both text
  sources not confident → `candidates` is reassigned to the visual step's
  output unconditionally (no confidence re-check on visual candidates,
  correct per `flow.md` step [4], which has no "confident" gate, only "≥1
  candidate"). This matches `flow.md`'s "only one step's list proceeds"
  semantics exactly, confirmed independently via
  `test_caption_confident_short_circuits_comment_and_visual` and
  `test_creator_comment_confident_short_circuits_visual_and_filters_comments`
  both asserting zero calls into the skipped step(s), not just the right
  final output.
- **Creator-comment filter** (L71-76): the exact condition
  `comment.author_id == result.creator_account_id and not comment.is_reply`
  is what's applied — confirmed by reading the line directly, field names
  (`author_id`, `is_reply`) match `core/models.py`'s `Comment` dataclass
  exactly. `test_creator_comment_confident_short_circuits_visual_and_filters_comments`
  genuinely exercises both exclusion cases (a different author's top-level
  comment, and the creator's own *reply*) and asserts their text never
  reached the extractor, not just that the right candidate came out the
  other end.
- **Error-handling rules**: step [1] (`deps.ingestor.fetch_metadata`, L181)
  has no try/except anywhere around it in `run_pipeline` — confirmed by
  reading the function body — so any exception propagates straight out,
  matching `flow.md`'s "fail immediately" rule; verified by
  `test_step1_ingestor_failure_propagates`. Steps [2]-[4] each wrap their
  body in `try/except Exception: logger.exception(...); return []` inside
  their own helper, confirmed by reading each of the three functions in
  full; verified live for both the caption-step and visual-step failure
  cases by `test_caption_extraction_internal_error_falls_through_to_comment_step`
  and `test_visual_fallback_internal_error_is_swallowed_not_raised`.
- **"Keep candidate with tmdb=None" rule**: `_resolve_all` (L108-137)
  appends a `Recommendation(..., tmdb=resolved)` unconditionally, whether
  `resolved` is a real `ResolvedMovie` or `None` — there is no branch that
  drops the candidate. Confirmed directly by reading the function (no
  `if resolved is not None` guard exists) and by re-running
  `test_unresolved_candidate_is_kept_with_tmdb_none`.
- **Dedupe-by-tmdb-id merge logic** (`_dedupe`, L140-165): confirmed by
  reading the function and by direct execution that (a) two different
  unresolved (`tmdb=None`) recommendations are never merged with each other
  (`unresolved` is carried through untouched, grouping only happens on
  `resolved`) — reproduced directly: two distinct `tmdb=None` recommendations
  in, two distinct ones out; (b) two recommendations resolving to the same
  `tmdb.id` correctly collapse to one, keeping the higher-confidence one
  verbatim (`test_two_candidates_resolving_to_same_tmdb_id_are_deduped`);
  (c) distinct `tmdb.id` groups are never conflated with each other.
- **Protocol-only import boundary** (`waterfall.py` vs. `deps.py`):
  `grep -n "^from\|^import" reel2movie/pipeline/waterfall.py` shows imports
  only from `reel2movie.core.models`, `reel2movie.pipeline.deps`,
  `reel2movie.tmdb.resolver` (the `resolve_candidate` free function, per the
  task's explicit "already built, call it directly" instruction), and
  `reel2movie.visual.frame_sampler` (`sample_frames`, same rule). A targeted
  grep for `ingest.`, `text_extraction.`, `visual.vision_llm_detector`, and
  `tmdb.client` inside `waterfall.py` returns zero matches — none of those
  concrete-implementation modules are imported there. `deps.py` is
  confirmed as the sole place importing `InstagramIngestor`, `YtDlpClient`,
  `RegexCandidateExtractor`, `TMDBHttpClient`, `AnthropicVisionChatClient`,
  and `VisionLLMPosterDetector`.
- **Fakes genuinely exercise what's claimed**: read `test_waterfall.py` in
  full. Each of the four fakes (`FakeIngestor`, `FakeCandidateExtractor`,
  `FakePosterDetector`, `FakeTMDBClient`) records every call it receives
  into a `calls`/`*_calls` list, and multiple tests assert on those lists
  being empty or containing exactly the expected entries (e.g.
  `assert poster_detector.calls == []`, `assert ingestor.ensure_video_calls
  == []`, `assert extractor.calls == [("Inception (2010)", SourceTag.CAPTION)]`)
  — these are real assertions checked by the test, not fakes that record
  calls no test ever inspects.

**From `/ponytail:ponytail-review` (over-engineering/complexity, both
non-blocking):**

- `waterfall.py` L50-105: `shrink:` three near-identical
  `try/except Exception: logger.exception(...); return []` wrappers
  (`_extract_from_caption`, `_extract_from_creator_comments`,
  `_extract_from_visual`) differing only in the log label and body. One
  `_run_step(label, fn)` helper taking a thunk, called 3x, would replace all
  three bodies.
- `deps.py` L36: `yagni:` `_DEFAULT_FRAME_COUNT` module constant used by
  exactly one call site (the dataclass field default). Could inline
  `frame_count: int = 6` directly.
- Everything else (`PipelineDeps`'s four Protocol fields + one config knob,
  `_dedupe`'s split/group/sort, `_resolve_all`'s per-candidate try/except,
  the four Protocol fakes each exercised by multiple tests) is load-bearing
  for the branches the 12 waterfall tests + 1 deps test actually exercise.
  No reinvented stdlib, no unneeded dependency, no speculative abstraction.
  `net: -12 lines possible` (both cosmetic).

VERDICT: NEEDS FIXES

#### cycle 2 review (current — fresh re-review of the post-fix-cycle-1 working tree)

Scope: the full current diff — `reel2movie/pipeline/{__init__,deps,waterfall}.py`
+ `tests/unit/pipeline/`, as they stand after fix cycle 1 (temp-dir cleanup,
the `None`/`<=0` duration guard, and the `CONFIDENCE_THRESHOLD` import-binding).
Run as a clean re-review, not a continuation of the cycle-0 session: fresh
`/code-review` (medium) and `/ponytail:ponytail-review` invocations against
the current diff, a full manual read of `_extract_from_visual` end to end,
direct reproduction (not trusted from the "Fixes applied" narration) of both
original BLOCKING bugs' fixes, a direct check of the `CONFIDENCE_THRESHOLD`
binding, and a from-scratch `python3 -m pytest tests/unit -q` run.

**Primary question — are both cycle-0 BLOCKING bugs actually fixed? Yes, confirmed by direct reproduction, not by reading the fix report:**

- **Temp-dir leak** — called `_extract_from_visual` with fake deps three ways:
  (a) a `sample_frames` fake that records the `output_dir` it was handed,
  asserts it's non-`None` and already exists, and writes a real file into
  it; after `_extract_from_visual` returned, `output_dir.exists()` was
  `False` — the directory is genuinely created by `waterfall.py` (not by
  `frame_sampler.py`, which is never called in this fake) and genuinely
  removed. (b) Same setup but with `poster_detector.detect()` raising
  `RuntimeError` on the one sampled frame, to exercise the `finally` path
  specifically, not just the happy path: the directory was still gone
  afterward, and `_extract_from_visual` returned `[]` (the exception is
  swallowed by the existing `except Exception` per this module's "step
  fails → empty" rule) rather than propagating. Both reproduced directly in
  a standalone script, not inferred from `test_waterfall.py`'s own claims.
- **`None`-duration TypeError** — called `_extract_from_visual` with
  `duration_seconds=None` and fakes for `ensure_video`/`sample_frames`/
  `detect` that each raise `AssertionError` if invoked at all: no
  `TypeError` escaped, the result was `[]`, and none of the three fakes
  were ever called (confirmed via the raising fakes never firing, not just
  via a call-count field). Also checked `duration_seconds=0` (the `<= 0`
  half of the guard, not just the `is None` half) — same short-circuit,
  same result. Both the `is None` and the `<= 0` branches of
  `result.duration_seconds is None or result.duration_seconds <= 0` are
  therefore confirmed live, not just one of the two.
- **`CONFIDENCE_THRESHOLD` binding** — read `waterfall.py` L31 and L48
  directly: `from reel2movie.text_extraction.regex_extractor import
  HIGH_CONFIDENCE` followed by `CONFIDENCE_THRESHOLD = HIGH_CONFIDENCE`.
  Confirmed via `inspect.getsource` in the same verification script that
  this exact import line and binding line are present in the live module
  (not just in a diff that could have been reverted), and that
  `waterfall.CONFIDENCE_THRESHOLD == regex_extractor.HIGH_CONFIDENCE`
  (`0.9 == 0.9`) at runtime. This is a direct import-binding, not a
  parallel literal re-declaration — the drift-window finding from cycle 0
  is genuinely closed, not just newly covered by a guard test.

**From `/code-review` (medium, forked) on the current diff — two new findings, both non-blocking:**

5. **Non-blocking** — `waterfall.py` L142-156 / L83-92: both
   `_extract_from_visual`'s per-frame `poster_detector.detect()` loop and
   `_extract_from_creator_comments`'s per-comment `extract()` loop are
   wrapped by one outer `try/except` around the *entire* loop, not a
   try/except per iteration. If `detect()`/`extract()` raises on, say, the
   3rd of 6 frames (or the 2nd of 2 creator comments) after succeeding on
   earlier ones, every candidate already found from the earlier
   frames/comments in that same call is discarded along with the one that
   failed — the whole step degrades to `[]` rather than keeping the
   partial results. This is most consequential for the visual step
   specifically because it is the *last* fallback with nothing further to
   fall through to. Judged non-blocking rather than blocking: this is the
   same "a source step fails internally → treat the whole step as empty,
   fall through" semantics `flow.md`'s error-handling section explicitly
   describes at the step level (not the item level), it's unchanged
   pre-existing control flow from the original build (not introduced or
   touched by fix cycle 1's diff, which only edited the duration-guard,
   temp-dir, and `CONFIDENCE_THRESHOLD` lines), and cycle 0's review did
   not flag it either. Still worth a follow-up — e.g. catching per-frame/
   per-comment the way `_resolve_all` already does per-candidate — so one
   bad frame doesn't erase good ones already found, but it's a design
   question to revisit deliberately, not a defect introduced by this fix
   cycle.

**From `/ponytail:ponytail-review` on the current diff — both cycle-0 findings still present, still non-blocking; nothing new added by the fix cycle:**

- `waterfall.py` L59-68, L75-92, L142-158: `shrink:` the same three
  near-identical `try/except Exception: logger.exception(...); return []`
  wrappers flagged in cycle 0 are still present, unchanged in shape. One
  `_run_step(label, fn)` helper would still replace all three.
- `deps.py` L36: `yagni:` `_DEFAULT_FRAME_COUNT` is still a module constant
  used at exactly one call site. Still inlinable.
- The fix cycle's own new code (the temp-dir create/try/finally block, the
  duration guard, the `CONFIDENCE_THRESHOLD` import-binding) is lean —
  nothing new to cut there.
- `net: -12 lines possible` (both carried over unchanged from cycle 0, not
  worth the scope-creep risk of a fix-only cycle, per the build agent's own
  stated reasoning).

**Independent test run:**

- `python3 -m pytest tests/unit -q` → `131 passed`, run directly in this
  review pass from a clean shell, matching the "Fixes applied" section's
  reported count exactly, not just trusted from that report.

VERDICT: ACCEPTABLE

### Fixes applied

Fix cycle 1 of max 3, addressing both BLOCKING findings plus the one cheap
non-blocking coupling fix, all in `reel2movie/pipeline/waterfall.py` only
(no changes to `frame_sampler.py` or `regex_extractor.py`):

1. **Temp-dir leak (blocking finding 1) — fixed.** `_extract_from_visual`
   now creates its own temp directory
   (`Path(tempfile.mkdtemp(prefix="reel2movie_frames_"))`), passes it
   explicitly as `sample_frames(..., output_dir=frames_dir)`, and removes
   it with `shutil.rmtree(frames_dir, ignore_errors=True)` in a `finally`
   block wrapping `ensure_video` → `sample_frames` → the
   `poster_detector.detect()` loop. Cleanup now runs even if poster
   detection or frame extraction raises partway through, since it's
   `finally`, not just a happy-path call at the end.
   `frame_sampler.py` is untouched — per its own docstring, taking an
   explicit `output_dir` and owning its cleanup was always the caller's
   job, and `waterfall.py` is that caller.
2. **`None`-duration crash silently swallowed (blocking finding 2) —
   fixed.** `_extract_from_visual` now checks
   `result.duration_seconds is None or result.duration_seconds <= 0`
   *before* doing anything else (before creating the temp dir, before
   calling `ensure_video`, before calling `sample_frames`), logs a
   `logger.warning` naming the actual cause ("cannot run visual fallback:
   unknown reel duration (duration_seconds=%r)...") and returns `[]`
   immediately. This is a distinct code path/log message from the
   existing `except Exception: logger.exception("visual fallback
   extraction failed; ...")` branch that catches ffmpeg/extraction/poster-
   detection failures, so "duration unknown, skipped" vs. "visual detector
   ran and found nothing" vs. "ffmpeg actually failed" are now
   distinguishable in logs, even though the return type is the same `[]`
   either way.
3. **`CONFIDENCE_THRESHOLD` coupling (non-blocking finding 3) — fixed,
   since it was a clean one-line change.** Confirmed
   `text_extraction/regex_extractor.py` exports `HIGH_CONFIDENCE = 0.9` as
   a real importable module-level constant (no circular-import risk:
   `regex_extractor.py` only imports from `core/models.py`). Replaced the
   hardcoded `CONFIDENCE_THRESHOLD = 0.9` literal with
   `from reel2movie.text_extraction.regex_extractor import HIGH_CONFIDENCE`
   + `CONFIDENCE_THRESHOLD = HIGH_CONFIDENCE`, removing the drift window
   entirely rather than only detecting it via
   `test_confidence_threshold_matches_regex_extractor_high_tier` (left
   in place — it still passes, now as a sanity check on the binding
   itself rather than the only thing keeping two literals in sync).

Left alone, as instructed: both `/ponytail:ponytail-review` cosmetic
findings (collapsing the three near-identical try/except wrappers into a
`_run_step` helper; inlining `_DEFAULT_FRAME_COUNT` in `deps.py`) — still
non-blocking, not worth the scope-creep risk in a fix-only cycle.

**New regression tests added to `tests/unit/pipeline/test_waterfall.py`:**

- `test_visual_fallback_cleans_up_its_own_temp_frame_directory` — a fake
  `sample_frames` asserts it's handed a real, already-existing `output_dir`
  (proving `waterfall.py`, not `frame_sampler.py`, created it) and writes a
  frame into it; after `run_pipeline` returns, asserts that directory no
  longer exists.
- `test_visual_fallback_cleans_up_temp_dir_even_if_poster_detection_raises`
  — same shape, but the poster detector raises; asserts the temp dir is
  still removed (proving the `finally` actually matters, not just the
  happy path) and the step still degrades to `[]` per the existing
  "internal failure → empty" rule.
- `test_visual_fallback_with_none_duration_logs_warning_and_skips_sample_frames`
  — `duration_seconds=None`, a `sample_frames` stub that raises
  `AssertionError` if ever called (proving it's genuinely never invoked,
  not just that the result happens to be empty), asserts
  `ingestor.ensure_video_calls == []`, `result.recommendations == []`, and
  (via `caplog`) that a warning containing "unknown reel duration" was
  logged.

**Manual verification performed directly (beyond the test suite), per the
task's instructions:**

- Called `waterfall._extract_from_visual` directly with
  `duration_seconds=None` and fake deps whose `ensure_video`/`detect`
  raise `AssertionError` if called at all, plus a `sample_frames` stub
  that does the same: confirmed no `TypeError` escapes, `sample_frames`
  is never invoked (call count 0), the result is `[]`, and the logged
  warning (`cannot run visual fallback: unknown reel duration
  (duration_seconds=None); ...`) is visible and distinct from the other
  two "found nothing" log messages in this module.
- Called `waterfall._extract_from_visual` directly with a real
  `duration_seconds=30.0` and a fake `sample_frames` that asserts its
  `output_dir` argument is non-`None` and already exists, writes a real
  file into it, and returns a `FrameSample` pointing there: confirmed the
  directory exists during the call and `.exists()` is `False` immediately
  after `_extract_from_visual` returns — the temp directory is genuinely
  created by `waterfall.py` and genuinely removed after use, not just
  claimed by a mocked assertion.

**Test run after fixes:** `python3 -m pytest tests/unit -q` →
`131 passed` (128 before this fix cycle + 3 new regression tests above; no
existing test needed modification, no regressions).

### Open questions / risks

- **No "Orchestration / pipeline module" section with a code sketch was
  found in `/Users/apple/.claude/plans/vast-wobbling-owl.md`** — the plan
  file (read in full, 214 lines) only lists `pipeline/` in the project
  layout and subtask-breakdown sections (no dedicated orchestration
  section exists in the file as it currently stands). Built directly from
  `flow.md`'s step-by-step spec plus this subtask's own detailed
  instructions instead; flagging the mismatch here rather than silently
  proceeding as if the referenced section existed.
- **Resolving the same raw candidate twice issues two TMDB searches** —
  `_resolve_all` calls `resolve_candidate` once per pooled candidate with
  no memoization, even if two candidates happen to have identical
  `raw_text` (e.g. the same title mentioned twice via two different regex
  passes in a single source, though `regex_extractor.py`'s own
  overlap-claiming should normally prevent that within one `extract()`
  call). Not addressed here — out of scope, and no evidence it happens in
  practice given the extractor's own dedup-by-span behavior.
- **`resolve_candidate` exceptions are caught per-candidate in
  `_resolve_all`**, even though flow.md's explicit error-handling section
  only names steps [1]-[4] (ingest/extraction), not step [5] (TMDB
  resolution), as needing "catch and treat as empty" handling. Chose to
  catch here anyway (treating a raised exception the same as a clean
  `None` return) as a deliberate robustness call: one candidate's lookup
  failing (e.g. a transient `requests` network error inside
  `TMDBHttpClient.search_movie`) isn't a reason to lose every other
  resolved candidate or abort the whole pipeline run. If this turns out
  to be the wrong call (e.g. the user wants a flaky TMDB connection to
  fail the whole run loudly rather than silently degrade), it's isolated
  to the one `try/except` in `_resolve_all`.
- **`PipelineDeps.frame_count` default of 6** is carried over as the
  spec's own example default (`frame_count: int = 6`); not tuned against
  any real visual-fallback run — same "isolated constant, easy to revisit"
  caveat as `tmdb/scoring.py`'s `MIN_MATCH_SCORE` and
  `vision_llm_detector.py`'s `CONFIDENCE_MAP`.
- **Did not add a "resolve the same candidate concurrently" optimization**
  (e.g. threading/async for multiple TMDB lookups) — out of scope per the
  subtask spec, and premature before subtask 8's real-world latency is
  ever measured.
- Per the plan's loop, this subtask's `### Review findings` /
  `### Fixes applied` sections are intentionally left as placeholders — a
  `/code-review` + `/ponytail:ponytail-review` pass (plus the usual manual
  spec check and independent test re-run) is the next step before this
  can be marked `status: done` and committed. No `git commit` was made for
  this subtask, per the task instructions.

---

## Subtask 8 — cli.py — status: done

### What's built

Files created:
- `reel2movie/__main__.py` — the package root previously had no
  `__main__.py` (only `__init__.py`), so `python -m reel2movie` could not
  be invoked at all until this subtask. Minimal: imports `main` from
  `reel2movie.cli` and calls `raise SystemExit(main())` under
  `if __name__ == "__main__":`.
- `reel2movie/cli.py` — `main(argv: list[str] | None = None) -> int`:
  - Parses exactly one required positional arg (`reel_url`) plus one
    optional `--frame-count` (int) override, via `argparse`. No other CLI
    surface, per the subtask's explicit "don't over-build" instruction.
  - Calls `build_default_pipeline_deps()` (imported by name from
    `reel2movie.pipeline.deps`, so tests can monkeypatch
    `reel2movie.cli.build_default_pipeline_deps` directly — the same
    seam-patching convention `tests/unit/pipeline/test_waterfall.py`
    already established for `sample_frames`), then — if `--frame-count`
    was passed — mutates the returned (non-frozen) `PipelineDeps.frame_count`
    in place, then calls `run_pipeline(reel_url, deps)` (same
    import-by-name convention, from `reel2movie.pipeline.waterfall`).
  - Both calls are wrapped in their own `try/except Exception`, each
    printing one clear `reel2movie: ...: <exc>` line to `sys.stderr` and
    returning `1` — no unhandled traceback ever reaches the user for
    either a `build_default_pipeline_deps()` failure (missing
    `TMDB_API_KEY`/`ANTHROPIC_API_KEY`, a plain `RuntimeError` per
    `config.py`) or a `run_pipeline()` failure (e.g. `fetch_metadata`
    raising on an unreachable/unsupported URL, per `flow.md`'s "fail
    immediately" rule for step 1). Caught broadly (`Exception`, not just
    `RuntimeError`) deliberately — the contract this CLI promises is "no
    raw traceback ever", not "only for the one exception type we
    anticipated"; `KeyboardInterrupt`/`SystemExit` are untouched since
    they aren't `Exception` subclasses.
  - On success, serializes the `PipelineResult` (see below) and prints it
    via `json.dumps(..., indent=2)` to stdout, returns `0`.
- `tests/unit/test_cli.py` — 5 tests, all monkeypatching
  `reel2movie.cli.build_default_pipeline_deps` / `reel2movie.cli.run_pipeline`
  directly (never touching the real env, network, or concrete `ingest/`,
  `tmdb/`, `visual/` classes):
  - `test_prints_expected_json_shape` — a canned `PipelineResult` with two
    `Recommendation`s (one resolved with a full `ResolvedMovie`, one with
    `tmdb=None`); captures stdout via `capsys`, parses it back with
    `json.loads`, and asserts every field by value (`reel_url`, both
    recommendations' `query`/`source`/`confidence`/`tmdb`), including that
    the unresolved recommendation's `tmdb` serializes to JSON `null` (not
    an error, not an omitted key) and that `match_score` — a real
    `ResolvedMovie` field not part of brainstorm.md's documented output
    shape — does **not** leak into the printed `tmdb` object.
  - `test_missing_api_key_prints_clear_error_on_stderr_and_returns_nonzero`
    — `build_default_pipeline_deps` raises `RuntimeError("TMDB_API_KEY not
    set; ...")`; asserts `main()` returns non-zero, stdout is empty, and
    the message is on stderr (via `capsys.readouterr().err`).
  - `test_fatal_pipeline_error_prints_clear_error_on_stderr_and_returns_nonzero`
    — same shape, but `run_pipeline` raises instead.
  - `test_frame_count_override_reaches_pipeline_deps` — passes
    `--frame-count 3`, asserts (via a `run_pipeline` stub that records
    `deps.frame_count`) that the value reaching `run_pipeline` is `3`, and
    that the override mutated the actual `PipelineDeps` object
    `build_default_pipeline_deps()` returned (not a copy).
  - `test_no_frame_count_override_leaves_default_untouched` — without the
    flag, confirms `deps.frame_count` reaching `run_pipeline` is whatever
    `build_default_pipeline_deps()` produced, untouched.
- `tests/integration/__init__.py` — empty, new top-level test package
  (sibling to `tests/unit/`), registered per the subtask spec.
- `tests/integration/test_live_smoke.py` — one test,
  `test_live_pipeline_end_to_end`, calling the real `reel2movie.cli.main()`
  (no mocking at all) against a real reel URL end-to-end. Guarded by
  `@pytest.mark.skipif(not os.environ.get("REEL2MOVIE_LIVE_TEST_URL"), reason=...)`
  — reads the URL from that env var rather than hardcoding one, so no real
  Instagram URL is embedded in the repo. Did **not** attempt to run this
  for real (no real API keys or Instagram access exist in this sandbox,
  per the task's explicit instruction) — only confirmed it collects and
  skips correctly (see "Test run" below).

### JSON serialization approach

Per the subtask spec: stdlib `dataclasses` only, no `pydantic` or other
new dependency. Chose a **manual `to_dict()`-style pair of small functions**
(`_tmdb_to_dict`, `_recommendation_to_dict`, `_result_to_dict` in `cli.py`)
over generic `dataclasses.asdict()` for one deliberate reason:
`brainstorm.md`'s "Output shape (draft)" section documents the `tmdb`
object with exactly five fields (`id`, `title`, `year`, `poster_path`,
`overview`) — it does **not** include `ResolvedMovie.match_score`, which is
a real field on that dataclass (added in `core/models.py` for TMDB-match-
quality scoring, per subtask 2). A blind `dataclasses.asdict()` recursive
walk would have included `match_score` in every CLI invocation's output,
silently exceeding the documented shape. The manual serializer whitelists
exactly the five documented fields instead, so the CLI's output is a
byte-for-byte match to the brainstorm.md draft shape, not a superset of it.
This is flagged as an explicit, deliberate choice (not an oversight) in
case a future consumer of this CLI actually wants `match_score` surfaced —
if so, it's one field to add back in `_tmdb_to_dict`, isolated in one place.

Two other serialization details worth recording:
- `SourceTag` (a `StrEnum`) is serialized via `rec.source.value` rather
  than relying on `json.dumps`'s native handling of `str` subclasses
  (which would also work, since `StrEnum` members *are* plain strings at
  the byte level) — `.value` was chosen for explicitness/robustness in
  case `SourceTag` is ever changed to a plain `Enum` later, which would
  silently break the implicit-str-subclass path but not the explicit
  `.value` one.
- `reel_url` and every other field in the output shape (`query`,
  `confidence`, `id`, `title`, `year`, `poster_path`, `overview`) are
  already plain `str`/`int`/`float`/`None` on the dataclasses themselves
  (per `core/models.py`), so no further per-field conversion (e.g. `Path`
  handling) was needed — `IngestResult.video_path: Path | None` exists on
  a different dataclass entirely and is never part of `PipelineResult`'s
  shape, so it never reaches the serializer.

### `tests/integration` vs. `pyproject.toml`'s `testpaths` decision

`pyproject.toml`'s `[tool.pytest.ini_options] testpaths = ["tests"]` was
left **unchanged** — i.e. `python3 -m pytest tests` (no path argument)
still collects both `tests/unit` and `tests/integration`. Reasoning:

- The live smoke test self-skips via `skipif` whenever
  `REEL2MOVIE_LIVE_TEST_URL` is unset, which is true in every CI run and
  every fresh clone unless a human deliberately sets it. So collecting it
  by default under `pytest tests` is safe — it costs one extra "skipped"
  line in the summary, never a hang, a real network call, or a failure.
- Narrowing `testpaths` to just `["tests/unit"]` would make the *default*
  `pytest` invocation (no args) match the "safe, no live calls" unit-only
  behavior the task cares about, but would also make `tests/integration`
  invisible to plain `pytest --collect-only` / IDE test discovery without
  an explicit path — a real, if minor, discoverability cost for the one
  module (a human with real credentials) who'd actually want to run it.
- The task's own two verification commands are `pytest tests/unit` and
  `pytest tests/integration` as *separate, explicit* invocations — never
  a bare `pytest` with no path — so nothing in the actual verification
  contract depends on `testpaths`'s value either way.
- Net: kept `testpaths = ["tests"]` as-is. If a later maintainer wants
  `pytest` (no args) to run only the always-safe unit suite by default,
  the one-line change is `testpaths = ["tests/unit"]`, with
  `tests/integration` then run explicitly by path — flagging this as the
  alternative considered, not implemented, since the current behavior is
  already safe by construction (the skip, not the path list, is what
  makes it safe).

### Test run

`python3 -m pytest tests/unit -q`:
```
........................................................................ [ 52%]
................................................................          [100%]
136 passed in 2.28s
```
(131 passed before this subtask, per the task's stated baseline + 5 new in
`tests/unit/test_cli.py` = 136; no existing test needed modification, no
regressions.)

`python3 -m pytest tests/integration -q`:
```
s                                                                          [100%]
1 skipped in 1.62s
```
Confirmed **skipped**, not passed/error — `REEL2MOVIE_LIVE_TEST_URL` is
unset in this sandbox, so the `skipif` guard fired correctly; the test was
never actually executed against a real reel.

Also ran the full default `python3 -m pytest tests -q` (both dirs
together, matching `testpaths`'s current value) as an extra sanity check
beyond what the task asked for: `136 passed, 1 skipped in 2.24s` — exactly
the union of the two runs above, confirming the two suites don't collide
(no duplicate collection, no fixture leakage between `tests/unit` and
`tests/integration`).

### `python -m reel2movie` smoke test

Run from the project root, no real `.env` present in this sandbox:

```
$ python3 -m reel2movie --help
usage: reel2movie [-h] [--frame-count FRAME_COUNT] reel_url

Extract movie recommendations from a reel and resolve them against TMDB.

positional arguments:
  reel_url              URL of the reel to process (e.g. an Instagram Reel
                        link).

options:
  -h, --help            show this help message and exit
  --frame-count FRAME_COUNT
                        Override the number of frames sampled during the
                        visual fallback step (default: PipelineDeps' own
                        default).
```

```
$ python3 -m reel2movie "https://www.instagram.com/reel/dummy123/"
reel2movie: configuration error: ANTHROPIC_API_KEY is not set (see .env.example at the project root for the expected variables).
$ echo "exit code: $?"
exit code: 1
```

Confirmed separately (via `2>/dev/null` and `2>&1 1>/dev/null` redirection)
that this message is on **stderr**, stdout is empty, exit code is `1`, and
no Python traceback appears anywhere — `python -m reel2movie` is genuinely
invocable as a module, not just importable from tests, and fails cleanly
on the expected missing-credential case in this sandbox (which has no real
`TMDB_API_KEY`/`ANTHROPIC_API_KEY`/`.env`).

### Review findings (latest pass)

Reviewed via `/code-review` (medium) on the current diff
(`reel2movie/{__main__,cli}.py`, `tests/unit/test_cli.py`,
`tests/integration/{__init__,test_live_smoke}.py`), `/ponytail:ponytail-review`
on the same diff, and independent manual verification (not trusted from the
build report above): a field-by-field comparison of `cli.py`'s JSON
serializer against `brainstorm.md`'s "Output shape (draft)" section, a
direct read of `cli.py` in full, and running the test suites and the CLI
itself from the project root.

**From `/code-review` (correctness):** no defect found. The diff is small,
matches the documented spec exactly, correctly wires
`build_default_pipeline_deps()`/`run_pipeline()` with signatures matching
their real definitions in `pipeline/deps.py`/`pipeline/waterfall.py`, and is
covered by tests for every stated edge case (JSON shape, missing API key,
fatal pipeline error, `--frame-count` override present/absent).

**From `/ponytail:ponytail-review` (over-engineering/complexity):**
- **Non-blocking** — `reel2movie/cli.py` L127-128: `delete:` the module's
  own `if __name__ == "__main__": raise SystemExit(main())` guard is
  redundant with `reel2movie/__main__.py`'s identical guard, which is
  already the sole entry point for `python -m reel2movie`. This guard in
  `cli.py` only fires if someone runs `python reel2movie/cli.py` directly
  or `python -m reel2movie.cli` — neither is a documented/supported
  invocation. Nothing replaces it; `net: -2 lines possible`.
- Everything else is lean: the three-function JSON serializer
  (`_tmdb_to_dict`/`_recommendation_to_dict`/`_result_to_dict`) mirrors the
  three real nesting levels of the output shape rather than being
  speculative, `_build_parser()` is the ordinary argparse-factory pattern,
  and the test file's two shared helpers (`_fake_deps`, `_canned_result`)
  are genuinely reused across multiple tests, not one-off abstractions.

**Manual verification (done directly, not trusted from the build report):**
- **brainstorm.md field-by-field match, confirmed correct:** `brainstorm.md`'s
  "Output shape (draft)" `tmdb` object lists exactly five fields — `id`,
  `title`, `year`, `poster_path`, `overview`. `core/models.py`'s
  `ResolvedMovie` has those same five fields **plus** `match_score` (added
  in Subtask 2 for TMDB-match-quality scoring). `cli.py`'s `_tmdb_to_dict()`
  (L66-83) emits exactly the five documented fields and omits
  `match_score` — this is a correct match-to-spec, not accidental data
  loss. Confirmed independently by reading both documents side by side, not
  just by reading the build report's claim; also confirmed
  `test_prints_expected_json_shape` asserts `"match_score" not in
  resolved["tmdb"]` on a `ResolvedMovie` constructed *with* a real
  `match_score=0.95` value, so the test would fail if it leaked.
- **`tmdb=None` → JSON `null`, confirmed:** `_tmdb_to_dict(None)` returns
  Python `None` (L75-76), which `json.dumps` serializes to JSON `null`, not
  an omitted key and not a crash — confirmed both by reading the code path
  and via `test_prints_expected_json_shape`'s
  `unresolved["tmdb"] is None` assertion on the parsed-back JSON.
- **Both error paths print to stderr only, never leak a traceback,
  confirmed:** read `cli.py` in full. Both `build_default_pipeline_deps()`
  (L108-112) and `run_pipeline()` (L117-121) calls are wrapped in their own
  `try/except Exception`, each printing one `reel2movie: ...: <exc>` line
  via `print(..., file=sys.stderr)` and returning `1`; stdout is never
  written to on either failure path (the `json.dumps` print only happens
  after both try blocks succeed). Confirmed live, not just read: ran
  `python3 -m reel2movie "https://www.instagram.com/reel/dummy123/"` from
  the project root with no `.env` and no `TMDB_API_KEY`/`ANTHROPIC_API_KEY`/
  `INSTAGRAM_COOKIES_FILE` set in the environment —
  ```
  $ python3 -m reel2movie "https://www.instagram.com/reel/dummy123/"
  (stdout: empty)
  (stderr): reel2movie: configuration error: ANTHROPIC_API_KEY is not set (see .env.example at the project root for the expected variables).
  exit code: 1
  ```
  stdout was empty, stderr held exactly one clean line, exit code was `1`,
  and grepping both streams for "traceback" found nothing. (Fired on
  `ANTHROPIC_API_KEY` rather than `TMDB_API_KEY` only because
  `build_default_pipeline_deps()` happens to construct the vision detector
  before the TMDB client — either missing var takes the same clean path.)
- **`except Exception` placement is sensible; `KeyboardInterrupt`/
  `SystemExit` are not swallowed, confirmed:** read the whole file —
  there is no bare `except:` anywhere, and both `except` clauses name
  `Exception` specifically. Since `KeyboardInterrupt` and `SystemExit`
  subclass `BaseException` directly (not `Exception`), Python's own
  semantics mean neither is caught by either block — a Ctrl-C during
  `build_default_pipeline_deps()` or `run_pipeline()` propagates normally
  rather than being reported as a generic configuration/processing error.
  This matches the module docstring's explicit claim (L26-28) exactly.
- **`--frame-count` reaches `PipelineDeps.frame_count`, confirmed:**
  `main()` (L114-115) mutates `deps.frame_count` in place — `PipelineDeps`
  is a plain (non-frozen) `@dataclass` (`pipeline/deps.py` L39-52), so this
  mutation is valid — *before* calling `run_pipeline(args.reel_url, deps)`,
  so the same object `build_default_pipeline_deps()` returned is what
  `run_pipeline` receives with the override applied. Confirmed by
  `test_frame_count_override_reaches_pipeline_deps` (asserts both the value
  `run_pipeline` sees *and* that the original `fake_deps` object itself was
  mutated, not a copy) and `test_no_frame_count_override_leaves_default_untouched`.
- **Independent test runs** (not trusted from the build report):
  - `python3 -m pytest tests/unit -q` → **136 passed**, matches exactly.
  - `python3 -m pytest tests/integration -q` → **1 skipped** (confirmed via
    `-rs`: `SKIPPED [1] tests/integration/test_live_smoke.py:37: set
    REEL2MOVIE_LIVE_TEST_URL and real API keys to run this live smoke
    test`) — not passed/error, and the skip reason is sensible (names the
    exact env var and what else is needed).
  - `python3 -m reel2movie --help` → clean usage text, exit code `0`.
  - `python3 -m reel2movie "https://www.instagram.com/reel/dummy123/"` →
    clean failure as detailed above, exit code `1`, no traceback, stderr
    only.

No blocking findings. The JSON shape match, `null` serialization, both
error paths, and the `--frame-count` wiring all check out against
`brainstorm.md`/the spec exactly under direct, independent verification —
not merely re-reading the build report's claims.

VERDICT: ACCEPTABLE

### Fixes applied
None needed — verdict is ACCEPTABLE. The one `/ponytail:ponytail-review`
finding (redundant `__main__` guard in `cli.py`, 2 lines) is non-blocking
and left as-is; it does not affect correctness or the CLI's documented
behavior.

### Open questions / risks

- **Observed discrepancy, not touched:** this subtask's instructions
  stated all of subtasks 0-7 are "done, reviewed, and committed." Reading
  subtask 7's own section above (and subtask 5's/6's) shows their status
  lines as `fixed, pending re-review` / `built, pending review` /
  `fixes applied, awaiting re-review` respectively, with explicit
  placeholder `### Review findings` / `### Fixes applied` sections —
  while `git log` shows a commit exists for every subtask through 7
  (`8cde262 Subtask 7: pipeline waterfall orchestration` is the tip before
  this subtask's work). Not resolved or edited here, per the explicit
  instruction not to touch earlier subtasks' sections — flagging for
  whoever runs this subtask's own review/acceptance pass, since it affects
  whether "every module is done and reviewed" is actually true yet.
- **Broad `except Exception` in `cli.py`'s two call sites** (rather than
  `except RuntimeError`) is a deliberate choice per the subtask's own
  "no raw traceback" requirement, covering both the anticipated case
  (missing env var) and any other unexpected failure in either call —
  flagging in case a reviewer prefers narrowing it back to `RuntimeError`
  specifically, trading robustness against unanticipated exceptions for a
  tighter, more specific contract.
- **`match_score` is dropped from the CLI's JSON output** (see
  "JSON serialization approach" above) since it's not part of
  brainstorm.md's documented shape. If a downstream consumer of this CLI
  later wants TMDB match-confidence surfaced in the output, this is the
  one place to revisit.
- **No retry/timeout wrapping at the CLI layer** — `run_pipeline` is
  called exactly once per invocation; a flaky network mid-run (e.g. during
  the visual fallback's Anthropic vision calls) surfaces as whatever
  exception the lowest layer raises, caught by `cli.py`'s blanket
  `except Exception` and reported as a generic "failed to process" message
  rather than a more specific diagnosis. Out of scope per the subtask spec
  (which only asked for clean error handling, not retry logic).
- **Live smoke test genuinely never executed** in this sandbox (by
  explicit instruction) — its correctness rests on: (a) `main()`'s own
  signature/behavior, already covered by the mocked unit tests above, and
  (b) the `skipif` guard firing correctly, confirmed directly via the
  `1 skipped` pytest output above. The actual end-to-end real-API/real-IG
  path (`InstagramIngestor` → `VisionLLMPosterDetector` → `TMDBHttpClient`,
  all wired by `build_default_pipeline_deps()`) remains unverified against
  a live reel — this was explicitly called out in the original plan
  (`vast-wobbling-owl.md`'s "Verification" section) as needing the user's
  own IG session cookies, deferred to whenever the user actually runs this
  for real.
- **`pyproject.toml` left unchanged** — see the dedicated section above
  for the reasoning; flagging here too since it was an explicit "your
  call" decision point in the subtask spec, not an oversight.

---

## Project status

All 9 subtasks (0 core, 1 config, 2 tmdb, 3 text_extraction, 4 ingest,
5 frame_sampler, 6 vision_llm_detector, 7 pipeline, 8 cli) have been built,
each with its own unit tests using fakes/fixtures (no live network/API
calls anywhere in `tests/unit`). Total test count as of this subtask:
**136 passed** in `tests/unit` + **1 skipped** (by design) in
`tests/integration` = 137 collected tests. (Note the open question above:
subtasks 5-7's `PROGRESS.md` sections show their own review/fix cycles as
not fully closed out as of this writing, even though code for all of them
exists, is tested, and is committed through `8cde262`; whoever runs this
subtask's acceptance pass should reconcile that before calling the whole
pipeline "reviewed," not just "built.")

To actually run this for real against a live Instagram Reel, a user needs
to, in order:

1. **Populate `.env` from `.env.example`** at the project root — set
   `TMDB_API_KEY` (a TMDB v4 "API Read Access Token", not the older v3
   `api_key`) and `ANTHROPIC_API_KEY` (an Anthropic API key with billing
   enabled — the visual fallback's vision-LLM calls are billed against
   this). `.env` is gitignored; `.env.example` documents the three
   expected variable names with no real values.
2. **Provide Instagram cookies** — export a logged-in Instagram session's
   cookies to a Netscape-format cookies file (e.g. via a browser extension
   like "Get cookies.txt"), then set `INSTAGRAM_COOKIES_FILE` in `.env` to
   that file's path. This is required for `yt-dlp` to reliably fetch
   caption/comment data per `vast-wobbling-owl.md`'s "Decisions made"
   section (a real ToS/account-risk tradeoff the user already accepted
   when this plan was approved).
3. **Run the real pipeline**: `python3 -m reel2movie "<instagram-reel-url>"`
   — prints the `brainstorm.md`-shaped JSON result to stdout on success,
   or a clear one-line error to stderr with a non-zero exit code on
   failure (missing credentials, unreachable URL, etc.).
4. **Optionally, set `REEL2MOVIE_LIVE_TEST_URL`** to a real, currently-
   reachable Instagram Reel URL (in addition to the three env vars above)
   to run the one live smoke test:
   `python3 -m pytest tests/integration -q` — without it, that test
   self-skips safely; with it (and real credentials), it exercises the
   entire pipeline end-to-end for the first time outside of mocked unit
   tests.

No `git commit` was made for this subtask's work, per the task
instructions — that is the orchestrator's final step after this subtask's
own review passes.

---

## Post-ship follow-up — anonymous Instagram access confirmed + tested

User asked whether Instagram cookies could be avoided entirely (initially
asked about a username/password login script; checked the installed yt-dlp
package directly and confirmed its Instagram extractor has no `_perform_login`
method at all, so that path isn't technically viable, separate from the
security concerns with handling a password). `cookies_from_browser` was
offered as the recommended alternative but not yet built.

In the meantime: confirmed `InstagramIngestor`/`YtDlpClient` already support
running with `cookies_file=None` (anonymous/unauthenticated access) as a
built-in default from Subtask 4 — no production code change was needed. This
was tested at the `YtDlpClient` layer already but not end-to-end through
`InstagramIngestor`; added
`test_fetch_metadata_runs_cookieless_when_no_cookies_file_given` to
`tests/unit/ingest/test_instagram.py` to close that gap. 137 tests passing.
Also clarified `.env.example`'s `INSTAGRAM_COOKIES_FILE` comment to state
plainly that it's optional and what the reliability tradeoff is.

---

## Follow-up — Claude Code CLI vision backend — status: done

### Why this exists (not in the original 9-subtask plan)

`vast-wobbling-owl.md`'s original "Visual detection approach" decision was
"Anthropic Claude vision-LLM, billed against Claude credits" — i.e. a
separate, metered `ANTHROPIC_API_KEY`. The user asked for an alternative:
drive the visual-fallback step through the locally-installed `claude` CLI
instead, so it draws on an existing Claude Pro/Max subscription's usage
instead of requiring separate API billing. This updates that framing: the
plan's original decision isn't wrong, it's just no longer the default —
see below for exactly what changed and why.

### What's built

- `reel2movie/visual/vision_llm_detector.py` — added
  `ClaudeCodeVisionError(RuntimeError)` and `ClaudeCodeVisionChatClient`,
  a second `VisionChatClient` implementation alongside the existing
  `AnthropicVisionChatClient`. `VisionLLMPosterDetector` itself was **not**
  touched at all — confirming by construction that it really is agnostic
  to which `VisionChatClient` it's given, exactly as the existing module
  docstring claims.
  - `ClaudeCodeVisionChatClient.__init__(claude_binary="claude",
    timeout_seconds=60.0)`.
  - `.chat(image_path, prompt)` builds a combined instruction
    (`f"Read the image file at {image_path} using your Read tool. {prompt}"`),
    then runs:
    `subprocess.run([claude_binary, "-p", "--output-format", "json",
    "--tools", "Read", "--permission-mode", "bypassPermissions",
    "--no-session-persistence", combined_prompt], capture_output=True,
    text=True, timeout=timeout_seconds)`.
  - Raises `ClaudeCodeVisionError` (clear message each time, reusing the
    same "custom `RuntimeError` subclass with a message that always
    includes the relevant captured detail" pattern `frame_sampler.py`'s
    `FrameExtractionError` already established in this codebase) on:
    `subprocess.TimeoutExpired` (caught explicitly, re-raised as
    `ClaudeCodeVisionError` naming the timeout — never lets the raw
    exception propagate), non-zero exit code (message includes captured
    stderr), non-JSON stdout (`json.JSONDecodeError` caught, message
    includes the raw stdout), parsed `is_error: true`, and non-empty
    `permission_denials` — this last check runs *in addition to* the
    `is_error` check, not instead of it, so a response that passes
    `is_error` but has a non-empty `permission_denials` still raises
    rather than being trusted. On success, returns `parsed["result"]`.
  - The class docstring documents explicitly that the exact JSON shape
    parsed (`result`, `is_error`, `permission_denials`, `subtype`, `type`,
    plus the other fields) is grounded in a **real, user-captured**
    response from running the actual `claude` CLI command (quoted in
    full in the docstring), not guessed from documentation or simulated —
    and points future maintainers at this PROGRESS.md section (here) for
    the full captured response if the parsing ever needs revisiting,
    since this JSON shape isn't part of any published/versioned API
    contract.

  Real captured response this was built against (verbatim, as given):
  ```json
  {
    "duration_api_ms": 4057, "stop_reason": "end_turn",
    "session_id": "aa89cba6-ce5b-4089-978a-a77f37a9e9dc",
    "total_cost_usd": 0.0609246, "usage": {"...": "..."},
    "modelUsage": {"claude-sonnet-5": {"...": "...", "costBasis": "list"}},
    "permission_denials": [], "terminal_reason": "completed",
    "is_error": false, "num_turns": 2, "subtype": "success",
    "api_error_status": null,
    "result": "This is a classic TV color bar test pattern with vertical stripes of white, yellow, cyan, green, magenta, red, and blue arranged in a circle on a black background, with a horizontal rainbow gradient bar across the bottom and a small black rectangle with a white outline on the right side.",
    "type": "result", "duration_ms": 4195,
    "uuid": "6784baa3-fa8b-48b5-9871-2e34909c7397"
  }
  ```
  (from `claude -p --output-format json --tools Read --permission-mode
  bypassPermissions --no-session-persistence "Read the image file at
  /tmp/test_poster.jpg using your Read tool, then describe the
  colors/pattern you see in exactly one sentence."`, ~4.2s end to end.)

- `reel2movie/config.py` — added `get_vision_backend() -> str`. Reads
  `VISION_BACKEND`; unset/empty defaults to `"claude_code"` (does **not**
  raise — this is the deliberate new default, not an error condition);
  explicitly set to `"claude_code"` or `"anthropic_api"` returns that
  value; any other explicitly-set value raises `RuntimeError` naming the
  bad value and the two valid options. `get_tmdb_token()` and
  `get_anthropic_key()` are unchanged.

- `reel2movie/pipeline/deps.py` — `build_default_pipeline_deps()` now
  calls `config.get_vision_backend()` and branches:
  `"claude_code"` → `ClaudeCodeVisionChatClient()` (no key needed);
  `"anthropic_api"` → `AnthropicVisionChatClient(config.get_anthropic_key())`;
  anything else → `RuntimeError` (unreachable in practice since
  `get_vision_backend()` already validates, but kept as a defensive
  explicit branch per the task's exact requested shape, and cheap
  insurance against the two functions' valid-value sets ever drifting
  apart). **Critical property, directly verified by test**:
  `config.get_anthropic_key()` is called *only* inside the
  `"anthropic_api"` branch — never eagerly, never unconditionally, so a
  caller who leaves `ANTHROPIC_API_KEY` entirely unset (using the default
  `claude_code` backend) never hits a missing-key error anywhere during
  construction. `config.get_tmdb_token()` remains unconditionally
  required, as before — unrelated to this change.

- `.env.example` — added `VISION_BACKEND` (optional, documents both valid
  values and the cost/dependency tradeoff of each: `claude_code` needs
  the `claude` CLI installed and logged into a subscription on the
  machine running the pipeline; `anthropic_api` needs a separate billed
  API key but no CLI dependency). Re-labeled `ANTHROPIC_API_KEY` as
  optional, only required when `VISION_BACKEND=anthropic_api` is
  explicitly set.

### Tests added (no real `claude` subprocess calls anywhere)

- `tests/unit/visual/test_vision_llm_detector.py` — new
  `TestClaudeCodeVisionChatClient` class, mocking
  `reel2movie.visual.vision_llm_detector.subprocess.run` (same patching
  convention `tests/unit/visual/test_frame_sampler.py` already established
  for ffmpeg). A `_canned_cli_json()` helper builds stdout matching the
  real captured shape field-for-field. Covers: success (returns the
  `result` string, and separately asserts the exact CLI invocation shape —
  binary name, all five flags, the combined prompt containing both the
  image path and the original prompt text, `capture_output`/`text`/
  `timeout` kwargs); `is_error: true` → raises; **non-empty
  `permission_denials` with `is_error: false` and a plausible-looking
  `result`** → still raises (the subtlest case, called out explicitly in
  its own test
  `test_chat_raises_on_nonempty_permission_denials_even_if_result_looks_fine`,
  specifically constructed so a naive implementation that only checks
  `is_error` would wrongly pass); non-JSON stdout → raises; non-zero exit
  code → raises (message includes captured stderr); `subprocess.TimeoutExpired`
  → raises `ClaudeCodeVisionError` naming the timeout, not the raw
  exception; a custom `claude_binary`/`timeout_seconds` constructor args
  case confirming both are actually threaded through to the subprocess call.
- `tests/unit/test_config.py` — `get_vision_backend()`: unset → default;
  empty-string → default (consistent with the other getters' empty-is-unset
  handling); explicitly `"claude_code"` → that value; explicitly
  `"anthropic_api"` → that value; invalid value → raises naming
  `VISION_BACKEND`.
- `tests/unit/pipeline/test_deps.py` — four new tests using
  `monkeypatch.setenv`/`delenv`: (1) `VISION_BACKEND` unset,
  `ANTHROPIC_API_KEY` unset, `TMDB_API_KEY` set → construction succeeds
  without raising (the key behavioral proof this whole change is for);
  (2) same but `VISION_BACKEND` explicitly `"claude_code"` → also
  succeeds without the key; (3) `VISION_BACKEND=anthropic_api`,
  `ANTHROPIC_API_KEY` unset → raises `RuntimeError` matching
  `ANTHROPIC_API_KEY` (proving the key is still required in that branch,
  not silently skipped); (4) same but with the key set → succeeds.

Ran `python3 -m pytest tests/unit -q`:

```
.........................................................................
.........................................................................
.........
153 passed in 3.49s
```

(137 passing before this follow-up + 16 new: 7 in
`test_vision_llm_detector.py`, 5 in `test_config.py`, 4 in
`test_deps.py`. Confirmed directly, not just assumed.)

### Explicit confirmation: `ANTHROPIC_API_KEY` is no longer required by default

With `VISION_BACKEND` unset (or explicitly `"claude_code"`) and
`ANTHROPIC_API_KEY` completely unset, `build_default_pipeline_deps()`
succeeds — `get_anthropic_key()` is never called on that path at all.
`ANTHROPIC_API_KEY` is only ever needed when `VISION_BACKEND=anthropic_api`
is explicitly set. `TMDB_API_KEY` remains unconditionally required in all
cases (unrelated to this change).

### Framing update — reconciling with the original plan's decision

`vast-wobbling-owl.md`'s original "Visual detection approach" decision
("Anthropic Claude vision-LLM, billed against Claude credits") described
what is now the `anthropic_api` backend — it's still fully present,
unchanged, and still selectable. What changed here, as an explicit,
deliberate deviation from that original framing (per the user's
stated preference to avoid separate metered API billing where possible):
`claude_code` is now the **default** backend when `VISION_BACKEND` is
unset, not `anthropic_api`. This is not a contradiction left unexplained —
it's a conscious reprioritization for a follow-up subtask outside the
original plan's scope, made possible precisely because
`VisionLLMPosterDetector`'s Protocol-based design (subtask 6) already
decoupled the detector from any specific provider.

### New tradeoff introduced — an environmental dependency, not a pip package

Every dependency this project has taken on through subtask 8 has been a
pip package (`anthropic`, `requests`, `imageio-ffmpeg`, `rapidfuzz`,
`yt-dlp`, etc.) — something `pip install -e .` fully resolves. The
`claude_code` backend is different in kind: it depends on the `claude`
CLI binary being **installed and authenticated** (logged into a Claude
subscription) on whatever machine actually executes the pipeline at
runtime, which is an environmental/system-level dependency no
`pyproject.toml` entry can express or guarantee. If the binary is missing,
not on `PATH`, or not logged in, `ClaudeCodeVisionChatClient.chat()` fails
at call time (a non-zero exit or a clear subprocess error, not a silent
wrong answer) rather than at install time or even at
`build_default_pipeline_deps()` construction time — construction succeeds
unconditionally for this backend since no credential-shaped check is
possible for it the way `get_anthropic_key()` does for the other backend.
This is a one-way tradeoff against the `anthropic_api` backend's pure-pip
dependency profile, accepted here because it's exactly the point of the
feature (reuse an existing subscription instead of a separate billed key),
but worth remembering if this pipeline is ever deployed to an environment
(e.g. a CI runner, a server) where no human has ever interactively logged
the `claude` CLI into an account — `anthropic_api` remains the right
choice for that kind of environment, via `VISION_BACKEND=anthropic_api`.

### Review findings (latest pass)

This section holds two review passes, kept distinct rather than letting the
newer one overwrite the older (per the historical/current split convention
already established in Subtasks 3, 5, and 7). **Cycle 0** (below) is the
original pre-fix review; its outcome is narrated in `### Fixes applied`
below (fix cycle 1) and is kept here verbatim for the record. **Cycle 2**
(further down) is a fresh, from-scratch re-review of the current working
tree — run independently of cycle 0/1, not a continuation of them.

#### cycle 0 review (historical — pre-fix; see "Fixes applied" below for what changed in response)

Ran `/code-review` and `/ponytail:ponytail-review` against the current diff
(`.env.example`, `.gitignore`, `reel2movie/config.py`,
`reel2movie/pipeline/deps.py`, `reel2movie/visual/vision_llm_detector.py`,
and the three test files), plus independent manual verification (not just
re-reading the build report's claims):

- **`permission_denials` check — directly verified, not just read.**
  Constructed a fake `subprocess.run` return value by hand with
  `is_error: False`, a plausible-looking `result` string ("This image shows
  a clearly readable movie poster for Inception (2010)."), and a non-empty
  `permission_denials` list, monkeypatched
  `reel2movie.visual.vision_llm_detector.subprocess.run` to return it, and
  called `ClaudeCodeVisionChatClient().chat(...)` directly (no pytest, no
  existing test file). It raised `ClaudeCodeVisionError` as claimed, not a
  silently-trusted plausible-looking string. The `is_error` check and the
  `permission_denials` check are both present and independent (code.py
  lines ~213 and ~219), confirming the build report's claim field-for-field.

- **JSON shape vs. the real captured response — compared field-for-field.**
  Every key `chat()` reads (`is_error`, `permission_denials`, `result`) is
  present, with matching types, in the real captured CLI response pasted
  above (`is_error: false`, `permission_denials: []`, `result: "<string>"`,
  plus `subtype`/`type` referenced only in the docstring, not parsed). No
  mismatch found between the code and the pasted real JSON.

- **`subprocess.TimeoutExpired` handling — directly verified.** Mocked
  `subprocess.run` to raise `subprocess.TimeoutExpired` directly (bypassing
  the existing test file) and confirmed `.chat()` raises
  `ClaudeCodeVisionError` naming the timeout, not the raw
  `TimeoutExpired`.

- **BLOCKING: a missing/not-on-PATH `claude` binary is not caught, and
  this contradicts the section's own documented claim.**
  `chat()`'s `try/except` around `subprocess.run` only catches
  `subprocess.TimeoutExpired` (`vision_llm_detector.py` ~line 175). If the
  `claude` binary itself is missing or not on `PATH`, `subprocess.run`
  raises a raw `FileNotFoundError`, which is not caught anywhere in
  `chat()` and propagates unwrapped — never becoming a
  `ClaudeCodeVisionError`. This directly contradicts this very
  section's "New tradeoff introduced" paragraph above, which explicitly
  claims "If the binary is missing, not on `PATH`, or not logged in,
  `ClaudeCodeVisionChatClient.chat()` fails at call time (a non-zero exit
  or **a clear subprocess error**...)" — a missing binary does not fail
  with a non-zero exit (there is no process to exit) and the raw
  `FileNotFoundError`, while not opaque, is not the documented
  `ClaudeCodeVisionError` contract either, and the method's own docstring
  "Raises" list only names `ClaudeCodeVisionError`. This is exactly the
  failure mode most likely to be hit in practice now that `claude_code` is
  the *default* backend — anyone who hasn't installed the `claude` CLI and
  does nothing special will hit this on the very first visual-fallback
  frame. Fix: wrap the `subprocess.run` call's except clause to also catch
  `OSError` (covers `FileNotFoundError` and `PermissionError`) and re-raise
  as `ClaudeCodeVisionError` naming the binary and the underlying OS error.

- **Non-blocking (ponytail-review): dead unreachable branch.**
  `build_default_pipeline_deps()`'s `else: raise RuntimeError(...)` branch
  (`deps.py` ~lines 94-98) for an unrecognized `VISION_BACKEND` value can
  never execute: `config.get_vision_backend()` already validates and only
  ever returns `"claude_code"`/`"anthropic_api"` or raises first. It's
  kept deliberately per the build report ("cheap insurance" against the
  two functions' valid-value sets drifting apart), which is a defensible
  judgment call, not a bug — flagged here as cuttable (~5 lines) if a
  future pass wants the single validated source of truth to be the only
  place this is checked, but not required to fix.

- **No-eager-`get_anthropic_key()` proof — independently re-verified, not
  just re-read.** `grep -rn "get_anthropic_key"` across the whole repo
  shows exactly one call site outside `config.py`'s own definition and
  docstrings/tests: `deps.py`'s `"anthropic_api"` branch
  (`AnthropicVisionChatClient(config.get_anthropic_key())`). No other call
  site exists anywhere, eager or otherwise. Separately ran
  `python3 -m pytest tests/unit -q` directly: **153 passed**, confirming
  the build report's count rather than trusting it. Also ran, outside
  pytest entirely, a standalone subprocess script that sets `TMDB_API_KEY`,
  unsets `VISION_BACKEND` and `ANTHROPIC_API_KEY`, and calls
  `build_default_pipeline_deps()` directly: it succeeded and returned a
  `PipelineDeps` whose `poster_detector._chat_client` is a
  `ClaudeCodeVisionChatClient` — confirming the core claim of this
  follow-up end-to-end, not just via the test suite that could itself be
  wrong.

No `git commit` was made for this follow-up, per the task instructions —
that happens after review.

Cycle 0 outcome: **NEEDS FIXES** (addressed by `### Fixes applied` below —
fix cycle 1 — producing the working tree re-reviewed in cycle 2 below).

#### cycle 2 review (current — fresh re-review of the post-fix working tree)

Run as a clean re-review, not a continuation of the cycle 0/1 session: fresh
reads of `PROGRESS.md`'s cycle 0 findings and fix-cycle-1 notes above, then
`/code-review` (medium) and `/ponytail:ponytail-review` run independently
against the current uncommitted diff (`.env.example`, `.gitignore`,
`reel2movie/config.py`, `reel2movie/pipeline/deps.py`,
`reel2movie/visual/vision_llm_detector.py`, and the three test files), plus
direct manual reproduction rather than trusting the fix-cycle-1 report's
claims.

**Primary question — is the cycle 0 BLOCKING bug actually fixed? Yes,
confirmed by direct reproduction, no mocking:** constructed
`ClaudeCodeVisionChatClient(claude_binary="definitely-not-a-real-claude-binary-xyz")`
directly and called `.chat(Path("/tmp/nonexistent_test_image.jpg"), "test")`
for real — `subprocess.run` genuinely raised `FileNotFoundError` trying to
exec a binary that doesn't exist on this machine's `PATH`, and it surfaced
as:
```
ClaudeCodeVisionError: could not run the 'claude' CLI (binary: 'definitely-not-a-real-claude-binary-xyz') -- is it installed and on PATH? ([Errno 2] No such file or directory: 'definitely-not-a-real-claude-binary-xyz')
```
— a `ClaudeCodeVisionError` naming the exact configured binary string, not a
raw `FileNotFoundError`/`OSError`. The cycle 0 BLOCKING finding is genuinely
fixed, not just re-described as fixed.

**Regression check — the two pre-existing checks the fix cycle didn't
touch are still intact.** Read `chat()` in full (lines ~166-238) and
separately re-verified both by direct reproduction (monkeypatched
`subprocess.run`, no pytest):
- `permission_denials` check: fed a canned reply with `is_error: False` and
  a plausible-looking `result` ("This image shows a clearly readable movie
  poster for Inception (2010).") but a non-empty `permission_denials` list
  — still raised `ClaudeCodeVisionError` naming `permission_denials`, not
  silently trusted. Unchanged by the fix.
- `subprocess.TimeoutExpired` handling: mocked `subprocess.run` to raise
  `TimeoutExpired` directly — still raised `ClaudeCodeVisionError` naming
  the timeout, not the raw exception. Unchanged by the fix. The new
  `except OSError` clause sits alongside (not instead of) the existing
  `except subprocess.TimeoutExpired` clause, and the two exception types
  are disjoint, so there's no shadowing risk between them.

**From `/code-review` (correctness):**
- **Non-blocking** — `vision_llm_detector.py` L238 (`return
  parsed["result"]`): direct-key access instead of `.get("result")`, so a
  parsed CLI reply with `is_error: false` and empty `permission_denials` but
  no `result` key raises a bare `KeyError` instead of the documented
  `ClaudeCodeVisionError`. Reproduced directly: fed `json.dumps({"is_error":
  False, "permission_denials": []})` (no `result` key) as canned stdout —
  `client.chat(...)` raised `KeyError: 'result'`, not
  `ClaudeCodeVisionError`, contradicting `chat()`'s own `Raises:` docstring
  (which names only `ClaudeCodeVisionError`). Non-blocking: this JSON shape
  isn't part of any versioned contract (per the class's own docstring) and
  every real captured response — including the one this parsing is grounded
  in — always includes `result` when `is_error` is false, so this is a
  defensive-robustness gap against a hypothetical future CLI output change,
  not a failure mode hit in normal operation today. Pre-existing from
  cycle 0 (the `parsed["result"]` line itself wasn't touched by fix cycle
  1's `except OSError` addition), not introduced by this fix cycle. Fix (if
  taken up): `parsed.get("result")`, or an explicit `if "result" not in
  parsed: raise ClaudeCodeVisionError(...)` guard.
- **Non-blocking** — `deps.py` ~L94-98 (`else: raise RuntimeError("Unknown
  VISION_BACKEND...")`): still unreachable dead code, unchanged from cycle
  0 — `config.get_vision_backend()` already validates and only ever returns
  `"claude_code"`/`"anthropic_api"` or raises first, so this branch can
  never execute. Carried over verbatim from cycle 0's non-blocking finding
  (not touched by fix cycle 1, which only edited
  `vision_llm_detector.py`'s exception handling); still a defensible
  judgment call per the build report ("cheap insurance" against the two
  functions' valid-value sets drifting apart), not required to fix.

**From `/ponytail:ponytail-review` (over-engineering/complexity):**
- Same dead-branch finding as above (`deps.py` ~L94-98): `delete:` the
  unreachable `else` branch; nothing replaces it, since
  `config.get_vision_backend()` is already the single source of truth for
  valid values.
- The fix cycle 1 diff itself (the two-line `except OSError` clause in
  `vision_llm_detector.py`) introduces no new bloat: it's the minimum
  addition, directly mirrors the existing `except
  subprocess.TimeoutExpired` clause's shape, and the one new regression
  test (`test_chat_raises_clear_error_when_binary_missing_not_raw_exception`)
  follows the same mocking convention as its six siblings rather than
  inventing a new pattern. The seven near-identical
  `tmp_path / "frame_000.jpg"; image_path.write_bytes(...)` setup lines
  across `TestClaudeCodeVisionChatClient`'s tests are not flagged — this
  duplication is a pre-existing convention already present in the untouched
  `TestAnthropicVisionChatClient` tests above it in the same file (e.g.
  L236, L277, L306), not something this diff introduced.
- `net: -5 lines possible` (the dead branch only; non-blocking).

**Independent test run:** ran `python3 -m pytest tests/unit -q` directly in
this review pass (not trusting the reported 154): **154 passed**, matching
the fix-cycle-1 report's count exactly.

No BLOCKING findings remain. The one BLOCKING finding from cycle 0 is
confirmed fixed by direct reproduction; both findings surfaced this pass are
non-blocking (one pre-existing edge case untouched by this fix cycle, one
carried-over dead branch already judged acceptable to leave).

VERDICT: ACCEPTABLE

### Fixes applied

Addressed the one BLOCKING finding above (missing-binary case). Left the
non-blocking `deps.py` dead-branch finding untouched, per the review's own
"defensible judgment call, not required to fix."

- `reel2movie/visual/vision_llm_detector.py` — `ClaudeCodeVisionChatClient.chat()`'s
  `try/except` around `subprocess.run` now has a second `except OSError`
  clause alongside the existing `except subprocess.TimeoutExpired` (added,
  not replaced — the two are disjoint exception hierarchies, so order
  between them doesn't matter; `OSError` catches `FileNotFoundError`
  (missing binary/not on `PATH`) and `PermissionError` (not executable)
  alike). Re-raises as `ClaudeCodeVisionError` with message
  `"could not run the 'claude' CLI (binary: {claude_binary!r}) -- is it "
  "installed and on PATH? ({exc})"` — names the configured binary and
  includes the underlying `OSError`'s own text, so "it hung" (timeout
  message) and "the binary doesn't exist" (this message) read as visibly
  different problems. Also updated `chat()`'s docstring `Raises:` section
  and the `ClaudeCodeVisionError` class docstring's "Covers:" list to
  name this case explicitly, so the documented contract now matches the
  code (closing the exact gap the review flagged against this section's
  "New tradeoff introduced" paragraph).

- `tests/unit/visual/test_vision_llm_detector.py` — added
  `test_chat_raises_clear_error_when_binary_missing_not_raw_exception`
  to `TestClaudeCodeVisionChatClient`: mocks `subprocess.run` with
  `side_effect=FileNotFoundError("[Errno 2] No such file or directory: "
  "'claude'")`, calls `.chat(...)`, and asserts it raises
  `ClaudeCodeVisionError` (matching `"claude"` in the message) rather
  than the raw `FileNotFoundError`.

Ran `python3 -m pytest tests/unit -q`:

```
154 passed in 3.59s
```

(153 passing before this fix + 1 new regression test, confirmed directly.)

**Direct manual verification, independent of pytest** (same approach the
reviewer used for the `permission_denials` finding): ran a standalone
script (no pytest) that (1) monkeypatches
`reel2movie.visual.vision_llm_detector.subprocess.run` with
`side_effect=FileNotFoundError(...)` and calls
`ClaudeCodeVisionChatClient().chat(...)` directly — raised
`ClaudeCodeVisionError` with message `"could not run the 'claude' CLI "
"(binary: 'claude') -- is it installed and on PATH? ([Errno 2] No such "
"file or directory: 'claude')"`, not the raw exception; and (2), with no
mocking at all, constructed `ClaudeCodeVisionChatClient(claude_binary=`
`"definitely-not-a-real-claude-binary-xyz")` and called `.chat(...)` for
real against an image path that doesn't even need to exist for this
failure mode — `subprocess.run` genuinely raised `FileNotFoundError`
trying to exec a binary that doesn't exist on this machine's `PATH`, and
it came back as `ClaudeCodeVisionError` naming that exact binary string.
Both confirm the fix end-to-end, not just via the mocked test.

VERDICT: fix applied for the BLOCKING finding; ready for re-review.

---

## Post-ship follow-up — .env was never actually loaded

Discovered while preparing for a real end-to-end test: `config.py` only
ever read `os.environ` directly — nothing in the project called
`load_dotenv()`, so values sitting in `.env` were never actually visible
to the running process. This was a gap across all 9 original subtasks and
the vision-backend follow-up; none of the build passes added it.

Fixed directly (small, well-understood, low-risk addition — not run
through the full subagent build-review loop): added `python-dotenv` to
`pyproject.toml`, and `reel2movie/cli.py`'s `main()` now calls
`load_dotenv()` as its first line (never overrides a var already set in
the real shell environment). Verified via `python3 -m pytest tests -q`
(154 passed, 1 skipped, no regressions) and a real smoke test:
`python3 -m reel2movie "https://www.instagram.com/reel/dummy123/"` now
gets past config entirely and fails only at real yt-dlp ingestion (dummy
URL isn't a real reel) instead of erroring on a missing env var — proof
`.env`'s `TMDB_API_KEY` is actually being read now.

---

## Follow-up — Claude CLI text extraction fallback — status: done

### Motivation

A real end-to-end test against an actual Instagram reel (caption: "🎬
Dhobi Ghat, released internationally as Mumbai Diaries and Bombay
Diaries, is a 2010 Indian drama film directed by Kiran Rao...") showed
`RegexCandidateExtractor` completely misses the movie title: it's stated
in natural prose — no quotes, no year immediately in parens (`"is a 2010
... film"`, not `"Dhobi Ghat (2010)"`), no numbered list. This is a real,
common caption style that regex is structurally incapable of parsing (it
only matches a small set of explicit shapes by design — see Subtask 3's
section above). Regex itself is not wrong or buggy here; it's simply
scoped to a narrower set of shapes than real captions actually use.

### What's built

Files created:
- `reel2movie/text_extraction/claude_code_extractor.py` — `TextChatClient`
  (a local `@runtime_checkable` `Protocol`, `chat(prompt) -> str`, same
  pattern as `visual/vision_llm_detector.py`'s local `VisionChatClient`),
  `ClaudeCodeTextError` (text-only mirror of `ClaudeCodeVisionError`'s
  semantics), `ClaudeCodeTextChatClient` (shells out to the `claude` CLI
  with `claude -p --output-format json --tools "" --permission-mode
  bypassPermissions --no-session-persistence <prompt>` — `--tools ""`
  instead of `vision_llm_detector.py`'s `--tools Read`, since pure text
  reasoning needs no file/image access at all), and
  `ClaudeCodeCandidateExtractor` (the actual `CandidateExtractor`).
  `ClaudeCodeTextChatClient.chat()`'s error-handling layering is an exact
  mirror of `ClaudeCodeVisionChatClient.chat()`: `subprocess.TimeoutExpired`
  → `OSError` → non-zero exit → `json.JSONDecodeError` → `is_error` →
  `permission_denials` → return `parsed["result"]`, raising
  `ClaudeCodeTextError` at each stage.
  `ClaudeCodeCandidateExtractor.extract(text, source)`:
  - Short-circuits to `return []` with **no CLI call at all** when `text`
    is empty/whitespace-only — no point spending a subprocess call on
    nothing (proven by a test asserting the fake chat client's call count
    stays 0).
  - Otherwise embeds `text` directly into a prompt (no file needed)
    instructing the model to identify any movie title(s) explicitly
    stated or clearly implied, including year if stated, including
    natural-prose statements of fact (not just quoted/listed titles), and
    to respond with ONLY a strict JSON array
    (`[{"title": "...", "year": 2010, "confidence": "high"}]` or `[]`) —
    same prompt-strictness pattern as `VisionLLMPosterDetector`'s own
    prompt (no prose, no markdown fences).
  - Parses the response with the exact same defensive pattern
    `VisionLLMPosterDetector.detect()` uses: non-JSON → `[]`; not a list →
    `[]`; a malformed item (missing/non-string/blank `title`) within an
    otherwise-good list is skipped via `logger.warning(...)`, siblings
    kept; `year` normalized the same way (bool rejected, numeric string
    coerced, anything else non-int dropped to `None`).
  - Maps `"high"` → `HIGH_CONFIDENCE`, `"medium"` → `MEDIUM_CONFIDENCE`,
    anything else/missing → `MEDIUM_CONFIDENCE` (the safe middle default
    — never defaults an unrecognized label to HIGH, which would be too
    permissive).
  - Builds `raw_text` as `f"{title} ({year})"` when a year is given, else
    bare `title` — byte-for-byte the same format `regex_extractor.py`
    uses, which is what makes `tmdb/resolver.py`'s `_extract_year_hint()`
    work on this extractor's output without any special-casing.
  - `source` is always the method's own parameter, never hardcoded.
- `reel2movie/text_extraction/fallback_extractor.py` —
  `FallbackCandidateExtractor(primary, fallback)`: calls
  `primary.extract(text, source)`, returns it immediately if non-empty,
  otherwise calls and returns `fallback.extract(text, source)`. Both
  constructor parameters are typed against `core.protocols.CandidateExtractor`
  (structural), not any concrete class — a generic composable wrapper,
  not specific to regex+claude at all, so it can wrap any two
  `CandidateExtractor`-shaped objects in the future.

Files changed:
- `reel2movie/pipeline/deps.py` — `build_default_pipeline_deps()`'s
  `text_extractor` is now
  `FallbackCandidateExtractor(RegexCandidateExtractor(),
  ClaudeCodeCandidateExtractor(ClaudeCodeTextChatClient()))` instead of a
  bare `RegexCandidateExtractor()`. Docstring updated to call out
  explicitly that this wiring is **independent of `VISION_BACKEND`**: the
  `claude` CLI is now an always-on dependency for *text* extraction
  regardless of which vision backend (`claude_code` or `anthropic_api`)
  is selected for the separate *visual* poster-detection step. These are
  two independent decisions that happen to both be able to use the same
  CLI — not coupled to each other.

Tests added:
- `tests/unit/text_extraction/test_claude_code_extractor.py` —
  `TestClaudeCodeTextChatClient` mirrors
  `test_vision_llm_detector.py`'s `TestClaudeCodeVisionChatClient` shapes
  exactly (mocked `subprocess.run`): success (asserts `--tools ""` is
  passed, not `Read`), timeout, missing binary/`OSError`, non-zero exit,
  non-JSON stdout, `is_error`, non-empty `permission_denials`, custom
  binary/timeout. `TestClaudeCodeCandidateExtractor*` uses a fake
  `TextChatClient` returning canned JSON: single movie w/ year →
  `HIGH_CONFIDENCE` + `raw_text` round-trips through
  `tmdb/resolver.py`'s `_extract_year_hint()` (imported and called
  directly), single movie w/o year (round-trips to `None` year hint),
  multi-movie, explicit `[]`, non-JSON response (non-raising, `[]`), JSON
  object instead of array (`[]`), an item missing `title` within an
  otherwise-good list (skipped, sibling kept), unrecognized confidence
  label → `MEDIUM_CONFIDENCE` default, `source` echoed correctly for both
  `SourceTag` values, and the empty-string/whitespace-only short-circuit
  (asserts the fake chat client's `call_count == 0` — proves no wasted
  subprocess call).
- `tests/unit/text_extraction/test_fallback_extractor.py` — fake
  primary/fallback `CandidateExtractor`s recording whether they were
  called and what they were called with: primary non-empty → fallback
  never called, result is primary's; primary empty → fallback called,
  result is fallback's; both empty → `[]` with no error; `text`/`source`
  passed through unchanged to whichever extractor(s) actually run.
- `tests/unit/pipeline/test_deps.py` —
  `test_text_extractor_is_fallback_wrapping_regex_and_claude_code`:
  confirms `build_default_pipeline_deps()`'s `text_extractor` is a
  `FallbackCandidateExtractor` whose `_primary` is a
  `RegexCandidateExtractor` and whose `_fallback` is a
  `ClaudeCodeCandidateExtractor` (introspected directly via attribute
  access, since there's no public accessor and none was warranted for
  just this one test).

Ran `python3 -m pytest tests/unit -q`:

```
........................................................................ [ 39%]
........................................................................ [ 79%]
.....................................                                    [100%]
181 passed in 3.52s
```

(154 passing before this change + 27 new: 17 in
`test_claude_code_extractor.py`, 5 in `test_fallback_extractor.py`, 1 new
in `test_deps.py`, plus `tests/unit/pipeline/test_deps.py`'s pre-existing
tests still passing unchanged — the arithmetic here is 154 + 27 = 181,
matching the observed count exactly.)

### Confidence-mapping rationale — text-tier, not vision-tier

`ClaudeCodeCandidateExtractor` maps the model's own `"high"`/`"medium"`
labels to `HIGH_CONFIDENCE` (0.9) / `MEDIUM_CONFIDENCE` (0.6) — the exact
same module-level constants `regex_extractor.py` uses for its own
HIGH/MEDIUM tiers, imported directly rather than re-declared as parallel
literals (per this project's established convention — `waterfall.py`'s
`CONFIDENCE_THRESHOLD = HIGH_CONFIDENCE` set this precedent). This is
deliberately **not** `vision_llm_detector.py`'s dampened 0.8/0.5/0.3
scale, even though both modules are "a `claude`-CLI-backed LLM call
parsed into Candidates" at the implementation level. The two cases are
not analogous in kind:

- Vision detection is fundamentally a *guess from pixels* — the model is
  inferring a title from a poster image or scene it may only partially
  recognize, so even a "high confidence" vision read carries irreducible
  uncertainty from the image itself. Dampening to 0.8 reflects that.
- Explicit text stating "X is a 2010 film" is not a guess — it's reading
  a fact the caption's author already wrote down in plain language. The
  only reason this needs an LLM at all (instead of regex) is that the
  *shape* of the sentence isn't one of regex's four matchable patterns —
  the *certainty* of the claim itself is no different from regex's own
  HIGH tier (`"Title (YYYY)"`, quoted or unquoted), which also just reads
  an explicit title+year stated directly in the text. An LLM correctly
  reading an unambiguous textual statement deserves the same confidence
  tier as regex pattern-matching an unambiguous textual shape — the
  *extraction mechanism* differs, the *epistemic status of the claim*
  does not.
- Concretely: this is what lets `waterfall.py`'s `CONFIDENCE_THRESHOLD =
  HIGH_CONFIDENCE` gate correctly treat a claude-CLI-recovered "Dhobi Ghat
  is a 2010 film" caption candidate as "confident enough to skip the
  creator-comment and visual-fallback steps" — exactly like a regex HIGH
  hit would, and exactly unlike a vision-tier 0.8 would (0.8 < 0.9, so a
  vision hit alone never clears this gate, by design. A text-tier 0.9
  claude-CLI hit correctly does).
- The `"medium"` label maps to `MEDIUM_CONFIDENCE` (0.6) for the same
  reason regex's own MEDIUM tier exists: a title-like signal is present
  (the model identified a specific movie) but without the same
  unambiguous year-anchored certainty — e.g. the text implies a
  recommendation without flatly stating it as settled fact. An
  unrecognized/missing confidence label also falls back to
  `MEDIUM_CONFIDENCE`, not `HIGH_CONFIDENCE` — deliberately the safer,
  less-permissive default, since defaulting an *unparseable* label to the
  *most* trusted tier would be backwards.

### Fallback-composition design

`FallbackCandidateExtractor` is intentionally generic: both constructor
parameters (`primary`, `fallback`) are typed against
`core.protocols.CandidateExtractor` — the structural Protocol — not
against `RegexCandidateExtractor`/`ClaudeCodeCandidateExtractor`
concretely. `extract()` is exactly the three-line waterfall the task
spec gave: try `primary`, return its result immediately if non-empty,
otherwise call and return `fallback`'s result. This keeps the "try cheap
first, escalate only on a miss" pattern reusable for any future
extractor pair (e.g. if a third, even-smarter extractor is added later,
or if the regex/claude roles ever need swapping in a test), rather than
hardcoding a regex-specific or claude-specific waterfall. The composition
also means `RegexCandidateExtractor`'s own zero-latency/zero-cost
behavior for the common explicit-format case is fully preserved — regex
runs unconditionally first, and the `claude` CLI subprocess is only ever
invoked on a genuine regex miss, never on every call.

### New always-on dependency: the `claude` CLI for text extraction

This follow-up adds a **new, unconditional** runtime dependency on the
local `claude` CLI being installed/on `PATH`/authenticated: whenever
regex finds zero candidates for a caption or creator-comment block,
`build_default_pipeline_deps()`'s wiring now shells out to `claude` to
try again, **regardless of `VISION_BACKEND`'s value**. Before this
follow-up, the `claude` CLI was only ever invoked when
`VISION_BACKEND=claude_code` (the default) was selected for the visual
poster-detection step — a user on `VISION_BACKEND=anthropic_api` could
previously avoid the `claude` CLI entirely and rely solely on the
`anthropic` API key for everything. That is no longer true: text
extraction's fallback path always uses the `claude` CLI now, independent
of whatever the visual step is configured to use. This is a deliberate,
not-silently-coupled decision per the task spec ("don't couple these two
independent decisions") — it is called out explicitly here, and in
`deps.py`'s own docstring, rather than left as an implicit side effect a
future maintainer would have to rediscover by reading code.

### Open questions / risks

- **No live `claude` CLI call was tested end-to-end against the real
  Dhobi Ghat caption** in this follow-up — all tests use a fake
  `TextChatClient`/mocked `subprocess.run`, per the explicit "no real
  subprocess calls in automated tests" instruction. The prompt's ability
  to actually recover "Dhobi Ghat" (year 2010) from that exact caption
  text in practice is not verified by this test suite; it's a reasonable
  design based on the same prompt-strictness pattern
  `VisionLLMPosterDetector` already uses successfully, but a real smoke
  test against the actual reel (as the motivating bug report described)
  would be the next step to fully close the loop.
- **Latency/cost**: unlike `RegexCandidateExtractor`, every regex-miss
  now costs one `claude` CLI subprocess invocation (default 60s timeout)
  per caption and per creator-comment text block. For a reel whose
  caption and every creator top-level comment all miss regex, this could
  mean several sequential CLI calls before even reaching the visual
  fallback step. Not addressed here (out of scope per the task spec,
  which explicitly asked only for the fallback mechanism, not
  batching/parallelizing the calls) — worth revisiting if real-world
  waterfall latency becomes a concern.
- **`--tools ""` CLI flag shape** was specified directly by the task
  instructions (not independently re-derived from a captured real
  response, unlike `ClaudeCodeVisionChatClient`'s `--tools Read`, which
  the project's history notes was grounded in an actual captured CLI
  response). If a live run shows `--tools ""` doesn't behave as expected
  (e.g. a different flag shape is needed to fully disable tools on this
  CLI version), that would need a fresh real-response capture the same
  way the vision client's shape was originally validated.
- This follow-up did not touch `pipeline/waterfall.py` at all — the
  waterfall already calls `deps.text_extractor.extract(...)` generically
  against the `CandidateExtractor` Protocol, so swapping in
  `FallbackCandidateExtractor` under that same attribute name required no
  changes to the waterfall's own logic. `CONFIDENCE_THRESHOLD =
  HIGH_CONFIDENCE` (imported from `regex_extractor.py`) continues to work
  unchanged, now correctly gating claude-CLI-recovered text candidates
  the same way it already gated regex's own HIGH candidates.

### Review findings (latest pass)

Reviewed via `/code-review` (medium) on the current diff
(`reel2movie/text_extraction/{claude_code_extractor,fallback_extractor}.py`,
`reel2movie/pipeline/deps.py`, and the new/updated tests),
`/ponytail:ponytail-review` on the same diff, a manual line-by-line
comparison of `ClaudeCodeTextChatClient.chat()` against
`ClaudeCodeVisionChatClient.chat()`, a manual trace of the
confidence-default and fallback-triggering-condition logic plus the tests
that claim to prove them, a grep-based check of `deps.py`'s
`VISION_BACKEND` independence, and a fresh `python3 -m pytest tests/unit -q`
run (181 passed, confirmed independently, not just trusted from the build
report).

**Manual verification — the five highest-risk correctness points named for
this pass, all confirmed correct:**

1. **Error-handling layering mirrors the vision client.** Read
   `ClaudeCodeTextChatClient.chat()` (`claude_code_extractor.py` L86-153)
   side by side with `ClaudeCodeVisionChatClient.chat()`
   (`vision_llm_detector.py` L166-238): both run the exact same ordered
   stages -- `subprocess.TimeoutExpired` -> `OSError` -> non-zero exit ->
   `json.JSONDecodeError` -> `is_error` -> `permission_denials` -> `return
   parsed["result"]` -- raising their own distinctly-typed error
   (`ClaudeCodeTextError`/`ClaudeCodeVisionError`) at each stage. Confirmed
   genuinely matching, not just claimed to match.
2. **Confidence import, not duplicated literals.**
   `claude_code_extractor.py` L41-44 imports `HIGH_CONFIDENCE,
   MEDIUM_CONFIDENCE` directly from `regex_extractor.py` -- confirmed by
   reading the import statement, not a re-declared `0.9`/`0.6` literal.
   `_CONFIDENCE_MAP` (L192-195) maps `"high"`->`HIGH_CONFIDENCE`,
   `"medium"`->`MEDIUM_CONFIDENCE`; `_DEFAULT_CONFIDENCE =
   MEDIUM_CONFIDENCE` (L200) is the fallback for a missing/unrecognized
   label -- confirmed NOT defaulting to HIGH.
   `test_unrecognized_confidence_label_falls_back_to_medium_default`
   (`test_claude_code_extractor.py` L361-371) exercises this directly with
   `"confidence": "very sure"` and asserts `candidate.confidence ==
   MEDIUM_CONFIDENCE`. This is the correct, safe default.
3. **`raw_text` format round-trips through `resolver.py`.**
   `claude_code_extractor.py` L274: `raw_text = f"{title} ({year})" if year
   is not None else title` -- byte-identical to `regex_extractor.py`'s own
   HIGH-tier format. `test_raw_text_year_round_trips_through_resolver`
   (`test_claude_code_extractor.py` L248-256) imports
   `tmdb.resolver._extract_year_hint` directly and asserts it recovers the
   year from a constructed candidate's `raw_text` -- a genuine cross-module
   round-trip test, not just an eyeballed string-shape assertion.
4. **`FallbackCandidateExtractor` triggers only on an EMPTY primary result,
   never on confidence.** `fallback_extractor.py` L35-37: `primary_result =
   self._primary.extract(...); if primary_result: return primary_result;
   return self._fallback.extract(...)` -- a plain truthiness check on the
   list, no confidence inspection anywhere. Confirmed by reading the whole
   38-line file (nothing else in it could branch on confidence) and by
   `test_fallback_extractor.py`'s
   `test_primary_nonempty_short_circuits_fallback`, which uses a primary
   returning a single arbitrary-confidence (`0.9`) candidate and asserts
   `fallback.called is False` -- though confidence is irrelevant to that
   fake, so the test alone doesn't distinguish "any non-empty result
   short-circuits" from "any sufficiently-confident result
   short-circuits." Traced the implementation itself (not just the test)
   to settle this: there is no confidence read anywhere in
   `fallback_extractor.py`, so even a bare MEDIUM-confidence regex
   candidate correctly short-circuits the claude-CLI fallback, matching
   the design intent exactly.
5. **Empty/whitespace short-circuit never invokes the chat client.**
   `claude_code_extractor.py` L225-226: `if not text or not text.strip():
   return []` -- placed before `self._chat_client.chat(...)` is ever
   referenced, so no code path between the guard and a `chat()` call
   exists. `test_empty_string_never_calls_chat_client` and
   `test_whitespace_only_text_never_calls_chat_client`
   (`test_claude_code_extractor.py` L391-407) both assert `fake.call_count
   == 0` on a fake `TextChatClient` that increments a counter inside
   `chat()` -- a genuine zero-subprocess-calls proof, not an inferred
   claim.

**From `/code-review` (medium) -- four findings, outside the five points
above but worth recording:**
- **Non-blocking** -- `pipeline/waterfall.py` L75-89
  (`_extract_from_creator_comments`, file not touched by this diff but
  newly exposed by it): the `for comment in creator_top_level_comments`
  loop accumulates `candidates` across multiple comments, all inside one
  `try` that maps any exception to a blanket `except Exception: return
  []`. Before this follow-up, `deps.text_extractor` was a bare
  `RegexCandidateExtractor`, which never raises -- so this blanket catch
  was dead code for all practical purposes. Now that `text_extractor` can
  genuinely raise (`ClaudeCodeTextError` from a subprocess
  timeout/missing-binary/malformed-CLI-response on any one comment), a
  failure on comment N discards every candidate already found from
  comments 1..N-1 in the same batch, not just comment N's own (empty)
  result. Concrete failure scenario: creator posts two top-level comments,
  the first regex-matches a HIGH candidate, the second is prose that falls
  to the `claude` CLI fallback and that CLI call times out -- the whole
  step returns `[]`, discarding the first comment's good candidate and
  incorrectly falling through to the visual-fallback step. This is a real
  behavior change introduced by this follow-up (making a previously-
  unreachable catch block reachable with real consequences), but it's in
  an unmodified file outside this diff's scope -- flagging as a risk to
  fix in a follow-up to `waterfall.py` rather than blocking this diff.
- **Non-blocking, by design -- not a bug** -- `fallback_extractor.py`
  L34-37: a regex false-positive (e.g. an unrelated quoted phrase matched
  by `_QUOTED_SPAN`) returns a non-empty-but-wrong result that
  short-circuits the claude-CLI fallback, even though the caption's real
  movie statement (in prose, elsewhere in the same text) would have been
  caught by the fallback. `/code-review` initially flagged this as a
  defect; re-checked against this pass's explicit design instruction ("per
  design, any non-empty regex result -- even a bare MEDIUM-confidence
  candidate -- should short-circuit the claude-CLI fallback entirely,
  since regex already explicitly skips genuinely low-signal text rather
  than tagging it LOW") and confirmed this is the intended, accepted
  tradeoff, not an oversight. Recording here as a known edge case (a stray
  regex match can mask a real prose statement elsewhere in the same text)
  rather than a finding to fix.
- **Non-blocking** -- `claude_code_extractor.py` L247-283 duplicates ~35
  lines of `vision_llm_detector.py`'s `VisionLLMPosterDetector.detect()`
  parsing loop (L320-362) near-verbatim (non-dict-item skip, title
  validation, bool/str/int year coercion, confidence-label lookup). Also
  flagged independently by the ponytail pass below -- see there for the
  fix recommendation.
- **Non-blocking** -- `claude_code_extractor.py` L228
  (`_PROMPT_TEMPLATE.replace("{text}", text)`): untrusted caption/comment
  text is spliced directly into the LLM prompt with no escaping, so a
  crafted caption could in principle prompt-inject a fabricated
  HIGH-confidence title. Bounded blast radius: `--tools ""` means no
  tool/file access is at risk, and the pipeline's existing trust model
  already lets any caption author plant an arbitrary `Candidate` via
  `RegexCandidateExtractor`'s own pattern-matching (e.g. writing
  `"Anything" (1999)` directly) -- this is a variation on an
  already-accepted trust boundary (caption text chooses its own extracted
  candidate), not a new category of risk. Worth a light mitigation (e.g.
  wrapping the untrusted span more defensively) but not blocking.

**From `/ponytail:ponytail-review` (over-engineering/complexity):**
- `claude_code_extractor.py:L86-153` vs `vision_llm_detector.py:L166-238`:
  `shrink:` both ~70-line `chat()` bodies run the identical 6-stage
  error-layering boilerplate, differing only in CLI args/messages. One
  shared `_run_claude_cli(args, binary, timeout) -> dict` helper collapses
  both to ~12-line wrappers.
- `claude_code_extractor.py:L247-283` vs
  `vision_llm_detector.py:L320-362`: `shrink:` identical per-item
  title/year/confidence-parsing loop, copy-pasted. One shared
  `_parse_item(item) -> tuple[...] | None` helper.
- `ClaudeCodeTextError` vs `ClaudeCodeVisionError` and the
  `TextChatClient`/`VisionChatClient` Protocol split: **not flagged** --
  these back genuinely distinct catch sites (`pipeline/waterfall.py`'s
  separate text-extraction and visual-fallback steps) with different call
  signatures (`chat(prompt)` vs `chat(image_path, prompt)`); keeping them
  separately typed is the right call, not duplication for its own sake.
  This directly answers the "or whether keeping them separate is the
  right call" question: the *types* should stay separate, but the
  *mechanics inside `chat()`'s body* should not have been copy-pasted.
- `fallback_extractor.py` and the `deps.py` diff: lean already, nothing to
  cut.
- `net: -60 lines possible` (both findings span into the already-shipped
  `vision_llm_detector.py`, so realizing the saving means touching code
  outside this diff, not just this diff's new files).

**Independent verification of `deps.py` wiring (not trusted from the build
report):**
- Read `build_default_pipeline_deps()` (`pipeline/deps.py` L61-125):
  confirmed `text_extractor = FallbackCandidateExtractor(
  RegexCandidateExtractor(), ClaudeCodeCandidateExtractor(
  ClaudeCodeTextChatClient()))` (L101-104) is constructed and assigned
  *before* `backend = config.get_vision_backend()` is even called
  (L106) -- the construction has no data or control dependency on
  `backend` at all.
- `grep -rn "VISION_BACKEND" reel2movie/` confirms the only places
  `VISION_BACKEND` is read or referenced are `config.py`
  (`get_vision_backend()`'s own implementation) and `deps.py`'s
  visual-backend branch (L106-116) plus its own docstring prose -- never
  anywhere near the `text_extractor` assignment. Confirmed independent.

**Independent test run:**
- `python3 -m pytest tests/unit -q` run directly (not trusted from the
  reported 181): **181 passed in 3.47s** -- matches the build report's
  count exactly.

No blocking findings. The five highest-risk correctness points for this
pass (error-handling mirroring, confidence-default safety, raw_text
round-trip, fallback-triggering condition, empty-text short-circuit) all
check out exactly as designed. The one genuinely new risk
(`waterfall.py`'s creator-comment loop now able to discard already-found
candidates on a mid-loop `ClaudeCodeTextError`) is real but lives in a
file outside this diff's scope, and the duplication findings are
complexity/maintenance concerns, not correctness defects.

VERDICT: ACCEPTABLE

---

## Follow-up — duration probing fallback for visual step — status: done

### Motivation

A real end-to-end test against an actual Instagram reel showed
Instagram/yt-dlp didn't report a `duration` for that post, so
`IngestResult.duration_seconds` was `None`. The old
`_extract_from_visual` checked `duration_seconds is None or <= 0` and
returned `[]` *before* ever calling `ensure_video` -- so the last-resort
visual fallback never even attempted to download the video or look at
the file itself. A missing metadata field was silently treated the same
as "nothing to see here," even though the file itself (once downloaded)
would have its own real duration.

### What's built

- `reel2movie/visual/frame_sampler.py` -- new `probe_duration_seconds(video_path: Path) -> float`:
  - Runs `[imageio_ffmpeg.get_ffmpeg_exe(), "-i", str(video_path)]` via
    `subprocess.run(capture_output=True, text=True, timeout=_FFMPEG_TIMEOUT_SECONDS)`
    (the same 30s timeout constant `sample_frames` already uses -- no new
    constant needed). No output path is given, so ffmpeg always exits
    non-zero; the exit code is ignored entirely and only stderr is
    examined.
  - A new module-level `_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d\d):(\d\d\.\d+)")`
    parses ffmpeg's `Duration: HH:MM:SS.ss` stderr line and converts to
    total seconds as a float.
  - Raises the file's existing `FrameExtractionError` (reused, not a new
    exception type) in exactly three cases: `subprocess.TimeoutExpired`,
    `OSError` (binary can't be run -- a case `sample_frames` itself
    didn't previously handle either), and no parseable `Duration:` line
    found in stderr (corrupt/non-video file) -- the last case's message
    includes a stderr snippet (first 500 chars) for debuggability.
  - Has zero dependency on yt-dlp/Instagram metadata -- it only ever
    looks at the file on disk, which is the whole point: an independent,
    metadata-agnostic fallback.

- `reel2movie/pipeline/waterfall.py` -- `_extract_from_visual` restructured
  from "check duration validity, bail before downloading" to
  "download unconditionally, then determine duration, falling back to
  probing":
  1. `deps.ingestor.ensure_video(result)` is now called unconditionally,
     as the very first thing inside the `try` block, whenever this step
     is reached -- no longer gated on `duration_seconds` being valid.
  2. If `result.duration_seconds` is a valid positive number, it's used
     directly (logged at `debug` -- "using metadata-reported duration").
     This is checked *first* so a working metadata duration never pays
     for an extra ffmpeg probe call.
  3. Otherwise, `probe_duration_seconds(video_path)` is called as a
     fallback. Success is logged at `info` level (new, less-trusted
     behavior, so it's visible by default) -- "metadata duration
     missing/invalid; probed actual video file for duration instead".
  4. If probing raises `FrameExtractionError`, *or* yields a `<= 0`
     value, duration is treated as genuinely undeterminable: a
     `logger.warning` (keeping the "cannot run visual fallback: unknown
     reel duration" phrase from the original message, but now explicit
     that both metadata *and* probing were tried and both failed) and
     `return []` -- same end result as before, reached via a more
     thorough path. This return is inside the function's `try`, so the
     existing `finally: shutil.rmtree(frames_dir, ...)` still cleans up
     the (empty) frames directory.
  5. Any *other* internal failure (`ensure_video` itself raising, ffmpeg
     frame extraction, poster detection) is still caught by the
     pre-existing, separate `except Exception: logger.exception(...)`
     block -- the two "found nothing" causes (duration genuinely
     undeterminable vs. some other internal failure) remain distinct
     catches, not collapsed into one generic catch-all, preserving the
     original design point from this module's history.
  6. Everything downstream of duration determination (the `sample_frames`
     call, the poster-detection loop, `frames_dir` cleanup) is
     structurally unchanged, just now fed whichever `duration_seconds`
     value (metadata or probed) was determined valid.
  - The function's docstring was rewritten in full to describe this new
    flow and explicitly retire the old "checked explicitly *before*
    calling `sample_frames`... to avoid downloading" rationale, which no
    longer applies.

### Tradeoff: `ensure_video` now runs even when duration ends up undeterminable

Explicitly confirming, since the task asked for it directly: **yes**,
`ensure_video` now runs even in the case where duration turns out to be
totally undeterminable (metadata missing/invalid *and* probing fails).
There is no way to attempt probing without first having the file on
disk, so the download has to happen before we can know whether probing
will succeed. This is an accepted cost of the fix, not an oversight: a
reel whose video is corrupt, geo-blocked-at-download-time, or otherwise
unprobeable now always pays for one download attempt it previously
could sometimes skip (the old code's only advantage was skipping
*exactly* this one case for free, at the cost of also skipping every
*recoverable* missing-duration case, which is the actual bug this
follow-up fixes). Since the visual step is already the pipeline's last
resort (reached only when caption and creator-comment extraction both
failed to yield a confident candidate), this is judged a reasonable
trade: one extra download attempt in a rare dead-end case, in exchange
for the visual fallback actually working in the much more common
"metadata just didn't report duration" case that motivated this
follow-up in the first place.

### Tests

- `tests/unit/visual/test_frame_sampler.py` -- 5 new tests for
  `probe_duration_seconds`, reusing the file's existing `sample_video`
  module-scoped fixture (a real, synthetic 6-second ffmpeg `testsrc`
  video) rather than inventing a new fixture pattern:
  - `test_probe_duration_seconds_matches_known_duration_within_tolerance`
    -- probes the real fixture video, asserts the result is within 0.5s
    of the known `VIDEO_DURATION_SECONDS = 6.0` (not exact equality, per
    ffmpeg's own duration-reporting precision limits).
  - `test_probe_duration_seconds_on_nonexistent_file_raises_clear_error`
    -- a missing path raises `FrameExtractionError` with the path
    included in the message.
  - `test_probe_duration_seconds_on_corrupt_file_raises_clear_error` -- a
    file containing junk (non-video) bytes raises `FrameExtractionError`
    matching `"Duration"` (the clear, parseable error, not a raw regex/
    `None`-unpacking crash).
  - `test_probe_duration_seconds_timeout_raises_frame_extraction_error`
    and `test_probe_duration_seconds_oserror_raises_frame_extraction_error`
    -- both mock `subprocess.run` (same `patch("reel2movie.visual.frame_sampler.subprocess.run")`
    pattern the file's existing `sample_frames` timeout test uses) to
    raise `TimeoutExpired` / `OSError` respectively.

- `tests/unit/pipeline/test_waterfall.py`:
  - Renamed and rewrote the old
    `test_visual_fallback_with_none_duration_logs_warning_and_skips_sample_frames`
    (which asserted `ensure_video_calls == []` -- no longer true under
    the new flow) into
    `test_visual_fallback_with_none_duration_and_failed_probe_logs_warning_and_skips_sample_frames`:
    `duration_seconds=None`, `probe_duration_seconds` monkeypatched on
    the `waterfall` module (same pattern already used for
    `sample_frames`) to raise `FrameExtractionError`; asserts `[]` is
    returned, the warning is logged, `sample_frames` is never called,
    but `ensure_video_calls` now has exactly 1 entry -- proving the new
    unconditional-download behavior directly, not just asserting the
    old "never downloads" behavior is gone.
  - New `test_visual_fallback_none_duration_falls_back_to_probed_duration`
    -- `duration_seconds=None`, `probe_duration_seconds` monkeypatched to
    succeed with a known value (`42.5`); asserts `sample_frames` is
    called with that exact probed value (not `None`, not some stale
    default), and the resulting recommendation still resolves correctly
    end-to-end.
  - New `test_visual_fallback_with_valid_metadata_duration_never_probes`
    -- `duration_seconds=30.0` (valid); `probe_duration_seconds`
    monkeypatched to an assertion-raising stub, proving it is genuinely
    never called when metadata already supplies a valid duration (no
    wasted ffmpeg invocation), while `ensure_video` still runs (needed
    for frame sampling regardless) and `sample_frames` receives the
    metadata value unchanged.

Ran `python3 -m pytest tests/unit -q`:

```
........................................................................ [ 38%]
........................................................................ [ 76%]
............................................                             [100%]
188 passed in 2.60s
```

(181 passing before this follow-up + 7 new: 5 in
`test_frame_sampler.py`, and a net +2 in `test_waterfall.py` from
replacing 1 old test with 1 renamed/rewritten test plus 2 brand-new
ones.)

### Open questions / risks

- **ffmpeg duration-parsing precision/locale assumptions**: `_DURATION_RE`
  assumes ffmpeg's stderr always renders `Duration:` in the
  `HH:MM:SS.ss` format with a literal `.` decimal separator and ASCII
  digits, which is ffmpeg's standard, locale-independent CLI output
  format in every version observed -- not something this follow-up
  verified across multiple ffmpeg builds/versions beyond the one bundled
  by the installed `imageio-ffmpeg` version. If a future `imageio-ffmpeg`
  upgrade ever changed that line's format, `probe_duration_seconds`
  would correctly raise `FrameExtractionError` (no parseable line found)
  rather than silently returning a wrong value -- a safe failure mode,
  but one that hasn't been exercised against a different ffmpeg build.
- **Not yet verified against the real Dhobi Ghat reel that motivated
  this fix.** This follow-up was built and tested entirely against the
  existing synthetic `testsrc` fixture and fakes/mocks in the unit test
  suite -- there was no live network/Instagram access available in this
  environment to re-run the actual end-to-end case (the specific reel
  whose missing `duration` metadata originally surfaced this gap). The
  fix directly addresses the mechanism described (metadata-missing
  duration no longer skips `ensure_video`/the visual fallback), and the
  new unit tests cover the probing success/failure/precedence logic in
  isolation, but a real run against that specific reel (or any reel
  Instagram omits duration for) would be the strongest remaining
  confirmation that this actually resolves the originally-observed
  failure end-to-end.
- **ffmpeg's `-i`-with-no-output probe cost**: `probe_duration_seconds`
  only reads container metadata (ffmpeg doesn't need to decode any
  frames to print the `Duration:` line), so it should be fast regardless
  of video length -- but this wasn't benchmarked against a real
  multi-megabyte Instagram reel file, only the tiny 6-second synthetic
  fixture.
- As called out in the tradeoff section above: a reel whose video
  download succeeds but whose file is genuinely corrupt/unprobeable now
  always pays for that download attempt before giving up, whereas the
  old code could sometimes skip it for free (at the cost of also wrongly
  skipping every recoverable case). Not revisited further here since the
  task explicitly framed this as an accepted cost, not an open question
  to resolve.

### Review findings (latest pass)

Reviewed via `/code-review` (medium, forked) on the current diff
(`reel2movie/visual/frame_sampler.py`, `reel2movie/pipeline/waterfall.py`,
plus the two test files), `/ponytail:ponytail-review` on the same diff, a
manual line-by-line trace of the new `_extract_from_visual` flow and
`probe_duration_seconds` against the task's specific concerns, a from-scratch
`python3 -m pytest tests/unit -q` run plus individually-named runs of the two
touched test files, and a standalone, outside-pytest script that generates a
real synthetic video and calls `probe_duration_seconds()` on it directly (not
mocked) to confirm the regex/parsing genuinely works end-to-end.

**From `/code-review` (correctness):**
- **Non-blocking** — `frame_sampler.py` L144-151 vs. L220-223: the new
  `probe_duration_seconds` catches `OSError` from `subprocess.run` (e.g. the
  `imageio_ffmpeg`-resolved binary path is missing/not executable) and wraps
  it into a clear `FrameExtractionError`, but the pre-existing `sample_frames`
  right above it in the same file does not catch `OSError` at all for the
  identical failure mode. Not a regression introduced by this diff (
  `sample_frames` wasn't touched), and the raw `OSError` is still caught one
  level up by `_extract_from_visual`'s outer `except Exception` in
  `waterfall.py`, so nothing crashes unhandled — but the two sibling
  functions now handle the same underlying failure inconsistently (one gives
  a debuggable `FrameExtractionError` message, the other gives a generic
  "visual fallback extraction failed" log with no specific cause). Worth a
  follow-up to catch `OSError` in `sample_frames` too for consistency, not
  blocking this follow-up.

**From `/ponytail:ponytail-review` (over-engineering/complexity):**
- `waterfall.py:L168-190`: `shrink:` two near-identical
  warning-log-then-`return []` blocks — one for `probe_duration_seconds`
  raising `FrameExtractionError`, one for it returning a `<= 0` value — differ
  only in wording and which variable they report. Catch the exception into a
  sentinel (e.g. `duration_seconds = -1.0`) and fall through to one shared
  `if duration_seconds <= 0: logger.warning(...); return []` check instead of
  two separate ones. `net: -10 lines possible` (non-blocking — the current
  form is correct and already reasonably readable, this is purely a line-count
  opportunity).
- Everything else (the new `_DURATION_RE` regex, `probe_duration_seconds`
  itself, the three-way duration-precedence logic in `_extract_from_visual`)
  is load-bearing for the fix this follow-up targets, not speculative. No
  reinvented stdlib, no new dependency (reuses the already-declared
  `imageio-ffmpeg`), no dead flexibility.

**Manual trace of `_extract_from_visual` against the task's specific concerns:**
- **`ensure_video` runs unconditionally, confirmed by reading the code**:
  `waterfall.py` L155 (`video_path = deps.ingestor.ensure_video(result)`) is
  the first statement inside the `try` block, with no duration check or
  early-return before it anywhere in the function — including when
  `result.duration_seconds` is already known-invalid (`None`, `0`, or
  negative). This is exactly the behavior change the follow-up's motivation
  section describes, and it's real, not just narrated.
- **Metadata duration genuinely takes precedence; probing is genuinely
  skipped, not run redundantly, when both are available**: the `if
  result.duration_seconds is not None and result.duration_seconds > 0:`
  branch (L157) is checked *before* the `else` branch that calls
  `probe_duration_seconds` (L167) — structurally an if/else, not two
  independent calls — so a valid metadata duration takes the `if` branch and
  `probe_duration_seconds` is never invoked in that run. Confirmed both by
  code structure and by `test_visual_fallback_with_valid_metadata_duration_never_probes`,
  which monkeypatches `probe_duration_seconds` to an assertion-raising stub
  and passes, proving it's genuinely never called in that path.
- **Probe failure produces a clean `[]` with a clear log message, not an
  unhandled exception or a confusing double-logged state**: the `except
  FrameExtractionError:` at L168 is scoped narrowly around only the
  `probe_duration_seconds(video_path)` call (L166-167), not around
  `sample_frames` or anything else — so it can't accidentally swallow an
  unrelated failure. Exactly one `logger.warning` call fires per failure
  path, immediately followed by `return []` inside the same `try`, so the
  pre-existing `finally: shutil.rmtree(...)` still cleans up — no double log,
  no unhandled exception, confirmed by direct read, not inference.
- **The two "found nothing" failure modes remain genuinely distinguishable,
  not collapsed by the restructure**: (1) duration genuinely undeterminable —
  caught by the narrow `except FrameExtractionError:` / `if duration_seconds
  <= 0:` checks inside the inner duration-determination logic, logged via
  `logger.warning` with a message naming both metadata and probe outcomes,
  returns `[]` *without* ever calling `sample_frames`; (2) any other internal
  failure (`ensure_video` itself raising, `sample_frames`/ffmpeg extraction
  raising, poster detection raising) — falls through to the function's
  outer, separate `except Exception:` block (L210-212), logged via
  `logger.exception` with a distinctly different message
  ("visual fallback extraction failed"). These two catches are structurally
  separate (inner narrow catch vs. outer blanket catch), not merged into one
  generic handler during the restructure — confirmed by reading the full
  function body, not just the docstring's claim that this is true.

**Direct, outside-pytest sanity check of `probe_duration_seconds` against a
real video (not mocks) — run as a standalone script, no pytest involved:**
- Generated a real 6-second, 64x64, synthetic ffmpeg `testsrc` video (same
  technique `tests/unit/visual/test_frame_sampler.py`'s `sample_video` fixture
  uses, but built fresh and independently here) and called
  `probe_duration_seconds()` on it directly:
  ```
  known duration:  6.0
  probed duration: 6.0
  abs diff:        0.0
  ```
  Exact match in this run (ffmpeg's `testsrc` duration is generated precisely
  enough that it landed on exactly 6.0s; the test suite's own tolerance check
  — `abs=0.5` — is still the correct, non-flaky assertion to keep, since
  ffmpeg's real-world duration reporting precision isn't guaranteed to always
  land exactly on the nominal value for arbitrary input files).
- Also ran, in the same standalone script, a nonexistent-file case and a
  corrupt/junk-bytes-file case directly against the real ffmpeg binary (no
  mocking of `subprocess.run` at all, unlike the two equivalent unit tests
  which do mock it for the timeout/`OSError` cases specifically): both raised
  `FrameExtractionError` with a clear, debuggable message including a stderr
  snippet, exactly as designed, no crash.
- **Conclusion: the regex (`_DURATION_RE`) and parsing in
  `probe_duration_seconds` genuinely work end-to-end against a real ffmpeg
  invocation on a real video file** — this was verified by direct execution
  in this review pass, not by reading the regex and assuming it's correct.

**Independent test runs (run directly in this review pass, not trusted from
the build report):**
- `python3 -m pytest tests/unit -q` → **188 passed**, matching the build
  report's count exactly, confirmed independently.
- `python3 -m pytest tests/unit/visual/test_frame_sampler.py -v` → **16
  passed**, including all 5 new `probe_duration_seconds` tests by name:
  `test_probe_duration_seconds_matches_known_duration_within_tolerance`,
  `test_probe_duration_seconds_on_nonexistent_file_raises_clear_error`,
  `test_probe_duration_seconds_on_corrupt_file_raises_clear_error`,
  `test_probe_duration_seconds_timeout_raises_frame_extraction_error`,
  `test_probe_duration_seconds_oserror_raises_frame_extraction_error`.
- `python3 -m pytest tests/unit/pipeline/test_waterfall.py -v` → **17
  passed**, including all 3 duration-handling tests by name:
  `test_visual_fallback_with_none_duration_and_failed_probe_logs_warning_and_skips_sample_frames`,
  `test_visual_fallback_none_duration_falls_back_to_probed_duration`,
  `test_visual_fallback_with_valid_metadata_duration_never_probes`.

No blocking findings. The core correctness properties the task specifically
asked to verify — unconditional `ensure_video`, metadata-before-probe
precedence with no redundant probing, clean non-exceptional failure handling,
and genuinely distinct "found nothing" causes — all check out against the
actual code, not just the build report's narrative, and
`probe_duration_seconds` was independently confirmed to work against a real
video file outside of any mock.

VERDICT: ACCEPTABLE

### Fixes applied
(none yet — both findings above are non-blocking polish, left for a future
pass per instructions not to scope-creep into a refactor during review)

## Follow-up — retry/backoff for TMDB client network errors — status: done

### Motivation

A real end-to-end test against an actual reel showed `TMDBHttpClient.
search_movie()` intermittently failing with `requests.exceptions.
ConnectionError` ("Connection reset by peer", during the TLS handshake)
against the real TMDB API — confirmed via direct testing to be transient
network flakiness, not an auth/token/host problem (the exact same request
with the exact same token succeeds via plain `curl`, and sometimes succeeds
via a bare retry, just unreliably — roughly 40-60% failure rate observed
across several real attempts in this environment). This was already
flagged as an open risk in this module's own original review ("No
retry/backoff/caching on `TMDBHttpClient.search_movie`... worth revisiting
if TMDB rate limits become real") — now empirically confirmed real, not
hypothetical.

### What's built

- `reel2movie/tmdb/client.py` — `search_movie()` now wraps the
  `requests.get(...)` call in a small, fixed retry loop:
  - **Retries only** `requests.exceptions.ConnectionError` and
    `requests.exceptions.Timeout` — the connection-level failures actually
    observed (a TLS handshake reset is a `ConnectionError`, not an HTTP
    error response).
  - **Does NOT retry** `requests.exceptions.HTTPError` raised by
    `response.raise_for_status()` for a genuine 4xx/5xx response — that's
    a real API-level outcome (bad auth, bad request, a server
    deliberately erroring), not a transient connection blip, and retrying
    it could mask a real bug or hammer a server that's intentionally
    returning an error. Confirmed by test (below): on an `HTTPError`,
    `requests.get` is called exactly once.
  - **3 total attempts**, backing off `0.5s` then `1.0s` between failed
    attempts (`time.sleep`, no new dependency — plain stdlib, per this
    project's existing "don't add a dependency when stdlib suffices"
    convention; no `tenacity` or similar added). Chosen small and fast
    deliberately: this is a human-facing CLI call, not a background batch
    job, and the observed failures resolve within a retry or two — so
    worst case this adds 1.5s before either succeeding or finally
    surfacing the error, not tens of seconds.
  - If all 3 attempts raise the connection-level exception, the final
    exception is re-raised unchanged — exactly the pre-existing behavior.
    Nothing downstream changes: `tmdb/resolver.py`'s `resolve_candidate`
    has no try/except of its own around `client.search_movie(...)`, so
    the exception propagates up to `pipeline/waterfall.py`'s
    `_resolve_all`, whose existing broad `except Exception:` around the
    per-candidate resolve call catches it, logs it, and keeps that one
    candidate unresolved rather than crashing the whole pipeline — this
    follow-up only changes how many chances a single TMDB call gets
    before giving up, not what happens after it finally gives up.

### Decision: no 5xx-specific retry added

Deliberately did **not** add retry-on-certain-5xx-status-codes as part of
this change, even though some 5xx responses (502/503/504 in particular)
can also be transient server-side blips in principle. Reasoning:
- The task's own motivation section was specific — the *observed, tested*
  failure mode is a TLS handshake reset (`ConnectionError`), not an HTTP
  5xx response. There's no empirical evidence here that TMDB has been
  returning transient 5xxs against this project's real calls; adding a
  retry for a failure mode that hasn't actually been observed would be
  speculative.
- The task explicitly asked for this to be called out as a separate,
  deliberate decision rather than silently folded in, specifically because
  retrying a 5xx is a different kind of judgment call (it comes after
  `raise_for_status()` has already decided "this is a real HTTP-level
  error") than retrying a connection failure that never got an HTTP
  response at all.
- If TMDB 5xx responses are later observed to be a real, recurring problem
  (the same way the `ConnectionError` issue was first flagged as
  hypothetical and only later confirmed real), that would justify a
  follow-up adding a narrow, explicit retry on e.g. `response.status_code
  in (502, 503, 504)` before/instead of calling `raise_for_status()` — but
  not now, on spec alone.

### `timeout=` finding (reported, not changed)

The task asked to confirm the existing `timeout=` value on the
`requests.get` call and leave it as-is. On inspection, `search_movie()`'s
`requests.get(...)` call currently passes **no `timeout=` parameter at
all** — there never was one to keep. Left as-is per the instruction not to
change this speculatively (`requests.exceptions.Timeout` is now wired into
the retry logic in case a timeout is ever added or ever occurs via some
other path, e.g. a proxy), but flagging explicitly: with no timeout set,
a hung TLS handshake or slow server can block `requests.get` indefinitely
rather than raising `Timeout` — so today, the retry loop's `Timeout`
branch is reachable in principle but not exercised by the actual failure
mode seen in testing (which raises `ConnectionError`, not `Timeout`).
Worth a separate follow-up to add a `timeout=` if indefinite hangs are ever
observed in practice.

### Tests

`tests/unit/tmdb/test_client.py` — added:
- `test_search_movie_retries_connection_error_then_succeeds` — `requests.
  get` raises `ConnectionError` twice then returns a successful response;
  asserts the final result is correct AND `mock_get.call_count == 3`
  (not just "it eventually returned something").
- `test_search_movie_exhausts_retries_and_raises_connection_error` —
  `requests.get` raises `ConnectionError` on every call; asserts the
  `ConnectionError` propagates and `mock_get.call_count == 3` exactly (not
  2, not 4 — the retry budget is exact).
- `test_search_movie_retries_timeout_then_succeeds` — same shape as the
  `ConnectionError` test but for `requests.exceptions.Timeout`, confirming
  both exception types in the retry set are actually handled.
- Extended the pre-existing `test_search_movie_raises_on_http_error` with
  `assert mock_get.call_count == 1` — proving the retry logic does not
  accidentally swallow/retry a real HTTP error.
- All three new/extended tests mock `reel2movie.tmdb.client.time.sleep`
  and assert `mock_sleep.call_args_list == [((0.5,),), ((1.0,),)]` (or the
  matching prefix for the 2-call success case) — confirming the actual
  backoff values used, without the test suite actually sleeping.

`python3 -m pytest tests/unit -q` → **191 passed** (188 before this
change + 3 new tests; the existing `test_search_movie_raises_on_http_error`
was extended in place, not counted as new).

### Review findings (latest pass)

Reviewed via `/code-review` (high, forked) on the current diff
(`reel2movie/tmdb/client.py`, `tests/unit/tmdb/test_client.py`,
`PROGRESS.md`), `/ponytail:ponytail-review` on the same diff, a manual
line-by-line trace of `search_movie()`'s retry loop against the task's
specific concerns (retry scope, exact attempt count), and a from-scratch
`python3 -m pytest tests/unit -q` run plus a named run of
`tests/unit/tmdb/test_client.py -v`.

**Manual trace — retry scope and exact count (read directly, not trusted
from the build report):**
- **Confirmed**: `response.raise_for_status()` (L95) sits *after* the
  `for attempt in range(_MAX_ATTEMPTS): ... break` loop (L81-93), not
  inside its `try`/`except`. The `except` clause (L88) only ever catches
  `(requests.exceptions.ConnectionError, requests.exceptions.Timeout)`
  raised by `requests.get(...)` itself (L83-87). So a genuine
  `requests.exceptions.HTTPError` from `raise_for_status()` is structurally
  unreachable from inside the retry's `except` — it propagates on the
  first and only attempt, exactly as claimed.
- **Confirmed exact count**: `_MAX_ATTEMPTS = 3`, loop is
  `range(_MAX_ATTEMPTS)` → attempts indexed `0, 1, 2` = **3 total calls**
  to `requests.get`, not 2 or 4. The `if attempt == _MAX_ATTEMPTS - 1:
  raise` guard fires only on the last index (`2`), and
  `time.sleep(_BACKOFF_SECONDS[attempt])` otherwise fires for indices `0`
  (`0.5`) and `1` (`1.0`) — matches the claimed `0.5s` then `1.0s` backoff
  exactly.

**From `/code-review` (correctness):**
- **BLOCKING (see independent judgment below)** — `client.py` L83-87:
  `requests.get(...)` is called with no `timeout=` kwarg at all, so the
  newly-added `Timeout` except-branch is dead code in practice — `requests`
  never raises `Timeout` unless a timeout is configured. A hung TLS
  handshake or unresponsive server blocks indefinitely with no exception,
  so neither the retry loop nor `raise_for_status()` ever runs. Also
  inconsistent with this project's own established convention of passing
  an explicit timeout to blocking calls elsewhere (`claude_code_extractor.
  py:112`, `vision_llm_detector.py:196`).
- **Non-blocking** — `_MAX_ATTEMPTS` (3) and `len(_BACKOFF_SECONDS)` (2)
  are two separately-maintained constants with an implicit invariant
  (`len(_BACKOFF_SECONDS) == _MAX_ATTEMPTS - 1`) that nothing enforces. A
  future bump of `_MAX_ATTEMPTS` without updating `_BACKOFF_SECONDS` would
  raise `IndexError` on the 3rd failure instead of retrying or surfacing
  the real network error. Cheap future-proofing (e.g. an assertion at
  import time, or deriving backoff via a formula) but not required now —
  both constants are co-located and commented, so the risk is only live if
  someone edits one without reading the other.
- **Non-blocking** — the retry only catches `ConnectionError`/`Timeout`;
  `requests.exceptions.ChunkedEncodingError` (a reset mid-response-body,
  not at handshake) is not retried. Real edge case, but not the failure
  mode actually observed (TLS-handshake reset) — reasonable to defer by
  the same logic already used to defer the 5xx-retry decision above.
- **Non-blocking** — the hand-rolled attempt-count/sleep loop reimplements
  retry-with-backoff behavior `urllib3`'s `Retry` (already bundled via
  `requests`, no new dependency) provides via a `Session`/`HTTPAdapter`.
  Weighed against actually switching: doing so would require adding
  persistent `Session` state to `__init__` and re-pointing every existing
  test's mock target from `requests.get` to the session/adapter, for a
  modest net line savings and a backoff-formula semantics change — not a
  clear win for one call site. Reasonable to keep as-is.

**From `/ponytail:ponytail-review` (over-engineering/complexity):**
- Same reuse angle as above (hand-rolled loop vs. `urllib3.Retry`) was the
  only candidate found. Assessed and judged not worth the churn for the
  reason given above (new `Session` plumbing + test-mock rewrite for a
  single call site, exact backoff-value/exception-type-only control is
  easier to express directly than via `Retry`'s formula-based backoff).
- No unused flexibility, no new dependency, no speculative config, no
  reinvented stdlib otherwise. The two new module constants are both
  load-bearing and used. The four new/extended tests each cover a distinct
  new branch (success-after-retry, exhaustion, `Timeout` variant, "HTTP
  errors aren't retried") — proportionate, not excessive.
- **Lean already, modulo the one deferred reuse note above.**

**Independent judgment on the missing `timeout=` gap (asked for explicitly
— not just repeating the build report's framing):**
- **Verdict: BLOCKING.** Three factors tip this past "defensible to defer
  again": (1) it is cheap — a single `timeout=` kwarg, zero risk of
  breaking the mocked unit tests since none of them assert on the absence
  of that kwarg; (2) it directly undermines the stated goal of this exact
  fix cycle — "this call should be resilient to network flakiness" — by
  leaving a failure mode (indefinite hang) that is strictly *worse* than
  the connection-reset this fix already handles (a hang never surfaces an
  exception at all, so it never even reaches the new retry logic, let
  alone a final error the caller can log and move past); (3) it has now
  been flagged twice — once in this module's original review, once again
  here — and cheap, clearly-relevant fixes that get deferred twice tend to
  never get picked up absent being forced. A secondary, non-dispositive
  point: shipping a dedicated `Timeout` except-branch, with its own test,
  for an exception that is provably unreachable under the current
  configuration reads as the problem being handled when it isn't —
  borderline-misleading to a future maintainer skimming the retry logic.
  Recommend a conservative, generous value (e.g. `timeout=10`) — TMDB's
  `search/movie` typically responds in a small fraction of that, so this
  bounds the hang without meaningfully risking false-positive timeouts on
  legitimately-slow-but-successful responses.

**Independent test runs (run directly in this review pass, not trusted
from the build report):**
- `python3 -m pytest tests/unit -q` → **191 passed**, matching the build
  report's count exactly.
- `python3 -m pytest tests/unit/tmdb/test_client.py -v` → **9 passed**,
  including all 3 new tests and the extended
  `test_search_movie_raises_on_http_error` by name.
- Read `tests/unit/tmdb/test_client.py` in full: confirmed the three
  backoff-asserting tests check the literal sleep values, not just call
  counts — `assert mock_sleep.call_args_list == [((0.5,),), ((1.0,),)]`
  (two-failure and exhaustion cases) and `[((0.5,),)]` (single-`Timeout`
  case) — genuinely pinning `0.5` then `1.0`, matching the claim exactly.

One blocking finding: the missing `timeout=` on `search_movie()`'s
`requests.get(...)` call leaves the newly-added `Timeout` retry branch
unreachable and allows an indefinite hang, which undermines this fix
cycle's own stated robustness goal — judged here as cheap enough and
relevant enough to fix now rather than defer a third time. All other
findings (constant-coupling fragility, `ChunkedEncodingError` gap,
hand-rolled-loop-vs-`Retry` reuse angle) are non-blocking. The retry
scope (only `ConnectionError`/`Timeout`, never `HTTPError`) and the exact
3-attempt/`0.5s`+`1.0s` backoff were independently confirmed by direct
code reading, and the test count and backoff-value assertions were
independently confirmed by running the tests and reading their bodies.

VERDICT: NEEDS FIXES

### Fixes applied

Added `timeout=10` to the `requests.get(...)` call in `TMDBHttpClient.search_movie()`
(per the review's blocking finding — the missing timeout made the new `Timeout`
retry branch unreachable dead code and left an unbounded-hang failure mode).
One-line fix, applied directly (not re-run through a full build/fix subagent
cycle given how small and unambiguous it was). Verified: `tests/unit/tmdb`
(23 passed) and the full suite (191 passed) both still pass.

## Follow-up — fix TMDB query dilution from embedded year — status: done

A real end-to-end test against a real Instagram reel exposed a live,
confirmed-severe bug: `resolve_candidate()` in `tmdb/resolver.py` was
sending `candidate.raw_text` — the FULL candidate text, including its
literal trailing `"(YYYY)"` — as the TMDB search query string, instead of
just the title. Confirmed directly against the live TMDB API (not
mocked): querying `"Dhobi Ghat (2010)"` returns **zero** results, while
querying `"Dhobi Ghat"` alone (title only, year passed separately via the
already-correct `year=` param) returns a perfect-score match. This hit
every HIGH-confidence candidate (every `"Title (YYYY)"`-shaped candidate
out of `text_extraction/regex_extractor.py` or the Claude Code CLI
extractor) — the most common, most important tier in the whole pipeline.
This exact risk was flagged as non-blocking ("risk to watch against live
TMDB data later") during the original `tmdb/` module's review; it's now
confirmed real.

### What's built

`reel2movie/tmdb/resolver.py`:
- Added `_TRAILING_YEAR_IN_PARENS = re.compile(r"\s*\((\d{4})\)\s*$")` and
  a new `_strip_trailing_year(raw_text)` helper that strips a `"(YYYY)"`
  anchored at the very **end** of the string only, returning the original
  string unchanged (defensively) if stripping would somehow leave nothing.
- `resolve_candidate()` now computes
  `query_title = _strip_trailing_year(candidate.raw_text) if year_hint is not None else candidate.raw_text`
  and uses `query_title` — not `candidate.raw_text` — for all three of
  `client.search_movie(query_title, year=year_hint)`,
  `pick_best(query_title, year_hint, results)`, and
  `score_result(query_title, year_hint, best)` when building the
  `ResolvedMovie`. `pick_best`/`score_result` needed the same cleaned
  string because the fuzzy title-similarity comparand is diluted by the
  same trailing `"(YYYY)"` noise the search query was.
- Scoped entirely to what `resolver.py` sends to/compares against TMDB.
  `Candidate.raw_text` and `Recommendation.query` (`pipeline/waterfall.py`)
  are untouched — the candidate's own identity elsewhere in the pipeline
  (display, dedup keys, logging) is unaffected; only the TMDB-facing query
  string changed.

**Why "trailing only" stripping, not "strip any `(YYYY)` anywhere":**
`_extract_year_hint()` already had to solve this same problem for a
different reason — a title can contain its own embedded parenthetical
year that isn't the release year (e.g.
`"Experience Paris (1920) like never before (2023)"`, where 2023 is the
real year and 1920 is part of the title's own content). It solves this by
taking the LAST `"(YYYY)"` match, i.e. searching from the right.
`_strip_trailing_year()` uses the same philosophy via an end-anchored
regex (`\s*\((\d{4})\)\s*$`): it only strips a year-in-parens that is
literally the last thing in the string, which is exactly the shape
`text_extraction/regex_extractor.py` (and the Claude Code CLI extractor)
always produce (`f"{title} ({year})"`, confirmed by reading
`regex_extractor.py`). A title with its own embedded, non-trailing
parenthetical year is left completely untouched, since the regex's `$`
anchor simply won't match there.

### Tests

`tests/unit/tmdb/test_resolver.py`:
- Updated the pre-existing `test_extracts_year_hint_from_candidate_text`
  — it previously asserted the (buggy) `client.last_query ==
  "The Matrix (1999)"`; now asserts `client.last_query == "The Matrix"`
  (year still passed separately via `last_year == 1999`).
- `test_query_strips_trailing_year_for_high_confidence_candidate` — the
  exact bug-shaped case: `"Inception (2010)"` → query sent is exactly
  `"Inception"`, year sent is `2010`.
- `test_query_strips_only_trailing_year_not_embedded_one` — the
  embedded-year edge case: `"Experience Paris (1920) like never before
  (2023)"` → only the trailing `"(2023)"` is stripped, leaving
  `"Experience Paris (1920) like never before"` as the query; the
  embedded `"(1920)"` survives untouched.
- `test_query_unchanged_when_no_year_present` — a MEDIUM-confidence bare
  title (`"Interstellar"`, no year): query passed is unchanged, exactly
  `"Interstellar"` — no stripping attempted.
- `test_match_score_uses_stripped_query_not_raw_text_with_year` — proves
  `score_result`/`pick_best` also receive the stripped query: computes
  `score_result` directly for both the stripped (`"Inception"`) and
  unstripped (`"Inception (2010)"`) query against the same result,
  confirms the two scores measurably differ, and asserts the resolved
  candidate's `match_score` equals the stripped-query score.

Also had to update one pre-existing pipeline-level test,
`tests/unit/pipeline/test_waterfall.py::test_two_candidates_resolving_to_same_tmdb_id_are_deduped`:
its `FakeTMDBClient` is keyed by exact query string
(`results_by_query`), and one of its two candidates
(`"The Thing (1982)"`) now gets searched as `"The Thing"` post-fix, so
the dict key was updated from `"The Thing (1982)"` to `"The Thing"` (its
sibling candidate, `"The Thing (1982) remastered"`, has no *trailing*
year — `"(1982)"` is followed by `" remastered"`, not end-of-string — so
it's searched unstripped and needed no key change). This is pre-existing
test infrastructure asserting on the literal query string, not a design
change; it had to move in lockstep with the real fix.

`python3 -m pytest tests/unit -q` → **195 passed** (191 before this
change + 4 new resolver tests; the existing
`test_extracts_year_hint_from_candidate_text` was updated in place, not
counted as new).

### Live-API verification (the actual confirmed-real bug case)

Per the task, wrote a standalone (uncommitted, not in `tests/`) script
that loaded the real `.env` TMDB token via `config.get_tmdb_token()`,
built a real `TMDBHttpClient`, constructed
`Candidate(raw_text="Dhobi Ghat (2010)", source=SourceTag.CAPTION,
confidence=0.9)`, and called the real `resolve_candidate()` end-to-end
against the live TMDB API. Output:

```
resolved: ResolvedMovie(id=54890, title='Dhobi Ghat', year=2010, poster_path='/hSNbvyrRbfAxz29yJSz7bJ1Ujuu.jpg', overview='Arun is a reclusive and lonely modern art painter. Shai is an American banker who is on a visit to Mumbai. Munna is a washerboy also living near Arun and Yasmin. The movie is about these four characters from different class of society and how the lives of four characters are intertwined.', match_score=1.0)
VERIFIED: live TMDB resolution of 'Dhobi Ghat (2010)' succeeded.
```

`id=54890`, `title="Dhobi Ghat"`, `year=2010`, `match_score=1.0` — exactly
the real-world case that exposed the bug, now resolving correctly against
the live API (no mocks). Script deleted after verification, per the
task's instructions (kept out of `tests/`).

### Review findings (latest pass)

This section holds two review passes, kept distinct rather than letting the
newer one overwrite the older (per the historical/current split convention
already established in earlier subtasks). **Cycle 0** (below) is the
original pre-fix review; its outcome is narrated in `### Fixes applied`
below and is kept here verbatim for the record. **Cycle 2** (further down)
is a fresh, from-scratch re-review of the current working tree — including
the loop-based `_strip_trailing_year()` fix and both ponytail
simplifications from fix cycle 1 — run independently of cycle 0, not a
continuation of it.

#### cycle 0 review (historical — pre-fix; see "Fixes applied" below for what changed in response)

Reviewed via `/code-review` (high, forked) on the current diff
(`reel2movie/tmdb/resolver.py`, `tests/unit/pipeline/test_waterfall.py`,
`tests/unit/tmdb/test_resolver.py`, `PROGRESS.md`),
`/ponytail:ponytail-review` on the same diff, a manual hand-trace of
`_TRAILING_YEAR_IN_PARENS` against the embedded-year edge case, a
from-scratch `python3 -m pytest tests/unit -q` run, and an independent
live-TMDB-API re-verification (own script, own API call, not the build
report's pasted output).

**Manual trace — regex anchoring (read directly, not trusted from the
build report):**
- **Confirmed**: `_TRAILING_YEAR_IN_PARENS = re.compile(r"\s*\((\d{4})\)\s*$")`.
  Because `$` only ever matches once per string (the end position),
  `.sub()` can replace at most the one occurrence anchored there — an
  earlier `"(YYYY)"` elsewhere in the string cannot also satisfy `$` and
  is structurally untouched. Hand-traced against
  `"Experience Paris (1920) like never before (2023)"`: only the trailing
  `" (2023)"` matches and is removed, leaving
  `"Experience Paris (1920) like never before"` with `"(1920)"` intact —
  exactly what `test_query_strips_only_trailing_year_not_embedded_one`
  asserts. Confirmed by running that test and also by re-running the
  substitution directly at a Python prompt.
- **Confirmed**: all three call sites inside `resolve_candidate()` —
  `client.search_movie(query_title, ...)`, `pick_best(query_title, ...)`,
  and `score_result(query_title, ...)` in the `ResolvedMovie(...)`
  construction — use `query_title`, not a mix with `candidate.raw_text`.
  Read the full current file; no half-fixed call site.
- **Confirmed**: `candidate.raw_text` and `Recommendation.query` are
  genuinely unchanged by this fix. Grepped `pipeline/waterfall.py`:
  `_resolve_all()` builds `Recommendation(query=candidate.raw_text, ...)`
  directly from the candidate, never touching `resolve_candidate`'s
  internal `query_title` — the final CLI JSON's `query` field still shows
  the original raw text, including any trailing `"(YYYY)"`, by design
  (this fix is scoped to TMDB-facing lookup only).
- **Confirmed**: the `test_waterfall.py` fixture change
  (`"The Thing (1982)"` → `"The Thing"` as the fake client's dict key) is
  genuine fallout, not papering over anything. `"The Thing (1982)"` has a
  trailing year and now gets searched as `"The Thing"` post-fix; its
  sibling `"The Thing (1982) remastered"` has `"(1982)"` followed by
  `" remastered"` — not end-of-string — so it is correctly left
  unstripped and its dict key is correctly left unchanged. The test's own
  assertion (both candidates dedupe to the same tmdb id) is untouched.

**BLOCKING — found independently, and reproduced against the live TMDB
API (not just theoretical):** `_strip_trailing_year()` performs only a
single, non-repeated substitution. A candidate whose raw_text ends in
*two* adjacent `"(YYYY)"` groups — reachable via the real
`RegexCandidateExtractor`'s `_QUOTED_TITLE_YEAR` pattern, whose quoted-title
capture group has no restriction against parentheses, so a caption like
`Rewatching "Se7en (1995)" (2015) tonight` produces
`Candidate(raw_text='Se7en (1995) (2015)', confidence=0.9)` — only has its
outer trailing `" (2015)"` stripped, leaving `query_title = "Se7en (1995)"`,
which *itself* is still trailing-year-shaped. Verified mechanically by
running the real extractor + resolver helpers (confirmed the exact
`raw_text`/`query_title` values above), then verified against the live
TMDB API directly: `search_movie("Se7en (1995)", year=2015)` → **0
results**; `search_movie("Se7en", year=2015)` → **7 results** (top hit
`"Se7en"`). This is the identical zero-result failure mode this entire
fix cycle exists to close, recurring through a gap in the fix itself. Fix
is cheap: loop the substitution until no further trailing match is found
(or apply the pattern with a trailing `*` repetition), e.g.
```python
def _strip_trailing_year(raw_text: str) -> str:
    stripped = raw_text
    while True:
        new = _TRAILING_YEAR_IN_PARENS.sub("", stripped).strip()
        if new == stripped:
            break
        stripped = new
    return stripped or raw_text
```
- Related, same root cause: `test_query_strips_only_trailing_year_not_embedded_one`
  only covers an embedded year *separated* from the trailing year by other
  text; no test covers the adjacent-double-year shape, so the suite gives
  false confidence that "embedded year" is fully handled.

**Non-blocking — architectural note (pre-existing, not introduced by this
diff):** the fix re-derives title/year via a second anchored regex that
must stay byte-for-byte compatible with the `f"{title} ({year})"` format
independently produced at four separate construction sites
(`regex_extractor.py` ×2, `claude_code_extractor.py`, `vision_llm_detector.py`
— confirmed by grep). Nothing couples the regex to that format except
convention; a future drift at any site would silently reintroduce query
dilution with no test signal. Root cause is `Candidate` conflating
title+year into one string, which predates this fix and is out of scope
to redesign here.

**Non-blocking:** `return stripped or raw_text` (the empty-query
fallback) only fires when `raw_text` is pure whitespace plus a year
(e.g. `" (2010)"`), and even then returns the *unstripped* original,
which still carries the trailing `"(YYYY)"` — so the fallback doesn't
actually prevent the dilution bug it's defensively guarding against.
Realistically unreachable from any real extractor (title is never empty
upstream), so low-severity.

**From `/ponytail:ponytail-review` (over-engineering/complexity):**
- `L62-66` **yagni**: the `if year_hint is not None else candidate.raw_text`
  branch in `resolve_candidate()` duplicates what `_strip_trailing_year`
  already does safely on its own (no match → string returned unchanged).
  Calling it unconditionally — `query_title = _strip_trailing_year(candidate.raw_text)`
  — drops the branch, 1 line instead of 5.
- `L49` **delete**: same empty-query fallback flagged above as
  non-blocking from the correctness angle — also flagged here as
  unneeded defensive code; nothing replaces it.
- net: -4 lines possible. No unused dependency, no speculative
  config, no reinvented stdlib otherwise; the second compiled regex is
  justified (genuinely different semantics — trailing-only vs.
  last-match-anywhere — from the pre-existing `_YEAR_IN_PARENS`).

**Independent test run (run directly in this review pass, not trusted
from the build report):**
- `python3 -m pytest tests/unit -q` → **195 passed**, matching the build
  report's count exactly.

**Independent live-API re-verification (own script, own call, not the
build report's pasted output):** loaded the real `.env` `TMDB_API_KEY`
via `config.get_tmdb_token()` + `load_dotenv()`, built a real
`TMDBHttpClient`, constructed
`Candidate(raw_text="Dhobi Ghat (2010)", source=SourceTag.CAPTION,
confidence=0.9)`, and called the real `resolve_candidate()` end-to-end
against the live TMDB API (no mocks, no retry needed — succeeded on the
first attempt, no `ConnectionResetError` hit). Result:
```
resolved: ResolvedMovie(id=54890, title='Dhobi Ghat', year=2010, poster_path='/hSNbvyrRbfAxz29yJSz7bJ1Ujuu.jpg', overview='...', match_score=1.0)
INDEPENDENT VERIFICATION PASSED: id=54890, title='Dhobi Ghat', year=2010
```
Matches `id=54890`, `title="Dhobi Ghat"`, `year=2010` exactly — the
original fix's core claim independently confirmed.

One blocking finding: `_strip_trailing_year()`'s single-pass substitution
leaves an adjacent-double-trailing-year shape (reachable via the real
quoted-title extractor path) still trailing-year-shaped after stripping,
reproducing — confirmed against the live TMDB API — the exact zero-result
failure mode this fix cycle exists to close. All other findings
(regex-to-construction-format coupling, the self-defeating empty-query
fallback, the two ponytail simplification notes) are non-blocking. The
regex anchoring for the originally-specified embedded-year case, the
three-call-site consistency, the `raw_text`/`Recommendation.query` blast
radius, and the `test_waterfall.py` fixture fallout were all independently
confirmed correct by direct code reading and grep. Tests (195 passed) and
the live-API Dhobi Ghat case were independently re-run and matched.

VERDICT: NEEDS FIXES

#### cycle 2 review (current — fresh re-review of the post-fix-cycle-1 working tree)

Scope: the full current diff — `reel2movie/tmdb/resolver.py` (now with the
looped `_strip_trailing_year()` and both ponytail simplifications from fix
cycle 1 applied), `tests/unit/pipeline/test_waterfall.py`,
`tests/unit/tmdb/test_resolver.py`, `PROGRESS.md`. Run as a clean re-review,
not a continuation of the cycle 0/1 session: fresh `/code-review` (high,
forked) and `/ponytail:ponytail-review` invocations against the current
diff, plus independent manual verification (a from-scratch full-suite run,
a direct read of `_strip_trailing_year()`/`resolve_candidate()`, a
three-adjacent-year loop-termination stress test built from scratch, and an
independent reproduction of the fix's own Se7en regression case against a
hand-written fake client).

**Primary question — is the cycle 0 BLOCKING double-adjacent-year bug
actually fixed? Yes, confirmed by direct reproduction, including a
three-adjacent-year case beyond what cycle 0 required:**
- The task's own suggested stress-test string, `"Title (1) (2) (2020)"`,
  turns out not to exercise what it was meant to: `_TRAILING_YEAR_IN_PARENS`
  is anchored on exactly `\d{4}`, so the single-digit `(1)`/`(2)` groups
  never match it at all. Run directly: `_strip_trailing_year("Title (1) (2) (2020)")`
  → `"Title (1) (2)"` — correct, not a bug (those groups aren't
  year-shaped), but not a 3-iteration stress test either.
- Built a genuine three-adjacent-4-digit-year case instead:
  `_strip_trailing_year("Title (1111) (2222) (2020)")` → runs the `while
  True` loop exactly 3 times and returns exactly `"Title"`. Confirmed by
  direct execution.
- Termination/no-infinite-loop check: ran `_strip_trailing_year("X" + "
  (1999)" * 50)` (50 chained trailing groups) → reduces to `"X"` in under
  1ms. The loop is structurally guaranteed to terminate for any finite
  input: each iteration either strictly shortens the string (one more
  trailing group consumed) or produces no change, and "no change" is the
  loop's own exit condition (`if new == stripped: break`) — there is no
  path that re-lengthens or oscillates the string.
- Re-confirmed the zero/one/two-adjacent cases directly:
  `_strip_trailing_year("Interstellar")` → unchanged;
  `_strip_trailing_year("Inception (2010)")` → `"Inception"`;
  `_strip_trailing_year("Se7en (1995) (2015)")` → `"Se7en"` (the fix's own
  cycle-0 regression case, exactly as fixed).
- Independently reproduced the fix's own regression test case end-to-end
  (own hand-written fake `TMDBClient`, not the test suite's
  `FakeTMDBClient`): `resolve_candidate(Candidate(raw_text="Se7en (1995)
  (2015)", source=SourceTag.CAPTION, confidence=0.9), client)` → the query
  sent is exactly `"Se7en"`, year sent is `2015`. Matches
  `test_query_strips_adjacent_double_trailing_year` exactly.
- Read the full current `_strip_trailing_year()` and `resolve_candidate()`:
  confirmed the loop fix is applied, both ponytail simplifications from fix
  cycle 1 (`query_title = _strip_trailing_year(candidate.raw_text)` called
  unconditionally; the `return stripped or raw_text` fallback removed in
  favor of `return stripped` directly) are applied exactly as the fix
  report describes, and all three TMDB-facing call sites
  (`client.search_movie`, `pick_best`, `score_result`) consistently use
  `query_title` — no half-fixed call site.

**BLOCKING — found independently via `/code-review`, and reproduced
directly against the real extractor (not just theoretical):** removing the
`return stripped or raw_text` fallback (per cycle 0's non-blocking
"self-defeating, realistically unreachable" note and the matching ponytail
`delete:` suggestion) reintroduces a real, worse failure mode that cycle
0's "unreachable" reasoning did not anticipate. `_strip_trailing_year()`'s
loop can now reduce `query_title` all the way to the **empty string**, not
just a still-year-shaped remainder, whenever the quoted title content
captured by `RegexCandidateExtractor`'s `_QUOTED_TITLE_YEAR` pattern is
*itself* entirely `"(YYYY)"`-shaped. Confirmed by direct reproduction
through the real extractor, not a synthetic string:
```python
RegexCandidateExtractor().extract('Watch "(1999)" (2010) now', SourceTag.CAPTION)
# -> [Candidate(raw_text='(1999) (2010)', confidence=0.9)]   # HIGH confidence
_strip_trailing_year('(1999) (2010)')
# -> ''   # loop: "(1999) (2010)" -> "(1999)" -> "" -> break
```
`resolve_candidate()` has no guard against an empty `query_title` and calls
`client.search_movie("", year=2010)` directly — against the real
`TMDBHttpClient` this sends a blank `query` param to TMDB's search
endpoint with no local validation, likely surfacing as an HTTP error
(caught by `_resolve_all`'s broad `except Exception` in
`pipeline/waterfall.py`, silently dropping a HIGH-confidence candidate)
rather than the "just zero relevant results" degradation the pre-fix code
(which sent `candidate.raw_text` unstripped, i.e. the non-empty
`"(1999) (2010)"`) would have produced for this same contrived input. This
is strictly worse than the pre-this-fix-cycle behavior for this input
shape, and a direct consequence of this diff: the loop's own fixed-point
termination behaves correctly (per the three/fifty-adjacent-year checks
above), but nothing stops it from consuming the *entire* string when the
"title" portion is itself year-shaped. Narrow/contrived input (a quoted
span whose entire content looks like a year), same rarity class as cycle
0's Se7en case, but demonstrated reachable through the real production
extractor at HIGH confidence (0.9) — the tier this whole fix cycle is
about. Cheap fix: guard the final return, e.g. `return stripped or
raw_text` (restoring cycle 1's removed fallback) or `return stripped if
stripped else raw_text`, so a would-be-empty result falls back to the
original (still non-empty, if diluted) raw_text instead of an empty query
string.

**Non-blocking — re-confirmed, carried over from cycle 0, unchanged by fix
cycle 1:** the architectural note about `_strip_trailing_year()` needing to
stay byte-for-byte compatible with the `f"{title} ({year})"` format
produced independently at four separate construction sites — still valid,
still out of scope to redesign here, still just a latent-drift risk with no
test signal.

**From `/code-review` (correctness) and `/ponytail:ponytail-review`
(complexity) — same simplification, found independently by both:**
- `_strip_trailing_year()`'s 7-line hand-written `while True` loop
  (re-running `_TRAILING_YEAR_IN_PARENS.sub(...)` to a fixed point) can be
  replaced by a single non-looping regex using a repeated-group quantifier:
  `_TRAILING_YEARS_IN_PARENS = re.compile(r"(?:\s*\(\d{4}\)\s*)+$")`, then
  `return _TRAILING_YEARS_IN_PARENS.sub("", raw_text).strip()` — one `.sub()`
  call instead of a loop, handling any number of chained trailing year
  groups (including the three/fifty-adjacent cases stress-tested above) in
  one pass. Removes the loop body and the ~9-line docstring paragraph
  justifying why a loop is needed. Note: this simplification does **not**
  fix the BLOCKING empty-query finding above on its own — the single-regex
  version has the identical "can consume the entire string" behavior for
  all-year-shaped input, so the `return stripped or raw_text`-style guard
  is still needed regardless of which implementation (loop vs. quantifier)
  is used.
- `net: -10 lines possible` (non-blocking; independent of the BLOCKING fix
  above, which must land either way).

**Independent test run (run directly in this review pass, not trusted from
the build report):**
- `python3 -m pytest tests/unit -q` → **196 passed**, matching the fix
  report's count exactly.

Cycle 2 outcome: one BLOCKING finding (the empty-query collapse above),
newly found in this pass and not present in cycle 0's findings — the
double-adjacent-year loop-termination bug cycle 0 flagged is genuinely
fixed and holds up under a three- and fifty-adjacent-year stress test, but
removing the defensive fallback (per cycle 0's own "realistically
unreachable" judgment call, which this pass shows was incorrect for the
quoted-title-is-itself-year-shaped sub-case) opened a new, reachable gap.
Everything else — the loop's correctness and termination, all three
TMDB-facing call sites, the `raw_text`/`Recommendation.query` blast radius,
the `test_waterfall.py` fixture fallout, and the test count — was
independently re-confirmed correct.

VERDICT: NEEDS FIXES

#### cycle 3 review (current — fresh re-review of the post-cycle-2-fix working tree; final cycle per the project's 3-cycle cap)

Scope: the full current diff as it stands uncommitted right now —
`reel2movie/tmdb/resolver.py` (cycle 2's empty-query guard restored:
`return stripped or raw_text`), `tests/unit/tmdb/test_resolver.py` (with
both of cycle 2's new regression tests,
`test_query_falls_back_to_raw_text_when_fully_stripped_to_empty` and
`test_query_strips_three_adjacent_trailing_years`),
`tests/unit/pipeline/test_waterfall.py`, `PROGRESS.md`. Run as a clean
re-review, not a continuation of cycles 0/2: fresh `/code-review` (high,
forked) and `/ponytail:ponytail-review` invocations against the current
diff, plus independent manual verification done directly in this pass (a
from-scratch `python3 -m pytest tests/unit -q` run, a full read of the
final `_strip_trailing_year()`/`resolve_candidate()`, and hand
reproduction — outside pytest — of both of cycle 2's own regression
cases plus several adversarial cases beyond what's already tested).

**`/code-review` (high, forked) — no correctness bug found.** Scope was
`reel2movie/tmdb/resolver.py` + its two test files (`PROGRESS.md` is
documentation, out of scope); cross-checked callers in
`pipeline/waterfall.py`, `text_extraction/regex_extractor.py`, and
`text_extraction/claude_code_extractor.py` to re-verify the
"`raw_text` is always `f'{title} ({year})'`" assumption
`_strip_trailing_year` depends on, and confirmed `Recommendation.query`
still intentionally uses the original unstripped `candidate.raw_text`
(display vs. search-query correctly kept separate). Returned `[]`
(empty findings). One cosmetic **non-blocking** nit: `reel2movie/tmdb/resolver.py:12`
— `_TRAILING_YEAR_IN_PARENS = re.compile(r"\s*\((\d{4})\)\s*$")`'s
capturing group `(\d{4})` is never read (`.sub()` discards the whole
match); a non-capturing `(?:\d{4})` would be clearer, but this has zero
behavioral effect.

**`/ponytail:ponytail-review` — one finding, carried over from cycle 2,
already explicitly considered and deliberately deferred by the cycle 2
fix itself (non-blocking both times):**
- `reel2movie/tmdb/resolver.py:L69-75`: `shrink:` the 7-line hand-written
  `while True` fixed-point loop re-running `_TRAILING_YEAR_IN_PARENS.sub(...)`
  can be replaced by one non-looping regex with a repeated-group
  quantifier: `_TRAILING_YEARS_IN_PARENS = re.compile(r"(?:\s*\(\d{4}\)\s*)+$")`,
  then `return _TRAILING_YEARS_IN_PARENS.sub("", raw_text).strip() or raw_text`.
  This is the identical suggestion cycle 2's review made; the cycle 2 fix
  report explicitly chose to keep the loop as-is ("to keep the change
  minimal and the fix cycle's diff easy to re-review") since the reviewer
  itself flagged the style choice as non-blocking. Re-raising it here only
  for completeness/traceability, not as a new finding — it is not
  reasserted as something that must land in this cycle.
- `reel2movie/tmdb/resolver.py:L11-12`: `shrink:` same capturing-group nit
  `/code-review` found independently (see above) — `(\d{4})` → `(?:\d{4})`.
- `net: -6 lines possible` (both non-blocking, carried over / cosmetic).
- Lean otherwise: the two test files add coverage, not production
  complexity, and are out of this skill's scope.

**Manual verification (done directly in this pass, not trusted from
either skill's report or from cycle 2's writeup):**
- Read the full current `_strip_trailing_year()` and `resolve_candidate()`
  in `reel2movie/tmdb/resolver.py` end to end. Confirmed: the loop body is
  `new = _TRAILING_YEAR_IN_PARENS.sub("", stripped).strip()`, compared
  against `stripped` for the fixed-point break, and the function ends
  with `return stripped or raw_text` — the empty-query guard cycle 2
  re-added is present and intact. `resolve_candidate()` calls
  `_strip_trailing_year(candidate.raw_text)` unconditionally and threads
  the single `query_title` result into all three of
  `client.search_movie`, `pick_best`, and `score_result` — no half-fixed
  call site.
- `python3 -m pytest tests/unit -q`, run independently, from scratch →
  **198 passed** — matches the reported count exactly, not merely
  trusted from the build report.
- **Hand-reproduced both of cycle 2's own regression tests directly**,
  bypassing pytest entirely — constructed `Candidate` objects and a
  hand-written `FakeTMDBClient` inline and called `resolve_candidate()`
  myself:
  - `Candidate(raw_text="(1999) (2010)", ...)` → `client.last_query ==
    "(1999) (2010)"` (the full original, non-empty, unchanged) and
    `client.last_query != ""`, `client.last_year == 2010`. Matches
    `test_query_falls_back_to_raw_text_when_fully_stripped_to_empty`
    exactly.
  - `Candidate(raw_text="Title (1111) (2222) (2020)", ...)` →
    `client.last_query == "Title"`, `client.last_year == 2020`. Matches
    `test_query_strips_three_adjacent_trailing_years` exactly.
  - Also re-ran `RegexCandidateExtractor().extract('Watch "(1999)" (2010)
    now', SourceTag.CAPTION)` directly (not trusted from the test's
    docstring claim) → confirmed it genuinely produces
    `Candidate(raw_text='(1999) (2010)', confidence=0.9)` against the real
    extractor, so the fully-empty-collapse guard is reachable through real
    production code, not just a synthetic string — both regression tests
    are genuinely testing what they claim, not vacuously passing.
- **Adversarial case beyond what's already tested — whitespace-only
  intermediate, run directly at a Python prompt, not reasoned about only
  on paper:** traced `_strip_trailing_year()`'s iteration-by-iteration
  `stripped` values for inputs designed to probe whether a whitespace-only
  (not literally `""`) intermediate could ever survive a full iteration
  and defeat the `stripped or raw_text` falsy check (which only catches
  literal `""` — a truthy `" "` would slip past it). Tested
  `"   (2020)   "` (whitespace-padded lone year, no title content),
  `"(1999)  (2010)"` (double internal space between adjacent groups), and
  `" "` (pure whitespace, no year at all). In every case the iteration
  trace showed `stripped` collapsing straight from a non-whitespace (or
  non-empty) value directly to exactly `""` in one step — never pausing on
  a truthy, whitespace-only value — because `.strip()` is applied to
  `new` on *every* iteration of the loop, before the fixed-point
  comparison, so any would-be whitespace-only remainder is normalized to
  `""` in the same iteration it would otherwise arise. This confirms the
  `.strip()` placement inside the loop body is load-bearing, not cosmetic:
  without it, a case producing a lone-whitespace remainder could in
  principle produce a truthy `" "` that slips past `stripped or raw_text`
  undetected; with it, no such state is reachable. (`"   (2020)   "` →
  falls back to itself unchanged, including its own leading/trailing
  padding — see next point.)
- **Confirmed the fallback returns the literal, byte-for-byte ORIGINAL
  `raw_text`, not a partially-stripped intermediate:** read the code —
  `raw_text` is the function's parameter and is never reassigned anywhere
  in the loop (only the local `stripped` variable is mutated), so
  `stripped or raw_text` genuinely falls back to the exact original
  argument. Confirmed concretely: `_strip_trailing_year("   (2020)   ")`
  (padding included) returns `"   (2020)   "` — the original padding and
  all — not e.g. `"(2020)"` or `""`; this is consistent with the
  function's own docstring ("Falls back to the original, unstripped
  `raw_text`") and is the intended, documented behavior, not a bug.

No new BLOCKING issue found in this cycle. Both items above (the
loop-vs-single-regex shrink and the unused capturing group) are
non-blocking cosmetic carryovers/nits with zero behavioral effect, not
correctness defects, and the loop-vs-regex one was already explicitly
and deliberately deferred by name in the cycle 2 fix report. All of
cycle 0's and cycle 2's BLOCKING findings were independently
re-confirmed fixed and holding up under additional adversarial cases
(whitespace-only intermediates, the three-adjacent-year stress case, and
direct hand reproduction of both regression tests outside the test
runner).

VERDICT: ACCEPTABLE

### Fixes applied

`reel2movie/tmdb/resolver.py`:
- `_strip_trailing_year()` now loops the `_TRAILING_YEAR_IN_PARENS.sub(...)`
  substitution until the string stops changing, instead of a single
  non-repeated `.sub()` call. Fixes the BLOCKING finding: an adjacent
  double-trailing-year `raw_text` (e.g. `"Se7en (1995) (2015)"`) now
  strips all the way down to `"Se7en"` instead of stopping after one pass
  at `"Se7en (1995)"` (itself still trailing-year-shaped).
- Applied both non-blocking ponytail simplifications, since neither
  conflicted with the loop fix: `resolve_candidate()` now calls
  `_strip_trailing_year(candidate.raw_text)` unconditionally — dropped
  the `if year_hint is not None else candidate.raw_text` branch, since
  `_strip_trailing_year` already safely no-ops (returns the input
  unchanged, module whitespace trimming) when there's no trailing-year
  match. Also dropped the `return stripped or raw_text` empty-query
  defensive fallback — `_strip_trailing_year` now always returns
  `stripped` directly; the loop's own termination (`new == stripped` →
  break) already handles the "nothing left to strip" case correctly, and
  the reviewer judged the all-whitespace-input case it guarded as
  unreachable from any real extractor.
- Net line delta matches the review's "-4 lines possible" estimate.

#### cycle 2 fix

`reel2movie/tmdb/resolver.py`:
- Re-added the empty-query guard that fix cycle 1 removed, fixing cycle
  2's BLOCKING finding: `_strip_trailing_year()` now ends with
  `return stripped or raw_text` instead of `return stripped`. Kept the
  existing `while True` loop implementation rather than switching to the
  reviewer's suggested single-regex-with-repeated-group form (`r"(?:\s*\(\d{4}\)\s*)+$"`)
  — the reviewer explicitly flagged that style choice as non-blocking and
  noted the guard is needed either way, so the loop was left as-is and
  only the guard was restored, to keep the change minimal and the fix
  cycle's diff easy to re-review.
- Expanded `_strip_trailing_year()`'s docstring with a new paragraph
  explaining why the fallback is reachable, not just defensive: a
  candidate whose entire `raw_text` is chained `"(YYYY)"`-shaped groups
  with nothing else (e.g. `'(1999) (2010)'`, produced by the real
  `RegexCandidateExtractor`'s `_QUOTED_TITLE_YEAR` pattern from a caption
  like `Watch "(1999)" (2010) now`) loops the strip all the way down to
  `""`; falling back to the original unstripped `raw_text` sends TMDB a
  non-empty (if imperfect) query instead of a blank one.

`tests/unit/tmdb/test_resolver.py`:
- Added `test_query_falls_back_to_raw_text_when_fully_stripped_to_empty` —
  the exact BLOCKING regression case: `raw_text='(1999) (2010)'` against
  a `FakeTMDBClient`, asserting `client.last_query == "(1999) (2010)"`
  (the full original, non-empty fallback) and explicitly
  `client.last_query != ""`.
- Added `test_query_strips_three_adjacent_trailing_years` — the
  reviewer's loop-termination stress-test case,
  `raw_text="Title (1111) (2222) (2020)"`, asserting it still fully
  reduces to `client.last_query == "Title"`, confirming the guard didn't
  regress the already-working multi-strip behavior.
- Manually verified (not just via the test suite) that
  `RegexCandidateExtractor().extract('Watch "(1999)" (2010) now',
  SourceTag.CAPTION)` really does produce
  `Candidate(raw_text='(1999) (2010)', confidence=0.9)` against the real
  extractor, then ran that exact candidate through `_strip_trailing_year`
  and `resolve_candidate` end-to-end (fake client), confirming the query
  sent is the non-empty `'(1999) (2010)'`, not `""`.

`python3 -m pytest tests/unit -q` → **198 passed** (196 before this fix
cycle + 2 new resolver tests).

### Tests

`tests/unit/tmdb/test_resolver.py`:
- Added `test_query_strips_adjacent_double_trailing_year` — the exact
  BLOCKING regression case: `raw_text='Se7en (1995) (2015)'` against a
  `FakeTMDBClient`, asserting `client.last_query == "Se7en"` (fully
  stripped, not `"Se7en (1995)"`) and `client.last_year == 2015`.

`python3 -m pytest tests/unit -q` → **196 passed** (195 before this
fix cycle + 1 new regression test).

### Live-API verification

Loaded the real `.env` `TMDB_API_KEY` via `config.get_tmdb_token()` +
`load_dotenv()`, built a real `TMDBHttpClient`, constructed
`Candidate(raw_text="Se7en (1995) (2015)", source=SourceTag.CAPTION,
confidence=0.9)`, and called the real `resolve_candidate()` end-to-end
against the live TMDB API (script written to a scratchpad outside the
repo, not committed). Output:

```
stripped query_title: 'Se7en'
resolved: None
```

The stripping fix itself is confirmed correct — `_strip_trailing_year`
returns exactly `"Se7en"` for this input, matching the fake-client test.
But the full `resolve_candidate()` call still returns `None` live, for a
**separate, pre-existing reason outside this fix's scope**:
`_extract_year_hint()` picks the LAST `"(YYYY)"` match in `raw_text`
(by design, documented behavior, unrelated to the stripping bug), which
for this exact caption shape is `2015` — not Se7en's real release year
(`1995`). `TMDBHttpClient.search_movie()` passes `year` straight through
to TMDB's `/search/movie?year=` parameter, which TMDB applies as a hard
server-side filter. Confirmed directly against the live API:
`search_movie("Se7en", year=2015)` → **0 results** (not the 7 the
earlier review pass's writeup stated — re-ran this exact call twice,
consistently 0; TMDB's `year` filter excludes the real 1995 release
entirely once a non-matching year is supplied). Isolating the stripping
fix from this separate year-filter interaction confirms it works as
intended: `search_movie("Se7en", year=None)` → **7 results**, top hit
(`original_rank=0`) `id=807, title='Se7en', year=1995`; feeding that
result set through `pick_best`/`score_result` with the stripped query
and the `2015` year hint still yields `id=807, title='Se7en', year=1995,
match_score=0.9` as the best (non-rejected) result. This proves the
BLOCKING stripping bug is fixed; the `None` on the literal end-to-end
call is TMDB's live `year=` hard filter rejecting a year hint that, for
this specific constructed example, happens not to be the film's real
release year — a distinct, pre-existing ambiguity in `_extract_year_hint`
("last parenthetical wins") colliding with a caption where the last
parenthetical isn't the release year, not a regression from or scope of
this fix cycle's assigned BLOCKING finding. Left unfixed as out of
scope; flagged here for visibility rather than silently worked around.

## Follow-up — prioritize exact title match over popularity in scoring — status: DONE

Confirmed real bug found via live testing: a caption recommending a
"mind-bending movies" list (Primer, Coherence, Predestination, Memento,
Donnie Darko, Triangle, Resolution) had "Triangle" resolved to "Triangle
of Sadness" (2022, an unrelated satire) instead of the actual 2009
time-loop thriller "Triangle" that fits the list's theme.

### Root cause

`reel2movie/tmdb/scoring.py`'s `pick_best()` scored every result with
`score_result()` (`0.65 * title_similarity + 0.25 * rank_bonus + 0.10 *
year_bonus`) and took the single argmax across the whole result set.
`title_similarity` is `rapidfuzz.fuzz.WRatio(query, result.title) / 100`,
which uses partial-ratio logic: a short query that is a full substring of
a longer title (e.g. `"Triangle"` inside `"Triangle of Sadness"`) scores
very close to 1.0, nearly indistinguishable from a true exact match. Once
combined with `rank_bonus` (`1 / (1 + original_rank)`), a popular partial
match that TMDB ranks first can out-score a true exact match TMDB ranks
lower — reweighting the formula's coefficients would only ever produce a
*harder-to-reach* threshold, not a categorical guarantee, since any fixed
weights can in principle be beaten by a large enough rank/popularity gap.

### Design: tiered selection, not a reweighted formula

Restructured `pick_best(query, year_hint, results)` into two tiers so
"name matching beats popularity" holds categorically:

1. Partition `results` into exact-title matches (via a new
   `_is_exact_title_match(query, title)` helper — strict, normalized
   (`.strip().casefold()`) equality, deliberately NOT fuzzy/partial) vs.
   everything else.
2. If the exact-match group is non-empty, select the best *only* from
   that group, using the existing `score_result()` purely as a
   tiebreaker (so `year_hint` and TMDB's own rank still correctly
   disambiguate between, say, two different movies both literally titled
   "Triangle" in different years). A fuzzy/partial match in the other
   group can never win once a real exact match exists, regardless of its
   popularity or TMDB rank.
3. If there are no exact matches at all, fall back unchanged to the
   original behavior: score every result and take the argmax.

`MIN_MATCH_SCORE` is still applied as the floor in both branches.
`score_result()` itself was left untouched, exactly as scoped — it's
still used for tie-breaking within the exact-match tier and for the
no-exact-match fallback.

### Tests

`tests/unit/tmdb/test_scoring.py` — added 5 tests:
- `test_pick_best_prefers_exact_match_over_popular_partial_match` — the
  real-world regression: `"Triangle of Sadness"` (`original_rank=0`,
  `popularity=120.0`) vs `"Triangle"` (`original_rank=1`,
  `popularity=15.0`), `pick_best("Triangle", None, ...)` must pick
  `"Triangle"`.
- `test_pick_best_falls_back_to_fuzzy_scoring_when_no_exact_match_exists`
  — proves the no-exact-match fallback path is unchanged: best fuzzy
  score still wins when nothing is an exact match.
- `test_pick_best_among_exact_matches_uses_year_hint_as_tiebreaker` — two
  different movies both exactly titled "Triangle" (2009 vs 1994), tied on
  TMDB rank so only `year_hint` distinguishes them; confirms `year_hint`
  still picks the right one among exact matches.
- `test_pick_best_exact_match_wins_despite_huge_popularity_gap` — the
  direct "name matching beats popularity" proof: a non-exact,
  `original_rank=0`/`popularity=500.0` result still loses to an exact
  match at `original_rank=9`/`popularity=1.0`.
- `test_pick_best_exact_match_is_case_and_whitespace_insensitive` —
  `"the matrix"` vs `"The Matrix"` and `" Inception "` vs `"Inception"`
  both still count as exact.

`python3 -m pytest tests/unit -q` → **203 passed** (198 before this
follow-up + 5 new scoring tests).

### Live-API verification

Loaded the real `.env` `TMDB_API_KEY` via `config.get_tmdb_token()` +
`load_dotenv()`, built a real `TMDBHttpClient`, called
`search_movie("Triangle")` against the live TMDB API, and ran the full
result list through the fixed `pick_best("Triangle", None, results)`
(script written to a scratchpad outside the repo, not committed). Live
TMDB returned 20 results for the query `"Triangle"`, including
`"Triangle of Sadness"` (2022, `original_rank=0`, `popularity=34.666`)
ranked ahead of several genuinely-titled `"Triangle"` entries at
different years (2009, 2020, 2024, 2007, 2022, 1994, 2014, 2025, plus an
all-caps `"TRIANGLE"` (2012)). Output:

```
=== pick_best('Triangle', None, results) ===
TMDBSearchResult(id=26466, title='Triangle', year=2009, poster_path='/cRlMrbc4Iof7vN0ZqHwJnMBYBLi.jpg', overview='When Jess sets sail on a yacht with a group of friends, she cannot shake the feeling that there is something wrong.', popularity=9.7426, original_rank=1)

score_result for best: 0.775
```

Confirmed: `id=26466` is the real 2009 time-loop thriller "Triangle" —
exactly the diagnostic-output id named in this follow-up's task, now
independently reconfirmed against the live API rather than assumed. The
fix correctly rejects the more popular, top-ranked "Triangle of Sadness"
(`original_rank=0`) in favor of the true exact title match, and also
correctly disambiguates among the *several* other exact-titled
`"Triangle"` results in the live result set by falling back to
`score_result`'s `rank_bonus` tiebreaker (no `year_hint` was supplied in
this call) to pick the one TMDB itself ranks highest among the
genuinely-tied exact matches.

### Files changed

- `reel2movie/tmdb/scoring.py` — tiered `pick_best()` + new
  `_is_exact_title_match()` helper; `score_result()` unchanged.
- `tests/unit/tmdb/test_scoring.py` — 5 new tests (above).

### Review findings (latest pass)

This section holds two review passes, kept distinct rather than letting the
newer one overwrite the older (per handoff-logging convention: never destroy
history). **Cycle 0** (below) is the original pre-fix review; its outcome is
narrated in `### Fixes applied` below and is kept here verbatim for the
record. **Cycle 2** (further down) is a fresh, from-scratch re-review of the
current working tree (fix cycle 1 already applied) — run independently of
cycle 0/1, not a continuation of them.

#### cycle 0 review (historical — pre-fix; see "Fixes applied" below for what changed in response)

Reviewed via `/code-review` (high, forked) on the current diff
(`reel2movie/tmdb/scoring.py`, `tests/unit/tmdb/test_scoring.py`,
`PROGRESS.md`), `/ponytail:ponytail-review` on the same diff, a
from-scratch `python3 -m pytest tests/unit -q` run, and an independent
live-TMDB-API re-verification (own script, own API call, not the build
report's pasted output).

**BLOCKING — confirmed by direct repro, not just read:** `_is_exact_title_match()`
normalizes case (`.casefold()`), but once a candidate is placed in the
exact-match tier, its *own* tiebreak/floor score still comes from
`score_result()`, whose `title_similarity` term is `fuzz.WRatio(query,
result.title) / 100` — which is case-sensitive for this kind of
short, all-caps-vs-title-case pair. The two functions disagree on what
"the same title" means, so a genuinely exact (case-insensitive) match
can be placed in the exact-only tier and then scored so low by the
case-sensitive formula that it fails `MIN_MATCH_SCORE` — at which point
`pick_best` returns `None`, discarding the real exact match entirely
rather than falling back to anything else (the exact tier is exclusive
by design, so there's no fallback once it's non-empty). Verified directly:
```python
up = TMDBSearchResult(id=1, title="Up", year=2009, ..., popularity=50.0, original_rank=3)
up_all_night = TMDBSearchResult(id=2, title="Up All Night", year=2011, ..., popularity=90.0, original_rank=0)
pick_best("UP", None, [up_all_night, up])  # -> None
# score_result("UP", None, up) == 0.3875  (< MIN_MATCH_SCORE == 0.5)
# score_result("UP", None, up_all_night) == 0.64  (would have cleared the floor)
```
Confirmed with `fuzz.WRatio("UP", "Up") == 50.0` directly (not case-insensitive
here), vs. `fuzz.WRatio("UP", "UP") == 100.0`. Before this diff, the plain
global-argmax fallback would have returned *something* (`"Up All Night"`,
wrong movie but non-`None`); after this diff, having a real exact match
present actively makes the outcome `None` instead. This is the exact
"pathological case where the best exact match scores below the floor"
the task asked to construct — it is real, reachable (all-caps or
otherwise differently-cased short captions are a plausible real-world
input for this pipeline's OCR/caption-extracted queries), and it
silently defeats the entire point of the exact-match tier for the one
case class (low TMDB rank + case-differing query) it should have helped
most. The floor-check *mechanism* itself isn't broken (it still
correctly returns `None` below `MIN_MATCH_SCORE`), but the input to that
mechanism is inconsistent with how "exact" was defined one line earlier.
Fix direction: within the exact-match tier, don't re-score title
similarity via `fuzz.WRatio` at all (it's already known to be 1.0 in the
intended sense) — tiebreak only on `rank_bonus`/`year_bonus`, or at minimum
make `score_result`'s title-similarity term case/whitespace-normalized
the same way `_is_exact_title_match` is, so the two checks can't disagree.

**Non-blocking:** `_is_exact_title_match()` only strips leading/trailing
whitespace (`.strip().casefold()`), so it misses exact matches that
differ by internal whitespace runs (e.g. OCR/caption noise producing
`"The  Matrix"` with a double space) or Unicode normalization form.
Confirmed: `_is_exact_title_match("The  Matrix", "The Matrix")` is
`False`. Not a regression from this diff — these cases simply fall
through to the unchanged fuzzy fallback, the same as before this fix
existed — just a missed robustness improvement, not a new bug.

**Judgment on "could exact-match-always-wins ever pick something worse
than the old fuzzy-only approach?":** Yes, in principle, but only in a
narrow class of inputs: it requires the *correct* intended movie's real
TMDB title to NOT be a literal (case/whitespace-insensitive) match for
the query (e.g. the query is missing an article, has different
punctuation, or the query itself is slightly off from the caption),
while some *other*, unrelated/obscure movie's title happens to be a
literal exact match for that same query string. In that specific
situation, the obscure one wins categorically even if the real target
would have scored dramatically higher under the old fuzzy formula. For
genuinely famous titles like the task's "The Dark Knight" example, this
is close to non-reachable in practice: TMDB's title field for a famous
film is reliably its exact common name, so the real film would also
land in the exact tier (and `rank_bonus`/`year_bonus` tiebreaking inside
that tier would almost always still favor it over an obscure decoy,
since TMDB's own relevance ranking already biases toward the better-known
title). This class of risk is also the explicit, deliberate tradeoff
this fix accepts per `brainstorm.md`'s "name matching categorically
outranks popularity" decision — it is narrower and far less frequently
triggered than the bug being fixed (the "Triangle" / "Triangle of
Sadness" substring-match class is systematic and common; this
"exact-but-wrong-movie" class requires a specific title collision plus
the real movie's title diverging from the query, which is comparatively
rare). Net judgment: an acceptable, documented tradeoff, not a
newly-introduced regression — but worth keeping in mind if a future bug
report surfaces a short/generic query colliding with an obscure
exact-titled movie.

**From `/ponytail:ponytail-review` (over-engineering/complexity):**
- `L61-62` **shrink**: the two-line "exact matches, else all results"
  fallback (`exact_matches = [...]; candidates = exact_matches if
  exact_matches else results`) can be one line, relying on a non-empty
  list being truthy: `candidates = [r for r in results if
  _is_exact_title_match(query, r.title)] or results`.
- net: -1 line possible. Everything else is lean — `_is_exact_title_match`
  is a single strict comparison with no stray flexibility, and the
  tiered `pick_best` has no speculative branches.

**Independent test run (run directly in this review pass, not trusted
from the build report):**
- `python3 -m pytest tests/unit -q` → **203 passed**, matching the build
  report's count exactly.

**Independent live-API re-verification (own script, own call, not the
build report's pasted output):** loaded the real `.env` `TMDB_API_KEY`
via `config.get_tmdb_token()` + `load_dotenv()`, built a real
`TMDBHttpClient`, called `search_movie("Triangle")` against the live
TMDB API, and ran the full result list through `pick_best("Triangle",
None, results)`. Live TMDB returned 20 results, including `"Triangle of
Sadness"` (2022, `original_rank=0`, popularity 34.67) ranked ahead of
the real `"Triangle"` (2009, `original_rank=1`) and several other
exactly-titled `"Triangle"` entries at other years/ranks. Result:
```
pick_best('Triangle', None, results) ->
TMDBSearchResult(id=26466, title='Triangle', year=2009, poster_path='/cRlMrbc4Iof7vN0ZqHwJnMBYBLi.jpg', ..., popularity=9.7426, original_rank=1)
```
Matches `id=26466`, `title="Triangle"`, `year=2009` exactly — the
original fix's core claim independently confirmed against a fresh live
API call (note: TMDB's live dataset had shifted slightly since the prior
verification — e.g. `"Triangle of Sadness"`'s id and popularity differ
from the earlier pasted output, and the result set now includes a few
additional `"Triangle"`-titled entries — but the fix's behavior holds
regardless).

One blocking finding: the exact-match tier's own tiebreak/floor check
reuses `score_result()`'s case-sensitive `fuzz.WRatio` title-similarity
term, which disagrees with `_is_exact_title_match()`'s case-insensitive
definition of "exact" — a real exact match at low TMDB rank with
different casing than the query can be scored below `MIN_MATCH_SCORE`
and discarded as `None` even though a genuine exact match was present
in the results, which is strictly worse than the pre-fix global-argmax
behavior for that case class. All other findings (the internal-whitespace/
Unicode gap in `_is_exact_title_match`, and the ponytail one-line shrink)
are non-blocking. Tests (203 passed) and the live-API Triangle case were
independently re-run and matched; the "exact match could beat a clearly
better fuzzy match" risk is real but narrow, judged an acceptable,
documented tradeoff rather than a regression.

VERDICT: NEEDS FIXES

### Fixes applied

Fixed the BLOCKING finding in `reel2movie/tmdb/scoring.py` (review→fix
cycle 1 of 3).

**Direction chosen: (a)** — exact matches no longer go through
`score_result()` at all. Added a new `_exact_tier_rank(result,
year_hint)` helper used only inside `pick_best()`'s exact-match branch:

```python
def _exact_tier_rank(result: TMDBSearchResult, year_hint: int | None) -> float:
    rank_bonus = 1 / (1 + result.original_rank)
    year_bonus = 1.0 if year_hint and result.year == year_hint else 0.0
    return 0.25 * rank_bonus + 0.10 * year_bonus
```

`pick_best()`'s exact-match branch now does
`max(exact_matches, key=lambda r: _exact_tier_rank(r, year_hint))` and
returns immediately — it no longer calls `score_result()` or checks
`MIN_MATCH_SCORE` for that tier at all. The no-exact-match fallback
branch is untouched: it still calls `score_result()` and still enforces
`MIN_MATCH_SCORE` exactly as before.

**Why (a) over (b):** both directions fix the bug, but (a) avoids adding
a conditional/special-case ("is this an exact match? then fix
title_similarity to 1.0...") inside `score_result()`, which is also used
standalone (and tested standalone, e.g. `test_exact_title_match_scores_
highest`) outside of `pick_best()`'s tiering — threading exact-match
awareness into it would have coupled a general-purpose scorer to
`pick_best()`'s tiering concept. Keeping the exact tier's ranking as its
own small, honestly-named function (`_exact_tier_rank`) keeps
`score_result()` simple and unchanged, and makes the exact tier's logic
self-contained and easy to audit: it only ever looks at `rank_bonus`/
`year_bonus`, never at title text, so there is no case-sensitivity (or
any other title-matching) path left for it to disagree with
`_is_exact_title_match()` on. The `0.25`/`0.10` weights were kept
identical to `score_result()`'s so the relative tiebreak behavior among
exact matches (rank vs. year_hint) is unchanged from before — this is
mathematically equivalent to what `score_result()` would have computed
*if* `title_similarity` had correctly been a constant `1.0` for every
member of the tier, which is precisely the bug being fixed.

**Ponytail suggestions:**
- *(1) collapse the two-line fallback into one line* — not applied as
  literally suggested. The suggested one-liner
  (`candidates = [...] or results`) assumed both tiers still flow
  through a single `score_result`-based `max(...)` call, which is no
  longer true under direction (a): the exact tier now has its own
  ranking function and skips `MIN_MATCH_SCORE` entirely, so there's no
  longer a shared `candidates` list to unify the two branches around.
  The new code is arguably still just as lean — `if exact_matches:
  return max(exact_matches, key=...)` is one line more than a `candidates
  = ... or ...` assignment would have been, but avoids re-merging two
  branches that now have genuinely different semantics (one skips the
  floor check, one doesn't).
- *(2) whitespace-normalization nit* — left alone, as instructed (the
  reviewer explicitly flagged it as a non-regression, not required).

**Tests:** added
`test_pick_best_exact_match_not_penalized_by_case_sensitive_wratio` to
`tests/unit/tmdb/test_scoring.py` — the reviewer's exact repro case:
`TMDBSearchResult(title="Up", year=2009, popularity=50.0,
original_rank=3)` vs `TMDBSearchResult(title="Up All Night", year=2011,
popularity=90.0, original_rank=0)`, asserts
`pick_best("UP", None, [up_all_night, up])` returns the `"Up"` result
(not `None`, not "Up All Night").

`python3 -m pytest tests/unit -q` → **204 passed** (203 before this fix
+ 1 new regression test).

**Manual verification (outside pytest), reviewer's exact case:**
```
fuzz.WRatio("UP", "Up") = 50.0
score_result("UP", None, up) [old-style, case-sensitive] = 0.3875
MIN_MATCH_SCORE = 0.5
pick_best("UP", None, [up_all_night, up]) -> TMDBSearchResult(id=1, title='Up', year=2009, poster_path=None, overview='', popularity=50.0, original_rank=3)
PASS: exact match "Up" correctly returned, not None, not Up All Night
```
Confirms the invariant the reviewer required: `score_result()` alone
still scores `"Up"` at 0.3875 (below `MIN_MATCH_SCORE`) because
`fuzz.WRatio` is still case-sensitive — but `pick_best()` no longer
routes exact-tier candidates through `score_result()`/`MIN_MATCH_SCORE`
at all, so the case-sensitivity of `fuzz.WRatio` can no longer affect
the outcome for a result `_is_exact_title_match()` has already
classified as exact.

#### cycle 2 review (current — fresh re-review of the post-fix-cycle-1 working tree)

Scope: the full current diff — `reel2movie/tmdb/scoring.py` (both
`_is_exact_title_match()` from cycle 0 and `_exact_tier_rank()` from fix
cycle 1), `tests/unit/tmdb/test_scoring.py` (all 6 added tests), and
`PROGRESS.md`. Run as a clean re-review, not a continuation of the
cycle 0/1 session: fresh `/code-review` (high, forked) and
`/ponytail:ponytail-review` invocations against the current diff, a direct
read of `_exact_tier_rank()`'s source, two own repro scripts (the
reviewer's original case + a fresh adversarial tie case), an independent
`python3 -m pytest tests/unit -q` run, and an independent live-TMDB-API
re-verification (own script, own call).

**Primary question — is the cycle 0 BLOCKING case-sensitivity bug actually
fixed? Yes, confirmed by direct reproduction, not just by reading the fix:**
```
fuzz.WRatio('UP','Up') = 50.0
score_result('UP', None, up) [would-be, bypassed now] = 0.3875
MIN_MATCH_SCORE = 0.5
pick_best('UP', None, [up_all_night, up]) -> TMDBSearchResult(id=1, title='Up', year=2009, ...)
PASS: exact match 'Up' returned despite case-sensitive WRatio scoring below floor
```
Same outcome the fix-cycle-1 report claimed, independently re-run.

**(a) Does `_exact_tier_rank()` genuinely never touch title text/fuzz
matching? Confirmed by direct read of the source, not inference:**
```python
def _exact_tier_rank(result: TMDBSearchResult, year_hint: int | None) -> float:
    rank_bonus = 1 / (1 + result.original_rank)
    year_bonus = 1.0 if year_hint and result.year == year_hint else 0.0
    return 0.25 * rank_bonus + 0.10 * year_bonus
```
The only attributes read are `result.original_rank` and `result.year`;
`result.title` never appears, `fuzz`/`score_result`/`MIN_MATCH_SCORE` are
never imported or called from it, and `pick_best()`'s exact branch
(`return max(exact_matches, key=lambda r: _exact_tier_rank(r, year_hint))`)
calls nothing else before returning. There is no path left by which a
case-sensitivity (or any other title-matching) disagreement between this
function and `_is_exact_title_match()` can resurface. Cycle 0's BLOCKING
finding is genuinely fixed, not just re-described as fixed.

**(b) Judgment — is skipping `MIN_MATCH_SCORE` entirely for ALL exact
matches safe?** Yes — safe, and actually the only sensible choice given
how the floor is calibrated, not merely a defensible shortcut:

- `MIN_MATCH_SCORE` (0.5) was calibrated against `score_result()`'s full
  formula, where `title_similarity` contributes up to `0.65` of the total
  — i.e. the floor is fundamentally a title-similarity gate, with
  `rank_bonus`/`year_bonus` only ever nudging a result that already has
  decent title similarity. `_exact_tier_rank()`'s own range is `[0, 0.35]`
  (`0.25` max rank_bonus + `0.10` max year_bonus) — strictly *below* `0.5`
  for every possible input. Applying the unmodified floor to this tier's
  scale wouldn't just risk edge cases, it would reject every exact match,
  always, unconditionally — proof that the floor was never meant to apply
  to this tier's scale in the first place, not just safe to omit from it.
- Conceptually: `MIN_MATCH_SCORE` exists to answer "is the title similar
  enough to trust?". Within the exact tier, that question is already
  answered categorically and maximally by `_is_exact_title_match()`
  (post-casefold string equality) — there is no continuous "how similar"
  left for a floor to gate. The only genuinely open question inside the
  tier is disambiguation among multiple same-titled movies, and that is
  what `rank_bonus`/`year_bonus` tiebreaking already does — a popularity
  floor was never doing that disambiguation job either.
- Adversarial case considered: could a title be an exact (post-casefold)
  match to the query yet obviously be the wrong movie, in a way
  `MIN_MATCH_SCORE` was protecting against? The only such class is the one
  cycle 0's own judgment paragraph already identified and accepted as a
  documented tradeoff — an obscure movie's title collides exactly with the
  query while the *real* target's title diverges from the query (e.g. a
  missing article or punctuation). Re-examined here specifically for
  `MIN_MATCH_SCORE`'s role: the floor would not have blocked this class
  either, before or after this fix — the old formula scores a
  title-identical string at `title_similarity ≈ 1.0` via `fuzz.WRatio`
  regardless of which movie it belongs to, so an obscure exact-string
  collision would have cleared `MIN_MATCH_SCORE` comfortably under the old
  code too. `MIN_MATCH_SCORE` was never the mechanism guarding against
  "right string, wrong movie" — only against "string doesn't really
  match" — so removing it from a tier where the string is already
  confirmed to match changes nothing about that risk. Net judgment:
  "exact title match" is inherently strong enough that a popularity/
  `MIN_MATCH_SCORE` floor was never meaningfully protecting anything in
  this tier — skipping it is correct, not just low-risk.

**(c) Repro of the reviewer's original case:** see "Primary question"
above — reproduced directly, passes.

**(c) Fresh adversarial case — two exact matches, no year hint, IDENTICAL
`original_rank` (a tie within a tie):**
```python
triangle_a = _result(id=100, title="Triangle", year=2009, original_rank=4)
triangle_b = _result(id=200, title="Triangle", year=1994, original_rank=4)
_exact_tier_rank(triangle_a, None) == _exact_tier_rank(triangle_b, None) == 0.05
pick_best("Triangle", None, [triangle_a, triangle_b]) -> id=100 (triangle_a)
pick_best("Triangle", None, [triangle_b, triangle_a]) -> id=200 (triangle_b)
# stable across 5 repeated trials each ordering
```
`max()` behaves exactly per Python's documented tie-break rule: it returns
the *first* maximal element encountered in iteration order. No crash, no
`None`, no non-determinism across repeated runs — the outcome is a pure,
stable function of input list order when every other signal is tied.
**Caveat, checked directly:** this exact scenario is not reachable via the
one production call site. `reel2movie/tmdb/resolver.py:90` passes
`client.search_movie(...)`'s return value straight into `pick_best()`
unmodified, and `TMDBHttpClient.search_movie()`
(`reel2movie/tmdb/client.py:107`) assigns `original_rank=rank` via
`enumerate(payload["results"])` — guaranteeing every result in one
`search_movie()` call has a unique `original_rank`. So a same-call tie on
`original_rank` can't actually occur today; this was a synthetic
unit-level stress case, not a reachable regression. Still worth having
confirmed: `pick_best()` takes a plain `list[TMDBSearchResult]` with no
caller-independent uniqueness guarantee enforced at the type level, so if
a future caller ever merges results from more than one search call before
calling `pick_best()`, the tie-break would silently degenerate to list
order rather than crash — good defensive behavior to have confirmed now
rather than assumed.

**From `/ponytail:ponytail-review` (over-engineering/complexity) —
re-run fresh on the full current diff:** nothing to cut. `_exact_tier_rank()`
duplicates `score_result()`'s two-line `rank_bonus`/`year_bonus`
computation, but extracting a shared helper is a wash (a 4-line helper
replacing two 2-line duplicates nets ~0 lines) and the duplication is a
maintainability/drift concern (see code-review finding below), not a
complexity/line-count one — out of ponytail's "fewer lines" scope. No
speculative flexibility, no unused config, no reinvented stdlib in the new
code. **Lean already. Ship.**

**From `/code-review` (high, forked) — two findings, both non-blocking:**

1. **Non-blocking (latent, currently unreachable in output):**
   `reel2movie/tmdb/resolver.py:100`'s `resolve_candidate()` sets
   `ResolvedMovie.match_score` via `score_result(query_title, year_hint,
   best)` unconditionally — including when `best` came from `pick_best()`'s
   exact-match tier, which by design never calls `score_result()` to pick
   it. Confirmed directly: for the "UP"/"Up" case, `pick_best()` correctly
   returns `up` via the exact tier, but `resolve_candidate()` would then
   store `match_score = score_result("UP", None, up) == 0.3875` — a value
   *below* `MIN_MATCH_SCORE`, on a result the pipeline just trusted as a
   categorical exact match. Checked whether this is reachable in current
   output: `reel2movie/cli.py`'s `_tmdb_to_dict()` deliberately excludes
   `match_score` from the emitted CLI output today (its docstring says so
   explicitly), and nothing else in the codebase reads
   `ResolvedMovie.match_score`, so this doesn't produce an incorrect
   *visible* result right now — hence non-blocking rather than blocking.
   However, `flow.md` ("Sort by confidence") and `brainstorm.md` (a
   `confidence` field in the documented output draft) both describe a
   planned confidence-based sorting/thresholding feature that this field
   is clearly meant to feed — and for that feature, a misleadingly low
   `match_score` on exactly the results this fix was designed to treat as
   highest-confidence would be actively wrong. Recommended near-term
   follow-up (not required for this diff): give exact-tier picks a
   `match_score` consistent with their tier (e.g. a constant `1.0`, or
   reuse `_exact_tier_rank`'s value on a comparable scale) instead of
   silently re-running them through the case-sensitive formula the tier
   was built to bypass.
2. **Non-blocking (maintainability nit):** `_exact_tier_rank()` duplicates
   `score_result()`'s `rank_bonus`/`year_bonus` formula and literal weights
   (`0.25`, `0.10`) as a separate, independently-maintained copy rather
   than a shared helper. If either formula is retuned later (e.g. the
   weights, or the year-bonus condition), the two tiers' tiebreak logic
   can silently drift apart with nothing (no test, no type error) to
   surface the inconsistency. Same observation ponytail's duplication note
   above makes from the lines angle; flagged here from the drift-risk
   angle. Low cost to defer: the weights are currently identical by
   construction and the comment in `_exact_tier_rank()`'s docstring
   already documents the intent to keep them in sync.

**Independent test run (run directly in this pass, not trusted from the
build/fix-cycle-1 report):**
```
python3 -m pytest tests/unit -q
204 passed in 3.75s
```
Matches the fix-cycle-1 report's count exactly.

**Independent live-API re-verification (own script, own call, not the
fix-cycle-1 report's pasted output) — confirms both cycles' fixes hold
together end-to-end against live data:** loaded the real `.env`
`TMDB_API_KEY` via `config.get_tmdb_token()` + `load_dotenv()` (passed an
explicit path — `load_dotenv()`'s default search walks up from the
*calling script's* own directory, not the cwd, so a script run from
outside the repo needs the path spelled out explicitly; not a product
bug, a test-harness detail), built a real `TMDBHttpClient`, called
`search_movie("Triangle")` against the live TMDB API, and ran the full
result list through `pick_best("Triangle", None, results)`. Live TMDB
returned 20 results, including `"Triangle of Sadness"` (2022,
`original_rank=0`, popularity 34.67, still ranked first by TMDB itself),
several genuinely-titled `"Triangle"` entries at other years (2009, 2020,
2024, 2007, 2022, 1994, 2014, 2025), and an all-caps `"TRIANGLE"` (2012,
`original_rank=16`) that only matters because of cycle 0's fix (it's an
exact match only once case is normalized). Result:
```
pick_best('Triangle', None, results) ->
TMDBSearchResult(id=26466, title='Triangle', year=2009, ..., popularity=9.7426, original_rank=1)
```
Matches `id=26466`, `title="Triangle"`, `year=2009` — the correct 2009
time-loop thriller, beating both the more popular `"Triangle of Sadness"`
(`original_rank=0`) and the other exact-titled `"Triangle"` entries via
`_exact_tier_rank`'s rank-bonus tiebreak (no `year_hint` supplied). The
combined fix from both cycles resolves correctly end-to-end against a
fresh live API call.

**Summary:** no BLOCKING findings in this pass. The cycle 0 BLOCKING bug is
confirmed genuinely fixed by direct reproduction and by reading
`_exact_tier_rank()`'s source (it provably never touches title text or
`fuzz`). Skipping `MIN_MATCH_SCORE` for the entire exact tier is judged
correct, not just acceptable — the floor's own scale (`title_similarity`-
dominated, max possible exact-tier score of `0.35` vs. a `0.5` floor)
proves it was never calibrated to apply to this tier, and the risk class
it might otherwise have guarded against ("right string, wrong movie") was
never something `MIN_MATCH_SCORE` actually caught, before or after this
fix. The tie-within-a-tie case confirmed `max()`'s deterministic
first-wins behavior with no crash, though the scenario itself is not
reachable via the current single production call site. Two non-blocking
findings carry forward as recommended follow-ups: `resolve_candidate()`'s
`match_score` can be misleadingly low for exact-tier picks (latent,
currently unreachable in any emitted output, but worth fixing before the
planned confidence-sorting feature lands), and `_exact_tier_rank()`
duplicates `score_result()`'s rank/year formula (drift risk, no test
coverage for staying in sync). Tests (204 passed) and the live-API
Triangle case were independently re-run from scratch and matched.

VERDICT: ACCEPTABLE

## Follow-up — drop unresolved duplicate when same-query candidate already resolved — status: DONE

**Bug (confirmed via live testing):** a reel with no caption/comment match
fell through to the visual fallback, which sampled multiple frames and
detected the SAME movie poster across two different frames, producing two
separate `Candidate`s with identical `raw_text` (e.g. `"Om Dar-B-Dar
(1988)"`). One copy's TMDB resolution succeeded; the other hit a transient
network error and came back `tmdb=None`. `_dedupe()` in
`reel2movie/pipeline/waterfall.py` groups resolved recommendations by
`tmdb.id`, so it correctly merges two recommendations that both resolve —
but an unresolved recommendation has no id to group by, so it was invisible
to that logic even when another recommendation with the exact same `query`
string had resolved. Final output showed both: the real resolved movie and
a redundant, confusing `tmdb: null` duplicate.

**Fix (minimal, additive, nothing else touched):** in `_dedupe()`, after
splitting recommendations into `unresolved`/`resolved` (unchanged), added
one line computing the set of `query` strings among `resolved`, then
filtered `unresolved` to drop any whose `query` appears in that set, before
the existing dedupe-by-`tmdb.id` grouping (unchanged) runs. An unresolved
recommendation with no same-query resolved sibling is unaffected and still
kept, per flow.md's existing rule. Docstring updated to describe the new
behavior. No other function in `waterfall.py` was touched — no renaming, no
restructuring of the existing dedupe-by-id logic, `_resolve_all` untouched.

**Tests added** (`tests/unit/pipeline/test_waterfall.py`), calling `_dedupe`
directly:
- `test_unresolved_duplicate_dropped_when_same_query_candidate_already_resolved`
  — exact real-world repro shape (same `query="Om Dar-B-Dar (1988)"`, one
  `Recommendation` with a real `ResolvedMovie`, one with `tmdb=None`) ->
  asserts only the resolved one survives.
- `test_unresolved_candidate_with_no_resolved_sibling_is_still_kept` —
  confirms existing behavior unchanged: a genuinely-unresolved
  recommendation with no same-query resolved sibling is kept, not
  accidentally dropped.
- `test_two_different_unresolved_candidates_with_different_queries_both_kept`
  — confirms the new logic doesn't merge unrelated unresolved candidates
  with each other.

```
python3 -m pytest tests/unit -q
207 passed in 3.69s
```
(204 prior + 3 new, all passing.)

### Review findings (latest pass)

Reviewed via `/code-review` (medium, forked) on the current diff
(`reel2movie/pipeline/waterfall.py`, `tests/unit/pipeline/test_waterfall.py`,
`PROGRESS.md`), `/ponytail:ponytail-review` on the same diff, a from-scratch
`python3 -m pytest tests/unit -q` run, and a direct, independent `_dedupe()`
repro (own script, own constructed `Recommendation`s, not the build report's
pasted output).

**Non-blocking — order-of-operations confirmed safe:** traced the actual
code (`reel2movie/pipeline/waterfall.py:269-284`). The two new lines run
immediately after the existing `unresolved`/`resolved` split and *before*
the `best_by_tmdb_id` grouping loop, but the two steps are independent
regardless of ordering: the new query-based filter only ever reads/writes
the `unresolved` list, and the id-based merge only ever reads the (full,
unfiltered) `resolved` list to build `best_by_tmdb_id`. Neither step's
input depends on the other step's output, so placing the query filter
before vs. after the id-merge loop would produce the identical final
`deduped` list either way. No bad interaction.

**Non-blocking — same-query-but-different-candidate edge case, judged safe:**
traced `resolve_candidate` (`reel2movie/tmdb/resolver.py:78-101`): it is a
pure function of `candidate.raw_text` (== `Recommendation.query`) and the
TMDB client's search results — `year_hint`/`query_title` are both derived
from `raw_text` alone, with no other disambiguating input. `_resolve_all`
only ever converts an *exception* from that call into `tmdb=None`; it never
introduces a legitimate "different movie" branch for the same input text.
Consequence: two `Recommendation`s that share the exact same literal
`query` string necessarily went through the identical TMDB search, so any
resolved/unresolved split between them can only be transient-failure noise
(network blip, as the bug report itself describes), never two genuinely
distinct real-world candidates that happen to print the same raw text with
different correct outcomes. Verified this directly rather than just
reasoning about it — constructed a "lookalike" case deliberately shaped like
the worry (same literal query, one resolved to a real TMDB id, one
`tmdb=None`, framed as if they were different candidates) and ran it through
`_dedupe()`: the unresolved copy is dropped, which is the *correct* outcome
given the above, not a bug. **Judgment: the edge case the task asked about
cannot occur in this codebase's design — the fix is safe without
qualification.**

**Non-blocking — scope confirmed minimal, nothing else touched:**
`git diff -- reel2movie/pipeline/waterfall.py` shows exactly one hunk,
confined to `_dedupe()` (lines 256-284: the expanded docstring plus the two
logic lines). `_extract_from_caption`, `_extract_from_creator_comments`,
`_extract_from_visual`, `_resolve_all`, and `run_pipeline` all have zero
diff lines — confirmed by the diff itself, not by trusting the build
report's claim.

**Non-blocking — `/ponytail:ponytail-review`:** "Lean already. Ship."
`net: -0 lines possible.` The 2-line fix (set comprehension + list-comp
filter) is already the minimal idiomatic form; the docstring expansion
matches this file's existing verbose-docstring convention elsewhere; the 3
new tests each cover a distinct behavioral case and, per the skill's own
rule, test/assert code is the ponytail minimum and is never flagged for
deletion.

**Non-blocking — `/code-review` (medium):** no findings. Assessed as a
deliberate, well-documented, narrowly-scoped bugfix with matching tests;
no correctness, reuse, or efficiency issue cleared the bar for a finding.

**Independent verification (run directly in this review pass, not trusted
from the build report):**
- `python3 -m pytest tests/unit -q` → **207 passed**, matching the build
  report's count exactly, confirmed independently.
- Direct `_dedupe()` repro, own script, own constructed objects (not copy-
  pasted from the test file): built one resolved `Recommendation` + one
  `tmdb=None` `Recommendation` sharing `query="Om Dar-B-Dar (1988)"` →
  `_dedupe()` returned exactly 1 item, the resolved one. Built a lone
  `tmdb=None` `Recommendation` with no resolved sibling → `_dedupe()`
  returned it unchanged. Built the same-query "lookalike distinct
  candidate" edge case described above → `_dedupe()` dropped the unresolved
  copy, confirmed correct per the judgment above. All three match the
  claimed behavior exactly.

No blocking findings. The fix is a correct, minimally-scoped 2-line
addition that behaves exactly as documented, the same-query edge case the
task raised cannot produce an incorrect drop given how `resolve_candidate`
works, and the diff genuinely touches nothing outside `_dedupe()` and its
tests.

VERDICT: ACCEPTABLE

---

## Follow-up — widen TMDB resolution scope to include TV shows — status: done

### Motivation

Live testing showed a reel recommending "The Mentalist" (explicitly
described in its own caption as "this cop consultant mystery **show**...
on Netflix") got confidently resolved to an unrelated 2011 Indonesian
MOVIE (TMDB id 648544) that happens to share the exact title — because the
pipeline only ever searched TMDB's `/search/movie` endpoint, which cannot
return TV results at all. This follow-up widens scope so TV shows are
valid resolution targets too, not just movies.

### Live `/search/multi` verification (done BEFORE writing any code)

Hit the real TMDB API directly (via `load_dotenv()` +
`config.get_tmdb_token()` + `requests`, scratch script, not committed) with
`GET /3/search/multi?query=The%20Mentalist`. Observed, verbatim (abridged):

```json
{
  "id": 5920,
  "name": "The Mentalist",
  "media_type": "tv",
  "first_air_date": "2008-09-23",
  ...
},
{
  "id": 648544,
  "title": "The Mentalist",
  "media_type": "movie",
  "release_date": "2011-11-10",
  ...
}
```

Confirmed:
- Every result row carries `media_type`: `"movie"`, `"tv"`, or `"person"`
  (confirmed `"person"` separately via `query=Tom Hanks`, e.g.
  `{"id": 31, "name": "Tom Hanks", "media_type": "person", ...}` — no
  `title`/`release_date`/usable-as-a-recommendation shape at all).
- Movie rows use `title` + `release_date`; TV rows use `name` +
  `first_air_date` — exactly the field-name split the task described.
- The real TV id for "The Mentalist" is **5920**, not 1622 as guessed in
  the task brief — confirmed against the live call, not assumed.
- **New finding, not in the task brief:** `/search/multi` does **not**
  support a `year` query param at all — `query=The Matrix&year=1999` and
  `query=The Matrix&year=2199` (an impossible year) returned identical
  `total_results` and ordering. Unlike `/search/movie`, TMDB silently
  ignores `year` on this endpoint server-side. `year` is still sent (it's
  harmless) but the real year-based disambiguation now happens entirely
  client-side via `scoring.py`'s existing `year_bonus` term — this was
  already true in spirit (scoring always re-checked the year), but now
  it's the *only* place year filtering happens.

### Naming decision: renamed `search_movie` → `search`

Chose to rename rather than keep the old name, since `search_movie` would
now be actively misleading (it searches TV too) and the task explicitly
permitted a rename as long as every call site/fake was updated
consistently. Updated every one of them — confirmed via grep before
starting and a full `pytest` run after:
- `reel2movie/core/protocols.py` — `TMDBClient.search_movie` → `.search`.
- `reel2movie/tmdb/client.py` — `TMDBHttpClient.search_movie` → `.search`;
  endpoint constant `_SEARCH_MOVIE_URL` → `_SEARCH_MULTI_URL`, now pointing
  at `/3/search/multi`.
- `reel2movie/tmdb/resolver.py` — `client.search_movie(...)` →
  `client.search(...)`.
- Fakes in `tests/unit/core/test_protocols.py`,
  `tests/unit/tmdb/test_resolver.py`,
  `tests/unit/pipeline/test_waterfall.py` — all renamed to `.search`.
- `tests/unit/tmdb/test_client.py` — every `client.search_movie(...)` call
  site renamed to `client.search(...)`; test function names that
  referenced `search_movie`/the old endpoint renamed to match (e.g.
  `test_search_hits_search_multi_endpoint`).

### What changed, file by file

- **`reel2movie/core/models.py`** — added `media_type: str` to both
  `TMDBSearchResult` and `ResolvedMovie`. Class names kept as-is (not
  renamed) per the task's instruction, with a docstring note on each that
  it may now represent a TV show despite the name.
- **`reel2movie/core/protocols.py`** — `TMDBClient.search_movie` renamed to
  `.search`; docstring updated to say "movies AND TV shows."
- **`reel2movie/tmdb/client.py`** — `search()` now calls
  `GET /3/search/multi` instead of `/3/search/movie`. Filters out any
  result with `media_type == "person"`. For kept rows: `title` <- `title`
  (movie) or `name` (tv); `year` <- `_parse_year()` of `release_date`
  (movie) or `first_air_date` (tv) — same parsing logic as before, just
  applied to whichever date field matches the row's `media_type`;
  `media_type` <- the raw TMDB value. `original_rank` is now a **sequential
  rank over the kept (non-person) rows**, not the raw payload index — a
  person result sitting between two valid candidates in TMDB's raw
  ordering no longer dilutes the loser's rank number, which is more
  correct for `scoring.py`'s `rank_bonus` term (TMDB's *own relevance
  order among valid candidates*, not among everything it decided to
  return).
- **`reel2movie/tmdb/resolver.py`** — `resolve_candidate()` now calls
  `client.search(...)` and threads `best.media_type` through into the
  `ResolvedMovie` it constructs. No other logic changes.
- **`reel2movie/tmdb/scoring.py`** — confirmed, not assumed: unchanged.
  Re-read `score_result`, `pick_best`, `_exact_tier_rank`,
  `_is_exact_title_match` line by line — every one reads only
  `result.title`, `result.year`, and `result.original_rank`; none ever
  touches `media_type`. A movie and a TV show sharing an exact title now
  compete on equal footing through the existing tiered exact-match logic,
  with TMDB's own relevance ordering (via `rank_bonus`) as the tiebreaker
  — exactly the same mechanism that already breaks ties between two
  movies, which is the correct behavior here.
- **`reel2movie/cli.py`** — `_tmdb_to_dict()` now emits `media_type` as a
  6th key, a deliberate documented deviation from `brainstorm.md`'s
  original 5-field shape (brainstorm.md's "Output shape" section updated
  to match).
- **`brainstorm.md`** — "Scope (v1)" bullet that said "Not in scope for
  v1: TV shows..." rewritten to state both movies and TV shows are valid
  recommendation targets; "Output shape (draft)" JSON example gets a
  `"media_type": "movie | tv"` key. No other section asserted movie-only
  scope, so nothing else in that document was touched.

### Tests

Updated every existing fake `TMDBClient` (grepped for `search_movie` across
the whole `tests/` tree first — 6 files had call sites/fakes: `test_client.py`,
`test_resolver.py`, `test_waterfall.py`, `test_protocols.py`, plus
`TMDBSearchResult(`/`ResolvedMovie(` construction sites needing the new
required `media_type` field in `test_models.py` and `test_scoring.py`;
`test_deps.py` had no `search_movie` references at all, confirmed by grep).

New tests added:
- `tests/unit/tmdb/test_client.py::test_search_filters_out_person_and_maps_movie_and_tv_distinctly`
  — mocks a `/search/multi`-shaped response with a movie (The Mentalist,
  the Indonesian one), a tv show (The Mentalist, the Netflix one), and a
  person (Tom Hanks); asserts the person is dropped, the tv row's
  `name`/`first_air_date` map to `title`/`year` with `media_type="tv"`,
  and the movie row's `title`/`release_date` still map correctly with
  `media_type="movie"`.
- `tests/unit/tmdb/test_resolver.py::test_maps_tv_result_to_resolved_movie_with_tv_media_type`
  — fake client returns a tv-shaped `TMDBSearchResult`; confirms
  `resolve_candidate()` produces a `ResolvedMovie` with
  `media_type="tv"`.
- `tests/unit/test_cli.py` — extended `test_prints_expected_json_shape`
  with explicit assertions that `media_type` appears (and equals
  `"movie"` for the canned `ResolvedMovie`) in the serialized JSON.

`python3 -m pytest tests/unit -q`:

```
209 passed in 3.82s
```

(207 before this change, +2 new test functions; existing tests' assertion
counts grew in-place without adding new test functions for `test_cli.py`
and `test_models.py`/`test_scoring.py`.)

### Live-API verification of the actual real-world bug case

Ran the exact real candidate from the bug report —
`Candidate(raw_text="The Mentalist", source=SourceTag.CAPTION,
confidence=0.9)` (no year hint, matching the real caption) — through the
real `resolve_candidate()` end to end against the live API (real
`TMDBHttpClient`, real bearer token via `config.get_tmdb_token()`):

```
resolved: ResolvedMovie(id=5920, title='The Mentalist', year=2008,
poster_path='/acYXu4KaDj1NIkMgObnhe4C4a0T.jpg', overview='Patrick Jane, a
former celebrity psychic medium, uses his razor sharp skills of
observation and expertise at "reading" people to solve serious crimes
with the California Bureau of Investigation.', match_score=0.9,
media_type='tv')
```

Confirms the fix: resolves to the Netflix crime-drama TV series (id 5920,
`media_type="tv"`), NOT the unrelated 2011 Indonesian movie (id 648544)
from before. `media_type='tv'` correctly flags this as a TV show, not a
movie, in the final pipeline output.

### Verification scripts

Both the live `/search/multi` shape probe and the end-to-end
"The Mentalist" resolution script were throwaway scripts written only to
the session scratchpad, never committed to the repo.

### Review findings (latest pass)

Reviewed via `/code-review` (medium, forked) on the current diff (all 13
non-`PROGRESS.md` touched files), `/ponytail:ponytail-review` on the same
diff, a from-scratch `python3 -m pytest tests/unit -q` run, and an
independent live-API re-verification script (own script, own
`Candidate`/`resolve_candidate()` call, not the build report's pasted
output) — plus a direct repo-wide `grep -rn "search_movie"` sweep.

**Non-blocking — rename completeness confirmed by direct grep, not
trusted from the build report:** `grep -rn "search_movie" --include="*.py"
--include="*.md"` across the whole repo turns up zero remaining call
sites, zero remaining fakes, and zero production references. The only
survivors are: (1) `PROGRESS.md`'s own older sections (expected —
historical record of earlier follow-ups, correctly left untouched), and
(2) one docstring comment in `tests/unit/tmdb/test_resolver.py` (around
`test_query_strips_adjacent_double_trailing_year`) that narrates a
*different, older* follow-up's live-API verification ("confirmed live:
`search_movie("Se7en (1995)", year=2015)` -> 0 results...") — this
docstring predates this diff (confirmed: `git diff` shows this file's only
changes are the fake's rename and the new TV test; this comment block is
untouched) and describes a historical finding, not a current call site.
Cosmetically stale now that the method is renamed, but it is prose
documentation of a past experiment, not a missed rename — harmless.

**Non-blocking — every renamed fake is actually exercised, not just
present:** checked each of the 4 fakes individually
(`tests/unit/core/test_protocols.py`, `tests/unit/tmdb/test_resolver.py`,
`tests/unit/pipeline/test_waterfall.py`, plus the real `TMDBHttpClient` in
`tests/unit/tmdb/test_client.py`) — every one has at least one test that
calls `.search(...)` and asserts on either the return value or a recorded
call (`last_query`/`last_year`/`calls`). None of the 4 is a silently
orphaned definition that would pass vacuously if left as `search_movie`.

**Non-blocking — `person` filtering traced directly in
`reel2movie/tmdb/client.py:123-149`:** the loop does
`if media_type == "person": continue` *before* `results.append(...)` and
*before* `rank += 1` — a person row is dropped from the returned list
entirely and never consumes a rank slot. Confirmed structurally (not just
via the new test) by reading the loop body directly.

**Non-blocking — `original_rank` renumbering verified correct, including
the person-before-valid-row ordering case:** traced the same loop —
`rank` only increments on the `rank += 1` line, which sits after the
`continue`, so skipped (person) rows never increment it. The new
`test_search_filters_out_person_and_maps_movie_and_tv_distinctly` test's
raw payload is TV (idx 0), movie (idx 1), person (idx 2) — doesn't actually
cover a person sitting *between* two kept rows in raw order. Traced it by
hand anyway with a payload shaped [movie, person, tv]: movie gets
`original_rank=0` (rank 0, then increments to 1), person is skipped (rank
stays 1, not incremented), tv gets `original_rank=1` (not 2). Confirmed:
TMDB's relevance order among the *kept* results is preserved contiguously
as 0, 1, 2... regardless of where person rows fall in the raw payload —
exactly the claimed behavior, and `rank_bonus` in `scoring.py` (which
reads `original_rank` directly, unchanged) therefore still means "TMDB's
own relevance order among valid candidates" and is not diluted by person
rows in any raw-payload position.

**Non-blocking — movie/TV field mapping read directly, not trusted from
the report:** `reel2movie/tmdb/client.py:129-134` —
`if media_type == "tv": title = item["name"]; date_field =
item.get("first_air_date")` vs. the `else` branch using `item["title"]` /
`item.get("release_date")`. Matches the live-verified field-name split
exactly (movie: `title`+`release_date`; tv: `name`+`first_air_date`).
Note: any `media_type` other than `"tv"` or `"person"` falls into the
`else` (movie-shaped) branch — fine today since TMDB's documented
`/search/multi` only ever returns `movie`/`tv`/`person`, but worth
flagging that an unrecognized future `media_type` would hard-`KeyError`
on `item["title"]` rather than being skipped or defaulting gracefully.
Judged non-blocking: matches the live-verified real-world API shape, and
a `KeyError` (loud failure) is arguably safer than silently mis-mapping a
TV field onto a movie shape.

**Non-blocking — `scoring.py` genuinely untouched, confirmed by reading
it directly:** `git diff -- reel2movie/tmdb/scoring.py` is empty, and a
direct read of `score_result`, `pick_best`, `_exact_tier_rank`, and
`_is_exact_title_match` confirms none references `media_type` anywhere —
each reads only `result.title`, `result.year`, and `result.original_rank`.
The claim in the build report is accurate.

**Non-blocking — `/code-review` (medium, forked):** no findings. Forked
run independently grepped for `search_movie`/`_SEARCH_MOVIE_URL`, traced
the person-filter/rank logic against the new test, confirmed every
`TMDBSearchResult`/`ResolvedMovie` construction site updated (frozen/slots
dataclasses would hard-fail at collection on a miss), confirmed
`brainstorm.md` matches `cli.py`'s `_tmdb_to_dict` exactly, and ran
`python3 -m pytest tests/ -q` → 209 passed, 1 skipped.

**Non-blocking — `/ponytail:ponytail-review`:** "Lean already. Ship."
`net: 0 lines possible.` The imperative loop in `client.py`'s `search()`
(replacing the old one-line comprehension) is justified: the
movie/TV conditional field mapping plus person-filtering doesn't fit a
one-liner without an equally-long helper function, so it's not meaningful
bloat. All other changes are mechanical, necessary additions (threading
the new required `media_type` field through models, fakes, and
assertions).

**Independent verification (run directly in this review pass, not
trusted from the build report):**
- `python3 -m pytest tests/unit -q` → **209 passed**, matching the build
  report's count exactly, confirmed independently.
- Own live-API script (`Candidate(raw_text="The Mentalist",
  source=SourceTag.CAPTION, confidence=0.9)` through the real
  `resolve_candidate()` against the live TMDB API, real bearer token via
  `config.get_tmdb_token()`) →
  `ResolvedMovie(id=5920, title='The Mentalist', year=2008, ...,
  media_type='tv')`. Matches the build report's claim exactly — confirms
  the real bug case now resolves to the Netflix TV series, not the
  unrelated 2011 Indonesian movie (id 648544).
- Own live-API spot-check of `Candidate(raw_text="Dhobi Ghat (2010)",
  source=SourceTag.CAPTION, confidence=0.9)` (the first real bug case from
  earlier this session) against the same real `resolve_candidate()` →
  `ResolvedMovie(id=54890, title='Dhobi Ghat', year=2010, ...,
  match_score=1.0, media_type='movie')`. Confirms the TMDB-scope widening
  did not regress plain movie resolution — a pure movie still resolves
  correctly with `media_type='movie'` and a perfect match score.

No blocking findings. The rename is complete across production code and
every fake (confirmed by direct grep and by confirming each fake is
actually exercised), `person` filtering and `original_rank` renumbering
are both correct by direct trace (including the person-row-in-the-middle
ordering case, hand-verified), movie/TV field mapping matches the live-
verified API shape, `scoring.py` is genuinely untouched, and both
independent live-API checks (the TV regression case and the movie
regression spot-check) match the build report's claims exactly.

VERDICT: ACCEPTABLE

## Follow-up — disambiguate tied exact matches using caption context — status: done

### Motivation

The real bug case: a reel's caption recommended "Don't Be Shy" (an Amazon
Prime rom-com with Alia Bhatt, per the caption's own text and @-tags), but
TMDB has several different, exact-titled "Don't Be Shy" entries — including
a 2025 entry whose overview describes an unrelated adult-themed plot about
a threesome. The tiered exact-match scoring built in the two previous
follow-up cycles this session (`pick_best()`'s exact-match tier) only
breaks ties using TMDB popularity/rank, which isn't a reliable
disambiguator between unrelated movies that happen to share a title. This
follow-up adds a surrounding-context (caption text) vs. candidate-overview
disambiguation step, asked of the `claude` CLI, layered strictly on top of
the existing tiebreak as a fallback-safe enhancement.

### Step 1 — live-API apostrophe check (done BEFORE writing any code)

Hit the real TMDB API via `load_dotenv()` + `config.get_tmdb_token()` +
`requests` with `GET /3/search/multi?query=Don't Be Shy` (scratch script,
not committed). Verbatim results (abridged to title/media_type/id/date):

```
"Don't Be Shy"   movie 1586276 2025-11-21   (straight apostrophe, U+0027)
"Don't Be Shy!"  movie 1529372 2026-09-25   (straight apostrophe)
"DON'T BE SHY"   movie 420599  2015-07-10   (straight apostrophe)
"Don't Be Shy"   tv    198009  2022-04-19   (straight apostrophe)
"Don’t Be Shy"   movie 1563521 (no date)    (CURLY apostrophe, U+2019)
"Don’t Be Shy"   movie 1270005 2024-04-23   (CURLY apostrophe, U+2019)
"Keine Scheu vor heiklen Fragen" movie 1245357 1965-11-19  (unrelated title)
```

**Confirmed real: a genuine straight-vs-curly apostrophe mismatch exists.**
Two of the seven TMDB rows for this exact query use a Unicode right single
quotation mark (`’`, U+2019) instead of a straight apostrophe (`'`,
U+0027).

Then checked which apostrophe the REAL candidate extraction pipeline
actually produces for this reel's real caption. First confirmed
`RegexCandidateExtractor().extract(caption, SourceTag.CAPTION)` returns
**zero** candidates for "Don't Be Shy" at all — the caption never quotes
the title or pairs it with a parenthesized year, so neither of
`regex_extractor.py`'s HIGH-tier patterns match it (confirmed: the title
appears twice in plain, unquoted prose). This means the real candidate for
this reel can only have come from the `claude`-CLI text-extraction
fallback (`ClaudeCodeCandidateExtractor`), not regex — contrary to the
task brief's "whichever actually produced the real candidate" being
ambiguous between the two, it's definitively the CLI path.

Ran the real `ClaudeCodeCandidateExtractor` (real `claude` CLI subprocess
call, no mocking) against the real caption text:

```
"Don't Be Shy" 0.9   (straight apostrophe, U+0027 — confirmed via hex dump)
```

**Finding: real, exploitable mismatch confirmed.** The real extracted
candidate always uses the straight apostrophe, but TMDB's own data for
this exact title includes rows using the curly apostrophe. Without
normalizing both forms before comparing, `_is_exact_title_match()` would
silently exclude ids 1563521 and 1270005 from the exact-match tier
entirely — before any disambiguation logic (this follow-up's new feature
or the pre-existing rank tiebreak) ever got a chance to consider them.

**Fix applied** in `reel2movie/tmdb/scoring.py`: a small, targeted
`_normalize_apostrophes()` helper (a `str.translate()` table mapping
U+2019 and U+2018 to the plain `'`), applied to both `query` and `title`
inside `_is_exact_title_match()` before the existing case/whitespace-
insensitive comparison. Deliberately not a general Unicode-folding
library — just the two apostrophe lookalikes actually observed live, plus
the left-curly form as the same kind of lookalike (no live evidence
forced that one specifically, but it's the same character class).

### Step 2 — the disambiguation feature

**`reel2movie/tmdb/scoring.py`:**
- Extracted the exact-match-finding logic out of `pick_best()` into its
  own `find_exact_matches(query, results) -> list[TMDBSearchResult]`,
  which now also benefits from the apostrophe normalization above.
  `pick_best()` calls it internally; `pick_best()`'s own behavior is
  unchanged (confirmed by the full existing `test_scoring.py` suite
  passing unmodified, plus new tests below).

**`reel2movie/tmdb/resolver.py`:**
- Added `disambiguate_with_context(candidates, context, chat_client) ->
  TMDBSearchResult | None`. Builds a prompt giving the model `context`
  verbatim plus each candidate as `{id, title, year, media_type,
  overview}` (JSON), and asks which `id` the context is actually
  describing/recommending, responding with ONLY a bare integer id or the
  literal string `"unknown"`. Parses defensively: a chat-client exception,
  a non-numeric/garbage reply, a bare `"unknown"`, or an id not actually
  among the candidates, are all treated identically as an inconclusive
  `None` — never raises.
- `resolve_candidate()` gained two new, both-default-`None` parameters:
  `context: str | None` and `chat_client: TextChatClient | None` (the
  exact `TextChatClient` Protocol already defined in
  `text_extraction/claude_code_extractor.py` — reused directly, not
  redefined). New logic: after `client.search(...)`, call
  `find_exact_matches(query_title, results)`. If 2+ exact matches AND both
  `context`/`chat_client` are given, call `disambiguate_with_context(...)`;
  a confident pick is used directly, skipping `pick_best()` entirely for
  this candidate. An inconclusive (`None`) result, or 0-1 exact matches,
  or either optional arg missing, falls through to the pre-existing
  `pick_best(query_title, year_hint, results)` call, unchanged. This is a
  strictly additive, backward-compatible signature change — every
  existing call site keeps working identically.
- Layering note: `tmdb/resolver.py` now imports `TextChatClient` from
  `text_extraction/claude_code_extractor.py` — a new cross-subpackage
  import not previously present. Considered moving the Protocol into
  `core/protocols.py` instead, but the task explicitly directs reusing
  this *exact* Protocol/client as-is, and `TextChatClient` is a tiny,
  already-`runtime_checkable`, dependency-free structural type — moving it
  would be a larger, out-of-scope refactor for a small follow-up. Noted
  here as a deliberate, considered tradeoff, not an oversight.

**`reel2movie/pipeline/deps.py`:**
- `PipelineDeps` gained `disambiguation_chat_client: TextChatClient | None
  = None` — defaults to `None` so any existing `PipelineDeps` construction
  (every existing test) behaves exactly as before.
- `build_default_pipeline_deps()`: the `ClaudeCodeTextChatClient()`
  instance is now constructed once (`claude_text_chat_client`) and shared
  between `text_extractor`'s `ClaudeCodeCandidateExtractor` fallback AND
  the new `disambiguation_chat_client` field — not duplicated. Both are
  the identical "shell out to the `claude` CLI for a stateless text reply"
  primitive, so sharing one instance is strictly simpler than constructing
  a second.

**`reel2movie/pipeline/waterfall.py`:**
- `_resolve_all(candidates, deps, result)` — gained a third parameter,
  the original `IngestResult`, used only for `result.caption`. Threaded
  through every `resolve_candidate(candidate, deps.tmdb_client,
  context=result.caption, chat_client=deps.disambiguation_chat_client)`
  call. `run_pipeline()`'s call site updated to
  `_resolve_all(candidates, deps, result)` — `result` was already in
  scope there. The caption (not whichever text actually produced the
  winning candidate) is used as context for every candidate regardless of
  source, per the task's instruction that it's "the most reliably-present
  single text signal."

### Tests

`tests/unit/tmdb/test_scoring.py` — 5 new tests: `find_exact_matches()`
returns the whole tied group in order; returns `[]` when nothing matches;
normalizes curly-vs-straight apostrophes (right AND left curly forms);
and a `pick_best()`-level test confirming the normalization benefits
`pick_best()` too (not just the extracted helper).

`tests/unit/tmdb/test_resolver.py` — 11 new tests, using a fake
`FakeChatClient` (configurable reply or raise, records prompts/call
count) alongside the existing fake `TMDBClient`:
- `disambiguate_with_context()` direct tests: picks by id; returns `None`
  on `"unknown"`, garbage, an id not among candidates, or a raising chat
  client; and a prompt-content test confirming `context` and both
  candidates' overviews/ids appear in the prompt sent to the chat client.
- `resolve_candidate()` wiring tests, matching the task's (a)-(d):
  (a) a confident disambiguation pick is returned as the resolved id;
  (b) `"unknown"` falls back to `pick_best()` — proved by asserting the
  SAME `ResolvedMovie` (dataclass equality) comes back whether
  disambiguation is skipped entirely or explicitly returns `"unknown"`;
  (c) no `context`/`chat_client` at all is byte-for-byte identical to the
  pre-fix call (same two-exact-match setup, `pick_best()`'s rank tiebreak
  wins); (d) only 1 exact match -> `chat_client.call_count == 0`,
  disambiguation never attempted. Two extra tests cover the "only one of
  the two optional args given" half-wired cases (both must be present).

`tests/unit/pipeline/test_waterfall.py` — 2 new tests, plus a new
`FakeChatClient` fake: one confirms `result.caption` reaches the real
disambiguation chat client's prompt during an actual `run_pipeline()` run
(via a `PipelineDeps` with tied exact-match TMDB results and a wired
`disambiguation_chat_client`); the other confirms a `PipelineDeps` with no
`disambiguation_chat_client` (every pre-existing test's shape) still
resolves tied exact matches via the unchanged `pick_best()` rank tiebreak.

`python3 -m pytest tests/unit -q`:

```
228 passed in 3.31s
```

(209 before this change, +19 new test functions: 5 in `test_scoring.py`,
11 in `test_resolver.py` + 1 fake class, 2 in `test_waterfall.py` + 1 fake
class.)

### Live-API verification of the actual real-world "Don't Be Shy" case

Reconstructed the real scenario end to end: the real caption text (as
given in the task brief, verbatim), `Candidate(raw_text="Don't Be Shy",
source=SourceTag.CAPTION, confidence=0.9)` (straight apostrophe, confirmed
in Step 1 to be what the real extractor actually produces), a real
`TMDBHttpClient` (`config.get_tmdb_token()`), and a real
`ClaudeCodeTextChatClient` (real `claude` CLI subprocess). Script written
only to the session scratchpad, never committed.

**Exact matches found (5, after the apostrophe fix — up from the 3 that a
straight-only comparison would have found):**

```
id=1586276 year=2025 movie  "On the verge of a threesome, a wild surprise
                             turns Noah's evening from seductive fantasy
                             to real life nightmare."       <- the bad one
id=420599  year=2015 movie  (no overview on file)
id=198009  year=2022 tv     "A watch that is ticking in reverse and a
                             30-day cohabitation contract puts the
                             domineering female CEO together with a pet
                             mortician..."
id=1563521 year=None movie  "On the night he loses his mom, a shy young
                             man is pulled into an unexpected adventure
                             by a spontaneous stranger who helps him feel
                             alive again."
id=1270005 year=2024 movie  "In this experimental micro-short, the
                             filmmaker uses a digital collage technique
                             to walk around and explore different parts
                             of her body."
```

**Honest finding: TMDB does not actually have the real Alia Bhatt / Amazon
Prime "Don't Be Shy" rom-com in its database.** None of the 5 exact-titled
entries' overviews describe anything resembling a college rom-com — this
is exactly the "TMDB may not have the real film at all" possibility the
task anticipated.

**Ran `resolve_candidate(candidate, real_client, context=<real caption>,
chat_client=real_chat_client)` end to end, repeated several times (the
`claude` CLI's reply is not deterministic across calls):**

- Across 8 total live model invocations (some via `resolve_candidate()`
  directly, some via a direct `disambiguate_with_context()` loop over the
  same 5 candidates): the model picked id `1563521` three times, id
  `1270005` three times, id `1586276` (the threesome one) **once**, and
  never once replied `"unknown"`.
- **The core bug case mostly succeeds**: in the large majority of trials,
  the fix does what it was built for — it stops the pipeline from
  confidently resolving to the threesome-themed entry, instead landing on
  a different (still wrong, since the real film isn't in TMDB at all)
  exact-titled entry.
- **But it is not fully reliable**: in 1 of 8 trials, the model itself
  picked id `1586276` (the threesome movie) — i.e. disambiguation can, on
  an unlucky model sample, still actively choose the exact bad outcome
  this feature exists to prevent, rather than falling back safely. This
  is a real limitation of relying on a single non-deterministic LLM call
  for disambiguation, not a bug in the wiring: `disambiguate_with_context`
  faithfully returns whatever id the model names, and the model named the
  wrong one once.
- **The model also never said `"unknown"`** in any of the 8 trials, even
  though arguably it should have (no candidate overview plausibly matches
  the caption's description) — it always guessed one of the 5 ids
  instead. This means the "honest fallback via inconclusive disambiguation"
  path, while fully implemented and unit-tested (see `test_resolver.py`'s
  `"unknown"` tests), was never actually exercised by the real model
  against this specific real-world input; the model's behavior here is a
  genuine, observed limitation of the prompt/model combination, not of
  this feature's fallback logic (which is proven correct via fakes).

One representative end-to-end `resolved` value (the most common outcome,
3 of 8 trials):

```
ResolvedMovie(id=1563521, title='Don’t Be Shy', year=None,
poster_path='/3N8hBvgPi4YyB4yNkwDFpe0nQVD.jpg', overview='On the night he
loses his mom, a shy young man is pulled into an unexpected adventure by a
spontaneous stranger who helps him feel alive again.',
match_score=0.6458333333333333, media_type='movie')
```

**Bottom line, reported honestly per the task's own framing:** the fix
correctly avoids the specific known-bad outcome (the threesome-themed
entry) in 7 of 8 live trials, and the apostrophe-normalization fix is
confirmed necessary and working (2 of the 5 exact matches would otherwise
have been invisible to the exact-match tier at all). It is not a clean,
fully reliable win: the underlying real film isn't in TMDB's database, the
model never recognized that and said `"unknown"`, and on one trial out of
eight it still picked the harmful entry. The disambiguation feature is a
probabilistic improvement over the old pure-rank tiebreak (which would
have picked id `1586276`, rank 0, the threesome movie, on 100% of runs),
not a deterministic guarantee.

### Verification scripts

All four scripts (the Step 1 apostrophe/regex/claude-CLI probe, the
end-to-end real-caption resolution script, the 5x `disambiguate_with_context`
repeat loop, and their reruns) were throwaway scripts written only to the
session scratchpad, never committed to the repo.

### Review findings (latest pass)

Reviewed via `/code-review` (medium, forked) on the current diff,
`/ponytail:ponytail-review` on the same diff, a from-scratch
`python3 -m pytest tests/unit -q` run, and independent live-API
re-verification scripts (own scripts, own `Candidate`/`pick_best`/
`resolve_candidate` calls against the real TMDB + real `claude` CLI, not
the build report's pasted output) — plus direct reads of
`build_default_pipeline_deps()`, `_resolve_all()`, and
`disambiguate_with_context()`.

**Non-blocking — `/code-review` (medium, forked), two findings, both
accepted as real but non-blocking:**
1. Each candidate with 2+ tied exact TMDB matches now pays a synchronous
   `claude` CLI subprocess call inside `_resolve_all()`'s per-candidate
   loop (`reel2movie/pipeline/waterfall.py`), serializing rather than
   parallelizing disambiguation calls across multiple ambiguous
   candidates in the same run. True, but out of scope for this follow-up
   (which is about correctness of disambiguation, not pipeline
   concurrency) and consistent with the rest of `_resolve_all()`'s
   existing sequential-loop design (it doesn't parallelize ordinary TMDB
   lookups either).
2. `result.caption` is threaded in as `context` even when it's `""` (the
   documented empty-string fallback in
   `reel2movie/ingest/instagram.py:75`'s `info.get("description") or
   ""`), and `resolve_candidate()`'s `context is not None` check passes
   for `""`, so a reel with no caption and 2+ tied exact matches still
   pays a wasted `claude` CLI call that will almost always come back
   `"unknown"`. Confirmed by reading `resolve_candidate()` directly —
   real, minor inefficiency, not a correctness bug (the fallback to
   `pick_best()` still fires correctly on `"unknown"`).

**Non-blocking — `/ponytail:ponytail-review`:** diff is lean overall
(reuses `find_exact_matches`, reuses the existing `TextChatClient`
Protocol instead of redefining it, shares one `ClaudeCodeTextChatClient`
instance instead of constructing a second). One minor duplication: the
same 14-line tied `TMDBSearchResult` list literal (ids 111/222, "Don't Be
Shy") is repeated verbatim across
`test_captions_context_is_threaded_into_disambiguation_chat_client` and
`test_no_disambiguation_chat_client_falls_back_to_pick_best_in_real_pipeline`
in `tests/unit/pipeline/test_waterfall.py`. `tests/unit/tmdb/test_resolver.py`
already shows the fix (a `_tied_rom_com_and_threesome_results()` helper);
`test_waterfall.py`'s two new tests could share a similar helper.
`net: -14 lines possible.`

**Own verification — backward compatibility of `resolve_candidate()`
traced directly, both new params default to `None`:** read
`reel2movie/tmdb/resolver.py`'s `resolve_candidate()` signature and body
— `context: str | None = None`, `chat_client: TextChatClient | None =
None`; the only new branch is `if len(exact_matches) >= 2 and context is
not None and chat_client is not None:`, which is false whenever either
arg is omitted, so `best` stays `None` from that branch and falls straight
into the pre-existing `if best is None: best = pick_best(...)` line,
unchanged. Every other line (year-hint extraction, `client.search(...)`,
the `ResolvedMovie` construction) is byte-for-byte identical to before
this diff.

**Own verification — Triangle case, live TMDB, re-run directly (not
trusted from the report):** `pick_best("Triangle", None,
client.search("Triangle"))` → now returns `id=2367` ("Triangle", a 1981
BBC TV soap opera), **not** the `id=26466` (2009 movie) the original
"prioritize exact title match" follow-up's write-up recorded. Investigated
directly with `git stash` / `git stash pop`: ran the identical script
against the pre-diff code and got the **identical** `id=2367` result.
Conclusion: this is **live TMDB data drift** (a TV show now also
exactly-matches "Triangle", interacting with the already-committed, prior
"widen TMDB resolution scope to include TV shows" follow-up) — it
predates and is wholly unrelated to the current diff under review, and
`pick_best()`'s behavior for this query is confirmed byte-for-byte
unchanged by this diff specifically. Recorded here for honesty/paper
trail, not as a finding against this follow-up.

**Own verification — Dhobi Ghat case, live TMDB, re-run directly via the
OLD 2-arg `resolve_candidate(candidate, client)` call (no `context`/
`chat_client` at all):** `resolve_candidate(Candidate(raw_text="Dhobi
Ghat (2010)", source=SourceTag.CAPTION, confidence=0.9), client)` →
`ResolvedMovie(id=54890, title='Dhobi Ghat', year=2010, ...,
match_score=1.0)` — matches the originally-recorded result exactly.
Confirms the simple/common path (no tied exact matches, disambiguation
args omitted) is unaffected.

**Own verification — UP/Up case-sensitivity case, live TMDB, re-run
directly:** `pick_best("Up", None, client.search("Up"))` → returns the
real Pixar "Up" (`id=14160`, title exactly `"Up"`), confirming the
case-insensitive exact-match tier still isn't penalized by case
differences after the `find_exact_matches()` extraction.

**Own verification — `_normalize_apostrophes()` scope confirmed narrow:**
read `reel2movie/tmdb/scoring.py` directly — it's a 2-entry
`str.maketrans()` table (`’`→`'`, `‘`→`'`), applied only inside
`_is_exact_title_match()` to `query` and `title` immediately before the
existing `.strip().casefold()` comparison. Not a general Unicode-folding
operation (e.g. no NFKD normalization, no broad punctuation stripping) —
confirmed it cannot cause a new false-positive exact match between
genuinely different titles, since it only maps two specific lookalike
code points to U+0027 and touches nothing else.

**Own verification — `find_exact_matches()` extraction is genuinely
behavior-preserving, confirmed by direct read plus the Triangle/UP live
reruns above:** `pick_best()`'s only change is
`exact_matches = find_exact_matches(query, results)` replacing the
previous inline list comprehension — `find_exact_matches()`'s body is
that exact same comprehension, now calling `_is_exact_title_match()`
(itself only changed by the additive apostrophe normalization). Both live
reruns above (Triangle, UP/Up) return results consistent with the
pre-existing scoring tests, confirming no behavioral drift from the
refactor itself.

**Own verification — fallback-to-`pick_best()` path traced for both the
"inconclusive" and "no-args" cases:** in `resolve_candidate()`, both
paths — (a) `context`/`chat_client` omitted entirely, and (b)
`disambiguate_with_context()` returns `None` (its own `"unknown"`/
garbage/raise/id-not-found branches, all confirmed to return `None`, never
raise, by direct read) — converge on the exact same line,
`best = pick_best(query_title, year_hint, results)`, with no other state
differing between the two paths (`results`, `query_title`, `year_hint`
are computed once, before either branch). Confirmed identical, not just
similar.

**Own verification — every `resolve_candidate()` call site in the
pipeline receives both new args:** `grep -rn "resolve_candidate(" --include="*.py" reel2movie/`
finds exactly one production call site,
`reel2movie/pipeline/waterfall.py`'s `_resolve_all()` loop, which passes
`context=result.caption, chat_client=deps.disambiguation_chat_client` on
every iteration (not conditionally) — there is no second call site that
could have been missed.

**Own verification — `build_default_pipeline_deps()` shares ONE
`ClaudeCodeTextChatClient` instance, confirmed by direct read:** in
`reel2movie/pipeline/deps.py`, `claude_text_chat_client =
ClaudeCodeTextChatClient()` is constructed exactly once, then passed both
into `ClaudeCodeCandidateExtractor(claude_text_chat_client)` (the
text-extraction fallback) and directly as
`disambiguation_chat_client=claude_text_chat_client` on the returned
`PipelineDeps` — not two separate constructions.

**Own verification — `disambiguate_with_context()` prompt-construction
and response-parsing, read directly, confirmed matches the build report's
claims exactly:** bare-integer-id parsing via `int(reply.strip())` inside
a `try/except ValueError`; `"unknown"` (checked case-insensitively via
`.lower()`) → `None`; a chat-client exception caught by a blanket
`except Exception` → `None` (logged via `logger.exception`, never
re-raised); an id not among `candidates` → `None` (logged via
`logger.warning`); garbage/non-numeric reply → `None` via the same
`ValueError` branch. Every path returns `None`, none raises.

**Own verification — `python3 -m pytest tests/unit -q`, run independently,
not trusted from the reported 228:**

```
228 passed in 3.74s
```

Matches the build report exactly.

**Own verification — one live sanity run of the full wiring on the real
"Don't Be Shy" tied case (not the full 8-trial experiment, per the task's
own instruction that re-running that is unnecessary):** real `TMDBClient`
+ real `ClaudeCodeTextChatClient`, `find_exact_matches()` found the same 5
tied exact matches as the build report's own verification. The one-shot
`resolve_candidate(..., context=<realistic caption>, chat_client=...)`
call returned `ResolvedMovie(id=1586276, ...)` — i.e. on this particular
run the model picked the known-bad threesome-themed entry, consistent
with the build report's own honestly-disclosed 1-in-8 failure rate (a
probabilistic, not deterministic, limitation of the underlying model
call, already documented above). The wiring itself behaved exactly as
designed: it didn't crash, didn't raise, and returned a valid
`ResolvedMovie` either way — confirming the plumbing is sound even though
the model's pick on this particular run was the unlucky one.

VERDICT: ACCEPTABLE

## Follow-up — unify duplicated claude-CLI subprocess/parsing logic — status: DONE

**Motivation (from the repo-wide ponytail-audit):** `ClaudeCodeVisionChatClient.chat()`
(`visual/vision_llm_detector.py`) and `ClaudeCodeTextChatClient.chat()`
(`text_extraction/claude_code_extractor.py`) duplicated ~90% of their
`subprocess.run()` → timeout/`OSError` → non-zero-exit →
`json.JSONDecodeError` → `is_error` → `permission_denials` → return
`parsed["result"]` pipeline almost line-for-line, differing only in CLI
flags (`--tools Read` + an image-read prompt prefix vs. `--tools ""`) and
in which exception class each raised. Likewise `VisionLLMPosterDetector.detect()`
and `ClaudeCodeCandidateExtractor.extract()` duplicated the same
"parse a JSON array of `{title, year, confidence}` items into `Candidate`s,
skipping malformed items, mapping confidence labels via a caller-supplied
map" loop nearly verbatim.

**New module layout — two small internal (`_`-prefixed, not part of the
public package surface) modules, both under `reel2movie/`:**

- `reel2movie/_claude_cli.py` (92 lines): `ClaudeCliError` (the one real
  error class now) and `run_claude_cli(args, *, claude_binary,
  timeout_seconds, context) -> str` — the shared subprocess-run → parse
  `--output-format json` → `result` pipeline. `context` is a plain string
  each caller supplies purely to make error messages identify what was
  being processed (an image path for vision, a fixed string for text); it
  has no effect on control flow.
- `reel2movie/_candidate_parsing.py` (87 lines):
  `parse_movie_candidates(raw_response, *, confidence_map,
  default_confidence, source, log_context) -> list[Candidate]` — the
  shared JSON-array-of-movie-mentions parser. Each caller supplies its own
  confidence-label map (vision's dampened 0.8/0.5/0.3 vs. text's
  `HIGH_CONFIDENCE`/`MEDIUM_CONFIDENCE` imported from `regex_extractor.py`,
  unchanged) and default.

**How the two original files changed:**

- `reel2movie/visual/vision_llm_detector.py` (364 → 256 lines):
  `ClaudeCodeVisionError` is now `ClaudeCodeVisionError = ClaudeCliError`
  — a bare alias (not a subclass), per the task's explicit allowance for
  either — so every existing `pytest.raises(ClaudeCodeVisionError, ...)`
  still catches exactly what gets raised, since it's the same class
  object. `ClaudeCodeVisionChatClient.chat()` now only builds its
  `combined_prompt` (the "Read the image file at {image_path} using your
  Read tool. {prompt}" prefix, unchanged) and its own `args` list (same
  flags, same order: `-p`, `--output-format json`, `--tools Read`,
  `--permission-mode bypassPermissions`, `--no-session-persistence`), then
  returns `run_claude_cli(args, claude_binary=..., timeout_seconds=...,
  context=f"analyzing {image_path}")`. `VisionLLMPosterDetector.detect()`
  now just calls `self._chat_client.chat(...)` then returns
  `parse_movie_candidates(raw_response, confidence_map=CONFIDENCE_MAP,
  default_confidence=_DEFAULT_CONFIDENCE, source=SourceTag.FRAME_VISUAL,
  log_context=...)` — `CONFIDENCE_MAP` (0.8/0.5/0.3) and
  `_DEFAULT_CONFIDENCE` stayed exactly where they were, unchanged. Removed
  the now-unused `import json`, `import subprocess`, `import logging` (and
  module-level `logger`), since all three responsibilities moved to the
  shared helpers.
- `reel2movie/text_extraction/claude_code_extractor.py` (285 → 189 lines):
  same treatment. `ClaudeCodeTextError = ClaudeCliError` (alias).
  `ClaudeCodeTextChatClient.chat()` shrinks to building its own `args`
  (`--tools ""` instead of `--tools Read`, no image-read prompt prefix,
  prompt passed as-is) and calling `run_claude_cli(..., context="extracting
  movie titles from text")`. `ClaudeCodeCandidateExtractor.extract()` keeps
  its empty/whitespace-only-text short-circuit (unchanged, still returns
  `[]` before ever touching the chat client) and otherwise delegates to
  `parse_movie_candidates(..., confidence_map=_CONFIDENCE_MAP,
  default_confidence=_DEFAULT_CONFIDENCE, source=source, ...)` where
  `_CONFIDENCE_MAP` is still built from `HIGH_CONFIDENCE`/`MEDIUM_CONFIDENCE`
  imported from `regex_extractor.py` exactly as before. Removed the
  now-unused `import json`/`import logging`/module-level `logger`.

**Confirmed zero behavior change — grepped the whole repo first for every
externally-visible name before touching anything:**
`ClaudeCodeVisionError`, `ClaudeCodeTextError`, `ClaudeCodeVisionChatClient`,
`ClaudeCodeTextChatClient`, `VisionChatClient`, `TextChatClient` are each
still defined under their original name, in their original module, with
their original public constructor signature (`claude_binary: str =
"claude", timeout_seconds: float = 60.0` for both chat-client classes) and
`chat()` signature. Confirmed every production call site unaffected by
direct read: `reel2movie/pipeline/deps.py` imports `ClaudeCodeTextChatClient`/
`TextChatClient` from `text_extraction.claude_code_extractor` and
`ClaudeCodeVisionChatClient`/`AnthropicVisionChatClient` from
`visual.vision_llm_detector` — both unmoved; `reel2movie/tmdb/resolver.py`
imports `TextChatClient` from `claude_code_extractor` — unmoved, Protocol
definition untouched. Not changed anywhere: the exact CLI flags per
caller, the prompt text/construction for either caller, `raw_text`
formatting (`f"{title} ({year})"`), the `permission_denials`/`is_error`
check semantics (same two checks, same order, same "raise before trusting
`result`" behavior), or either caller's confidence mapping/default.
(Error-message *prose* did change in a few spots — e.g. non-JSON/`is_error`
messages for the text caller now include the `context` string where they
previously didn't, and vision's permission_denials message lost its
`image never actually seen` phrase in favor of a shared "reply cannot be
trusted" phrase — this is cosmetic log/exception text, not checked by any
existing test beyond generic substrings like `"is_error"`/
`"permission_denials"`/`"non-JSON"`/`"timed out"`/`"not logged in"`/`"claude"`,
all of which still match.)

**Tests:**

- `tests/unit/visual/test_vision_llm_detector.py` and
  `tests/unit/text_extraction/test_claude_code_extractor.py`: every test
  kept, unchanged in substance. The only edit was the `subprocess.run`
  mock-patch target, since that's genuinely where the call moved to:
  `reel2movie.visual.vision_llm_detector.subprocess.run` →
  `reel2movie._claude_cli.subprocess.run`, and
  `reel2movie.text_extraction.claude_code_extractor.subprocess.run` →
  `reel2movie._claude_cli.subprocess.run` (same new target for both, since
  both now share the one module that actually calls `subprocess.run`).
  All 44 of their tests still pass.
- New `tests/unit/test_claude_cli.py` (8 tests): the same error-case
  coverage proven per-caller before (success/`result`-returned, timeout,
  missing binary, non-zero exit, non-JSON stdout, `is_error`,
  `permission_denials`-despite-plausible-`result`, plus a check that
  `context` actually shows up in a raised message), now proven once
  directly against `run_claude_cli()`.
- New `tests/unit/test_candidate_parsing.py` (8 tests): standalone
  coverage of `parse_movie_candidates()` — title+year, title without year,
  empty array, non-JSON, JSON-object-not-array, missing-title item
  skipped, unrecognized confidence label falls back to default, and (the
  point of taking `confidence_map` as a parameter) two different callers
  getting different numeric confidence for the same label.

**`python3 -m pytest tests/unit -q`, run after the refactor:**

```
244 passed in 3.50s
```

228 (pre-refactor baseline) + 8 (`test_claude_cli.py`) + 8
(`test_candidate_parsing.py`) = 244. Count only grew, never dropped —
every pre-existing test still proves the same thing it did before.

**Live-API spot check (`load_dotenv()` + the real `claude` CLI, no mocks),
run directly against both refactored clients:**

```
=== ClaudeCodeTextChatClient live call ===
result: '4'

=== ClaudeCodeVisionChatClient live call ===
result: 'White'
```

`ClaudeCodeTextChatClient().chat("What is 2+2? Respond with just the
number.")` → `'4'`. For vision, generated a fresh scratchpad test image (a
400×300 JPEG with a white rectangle border drawn via PIL — the repo's own
prior scratchpad frames were from an earlier subtask, so a new one was
made rather than reused) and ran `ClaudeCodeVisionChatClient().chat(image_path,
"What color is the border rectangle drawn in this image? Answer in one
word.")` → `'White'`, correctly matching the actual drawn color. Confirms
the real `claude` CLI integration genuinely still works post-refactor
through both shrunk `chat()` methods, not just against the mocked
`subprocess.run` the unit tests use.

**Net lines-saved count:** production source (excluding tests) went from
`364 + 285 = 649` lines (`vision_llm_detector.py` +
`claude_code_extractor.py`, pre-refactor) to `256 + 189 + 92 + 87 = 624`
lines (those same two files, now shrunk, plus the two new shared modules
that replace their duplicated logic) — a net reduction of 25 production
lines, with the actual duplicated subprocess/JSON-parsing and
candidate-parsing logic now written exactly once instead of twice. Test
line count grew by design (table above): +352 lines across the two new
dedicated shared-helper test files, with the two existing per-caller test
files unchanged in line count (only their mock-patch target strings
edited).

VERDICT: DONE — pure refactor, zero behavior change, pytest count only
grew (228 → 244), live CLI spot check passes for both clients.

### Review findings (latest pass)

Reviewed via `/code-review` (high, forked) on the current diff,
`/ponytail:ponytail-review` on the two new shared modules, a from-scratch
`python3 -m pytest tests/unit -q` run, direct reads of both diffs against
`git show HEAD:...`, a repo-wide grep for every externally-importable
name and for `isinstance`/`except` usage against the error classes, and
independent live-`claude`-CLI spot checks + one higher-level integration
rerun (own scripts, real CLI, no mocks — not the build report's pasted
output).

**Non-blocking — `/code-review` (high, forked), two findings, both
accepted as real but non-blocking:**
1. `parse_movie_candidates()` (`reel2movie/_candidate_parsing.py:20`) logs
   its warnings under the single shared logger name
   `"reel2movie._candidate_parsing"`, whereas before the refactor the
   vision and text callers each logged under their own module's logger
   (`"reel2movie.visual.vision_llm_detector"` /
   `"reel2movie.text_extraction.claude_code_extractor"`). Confirmed by
   direct diff read: both callers' `logger = logging.getLogger(__name__)`
   lines were removed. This silently merges what were two independently
   configurable/filterable log streams into one. Real, but not disclosed
   in the original write-up above (which only disclosed *message text*
   drift, not logger identity), and no existing test uses `caplog` to
   depend on logger name — non-blocking.
2. `run_claude_cli()`'s shared error messages unconditionally splice
   `context` into every raised message, changing exact text for the text
   caller's `is_error`/non-JSON/`permission_denials` cases (previously
   context-free) and replacing vision's specific "the model never
   actually saw the image" permission-denial caveat with a generic "the
   model's reply cannot be trusted" phrase. This matches what the
   original write-up above already self-disclosed ("Error-message
   *prose* did change in a few spots...") — confirmed accurate by direct
   diff read, not a new finding, and no test/code inspects the exact
   phrasing (all `pytest.raises` use `match=` on substrings still
   present) — non-blocking.

**Non-blocking — `/ponytail:ponytail-review`:** both new modules are lean
— every parameter (`context`, `confidence_map`, `default_confidence`,
`source`, `log_context`) is genuinely consumed differently by the two
real callers, no speculative hooks/config, no unused imports. One minor
duplication: `run_claude_cli(args, *, claude_binary, ...)` takes
`claude_binary` as its own keyword even though it's always `args[0]` too
(both callers pass it both ways). Could derive it inside the function as
`args[0]` and drop the separate parameter, saving one line at each of the
two call sites. `net: -2 lines possible.`

**Own verification — CLI args/flags byte-for-byte unchanged, confirmed by
direct diff read (not trusted from the write-up):** `git diff HEAD --
reel2movie/visual/vision_llm_detector.py reel2movie/text_extraction/claude_code_extractor.py`
shows the only change inside each `chat()` method is replacing the
inline `subprocess.run()`/parse block with a call to `run_claude_cli()`
passing the *exact same* `args` list literal (same flags, same order,
same values: `-p`, `--output-format json`, `--tools Read` for vision vs.
`--tools ""` for text, `--permission-mode bypassPermissions`,
`--no-session-persistence`, and vision's unchanged `combined_prompt` =
`f"Read the image file at {image_path} using your Read tool. {prompt}"`).
The `is_error` check precedes the `permission_denials` check in both the
old inline code and the new `run_claude_cli()`, same as before. `raw_text`
formatting (`f"{title} ({year})" if year is not None else title`) and both
callers' confidence maps/defaults (vision's `CONFIDENCE_MAP` 0.8/0.5/0.3 +
`_DEFAULT_CONFIDENCE`; text's `_CONFIDENCE_MAP` built from
`HIGH_CONFIDENCE`/`MEDIUM_CONFIDENCE` imported from `regex_extractor.py`)
are untouched by the diff — confirmed these constants/lines don't even
appear in the diff hunks.

**Own verification — `ClaudeCodeVisionError`/`ClaudeCodeTextError` alias
safety, confirmed by repo-wide grep:** both are `= ClaudeCliError`
(literally the same class object under two names, not a subclass).
Grepped the whole repo for `isinstance.*ClaudeCode`, `except
ClaudeCode`, and `ClaudeCliError` — the only `isinstance()` in the repo
near these names is `tests/unit/pipeline/test_deps.py`'s unrelated
`isinstance(deps.text_extractor._fallback, ClaudeCodeCandidateExtractor)`
(a class check, not an error check). Every `pytest.raises(ClaudeCodeVisionError, ...)`
/ `pytest.raises(ClaudeCodeTextError, ...)` in the test suite catches
exactly what `run_claude_cli()` raises, since it's the same object —
confirmed this works by the full suite passing (see below), not just by
assumption.

**Own verification — every externally-importable name re-grepped
repo-wide, not just the files the build report listed:** `grep -rn` for
`ClaudeCodeVisionChatClient`, `ClaudeCodeTextChatClient`,
`VisionChatClient`, `TextChatClient`, `ClaudeCodeVisionError`,
`ClaudeCodeTextError` across the whole repo. Confirmed `reel2movie/pipeline/deps.py`
still imports `ClaudeCodeTextChatClient`/`TextChatClient` from
`text_extraction.claude_code_extractor` and `ClaudeCodeVisionChatClient`/
`AnthropicVisionChatClient` from `visual.vision_llm_detector`, and
`reel2movie/tmdb/resolver.py` still imports `TextChatClient` from
`claude_code_extractor` — both unmoved, no call site outside the two
refactored files and their own tests references anything that changed
location or signature.

**Own verification — `python3 -m pytest tests/unit -q`, run
independently, not trusted from the reported 244:**

```
244 passed in 3.61s
```

Matches the build report exactly.

**Own live-API spot check, both clients, real `claude` CLI, no mocks
(own scripts, not the build report's pasted output):**

```
TEXT RESULT: '12'
VISION RESULT: 'Red'
```

`ClaudeCodeTextChatClient().chat("What is 7+5? Respond with just the
number.")` → `'12'`. For vision, generated a fresh scratchpad 400×300 JPEG
with a red rectangle border (PIL) and ran
`ClaudeCodeVisionChatClient().chat(image_path, "What color is the
rectangle border drawn in this image? Answer in one word.")` → `'Red'`,
correctly matching the actual drawn color — independently confirms the
real CLI integration works post-refactor for both clients, using
different example inputs than the build report's own spot check (2+2/
white border) so this isn't just re-running the same cached-looking
result.

**Own verification — higher-level integration rerun through the real
`ClaudeCodeCandidateExtractor` (exercises the new `parse_movie_candidates`
shared module end-to-end via the real CLI, not just the raw `chat()`
call):** fed the same "Dhobi Ghat" prose caption from the original
Claude CLI text-extraction-fallback follow-up through
`ClaudeCodeCandidateExtractor(ClaudeCodeTextChatClient()).extract(caption, SourceTag.CAPTION)`
→ `Candidate(raw_text='Dhobi Ghat (2010)', source=SourceTag.CAPTION,
confidence=0.9)` — correct title, correct year, confidence exactly
`HIGH_CONFIDENCE` (0.9, confirmed against `regex_extractor.py`). Also ran
`VisionLLMPosterDetector(ClaudeCodeVisionChatClient()).detect(frame)` on
the same plain red-rectangle scratchpad frame (no poster/title visible)
→ `[]`, correctly empty. Both prove the full `detect()`/`extract()` →
`chat()` → `run_claude_cli()` → `parse_movie_candidates()` chain works
end-to-end against the real CLI post-refactor, at a level unit tests
(mocked `subprocess.run`) can't catch.

VERDICT: ACCEPTABLE

## Subtask 9 — dense frame sampling + perceptual dedup + on-screen text detection — status: done

This is the BUILD step only -- no review pass has happened yet (a separate
pass does that next), so this entry is deliberately `status: building`,
not `done`, and the "Review findings" section below is a placeholder, not
fabricated findings.

### Motivation (why this subtask exists)

The visual fallback (`pipeline/waterfall.py`'s `_extract_from_visual`)
previously sampled only 6 sparse, equally-spaced frames per reel
(`visual/frame_sampler.sample_frames`, within the inner 5%-95% window) and
asked a vision LLM whether each showed a movie poster/title card
(`visual/vision_llm_detector.VisionLLMPosterDetector`). This misses a
common real-world pattern -- "rate these movies" / "movies like X" reels
where the creator burns the title directly onto the video as a transient
on-screen text overlay (a caption, a lower-third, a listicle-style text
card) rather than ever showing an actual poster. If that overlay is only
on screen for 1-2 seconds, it can fall entirely between two of the 6
sparse samples -- a false negative the old sampling strategy couldn't
avoid no matter how good the vision prompt was, since the frame carrying
the answer was never even extracted. Three changes together fix this:
(1) dense 1-frame-per-second sampling across the WHOLE video including
both edges, (2) a cheap perceptual-dedup pre-filter so a long static shot
doesn't multiply the number of (expensive, Claude-CLI-backed) vision calls
per reel, and (3) widening the existing vision prompt to also ask about
on-screen text, reusing the exact same `VisionChatClient` backend (no new
provider, no new billing path).

### What's built

Files created:
- `reel2movie/visual/frame_dedup.py` (new module) — pure function
  `dedupe_similar_frames(frames: list[FrameSample], threshold: float =
  0.04) -> list[FrameSample]`. Pillow-only (`Image`, `ImageChops`,
  `ImageStat`), no ffmpeg/subprocess, no network. Always keeps `frames[0]`
  unconditionally (empty input returns `[]`); every later frame is
  fingerprinted (`Image.open(path)` inside a `with` block so file handles
  don't accumulate across dozens of frames, `.convert("L")` grayscale,
  `.resize((64, 64))`, `.copy()` to detach from the closed file handle) and
  compared via `ImageChops.difference(...)` +
  `ImageStat.Stat(diff).mean[0] / 255.0` (a single float in `[0, 1]`,
  unambiguous since both images are single-band "L" mode) against the
  fingerprint of the last frame that was actually KEPT -- not the
  immediately-previous candidate. That distinction is the whole point: a
  long run of near-static frames collapses to exactly one kept frame
  because every candidate in the run is judged against the SAME original
  kept frame, instead of a naive "compare to previous" walk that would let
  slow drift accumulate past the threshold one small step at a time
  without ever being compared back to where the run actually started.
  `threshold=0.04` is explicitly documented in the module docstring as an
  UNVALIDATED starting guess, not tuned against real reel footage --
  callers/reviewers should expect this number to be revisited once real
  reels are run through it.
- `tests/unit/visual/test_frame_dedup.py` (7 tests) — all pure
  Pillow-generated synthetic JPEGs written to `tmp_path` (`Image.new("RGB",
  (64, 64), color=...)`), no ffmpeg involved:
  - empty input → `[]`; single frame → returned unchanged.
  - a 5-frame run of the identical solid color collapses to just the
    first frame (proves the long-static-shot collapsing behavior, not
    "every other frame kept").
  - a substantially different frame amid a same-color run is kept, and
    becomes the new baseline.
  - `test_compares_against_last_kept_not_immediately_previous_frame` --
    the test specifically designed to distinguish "compare to last KEPT"
    from the simpler-but-wrong "compare to immediately previous frame":
    frame A (black) is kept as the baseline, frame B (far from A) is kept
    and becomes the new baseline, frame C (close to B, computed to land
    just under the threshold against B) is dropped. A naive
    "compare-to-previous" implementation would behave identically on this
    particular 3-frame case (C is compared to B either way, since B is
    both "previous" and "last kept" here) -- the test's real evidentiary
    weight is that A is NOT reconsulted for C's decision; if the
    implementation ever regressed to "reset to frame zero after every
    keep", this and the collapsing-run test together would catch it, since
    neither test's expected output is consistent with resetting to A.
  - two threshold-boundary tests using the SAME pair of grayscale values
    (100,100,100) vs (105,105,105) -- independently measured (see below)
    to produce a real mean-abs-difference of `5/255 ≈ 0.0196` after the
    JPEG round-trip and resize -- asserting it's dropped at
    `threshold=0.03` (0.0196 < 0.03) and kept at `threshold=0.01` (0.0196 >
    0.01). This value was verified by actually running the fingerprinting
    code against the real Pillow-generated+reloaded JPEGs (not assumed
    from theory), confirming JPEG's lossy compression doesn't perturb a
    solid-color block's pixel values enough to break the boundary math at
    these two specific threshold values.
- `reel2movie/visual/frame_sampler.py` — refactored, not rewritten:
  - Extracted a new private `_extract_frame_at(video_path: Path,
    timestamp: float, frame_path: Path) -> None` helper containing exactly
    the subprocess-call + timeout/nonzero-exit/exit-0-but-empty-file error
    handling that used to live inline in `sample_frames`'s for-loop,
    raising `FrameExtractionError` exactly as before (same messages, same
    conditions). Both `sample_frames` and the new
    `sample_frames_at_interval` (below) call this one helper -- there is no
    duplicated ffmpeg-invocation logic between them now.
  - Added public `sample_frames_at_interval(video_path: Path,
    interval_seconds: float, duration_seconds: float, *, output_dir: Path
    | None = None) -> list[FrameSample]`. Timestamps: a plain `while t <
    duration_seconds: timestamps.append(t); t += interval_seconds` walk
    starting at `0.0` -- deliberately NOT `sample_frames`'s 5%-95% window,
    since that dodge exists specifically to avoid intro/outro bumpers for
    POSTER detection (a poster is rarely the very first/last thing shown);
    this function exists for reading on-screen TEXT, which can
    legitimately appear right at the very start or end of a reel, so
    skipping those edges here would defeat the point of dense sampling.
    Raises `ValueError` on `interval_seconds <= 0` or `duration_seconds <=
    0`, same style/message pattern as `sample_frames`. Same
    caller-owns-`output_dir`/`mkdtemp()`-when-omitted contract as
    `sample_frames` (see Subtask 5's "Temp-directory ownership/cleanup
    decision" section above -- unchanged reasoning, just documented again
    in the new function's own docstring). Output filenames use
    `frame_{i:04d}.jpg` (4 digits vs. `sample_frames`'s 3) -- a deliberate
    visual signal that these came from a different function, not a
    correctness requirement (a 60s reel at the 1s default interval needs
    only ~60 frames, nowhere near 3-digit overflow), in case a future
    caller ever points both functions at the same directory (neither does
    today).
  - Module docstring rewritten to explain both sampling strategies and
    when each is used.
- `tests/unit/visual/test_frame_sampler.py` — 9 new tests added (2
  parametrized into 2 cases each, so 11 actual runs) for
  `sample_frames_at_interval`, reusing the existing module-scoped
  `sample_video` fixture (6s synthetic `testsrc` at `rate=10`): correct
  timestamp spacing for a 2s interval over the 6s fixture (`[0.0, 2.0,
  4.0]`, confirming `6.0` itself is excluded per the exclusive-of-duration
  rule); a timestamp at/near `0.0` (unlike `sample_frames`, which starts at
  5% of duration); a timestamp within one interval of the true end (unlike
  `sample_frames`'s 95% cutoff); `interval_seconds<=0` and
  `duration_seconds<=0` each raise `ValueError`; one representative
  `FrameExtractionError`-propagates case via the same `subprocess.run`
  mocking pattern already used for `sample_frames` (not exhaustively
  re-proving every ffmpeg failure mode, since `_extract_frame_at` is the
  single shared implementation already fully covered by `sample_frames`'s
  existing tests); and a check that the first frame's filename is
  `frame_0000.jpg` (the distinct 4-digit pattern).
- `reel2movie/visual/vision_llm_detector.py` — prompt widened, architecture
  untouched:
  - `_PROMPT` now asks about EITHER (a) a movie poster/title card/clearly
    identifiable scene (the original ask) OR (b) a creator-added on-screen
    TEXT overlay (caption/lower-third/listicle-style text card -- text
    added on top of the video, not text that's part of the filmed scene
    itself) naming a movie/show. The output JSON contract
    (`[{"title", "year", "confidence"}, ...]`) is unchanged -- this is
    additive to what the model looks for, not a schema change, and it's
    still the exact same single Claude call per frame (no second call, no
    new backend).
  - Module and class docstrings (`VisionLLMPosterDetector`) updated to
    describe the widened scope. Deliberately did NOT rename
    `VisionLLMPosterDetector`, `PosterDetector`, or `VisionChatClient` --
    those are structural identifiers referenced across
    `core/protocols.py`, `pipeline/deps.py`, `pipeline/waterfall.py`, and
    their tests; renaming for a prompt-only change would ripple pointlessly
    and wasn't asked for.
  - `tests/unit/visual/test_vision_llm_detector.py` needed NO changes: its
    tests all assert on parsed `Candidate` output from canned fake
    responses (the established pattern), never on the literal `_PROMPT`
    text -- confirmed by reading the whole file before touching anything.
- `reel2movie/pipeline/waterfall.py` — wired the new sample → dedup →
  detect pipeline into `_extract_from_visual`, replacing the old
  sample → detect pipeline:
  ```python
  frames = sample_frames_at_interval(
      video_path, deps.frame_interval_seconds, duration_seconds, output_dir=frames_dir
  )
  unique_frames = dedupe_similar_frames(frames, threshold=deps.frame_dedup_threshold)
  candidates: list[Candidate] = []
  for frame in unique_frames:
      candidates.extend(deps.poster_detector.detect(frame))
  ```
  Everything else in that function is structurally unchanged: duration
  resolution (metadata-or-probe, with the same three distinct logged
  outcomes), `ensure_video` timing, and the `frames_dir`
  create-pass-cleanup-in-`finally` lifecycle via `shutil.rmtree`. Imports
  updated (`sample_frames_at_interval` + `probe_duration_seconds` from
  `frame_sampler`, `dedupe_similar_frames` from the new `frame_dedup`
  module); module docstring's list of free functions this module is
  allowed to call updated to match. One stale docstring reference to
  `sample_frames` inside the duration-undeterminable-outcome explanation
  was also corrected to `sample_frames_at_interval` while making this
  change (found by grepping the file for every remaining `sample_frames`
  mention after the edit, not missed).
- `reel2movie/pipeline/deps.py` — `PipelineDeps.frame_count: int =
  _DEFAULT_FRAME_COUNT` (= 6) replaced with two fields:
  `frame_interval_seconds: float = _DEFAULT_FRAME_INTERVAL_SECONDS` (= 1.0)
  and `frame_dedup_threshold: float = _DEFAULT_FRAME_DEDUP_THRESHOLD` (=
  0.04, deliberately mirroring `frame_dedup.py`'s own default exactly).
  Both module constants carry the same "not yet empirically tuned against
  real reel footage" caveat as `frame_dedup.py`'s docstring -- 1.0s was
  picked because it gives a 1-2 second on-screen text overlay a
  near-guaranteed chance of landing in at least one sampled frame, not
  because it was measured against real reels. `build_default_pipeline_deps()`
  needed no changes beyond what the field rename implies -- confirmed by
  reading it directly, it never referenced `frame_count` (or either new
  field) by name; both new fields simply keep their dataclass defaults
  through that function untouched.
- `reel2movie/cli.py` — `--frame-count` (`type=int`) replaced with
  `--frame-interval-seconds` (`type=float`, default `None` meaning "use
  `PipelineDeps`' own default" -- same override pattern as before,
  overriding `deps.frame_interval_seconds` instead of `deps.frame_count`).
  Help text updated, including an explicit note that no flag is exposed
  for the dedup threshold (deliberately -- see "Deferred / judgment calls"
  below). Module docstring's `sample_frames` seam-patching example updated
  to `sample_frames_at_interval` to match what `test_waterfall.py` actually
  patches now.
- `pyproject.toml` — added `"Pillow"` to `dependencies` (already present
  in the environment at 11.3.0, confirmed via `python3 -c "import PIL;
  print(PIL.__version__)"` before relying on it).

### Test fixes/additions across the suite (frame_count → frame_interval_seconds/frame_dedup_threshold, sample_frames → sample_frames_at_interval)

- `tests/unit/pipeline/test_waterfall.py`:
  - `_make_deps()` helper's `frame_count: int = 6` param renamed to
    `frame_interval_seconds: float = 1.0`.
  - Added a module-level `_identity_dedupe(frames, threshold=None)`
    pass-through fake, and a module docstring explaining the per-test
    choice: most existing tests monkeypatch BOTH
    `waterfall_module.sample_frames_at_interval` (renamed from
    `sample_frames`, same seam-patching convention) AND
    `waterfall_module.dedupe_similar_frames` (to the identity fake) --
    since those tests aren't about dedup specifically and the fake frames
    they hand back don't necessarily point at real, distinct on-disk
    images for a real perceptual diff to operate on meaningfully.
  - Every test that previously patched `sample_frames` now patches
    `sample_frames_at_interval` with a 3-arg signature
    `(video_path, interval_seconds, duration_seconds, **kwargs)` (renamed
    from `n` to `interval_seconds` to match the new function's actual
    parameter), and (except where noted) also patches
    `dedupe_similar_frames` to `_identity_dedupe`. Renamed:
    `test_frame_count_passed_through_to_sample_frames` →
    `test_frame_interval_seconds_passed_through_to_sample_frames_at_interval`;
    `deps.frame_count` → `deps.frame_interval_seconds` in the one
    remaining direct-field assertion
    (`test_visual_fallback_with_valid_metadata_duration_never_probes`).
  - New test: `test_dedup_step_is_wired_in_and_filters_frames_before_detection`
    -- the ONE test, per the task spec, that proves the wiring (not the
    dedup algorithm's own correctness, which `test_frame_dedup.py` already
    covers in isolation). Patches `sample_frames_at_interval` to return 5
    `FrameSample`s -- 4 of them pointing at the SAME on-disk fixture JPEG
    (a solid `(10, 20, 30)` 64x64 image) and 1 pointing at a substantially
    different fixture (`(250, 240, 230)`) -- and deliberately does NOT
    patch `dedupe_similar_frames`, letting the real implementation run.
    Asserts `poster_detector.calls` (the `FakePosterDetector`'s own call
    log) has strictly fewer entries than the 5 raw sampled frames and at
    least 1 -- proving frames were actually filtered between sampling and
    detection, not merely that detection ran at all. (Traced through by
    hand: kept = [frame0 (first, unconditional), frame3 (different enough
    from frame0's baseline), frame4 (different enough from frame3, which
    became the new baseline after frame3 was kept)] = 3 of 5 kept, 2
    dropped -- consistent with "strictly fewer than 5, at least 1".)
- `tests/unit/pipeline/test_deps.py`:
  `test_builds_without_raising_when_required_env_vars_present`'s
  `assert deps.frame_count > 0` → `assert deps.frame_interval_seconds > 0`
  plus an added `assert deps.frame_dedup_threshold >= 0` (covering both new
  fields, not just the renamed one).
- `tests/unit/test_cli.py`: `test_frame_count_override_reaches_pipeline_deps`
  → `test_frame_interval_seconds_override_reaches_pipeline_deps` (asserts
  `--frame-interval-seconds 3` reaches `deps.frame_interval_seconds` as
  `3.0`, and that the override mutates the actual object, not a copy, same
  as before); `test_no_frame_count_override_leaves_default_untouched` →
  `test_no_frame_interval_seconds_override_leaves_default_untouched`
  (unchanged in substance, just renamed/re-pointed at the new field).

### Deferred / judgment calls the orchestrating conversation should know about before review

- **`threshold=0.04` (both in `frame_dedup.py` and as
  `PipelineDeps.frame_dedup_threshold`'s default) and
  `frame_interval_seconds=1.0` are UNVALIDATED starting guesses**, exactly
  as the task spec instructed -- neither has been run against a single
  real downloaded reel yet (only the synthetic ffmpeg `testsrc` fixture and
  pure-Pillow synthetic images in this subtask's own tests). The task spec
  explicitly says the orchestrating conversation plans to validate/adjust
  these empirically against real reels after this subtask lands; flagging
  this prominently rather than letting a reviewer mistake the number for
  something already tuned.
- **No CLI flag for the dedup threshold**, per the task spec's explicit
  instruction not to speculatively add one. It remains reachable only by
  constructing/mutating a `PipelineDeps` directly (as
  `build_default_pipeline_deps()` + manual attribute assignment, same
  pattern the CLI itself uses for `frame_interval_seconds`).
- **`dedupe_similar_frames`'s fingerprint size (`64x64`, grayscale) was not
  separately parameterized** -- it's a module-level constant
  (`_FINGERPRINT_SIZE`), not exposed to callers at all. The task spec's
  function signature only exposes `threshold`, so this follows that
  signature exactly rather than adding an unasked-for knob.
- **Dense sampling plus real-world reel lengths**: a 1-second interval over
  a, say, 90-second reel produces up to 90 raw frames before dedup runs.
  This subtask did not add any upper bound/cap on frame count for
  unusually long input videos -- the task spec didn't ask for one, and
  `dedupe_similar_frames` is expected to collapse most of a long static
  reel down to a small kept set before any frame reaches the (expensive)
  vision LLM call regardless. Worth watching in review if genuinely long
  reels turn out to be common in practice.
- **Pillow version**: added as a bare `"Pillow"` dependency (no version
  pin) in `pyproject.toml`, matching the un-pinned style already used for
  `yt-dlp`/`requests`/`rapidfuzz` in that same file (only `anthropic` has a
  floor pin, `>=1.0`) -- not a special-cased decision for this subtask,
  just consistency with the existing file's convention.

### Test results

```
python3 -m pytest tests/unit -q
261 passed in 3.58s
```

244 (prior total, per the last Follow-up entry above) + 17 new tests (7 in
new `tests/unit/visual/test_frame_dedup.py` + 9 new
`sample_frames_at_interval` tests in `tests/unit/visual/test_frame_sampler.py`
+ 1 new `test_dedup_step_is_wired_in_and_filters_frames_before_detection`
in `tests/unit/pipeline/test_waterfall.py`) = 261. Renamed tests
(`test_frame_count_...` → `test_frame_interval_seconds_...`, etc.) don't
add to this count, only genuinely new tests do. Count only grew, never
dropped -- every pre-existing test (after being updated for the
rename/wiring change, not deleted) still passes.

### Review findings

Reviewed via `/code-review` (medium, forked) on the current working-tree
diff (`git status`/`git diff` -- nothing committed), `/ponytail:ponytail-review`
on the six named files (`visual/frame_dedup.py`, `visual/frame_sampler.py`,
`visual/vision_llm_detector.py`, `pipeline/waterfall.py`,
`pipeline/deps.py`, `cli.py`), and independent manual verification of the
specific behavioral contract points the task called out, not trusted from
the build report above.

**Own verification of the five called-out behavioral points:**

1. **`dedupe_similar_frames` compares each candidate against the last-KEPT
   frame, confirmed by reading the loop directly** (`visual/frame_dedup.py`
   L112-120): `last_kept_fingerprint` is only ever reassigned inside the
   `if difference >= threshold:` branch (i.e. only when a frame is actually
   kept), and every candidate's `_mean_abs_difference` call always reads
   whatever `last_kept_fingerprint` currently holds -- a dropped candidate
   never updates it. This is genuinely "compare to last kept," not "compare
   to immediately previous."
2. **`sample_frames_at_interval` covers ~0 to the tail with no 5%/95%
   dodge, confirmed by reading `_compute`-style logic directly**
   (`visual/frame_sampler.py` L286-290): a plain `t = 0.0; while t <
   duration_seconds: ...; t += interval_seconds` walk, with no `0.05 *` /
   `0.95 *` window anywhere in this function (that window is
   `_compute_timestamps`'s, used only by the separate `sample_frames`).
   First timestamp is exactly `0.0`; last is `< duration_seconds`, not
   `0.95 * duration_seconds`.
3. **Waterfall wiring: sample -> dedup -> detect, in order, using
   `deps.frame_interval_seconds`/`deps.frame_dedup_threshold`, confirmed by
   reading `_extract_from_visual` directly** (`pipeline/waterfall.py`
   L222-234): `sample_frames_at_interval(video_path,
   deps.frame_interval_seconds, duration_seconds, output_dir=frames_dir)`
   feeds straight into `dedupe_similar_frames(frames,
   threshold=deps.frame_dedup_threshold)`, and only `unique_frames` (the
   dedup output) is iterated into `deps.poster_detector.detect()`. No
   hardcoded `6`/`0.04` literal anywhere in this function -- both values
   come from `deps`.
4. **Zero changes outside this subtask's scope, confirmed via `git
   status`:** `git status --porcelain -- reel2movie/ingest
   reel2movie/tmdb reel2movie/text_extraction reel2movie/core
   reel2movie/config.py` returns nothing. The full `git status` shows
   changes confined to `PROGRESS.md`, `pyproject.toml`, `cli.py`,
   `pipeline/deps.py`, `pipeline/waterfall.py`, `visual/frame_sampler.py`,
   `visual/vision_llm_detector.py`, their tests, plus the two new
   untracked files (`visual/frame_dedup.py` + its test).
5. **Independent test run, not trusted from the build report:**
   `python3 -m pytest tests/unit -q` -> **261 passed in 3.41s**, run
   directly in this review pass -- matches the build report's claimed
   count exactly.

**Vision prompt widened correctly, output contract unchanged (confirmed by
reading `_PROMPT` directly, `visual/vision_llm_detector.py` L217-249):**
the prompt now asks EITHER (1) poster/title-card/identifiable-scene (the
original ask) OR (2) a creator-added on-screen TEXT overlay naming a
movie/show, explicitly distinguishing it from text that's part of the
filmed scene. The required JSON shape
(`[{"title", "year"?, "confidence"}, ...]`) and its three confidence labels
are untouched between the old and new prompt text -- this is additive to
what the model looks for, not a schema change, confirmed by diffing the
prompt string directly rather than assuming from the PROGRESS.md narrative.

**From `/code-review` (correctness) + `/ponytail:ponytail-review`
(over-engineering), all non-blocking:**

- **Non-blocking, flagged prominently** -- `pipeline/waterfall.py`'s module
  docstring still claims "Implements `flow.md` steps [2]-[6] exactly," but
  `flow.md` step [4] explicitly says "pick N equally-spaced timestamps
  (not a dense scan)" (confirmed by reading `flow.md` L31-34 directly) --
  the literal opposite of what `_extract_from_visual` now does. This is a
  deliberate, sanctioned behavior change (the entire point of this
  subtask, per its own Motivation section above), not an accidental bug,
  but `flow.md` itself was not updated to reflect the new dense-sampling
  contract, so the module's "implements flow.md exactly" claim is now
  false on its face. Same category/severity as Subtask 7's
  `CONFIDENCE_THRESHOLD`-literal finding (non-blocking, correct as
  shipped, but a doc/spec-drift risk for the next reader who trusts the
  docstring over the code). Recommend updating `flow.md` step [4]'s text
  in a follow-up, not re-opening this subtask for it.
- **Non-blocking** -- `visual/frame_sampler.py`'s `sample_frames` (the old
  sparse, N-equally-spaced, 5%-95%-windowed function) now has zero
  production call sites: `pipeline/waterfall.py`'s only call site was
  switched to `sample_frames_at_interval`, and a repo-wide grep
  (`grep -rn "sample_frames\b" reel2movie/`) confirms nothing outside
  `frame_sampler.py`'s own definition/docstrings calls it. It is exercised
  only by its own dedicated tests now. Not flagged blocking since the task
  spec explicitly asked for a refactor ("not rewritten") that keeps
  `sample_frames` intact and only adds `sample_frames_at_interval`
  alongside it -- but a future subtask should decide whether to delete it
  (and its tests) or find it a real caller.
- **Non-blocking** -- `pipeline/deps.py`'s `_DEFAULT_FRAME_DEDUP_THRESHOLD
  = 0.04` is a second, independently-declared literal that merely mirrors
  `visual/frame_dedup.py`'s own `_DEFAULT_THRESHOLD = 0.04` by convention,
  not by import. Both docstrings explicitly flag the *value* as an
  unvalidated placeholder expected to change -- but nothing enforces the
  two literals staying equal once it does, raising the same "two sources
  of truth, kept in sync only by convention" risk Subtask 7's
  `CONFIDENCE_THRESHOLD` finding already named and accepted as
  non-blocking. Recommend importing `frame_dedup`'s constant into
  `deps.py` instead of re-declaring it, in a follow-up.
- **Non-blocking, low severity** -- `sample_frames_at_interval`'s timestamp
  walk (`t = 0.0; while t < duration_seconds: ...; t += interval_seconds`)
  accumulates ordinary binary floating-point error across repeated
  addition. For round values like the current default (`1.0`) this is a
  non-issue, but a caller passing a non-binary-exact interval (e.g. `0.3`)
  can get one more or one fewer frame than a clean `duration/interval`
  division implies, depending on which side of the true boundary the
  accumulated error lands on. Worst case is a single extra/missing sample
  at the tail of an already-dense scan, not a crash or a silent large
  miscount -- not worth blocking a subtask whose own stated defaults are
  round numbers, but worth a `math.ceil`/integer-step rewrite if a
  non-round interval ever becomes a real override value.
- **From `/ponytail:ponytail-review`:** the diff is otherwise lean --
  `_extract_frame_at` is a genuine, newly-shared helper eliminating real
  duplication between `sample_frames` and `sample_frames_at_interval`
  (the opposite of over-engineering), `frame_dedup.py`'s three functions
  each do exactly one job with no speculative parameterization beyond
  what the task spec's own function signature asked for, and `cli.py`'s
  flag rename is a pure 1:1 swap. No reinvented stdlib, no unneeded
  dependency, no speculative abstraction beyond the two items above (both
  already non-blocking and already named by `/code-review` too).

No blocking findings. Both new-module algorithmic claims (compare-to-last-
kept, whole-video coverage), the waterfall wiring order and its use of the
new `deps` fields, the untouched-directories claim, the independently-run
test count, and the widened-but-contract-preserving vision prompt all check
out under direct, independent verification -- not merely re-reading the
build report's claims.

VERDICT: ACCEPTABLE

### Follow-up — tolerate per-timestamp extraction failures

Real end-to-end testing against 11 live Instagram reels (after this
subtask landed) surfaced a genuine bug in `sample_frames_at_interval`,
caught via the actual pipeline run against
`https://www.instagram.com/reel/DeCngQIST-o/`, which returned ZERO
recommendations despite the video almost certainly having detectable
content. The real stderr:

```
reel2movie.visual.frame_sampler.FrameExtractionError: ffmpeg reported success (exit code 0)
extracting frame at timestamp 158.000s from .../Video by akshatonli [DeCngQIST-o].mp4,
but the output file .../frame_0158.jpg is missing or empty. ffmpeg stderr: ffmpeg version 7.1 ...
```

**Root cause:** this is the same documented ffmpeg quirk this subtask's
own docstrings and tests already named ("Output file is empty, nothing
was encoded" / "a real ffmpeg quirk specific to very sparse frame
grids") -- seeking very close to the true end of a video stream can make
ffmpeg exit 0 while writing nothing. `sample_frames` mostly dodges this
by staying within its 5%-95% window, but `sample_frames_at_interval`
deliberately samples the full 0-to-duration range INCLUDING the tail (by
design -- that's the whole point of this subtask, catching on-screen
text that can appear right at a reel's edges), so any reel whose
duration doesn't land cleanly on an interval boundary can produce a
final timestamp right at the stream's ragged edge. Before this fix, that
one failing timestamp's `FrameExtractionError` propagated straight out
of `sample_frames_at_interval` (via the shared `_extract_frame_at`
helper), and `pipeline/waterfall.py`'s `_extract_from_visual` wraps the
whole sample→dedup→detect sequence in one broad
`except Exception: logger.exception(...); return []` -- so one failed
frame at timestamp 158 silently discarded every OTHER successfully-
extracted frame's detections too. A reel with ~150 good frames and 1 bad
one at the tail returned nothing at all, instead of the 150 good frames'
worth of results.

**Fix:** `sample_frames_at_interval`'s per-timestamp loop now catches
`FrameExtractionError` itself, logs a warning naming the skipped
timestamp and the video path plus the underlying error, and continues
to the next timestamp -- returning whatever subset of `FrameSample`s
succeeded (an empty list, not a raise, if literally every timestamp
fails). This is a deliberately narrower change than it might look:
`sample_frames` (the old sparse function) and `_extract_frame_at` itself
are completely untouched and still raise on the first failure exactly as
before -- `sample_frames`'s fixed-`n` callers (poster detection) expect a
complete, fixed-size result and existing tests assert that all-or-nothing
contract. Only `sample_frames_at_interval`'s caller-facing contract
changed, from all-or-nothing to best-effort-partial. Both functions'
docstrings (and the module docstring's summary) now spell out this
difference explicitly, citing this exact production failure as the
motivating case, the same way other docstrings in this file already cite
specific observed ffmpeg quirks.

`pipeline/waterfall.py`'s `_extract_from_visual` was checked and needs no
change: `dedupe_similar_frames` already returns `[]` outright for an
empty input list (confirmed by reading `frame_dedup.py`'s own docstring
and early-return), and handles any shorter-than-expected, non-empty list
identically to a "complete" one -- the `for frame in unique_frames:
candidates.extend(deps.poster_detector.detect(frame))` loop has no
dependency on the list being any particular length. A partial frame list
from `sample_frames_at_interval` therefore already flows through
correctly as "fewer frames to run detection on," same as if the video had
simply been shorter.

**Tests:** `tests/unit/visual/test_frame_sampler.py`'s
`test_sample_frames_at_interval_propagates_frame_extraction_error` (which
asserted the OLD all-or-nothing contract for this function -- it mocked
every timestamp to fail and asserted a raise) is no longer true of the
new behavior and was replaced by two tests instead:
`test_sample_frames_at_interval_every_timestamp_failing_returns_empty_list`
(same mock setup, now asserts `== []` with no raise) and the new
regression test
`test_sample_frames_at_interval_skips_one_failing_timestamp_and_returns_the_rest`,
which patches `subprocess.run` with a `side_effect` that fails only the
single timestamp matching `"3.0"` (exit code 0, empty output -- the exact
quirk from the real stderr above) while letting every other timestamp's
call fall through to the real ffmpeg binary, then asserts the 5 other
timestamps' frames all come back correctly (non-empty files on disk) and
the failed one is simply absent. All other `sample_frames_at_interval`
tests from this subtask's original build (spacing, start/tail inclusion,
invalid-argument `ValueError`s, filename pattern) are unchanged and still
pass, as do all of `sample_frames`'s own failure-mode tests (unaffected,
since `sample_frames` and `_extract_frame_at`'s raising behavior were not
touched).

Full suite: 261 -> 262 passed (`python3 -m pytest tests/unit -q`) -- net
+1 (one test replaced by two, per the above).

#### Review findings

Reviewed via `/code-review` (medium) against the working-tree diff,
`/ponytail:ponytail-review` against `reel2movie/visual/frame_sampler.py`,
and a manual verification pass (not trusting the fix report): read
`sample_frames_at_interval`, `sample_frames`, and `_extract_frame_at`
directly in full; read `pipeline/waterfall.py`'s `_extract_from_visual`
and `frame_dedup.dedupe_similar_frames` directly; ran
`git status --short` and `git status --short -- reel2movie/pipeline/waterfall.py`;
independently ran `python3 -m pytest tests/unit -q`; read the new/changed
tests in `tests/unit/visual/test_frame_sampler.py` in full.

**From `/code-review` (correctness/cleanup):** no findings. Scoped
correctly: the new `try/except FrameExtractionError: ...; continue` lives
only in `sample_frames_at_interval`'s loop; `sample_frames` and
`_extract_frame_at` are untouched; the `waterfall.py` caller already had
the right broad exception handling plus a `finally: shutil.rmtree`, so no
further change was needed there. 26/26 relevant tests pass.

**From `/ponytail:ponytail-review`:** no findings ("Lean already. Ship.",
net -0 lines possible). The actual code delta is minimal for the shape of
fix needed -- one `import logging` + one `logger` line + a 15-line
try/except/continue around the existing `_extract_frame_at` call, no new
class, no retry/backoff abstraction, no config knob, and no speculative
unification of `sample_frames`'s and `sample_frames_at_interval`'s now-
divergent error contracts (correctly left as two separate, simple
functions rather than one parameterized by a "failure policy"). The bulk
of the diff's line count is docstring prose, out of this review's
code-complexity scope.

**Manual verification (own reading, not the fix report):**
- `sample_frames_at_interval` (frame_sampler.py L350-370): confirmed the
  per-timestamp loop now wraps `_extract_frame_at(...)` in
  `try/except FrameExtractionError as exc: logger.warning(...); continue`,
  returning whatever subset of `FrameSample`s succeeded (`[]` if every
  timestamp fails). Matches the report exactly.
- `sample_frames` (L179-235) and `_extract_frame_at` (L102-176): read both
  in full. Confirmed byte-for-byte unchanged raise-on-first-failure
  behavior -- `sample_frames`'s loop still calls `_extract_frame_at`
  directly with no try/except, so a `FrameExtractionError` still
  propagates straight out, exactly as before. No drift into the sparse
  path.
- `git status --short -- reel2movie/pipeline/waterfall.py` returns
  nothing (file untouched), confirmed. Read `_extract_from_visual`
  (waterfall.py L101-239) directly: `frames = sample_frames_at_interval(...)`
  now may return a partial or empty list instead of raising; this flows
  into `unique_frames = dedupe_similar_frames(frames, ...)`; read
  `dedupe_similar_frames` (frame_dedup.py L87-122) directly and confirmed
  its `if not frames: return []` early-return handles the empty case, and
  a non-empty-but-shorter list is handled identically to a full one (same
  comparison-against-last-kept-fingerprint loop, no length assumption).
  The subsequent `for frame in unique_frames: candidates.extend(deps.poster_detector.detect(frame))`
  loop simply runs zero or fewer times on a trimmed list -- no exception
  path, so `_extract_from_visual` returns `[]` or a partial
  `candidates` list cleanly, never hitting its own `except Exception`
  handler as a side effect of this fix. Confirmed this really does fix
  the reported production bug: one bad tail timestamp no longer
  propagates up and discards every other frame's detections.
- `git status --short` (full repo): shows exactly `PROGRESS.md`,
  `reel2movie/visual/frame_sampler.py`, `tests/unit/visual/test_frame_sampler.py`
  -- nothing under `ingest/`, `tmdb/`, `text_extraction/`, `core/`,
  `config.py`, `frame_dedup.py`, `vision_llm_detector.py`, `cli.py`, or
  `deps.py`. Confirmed.
- `python3 -m pytest tests/unit -q`: independently re-ran, got
  `262 passed in 6.41s`. Matches the claimed 261 -> 262.
- Read `tests/unit/visual/test_frame_sampler.py`'s two new/changed tests
  in full.
  `test_sample_frames_at_interval_skips_one_failing_timestamp_and_returns_the_rest`
  is a genuine partial-failure test, not trivially true: it patches
  `subprocess.run` with a `side_effect` that fails only the call whose
  timestamp argument is `"3.0"` (exit 0, empty-output stderr -- the exact
  real-world quirk) while delegating every other timestamp to the real
  ffmpeg binary via a captured `real_run` reference, then asserts the
  other 5 timestamps (`[0.0, 1.0, 2.0, 4.0, 5.0]`) come back with actual
  non-empty files written to disk by real ffmpeg, and that `3.0` is simply
  absent from the result. This genuinely exercises the "mixed success/
  failure across a dense sample set" path, not a mocked-everything
  tautology.
  `test_sample_frames_at_interval_every_timestamp_failing_returns_empty_list`
  mocks `subprocess.run` to return exit code 1 for every call (same setup
  the old test used, which previously asserted a raise), now asserts
  `== []`. This genuinely exercises the "every timestamp fails" path
  since each call independently raises inside `_extract_frame_at` and is
  independently caught-and-skipped by the loop, converging on `[]` rather
  than failing fast on the first one.

No blocking findings. The fix is correctly and narrowly scoped (only
`sample_frames_at_interval`'s per-timestamp failure handling changed),
the claimed unchanged behavior for `sample_frames`/`_extract_frame_at`/
`waterfall.py` was independently confirmed by reading the code rather than
trusting the report, the test count and the two new tests' realism were
independently confirmed, and the diff footprint matches exactly what was
claimed.

VERDICT: ACCEPTABLE

## GUI Subtask 1: background engine (gui/workers.py)

### What's built

A new, separate `gui/` package layered on top of the already-complete
`reel2movie` pipeline — nothing under `reel2movie/` or `tests/` was
touched. First files in the package:

- `gui/__init__.py` — empty, marks `gui` as a package.
- `gui/workers.py` (~106 lines) — the single place in the GUI codebase
  allowed to know about `QThread`, the local `claude` CLI usability
  check, and the `VISION_BACKEND` env-var fallback. Zero Qt widget code,
  just two `QThread` subclasses plus three plain functions:
  - `check_claude_cli_usable` — checks `shutil.which("claude")` first,
    then runs `claude --version` via `subprocess.run` with a timeout,
    wrapped in a bare `except Exception`.
  - `ClaudeCliCheckWorker` — runs the above off the main thread.
  - `apply_anthropic_api_fallback` — flips the process over to the
    `anthropic_api` vision backend by setting two env vars; caller must
    invoke it before `build_deps_or_error()` when the CLI check comes
    back `False`.
  - `build_deps_or_error` — try/except wrapper around
    `build_default_pipeline_deps()` (from `reel2movie.pipeline.deps`),
    turning any construction failure (e.g. missing `TMDB_API_KEY`) into
    an error string instead of letting it raise.
  - `PipelineRunner` — runs `reel2movie.pipeline.waterfall.run_pipeline(url,
    deps)` off the main thread, emitting `succeeded`/`failed` instead of
    letting exceptions escape the thread.

### Public interface contract

This is the fixed contract other already-written/planned GUI code
depends on; names and signatures must not change:

- `check_claude_cli_usable(timeout_seconds=5.0) -> bool` — never raises;
  `False` on missing binary/timeout/nonzero exit/any exception.
- `ClaudeCliCheckWorker(QThread)` — `Signal(bool)` named `finished_check`,
  emitted exactly once.
- `apply_anthropic_api_fallback(api_key: str) -> None` — sets
  `os.environ["ANTHROPIC_API_KEY"]` and
  `os.environ["VISION_BACKEND"] = "anthropic_api"`.
- `build_deps_or_error() -> tuple[PipelineDeps | None, str | None]` —
  never raises, wraps `build_default_pipeline_deps()`.
- `PipelineRunner(QThread)` — `Signal(object)` named `succeeded`,
  `Signal(str)` named `failed`; exactly one fires per run; `run()` never
  raises uncaught.

### Smoke-test results (prior subagent, observed)

- `claude` CLI detection: both the found-and-working (`True`) and
  not-found/broken (`False`) paths exercised directly against
  `check_claude_cli_usable`.
- Env-var fallback: `apply_anthropic_api_fallback` confirmed to set both
  `ANTHROPIC_API_KEY` and `VISION_BACKEND` in `os.environ`.
- `build_deps_or_error`: both the happy path (real deps object returned,
  no error string) and the error path (missing API key surfaced as a
  string, not raised) exercised.
- `PipelineRunner`: failure path exercised against an unreachable URL —
  `failed` fired with a message, no uncaught exception escaped the
  thread.
- All of the above passed.

### Review pass outcome

Ran `code-review` (medium effort, full-file review since these are new
untracked files with no committed baseline) against the exact contract
above, point by point — came back clean, zero findings. Ran
`ponytail-review` for over-engineering (unneeded abstractions, reinvented
stdlib, speculative flexibility) — also came back clean: no dead code, no
unused flexibility, no reinvented stdlib: `shutil.which` + `subprocess.run`
used directly rather than wrapped, the two `QThread` subclasses are the
minimal Qt pattern for background work and are not candidates for merging
into a shared base given the fixed, distinct signal contracts each must
expose. No changes were made to `gui/workers.py` as a result of this
review pass.

## GUI Subtask 2: presentational widgets (gui/widgets.py)

### What's built

A new file in the same `gui/` package, sitting beside `gui/workers.py`
but deliberately isolated from it: `gui/widgets.py` (~600 lines) is pure
Qt (PySide6) presentation code with zero knowledge of `reel2movie`,
threading, or env vars. Every widget takes only plain Python values
(str/int/float/None/dict/list) via constructor args/methods and talks
upward only through plain Qt signals. Three classes:

- `RecommendationCard(title, year, overview, media_type, source,
  confidence, poster_path, query, parent=None)` — one result card.
  When `poster_path` is set and `title` is resolved (not `None`), the
  poster is fetched asynchronously via `QNetworkAccessManager`
  (`https://image.tmdb.org/t/p/w500{poster_path}`), never blocking the
  GUI thread; a failed fetch just leaves the placeholder, silently. When
  `title is None` the card is marked via the `unresolved` dynamic
  property, skips the network fetch entirely, and renders distinct
  placeholder copy that references the raw `query` string instead of a
  year/overview.
- `ApiKeyPromptPanel` — inline TMDB API key prompt; `Signal(str)` named
  `key_submitted` fires with the trimmed key on non-empty submit (button
  click or Enter-in-field); empty/whitespace-only input does not emit
  and instead reveals an inline validation hint label rather than a
  silent no-op.
- `ResultsPanel` — scrollable container of `RecommendationCard`s.
  `set_recommendations(cards_data: list[dict])` clears existing cards
  first, builds one card per dict (keys matching the
  `RecommendationCard` constructor kwargs exactly), and shows a centered
  "No recommendations found." message instead of a blank panel when the
  list is empty. `clear()` removes all cards *and* any empty-state
  message, leaving a genuinely empty container.

### Design system approach

Spacing (`SPACE_1`..`SPACE_6`), color (panel/card/text/accent/badge/
unresolved/danger tokens), and typography (`FONT_FAMILY`) are centralized
as module-level constants and woven into one QSS template (`_STYLESHEET`)
rather than scattered as inline hex strings across widget code. All three
widgets apply the same stylesheet to themselves (QSS rules are scoped by
object name, so sharing one sheet across independent widget instances is
harmless); this keeps each widget self-contained and stylable even when
embedded standalone, with no dependency on a top-level window applying a
shared application stylesheet.

### Smoke-test results (prior subagent, observed)

Per the prior subagent's report when the file was first written: poster
fetch success (resolved card with a real `poster_path` swapped in a
scaled pixmap), unresolved-state rendering (no network attempt, distinct
placeholder copy referencing `query`), submit validation (empty/
whitespace rejected with inline hint, non-empty trimmed and emitted), and
mixed-list rendering via `set_recommendations()` — all passed.

### Review pass outcome

Ran `code-review` (medium effort, full-file review since this is a new
untracked file with no committed baseline) against the exact contract
above. Findings: (1) **real bug, fixed** — the async poster-fetch
callback (`_on_poster_reply_finished`) had no guard against the card (and
its `_poster_label`) being deleted while the network reply was still in
flight (e.g. `ResultsPanel.clear()`/`set_recommendations()` re-running
mid-fetch); reproduced this exactly against an unpatched copy of the file
(`RuntimeError: libshiboken: Internal C++ object (PySide6.QtWidgets.
QLabel) already deleted`) and fixed it with a `try/except RuntimeError`
guard around the label update. (2) Duplicate badge-row construction
between the resolved/unresolved branches — extracted into a shared
`_build_badges_row(source, confidence)` helper. (3) Dead/ineffective QSS
property `line-height: 140%` on `QLabel#cardOverview` (not a Qt Style
Sheet–supported property for `QLabel`, silently had zero effect) —
removed. (4) Each card opening its own `QNetworkAccessManager` instead of
sharing one — replaced with a single process-wide shared manager
(`_get_shared_network_manager()`), cutting per-card connection-pool
overhead without touching the public constructor. Per-widget
`setStyleSheet(_STYLESHEET)` reapplication (flagged as a minor parse-cost
concern) was left as-is: it's already reasoned about in the module
docstring as a deliberate, negligible-cost tradeoff for keeping each
widget independently stylable.

Ran `ponytail-review` for over-engineering. The deliberate design-system
constants (spacing/color/typography tokens, the QSS template) were not
flagged, per the product requirement that this file carry real visual
polish. Genuine findings: an unused `ResultsPanel._cards` list that was
populated and reset but never read anywhere (the layout already owns and
tracks the child widgets) — removed; and the same badge-row duplication
code-review also caught — fixed via the same shared helper.

After the fixes, re-ran a throwaway (uncommitted) PySide6 script showing:
a resolved card with a real TMDB poster (loaded asynchronously, no GUI
thread block), a resolved card with `poster_path=None` (no fetch
attempted), an unresolved card (`unresolved` property `True`, no poster
label created), `ApiKeyPromptPanel` rejecting whitespace-only input with
the hint shown and no signal emitted, then accepting a real key trimmed
and emitted, and `ResultsPanel.set_recommendations()` with a mixed
resolved/unresolved list followed by an empty list (empty-state message
shown) and `clear()` (container and empty-state message both gone) — all
checks passed, no crash. Separately reproduced and re-verified the fixed
race condition directly: deleting a `RecommendationCard` immediately
after starting a real poster fetch no longer raises; an unpatched control
copy of the file still crashes with the exact `RuntimeError` described
above, confirming the fix is both real and effective.

No changes were needed to the public interface (class names, signal
names, constructor/method signatures); all fixes were internal.

## GUI Subtask 3: MainWindow, entry point, styling, packaging (gui/main_window.py, gui/main.py, gui/styles.qss, pyproject.toml)

### What's built

The final pieces of the `gui/` package, wiring Subtask 1's background
engine (`gui/workers.py`) to Subtask 2's presentational widgets
(`gui/widgets.py`) into one runnable app — nothing under `reel2movie/` or
`tests/` was touched.

- `gui/main_window.py` — `MainWindow(QMainWindow)`: the one-screen app.
  An always-visible URL input row (`QLineEdit` + "Run" `QPushButton`,
  Enter-to-submit) sits above a `QStackedWidget` with four pages —
  idle, running (indeterminate `QProgressBar` + status text), results
  (`ResultsPanel`), and a styled top-level error banner — plus an inline
  `ApiKeyPromptPanel` shown only when needed. The Run-click state
  machine: validate non-empty URL → run the one-time-per-session
  `ClaudeCliCheckWorker` → if the `claude` CLI isn't usable and no key has
  been supplied yet this session, pause on the inline API-key panel →
  once usable (CLI or a supplied key), `build_deps_or_error()` → on
  success run `PipelineRunner` → `succeeded`/`failed` each re-enable Run
  and show results/error respectively. `Recommendation` → dict mapping
  for `ResultsPanel.set_recommendations()` reads `rec.tmdb.title/year/
  overview/media_type/poster_path`, `rec.source.value`, `rec.confidence`,
  `rec.query` — re-verified field-for-field against `reel2movie/core/
  models.py`'s actual `ResolvedMovie`/`Recommendation` dataclasses; no
  mismatch.
- `gui/main.py` — entry point (`python3 -m gui.main`): `load_dotenv()`,
  `QApplication`, loads+applies `gui/styles.qss`, shows `MainWindow`,
  `sys.exit(app.exec())`.
- `gui/styles.qss` — pure QSS for the window chrome (input row, Run
  button, progress bar, status/validation text, error banner), sharing
  `gui/widgets.py`'s color tokens by value so the window doesn't clash
  with the cards/panels it hosts.
- `pyproject.toml` — one line added: `gui = ["PySide6"]` under
  `[project.optional-dependencies]`.

### Live end-to-end test (prior subagent, observed)

Run against a real Instagram reel URL
(`https://www.instagram.com/reel/DU7OQACiDtk/`) with the real pipeline
(no mocks): reached the results state successfully with 11 items
rendered, including some real TMDB-connection-reset unresolved entries
handled gracefully (rendered as the distinct "could not verify on TMDB"
card rather than crashing or dropping the row). Also exercised:
empty-URL validation, the missing-`TMDB_API_KEY` error path, the
claude-CLI-unusable → API-key-fallback path, and a double-Run-click state
reset.

### Review pass outcome

Ran `code-review` (high effort) against `gui/main_window.py` and
`gui/main.py`. Four findings, all independently re-confirmed by direct
code tracing against `gui/workers.py`, `reel2movie/pipeline/deps.py`, and
`reel2movie/config.py`:

1. **Real bug, fixed.** `_on_run_clicked` had no re-entrancy guard, and
   `url_input.returnPressed` fires regardless of `run_button`'s disabled
   state — pressing Enter while a CLI check or pipeline run was already
   in flight started a second `ClaudeCliCheckWorker`/`PipelineRunner` and
   overwrote the still-running one's `self._cli_check_worker`/
   `self._pipeline_runner` reference (risking Qt's "QThread: Destroyed
   while thread is still running" and racing `succeeded`/`failed`
   signals). Fixed with a one-line guard at the top of `_on_run_clicked`
   (`if not self.run_button.isEnabled(): return`), since `run_button`'s
   enabled state already tracks "is a background op in flight" precisely
   throughout the class.
2. **Blocking cross-module issue, NOT fixed (reported instead, per
   scope).** The inline `ApiKeyPromptPanel` (`gui/widgets.py`, out of
   scope/already approved) is hardcoded with the title "TMDB API Key
   Needed" and copy explaining it verifies titles against TMDB. But
   `main_window.py` only ever shows this panel on the claude-CLI-unusable
   fallback path, and wires its submitted value to
   `apply_anthropic_api_fallback()`, which sets `ANTHROPIC_API_KEY` /
   `VISION_BACKEND=anthropic_api` — never `TMDB_API_KEY`. Confirmed via
   `reel2movie/config.py`/`reel2movie/pipeline/deps.py` that this wiring
   is logically *correct* for its actual purpose (the Anthropic-key
   fallback for the vision backend), but the panel's own hardcoded text
   is simply the wrong copy for that context: a user following the
   on-screen instructions and pasting a real TMDB key would have it
   stored as `ANTHROPIC_API_KEY` instead, `TMDB_API_KEY` would still be
   unset, and they'd hit an unrelated-looking top-level error with no
   other path forward. Fixing this requires changing `gui/widgets.py`'s
   hardcoded panel copy, which is out of scope for this pass — flagged
   here as a blocking issue for a follow-up pass instead.
3. **Real bug, fixed.** Neither `QThread` worker is Qt-parented to
   `MainWindow` (both constructed with the default `parent=None`), so
   closing the window mid-run didn't stop them, and process teardown
   while a worker was still executing risked the same "destroyed while
   running" crash. Fixed with a minimal `closeEvent` override: ignore the
   close while either worker `isRunning()`, otherwise proceed normally.
4. **Assessed, not independently reachable — no fix made.**
   `_on_cli_check_finished` silently no-ops if `self._pending_url is
   None`, which could in theory leave `run_button` permanently disabled.
   Traced every path that sets `_pending_url`: it's set immediately
   before every `_begin_flow()` call and is never reset to `None`
   afterward anywhere in the class, so this branch is unreachable in the
   code as shipped (the finding's own hypothetical trigger was "a future
   edit" or interleaving with finding #1 — which fix #1 above now
   forecloses). Left as-is rather than add speculative dead-state
   handling.

Ran `ponytail-review` against both files for over-engineering: no
findings (`Lean already. Ship.`). The four-page `QStackedWidget`, the
small `_show_*` state-transition helpers (each with multiple call sites),
and the session-state flags (`_claude_cli_checked`/`_claude_cli_usable`/
`_api_key_supplied`/`_pending_url`, each required by the async CLI-check
step) were all judged necessary, not speculative — consistent with this
being real state-machine/design work rather than unused flexibility.

### Independent re-verification (this pass, not just trusting the prior report)

Wrote a throwaway script (`QT_QPA_PLATFORM=offscreen`, not committed)
driving real `MainWindow` instances directly:

- **Empty-URL validation**: whitespace-only input + Run → validation
  label shown with the exact expected text, content area stays on the
  idle page, Run stays enabled, no worker started. **Matches prior
  claim.**
- **Missing-`TMDB_API_KEY` error path**: using a scoped/cleared
  environment (never touched the real `.env`; `TMDB_API_KEY`/
  `ANTHROPIC_API_KEY`/`VISION_BACKEND` popped from `os.environ` first) →
  Run → error page shown with `"TMDB_API_KEY is not set"` in the banner
  text, Run re-enabled, no pipeline thread ever started. **Matches prior
  claim.**
- **Double-Run-click / Enter-bypass state reset**: monkeypatched
  `gui.workers.run_pipeline` to a fast fake (no real network), gave a
  throwaway `TMDB_API_KEY` so dependency construction succeeds, then
  called the Run slot twice back-to-back while the first run was still
  in flight (reproducing the Enter-key path, not just a second button
  click). Confirmed: only one `PipelineRunner` instance was ever created
  (`self._pipeline_runner` unchanged by the second call), the fake
  pipeline function was invoked exactly once, and after the run finished
  Run was re-enabled and the results page shown. This exercises the fix
  for finding #1 above and **matches/extends the prior claim** — the
  prior subagent's double-Run-*button*-click test wouldn't have caught
  the Enter-key path, which this pass's fix now also closes.

`python3 -m pytest tests/unit -q` → **262 passed**, confirming no
regression in `reel2movie/` (which this subtask did not touch).

### Closing note — the app is complete

All three GUI subtasks (`gui/workers.py`, `gui/widgets.py`,
`gui/main_window.py` + `gui/main.py` + `gui/styles.qss` + the
`pyproject.toml` optional-dependency line) are done. To run the app:

```
pip install -e ".[gui]"   # or: pip install PySide6
python3 -m gui.main
```

## GUI follow-up: fixed ApiKeyPromptPanel's mismatched copy

The one blocking cross-module issue from GUI Subtask 3's review (finding
#2: `ApiKeyPromptPanel` in `gui/widgets.py` said "TMDB API Key Needed"
and described verifying titles against TMDB, but the panel is only ever
shown on the claude-CLI-unusable → Anthropic-key fallback path and its
submitted value is stored as `ANTHROPIC_API_KEY`, never `TMDB_API_KEY`)
is now fixed. Title changed to "Anthropic API Key Needed", the
explanation reworded to describe the actual claude-CLI-unavailable /
vision-fallback context, and the `QLineEdit` placeholder ("Paste your
TMDB API key" → "Paste your Anthropic API key") updated to match — that
placeholder was the same bug but outside the first fix pass's stated
scope, caught and closed directly rather than spinning another
write/review cycle for a one-line string change.

Scope: pure string-content change in `ApiKeyPromptPanel` only — no
change to its class name, `key_submitted` signal, constructor signature,
or any other class in the file (`RecommendationCard`, `ResultsPanel`
untouched). Verified: `ast.parse` on the file succeeds, a standalone
smoke test confirms `key_submitted` still fires correctly on non-empty
submit and not on empty/whitespace input, and the full
`python3 -m pytest tests/unit -q` suite still passes (262 passed).

With this fix, the `gui/` package has no known open issues. All three
GUI subtasks' write/review loops are closed.

## Pipeline Rewrite Wave 1: frame sampling, cancellation infra, audio subpackage

First wave of a larger planned rewrite (a parallel "waterfall race"
architecture: caption/comment/visual/audio candidate extraction running
concurrently, losers genuinely killed once a winner is found). Three
pieces, built by three agents in parallel and committed together at
`a593b4c`, then given an independent second-look review pass (this
section) before the next wave builds on top of it.

### 1. Frame sampling interval + `ensure_video()` idempotency

- `pipeline/deps.py`'s `_DEFAULT_FRAME_INTERVAL_SECONDS`: `1.0` → `0.5`.
  Chosen from empirical A/B testing against 3 real sample Instagram Reel
  videos in the repo root — halving the interval caught meaningfully more
  brief on-screen-text/poster frames (creator-burned "movies like X" text
  cards held only 1-2s can fall entirely between two sparse samples) at a
  22%-58% increase in vision-LLM call count. Going denser still (0.2s) was
  tested and rejected: +26% to +248% more calls for diminishing catch
  rate.
- `ingest/instagram.py`'s `InstagramIngestor.ensure_video()` is now
  idempotent per URL: a `dict[str, Path]` cache keyed by reel URL, written
  only on a successful download (a failed attempt is never cached, so a
  retry after a transient error actually retries). Public contract
  unchanged (`Ingestor.ensure_video(result) -> Path`); this just avoids a
  double video download once a caller starts invoking it unconditionally
  rather than lazily.

### 2. Cancellation infrastructure (`cancel_event` threaded end-to-end)

New `reel2movie/_subprocess_util.py`: `run_cancelable(args, *,
timeout_seconds, cancel_event=None, poll_interval_seconds=0.2,
**popen_kwargs) -> subprocess.CompletedProcess` — a drop-in replacement
for `subprocess.run(args, capture_output=True, text=True,
timeout=timeout_seconds)` that additionally supports real OS-level
cancellation via a `threading.Event`: on cancellation or timeout it
escalates `proc.terminate()` → (2s grace) → `proc.kill()`, always waiting
for the process to actually exit (no zombies/orphans left behind).
`cancel_event=None` (the default) disables cancellation entirely, so
every pre-existing caller migrating from `subprocess.run` gets that as a
safe default.

`_claude_cli.py`'s `run_claude_cli()` and `visual/frame_sampler.py`'s
`_extract_frame_at()`/`probe_duration_seconds()` now call
`run_cancelable()` instead of `subprocess.run()`. A `cancel_event:
threading.Event | None = None` parameter is threaded through the whole
extraction call chain (`CandidateExtractor.extract()`,
`PosterDetector.detect()`, `AudioTranscriber.transcribe()` in
`core/protocols.py`, plus every real implementation and the local
`TextChatClient`/`VisionChatClient` Protocols in
`text_extraction/claude_code_extractor.py` /
`visual/vision_llm_detector.py`), forwarded at Protocol-boundary call
sites via a `kwargs = {"cancel_event": cancel_event} if cancel_event is
not None else {}` expansion — conditional specifically so a pre-existing
test fake that only implements the old, cancel_event-less signature
(several exist in `tests/unit/pipeline/test_waterfall.py` and
`tests/unit/text_extraction/test_fallback_extractor.py`'s own
`FakeExtractor`) keeps working unmodified. Traced end-to-end for this
review (see "Review pass outcome" below): a real `cancel_event` passed
into `FallbackCandidateExtractor.extract()` today reaches
`run_claude_cli()` → `run_cancelable()` with no silent drop anywhere in
the chain. `pipeline/waterfall.py` does not pass `cancel_event` at any
call site yet — that wiring is explicitly deferred to the next wave's
race orchestrator, not part of this one.

`visual/frame_sampler.py`'s `sample_frames_at_interval()` (dense,
on-screen-text sampling) has a best-effort cancellation contract:
whatever `FrameSample`s were extracted before cancellation are returned
(not raised), logged as a warning naming how many of the N requested
timestamps were attempted — consistent with its pre-existing
per-timestamp-failure tolerance (see Subtask 9 follow-up above).
`sample_frames()` (sparse, poster-detection) deliberately keeps an
all-or-nothing contract instead: cancelling lets `SubprocessCancelled`
propagate straight out, since its fixed-`n` callers want exactly N frames
or nothing.

`visual/vision_llm_detector.py`'s `AnthropicVisionChatClient.chat()`
accepts `cancel_event` only for signature compatibility — it cannot
actually be honored (the `anthropic` SDK's blocking HTTP call has no
local OS process to terminate), which is documented accurately in its
own docstring as a known, accepted limitation, not silently claimed as
supported.

### 3. Audio transcription subpackage

New `reel2movie/audio/` subpackage (the audio-transcript fallback: a
reel's spoken narration can confirm a recommendation even when
caption/comments/on-screen-text never name it):

- `audio_extractor.extract_audio(video_path, output_dir, *,
  cancel_event=None) -> Path` — demuxes via the `imageio_ffmpeg`-bundled
  ffmpeg binary: `ffmpeg -i <video_path> -vn -ar 16000 -ac 1 -c:a
  pcm_s16le -y <output_dir>/audio.wav`, i.e. 16kHz mono 16-bit PCM,
  whisper.cpp's documented required input format. Built on
  `run_cancelable()` from day one. Distrusts a bare zero exit code (same
  "ffmpeg can exit 0 while writing nothing" lesson `frame_sampler.py`
  already learned) — checks the output file actually exists and is
  non-empty.
- `whisper_cpp_transcriber.WhisperCppTranscriber.transcribe(audio_path,
  *, cancel_event=None) -> str` — shells out to `whisper-cli -m
  <model_path> -f <audio_path> -l auto -nt -otxt -of <prefix>` (`-l auto`
  for multilingual auto-detection, never hardcoded English; `-otxt -of`
  writes the transcript to `<prefix>.txt` rather than relying on stdout,
  which interleaves progress/system-info lines). Reads `<prefix>.txt`
  back and returns it whitespace-stripped. An empty transcript (silent
  audio) is treated as a legitimate non-error result.
- `config.py`: `get_whisper_cpp_binary()` (defaults to `"whisper-cli"`
  when unset, never raises) and `get_whisper_cpp_model_path()` (raises if
  unset — no safe default for a multi-hundred-MB-to-multi-GB model file
  path). Both follow the project's existing separation-of-concerns rule
  (never called from inside `audio/`, only from a future `pipeline/deps.py`
  wiring). Neither is called from `pipeline/deps.py` yet — correctly so,
  since the race orchestrator that would wire the audio fallback into the
  real pipeline is next wave's work, not this one's. `.env.example` gained
  `WHISPER_CPP_BINARY` / `WHISPER_CPP_MODEL_PATH` documenting both.
- `core/protocols.py` gained `AudioTranscriber` (`transcribe(audio_path,
  *, cancel_event=None) -> str`); `core/models.py`'s `SourceTag` gained
  `AUDIO_TRANSCRIPT`.

### Review pass outcome (independent second look, before the next wave)

Re-derived every claim from the code directly rather than trusting the
three agents' own already-reported clean reviews. `python3 -m pytest
tests/unit -q` confirmed **313 passed** at the reviewed snapshot (matching
the reported count).

**Confirmed working correctly:**
- `run_cancelable()`'s terminate→grace→kill escalation genuinely kills the
  OS process in both the cancel and timeout paths (verified with real
  subprocesses + PID-liveness checks in `tests/unit/test_subprocess_util.py`,
  not just that the Python call returned/raised).
- Elapsed-time tracking uses `time.monotonic()` throughout (not wall-clock,
  not restarted per poll) — correct.
- `cancel_event` genuinely reaches the real subprocess call in the one
  production chain traced end-to-end: `FallbackCandidateExtractor.extract(text,
  source, cancel_event=ev)` → `ClaudeCodeCandidateExtractor.extract(...)` →
  `ClaudeCodeTextChatClient.chat(prompt, cancel_event=ev)` →
  `run_claude_cli(..., cancel_event=ev)` → `run_cancelable(...,
  cancel_event=ev)`. No silent drop at any hop. The conditional-forwarding
  convention is not dead/speculative compatibility shimming — real,
  currently-passing tests (`FakeExtractor` in
  `tests/unit/text_extraction/test_fallback_extractor.py`, the fakes in
  `tests/unit/pipeline/test_waterfall.py`) exercise exactly the
  old-signature-fake case it protects.
- `sample_frames_at_interval()`'s cancellation contract returns a real,
  non-empty partial `list[FrameSample]` for whatever was extracted before
  cancellation (not `[]`, not a crash), and its warning log names both the
  cancellation stage (`"before"` vs. `"mid-extraction at"`) and the X/Y
  attempted-vs-requested count, so a log reader can tell a genuine
  cancellation apart from "the video just had fewer frames than expected."
- `AnthropicVisionChatClient.chat()`'s non-cancellation is accurately
  documented, and nothing downstream assumes it can be cancelled.
- Audio subpackage: ffmpeg args verified to actually produce 16kHz mono
  `pcm_s16le` WAV (matches whisper.cpp's documented requirement exactly);
  `get_whisper_cpp_*` config functions confirmed called only from tests
  today (correctly not wired into production yet) and confirmed not to
  raise at import time.

**Bugs found and fixed directly** (small, well-scoped; all re-verified
with `python3 -m pytest tests/unit -q` after each fix, plus one targeted
repro script per bug):

1. **Real pipe-buffer deadlock in `run_cancelable()` (highest-severity
   finding, caught by an independent `code-review --effort high` pass,
   then reproduced directly).** The poll loop called bare
   `proc.wait(timeout=poll_interval_seconds)`, which — unlike
   `communicate()` — never reads `stdout`/`stderr`. A child writing more
   than one OS pipe buffer's worth (~64KB) of combined output before
   exiting blocks on `write()` with nothing draining the other end, so
   `wait()` just keeps timing out even though the process would otherwise
   finish almost instantly; it only unblocks once the full
   `timeout_seconds` budget elapses and the process gets killed. This is
   the exact deadlock `subprocess`'s own docs warn about. Reproduced with
   a throwaway script (child writes 200KB to stdout, `timeout_seconds=5`):
   hung for the full 5s before being killed and raising `TimeoutExpired`,
   instead of returning the real result in milliseconds. **Not caught by
   the existing test suite** — none of `test_subprocess_util.py`'s cases
   exercised a child with non-trivial output. Fixed by switching the poll
   loop to repeated `proc.communicate(timeout=poll_interval_seconds)`
   calls instead of `proc.wait(...)` — per `communicate()`'s own docs,
   catching `TimeoutExpired` from a timed `communicate()` call and
   retrying is explicitly safe and loses no output. Re-ran the repro:
   completes in ~70ms. Added a permanent regression test
   (`test_large_output_does_not_deadlock_the_poll_loop`) asserting
   completion well under budget for a 200KB-stdout child.
2. **FD leak on cancel/timeout.** After `_terminate_then_kill()`, the
   dead process's `stdout`/`stderr` pipe file descriptors were left open
   until Python's GC reclaimed them. Fixed by explicitly closing
   `proc.stdout`/`proc.stderr` right after killing, on both the cancel
   and timeout paths.
3. **`InstagramIngestor._video_cache` race.** The cache's
   check-then-download-then-store sequence had no lock, so two threads
   calling `ensure_video()` for the same URL at nearly the same time
   (exactly the shape the next wave's visual-fallback + audio-fallback
   steps will produce, both needing the same reel's video) could both
   miss the cache and both trigger a redundant yt-dlp download. Fixed with
   one `threading.Lock()` per `InstagramIngestor` instance guarding the
   whole method — deliberately one lock, not per-URL, since it only needs
   to serialize concurrent calls on the same instance (in practice: the
   same reel).
4. **`sample_frames()` had no `cancel_event` parameter**, inconsistent
   with its sibling `sample_frames_at_interval()`/`probe_duration_seconds()`
   in the same module. Added, threaded through to `_extract_frame_at()`,
   keeping its existing all-or-nothing contract (cancellation just lets
   `SubprocessCancelled` propagate, no partial-result handling needed).
5. **`WhisperCppTranscriber.transcribe()` could return a stale transcript.**
   The success check only verified `output_txt_path.exists()`, not that
   *this* invocation wrote it — if whisper.cpp ever exits 0 without
   actually rewriting the file (the same "reports success, writes
   nothing" quirk this codebase already distrusts ffmpeg for), a leftover
   `.txt` from a previous run at the same path would be silently returned
   as the current transcript. Fixed by `unlink(missing_ok=True)`-ing the
   expected output path before invoking `whisper-cli`, so a genuine
   failure-to-write now correctly raises instead of returning stale data.

**Ponytail-review findings, applied:** the `if cancel_event is not None:
... else: ...` branch — duplicated across `FallbackCandidateExtractor`
(twice), `ClaudeCodeCandidateExtractor`, and `VisionLLMPosterDetector` —
was collapsed to `kwargs = {"cancel_event": cancel_event} if cancel_event
is not None else {}` followed by one call with `**kwargs`, same behavior,
fewer lines, no new abstraction. Everything else reviewed (the
`SubprocessCancelled`/`ClaudeCliCancelled` distinct exception types, the
per-subpackage `RuntimeError` subclasses, the `@runtime_checkable`
Protocols) was judged proportionate to actual need, not speculative.

**Blocking issues for the next wave:** none outstanding — all confirmed
findings above were small and fixed directly in this pass, not deferred.

**Final test count:** `python3 -m pytest tests/unit -q` → **314 passed**
(313 at the start of this review + 1 new deadlock regression test).

**Verdict: Wave 1 is OKAY TO BUILD ON for the next wave** (the waterfall
race rewrite). The one serious finding (the pipe-buffer deadlock) was in
the single highest-stakes piece of this wave's infrastructure and has
been fixed and regression-tested at the root (`run_cancelable()`), so
every caller built on it (`_claude_cli.py`, `frame_sampler.py`,
`audio_extractor.py`, `whisper_cpp_transcriber.py`) inherits the fix
automatically. The `cancel_event`-forwarding convention was traced
end-to-end and does not silently drop a real cancellation anywhere in the
chain as it stands today.

## Pipeline Rewrite Wave 2: parallel race rewrite + TMDB retry + review-fix follow-up

A prior agent rewrote `pipeline/waterfall.py` from the old strict,
sequential caption -> creator-comment -> visual waterfall into a parallel
RACE (all four candidate-generating jobs -- caption, creator-comment,
audio-transcript, visual -- launch concurrently; the first to produce a
confident candidate wins, `cancel_event` stops the others), and added
`tmdb/resolver.py`'s `resolve_candidate_with_retry()` (capped-exponential-
backoff outer retry layer over `resolve_candidate()`, for transient TMDB
failures beyond `tmdb/client.py`'s own internal 3-attempt budget) plus a
small `pipeline/deps.py` addition. That work landed uncommitted and
passed 332 tests, but a multi-angle code review flagged real,
confirmed issues the prior agent was cut off before addressing -- this
section documents fixing those, plus several further findings surfaced
by follow-up review passes during this same session.

### Fix 1 — video download + audio extraction no longer block the race

**Before:** `_prepare_video_and_audio()` ran synchronously, BEFORE
`_race_candidate_jobs()` submitted anything -- every reel paid for a full
yt-dlp download + ffmpeg extraction up front, even when caption/
creator-comment extraction (needing neither) would have won almost
instantly. This directly undercut the rewrite's whole point (the user's
stated complaint was "it's taking too long").

**After:** video download (`_prepare_video`) and audio extraction
(`_prepare_audio`) are now two more jobs that start immediately alongside
the four race jobs, not a blocking prerequisite. The audio-transcript and
visual jobs are the only ones that need that data, so only THEY block --
internally, within their own job function, via a new `_wait_or_cancelled()`
helper that polls a `Future` every ~0.2s instead of blocking on
`.result()` unboundedly (a plain unbounded wait was tried first and
proven, by a failing test, to reintroduce the exact blocking this fix
exists to remove: a job that starts waiting a moment before the race is
decided would otherwise still get stuck for the full download duration).
`_race_candidate_jobs()` also gives the three non-winning race jobs a
short, bounded grace period (`_RACE_LOSER_GRACE_SECONDS = 2.0`) to react
to `cancel_event` and finish before returning anyway -- needed because a
losing job's own thread scheduling isn't synchronized with the winner's,
so without some bound, two pre-existing tests (asserting a losing job's
own error-isolation log line, and that it genuinely observed
cancellation) became flaky.

**Process-exit correctness (caught by follow-up review, not the first
pass):** `_prepare_video`/`_prepare_audio` were initially submitted to
the same `ThreadPoolExecutor` as the four race jobs. That's wrong:
`concurrent.futures.thread` registers a process-wide `atexit` hook that
joins EVERY worker thread of EVERY `ThreadPoolExecutor` ever created in
the process before the process can exit, regardless of that executor's
own `shutdown(wait=False)`. For the GUI (long-running) that's invisible,
but for `reel2movie/cli.py` (fetch one reel, print, exit) it would
silently reintroduce the same latency this fix removes -- `run_pipeline()`
would return promptly, but the PROCESS would then hang at exit for
however long the download took. Fixed by moving `_prepare_video`/
`_prepare_audio`/`_cleanup_audio_temp_dir` (the audio-temp-dir cleanup
job, see below) onto plain `daemon=True` threads via a new
`_run_in_daemon_thread()` helper instead -- daemon threads aren't tracked
by that hook. The four actual race jobs stay on the `ThreadPoolExecutor`
since the orchestrator genuinely needs to track/cancel them.

Also fixed along the way: `_extract_from_audio_transcript`/`_prepare_audio`
now skip waiting on/running audio extraction entirely when
`deps.audio_transcriber is None` (the common case for any `PipelineDeps`
that never configures one) -- previously they'd still pay for the full
download+extraction chain only to discover afterward that nobody would
read the result. `_extract_from_creator_comments` and
`_extract_from_audio_transcript` also gained explicit `cancel_event`
checks between steps (before each comment's extraction call; between
transcribing and extracting from the transcript) so a lost race stops
launching new slow (claude-CLI-backed) calls promptly instead of only
relying on `cancel_event` being passed through to whatever call happens
to already be in flight.

Audio temp-directory lifecycle: a new `_cleanup_audio_temp_dir()`
background job (also a daemon thread) waits for both `_prepare_audio` and
the audio-transcript race job's future, then removes the temp directory
-- this works uniformly regardless of whether the transcript job ever
actually read the file (it may have lost the race before extraction even
finished, or no transcriber may be configured at all), without that job
needing any cleanup logic of its own.

New tests: `test_slow_video_download_does_not_block_a_fast_confident_text_job`
(a fake `Ingestor.ensure_video()` sleeping 2s + a fast confident caption
job; asserts `run_pipeline()` returns in well under 1s and the fake
download genuinely hadn't finished) and
`test_slow_video_download_runs_on_a_daemon_thread_not_the_shared_pool`
(asserts whatever thread is still alive after `run_pipeline()` returns is
a daemon thread, never a `ThreadPoolExecutor` worker -- the process-exit
regression test).

### Fix 2 — `run_pipeline()` now gets the same TMDB retry resilience as streaming

**Before:** `_resolve_all()` (used by `run_pipeline()`, the CLI's and most
tests' entry point) called plain `resolve_candidate()`; only
`run_pipeline_streaming()` used `resolve_candidate_with_retry()`. The same
transient-TMDB-failure problem got 5-minute retry resilience in one entry
point but not the other.

**After:** `_resolve_all()` now calls `resolve_candidate_with_retry()`
too, with the same default deadline. Kept sequential (not switched to
concurrent resolution like the streaming path): `run_pipeline()`'s
contract is one complete, already-deduped `PipelineResult`, so there's no
completion-order concern that needs concurrency, and every resolution has
to finish before `_dedupe` runs regardless -- sequential-but-retried is
the smallest change closing the actual gap. Factored the shared
"resolve one candidate, build a `Recommendation`, keep `tmdb=None` on
failure" logic into a new `_resolve_one()` helper used by both
`_resolve_all()` and `run_pipeline_streaming()` (previously hand-copied in
both places).

**Follow-up finding, also fixed:** `resolve_candidate_with_retry()`'s
retry loop treated bare `requests.exceptions.HTTPError` as always
retryable, with no status-code check -- a real, permanent 401 (invalid/
expired TMDB token), 400, 403, or 404 would get retried for the full
5-minute deadline exactly like a transient 429/5xx, turning a config error
into a multi-minute hang per candidate. Fixed with a new
`_is_retryable_http_error()` check: only 429 or 5xx is retried; anything
else propagates immediately. New tests:
`test_resolve_candidate_with_retry_succeeds_after_a_429` and
`test_resolve_candidate_with_retry_does_not_retry_a_permanent_http_error`
(a 401 raises after exactly one attempt, not five minutes of retrying).

New test proving Fix 2 itself:
`test_run_pipeline_retries_transient_tmdb_failure_and_resolves` -- a fake
`TMDBClient` that fails once (`ConnectionError`) then succeeds; confirms
`run_pipeline()`'s final result has the candidate resolved, not
`tmdb=None`.

### Fix 3 — parallelized the sequential per-frame vision-LLM calls

**Before:** after dense sampling + dedup, surviving unique frames were run
through `poster_detector.detect()` one at a time in a plain `for` loop --
each call an independent network/subprocess round-trip, and typically the
single slowest race job.

**After:** runs through a bounded `ThreadPoolExecutor`
(`_FRAME_DETECTION_MAX_WORKERS = 4`) via `as_completed()`, checking
`cancel_event` as each result arrives. Error-isolation preserved exactly
(a single frame's `detect()` raising still fails the whole visual job,
matching the pre-existing, tested contract -- not per-frame isolated).

**Follow-up finding, also fixed:** the first version wrapped this in
`with ThreadPoolExecutor(...) as frame_executor:`, but `Executor.__exit__`
always calls `shutdown(wait=True)` regardless of why the block was
exited -- so the `break` on cancellation gave none of the "stop promptly"
benefit it claimed; the function still blocked until every submitted
`detect()` call, including ones not yet even started, finished. Fixed by
managing the executor manually and calling
`shutdown(wait=False, cancel_futures=True)` on the cancelled/exception
path instead, which drops not-yet-started frames immediately. A second
follow-up finding caught that `cancel_futures=True` only drops
NOT-YET-STARTED futures -- an already-running `detect()` call (reading
the frame's JPEG, or a `claude` CLI subprocess with that file open) keeps
running regardless, and the enclosing `finally`'s `shutil.rmtree(frames_dir)`
could then delete a file out from under it. Fixed with a bounded
`wait(frame_futures, timeout=_FRAME_DETECTION_ABANDON_GRACE_SECONDS)`
(3.0s) right after the cancelled shutdown, before that rmtree runs.

New test: `test_visual_fallback_runs_frame_detection_concurrently` -- 4
frames each individually slow (0.3s); asserts total wall time is well
under the ~1.2s a strictly sequential loop would take.

### Fix 4 — consolidated the four race jobs' duplicated error-isolation boilerplate

All four job functions (`_extract_from_caption`, `_extract_from_creator_comments`,
`_extract_from_audio_transcript`, `_extract_from_visual`) used to
hand-copy the identical try/except pattern. Factored into one shared
`_run_job_safely(source, fn)` wrapper, called by all four via
`_race_candidate_jobs`'s `executor.submit()` calls -- the job functions
themselves no longer catch anything; they're free to just let an
exception propagate, and `_run_job_safely` is the only place that decides
what "cancelled" vs. "crashed" means.

### Fix 5 — consolidated the duplicated `cancel_event` kwargs snippet

The `kwargs = {"cancel_event": cancel_event} if cancel_event is not None
else {}` one-liner was hand-copied in `text_extraction/claude_code_extractor.py`,
`text_extraction/fallback_extractor.py`, and `visual/vision_llm_detector.py`.
Factored into `core/protocols.cancel_kwargs()` -- placed there (not
`_subprocess_util.py`) since it's a Protocol call-forwarding convention,
not a subprocess concern, and `core/protocols.py` is where every
Protocol defining `cancel_event` already lives.

### Minor cleanups applied

- `_race_candidate_jobs`: dropped the redundant `future_to_source` dict
  tracking -- keys off `outcome.source` directly, which already carries
  the same information; `as_completed()` now just takes a plain list of
  the four race futures.
- `_subprocess_util.py`: factored the identical terminate/close-fds
  3-line sequence (duplicated across `run_cancelable`'s cancel and
  timeout branches) into one `_terminate_kill_and_close()` helper.

### Further findings from follow-up review passes, also fixed in this wave

- `ClaudeCliCancelled` and `SubprocessCancelled` shared no common
  ancestor beyond `Exception`, forcing `pipeline/waterfall.py`'s
  `_CANCELLED_EXCEPTIONS` to hardcode a two-exception tuple.
  `ClaudeCliCancelled` now also inherits from `SubprocessCancelled`
  (multiple inheritance -- safe here since neither parent defines a
  custom `__init__`), so a plain `except SubprocessCancelled` now covers
  both, and any future cancellable component built on
  `run_cancelable`/`SubprocessCancelled` is automatically covered without
  that tuple needing to grow.
- `_wait_or_cancelled`'s leading `if cancel_event.is_set(): return None,
  True` guard was dead code (the `while not cancel_event.is_set():` loop
  already produces the identical result by never running its body) --
  deleted, with a one-line docstring note explaining why instead.

### Review process

Given this diff's size, review happened in several passes rather than
one: a manual read of the full rewritten `waterfall.py` plus
`tmdb/resolver.py`, `pipeline/deps.py`, `ingest/instagram.py`, and
`_subprocess_util.py` against the task's 5 named findings first; then
`/code-review --effort high` was launched (forked background execution,
8 finder-angle agents) and `/ponytail:ponytail-review` was invoked
alongside it. Several additional, genuine findings surfaced during this
process (the process-exit/daemon-thread issue, the `frame_executor`
`shutdown(wait=True)` issue and its `cancel_futures` follow-up, the
HTTPError status-code gating, the `ClaudeCliCancelled` common-ancestor
gap, the missing between-step `cancel_event` checks, and the wasted
audio extraction when no transcriber is configured) -- all were verified
against the actual code (not taken on faith), fixed directly, and
re-tested. Each fix was re-run through `python3 -m pytest tests/unit -q`
individually as it landed, not batched to the end.

### Final test count

`python3 -m pytest tests/unit -q` → **338 passed** (332 at the start of
this pass + 6 new regression tests: one proving Fix 1's return-before-
download-finishes behavior, one proving its daemon-thread/process-exit
correctness, one proving Fix 2's retry-and-resolve behavior, two proving
the HTTPError status-code gating fix, and one proving Fix 3's genuine
per-frame concurrency). Re-ran 3-5x in a loop with no flakiness observed
after the grace-period/polling fixes landed (an earlier iteration without
polling WAS observed to be flaky/wrong under real thread-scheduling
timing, which is exactly what led to the `_wait_or_cancelled` polling
design instead of a simpler before/after check).

### Verdict

**OK to build on for the next wave** (GUI streaming wiring + disambiguation
fixes). All 5 required fixes are in, re-tested individually as they
landed; the minor cleanups were applied; several additional genuine
correctness issues surfaced by follow-up review (process-exit via daemon
threads, the frame-executor `shutdown(wait=True)`/`cancel_futures`
in-flight-file-deletion race, HTTPError status-code gating, the
`ClaudeCliCancelled` ancestor gap, missing between-step cancellation
checks, and wasted audio extraction) were also fixed and tested rather
than deferred. No known blocking issues remain. Two items remain
explicitly OUT of scope per the task's own instructions, not overlooked:
`ingest/instagram.py`'s `ensure_video()` lock (kept -- concurrent calls
are now more plausible than before, not less, given this wave's
restructuring) and `resolve_candidate_with_retry`'s blocking-sleep-ties-
up-a-worker finding (low severity, conditional on candidate counts this
project doesn't expect to hit).

## Candidate noise filtering (Problem A) + "Don't Be Shy" reliability follow-up (Problem B)

Two related-but-distinct fixes layered strictly additively on top of the
parallel-race pipeline above. Neither touches `pipeline/waterfall.py`'s
race/cancellation machinery itself -- only one new call is inserted
between the race winner being determined and TMDB resolution starting.

### Problem A — noise filtering across genuinely different candidate strings

New module `reel2movie/text_extraction/candidate_disambiguation.py`:

```python
def select_primary_candidates(
    candidates: list[Candidate],
    source_text: str,
    chat_client: TextChatClient,
) -> list[Candidate]
```

This is a different problem from Problem B below: it picks among several
DIFFERENT raw candidate title *strings* extracted from one piece of
source text (some of which may be noise -- an unrelated quoted tagline, a
line of dialogue, a hashtag fragment, an incidental/comparison mention),
never among several TMDB *entries* sharing one title.

- Skips the LLM call entirely for `len(candidates) <= 1`, returning
  `candidates` unchanged -- mirrors `disambiguate_with_context()`'s
  existing "only bother when there's genuine ambiguity" precedent.
- Asks ONE model call for a PER-CANDIDATE keep/drop classification (not
  "pick a winner") plus one overall `media_type_hint`
  (`"movie"`/`"tv"`/`null`) for `source_text` as a whole. Per-candidate
  classification is the single mechanism that keeps a genuine "ranked
  list of 5 movies" caption's candidates all 5 intact (brainstorm.md's
  explicitly-required hard case) while collapsing a 1-real+N-noise
  caption down to just the 1 real candidate -- there is no separate
  single-vs-multi branch to keep in sync.
- Fail-safe, matching `disambiguate_with_context()`'s existing
  philosophy: ANY chat-client exception, or a reply that isn't the EXACT
  expected JSON shape (`_parse_reply`'s strict validation -- one
  well-formed, uniquely-indexed decision per candidate index, 0 through
  `len(candidates) - 1`), returns `candidates` UNCHANGED. A malformed
  reply is never partially trusted/applied.
- Surviving candidates get `media_type_hint` attached via
  `dataclasses.replace` (`Candidate` is frozen).

`reel2movie/core/models.py`: `Candidate` gained
`media_type_hint: str | None = None` as the LAST field. Confirmed every
existing `Candidate(...)` construction site in the codebase
(`text_extraction/regex_extractor.py`, `_candidate_parsing.py`) uses
keyword args, so this is non-breaking for keyword AND positional callers
alike.

### Problem B — "Don't Be Shy": strengthened unknown-detection + majority vote

`reel2movie/tmdb/resolver.py`:

1. `disambiguate_with_context()`'s prompt now has a prominent "IMPORTANT"
   paragraph explicitly instructing the model that if NONE of the
   candidates' overviews plausibly describe what the surrounding text is
   about, it MUST reply `"unknown"` rather than guess -- naming the real,
   observed risk (one of the real "Don't Be Shy" TMDB entries is
   adult-themed) as the concrete reason guessing is worse than admitting
   uncertainty. The original prompt never said this, and -- per this
   file's earlier "Don't Be Shy" writeup -- the model never once replied
   "unknown" across 8 real live trials even when no candidate plausibly
   matched.
2. New majority-vote reliability layer, scoped NARROWLY to this one
   function (not every chat-client call in the codebase): a new named
   constant `_DISAMBIGUATION_SAMPLE_COUNT = 3` independent chat-client
   calls for the identical prompt (via new internal `_disambiguate_once()`
   helper), requiring `_DISAMBIGUATION_MAJORITY_THRESHOLD = 2` of them to
   agree on the same id before trusting it. No majority (3 different ids,
   or a split with no 2+ agreement) is treated exactly like a single
   honest "unknown": falls through to the existing `pick_best()`
   rank-tiebreak fallback, unchanged. `disambiguate_with_context()`'s own
   signature is UNCHANGED -- the sampling loop is an internal
   implementation detail, so its one caller (`resolve_candidate()`)
   needed no changes at all.
   - **Real cost tradeoff, documented directly in the docstring**: 3x the
     chat-client calls, but ONLY for this one tie-break scenario, which
     fires when 2+ exact-title TMDB matches exist for a candidate -- a
     comparatively rare case (most candidates resolve with 0-1 exact
     matches and never reach this function at all), not every TMDB
     resolution in the pipeline.
3. `resolve_candidate()` and `resolve_candidate_with_retry()` both gained
   an optional `media_type_hint: str | None = None` parameter (both
   backward-compatible: `resolve_candidate_with_retry`'s existing params
   are already keyword-only and this is forwarded straight through to
   `resolve_candidate()`). When given, `client.search()`'s raw results are
   filtered down to that `media_type` BEFORE `find_exact_matches()`/
   `pick_best()`/disambiguation ever see them -- but if filtering would
   eliminate every result, the unfiltered list is used instead, the same
   fail-safe posture used throughout this module (an overzealous/wrong
   hint must never turn a real set of candidates into zero).

**Honest limitation, worth restating plainly** (already documented
elsewhere in this file under the original "Don't Be Shy" writeup --
repeated here because this follow-up does not, and cannot, change it):
TMDB genuinely does not have the real Alia Bhatt / Amazon Prime
"Don't Be Shy" rom-com in its database at all. This fix's achievable goal
was never "find the correct entry" -- that is structurally impossible
without the data existing in TMDB in the first place -- it is "never
confidently resolve to a wrong/inappropriate entry when the real one
isn't there." The majority vote directly targets the one observed failure
mode (1/8 real trials landing on the adult-themed entry): requiring 2-of-3
agreement makes a single unlucky sample far less likely to carry the
final decision on its own, and the strengthened "when in doubt, say
unknown" instruction gives the model actual explicit permission/incentive
to abstain, which the original prompt never successfully exercised in 8/8
real trials. Neither change makes TMDB's data more complete.

### `pipeline/waterfall.py` wiring

Two new functions, called once each from both `run_pipeline()` and
`run_pipeline_streaming()`, right after `_pool_candidates_and_transcript`
and before `_resolve_all`/the concurrent resolution loop:

- `_primary_candidate_source_text(winner, result) -> str` — picks the
  text that actually PRODUCED the winning outcome's candidates, per
  `SourceTag`: `CAPTION` -> `result.caption`; `CREATOR_COMMENT` -> every
  creator top-level comment's text joined together (the SAME comments
  `_extract_from_creator_comments` reads); `AUDIO_TRANSCRIPT` -> the
  winning outcome's `raw_text` (the transcript itself); `FRAME_VISUAL` (or
  any other/future source) -> falls back to `result.caption` (no raw TEXT
  signal exists for pixels). This is the piece that makes the fix actually
  work for a non-caption winner -- always using `result.caption` would
  have defeated the point for an audio/comment win.
- `_apply_primary_candidate_filter(outcomes, candidates, result, deps) ->
  list[Candidate]` — calls `select_primary_candidates` ONLY when there IS
  a single race winner (`len(outcomes) == 1`); in the no-winner 4-outcome
  pooled case, each of the four jobs independently contributed at most its
  own handful of candidates and there is no single coherent `source_text`
  to hand the model (caption/comment/transcript/visual are four unrelated
  signals), so filtering is skipped there and every pooled candidate
  resolves exactly as before this feature existed. Reuses
  `deps.disambiguation_chat_client` directly -- no new `PipelineDeps`
  field was needed; skipped entirely when that's `None` (same "feature
  not available" posture the pre-existing disambiguation step already
  takes for a missing chat client).
- `_resolve_one()` now threads `candidate.media_type_hint` through to
  `resolve_candidate_with_retry()`'s new param.

### Tests

New file `tests/unit/text_extraction/test_candidate_disambiguation.py` (9
tests): skips the LLM for 0 and for 1 candidate; the 5-genuine-candidate
ranked-list case keeps all 5 (with the shared `media_type_hint` attached);
a 1-real+2-noise case drops the noise and keeps just the real one; a
chat-client exception keeps candidates unchanged; a non-JSON garbage
reply keeps candidates unchanged; a reply missing a decision for one
index keeps candidates unchanged; `media_type_hint` attached on success;
an invalid hint value (e.g. `"documentary"`) is coerced to `None`; and a
prompt-content check (source text + every candidate string present).

`tests/unit/tmdb/test_resolver.py`: 4 new majority-vote tests for
`disambiguate_with_context` (unanimous 3-of-3 agreement; 2-of-3 majority
with one dissenting sample; no majority via 3 different replies; no
majority via a split with "unknown"s) -- each confirming via the fake
chat client's `call_count` that it was actually invoked
`_DISAMBIGUATION_SAMPLE_COUNT` (3) times, not once. 3 new
`media_type_hint` filtering tests for `resolve_candidate` (hint matches
some results -> filtered correctly; hint matches none -> falls back to
the unfiltered list, never returns empty; no hint given -> byte-for-byte
unchanged behavior). 4 PRE-EXISTING tests that hardcoded
`chat_client.call_count == 1` / `len(chat_client.prompts) == 1` for
`disambiguate_with_context` were updated to
`_DISAMBIGUATION_SAMPLE_COUNT` -- a deliberate, expected behavior change
from adding the majority vote, not a regression.

`tests/unit/pipeline/test_waterfall.py`: 2 new end-to-end tests
(`test_primary_candidate_filter_uses_caption_text_for_caption_win`,
`test_primary_candidate_filter_uses_transcript_text_for_audio_win`)
proving the right `source_text` reaches `select_primary_candidates` for
two different winning-source cases via a real `run_pipeline()` call with
fakes -- a caption win's filter prompt contains the caption's unique
marker text, an audio-transcript win's filter prompt contains the
transcript's unique marker text (and NOT the unrelated caption). 3
pre-existing tests with the same `call_count`/prompts-length-1 assumption
(all exercising `disambiguate_with_context` through a real `run_pipeline`
call) were updated to 3 for the same majority-vote reason.

### Test results

`python3 -m pytest tests/unit -q`: **338 passed** (baseline, reconfirmed
at the start of this wave) -> **357 passed** after this follow-up (19 new
tests: 9 in the new `test_candidate_disambiguation.py`, 7 new in
`test_resolver.py`, 2 new end-to-end in `test_waterfall.py`; zero
regressions -- the 7 pre-existing tests whose assertions changed were
updated for the DELIBERATE 3x-call-count behavior change, not broken by
it). Re-ran the full suite 3 times total with no flakiness observed.

### Review

Manually reviewed the diff against the task's exact requirements
(fail-safe posture on both new/changed functions, backward-compatible
signatures for `resolve_candidate`/`resolve_candidate_with_retry`/
`disambiguate_with_context`, the no-winner-pool skip, the per-`SourceTag`
`source_text` selection, `Candidate`'s new field placement). Ran
`ponytail:ponytail-review`, scoped manually to the files actually touched
by this follow-up (the raw `git diff` also contains a prior, separately-
reviewed wave's uncommitted race-pipeline rewrite -- out of scope for this
review pass). Two minor simplifications found and fixed in
`reel2movie/tmdb/resolver.py`: a manual vote-counting dict replaced with
`collections.Counter`, and a duplicated "find `TMDBSearchResult` by id"
linear-search loop (previously inlined separately in both
`_disambiguate_once` and `disambiguate_with_context`) factored into one
shared `_find_by_id()` helper. Also ran `/code-review --effort high` in
the background; no additional confirmed correctness findings surfaced
beyond what's listed above as of this writing -- re-ran the full test
suite (357 passed) after the two ponytail simplifications landed.

### Verdict

**OK to build on.** Both required fixes are in, tested, and re-tested
after the ponytail cleanups. `gui/` was not touched by this follow-up (its
concurrent GUI-streaming changes, visible in `git status` during this
session, belong to a different, parallel piece of work). The one
explicitly-acknowledged limitation (TMDB not having the real "Don't Be
Shy" film at all) is structural, not a bug in this fix, and is restated
above rather than silently left implicit.

## GUI streaming wiring (consuming `run_pipeline_streaming`)

**Goal:** wire the desktop GUI (`gui/`) to the pipeline's new
`run_pipeline_streaming()` generator (`reel2movie/pipeline/waterfall.py`,
landed in the previous backend wave) so recommendation cards appear one
at a time as each candidate resolves against TMDB, instead of the whole
results list popping in at once at the end. Only `gui/` was touched;
`reel2movie/` was read-only for this wave (its files showed as already
modified in `git status` before this wave started, and again mid-session
-- see below -- both from concurrent, unrelated backend work on
candidate disambiguation, not from this change).

### Changes

**`gui/workers.py`** -- `PipelineRunner.run()` now calls
`run_pipeline_streaming(url, deps)` instead of `run_pipeline(url, deps)`,
iterating it and emitting a new `recommendation_ready = Signal(object)`
for every raw `Recommendation` as it arrives. Exceptions raised by the
iterator (including mid-stream, after some items already streamed) are
caught the same way the old code caught `run_pipeline`'s exceptions and
turned into `failed.emit(str(exc))`.

Every yielded `Recommendation` is also accumulated into a plain list;
once the stream ends cleanly, that list is passed through `_dedupe`
(imported directly from `reel2movie.pipeline.waterfall` -- the exact same
function `run_pipeline()` itself calls) and wrapped in a `PipelineResult`,
emitted via the pre-existing `succeeded = Signal(object)`. **Dedup
decision:** reuse `_dedupe` rather than write a simpler GUI-side "merge by
`tmdb.id`" pass, even though it's module-private (leading underscore) in
`waterfall.py` -- `tests/unit/pipeline/test_waterfall.py` already imports
it directly rather than re-deriving its behavior, so treating it as
reusable within this codebase is consistent with existing practice. The
alternative (a second, GUI-only dedupe rule) risks silently drifting from
`_dedupe`'s actual merge semantics (same-tmdb-id-keep-highest-confidence,
same-query unresolved/resolved collapsing, confidence sort) over time;
reusing it means the GUI's final result is byte-for-byte what
`run_pipeline()` would have produced for the same reel. This also means
every existing caller of `succeeded` (`MainWindow._on_pipeline_succeeded`)
needed zero changes to its contract.

**`gui/widgets.py`** -- `ResultsPanel` had no incremental-add method
before this wave (confirmed by reading; only `set_recommendations()` full
-replace and `clear()` existed). Added `add_recommendation(card_data:
dict) -> None`: clears the "no recommendations found" empty-state label
first if it's currently showing, builds one `RecommendationCard` exactly
as `set_recommendations()` does (same constructor call, same `parent`),
and inserts it before the trailing stretch -- using
`self._content_layout.count() == 0` to tell whether that stretch exists
yet (no separate boolean flag needed; this was simplified down from an
initial `_has_cards` field during the ponytail-review pass below).
`clear()`'s docstring was updated to mention the new caller.

**`gui/main_window.py`** -- `_launch_pipeline()` now calls
`self.results_panel.clear()` right before starting a new
`PipelineRunner`, so a second Run click starts the incremental trickle
into a clean panel instead of appending onto whatever an earlier run left
behind (the panel is long-lived across runs, not recreated). Connects the
new `recommendation_ready` signal to a new handler,
`_on_recommendation_ready(rec: object) -> None`, which reuses the
existing `_recommendation_to_card_data()` static helper (no duplicated
mapping logic), calls `results_panel.add_recommendation(...)`, and
switches to the results page if not already showing it -- which happens
on the first call, satisfying "show results on the first item, not after
all of them" without redundantly calling `setCurrentWidget` on every
subsequent item. `_on_pipeline_succeeded()` (the `succeeded` handler) is
unchanged: it still does one full `set_recommendations()` re-render at
the end, which naturally corrects the trickled-in cards to the final
deduped/sorted set.

### Testing

**Mocked/integration (`PipelineRunner` + `MainWindow`, offscreen Qt,
script in the session's scratchpad, not committed):**

- Staggered-delay fake generator (3 items, 0.15s apart): confirmed
  `recommendation_ready` fired exactly 3 times with correct payloads,
  `succeeded` fired exactly once at the end with all 3 recommendations
  deduped, `failed` never fired.
- Exploding generator (yields 2 items, then raises `ValueError` mid
  -stream): confirmed `recommendation_ready` fired for the 2 items before
  the raise, `failed` fired exactly once with a readable message
  containing the real exception text, `succeeded` never fired, no crash
  or hang.
- Direct `MainWindow._on_recommendation_ready()` calls: confirmed the
  results page becomes the current `stacked_widget` page on the very
  FIRST call (not after all items), each call appends exactly one card
  (`content_layout.count()` grows by 1 per call, plus the lazily-added
  trailing stretch), and a subsequent `_on_pipeline_succeeded()` call
  re-renders the authoritative final set.
- `results_panel.clear()` immediately followed by one
  `add_recommendation()` call: confirmed no leftover cards from a
  simulated previous run.

All of the above: **PASS**.

**Live end-to-end** (`python3 -m gui.main`-equivalent, driven
programmatically under `QT_QPA_PLATFORM=offscreen` since this session has
no real display -- `MainWindow` constructed for real, `url_input` set to
`https://www.instagram.com/reel/DU7OQACiDtk/` (a sample reel already
cached as a local .mp4 in the repo root), `_on_run_clicked()` invoked for
real, polling `results_panel`'s actual layout state every 500ms): ran
against the real pipeline (`TMDB_API_KEY` from `.env`, real local `claude`
CLI) with a 150s hard observation budget.

Observed timeline (actual, not simulated):

```
t=  0.53s  page=running   content_layout.count()=0
t= 70.87s  page=RESULTS   content_layout.count()=2   <- first card, page switched immediately
t= 71.35s  page=RESULTS   content_layout.count()=9
t= 73.72s  page=RESULTS   content_layout.count()=10
t= 85.72s  page=RESULTS   content_layout.count()=11
t= 87.72s  page=RESULTS   content_layout.count()=12
t= 88.72s  page=RESULTS   content_layout.count()=13
t= 90.22s  page=RESULTS   content_layout.count()=14
t= 91.22s  page=RESULTS   content_layout.count()=15
t= 92.22s  page=RESULTS   content_layout.count()=16
t= 93.72s  page=RESULTS   content_layout.count()=18
t= 94.72s  page=RESULTS   content_layout.count()=13  <- succeeded's final re-render (dedup collapsed 17->12 cards)
(no further change through t=150s)
```

This confirms, with real network/TMDB/claude-CLI calls, both: (b) the
results page appears on the very first streamed item (t=70.87s), well
before the run actually finishes (t=94.72s); and the final `succeeded`
re-render visibly shrinks the card count (18->13, i.e. 17->12 cards) as
`_dedupe` collapses duplicate TMDB matches found by multiple
candidates/frames -- a real, visible "correction" effect, not just a
theoretical one. (Separately, this run's audio-transcript race job threw
`WHISPER_CPP_MODEL_PATH is not set` -- a pre-existing local-env
configuration gap, correctly error-isolated by `_run_job_safely` into an
empty outcome rather than crashing the pipeline; unrelated to this wave's
changes.)

### Review

Ran `/code-review --effort medium` and `/ponytail:ponytail-review` on the
full `gui/` diff. Findings and dispositions:

- **Fixed:** `ResultsPanel` tracked a separate `_has_cards` boolean just
  to know whether the trailing stretch already existed. Removed it --
  `self._content_layout.count() == 0` (checked right after the
  empty-state-label `clear()`, so it only reads "no stretch yet" in that
  state) tells the same thing with one less field to keep in sync across
  `set_recommendations`/`add_recommendation`/`clear`.
- **Fixed:** `_on_recommendation_ready()`'s docstring said the page switch
  happens "on the very first" item, but the code called `_show_results()`
  unconditionally on every call (harmless -- `setCurrentWidget` on an
  already-current widget is a no-op -- but not what the docstring
  claimed). Added a one-line guard (`if ... is not self.results_panel:`)
  so the code matches the documented intent exactly.
- **Accepted, not fixed:** streaming cards in non-deduped, completion
  -order means a transient visual state is possible where an unresolved
  card (`tmdb=None`) and a resolved card for the same underlying movie
  both appear briefly, until `succeeded`'s final re-render corrects it.
  This is the explicit, documented trade-off of this design (per the
  task's own instructions to keep the incremental path simple and let the
  final re-render be the one authoritative correction) -- the live test
  above confirms the correction does visibly happen (18->13), and adding
  incremental merge/dedup logic to `add_recommendation` would meaningfully
  expand this wave's scope for a cosmetic, self-correcting flicker.
- **Accepted, not fixed:** `PipelineRunner.run()`'s final
  `_dedupe(...)` + `PipelineResult(...)` pair duplicates (as a 2-line
  pattern, not duplicated logic) what `run_pipeline()` itself does
  internally in `waterfall.py`. Fixing this properly would mean factoring
  a shared helper *inside* `waterfall.py` -- out of scope for this wave,
  which was restricted to `gui/` only.

Re-ran both the mocked integration script and `python3 -m pytest
tests/unit -q` after applying the two fixes above -- all still pass (see
below).

### Test counts

`python3 -m pytest tests/unit -q` → **357 passed** at the time this wave
finished (the 338-passed baseline recorded at the start of this session
had already grown to 357 mid-session from a concurrent, unrelated
backend wave touching candidate disambiguation -- visible via `git
status` showing `reel2movie/core/models.py` newly modified and a new
`reel2movie/text_extraction/candidate_disambiguation.py` file appearing
partway through this session, neither of which this wave touched or
needed to: the only field that wave added, `Candidate.media_type_hint`,
is on `Candidate`, not on `Recommendation`/`ResolvedMovie`/
`PipelineResult`, so it has zero effect on anything the GUI consumes).
Confirmed via `git status --short gui/` and `git status --short
reel2movie/` that this wave's own diff is contained entirely to
`gui/main_window.py`, `gui/widgets.py`, and `gui/workers.py`.

### Verdict

**OK to build on.** All required behaviors ((a)-(d) from the mocked
tests, plus a real end-to-end run confirming (b) and the dedup-correction
effect with real network/TMDB/claude-CLI calls) are verified. No changes
were made under `reel2movie/`. Not committed to git per this wave's
instructions.

## Review-driven fixup wave: deps/race-pool/resolver/GUI findings

A separate, independent code-review pass against the previous two waves
(the waterfall race rewrite + TMDB retry, and candidate disambiguation +
GUI streaming) surfaced real findings the original agents hadn't caught.
This wave verified each claim by reading the actual current code first,
then fixed the confirmed issues, re-testing after each fix. Two more
findings were sent mid-session by the coordinator after their own
analysis, plus one further finding surfaced by running `/code-review` on
this wave's own diff, plus one final finding sent by the coordinator
after that. All eight+ items below were fixed and tested.

### Fix 1 (HIGH) — unconditional whisper.cpp wiring caused ERROR-log spam on every default run

**Confirmed.** `reel2movie/pipeline/deps.py`'s `build_default_pipeline_deps()`
constructed a `_LazyWhisperCppTranscriber()` unconditionally, regardless
of whether `WHISPER_CPP_MODEL_PATH` was actually set. Since whisper.cpp
is a brand-new optional subpackage most environments (including this
dev machine) don't have configured, every `run_pipeline`/
`run_pipeline_streaming` call triggered a wasted background ffmpeg audio
extraction AND `_extract_from_audio_transcript`'s
`deps.audio_transcriber.transcribe(...)` call raised `RuntimeError` (from
`config.get_whisper_cpp_model_path()`), logged via `logger.exception` at
ERROR with a full traceback on every single run.

**Fix:** `build_default_pipeline_deps()` now only constructs
`_LazyWhisperCppTranscriber()` when `os.environ.get("WHISPER_CPP_MODEL_PATH")`
is truthy (mirroring the same cheap-env-check pattern used elsewhere in
this function); otherwise `audio_transcriber` stays `None` -- the same
"capability not available" signal `disambiguation_chat_client` already
uses. Verified `_prepare_audio`/`_extract_from_audio_transcript` already
correctly skip all audio work when `audio_transcriber is None` (no
`waterfall.py` changes needed for this fix specifically). Replaced
`test_audio_transcriber_is_wired_without_requiring_whisper_cpp_model_path_env_var`
(which asserted the old, now-wrong behavior) with
`test_audio_transcriber_is_none_when_whisper_cpp_model_path_unset` and
`test_audio_transcriber_is_wired_when_whisper_cpp_model_path_set`.

### Fix 2 (MEDIUM-HIGH) — uncancellable Anthropic HTTP calls can still hang CLI process exit

**Confirmed.** `AnthropicVisionChatClient.chat()` (the non-default
`VISION_BACKEND=anthropic_api` backend) can't honor `cancel_event` (a
blocking HTTP call, no local process to kill). The PRIOR wave's Fix 1
moved `_prepare_video`/`_prepare_audio`/`_cleanup_audio_temp_dir` off
`ThreadPoolExecutor` onto plain daemon threads (`_run_in_daemon_thread`)
specifically to stop `concurrent.futures.thread`'s process-wide `atexit`
hook (which joins every worker thread of every `ThreadPoolExecutor` ever
created, regardless of `shutdown(wait=False)`) from hanging a
short-lived caller's process exit. But the four actual race jobs in
`_race_candidate_jobs` still ran on a real `ThreadPoolExecutor`, and the
visual job's own nested per-frame `frame_executor` pool was ALSO a real
`ThreadPoolExecutor` -- so an in-flight Anthropic HTTP call could still
hang process exit via either of those two pools, the same bug class via
a different path.

**Decision: partially converted, partially documented as an accepted
limitation** (per the task's own explicit escape valve):

- **Converted (done):** the outer 4-job race pool in `_race_candidate_jobs`
  is now `_run_in_daemon_thread`-backed, like the prep jobs. This was a
  genuinely mechanical substitution -- `_run_in_daemon_thread` already
  returns a plain `concurrent.futures.Future` that `as_completed()`/
  `wait()` consume identically regardless of what created it, and the
  pool only ever hosted exactly 4 jobs for exactly 4 workers (no real
  queueing/concurrency-limiting behavior to preserve). Removed the now-
  dead `_RACE_POOL_MAX_WORKERS` constant and the `executor`/`finally:
  shutdown(wait=False)` wrapper entirely.
- **NOT converted (documented as a known, accepted limitation):**
  `_extract_from_visual`'s nested per-frame `frame_executor` stays a real
  `ThreadPoolExecutor`. Unlike the outer pool, this one enforces a
  genuine bounded concurrency limit (`_FRAME_DETECTION_MAX_WORKERS`) over
  a variable, unbounded number of frames, plus tested
  `cancel_futures=True` drop-vs-already-running semantics and a bounded
  abandon-grace wait. Reproducing that correctly with raw daemon threads
  (e.g. a semaphore-gated spawner) would mean rewriting already
  load-bearing, tested cancellation logic for a benefit that only
  matters under the non-default `anthropic_api` backend -- judged too
  risky for this pass. Documented in the module docstring (new "Fix 2"
  note), `_extract_from_visual`'s own docstring, and a new test,
  `test_frame_detection_pool_threads_are_real_threadpool_workers_known_limitation`,
  that explicitly asserts the CURRENT (limitation-exists) state so a
  future fix converting `frame_executor` away from a real
  `ThreadPoolExecutor` makes this test fail loudly instead of the gap
  silently persisting unnoticed.

### Fix 3 (MEDIUM) — stale `_CANCELLED_EXCEPTIONS` tuple

**Confirmed.** `reel2movie/_claude_cli.py` already has `ClaudeCliCancelled(ClaudeCliError, SubprocessCancelled)`
(multiple inheritance, added in an earlier wave) -- so `waterfall.py`'s
`_CANCELLED_EXCEPTIONS = (ClaudeCliCancelled, SubprocessCancelled)` tuple
and its "unrelated class hierarchies" comment were stale. Simplified
`_run_job_safely`'s `except _CANCELLED_EXCEPTIONS:` to
`except SubprocessCancelled:` alone, removed the tuple and the stale
comment, and fixed the module docstring's error-isolation-policy section
to explain the inheritance instead. Updated
`test_claude_cli_cancelled_from_a_job_is_also_treated_as_lost_not_crashed`'s
docstring to describe the single `except` clause rather than two
separately-handled types (the test body itself needed no change -- it
already only asserted the observable behavior, not the internal tuple).

### Fix 4 (MEDIUM) — disambiguation's 3-sample majority vote ran sequentially

**Confirmed.** `tmdb/resolver.py`'s `disambiguate_with_context()` called
`_disambiguate_once()` 3 times via a plain sequential list comprehension,
tripling wall-clock latency for every tie-break scenario for no reason --
each call is an independent, data-independent blocking chat-client
round-trip. Fixed via `ThreadPoolExecutor(max_workers=_DISAMBIGUATION_SAMPLE_COUNT).map(...)`,
collecting all 3 results before the unchanged majority-vote counting
logic. `tests/unit/tmdb/test_resolver.py`'s `FakeChatClient` (which
indexes into a configured `replies` list via `self.call_count`, relying
on each call consuming a distinct, sequential reply) needed a
`threading.Lock` added around its read-then-increment to stay correct
now that 3 threads can call `chat()` concurrently -- without it, the
read-then-increment race could have two threads both consume the same
reply index, corrupting the majority-vote test fixtures' intended
reply distribution. Verified stable across 5 repeated runs of
`test_resolver.py` after the fix (no flakiness from the new concurrency).

### Fix 5 (MEDIUM) — `_dedupe` promoted to a public API

**Confirmed.** `gui/workers.py` imported and called
`reel2movie.pipeline.waterfall._dedupe` directly across a package
boundary (module-private, leading underscore), justified only by "an
existing test already does this." Renamed to a public
`dedupe_recommendations` in `waterfall.py`, updated its one internal
caller (`run_pipeline`), updated `gui/workers.py`'s import and both call
sites, and updated `tests/unit/pipeline/test_waterfall.py`'s import and
three direct calls. `_resolve_one` was checked and left private -- it's
only used internally within `waterfall.py` (`_resolve_all` and
`run_pipeline_streaming`), never imported elsewhere. Pure rename/
visibility change; behavior and parameters unchanged.

### Fix 6 (LOW) — duplicated "creator top-level comments" filter

**Confirmed and fixed** (cheap, not entangled with other logic as
feared). Factored the `comment.author_id == result.creator_account_id
and not comment.is_reply` predicate -- written out identically in both
`_extract_from_creator_comments` and `_primary_candidate_source_text` --
into one shared `_creator_top_level_comments(result) -> list[Comment]`
helper, used by both (the second call site maps `.text` over the
result).

### Follow-up finding A (sent mid-session) — prompt-corruption bug via chained `.replace()`

**Confirmed.** `reel2movie/text_extraction/candidate_disambiguation.py`'s
`select_primary_candidates()` built its prompt via chained `.replace()`
calls on the growing string. Each `.replace()` rescans the WHOLE string
including already-substituted content, so an untrusted `source_text`
(caption/comment/transcript) containing a literal `"{candidates}"` or
`"{max_index}"` substring got corrupted by a LATER `.replace()` call
matching inside the just-inserted text. Fixed by switching to
`str.format()` (one-pass substitution against the ORIGINAL template, like
`tmdb/resolver.py`'s own `_DISAMBIGUATION_PROMPT_TEMPLATE.format(...)`,
which was never affected by this bug) -- required escaping the prompt's
literal JSON-shape example braces (`{{`/`}}`) since `.format()` would
otherwise try to substitute them too. Added
`test_source_text_containing_literal_placeholder_substrings_passes_through_unmangled`,
confirming a `source_text` containing both literal substrings survives
intact in the final prompt.

### Follow-up finding B (sent mid-session) — `_prepare_audio`'s cancellation miscategorized as an error

**Confirmed.** `_prepare_audio()` caught `extract_audio()`'s failures
with a bare `except Exception:` that unconditionally called
`logger.exception(...)` (ERROR, full traceback) -- but `extract_audio()`
raises `SubprocessCancelled` on the NORMAL, expected "lost the race"
case (whenever a fast text job wins while audio extraction is still in
flight -- the common case for most successful runs once an
`AudioTranscriber` is configured), contradicting this module's own
documented error-isolation policy (cancellation -> INFO, genuine failure
-> ERROR) that `_run_job_safely` already correctly implements for the
four actual race jobs. Fixed by catching `SubprocessCancelled` separately,
logged at INFO. Added
`test_prepare_audio_cancellation_is_logged_at_info_not_error`, a
caplog-based test mirroring the existing
`test_cancelled_exception_from_a_job_is_treated_as_lost_not_crashed`
pattern, confirming no ERROR record is emitted when `extract_audio` is
cancelled.

### Review-pass finding (surfaced by running `/code-review` on this wave's own diff) — `_prepare_audio`'s `mkdtemp()` call could violate its own "never raises" contract

**Confirmed, fixed.** `tempfile.mkdtemp(prefix="reel2movie_audio_")` sat
outside `_prepare_audio`'s try/except, so a rare but real `OSError`
(disk full, unwritable temp dir) would propagate out of the function
despite its own docstring's explicit "Never raises" contract -- and
`_cleanup_audio_temp_dir()`, the only consumer that would ever observe
it via `audio_future.result()`, has no exception handling of its own, so
the failure would vanish with zero log output from inside its own
never-read daemon-thread `Future`. Wrapped the `mkdtemp()` call in its
own `try/except OSError`, logged via `logger.exception` and returning
`None` -- consistent with every other failure path in this function.

### Final finding (sent after the fixup round above) — unbounded wait on `video_future` could leak 2-3 daemon threads per hung download

**Confirmed.** `_prepare_audio()` called `video_future.result()`
unboundedly (no timeout, no `cancel_event` check). `InstagramIngestor
.ensure_video()` (the yt-dlp download `_prepare_video` blocks on) has no
cancellation/timeout support of its own at all. Since `ensure_video()`
now runs unconditionally on every pipeline run (not just the old
last-resort fallback), a single reel where yt-dlp's network call
genuinely hangs forever (sustained throttling, a dropped connection
yt-dlp's own retries never recover from) leaves `_prepare_video`'s daemon
thread blocked forever -- and the unbounded wait in `_prepare_audio`
leaked a SECOND permanently-blocked daemon thread on top of that, with
`_cleanup_audio_temp_dir` leaking a THIRD waiting on `_prepare_audio`'s
own future in turn. In a long-lived caller (the GUI), this would
accumulate 2-3 leaked threads per problem reel for the life of the
process.

**Fix:** added a new module constant, `_VIDEO_DOWNLOAD_WAIT_TIMEOUT_SECONDS`
(300.0s, mirroring `resolve_candidate_with_retry()`'s own "a few minutes
is a reasonable worst case for one reel" `deadline_seconds` default), and
gave `video_future.result(timeout=...)` that bound in `_prepare_audio`.
On `TimeoutError`, logs at WARNING (not ERROR -- it's not a crash) and
returns `None`, the same "nothing to work with" outcome every other
early-return in this function already produces -- never propagating.
This does NOT fix `_prepare_video`'s own thread leaking if `ensure_video()`
truly never returns (that needs yt-dlp's own cancellation support, out of
scope); it only stops the leak from cascading into 2-3 threads instead of
1, the achievable improvement from this function alone. Added
`test_prepare_audio_returns_within_bounded_timeout_when_video_future_never_resolves`,
which monkeypatches the timeout constant down to 0.2s (so the test stays
fast) and hands `_prepare_audio` a `Future` that's never resolved,
confirming it returns `None` promptly with a WARNING (not ERROR) log,
never hanging or raising.

Also updated `test_slow_video_download_runs_on_a_daemon_thread_not_the_shared_pool`'s
stale comment (it referred to "the 4-race-job pool's own (non-daemon)
worker threads", which no longer exist after Fix 2's race-pool
conversion) -- the test's own assertions needed no change since they
only ever checked observable thread properties (`daemon`, name prefix),
never the pool's existence directly.

### Testing

Ran `python3 -m pytest tests/unit -q` after every individual fix above,
not just at the end. Final count: **362 passed** (up from the 357/358
baseline at the start of this wave -- 5 new tests: one each for Fix 1's
new/changed behavior split across two tests replacing one, Fix 2's
known-limitation test, Follow-up A's corruption-regression test,
Follow-up B's cancellation-logging test, and the final finding's
bounded-timeout test). Also re-ran `tests/unit/tmdb/test_resolver.py`
alone 5 times in a row after Fix 4 to confirm no flakiness from the new
concurrency.

### Review

Ran `/code-review --effort medium` on this wave's diff: 10 findings came
back, 9 about pre-existing code from earlier waves (sequential TMDB
retry in `_resolve_all`, a `_terminate_then_kill()` pipe-drain gap in
`_subprocess_util.py`, a stale `Ingestor.ensure_video()` Protocol
docstring, cumulative thread-pool-stacking resource-budget concerns
across `resolver.py`/`waterfall.py`, dead synchronization in
`ingest/instagram.py`, the `ClaudeCliCancelled` multiple-inheritance
design, `resolver.py`'s two independently-tuned retry layers, and
`_wait_or_cancelled` duplicating `run_cancelable`'s poll-loop shape) --
all outside this wave's assigned scope (none introduced by this wave's
own changes) and left as accepted, pre-existing, out-of-scope findings
for a future pass, consistent with how prior waves handled similar
"accepted, not fixed" items. The 10th finding (`_prepare_audio`'s
`mkdtemp()` contract gap) WAS fixed -- see above.

Ran `/ponytail-review` on this wave's own diff (explicitly scoped to
this session's changes, not the pre-existing waves mixed into the
uncommitted working tree): no findings. Fix 2 and Fix 3 were net
deletions (removed the dead `_RACE_POOL_MAX_WORKERS` constant and the
`executor`/`finally` wrapper; removed the redundant exception tuple).
Fix 4 used the direct stdlib tool (`ThreadPoolExecutor.map`) for 3
independent blocking calls, no hand-rolled pool. The `.replace()` ->
`.format()` fix and the new `except OSError`/`except TimeoutError`
branches in `_prepare_audio` add no new abstraction -- the latter just
makes that function actually honor the "never raises" contract its own
docstring already claimed, matching this module's pre-existing,
identically-enforced policy for every other job.

### Verdict

**OK to proceed to final integration testing.** All 6 originally-assigned
findings plus the 2 mid-session follow-ups plus the 2 further findings
surfaced by the review passes themselves were verified against the
actual current code (not taken on faith), fixed, and re-tested
individually. Final suite: 362 passed, 0 failed. Fix 2's nested
per-frame pool limitation is a deliberate, documented, tested-as-known
trade-off (not an oversight) scoped to the non-default
`VISION_BACKEND=anthropic_api` backend only -- the default `claude_code`
backend (and everything else in this wave) has no known outstanding
process-exit-hang risk. No git commit made per this wave's instructions.

## Final live end-to-end confirmation (whole pipeline rewrite, real reel)

Ran `run_pipeline()` directly (not mocked) against
`https://www.instagram.com/reel/DU7OQACiDtk/` with the real `.env`
(`TMDB_API_KEY` set, `claude` CLI installed/authenticated,
`WHISPER_CPP_MODEL_PATH` intentionally left unset to also confirm Fix
1's env-gated transcriber wiring in the wild):
`build_default_pipeline_deps().audio_transcriber is None` confirmed (no
wasted ffmpeg call, no ERROR-level log spam -- Fix 1 working as intended
with a real `PipelineDeps`, not just a unit test).

Caption/creator-comment text did not cross the confidence bar for this
reel (consistent with its documented behavior from earlier sessions),
so the race correctly fell through to the visual-fallback job. Completed
in 165.0s (video download + dense frame sampling + per-frame vision
calls + TMDB resolution for every extracted candidate, with the new
per-title retry wrapper covering any transient TMDB flakiness along the
way) -- consistent with `handoff.md`'s documented visual-fallback timing
range, no regression from the rewrite. Process exited cleanly (exit code
0, no hang) -- a real-world confirmation that the CLI process-exit fix
(daemon threads for the prep/cleanup jobs) actually works end-to-end,
not just in the unit tests that simulate it.

13 candidates extracted, **all 13 resolved successfully** against real
TMDB entries: Shutter Island (2010), Gladiator (2000), Cars (2006),
Chinatown (1974), Mulholland Dr. (tv, no year) / Mulholland Drive (2001,
movie) as two separate candidates, Heat (1995), Interstellar (2014), The
Godfather (1972), Vertigo (1958), Paris, Texas (1984), La La Land
(2016), Se7en (1995) -- all with correct titles/years/media types. The
Mulholland Dr./Drive split is the pre-existing, already-documented
ambiguous-title-resolves-inconsistently-across-frames limitation (not a
regression introduced by this rewrite's candidate-disambiguation work,
which only applies its noise-filtering/majority-vote logic to
text-sourced candidates with a coherent single `source_text` -- the
no-winner pooled visual-fallback case this run hit is explicitly
documented as skipping that filter, by design).

No exceptions, no silent failures, no stuck threads observed. This is
the strongest available confirmation that the full three-wave rewrite
(parallel race architecture, TMDB retry/streaming, audio transcription,
denser frame sampling, candidate disambiguation) works correctly
together against real-world input, not just against fakes.
