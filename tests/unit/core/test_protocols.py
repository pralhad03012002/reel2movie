"""Tests for reel2movie.core.protocols: minimal fakes satisfy each Protocol.

Each Protocol is @runtime_checkable, so a minimal fake class implementing
the right method names/arities should pass isinstance(fake, Protocol).
Note runtime_checkable isinstance checks are structural on method
presence only (not signatures/types), which is why we also exercise each
fake by calling it with the real model types.
"""

from __future__ import annotations

from pathlib import Path

from reel2movie.core.models import (
    Candidate,
    FrameSample,
    IngestResult,
    Platform,
    SourceTag,
    TMDBSearchResult,
)
from reel2movie.core.protocols import (
    CandidateExtractor,
    Ingestor,
    PosterDetector,
    TMDBClient,
)


class FakeIngestor:
    def fetch_metadata(self, url: str) -> IngestResult:
        return IngestResult(
            platform=Platform.INSTAGRAM,
            url=url,
            caption="caption text",
            creator_account_id="creator123",
            comments=[],
            duration_seconds=10.0,
        )

    def ensure_video(self, result: IngestResult) -> Path:
        return Path("/tmp/fake_video.mp4")


class FakeCandidateExtractor:
    def extract(self, text: str, source: SourceTag) -> list[Candidate]:
        return [Candidate(raw_text=text, source=source, confidence=1.0)]


class FakePosterDetector:
    def detect(self, frame: FrameSample) -> list[Candidate]:
        return [
            Candidate(raw_text="Detected Title", source=SourceTag.FRAME_VISUAL, confidence=0.5)
        ]


class FakeTMDBClient:
    def search(self, query: str, year: int | None = None) -> list[TMDBSearchResult]:
        return [
            TMDBSearchResult(
                id=1,
                title=query,
                year=year,
                poster_path=None,
                overview="",
                popularity=1.0,
                original_rank=0,
                media_type="movie",
            )
        ]


def test_fake_ingestor_satisfies_protocol():
    fake = FakeIngestor()
    assert isinstance(fake, Ingestor)
    result = fake.fetch_metadata("https://instagram.com/reel/abc")
    assert isinstance(result, IngestResult)
    assert fake.ensure_video(result) == Path("/tmp/fake_video.mp4")


def test_fake_candidate_extractor_satisfies_protocol():
    fake = FakeCandidateExtractor()
    assert isinstance(fake, CandidateExtractor)
    candidates = fake.extract("Her (2013)", SourceTag.CAPTION)
    assert all(isinstance(c, Candidate) for c in candidates)


def test_fake_poster_detector_satisfies_protocol():
    fake = FakePosterDetector()
    assert isinstance(fake, PosterDetector)
    frame = FrameSample(path=Path("/tmp/frame_0.jpg"), timestamp_seconds=1.0)
    candidates = fake.detect(frame)
    assert all(isinstance(c, Candidate) for c in candidates)


def test_fake_tmdb_client_satisfies_protocol():
    fake = FakeTMDBClient()
    assert isinstance(fake, TMDBClient)
    results = fake.search("Her", year=2013)
    assert all(isinstance(r, TMDBSearchResult) for r in results)


def test_object_missing_methods_does_not_satisfy_protocol():
    class NotAnIngestor:
        def fetch_metadata(self, url: str) -> IngestResult:
            raise NotImplementedError

        # missing ensure_video

    assert not isinstance(NotAnIngestor(), Ingestor)


def test_plain_object_does_not_satisfy_any_protocol():
    class Empty:
        pass

    empty = Empty()
    assert not isinstance(empty, Ingestor)
    assert not isinstance(empty, CandidateExtractor)
    assert not isinstance(empty, PosterDetector)
    assert not isinstance(empty, TMDBClient)
