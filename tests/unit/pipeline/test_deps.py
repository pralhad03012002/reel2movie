"""Minimal construction check for `build_default_pipeline_deps()`.

Per the subtask spec, this is wiring, not logic -- no behavioral tests
here, just confirming it builds a `PipelineDeps` without raising when the
required env vars are present. No live network/API call happens during
construction of any of the wired classes.
"""

from __future__ import annotations

import pytest

from reel2movie.pipeline.deps import PipelineDeps, build_default_pipeline_deps
from reel2movie.text_extraction.claude_code_extractor import (
    ClaudeCodeCandidateExtractor,
)
from reel2movie.text_extraction.fallback_extractor import FallbackCandidateExtractor
from reel2movie.text_extraction.regex_extractor import RegexCandidateExtractor


def test_builds_without_raising_when_required_env_vars_present(monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "fake-tmdb-token")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-anthropic-key")
    monkeypatch.delenv("INSTAGRAM_COOKIES_FILE", raising=False)

    deps = build_default_pipeline_deps()

    assert isinstance(deps, PipelineDeps)
    assert deps.frame_interval_seconds > 0
    assert deps.frame_dedup_threshold >= 0


def test_frame_interval_seconds_defaults_to_half_a_second():
    """0.5s was chosen via empirical A/B testing (see `deps.py`'s comment
    above `_DEFAULT_FRAME_INTERVAL_SECONDS`) over the old 1.0s default --
    pin the exact value so a regression back to 1.0 (or any other value)
    is caught directly, independent of `build_default_pipeline_deps()`'s
    wiring.
    """
    deps = PipelineDeps(
        ingestor=None,
        text_extractor=None,
        poster_detector=None,
        tmdb_client=None,
    )

    assert deps.frame_interval_seconds == 0.5


def test_builds_without_anthropic_key_when_backend_defaults_to_claude_code(
    monkeypatch,
):
    """The whole point of this subtask: a user who leaves ANTHROPIC_API_KEY
    entirely unset (using the default `claude_code` vision backend) must
    never hit a missing-API-key error anywhere in construction.
    """
    monkeypatch.setenv("TMDB_API_KEY", "fake-tmdb-token")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("VISION_BACKEND", raising=False)
    monkeypatch.delenv("INSTAGRAM_COOKIES_FILE", raising=False)

    deps = build_default_pipeline_deps()

    assert isinstance(deps, PipelineDeps)


def test_builds_without_anthropic_key_when_backend_explicitly_claude_code(
    monkeypatch,
):
    monkeypatch.setenv("TMDB_API_KEY", "fake-tmdb-token")
    monkeypatch.setenv("VISION_BACKEND", "claude_code")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("INSTAGRAM_COOKIES_FILE", raising=False)

    deps = build_default_pipeline_deps()

    assert isinstance(deps, PipelineDeps)


def test_anthropic_api_backend_raises_when_key_unset(monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "fake-tmdb-token")
    monkeypatch.setenv("VISION_BACKEND", "anthropic_api")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("INSTAGRAM_COOKIES_FILE", raising=False)

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        build_default_pipeline_deps()


def test_anthropic_api_backend_succeeds_when_key_set(monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "fake-tmdb-token")
    monkeypatch.setenv("VISION_BACKEND", "anthropic_api")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-anthropic-key")
    monkeypatch.delenv("INSTAGRAM_COOKIES_FILE", raising=False)

    deps = build_default_pipeline_deps()

    assert isinstance(deps, PipelineDeps)


def test_text_extractor_is_fallback_wrapping_regex_and_claude_code(monkeypatch):
    """The new always-on text fallback: regex first (free/instant), claude
    CLI second -- wired regardless of VISION_BACKEND's value.
    """
    monkeypatch.setenv("TMDB_API_KEY", "fake-tmdb-token")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("VISION_BACKEND", raising=False)
    monkeypatch.delenv("INSTAGRAM_COOKIES_FILE", raising=False)

    deps = build_default_pipeline_deps()

    assert isinstance(deps.text_extractor, FallbackCandidateExtractor)
    assert isinstance(deps.text_extractor._primary, RegexCandidateExtractor)
    assert isinstance(deps.text_extractor._fallback, ClaudeCodeCandidateExtractor)
