"""Immutable value objects shared across reel2movie.

These are pure data contracts: no IO, no behavior beyond what dataclasses
give you for free. Every field name/type here is relied on by name from
other subpackages (tmdb/, text_extraction/, ingest/, visual/, pipeline/,
cli.py), so changes here ripple widely — keep this module boring.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class Platform(StrEnum):
    """Source platform a reel was ingested from.

    v1 scope is Instagram-only (see brainstorm.md), but this is an open
    enumeration point: new platforms (TikTok, YouTube Shorts, ...) are
    added as new members here, not by replacing this type.
    """

    INSTAGRAM = "instagram"


class SourceTag(StrEnum):
    """Which extraction source a Candidate/Recommendation came from."""

    CAPTION = "caption"
    CREATOR_COMMENT = "creator_comment"
    FRAME_VISUAL = "frame_visual"


@dataclass(frozen=True, slots=True)
class Comment:
    """A single comment on a reel post."""

    id: str
    author_id: str
    text: str
    is_reply: bool
    like_count: int | None = None


@dataclass(frozen=True, slots=True)
class IngestResult:
    """Metadata fetched for a reel, without the (expensive) video download.

    `video_path` is None until a separate `Ingestor.ensure_video()` call
    populates it — the pipeline only pays for the video download if it
    actually reaches the visual-fallback step (see flow.md step [4]).
    """

    platform: Platform
    url: str
    caption: str
    creator_account_id: str
    comments: list[Comment]
    duration_seconds: float | None
    video_path: Path | None = None


@dataclass(frozen=True, slots=True)
class FrameSample:
    """One sampled video frame on disk, extracted for visual detection."""

    path: Path
    timestamp_seconds: float


@dataclass(frozen=True, slots=True)
class Candidate:
    """A raw candidate movie title string pulled out of some text or frame.

    `confidence` is the extraction layer's own confidence (e.g. "this
    looks like a movie title") — independent of, and prior to, any later
    TMDB match-quality score.
    """

    raw_text: str
    source: SourceTag
    confidence: float


@dataclass(frozen=True, slots=True)
class TMDBSearchResult:
    """One row from a TMDB `search/multi` response.

    Despite the class name, this may represent a TV show as well as a
    movie (TMDB's resolution scope widened to include both -- see
    PROGRESS.md's "Follow-up" section) -- `media_type` ("movie" or "tv")
    says which. The class is not renamed to avoid a sweeping rename across
    every caller for what is, structurally, still the same shape.
    """

    id: int
    title: str
    year: int | None
    poster_path: str | None
    overview: str
    popularity: float
    original_rank: int
    media_type: str


@dataclass(frozen=True, slots=True)
class ResolvedMovie:
    """A TMDB movie OR TV show chosen as the best match for a candidate.

    Despite the class name, this may represent a TV show (`media_type ==
    "tv"`) -- see `TMDBSearchResult`'s docstring for why the name is kept
    as-is rather than swept into a rename.
    """

    id: int
    title: str
    year: int | None
    poster_path: str | None
    overview: str
    match_score: float
    media_type: str


@dataclass(frozen=True, slots=True)
class Recommendation:
    """One output recommendation: a candidate plus its (maybe absent) TMDB match.

    `tmdb` is None when nothing resolved — per flow.md, an unresolved
    candidate is kept in the output with `tmdb=None` rather than dropped.
    """

    query: str
    source: SourceTag
    confidence: float
    tmdb: ResolvedMovie | None = None


@dataclass(frozen=True, slots=True)
class PipelineResult:
    """Final pipeline output for a single reel."""

    reel_url: str
    recommendations: list[Recommendation] = field(default_factory=list)
