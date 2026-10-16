"""Structural interfaces (typing.Protocol) that decouple pipeline stages.

Each Protocol is the seam between a pipeline stage and its implementation,
so every later module (tmdb/, text_extraction/, ingest/, visual/,
pipeline/) can be built and tested independently, with fakes standing in
for the real implementation until it exists.

No implementer needs to inherit from these — Protocols are matched
structurally. They are marked @runtime_checkable so `isinstance(obj, X)`
works for quick structural checks (note: runtime_checkable isinstance
checks method presence/arity only, not signatures or types).
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from reel2movie.core.models import (
    Candidate,
    FrameSample,
    IngestResult,
    SourceTag,
    TMDBSearchResult,
)


@runtime_checkable
class Ingestor(Protocol):
    """Fetches reel metadata, and lazily the video file itself."""

    def fetch_metadata(self, url: str) -> IngestResult:
        """Fetch caption/comments/duration/creator id for a reel URL.

        Must NOT download the video — that is deferred to ensure_video()
        so the pipeline only pays for it when it reaches the visual
        fallback step.
        """
        ...

    def ensure_video(self, result: IngestResult) -> Path:
        """Download the video for `result` if not already present, and
        return the local path. Only called when the pipeline actually
        reaches the visual-fallback step (flow.md step [4]).
        """
        ...


@runtime_checkable
class CandidateExtractor(Protocol):
    """Pulls candidate movie-title strings out of a block of text."""

    def extract(self, text: str, source: SourceTag) -> list[Candidate]:
        ...


@runtime_checkable
class PosterDetector(Protocol):
    """Detects movie posters/title cards in a single sampled video frame."""

    def detect(self, frame: FrameSample) -> list[Candidate]:
        ...


@runtime_checkable
class TMDBClient(Protocol):
    """Looks up candidate titles against TMDB's movie search endpoint."""

    def search_movie(
        self, query: str, year: int | None = None
    ) -> list[TMDBSearchResult]:
        ...
