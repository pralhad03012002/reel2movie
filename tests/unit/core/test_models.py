"""Tests for reel2movie.core.models: construction, equality, immutability."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from reel2movie.core.models import (
    Candidate,
    Comment,
    FrameSample,
    IngestResult,
    PipelineResult,
    Platform,
    Recommendation,
    ResolvedMovie,
    SourceTag,
    TMDBSearchResult,
)


def test_platform_has_instagram_member():
    assert Platform.INSTAGRAM == "instagram"
    # Open enumeration point: more members can be added later without
    # breaking this assertion.
    assert "INSTAGRAM" in Platform.__members__


def test_source_tag_members():
    assert SourceTag.CAPTION == "caption"
    assert SourceTag.CREATOR_COMMENT == "creator_comment"
    assert SourceTag.FRAME_VISUAL == "frame_visual"


def test_comment_construction_and_defaults():
    c = Comment(id="1", author_id="creator", text="watch Her (2013)", is_reply=False)
    assert c.like_count is None
    c2 = Comment(id="1", author_id="creator", text="watch Her (2013)", is_reply=False)
    assert c == c2


def test_comment_is_immutable():
    c = Comment(id="1", author_id="creator", text="hi", is_reply=False)
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.text = "changed"  # type: ignore[misc]


def test_ingest_result_video_path_defaults_to_none():
    result = IngestResult(
        platform=Platform.INSTAGRAM,
        url="https://instagram.com/reel/abc",
        caption="5 movies you need to watch",
        creator_account_id="creator123",
        comments=[],
        duration_seconds=42.0,
    )
    assert result.video_path is None
    assert result.platform is Platform.INSTAGRAM


def test_ingest_result_with_video_path_and_equality():
    comments = [Comment(id="1", author_id="creator123", text="It (2017)", is_reply=False)]
    a = IngestResult(
        platform=Platform.INSTAGRAM,
        url="https://instagram.com/reel/abc",
        caption="cap",
        creator_account_id="creator123",
        comments=comments,
        duration_seconds=10.0,
        video_path=Path("/tmp/video.mp4"),
    )
    b = IngestResult(
        platform=Platform.INSTAGRAM,
        url="https://instagram.com/reel/abc",
        caption="cap",
        creator_account_id="creator123",
        comments=comments,
        duration_seconds=10.0,
        video_path=Path("/tmp/video.mp4"),
    )
    assert a == b
    assert a.video_path == Path("/tmp/video.mp4")


def test_ingest_result_is_immutable():
    result = IngestResult(
        platform=Platform.INSTAGRAM,
        url="u",
        caption="c",
        creator_account_id="id",
        comments=[],
        duration_seconds=None,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.caption = "other"  # type: ignore[misc]


def test_candidate_construction():
    cand = Candidate(raw_text="Her (2013)", source=SourceTag.CAPTION, confidence=0.9)
    assert cand.source is SourceTag.CAPTION
    assert 0.0 <= cand.confidence <= 1.0


def test_frame_sample_construction_and_equality():
    f1 = FrameSample(path=Path("/tmp/frame_0.jpg"), timestamp_seconds=1.5)
    f2 = FrameSample(path=Path("/tmp/frame_0.jpg"), timestamp_seconds=1.5)
    assert f1 == f2
    with pytest.raises(dataclasses.FrozenInstanceError):
        f1.timestamp_seconds = 2.0  # type: ignore[misc]


def test_tmdb_search_result_construction():
    r = TMDBSearchResult(
        id=1,
        title="Her",
        year=2013,
        poster_path="/poster.jpg",
        overview="A man falls in love with an AI.",
        popularity=12.3,
        original_rank=0,
        media_type="movie",
    )
    assert r.original_rank == 0
    assert r.year == 2013
    assert r.media_type == "movie"


def test_resolved_movie_construction():
    rm = ResolvedMovie(
        id=1,
        title="Her",
        year=2013,
        poster_path="/poster.jpg",
        overview="overview",
        match_score=0.95,
        media_type="movie",
    )
    assert rm.match_score == 0.95
    assert rm.media_type == "movie"


def test_recommendation_defaults_tmdb_to_none():
    rec = Recommendation(query="Her", source=SourceTag.CAPTION, confidence=0.8)
    assert rec.tmdb is None


def test_recommendation_unresolved_candidate_is_kept_not_dropped():
    # flow.md: an unresolved candidate is kept with tmdb=None, not dropped.
    rec = Recommendation(
        query="Some Obscure Title",
        source=SourceTag.FRAME_VISUAL,
        confidence=0.4,
        tmdb=None,
    )
    assert rec.query == "Some Obscure Title"
    assert rec.tmdb is None


def test_recommendation_with_resolved_tmdb():
    rm = ResolvedMovie(
        id=1,
        title="Her",
        year=2013,
        poster_path=None,
        overview="o",
        match_score=1.0,
        media_type="movie",
    )
    rec = Recommendation(query="Her", source=SourceTag.CAPTION, confidence=0.9, tmdb=rm)
    assert rec.tmdb is rm


def test_recommendation_is_immutable():
    rec = Recommendation(query="Her", source=SourceTag.CAPTION, confidence=0.9)
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.confidence = 0.1  # type: ignore[misc]


def test_pipeline_result_defaults_to_empty_recommendations():
    result = PipelineResult(reel_url="https://instagram.com/reel/abc")
    assert result.recommendations == []


def test_pipeline_result_with_recommendations_and_equality():
    rec = Recommendation(query="Her", source=SourceTag.CAPTION, confidence=0.9)
    a = PipelineResult(reel_url="u", recommendations=[rec])
    b = PipelineResult(reel_url="u", recommendations=[rec])
    assert a == b


def test_pipeline_result_default_factory_does_not_share_list_between_instances():
    a = PipelineResult(reel_url="a")
    b = PipelineResult(reel_url="b")
    a.recommendations.append(
        Recommendation(query="x", source=SourceTag.CAPTION, confidence=0.5)
    )
    assert b.recommendations == []
