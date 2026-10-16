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
