"""Tests for `pipeline/waterfall.py`'s `run_pipeline` waterfall.

Fakes for all four Protocols (`Ingestor`, `CandidateExtractor`,
`PosterDetector`, `TMDBClient`) live in this file; none of them touch the
network, a subprocess, or any real third-party client. `sample_frames`
(a free function, not a Protocol method) is monkeypatched at
`reel2movie.pipeline.waterfall.sample_frames` -- the name waterfall.py
imports it under -- rather than adding a new injection seam that isn't in
the plan.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

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
from reel2movie.pipeline.waterfall import CONFIDENCE_THRESHOLD, _dedupe, run_pipeline

URL = "https://instagram.com/reel/fake123/"


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class FakeIngestor:
    """Fake `Ingestor`: configurable metadata/video result, or a raise."""

    metadata: IngestResult | None = None
    metadata_error: Exception | None = None
    video_path: Path = Path("/fake/video.mp4")
    ensure_video_error: Exception | None = None
    fetch_metadata_calls: list[str] = field(default_factory=list)
    ensure_video_calls: list[IngestResult] = field(default_factory=list)

    def fetch_metadata(self, url: str) -> IngestResult:
        self.fetch_metadata_calls.append(url)
        if self.metadata_error is not None:
            raise self.metadata_error
        assert self.metadata is not None
        return self.metadata

    def ensure_video(self, result: IngestResult) -> Path:
        self.ensure_video_calls.append(result)
        if self.ensure_video_error is not None:
            raise self.ensure_video_error
        return self.video_path


@dataclass
class FakeCandidateExtractor:
    """Fake `CandidateExtractor`.

    `by_text` overrides take priority (keyed by the exact `text` passed
    in -- useful for returning different candidates per comment); falling
    back to `by_source` (keyed by `SourceTag`) otherwise. Every call is
    recorded in `calls` so tests can assert a step was never invoked.
    """

    by_text: dict[str, list[Candidate]] = field(default_factory=dict)
    by_source: dict[SourceTag, list[Candidate]] = field(default_factory=dict)
    error: Exception | None = None
    calls: list[tuple[str, SourceTag]] = field(default_factory=list)

    def extract(self, text: str, source: SourceTag) -> list[Candidate]:
        self.calls.append((text, source))
        if self.error is not None:
            raise self.error
        if text in self.by_text:
            return list(self.by_text[text])
        return list(self.by_source.get(source, []))


@dataclass
class FakePosterDetector:
    """Fake `PosterDetector`, keyed by frame path."""

    responses: dict[Path, list[Candidate]] = field(default_factory=dict)
    calls: list[FrameSample] = field(default_factory=list)

    def detect(self, frame: FrameSample) -> list[Candidate]:
        self.calls.append(frame)
        return list(self.responses.get(frame.path, []))


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
    frame_count: int = 6,
) -> PipelineDeps:
    return PipelineDeps(
        ingestor=ingestor,
        text_extractor=text_extractor,
        poster_detector=poster_detector or FakePosterDetector(),
        tmdb_client=tmdb_client or FakeTMDBClient(),
        frame_count=frame_count,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_confidence_threshold_matches_regex_extractor_high_tier():
    from reel2movie.text_extraction.regex_extractor import HIGH_CONFIDENCE

    assert CONFIDENCE_THRESHOLD == HIGH_CONFIDENCE


def test_caption_confident_short_circuits_comment_and_visual():
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

    # Only the caption extraction call happened -- no comment-extraction
    # call, no frame detection, no video download.
    assert extractor.calls == [("Inception (2010)", SourceTag.CAPTION)]
    assert poster_detector.calls == []
    assert ingestor.ensure_video_calls == []

    assert len(result.recommendations) == 1
    rec = result.recommendations[0]
    assert rec.source == SourceTag.CAPTION
    assert rec.tmdb is not None
    assert rec.tmdb.id == 1


def test_creator_comment_confident_short_circuits_visual_and_filters_comments():
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

    # Caption step ran (recorded), only the creator's own top-level
    # comment's text was ever extracted -- the other author's comment and
    # the creator's reply never reached the extractor.
    extracted_texts = [text for text, _source in extractor.calls]
    assert "not a confident caption" in extracted_texts
    assert "Parasite (2019)" in extracted_texts
    assert "Avatar (2009)" not in extracted_texts
    assert "Interstellar (2014)" not in extracted_texts

    # Visual fallback never invoked.
    assert poster_detector.calls == []
    assert ingestor.ensure_video_calls == []

    assert len(result.recommendations) == 1
    assert result.recommendations[0].source == SourceTag.CREATOR_COMMENT


def test_both_text_sources_empty_triggers_visual_fallback_once():
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

    def fake_sample_frames(video_path, n, duration_seconds, **kwargs):
        sample_calls.append((video_path, n, duration_seconds))
        return [frame]

    original = waterfall_module.sample_frames
    waterfall_module.sample_frames = fake_sample_frames
    try:
        result = run_pipeline(URL, deps)
    finally:
        waterfall_module.sample_frames = original

    assert len(ingestor.ensure_video_calls) == 1
    assert len(sample_calls) == 1
    assert poster_detector.calls == [frame]
    assert len(result.recommendations) == 1
    assert result.recommendations[0].source == SourceTag.FRAME_VISUAL


def test_frame_count_passed_through_to_sample_frames(monkeypatch):
    ingestor = FakeIngestor(metadata=_ingest_result(caption=""))
    extractor = FakeCandidateExtractor()
    deps = _make_deps(
        ingestor=ingestor,
        text_extractor=extractor,
        frame_count=9,
    )

    import reel2movie.pipeline.waterfall as waterfall_module

    captured = {}

    def fake_sample_frames(video_path, n, duration_seconds, **kwargs):
        captured["n"] = n
        return []

    monkeypatch.setattr(waterfall_module, "sample_frames", fake_sample_frames)

    run_pipeline(URL, deps)

    assert captured["n"] == 9


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
    an already-answered question, so `_dedupe` must drop it, leaving only
    the resolved one.
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

    deduped = _dedupe([resolved_rec, unresolved_duplicate_rec])

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

    deduped = _dedupe([lone_unresolved_rec])

    assert deduped == [lone_unresolved_rec]


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

    deduped = _dedupe([first_unresolved_rec, second_unresolved_rec])

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


def test_caption_extraction_internal_error_falls_through_to_comment_step():
    comments = [
        Comment(id="c1", author_id="creator-1", text="Dune (2021)", is_reply=False)
    ]
    comment_candidate = Candidate(
        raw_text="Dune (2021)", source=SourceTag.CREATOR_COMMENT, confidence=0.9
    )
    ingestor = FakeIngestor(
        metadata=_ingest_result(caption="caption text", comments=comments)
    )
    extractor = FakeCandidateExtractor()
    # Make the FIRST call (caption) raise, but subsequent calls (comments)
    # behave normally, by using a small stateful wrapper.
    call_count = {"n": 0}
    real_extract = extractor.extract

    def flaky_extract(text, source):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("boom")
        return real_extract(text, source)

    extractor.extract = flaky_extract  # type: ignore[method-assign]
    extractor.by_text = {"Dune (2021)": [comment_candidate]}

    tmdb_client = FakeTMDBClient(default_results=[_exact_match_result("Dune (2021)")])
    deps = _make_deps(
        ingestor=ingestor, text_extractor=extractor, tmdb_client=tmdb_client
    )

    result = run_pipeline(URL, deps)

    assert len(result.recommendations) == 1
    assert result.recommendations[0].source == SourceTag.CREATOR_COMMENT


def test_visual_fallback_internal_error_is_swallowed_not_raised(monkeypatch):
    ingestor = FakeIngestor(
        metadata=_ingest_result(caption=""), ensure_video_error=RuntimeError("no video")
    )
    extractor = FakeCandidateExtractor()
    deps = _make_deps(ingestor=ingestor, text_extractor=extractor)

    result = run_pipeline(URL, deps)

    assert result.recommendations == []


def test_visual_fallback_cleans_up_its_own_temp_frame_directory(monkeypatch):
    """Regression test for the temp-dir leak: `waterfall.py` must create its
    own `output_dir`, pass it to `sample_frames`, and remove it (via
    `shutil.rmtree`) once poster detection is done with the frames --
    `frame_sampler.py` itself never cleans up what it creates.
    """
    frame_candidate = Candidate(
        raw_text="Oldboy (2003)", source=SourceTag.FRAME_VISUAL, confidence=0.8
    )
    ingestor = FakeIngestor(metadata=_ingest_result(caption=""))
    extractor = FakeCandidateExtractor()  # no confident candidates anywhere
    captured_dirs = []

    def fake_sample_frames(video_path, n, duration_seconds, *, output_dir=None):
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
    # it's actually handed (captured_dirs isn't known until sample_frames
    # runs), via a tiny closure instead of the dict-keyed fake.
    def detect(frame):
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

    monkeypatch.setattr(waterfall_module, "sample_frames", fake_sample_frames)

    result = run_pipeline(URL, deps)

    assert len(captured_dirs) == 1
    frames_dir = captured_dirs[0]
    # The directory existed while frames were being read (asserted inside
    # fake_sample_frames above) but is gone by the time run_pipeline
    # returns -- cleaned up after poster detection finished using it.
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

    def fake_sample_frames(video_path, n, duration_seconds, *, output_dir=None):
        captured_dirs.append(output_dir)
        return [FrameSample(path=output_dir / "frame_000.jpg", timestamp_seconds=1.0)]

    class ExplodingPosterDetector:
        def __init__(self):
            self.calls: list = []

        def detect(self, frame):
            self.calls.append(frame)
            raise RuntimeError("poster detector blew up")

    deps = _make_deps(
        ingestor=ingestor,
        text_extractor=extractor,
        poster_detector=ExplodingPosterDetector(),
    )

    import reel2movie.pipeline.waterfall as waterfall_module

    monkeypatch.setattr(waterfall_module, "sample_frames", fake_sample_frames)

    result = run_pipeline(URL, deps)

    assert len(captured_dirs) == 1
    assert not captured_dirs[0].exists()
    # The whole visual step is swallowed as "found nothing", per the
    # existing "internal failure -> []" rule for this step.
    assert result.recommendations == []


def test_visual_fallback_with_none_duration_and_failed_probe_logs_warning_and_skips_sample_frames(
    monkeypatch, caplog
):
    """Regression test (updated for the duration-probing fallback):
    `result.duration_seconds=None` must be handled as its own distinct,
    clearly-logged case -- not passed into `sample_frames` (which would
    raise `TypeError` on `None <= 0` and get silently swallowed by the
    blanket `except Exception`, indistinguishable from a genuine "visual
    detector found nothing" outcome). `ensure_video` now runs
    unconditionally (new behavior: it's required to attempt the
    duration-probing fallback at all), but when probing ALSO fails,
    duration is still genuinely undeterminable and `sample_frames` must
    never be called.
    """
    ingestor = FakeIngestor(metadata=_ingest_result(caption="", duration_seconds=None))
    extractor = FakeCandidateExtractor()  # nothing confident from text sources
    deps = _make_deps(ingestor=ingestor, text_extractor=extractor)

    import reel2movie.pipeline.waterfall as waterfall_module
    from reel2movie.visual.frame_sampler import FrameExtractionError

    def sample_frames_must_not_be_called(*args, **kwargs):
        raise AssertionError(
            "sample_frames must never be called when duration is undeterminable"
        )

    def probe_duration_seconds_fails(video_path):
        raise FrameExtractionError("could not find a Duration: line; corrupt file")

    monkeypatch.setattr(
        waterfall_module, "sample_frames", sample_frames_must_not_be_called
    )
    monkeypatch.setattr(
        waterfall_module, "probe_duration_seconds", probe_duration_seconds_fails
    )

    with caplog.at_level("WARNING"):
        result = run_pipeline(URL, deps)

    assert result.recommendations == []
    # ensure_video now runs unconditionally once the visual step is
    # reached -- it's needed to even attempt the duration-probing
    # fallback -- unlike the old check-before-downloading behavior.
    assert len(ingestor.ensure_video_calls) == 1
    assert any(
        "unknown reel duration" in record.message for record in caplog.records
    )


def test_visual_fallback_none_duration_falls_back_to_probed_duration(monkeypatch):
    """`result.duration_seconds=None` must no longer short-circuit the
    visual fallback: `ensure_video` runs, `probe_duration_seconds` is
    tried, and on success `sample_frames` is called with the PROBED
    duration, not a stale/wrong one.
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

    def fake_probe_duration_seconds(video_path):
        probe_calls.append(video_path)
        return probed_duration

    sample_calls = []

    def fake_sample_frames(video_path, n, duration_seconds, **kwargs):
        sample_calls.append((video_path, n, duration_seconds))
        return [frame]

    monkeypatch.setattr(
        waterfall_module, "probe_duration_seconds", fake_probe_duration_seconds
    )
    monkeypatch.setattr(waterfall_module, "sample_frames", fake_sample_frames)

    result = run_pipeline(URL, deps)

    assert len(ingestor.ensure_video_calls) == 1
    assert len(probe_calls) == 1
    assert len(sample_calls) == 1
    # sample_frames must receive the PROBED duration, not None/stale.
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

    def probe_duration_seconds_must_not_be_called(video_path):
        raise AssertionError(
            "probe_duration_seconds must not be called when metadata "
            "duration is already valid"
        )

    sample_calls = []

    def fake_sample_frames(video_path, n, duration_seconds, **kwargs):
        sample_calls.append((video_path, n, duration_seconds))
        return []

    monkeypatch.setattr(
        waterfall_module,
        "probe_duration_seconds",
        probe_duration_seconds_must_not_be_called,
    )
    monkeypatch.setattr(waterfall_module, "sample_frames", fake_sample_frames)

    run_pipeline(URL, deps)

    assert len(ingestor.ensure_video_calls) == 1
    assert sample_calls == [(ingestor.video_path, deps.frame_count, 30.0)]
