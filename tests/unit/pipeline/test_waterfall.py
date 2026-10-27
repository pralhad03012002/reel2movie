"""Tests for `pipeline/waterfall.py`'s parallel candidate-extraction race
(`run_pipeline` / `run_pipeline_streaming` / `_race_candidate_jobs`).

Fakes for all five Protocols (`Ingestor`, `CandidateExtractor`,
`PosterDetector`, `TMDBClient`, `AudioTranscriber`) live in this file; none
of them touch the network, a subprocess, or any real third-party client.
`sample_frames_at_interval`/`probe_duration_seconds`/`dedupe_similar_frames`/
`extract_audio` (free functions, not Protocol methods) are monkeypatched at
`reel2movie.pipeline.waterfall.<name>` -- the names waterfall.py imports
them under.

Under the race model, EVERY job (caption, creator-comment, audio-transcript,
visual) always launches concurrently for every reel -- there is no more
sequential short-circuiting to assert against. Tests that used to prove
"a confident early step means a later step never runs at all" have been
rewritten to prove the new equivalent contract instead: "a confident job
wins the race, and the pool/final recommendations reflect only its
candidates" (the other three jobs still physically run -- with these fast,
synchronous fakes they typically finish anyway -- but their output is
discarded once a winner is found, and the shared `cancel_event` passed to
every job is observably set once that happens).

An autouse fixture (`_patch_cheap_defaults` below) monkeypatches
`extract_audio` and `sample_frames_at_interval` to fast, no-ffmpeg fakes by
default for every test in this file: `ensure_video()`+`extract_audio()` now
run unconditionally, upfront, for every reel (not just once some fallback
step is "reached"), and `sample_frames_at_interval` is one of the four
race jobs that always launches too -- without this, every single test
below would pay for real ffmpeg subprocess calls against a
`/fake/video.mp4` path that doesn't exist on disk, for no reason. Tests
that actually exercise visual/audio behavior override these again with
their own more specific `monkeypatch.setattr` calls, which take precedence
(they run during the test body, after this fixture's setup).
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import requests
from PIL import Image

from reel2movie._claude_cli import ClaudeCliCancelled
from reel2movie._subprocess_util import SubprocessCancelled
from reel2movie.core.models import (
    Candidate,
    Comment,
    FrameSample,
    IngestResult,
    Platform,
    Recommendation,
    ResolvedMovie,
    SourceTag,
    TMDBSearchResult,
)
from reel2movie.pipeline.deps import PipelineDeps
from reel2movie.pipeline.waterfall import (
    CONFIDENCE_THRESHOLD,
    _prepare_audio,
    dedupe_recommendations,
    run_pipeline,
    run_pipeline_streaming,
)

URL = "https://instagram.com/reel/fake123/"


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class FakeIngestor:
    """Fake `Ingestor`: configurable metadata/video result, or a raise.

    `ensure_video_delay_seconds`, if set, makes `ensure_video()` sleep
    that long before returning -- used to prove (Fix 1) that a slow
    download never blocks the race/orchestrator from returning once a
    fast, confident text job has won. `ensure_video_finished_event` is
    set right after that sleep (if any) completes, so a test can assert
    the download genuinely hadn't finished yet by the time `run_pipeline()`
    returned, not just that the pipeline happened to be fast.
    """

    metadata: IngestResult | None = None
    metadata_error: Exception | None = None
    video_path: Path = Path("/fake/video.mp4")
    ensure_video_error: Exception | None = None
    ensure_video_delay_seconds: float = 0.0
    fetch_metadata_calls: list[str] = field(default_factory=list)
    ensure_video_calls: list[IngestResult] = field(default_factory=list)
    ensure_video_finished_event: threading.Event = field(default_factory=threading.Event)

    def fetch_metadata(self, url: str) -> IngestResult:
        self.fetch_metadata_calls.append(url)
        if self.metadata_error is not None:
            raise self.metadata_error
        assert self.metadata is not None
        return self.metadata

    def ensure_video(self, result: IngestResult) -> Path:
        self.ensure_video_calls.append(result)
        if self.ensure_video_delay_seconds:
            time.sleep(self.ensure_video_delay_seconds)
        self.ensure_video_finished_event.set()
        if self.ensure_video_error is not None:
            raise self.ensure_video_error
        return self.video_path


@dataclass
class FakeCandidateExtractor:
    """Fake `CandidateExtractor`.

    `by_text` overrides take priority (keyed by the exact `text` passed
    in -- useful for returning different candidates per comment); falling
    back to `by_source` (keyed by `SourceTag`) otherwise. Every call is
    recorded in `calls` (text, source) -- same shape as before the race
    rewrite, so existing call-list assertions keep working -- with each
    call's `cancel_event` recorded in parallel in `cancel_events`, for
    tests that need to confirm cancellation was actually signaled.

    `error_by_source` raises a specific exception only for calls with a
    matching `SourceTag` (used to simulate "this ONE race job crashed/was
    cancelled" deterministically, regardless of which job happens to run
    first under real concurrency) -- `error` (unconditional) is kept for
    existing tests that don't care which source raises.

    `block_seconds_by_source`, if set for a given `SourceTag`, makes a
    call for that source busy-wait (checking `cancel_event` every 10ms)
    for up to that many seconds OR until `cancel_event` fires, whichever
    is first -- recording the source in `observed_cancelled_sources` if
    it actually noticed cancellation. This is what makes the genuine
    concurrent-race test below possible without a real subprocess.
    """

    by_text: dict[str, list[Candidate]] = field(default_factory=dict)
    by_source: dict[SourceTag, list[Candidate]] = field(default_factory=dict)
    error: Exception | None = None
    error_by_source: dict[SourceTag, Exception] = field(default_factory=dict)
    block_seconds_by_source: dict[SourceTag, float] = field(default_factory=dict)
    calls: list[tuple[str, SourceTag]] = field(default_factory=list)
    cancel_events: list["threading.Event | None"] = field(default_factory=list)
    observed_cancelled_sources: set[SourceTag] = field(default_factory=set)

    def extract(
        self, text: str, source: SourceTag, *, cancel_event=None
    ) -> list[Candidate]:
        self.calls.append((text, source))
        self.cancel_events.append(cancel_event)

        block_seconds = self.block_seconds_by_source.get(source)
        if block_seconds is not None:
            deadline = time.monotonic() + block_seconds
            while time.monotonic() < deadline:
                if cancel_event is not None and cancel_event.is_set():
                    self.observed_cancelled_sources.add(source)
                    break
                time.sleep(0.01)

        if source in self.error_by_source:
            raise self.error_by_source[source]
        if self.error is not None:
            raise self.error
        if text in self.by_text:
            return list(self.by_text[text])
        return list(self.by_source.get(source, []))


@dataclass
class FakePosterDetector:
    """Fake `PosterDetector`, keyed by frame path."""

    responses: dict[Path, list[Candidate]] = field(default_factory=dict)
    error: Exception | None = None
    calls: list[FrameSample] = field(default_factory=list)
    cancel_events: list["threading.Event | None"] = field(default_factory=list)

    def detect(self, frame: FrameSample, *, cancel_event=None) -> list[Candidate]:
        self.calls.append(frame)
        self.cancel_events.append(cancel_event)
        if self.error is not None:
            raise self.error
        return list(self.responses.get(frame.path, []))


@dataclass
class FakeAudioTranscriber:
    """Fake `AudioTranscriber`."""

    transcript: str = ""
    error: Exception | None = None
    calls: list[Path] = field(default_factory=list)
    cancel_events: list["threading.Event | None"] = field(default_factory=list)

    def transcribe(self, audio_path: Path, *, cancel_event=None) -> str:
        self.calls.append(audio_path)
        self.cancel_events.append(cancel_event)
        if self.error is not None:
            raise self.error
        return self.transcript


@dataclass
class FakeTMDBClient:
    """Fake `TMDBClient`, keyed by exact query string (falls back to a default)."""

    results_by_query: dict[str, list[TMDBSearchResult]] = field(default_factory=dict)
    default_results: list[TMDBSearchResult] = field(default_factory=list)
    calls: list[tuple[str, int | None]] = field(default_factory=list)

    def search(
        self, query: str, year: int | None = None
    ) -> list[TMDBSearchResult]:
        self.calls.append((query, year))
        return list(self.results_by_query.get(query, self.default_results))


@dataclass
class SleepyFakeTMDBClient:
    """Fake `TMDBClient` whose `search()` sleeps a configurable amount per
    query -- used to prove `run_pipeline_streaming` yields recommendations
    in actual TMDB-resolution COMPLETION order, not input/pool order.
    """

    sleep_seconds_by_query: dict[str, float] = field(default_factory=dict)
    result_by_query: dict[str, TMDBSearchResult] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def search(
        self, query: str, year: int | None = None
    ) -> list[TMDBSearchResult]:
        self.calls.append(query)
        time.sleep(self.sleep_seconds_by_query.get(query, 0.0))
        result = self.result_by_query.get(query)
        return [result] if result is not None else []


@dataclass
class FlakyFakeTMDBClient:
    """Fake `TMDBClient` whose `search()` raises a retryable exception
    (`requests.exceptions.ConnectionError`, one of
    `tmdb.resolver._RETRYABLE_EXCEPTIONS`) a configurable number of times
    before finally succeeding -- used to prove (Fix 2) that
    `run_pipeline()`'s resolution step actually goes through
    `resolve_candidate_with_retry()`'s outer backoff loop, not plain
    `resolve_candidate()` (which would give up on the very first raise).
    """

    fail_times: int = 0
    result: TMDBSearchResult | None = None
    calls: int = 0

    def search(self, query: str, year: int | None = None) -> list[TMDBSearchResult]:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise requests.exceptions.ConnectionError("transient TMDB failure")
        return [self.result] if self.result is not None else []


@dataclass
class FakeChatClient:
    """Fake `TextChatClient` for the disambiguation step -- records every
    `context` it was asked to disambiguate with (via the full prompt
    string, since `resolve_candidate`/`disambiguate_with_context` don't
    pass `context` to the chat client any other way)."""

    reply: str = "unknown"
    prompts: list[str] = field(default_factory=list)

    def chat(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.reply


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ingest_result(
    *,
    caption: str = "",
    creator_account_id: str = "creator-1",
    comments: list[Comment] | None = None,
    duration_seconds: float | None = 30.0,
) -> IngestResult:
    return IngestResult(
        platform=Platform.INSTAGRAM,
        url=URL,
        caption=caption,
        creator_account_id=creator_account_id,
        comments=comments or [],
        duration_seconds=duration_seconds,
    )


def _exact_match_result(query: str, *, tmdb_id: int = 1) -> TMDBSearchResult:
    """A TMDBSearchResult whose title exactly matches `query`.

    Gives `tmdb/scoring.py`'s real formula a title_similarity of 1.0 and
    rank_bonus of 1.0 (original_rank=0), comfortably clearing
    `MIN_MATCH_SCORE` without needing to mock scoring itself.
    """
    return TMDBSearchResult(
        id=tmdb_id,
        title=query,
        year=None,
        poster_path=None,
        overview="",
        popularity=10.0,
        original_rank=0,
        media_type="movie",
    )


def _make_deps(
    *,
    ingestor: FakeIngestor,
    text_extractor: FakeCandidateExtractor,
    poster_detector: FakePosterDetector | None = None,
    tmdb_client: FakeTMDBClient | None = None,
    audio_transcriber: FakeAudioTranscriber | None = None,
    frame_interval_seconds: float = 1.0,
) -> PipelineDeps:
    return PipelineDeps(
        ingestor=ingestor,
        text_extractor=text_extractor,
        poster_detector=poster_detector or FakePosterDetector(),
        tmdb_client=tmdb_client or FakeTMDBClient(),
        frame_interval_seconds=frame_interval_seconds,
        audio_transcriber=audio_transcriber,
    )


def _identity_dedupe(frames, threshold=None):
    """Pass-through fake for `dedupe_similar_frames`, for tests that don't
    care about dedup behavior itself (see module docstring)."""
    return list(frames)


@pytest.fixture(autouse=True)
def _patch_cheap_defaults(monkeypatch, tmp_path):
    """See module docstring: fast, no-ffmpeg defaults for `extract_audio`
    and `sample_frames_at_interval`, applied to every test in this file,
    since both now always run (concurrently, as race jobs) for every
    reel. Individual tests override either again with their own
    `monkeypatch.setattr` when they actually want to exercise that
    behavior.
    """
    import reel2movie.pipeline.waterfall as waterfall_module

    # Its own dedicated subdirectory, not `tmp_path` directly: production
    # `_prepare_audio` always writes into a fresh `tempfile.mkdtemp()`
    # directory containing nothing but `audio.wav`, and
    # `_cleanup_audio_temp_dir` removes that whole directory
    # (`audio_path.parent`) once it's no longer needed. If this fake
    # instead handed back a path living directly in the shared `tmp_path`
    # root, that same cleanup would `rmtree` `tmp_path` itself -- wiping
    # out whatever other per-test fixture files a test wrote there too.
    fake_audio_dir = tmp_path / "fake_audio"
    fake_audio_dir.mkdir()
    fake_audio_path = fake_audio_dir / "fake_audio.wav"
    fake_audio_path.write_bytes(b"\x00")

    def fake_extract_audio(video_path, output_dir, *, cancel_event=None):
        return fake_audio_path

    def fake_sample_frames_at_interval(
        video_path, interval_seconds, duration_seconds, **kwargs
    ):
        return []

    monkeypatch.setattr(waterfall_module, "extract_audio", fake_extract_audio)
    monkeypatch.setattr(
        waterfall_module, "sample_frames_at_interval", fake_sample_frames_at_interval
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_confidence_threshold_matches_regex_extractor_high_tier():
    from reel2movie.text_extraction.regex_extractor import HIGH_CONFIDENCE

    assert CONFIDENCE_THRESHOLD == HIGH_CONFIDENCE


def test_caption_confident_wins_the_race_and_other_jobs_are_cancelled():
    """Rewritten from the old "...short_circuits_comment_and_visual" test:
    under the race model, every job still launches (ensure_video now runs
    UNCONDITIONALLY for every reel, not just once a fallback step is
    reached), but a confident caption candidate still wins outright --
    the final recommendations reflect only the caption job's output, and
    the shared cancel_event the other three jobs were given ends up set.
    """
    caption_candidate = Candidate(
        raw_text="Inception (2010)", source=SourceTag.CAPTION, confidence=0.9
    )
    ingestor = FakeIngestor(metadata=_ingest_result(caption="Inception (2010)"))
    extractor = FakeCandidateExtractor(
        by_source={SourceTag.CAPTION: [caption_candidate]}
    )
    poster_detector = FakePosterDetector()
    tmdb_client = FakeTMDBClient(
        default_results=[_exact_match_result("Inception (2010)")]
    )
    deps = _make_deps(
        ingestor=ingestor,
        text_extractor=extractor,
        poster_detector=poster_detector,
        tmdb_client=tmdb_client,
    )

    result = run_pipeline(URL, deps)

    # ensure_video now runs unconditionally, once, for every reel.
    assert len(ingestor.ensure_video_calls) == 1
    # No comments on this reel, so the creator-comment job's loop never
    # calls the extractor at all; the only recorded call is the caption
    # job's. (The audio job has no `audio_transcriber` configured, so it
    # never calls the extractor either; the visual job's patched
    # `sample_frames_at_interval` returns no frames, so the poster
    # detector is never called.)
    assert extractor.calls == [("Inception (2010)", SourceTag.CAPTION)]
    assert poster_detector.calls == []

    assert len(result.recommendations) == 1
    rec = result.recommendations[0]
    assert rec.source == SourceTag.CAPTION
    assert rec.tmdb is not None
    assert rec.tmdb.id == 1

    # Proof the race's shared cancel_event was actually signaled once the
    # caption job was found confident.
    assert extractor.cancel_events[0] is not None
    assert extractor.cancel_events[0].is_set()


def test_creator_comment_confident_wins_the_race_and_filters_comments():
    comment_candidate = Candidate(
        raw_text="Parasite (2019)", source=SourceTag.CREATOR_COMMENT, confidence=0.9
    )
    comments = [
        Comment(
            id="c1",
            author_id="creator-1",
            text="Parasite (2019)",
            is_reply=False,
        ),
        Comment(
            id="c2",
            author_id="someone-else",
            text="Avatar (2009)",  # not the creator -> must be excluded
            is_reply=False,
        ),
        Comment(
            id="c3",
            author_id="creator-1",
            text="Interstellar (2014)",  # creator's own reply -> excluded
            is_reply=True,
        ),
    ]
    ingestor = FakeIngestor(
        metadata=_ingest_result(caption="not a confident caption", comments=comments)
    )
    extractor = FakeCandidateExtractor(
        by_source={
            # caption yields nothing confident
            SourceTag.CAPTION: [],
        },
        by_text={
            "Parasite (2019)": [comment_candidate],
        },
    )
    poster_detector = FakePosterDetector()
    tmdb_client = FakeTMDBClient(
        default_results=[_exact_match_result("Parasite (2019)")]
    )
    deps = _make_deps(
        ingestor=ingestor,
        text_extractor=extractor,
        poster_detector=poster_detector,
        tmdb_client=tmdb_client,
    )

    result = run_pipeline(URL, deps)

    # Caption job ran (recorded, found nothing confident), only the
    # creator's own top-level comment's text was ever extracted -- the
    # other author's comment and the creator's reply never reached the
    # extractor.
    extracted_texts = [text for text, _source in extractor.calls]
    assert "not a confident caption" in extracted_texts
    assert "Parasite (2019)" in extracted_texts
    assert "Avatar (2009)" not in extracted_texts
    assert "Interstellar (2014)" not in extracted_texts

    assert len(ingestor.ensure_video_calls) == 1
    assert poster_detector.calls == []

    assert len(result.recommendations) == 1
    assert result.recommendations[0].source == SourceTag.CREATOR_COMMENT


def test_no_confident_text_or_audio_candidates_pools_visual_candidate(monkeypatch):
    """When no job clears the confidence bar, every job is pooled -- here
    only the visual job produces anything (frame_candidate's confidence,
    0.8, does NOT itself clear `CONFIDENCE_THRESHOLD`/`HIGH_CONFIDENCE`
    (0.9), so there is genuinely no winner, and this exercises the
    no-winner pooling path, not a win)."""
    frame_candidate = Candidate(
        raw_text="Oldboy (2003)", source=SourceTag.FRAME_VISUAL, confidence=0.8
    )
    ingestor = FakeIngestor(metadata=_ingest_result(caption=""))
    extractor = FakeCandidateExtractor()  # no confident candidates anywhere
    frame = FrameSample(path=Path("/fake/frame_000.jpg"), timestamp_seconds=5.0)
    poster_detector = FakePosterDetector(responses={frame.path: [frame_candidate]})
    tmdb_client = FakeTMDBClient(default_results=[_exact_match_result("Oldboy (2003)")])
    deps = _make_deps(
        ingestor=ingestor,
        text_extractor=extractor,
        poster_detector=poster_detector,
        tmdb_client=tmdb_client,
    )

    import reel2movie.pipeline.waterfall as waterfall_module

    sample_calls = []

    def fake_sample_frames_at_interval(video_path, interval_seconds, duration_seconds, **kwargs):
        sample_calls.append((video_path, interval_seconds, duration_seconds))
        return [frame]

    monkeypatch.setattr(
        waterfall_module, "sample_frames_at_interval", fake_sample_frames_at_interval
    )
    monkeypatch.setattr(waterfall_module, "dedupe_similar_frames", _identity_dedupe)

    result = run_pipeline(URL, deps)

    assert len(ingestor.ensure_video_calls) == 1
    assert len(sample_calls) == 1
    assert poster_detector.calls == [frame]
    assert len(result.recommendations) == 1
    assert result.recommendations[0].source == SourceTag.FRAME_VISUAL


def test_frame_interval_seconds_passed_through_to_sample_frames_at_interval(monkeypatch):
    ingestor = FakeIngestor(metadata=_ingest_result(caption=""))
    extractor = FakeCandidateExtractor()
    deps = _make_deps(
        ingestor=ingestor,
        text_extractor=extractor,
        frame_interval_seconds=0.5,
    )

    import reel2movie.pipeline.waterfall as waterfall_module

    captured = {}

    def fake_sample_frames_at_interval(video_path, interval_seconds, duration_seconds, **kwargs):
        captured["interval_seconds"] = interval_seconds
        return []

    monkeypatch.setattr(
        waterfall_module, "sample_frames_at_interval", fake_sample_frames_at_interval
    )
    monkeypatch.setattr(waterfall_module, "dedupe_similar_frames", _identity_dedupe)

    run_pipeline(URL, deps)

    assert captured["interval_seconds"] == 0.5


def test_nothing_resolves_anywhere_returns_result_without_raising():
    ingestor = FakeIngestor(metadata=_ingest_result(caption=""))
    extractor = FakeCandidateExtractor()  # nothing from caption or comments
    poster_detector = FakePosterDetector()  # nothing from visual either

    deps = _make_deps(
        ingestor=ingestor, text_extractor=extractor, poster_detector=poster_detector
    )

    result = run_pipeline(URL, deps)

    assert result.reel_url == URL
    assert result.recommendations == []


def test_unresolved_candidate_is_kept_with_tmdb_none():
    candidate = Candidate(
        raw_text="Some Obscure Title (2010)",
        source=SourceTag.CAPTION,
        confidence=0.9,
    )
    ingestor = FakeIngestor(metadata=_ingest_result(caption="Some Obscure Title (2010)"))
    extractor = FakeCandidateExtractor(by_source={SourceTag.CAPTION: [candidate]})
    # No TMDB results at all for this query -> resolve_candidate returns None.
    tmdb_client = FakeTMDBClient(default_results=[])
    deps = _make_deps(
        ingestor=ingestor, text_extractor=extractor, tmdb_client=tmdb_client
    )

    result = run_pipeline(URL, deps)

    assert len(result.recommendations) == 1
    rec = result.recommendations[0]
    assert rec.query == "Some Obscure Title (2010)"
    assert rec.tmdb is None


def test_two_candidates_resolving_to_same_tmdb_id_are_deduped():
    lower_confidence_candidate = Candidate(
        raw_text="The Thing (1982)", source=SourceTag.CAPTION, confidence=0.9
    )
    higher_confidence_candidate = Candidate(
        raw_text="The Thing (1982) remastered", source=SourceTag.CAPTION, confidence=1.0
    )
    ingestor = FakeIngestor(metadata=_ingest_result(caption="two titles here"))
    extractor = FakeCandidateExtractor(
        by_source={
            SourceTag.CAPTION: [lower_confidence_candidate, higher_confidence_candidate]
        }
    )
    # Both queries resolve to the SAME tmdb id (id=42), via per-query exact
    # matches. `resolver.py` strips the candidate's trailing "(YYYY)" before
    # querying TMDB, so "The Thing (1982)" is searched as "The Thing" (the
    # year is still passed separately via `year=`); "The Thing (1982)
    # remastered" has no TRAILING year (year is mid-string, followed by
    # "remastered"), so it's searched unstripped.
    tmdb_client = FakeTMDBClient(
        results_by_query={
            "The Thing": [_exact_match_result("The Thing", tmdb_id=42)],
            "The Thing (1982) remastered": [
                _exact_match_result("The Thing (1982) remastered", tmdb_id=42)
            ],
        }
    )
    deps = _make_deps(
        ingestor=ingestor, text_extractor=extractor, tmdb_client=tmdb_client
    )

    result = run_pipeline(URL, deps)

    assert len(result.recommendations) == 1
    rec = result.recommendations[0]
    assert rec.tmdb is not None
    assert rec.tmdb.id == 42
    # The higher-confidence of the two merged recommendations survives.
    assert rec.confidence == 1.0
    assert rec.query == "The Thing (1982) remastered"


def test_unresolved_duplicate_dropped_when_same_query_candidate_already_resolved():
    """Real-world bug repro: visual fallback detects the same poster in two
    sampled frames, producing two `Recommendation`s with identical `query`.
    One's TMDB resolution succeeds; the other hits a transient error and
    comes back `tmdb=None`. The unresolved copy is a redundant duplicate of
    an already-answered question, so `dedupe_recommendations` must drop
    it, leaving only the resolved one.
    """
    resolved_movie = ResolvedMovie(
        id=7,
        title="Om Dar-B-Dar",
        year=1988,
        poster_path=None,
        overview="",
        match_score=1.0,
        media_type="movie",
    )
    resolved_rec = Recommendation(
        query="Om Dar-B-Dar (1988)",
        source=SourceTag.FRAME_VISUAL,
        confidence=0.8,
        tmdb=resolved_movie,
    )
    unresolved_duplicate_rec = Recommendation(
        query="Om Dar-B-Dar (1988)",
        source=SourceTag.FRAME_VISUAL,
        confidence=0.8,
        tmdb=None,
    )

    deduped = dedupe_recommendations([resolved_rec, unresolved_duplicate_rec])

    assert len(deduped) == 1
    assert deduped[0].tmdb is resolved_movie


def test_unresolved_candidate_with_no_resolved_sibling_is_still_kept():
    """Existing behavior must be unchanged: a genuinely-unresolved
    recommendation with no same-query resolved sibling is kept, not
    accidentally dropped by the new duplicate-dropping logic.
    """
    lone_unresolved_rec = Recommendation(
        query="Some Obscure Title (2010)",
        source=SourceTag.CAPTION,
        confidence=0.9,
        tmdb=None,
    )

    deduped = dedupe_recommendations([lone_unresolved_rec])

    assert deduped == [lone_unresolved_rec]


def test_captions_context_is_threaded_into_disambiguation_chat_client():
    """`result.caption` -- the original IngestResult's caption text -- must
    reach `resolve_candidate()`'s `context` param, which in turn hands it
    to the disambiguation chat client as part of its prompt. Set up two
    TIED exact-title TMDB results so `resolve_candidate` actually
    attempts disambiguation (and therefore actually calls the chat
    client) during a real `run_pipeline()` run.
    """
    caption_text = "THE_UNIQUE_CAPTION_CONTEXT_MARKER, a rom-com on Prime."
    candidate = Candidate(
        raw_text="Don't Be Shy", source=SourceTag.CAPTION, confidence=0.9
    )
    ingestor = FakeIngestor(metadata=_ingest_result(caption=caption_text))
    extractor = FakeCandidateExtractor(by_source={SourceTag.CAPTION: [candidate]})
    tied_results = [
        TMDBSearchResult(
            id=111,
            title="Don't Be Shy",
            year=2025,
            poster_path=None,
            overview="A college rom-com.",
            popularity=10.0,
            original_rank=0,
            media_type="movie",
        ),
        TMDBSearchResult(
            id=222,
            title="Don't Be Shy",
            year=2025,
            poster_path=None,
            overview="An unrelated adult-themed film.",
            popularity=5.0,
            original_rank=1,
            media_type="movie",
        ),
    ]
    tmdb_client = FakeTMDBClient(default_results=tied_results)
    chat_client = FakeChatClient(reply="111")
    deps = PipelineDeps(
        ingestor=ingestor,
        text_extractor=extractor,
        poster_detector=FakePosterDetector(),
        tmdb_client=tmdb_client,
        disambiguation_chat_client=chat_client,
    )

    result = run_pipeline(URL, deps)

    # `disambiguate_with_context`'s majority-vote reliability improvement
    # (resolver.py's `_DISAMBIGUATION_SAMPLE_COUNT`) samples the identical
    # prompt 3 times for this one tie-break, not once; there's only 1
    # candidate here, so `select_primary_candidates` never adds any
    # further prompts (it skips the LLM entirely for <=1 candidate).
    assert len(chat_client.prompts) == 3
    assert caption_text in chat_client.prompts[0]
    assert len(result.recommendations) == 1
    assert result.recommendations[0].tmdb is not None
    assert result.recommendations[0].tmdb.id == 111


def test_no_disambiguation_chat_client_falls_back_to_pick_best_in_real_pipeline():
    """A `PipelineDeps` with no `disambiguation_chat_client` (the default,
    matching every pre-existing test in this file) must behave exactly as
    before: disambiguation never runs, and `pick_best()`'s rank tiebreak
    picks the winner among tied exact matches."""
    candidate = Candidate(
        raw_text="Don't Be Shy", source=SourceTag.CAPTION, confidence=0.9
    )
    ingestor = FakeIngestor(metadata=_ingest_result(caption="some caption"))
    extractor = FakeCandidateExtractor(by_source={SourceTag.CAPTION: [candidate]})
    tied_results = [
        TMDBSearchResult(
            id=111,
            title="Don't Be Shy",
            year=2025,
            poster_path=None,
            overview="A college rom-com.",
            popularity=10.0,
            original_rank=0,
            media_type="movie",
        ),
        TMDBSearchResult(
            id=222,
            title="Don't Be Shy",
            year=2025,
            poster_path=None,
            overview="An unrelated adult-themed film.",
            popularity=5.0,
            original_rank=1,
            media_type="movie",
        ),
    ]
    tmdb_client = FakeTMDBClient(default_results=tied_results)
    deps = _make_deps(
        ingestor=ingestor, text_extractor=extractor, tmdb_client=tmdb_client
    )

    assert deps.disambiguation_chat_client is None

    result = run_pipeline(URL, deps)

    assert len(result.recommendations) == 1
    assert result.recommendations[0].tmdb is not None
    assert result.recommendations[0].tmdb.id == 111  # rank-0 wins the tiebreak


def test_two_different_unresolved_candidates_with_different_queries_both_kept():
    """The new logic must not merge unrelated unresolved candidates with
    each other -- only an unresolved rec whose query matches a *resolved*
    sibling's query is dropped.
    """
    first_unresolved_rec = Recommendation(
        query="First Obscure Title (2001)",
        source=SourceTag.CAPTION,
        confidence=0.9,
        tmdb=None,
    )
    second_unresolved_rec = Recommendation(
        query="Second Obscure Title (2002)",
        source=SourceTag.CAPTION,
        confidence=0.85,
        tmdb=None,
    )

    deduped = dedupe_recommendations([first_unresolved_rec, second_unresolved_rec])

    assert len(deduped) == 2
    assert first_unresolved_rec in deduped
    assert second_unresolved_rec in deduped


def test_recommendations_sorted_by_confidence_descending():
    weak = Candidate(raw_text="Weak Match (2001)", source=SourceTag.CAPTION, confidence=0.9)
    strong = Candidate(
        raw_text="Strong Match (2002)", source=SourceTag.CAPTION, confidence=0.95
    )
    ingestor = FakeIngestor(metadata=_ingest_result(caption="two titles"))
    extractor = FakeCandidateExtractor(by_source={SourceTag.CAPTION: [weak, strong]})
    tmdb_client = FakeTMDBClient(
        results_by_query={
            "Weak Match (2001)": [_exact_match_result("Weak Match (2001)", tmdb_id=1)],
            "Strong Match (2002)": [
                _exact_match_result("Strong Match (2002)", tmdb_id=2)
            ],
        }
    )
    deps = _make_deps(
        ingestor=ingestor, text_extractor=extractor, tmdb_client=tmdb_client
    )

    result = run_pipeline(URL, deps)

    assert [rec.confidence for rec in result.recommendations] == [0.95, 0.9]


def test_step1_ingestor_failure_propagates():
    ingestor = FakeIngestor(metadata_error=RuntimeError("unreachable/unsupported link"))
    extractor = FakeCandidateExtractor()
    deps = _make_deps(ingestor=ingestor, text_extractor=extractor)

    with pytest.raises(RuntimeError, match="unreachable/unsupported link"):
        run_pipeline(URL, deps)


def test_caption_job_crash_is_isolated_and_comment_job_still_wins():
    """Rewritten from the old "...falls_through_to_comment_step" test: that
    test relied on sequential short-circuiting (the FIRST extractor call,
    assumed to be caption's, raising). Under the race, calls can arrive in
    any order, so the caption job is made to raise deterministically by
    `SourceTag` instead of call order -- proving this module's
    error-isolation policy (a crashed job is isolated, not propagated)
    rather than the old "falls through to the next step" framing.
    """
    comments = [
        Comment(id="c1", author_id="creator-1", text="Dune (2021)", is_reply=False)
    ]
    comment_candidate = Candidate(
        raw_text="Dune (2021)", source=SourceTag.CREATOR_COMMENT, confidence=0.9
    )
    ingestor = FakeIngestor(
        metadata=_ingest_result(caption="caption text", comments=comments)
    )
    extractor = FakeCandidateExtractor(
        by_text={"Dune (2021)": [comment_candidate]},
        error_by_source={SourceTag.CAPTION: RuntimeError("boom")},
    )

    tmdb_client = FakeTMDBClient(default_results=[_exact_match_result("Dune (2021)")])
    deps = _make_deps(
        ingestor=ingestor, text_extractor=extractor, tmdb_client=tmdb_client
    )

    result = run_pipeline(URL, deps)

    assert len(result.recommendations) == 1
    assert result.recommendations[0].source == SourceTag.CREATOR_COMMENT


def test_unexpected_exception_from_a_job_is_isolated_and_logged(caplog):
    """The error-isolation policy's "crashed" branch: a genuine internal
    bug in one job (here, the creator-comment job) must not propagate out
    of `run_pipeline` or prevent another job's candidates from winning --
    but, unlike a cancellation, it IS logged as an error (via
    `logger.exception`), so a real bug stays discoverable.
    """
    caption_candidate = Candidate(
        raw_text="Inception (2010)", source=SourceTag.CAPTION, confidence=0.95
    )
    comments = [
        Comment(id="c1", author_id="creator-1", text="some comment", is_reply=False)
    ]
    ingestor = FakeIngestor(
        metadata=_ingest_result(caption="Inception (2010)", comments=comments)
    )
    extractor = FakeCandidateExtractor(
        by_source={SourceTag.CAPTION: [caption_candidate]},
        error_by_source={SourceTag.CREATOR_COMMENT: RuntimeError("a genuine bug")},
    )
    tmdb_client = FakeTMDBClient(
        default_results=[_exact_match_result("Inception (2010)")]
    )
    deps = _make_deps(
        ingestor=ingestor, text_extractor=extractor, tmdb_client=tmdb_client
    )

    with caplog.at_level("INFO"):
        result = run_pipeline(URL, deps)

    assert len(result.recommendations) == 1
    assert result.recommendations[0].source == SourceTag.CAPTION
    assert any(
        record.levelname == "ERROR"
        and "creator-comment candidate extraction failed" in record.message
        for record in caplog.records
    )


def test_cancelled_exception_from_a_job_is_treated_as_lost_not_crashed(caplog):
    """The error-isolation policy's "cancelled" branch: a `*Cancelled`
    exception from one job (here, the creator-comment job raising
    `SubprocessCancelled` directly, as `WhisperCppTranscriber`/
    `run_cancelable` genuinely do on cancellation) must be treated as
    "this job lost the race", not a crash -- no ERROR-level log, and the
    pipeline's result is unaffected.
    """
    caption_candidate = Candidate(
        raw_text="Inception (2010)", source=SourceTag.CAPTION, confidence=0.95
    )
    comments = [
        Comment(id="c1", author_id="creator-1", text="some comment", is_reply=False)
    ]
    ingestor = FakeIngestor(
        metadata=_ingest_result(caption="Inception (2010)", comments=comments)
    )
    extractor = FakeCandidateExtractor(
        by_source={SourceTag.CAPTION: [caption_candidate]},
        error_by_source={
            SourceTag.CREATOR_COMMENT: SubprocessCancelled("lost the race")
        },
    )
    tmdb_client = FakeTMDBClient(
        default_results=[_exact_match_result("Inception (2010)")]
    )
    deps = _make_deps(
        ingestor=ingestor, text_extractor=extractor, tmdb_client=tmdb_client
    )

    with caplog.at_level("INFO"):
        result = run_pipeline(URL, deps)

    assert len(result.recommendations) == 1
    assert result.recommendations[0].source == SourceTag.CAPTION
    assert not any(record.levelname == "ERROR" for record in caplog.records)
    assert any(
        "lost the race" in record.message or "cancelled" in record.message
        for record in caplog.records
    )


def test_claude_cli_cancelled_from_a_job_is_also_treated_as_lost_not_crashed():
    """Same as the `SubprocessCancelled` case above, but for
    `ClaudeCliCancelled` (e.g. from the claude-CLI-backed text extractor)
    -- `_run_job_safely`'s `except SubprocessCancelled:` clause must catch
    this too, since `ClaudeCliCancelled` is itself a `SubprocessCancelled`
    subclass (multiple inheritance -- see its own docstring), not a
    second, separately-handled exception type.
    """
    caption_candidate = Candidate(
        raw_text="Inception (2010)", source=SourceTag.CAPTION, confidence=0.95
    )
    comments = [
        Comment(id="c1", author_id="creator-1", text="some comment", is_reply=False)
    ]
    ingestor = FakeIngestor(
        metadata=_ingest_result(caption="Inception (2010)", comments=comments)
    )
    extractor = FakeCandidateExtractor(
        by_source={SourceTag.CAPTION: [caption_candidate]},
        error_by_source={
            SourceTag.CREATOR_COMMENT: ClaudeCliCancelled("lost the race")
        },
    )
    tmdb_client = FakeTMDBClient(
        default_results=[_exact_match_result("Inception (2010)")]
    )
    deps = _make_deps(
        ingestor=ingestor, text_extractor=extractor, tmdb_client=tmdb_client
    )

    result = run_pipeline(URL, deps)

    assert len(result.recommendations) == 1
    assert result.recommendations[0].source == SourceTag.CAPTION


def test_prepare_audio_cancellation_is_logged_at_info_not_error(monkeypatch, caplog):
    """`_prepare_audio` must follow this module's own error-isolation
    policy: `extract_audio` raising `SubprocessCancelled` is the NORMAL,
    expected outcome whenever a fast text job wins the race while audio
    extraction is still in flight (the common case for most successful
    runs once an `AudioTranscriber` is configured) -- it must be logged at
    INFO ("lost the race"), never as an ERROR via `logger.exception`. A
    confident caption candidate wins instantly here; `extract_audio` is
    monkeypatched to always raise `SubprocessCancelled` (simulating it
    having been cancelled once the race is decided), and an
    `AudioTranscriber` IS configured so `_prepare_audio` actually attempts
    extraction instead of bailing out early.
    """
    import reel2movie.pipeline.waterfall as waterfall_module

    def always_cancelled_extract_audio(video_path, output_dir, *, cancel_event=None):
        raise SubprocessCancelled("lost the race")

    monkeypatch.setattr(
        waterfall_module, "extract_audio", always_cancelled_extract_audio
    )

    caption_candidate = Candidate(
        raw_text="Inception (2010)", source=SourceTag.CAPTION, confidence=0.95
    )
    ingestor = FakeIngestor(metadata=_ingest_result(caption="Inception (2010)"))
    extractor = FakeCandidateExtractor(
        by_source={SourceTag.CAPTION: [caption_candidate]}
    )
    tmdb_client = FakeTMDBClient(
        default_results=[_exact_match_result("Inception (2010)")]
    )
    deps = _make_deps(
        ingestor=ingestor,
        text_extractor=extractor,
        tmdb_client=tmdb_client,
        audio_transcriber=FakeAudioTranscriber(transcript="irrelevant"),
    )

    with caplog.at_level("INFO"):
        result = run_pipeline(URL, deps)
        # `_prepare_audio` runs on a background daemon thread, not waited
        # on by the orchestrator -- give it a brief moment to actually
        # reach (and log) the cancellation before asserting on caplog.
        time.sleep(0.3)

    assert len(result.recommendations) == 1
    assert not any(record.levelname == "ERROR" for record in caplog.records)
    assert any(
        "lost the race" in record.message or "cancelled" in record.message
        for record in caplog.records
    )


def test_prepare_audio_returns_within_bounded_timeout_when_video_future_never_resolves(
    monkeypatch, caplog
):
    """Regression test: `_prepare_video`'s `ensure_video()` (yt-dlp) has no
    cancellation/timeout support of its own, so if its network call
    genuinely hung forever, `_prepare_audio` blocking UNBOUNDEDLY on
    `video_future.result()` would leak its own daemon thread on top of
    that (and `_cleanup_audio_temp_dir` a third, waiting on this
    function's future in turn). `_prepare_audio` now bounds that wait via
    `_VIDEO_DOWNLOAD_WAIT_TIMEOUT_SECONDS` -- this test monkeypatches that
    constant down to a tiny value (so the test itself stays fast) and
    hands `_prepare_audio` a `Future` that is never resolved, confirming
    it returns `None` promptly instead of hanging, with a WARNING (not
    ERROR) log, never raising.
    """
    import reel2movie.pipeline.waterfall as waterfall_module

    monkeypatch.setattr(
        waterfall_module, "_VIDEO_DOWNLOAD_WAIT_TIMEOUT_SECONDS", 0.2
    )

    never_resolves: "Future[Path | None]" = Future()
    deps = PipelineDeps(
        ingestor=None,
        text_extractor=None,
        poster_detector=None,
        tmdb_client=None,
        audio_transcriber=FakeAudioTranscriber(transcript="irrelevant"),
    )

    with caplog.at_level("WARNING"):
        result = _prepare_audio(never_resolves, deps, threading.Event())

    assert result is None
    assert not any(record.levelname == "ERROR" for record in caplog.records)
    assert any(
        "timed out" in record.message and "video download" in record.message
        for record in caplog.records
    )


def test_genuinely_concurrent_fast_job_wins_and_slow_job_observes_cancellation():
    """A real concurrency test (no monkeypatching away the thread pool):
    the caption job is instant and confident; the creator-comment job is
    configured to busy-wait for up to several seconds, checking the
    shared `cancel_event` every 10ms. Confirms (a) the fast job's result
    wins (b) the whole `run_pipeline()` call returns quickly -- nowhere
    near the comment job's full configured wait -- and (c) the comment
    job's fake actually observed `cancel_event` firing and broke out
    early, proving real cancellation propagated across threads, not just
    that the race "happened to" pick the fast winner.
    """
    caption_candidate = Candidate(
        raw_text="Inception (2010)", source=SourceTag.CAPTION, confidence=0.95
    )
    comments = [
        Comment(id="c1", author_id="creator-1", text="some comment", is_reply=False)
    ]
    ingestor = FakeIngestor(
        metadata=_ingest_result(caption="Inception (2010)", comments=comments)
    )
    extractor = FakeCandidateExtractor(
        by_source={SourceTag.CAPTION: [caption_candidate]},
        block_seconds_by_source={SourceTag.CREATOR_COMMENT: 3.0},
    )
    tmdb_client = FakeTMDBClient(
        default_results=[_exact_match_result("Inception (2010)")]
    )
    deps = _make_deps(
        ingestor=ingestor, text_extractor=extractor, tmdb_client=tmdb_client
    )

    start = time.monotonic()
    result = run_pipeline(URL, deps)
    elapsed = time.monotonic() - start

    assert len(result.recommendations) == 1
    assert result.recommendations[0].source == SourceTag.CAPTION
    # Well under the comment job's full 3s configured wait -- it must
    # have been cancelled early, not run to completion.
    assert elapsed < 1.5
    assert SourceTag.CREATOR_COMMENT in extractor.observed_cancelled_sources


def test_no_winner_pools_candidates_from_all_four_jobs(monkeypatch):
    """None of the four jobs' candidates clear `CONFIDENCE_THRESHOLD` --
    per `_race_candidate_jobs`'s contract, every job's candidates must
    then be pooled together (union), not just one.
    """
    caption_candidate = Candidate(
        raw_text="Capt Movie", source=SourceTag.CAPTION, confidence=0.6
    )
    comment_candidate = Candidate(
        raw_text="Comment Movie", source=SourceTag.CREATOR_COMMENT, confidence=0.6
    )
    audio_candidate = Candidate(
        raw_text="Audio Movie", source=SourceTag.AUDIO_TRANSCRIPT, confidence=0.6
    )
    visual_candidate = Candidate(
        raw_text="Visual Movie", source=SourceTag.FRAME_VISUAL, confidence=0.6
    )

    comments = [
        Comment(id="c1", author_id="creator-1", text="some comment text", is_reply=False)
    ]
    ingestor = FakeIngestor(metadata=_ingest_result(caption="some caption", comments=comments))
    extractor = FakeCandidateExtractor(
        by_source={
            SourceTag.CAPTION: [caption_candidate],
            SourceTag.CREATOR_COMMENT: [comment_candidate],
            SourceTag.AUDIO_TRANSCRIPT: [audio_candidate],
        }
    )
    audio_transcriber = FakeAudioTranscriber(transcript="a spoken transcript")
    frame = FrameSample(path=Path("/fake/frame_000.jpg"), timestamp_seconds=1.0)
    poster_detector = FakePosterDetector(responses={frame.path: [visual_candidate]})

    import reel2movie.pipeline.waterfall as waterfall_module

    def fake_sample_frames_at_interval(video_path, interval_seconds, duration_seconds, **kwargs):
        return [frame]

    monkeypatch.setattr(
        waterfall_module, "sample_frames_at_interval", fake_sample_frames_at_interval
    )
    monkeypatch.setattr(waterfall_module, "dedupe_similar_frames", _identity_dedupe)

    tmdb_client = FakeTMDBClient(
        results_by_query={
            "Capt Movie": [_exact_match_result("Capt Movie", tmdb_id=1)],
            "Comment Movie": [_exact_match_result("Comment Movie", tmdb_id=2)],
            "Audio Movie": [_exact_match_result("Audio Movie", tmdb_id=3)],
            "Visual Movie": [_exact_match_result("Visual Movie", tmdb_id=4)],
        }
    )
    deps = _make_deps(
        ingestor=ingestor,
        text_extractor=extractor,
        poster_detector=poster_detector,
        tmdb_client=tmdb_client,
        audio_transcriber=audio_transcriber,
    )

    result = run_pipeline(URL, deps)

    sources = {rec.source for rec in result.recommendations}
    assert sources == {
        SourceTag.CAPTION,
        SourceTag.CREATOR_COMMENT,
        SourceTag.AUDIO_TRANSCRIPT,
        SourceTag.FRAME_VISUAL,
    }
    assert len(result.recommendations) == 4
    assert all(rec.tmdb is not None for rec in result.recommendations)


def test_audio_transcript_context_used_for_disambiguation_when_audio_job_wins():
    """`_resolve_all`'s `transcript` param: when the audio-transcript job
    is the one that WINS the race outright, its transcript text must be
    concatenated onto the caption as disambiguation context.
    """
    audio_candidate = Candidate(
        raw_text="Don't Be Shy", source=SourceTag.AUDIO_TRANSCRIPT, confidence=0.95
    )
    ingestor = FakeIngestor(metadata=_ingest_result(caption="some caption"))
    extractor = FakeCandidateExtractor(
        by_source={SourceTag.AUDIO_TRANSCRIPT: [audio_candidate]}
    )
    audio_transcriber = FakeAudioTranscriber(
        transcript="THE_UNIQUE_TRANSCRIPT_MARKER mentions a rom-com"
    )
    tied_results = [
        TMDBSearchResult(
            id=111,
            title="Don't Be Shy",
            year=2025,
            poster_path=None,
            overview="A college rom-com.",
            popularity=10.0,
            original_rank=0,
            media_type="movie",
        ),
        TMDBSearchResult(
            id=222,
            title="Don't Be Shy",
            year=2025,
            poster_path=None,
            overview="An unrelated adult-themed film.",
            popularity=5.0,
            original_rank=1,
            media_type="movie",
        ),
    ]
    tmdb_client = FakeTMDBClient(default_results=tied_results)
    chat_client = FakeChatClient(reply="111")
    deps = PipelineDeps(
        ingestor=ingestor,
        text_extractor=extractor,
        poster_detector=FakePosterDetector(),
        tmdb_client=tmdb_client,
        disambiguation_chat_client=chat_client,
        audio_transcriber=audio_transcriber,
    )

    result = run_pipeline(URL, deps)

    # 3x for the same reason as `test_captions_context_is_threaded_into_
    # disambiguation_chat_client` above: the majority-vote sample count,
    # not `select_primary_candidates` (only 1 candidate here, so it never
    # calls the chat client at all).
    assert len(chat_client.prompts) == 3
    assert "THE_UNIQUE_TRANSCRIPT_MARKER" in chat_client.prompts[0]
    assert "some caption" in chat_client.prompts[0]
    assert result.recommendations[0].tmdb is not None
    assert result.recommendations[0].tmdb.id == 111


def test_transcript_not_used_for_disambiguation_when_no_job_wins_the_race():
    """Contrast with the test above: when the audio job's candidate does
    NOT win outright (no job does -- pooled/no-winner case), its
    transcript must NOT be used as disambiguation context, even though a
    transcript was produced -- only a genuine winner's `raw_text` ever
    populates it (see `_race_candidate_jobs`/`_resolve_all` docstrings).
    """
    audio_candidate = Candidate(
        raw_text="Don't Be Shy", source=SourceTag.AUDIO_TRANSCRIPT, confidence=0.5
    )
    ingestor = FakeIngestor(metadata=_ingest_result(caption="some caption"))
    extractor = FakeCandidateExtractor(
        by_source={SourceTag.AUDIO_TRANSCRIPT: [audio_candidate]}
    )
    audio_transcriber = FakeAudioTranscriber(transcript="THE_UNIQUE_TRANSCRIPT_MARKER")
    tied_results = [
        TMDBSearchResult(
            id=111,
            title="Don't Be Shy",
            year=2025,
            poster_path=None,
            overview="A college rom-com.",
            popularity=10.0,
            original_rank=0,
            media_type="movie",
        ),
        TMDBSearchResult(
            id=222,
            title="Don't Be Shy",
            year=2025,
            poster_path=None,
            overview="An unrelated adult-themed film.",
            popularity=5.0,
            original_rank=1,
            media_type="movie",
        ),
    ]
    tmdb_client = FakeTMDBClient(default_results=tied_results)
    chat_client = FakeChatClient(reply="111")
    deps = PipelineDeps(
        ingestor=ingestor,
        text_extractor=extractor,
        poster_detector=FakePosterDetector(),
        tmdb_client=tmdb_client,
        disambiguation_chat_client=chat_client,
        audio_transcriber=audio_transcriber,
    )

    result = run_pipeline(URL, deps)

    # 3x for the majority-vote sample count, same reasoning as the test
    # above.
    assert len(chat_client.prompts) == 3
    assert "THE_UNIQUE_TRANSCRIPT_MARKER" not in chat_client.prompts[0]
    assert "some caption" in chat_client.prompts[0]


# ---------------------------------------------------------------------------
# select_primary_candidates() source_text threading (Problem A wiring)
# ---------------------------------------------------------------------------


@dataclass
class _RecordingKeepAllChatClient:
    """Fake `TextChatClient` for `select_primary_candidates`'s noise-filter
    prompt: records every prompt it's asked, and always keeps both
    candidates with no media-type hint -- both end-to-end `source_text`
    tests below use exactly 2 candidates, so this fixed-shape reply
    suffices for either.
    """

    prompts: list[str] = field(default_factory=list)

    def chat(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return (
            '{"media_type_hint": null, "decisions": '
            '[{"index": 0, "keep": true}, {"index": 1, "keep": true}]}'
        )


def test_primary_candidate_filter_uses_caption_text_for_caption_win():
    """`_apply_primary_candidate_filter` must hand `select_primary_candidates`
    `result.caption` as `source_text` when the CAPTION job is the race
    winner -- proved by asserting the caption's own unique marker text
    reaches the noise-filter prompt.
    """
    caption_text = "THE_UNIQUE_CAPTION_MARKER recommends two movies: A and B."
    caption_candidates = [
        Candidate(raw_text="Movie A", source=SourceTag.CAPTION, confidence=0.95),
        Candidate(raw_text="Movie B", source=SourceTag.CAPTION, confidence=0.95),
    ]
    ingestor = FakeIngestor(metadata=_ingest_result(caption=caption_text))
    extractor = FakeCandidateExtractor(
        by_source={SourceTag.CAPTION: caption_candidates}
    )
    tmdb_client = FakeTMDBClient(
        results_by_query={
            "Movie A": [_exact_match_result("Movie A", tmdb_id=1)],
            "Movie B": [_exact_match_result("Movie B", tmdb_id=2)],
        }
    )
    chat_client = _RecordingKeepAllChatClient()
    deps = PipelineDeps(
        ingestor=ingestor,
        text_extractor=extractor,
        poster_detector=FakePosterDetector(),
        tmdb_client=tmdb_client,
        disambiguation_chat_client=chat_client,
    )

    result = run_pipeline(URL, deps)

    assert len(chat_client.prompts) == 1
    assert caption_text in chat_client.prompts[0]
    assert len(result.recommendations) == 2


def test_primary_candidate_filter_uses_transcript_text_for_audio_win():
    """Contrast with the test above: when the AUDIO_TRANSCRIPT job is the
    race winner instead, `select_primary_candidates` must be handed the
    TRANSCRIPT text as `source_text`, not `result.caption` -- proving this
    isn't hardcoded to always use the caption (which would defeat the
    point of this fix for a non-caption winner).
    """
    transcript_text = "THE_UNIQUE_TRANSCRIPT_MARKER recommends two shows: A and B."
    audio_candidates = [
        Candidate(raw_text="Show A", source=SourceTag.AUDIO_TRANSCRIPT, confidence=0.95),
        Candidate(raw_text="Show B", source=SourceTag.AUDIO_TRANSCRIPT, confidence=0.95),
    ]
    ingestor = FakeIngestor(metadata=_ingest_result(caption="an unrelated caption"))
    extractor = FakeCandidateExtractor(
        by_source={SourceTag.AUDIO_TRANSCRIPT: audio_candidates}
    )
    audio_transcriber = FakeAudioTranscriber(transcript=transcript_text)
    tmdb_client = FakeTMDBClient(
        results_by_query={
            "Show A": [_exact_match_result("Show A", tmdb_id=1)],
            "Show B": [_exact_match_result("Show B", tmdb_id=2)],
        }
    )
    chat_client = _RecordingKeepAllChatClient()
    deps = PipelineDeps(
        ingestor=ingestor,
        text_extractor=extractor,
        poster_detector=FakePosterDetector(),
        tmdb_client=tmdb_client,
        disambiguation_chat_client=chat_client,
        audio_transcriber=audio_transcriber,
    )

    result = run_pipeline(URL, deps)

    assert len(chat_client.prompts) == 1
    assert transcript_text in chat_client.prompts[0]
    assert "an unrelated caption" not in chat_client.prompts[0]
    assert len(result.recommendations) == 2


def test_visual_fallback_internal_error_is_swallowed_not_raised():
    ingestor = FakeIngestor(
        metadata=_ingest_result(caption=""), ensure_video_error=RuntimeError("no video")
    )
    extractor = FakeCandidateExtractor()
    deps = _make_deps(ingestor=ingestor, text_extractor=extractor)

    result = run_pipeline(URL, deps)

    assert result.recommendations == []
    assert len(ingestor.ensure_video_calls) == 1


def test_visual_fallback_cleans_up_its_own_temp_frame_directory(monkeypatch):
    """Regression test for the temp-dir leak: `waterfall.py` must create its
    own `output_dir`, pass it to `sample_frames_at_interval`, and remove it
    (via `shutil.rmtree`) once poster detection is done with the frames --
    `frame_sampler.py` itself never cleans up what it creates.
    """
    frame_candidate = Candidate(
        raw_text="Oldboy (2003)", source=SourceTag.FRAME_VISUAL, confidence=0.8
    )
    ingestor = FakeIngestor(metadata=_ingest_result(caption=""))
    extractor = FakeCandidateExtractor()  # no confident candidates anywhere
    captured_dirs = []

    def fake_sample_frames_at_interval(video_path, interval_seconds, duration_seconds, *, output_dir=None, cancel_event=None):
        # The directory must already exist (created by waterfall.py) and
        # be passed through explicitly -- not left as None for
        # frame_sampler.py to invent its own untracked tempfile.mkdtemp().
        assert output_dir is not None
        assert output_dir.is_dir()
        captured_dirs.append(output_dir)
        frame_path = output_dir / "frame_000.jpg"
        frame_path.write_bytes(b"fake-jpeg-bytes")
        frame = FrameSample(path=frame_path, timestamp_seconds=5.0)
        return [frame]

    poster_detector = FakePosterDetector()
    # Make the poster detector return the candidate for whatever frame path
    # it's actually handed (captured_dirs isn't known until
    # sample_frames_at_interval runs), via a tiny closure instead of the
    # dict-keyed fake.
    def detect(frame, *, cancel_event=None):
        poster_detector.calls.append(frame)
        return [frame_candidate]

    poster_detector.detect = detect  # type: ignore[method-assign]

    tmdb_client = FakeTMDBClient(default_results=[_exact_match_result("Oldboy (2003)")])
    deps = _make_deps(
        ingestor=ingestor,
        text_extractor=extractor,
        poster_detector=poster_detector,
        tmdb_client=tmdb_client,
    )

    import reel2movie.pipeline.waterfall as waterfall_module

    monkeypatch.setattr(
        waterfall_module, "sample_frames_at_interval", fake_sample_frames_at_interval
    )
    monkeypatch.setattr(waterfall_module, "dedupe_similar_frames", _identity_dedupe)

    result = run_pipeline(URL, deps)

    assert len(captured_dirs) == 1
    frames_dir = captured_dirs[0]
    # The directory existed while frames were being read (asserted inside
    # fake_sample_frames_at_interval above) but is gone by the time
    # run_pipeline returns -- cleaned up after poster detection finished
    # using it.
    assert not frames_dir.exists()
    assert len(result.recommendations) == 1
    assert result.recommendations[0].source == SourceTag.FRAME_VISUAL


def test_visual_fallback_cleans_up_temp_dir_even_if_poster_detection_raises(
    monkeypatch,
):
    """The cleanup must happen via try/finally -- even when something in the
    visual step raises partway through (after the temp dir is created),
    the temp directory must still be removed, not leaked.
    """
    ingestor = FakeIngestor(metadata=_ingest_result(caption=""))
    extractor = FakeCandidateExtractor()
    captured_dirs = []

    def fake_sample_frames_at_interval(video_path, interval_seconds, duration_seconds, *, output_dir=None, cancel_event=None):
        captured_dirs.append(output_dir)
        return [FrameSample(path=output_dir / "frame_000.jpg", timestamp_seconds=1.0)]

    class ExplodingPosterDetector:
        def __init__(self):
            self.calls: list = []

        def detect(self, frame, *, cancel_event=None):
            self.calls.append(frame)
            raise RuntimeError("poster detector blew up")

    deps = _make_deps(
        ingestor=ingestor,
        text_extractor=extractor,
        poster_detector=ExplodingPosterDetector(),
    )

    import reel2movie.pipeline.waterfall as waterfall_module

    monkeypatch.setattr(
        waterfall_module, "sample_frames_at_interval", fake_sample_frames_at_interval
    )
    monkeypatch.setattr(waterfall_module, "dedupe_similar_frames", _identity_dedupe)

    result = run_pipeline(URL, deps)

    assert len(captured_dirs) == 1
    assert not captured_dirs[0].exists()
    # The whole visual job is swallowed as "found nothing", per this
    # module's error-isolation policy.
    assert result.recommendations == []


def test_frame_detection_pool_threads_are_real_threadpool_workers_known_limitation(
    monkeypatch,
):
    """Documents (does NOT silently pass over) Fix 2's known, accepted
    limitation -- see the module docstring's "Fix 2" note and
    `_extract_from_visual`'s own docstring: unlike every other job this
    module starts (all on `_run_in_daemon_thread`'s plain
    `threading.Thread`s), `_extract_from_visual`'s nested per-frame
    `frame_executor` is a real `ThreadPoolExecutor`. Its worker threads
    are tracked in `concurrent.futures.thread`'s module-global
    `_threads_queues` registry, which that module's `atexit` hook
    EXPLICITLY `.join()`s regardless of `shutdown(wait=False)` or the
    thread's own `.daemon` flag (note: that flag alone isn't a reliable
    signal here -- a `ThreadPoolExecutor` worker's `daemon` attribute is
    merely INHERITED from whatever thread created the pool, which is now
    itself one of this module's own daemon threads, so it can come back
    `True` too; being registered in `_threads_queues` -- identifiable via
    the default `"ThreadPoolExecutor-N_M"` worker thread name -- is what
    actually causes the explicit join). Under `VISION_BACKEND=anthropic_api`
    (non-default), a `detect()` call still in-flight when cancelled stays
    blocked on `AnthropicVisionChatClient.chat()`'s uncancellable HTTP
    request on one of these tracked threads, reintroducing the
    process-exit-hang bug for that one backend. This test asserts the
    CURRENT (accepted-limitation) state: if `frame_executor` is ever
    converted away from a real `ThreadPoolExecutor`, this test should
    start failing and needs to be updated/removed rather than silently
    continuing to pass.
    """
    observed_thread_names: list[str] = []

    def recording_sample_frames_at_interval(
        video_path, interval_seconds, duration_seconds, *, output_dir=None, cancel_event=None
    ):
        return [
            FrameSample(path=output_dir / "frame_000.jpg", timestamp_seconds=1.0)
        ]

    class RecordingPosterDetector:
        def detect(self, frame, *, cancel_event=None):
            observed_thread_names.append(threading.current_thread().name)
            return []

    ingestor = FakeIngestor(metadata=_ingest_result(caption=""))
    extractor = FakeCandidateExtractor()  # nothing confident from text sources
    deps = _make_deps(
        ingestor=ingestor,
        text_extractor=extractor,
        poster_detector=RecordingPosterDetector(),
    )

    import reel2movie.pipeline.waterfall as waterfall_module

    monkeypatch.setattr(
        waterfall_module,
        "sample_frames_at_interval",
        recording_sample_frames_at_interval,
    )
    monkeypatch.setattr(waterfall_module, "dedupe_similar_frames", _identity_dedupe)

    run_pipeline(URL, deps)

    assert len(observed_thread_names) == 1
    assert observed_thread_names[0].startswith("ThreadPoolExecutor")


def test_visual_fallback_with_none_duration_and_failed_probe_logs_warning_and_skips_sample_frames(
    monkeypatch, caplog
):
    """Regression test (updated for the duration-probing fallback):
    `result.duration_seconds=None` must be handled as its own distinct,
    clearly-logged case -- not passed into `sample_frames_at_interval`
    (which would raise `TypeError` on `None <= 0` and get silently
    swallowed, indistinguishable from a genuine "visual detector found
    nothing" outcome). `ensure_video` runs unconditionally for every reel
    regardless, but when probing ALSO fails, duration is still genuinely
    undeterminable and `sample_frames_at_interval` must never be called.
    """
    ingestor = FakeIngestor(metadata=_ingest_result(caption="", duration_seconds=None))
    extractor = FakeCandidateExtractor()  # nothing confident from text sources
    deps = _make_deps(ingestor=ingestor, text_extractor=extractor)

    import reel2movie.pipeline.waterfall as waterfall_module
    from reel2movie.visual.frame_sampler import FrameExtractionError

    def sample_frames_at_interval_must_not_be_called(*args, **kwargs):
        raise AssertionError(
            "sample_frames_at_interval must never be called when duration "
            "is undeterminable"
        )

    def probe_duration_seconds_fails(video_path, *, cancel_event=None):
        raise FrameExtractionError("could not find a Duration: line; corrupt file")

    monkeypatch.setattr(
        waterfall_module,
        "sample_frames_at_interval",
        sample_frames_at_interval_must_not_be_called,
    )
    monkeypatch.setattr(
        waterfall_module, "probe_duration_seconds", probe_duration_seconds_fails
    )

    with caplog.at_level("WARNING"):
        result = run_pipeline(URL, deps)

    assert result.recommendations == []
    assert len(ingestor.ensure_video_calls) == 1
    assert any(
        "unknown reel duration" in record.message for record in caplog.records
    )


def test_visual_fallback_none_duration_falls_back_to_probed_duration(monkeypatch):
    """`result.duration_seconds=None` must no longer short-circuit the
    visual fallback: `probe_duration_seconds` is tried, and on success
    `sample_frames_at_interval` is called with the PROBED duration, not a
    stale/wrong one.
    """
    frame_candidate = Candidate(
        raw_text="Oldboy (2003)", source=SourceTag.FRAME_VISUAL, confidence=0.8
    )
    ingestor = FakeIngestor(metadata=_ingest_result(caption="", duration_seconds=None))
    extractor = FakeCandidateExtractor()
    frame = FrameSample(path=Path("/fake/frame_000.jpg"), timestamp_seconds=5.0)
    poster_detector = FakePosterDetector(responses={frame.path: [frame_candidate]})
    tmdb_client = FakeTMDBClient(default_results=[_exact_match_result("Oldboy (2003)")])
    deps = _make_deps(
        ingestor=ingestor,
        text_extractor=extractor,
        poster_detector=poster_detector,
        tmdb_client=tmdb_client,
    )

    import reel2movie.pipeline.waterfall as waterfall_module

    probed_duration = 42.5
    probe_calls = []

    def fake_probe_duration_seconds(video_path, *, cancel_event=None):
        probe_calls.append(video_path)
        return probed_duration

    sample_calls = []

    def fake_sample_frames_at_interval(video_path, interval_seconds, duration_seconds, **kwargs):
        sample_calls.append((video_path, interval_seconds, duration_seconds))
        return [frame]

    monkeypatch.setattr(
        waterfall_module, "probe_duration_seconds", fake_probe_duration_seconds
    )
    monkeypatch.setattr(
        waterfall_module, "sample_frames_at_interval", fake_sample_frames_at_interval
    )
    monkeypatch.setattr(waterfall_module, "dedupe_similar_frames", _identity_dedupe)

    result = run_pipeline(URL, deps)

    assert len(ingestor.ensure_video_calls) == 1
    assert len(probe_calls) == 1
    assert len(sample_calls) == 1
    # sample_frames_at_interval must receive the PROBED duration, not
    # None/stale.
    assert sample_calls[0][2] == probed_duration
    assert len(result.recommendations) == 1
    assert result.recommendations[0].source == SourceTag.FRAME_VISUAL


def test_visual_fallback_with_valid_metadata_duration_never_probes(monkeypatch):
    """When `result.duration_seconds` is already valid, metadata takes
    precedence -- `probe_duration_seconds` must never be called (no
    wasted extra ffmpeg invocation).
    """
    ingestor = FakeIngestor(metadata=_ingest_result(caption="", duration_seconds=30.0))
    extractor = FakeCandidateExtractor()
    deps = _make_deps(ingestor=ingestor, text_extractor=extractor)

    import reel2movie.pipeline.waterfall as waterfall_module

    def probe_duration_seconds_must_not_be_called(video_path, *, cancel_event=None):
        raise AssertionError(
            "probe_duration_seconds must not be called when metadata "
            "duration is already valid"
        )

    sample_calls = []

    def fake_sample_frames_at_interval(video_path, interval_seconds, duration_seconds, **kwargs):
        sample_calls.append((video_path, interval_seconds, duration_seconds))
        return []

    monkeypatch.setattr(
        waterfall_module,
        "probe_duration_seconds",
        probe_duration_seconds_must_not_be_called,
    )
    monkeypatch.setattr(
        waterfall_module, "sample_frames_at_interval", fake_sample_frames_at_interval
    )
    monkeypatch.setattr(waterfall_module, "dedupe_similar_frames", _identity_dedupe)

    run_pipeline(URL, deps)

    assert len(ingestor.ensure_video_calls) == 1
    assert sample_calls == [
        (ingestor.video_path, deps.frame_interval_seconds, 30.0)
    ]


def test_dedup_step_is_wired_in_and_filters_frames_before_detection(
    monkeypatch, tmp_path
):
    """Proves the wiring (sample -> dedup -> detect), not the dedup
    algorithm's own correctness (that's `tests/unit/visual/test_frame_dedup.py`'s
    job). `sample_frames_at_interval` is patched to return several
    `FrameSample`s, several of which are pixel-identical copies of a single
    tiny fixture image on disk; the REAL `dedupe_similar_frames` runs
    (nothing fake/identity patched over it here), and the assertion is that
    `poster_detector.detect()` was only called for the deduped subset --
    i.e. strictly fewer times than the number of frames `sample_frames_at_interval`
    produced.
    """
    fixture_image_path = tmp_path / "fixture.jpg"
    Image.new("RGB", (64, 64), color=(10, 20, 30)).save(fixture_image_path, "JPEG")

    different_image_path = tmp_path / "different.jpg"
    Image.new("RGB", (64, 64), color=(250, 240, 230)).save(different_image_path, "JPEG")

    # Five frames: four pixel-identical copies of the same fixture image
    # (all pointing at the SAME file -- dedup only reads pixel content, not
    # path identity) and one genuinely different frame.
    frames = [
        FrameSample(path=fixture_image_path, timestamp_seconds=0.0),
        FrameSample(path=fixture_image_path, timestamp_seconds=1.0),
        FrameSample(path=fixture_image_path, timestamp_seconds=2.0),
        FrameSample(path=different_image_path, timestamp_seconds=3.0),
        FrameSample(path=fixture_image_path, timestamp_seconds=4.0),
    ]

    ingestor = FakeIngestor(metadata=_ingest_result(caption=""))
    extractor = FakeCandidateExtractor()  # nothing confident from text sources
    poster_detector = FakePosterDetector()
    deps = _make_deps(
        ingestor=ingestor,
        text_extractor=extractor,
        poster_detector=poster_detector,
    )

    import reel2movie.pipeline.waterfall as waterfall_module

    def fake_sample_frames_at_interval(video_path, interval_seconds, duration_seconds, **kwargs):
        return frames

    monkeypatch.setattr(
        waterfall_module, "sample_frames_at_interval", fake_sample_frames_at_interval
    )
    # Deliberately NOT patching dedupe_similar_frames -- the real
    # implementation must run here.

    run_pipeline(URL, deps)

    # The first fixture-image frame is kept unconditionally; the next two
    # identical copies are dropped as near-duplicates of it; the
    # genuinely-different frame is kept and becomes the new baseline; the
    # final fixture-image frame is then compared against THAT baseline
    # (the different image), so it's different enough to be kept too.
    # Either way, detect() must have been called strictly fewer times than
    # the 5 raw sampled frames -- proving the dedup step actually ran
    # between sampling and detection, not just that detection happened.
    assert len(poster_detector.calls) < len(frames)
    assert len(poster_detector.calls) >= 1


# ---------------------------------------------------------------------------
# run_pipeline_streaming()
# ---------------------------------------------------------------------------


def test_run_pipeline_streaming_yields_recommendations_in_completion_order():
    """`run_pipeline_streaming` resolves the winning pool's candidates
    concurrently and yields each `Recommendation` as soon as it resolves
    -- in actual completion order, not input/pool order. Two non-confident
    caption candidates (so neither wins the race outright -- both are
    pooled) are resolved against a `TMDBClient` fake whose `search()`
    sleeps a different, deliberately large amount per query, so which one
    "finishes" first is fully controlled by the test, not a race.
    """
    slow_candidate = Candidate(
        raw_text="Slow Movie", source=SourceTag.CAPTION, confidence=0.5
    )
    fast_candidate = Candidate(
        raw_text="Fast Movie", source=SourceTag.CAPTION, confidence=0.5
    )
    ingestor = FakeIngestor(metadata=_ingest_result(caption="two non-confident titles"))
    extractor = FakeCandidateExtractor(
        by_source={SourceTag.CAPTION: [slow_candidate, fast_candidate]}
    )
    tmdb_client = SleepyFakeTMDBClient(
        sleep_seconds_by_query={"Slow Movie": 0.3, "Fast Movie": 0.02},
        result_by_query={
            "Slow Movie": _exact_match_result("Slow Movie", tmdb_id=1),
            "Fast Movie": _exact_match_result("Fast Movie", tmdb_id=2),
        },
    )
    deps = _make_deps(ingestor=ingestor, text_extractor=extractor, tmdb_client=tmdb_client)

    recommendations = list(run_pipeline_streaming(URL, deps))

    assert [rec.query for rec in recommendations] == ["Fast Movie", "Slow Movie"]
    assert [rec.tmdb.id for rec in recommendations] == [2, 1]


def test_run_pipeline_streaming_keeps_unresolved_candidate_with_tmdb_none():
    candidate = Candidate(
        raw_text="Some Obscure Title", source=SourceTag.CAPTION, confidence=0.5
    )
    ingestor = FakeIngestor(metadata=_ingest_result(caption="obscure"))
    extractor = FakeCandidateExtractor(by_source={SourceTag.CAPTION: [candidate]})
    tmdb_client = FakeTMDBClient(default_results=[])
    deps = _make_deps(ingestor=ingestor, text_extractor=extractor, tmdb_client=tmdb_client)

    recommendations = list(run_pipeline_streaming(URL, deps))

    assert len(recommendations) == 1
    assert recommendations[0].tmdb is None
    assert recommendations[0].query == "Some Obscure Title"


def test_run_pipeline_streaming_yields_nothing_when_no_candidates_found():
    ingestor = FakeIngestor(metadata=_ingest_result(caption=""))
    extractor = FakeCandidateExtractor()
    deps = _make_deps(ingestor=ingestor, text_extractor=extractor)

    recommendations = list(run_pipeline_streaming(URL, deps))

    assert recommendations == []


# ---------------------------------------------------------------------------
# Review-fix regression tests (Fix 1 / Fix 2 / Fix 3)
# ---------------------------------------------------------------------------


def test_slow_video_download_does_not_block_a_fast_confident_text_job():
    """Fix 1 regression test: video download + audio extraction must run
    as race-pool jobs alongside the four candidate jobs, not as a
    blocking prerequisite step before the race even starts. A fast,
    confident caption job must let `run_pipeline()` return well before a
    slow `ensure_video()` call has even finished -- proven here with a
    fake `Ingestor` whose `ensure_video()` sleeps for 2s, asserting both
    the wall-clock return time AND (directly, not just inferred from
    timing) that the fake download genuinely had not finished yet.
    """
    caption_candidate = Candidate(
        raw_text="Inception (2010)", source=SourceTag.CAPTION, confidence=0.95
    )
    ingestor = FakeIngestor(
        metadata=_ingest_result(caption="Inception (2010)"),
        ensure_video_delay_seconds=2.0,
    )
    extractor = FakeCandidateExtractor(
        by_source={SourceTag.CAPTION: [caption_candidate]}
    )
    tmdb_client = FakeTMDBClient(
        default_results=[_exact_match_result("Inception (2010)")]
    )
    deps = _make_deps(
        ingestor=ingestor, text_extractor=extractor, tmdb_client=tmdb_client
    )

    start = time.monotonic()
    result = run_pipeline(URL, deps)
    elapsed = time.monotonic() - start

    assert len(result.recommendations) == 1
    assert result.recommendations[0].source == SourceTag.CAPTION
    # Well under the fake download's full 2s delay.
    assert elapsed < 1.0
    # Not just "the pipeline happened to be fast" -- the slow download
    # genuinely had not completed yet by the time run_pipeline returned.
    assert not ingestor.ensure_video_finished_event.is_set()


def test_slow_video_download_runs_on_a_daemon_thread_not_the_shared_pool():
    """Reviewer finding on top of the previous test: `run_pipeline()`
    itself returning promptly is not the whole story for a short-lived
    caller like `reel2movie/cli.py`. `concurrent.futures.thread`
    registers a process-wide `atexit` hook that joins every worker
    thread of EVERY `ThreadPoolExecutor` ever created in the process
    before the process is allowed to exit -- regardless of that
    executor's own `shutdown()` having been called with `wait=False`. If
    `_prepare_video`/`_prepare_audio` ran on `_race_candidate_jobs`'s
    `ThreadPoolExecutor`, a short-lived CLI-style process would still hang
    at exit for however long the backgrounded download takes, even though
    `run_pipeline()` already returned. Proven here: whatever thread(s) are
    still alive right after `run_pipeline()` returns (from the slow fake
    download) must be plain daemon threads -- never a `ThreadPoolExecutor`
    worker -- since only a daemon thread is guaranteed not to block the
    whole process from exiting.
    """
    caption_candidate = Candidate(
        raw_text="Inception (2010)", source=SourceTag.CAPTION, confidence=0.95
    )
    ingestor = FakeIngestor(
        metadata=_ingest_result(caption="Inception (2010)"),
        ensure_video_delay_seconds=1.5,
    )
    extractor = FakeCandidateExtractor(
        by_source={SourceTag.CAPTION: [caption_candidate]}
    )
    tmdb_client = FakeTMDBClient(
        default_results=[_exact_match_result("Inception (2010)")]
    )
    deps = _make_deps(
        ingestor=ingestor, text_extractor=extractor, tmdb_client=tmdb_client
    )

    threads_before = set(threading.enumerate())
    run_pipeline(URL, deps)
    # Give the four race-job daemon threads a brief, bounded moment to
    # actually finish after the race is decided -- a few ms of natural
    # thread-exit lag unrelated to, and much shorter than, the fake
    # download's full 1.5s delay. What's still alive AFTER that moment is
    # what actually matters for CLI process-exit purposes: with all four
    # race jobs AND the two prep jobs now on `_run_in_daemon_thread`
    # daemon threads (see Fix 2), only `_prepare_video`'s own
    # still-sleeping fake-download thread should remain.
    time.sleep(0.3)
    still_alive = [
        t for t in threading.enumerate() if t not in threads_before and t.is_alive()
    ]

    assert not ingestor.ensure_video_finished_event.is_set()
    assert still_alive, "expected the slow fake download's thread to still be alive"
    assert all(t.daemon for t in still_alive)
    assert not any(t.name.startswith("ThreadPoolExecutor") for t in still_alive)


def test_run_pipeline_retries_transient_tmdb_failure_and_resolves(monkeypatch):
    """Fix 2 regression test: `run_pipeline()` (via `_resolve_all`) must
    use `resolve_candidate_with_retry()`, not plain `resolve_candidate()`
    -- a candidate whose TMDB lookup fails with a retryable error must
    still end up resolved (not `tmdb=None`) once the outer retry loop
    retries the whole `resolve_candidate()` call. Before this fix,
    `run_pipeline()` only ever called plain `resolve_candidate()`, which
    would have given up on the very first raise.
    """
    import reel2movie.tmdb.resolver as resolver_module

    # The retry loop's backoff sleep is real wall-clock time by design
    # (not configurable beyond deadline_seconds) -- patched away here
    # purely so this test doesn't need to wait out a real ~1s backoff.
    monkeypatch.setattr(resolver_module.time, "sleep", lambda seconds: None)

    candidate = Candidate(
        raw_text="Flaky Movie (2020)", source=SourceTag.CAPTION, confidence=0.9
    )
    ingestor = FakeIngestor(metadata=_ingest_result(caption="Flaky Movie (2020)"))
    extractor = FakeCandidateExtractor(by_source={SourceTag.CAPTION: [candidate]})
    tmdb_client = FlakyFakeTMDBClient(
        fail_times=1, result=_exact_match_result("Flaky Movie")
    )
    deps = _make_deps(
        ingestor=ingestor, text_extractor=extractor, tmdb_client=tmdb_client
    )

    result = run_pipeline(URL, deps)

    assert tmdb_client.calls == 2  # 1 failure, then 1 successful retry
    assert len(result.recommendations) == 1
    assert result.recommendations[0].tmdb is not None
    assert result.recommendations[0].tmdb.id == 1


def test_visual_fallback_runs_frame_detection_concurrently(monkeypatch):
    """Fix 3 regression test: `_extract_from_visual`'s per-frame
    `poster_detector.detect()` calls must run concurrently (a bounded
    `ThreadPoolExecutor`), not one at a time in a plain `for` loop.
    Proven by timing: 4 frames, each individually "slow" (0.3s), must
    finish in well under the ~1.2s a strictly sequential loop would take,
    if genuinely overlapped.
    """
    frames = [
        FrameSample(path=Path(f"/fake/frame_{i}.jpg"), timestamp_seconds=float(i))
        for i in range(4)
    ]

    class SlowPosterDetector:
        def __init__(self) -> None:
            self.calls: list[Path] = []

        def detect(self, frame, *, cancel_event=None) -> list[Candidate]:
            self.calls.append(frame.path)
            time.sleep(0.3)
            return []

    poster_detector = SlowPosterDetector()
    ingestor = FakeIngestor(metadata=_ingest_result(caption=""))
    extractor = FakeCandidateExtractor()  # nothing confident from text sources
    deps = _make_deps(
        ingestor=ingestor, text_extractor=extractor, poster_detector=poster_detector
    )

    import reel2movie.pipeline.waterfall as waterfall_module

    def fake_sample_frames_at_interval(video_path, interval_seconds, duration_seconds, **kwargs):
        return frames

    monkeypatch.setattr(
        waterfall_module, "sample_frames_at_interval", fake_sample_frames_at_interval
    )
    monkeypatch.setattr(waterfall_module, "dedupe_similar_frames", _identity_dedupe)

    start = time.monotonic()
    run_pipeline(URL, deps)
    elapsed = time.monotonic() - start

    assert len(poster_detector.calls) == 4
    assert elapsed < 1.0
