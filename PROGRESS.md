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
