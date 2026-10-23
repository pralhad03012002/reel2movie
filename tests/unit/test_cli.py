"""Tests for `reel2movie.cli`.

`build_default_pipeline_deps` and `run_pipeline` are monkeypatched as
attributes of `reel2movie.cli` itself (not of the modules they were
originally defined in), since `cli.py` imports them by name into its own
namespace -- the same seam-patching pattern `tests/unit/pipeline/
test_waterfall.py` uses for `sample_frames`. No real network/API/env-var
access happens in any test here.
"""

from __future__ import annotations

import json

import pytest

import reel2movie.cli as cli_module
from reel2movie.core.models import (
    PipelineResult,
    Recommendation,
    ResolvedMovie,
    SourceTag,
)
from reel2movie.pipeline.deps import PipelineDeps


def _fake_deps(**overrides) -> PipelineDeps:
    """A minimally-valid `PipelineDeps` -- fields are never actually
    called in these tests (the methods on `object()` would raise if they
    were), since `run_pipeline` itself is also monkeypatched out.
    """
    defaults = dict(
        ingestor=object(),
        text_extractor=object(),
        poster_detector=object(),
        tmdb_client=object(),
    )
    defaults.update(overrides)
    return PipelineDeps(**defaults)


def _canned_result(url: str) -> PipelineResult:
    return PipelineResult(
        reel_url=url,
        recommendations=[
            Recommendation(
                query="The Matrix (1999)",
                source=SourceTag.CAPTION,
                confidence=0.9,
                tmdb=ResolvedMovie(
                    id=603,
                    title="The Matrix",
                    year=1999,
                    poster_path="/poster.jpg",
                    overview="A hacker discovers reality is a simulation.",
                    match_score=0.95,
                    media_type="movie",
                ),
            ),
            Recommendation(
                query="Some Obscure Title",
                source=SourceTag.FRAME_VISUAL,
                confidence=0.6,
                tmdb=None,
            ),
        ],
    )


def test_prints_expected_json_shape(monkeypatch, capsys):
    url = "https://www.instagram.com/reel/abc123/"
    canned = _canned_result(url)

    monkeypatch.setattr(cli_module, "build_default_pipeline_deps", lambda: _fake_deps())

    def fake_run_pipeline(reel_url, deps):
        assert reel_url == url
        assert isinstance(deps, PipelineDeps)
        return canned

    monkeypatch.setattr(cli_module, "run_pipeline", fake_run_pipeline)

    exit_code = cli_module.main([url])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert captured.err == ""

    payload = json.loads(captured.out)
    assert payload["reel_url"] == url
    assert len(payload["recommendations"]) == 2

    resolved = payload["recommendations"][0]
    assert resolved["query"] == "The Matrix (1999)"
    assert resolved["source"] == "caption"
    assert resolved["confidence"] == 0.9
    assert resolved["tmdb"] == {
        "id": 603,
        "title": "The Matrix",
        "year": 1999,
        "poster_path": "/poster.jpg",
        "overview": "A hacker discovers reality is a simulation.",
        "media_type": "movie",
    }
    # match_score is a real ResolvedMovie field but is not part of
    # brainstorm.md's documented output shape, so it must not leak in.
    assert "match_score" not in resolved["tmdb"]
    # media_type is new: a deliberate, documented deviation from
    # brainstorm.md's original movie-only output shape -- confirms the
    # final JSON shows whether a recommendation resolved to a movie or
    # a TV show.
    assert resolved["tmdb"]["media_type"] == "movie"

    unresolved = payload["recommendations"][1]
    assert unresolved["query"] == "Some Obscure Title"
    assert unresolved["source"] == "frame_visual"
    assert unresolved["confidence"] == 0.6
    assert unresolved["tmdb"] is None


def test_missing_api_key_prints_clear_error_on_stderr_and_returns_nonzero(
    monkeypatch, capsys
):
    def raise_missing_key() -> PipelineDeps:
        raise RuntimeError(
            "TMDB_API_KEY not set; see .env.example for required env vars"
        )

    monkeypatch.setattr(cli_module, "build_default_pipeline_deps", raise_missing_key)

    exit_code = cli_module.main(["https://www.instagram.com/reel/abc123/"])

    assert exit_code != 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "TMDB_API_KEY" in captured.err


def test_fatal_pipeline_error_prints_clear_error_on_stderr_and_returns_nonzero(
    monkeypatch, capsys
):
    monkeypatch.setattr(cli_module, "build_default_pipeline_deps", lambda: _fake_deps())

    def raise_unreachable(reel_url, deps):
        raise RuntimeError("could not fetch metadata: URL is unreachable")

    monkeypatch.setattr(cli_module, "run_pipeline", raise_unreachable)

    exit_code = cli_module.main(["https://www.instagram.com/reel/does-not-exist/"])

    assert exit_code != 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "unreachable" in captured.err


def test_frame_interval_seconds_override_reaches_pipeline_deps(monkeypatch):
    fake_deps = _fake_deps()
    monkeypatch.setattr(cli_module, "build_default_pipeline_deps", lambda: fake_deps)

    seen_frame_intervals = []

    def fake_run_pipeline(reel_url, deps):
        seen_frame_intervals.append(deps.frame_interval_seconds)
        return PipelineResult(reel_url=reel_url, recommendations=[])

    monkeypatch.setattr(cli_module, "run_pipeline", fake_run_pipeline)

    exit_code = cli_module.main(
        ["https://www.instagram.com/reel/abc123/", "--frame-interval-seconds", "3"]
    )

    assert exit_code == 0
    assert seen_frame_intervals == [3.0]
    # The override mutates the very deps object build_default_pipeline_deps
    # returned, not a copy.
    assert fake_deps.frame_interval_seconds == 3.0


def test_no_frame_interval_seconds_override_leaves_default_untouched(monkeypatch):
    fake_deps = _fake_deps()
    default_frame_interval_seconds = fake_deps.frame_interval_seconds
    monkeypatch.setattr(cli_module, "build_default_pipeline_deps", lambda: fake_deps)

    seen_frame_intervals = []

    def fake_run_pipeline(reel_url, deps):
        seen_frame_intervals.append(deps.frame_interval_seconds)
        return PipelineResult(reel_url=reel_url, recommendations=[])

    monkeypatch.setattr(cli_module, "run_pipeline", fake_run_pipeline)

    exit_code = cli_module.main(["https://www.instagram.com/reel/abc123/"])

    assert exit_code == 0
    assert seen_frame_intervals == [default_frame_interval_seconds]
