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


def test_audio_transcriber_is_none_when_whisper_cpp_model_path_unset(monkeypatch):
    """`build_default_pipeline_deps()` must leave `audio_transcriber`
    `None` when `WHISPER_CPP_MODEL_PATH` is unset -- whisper.cpp is an
    optional capability most environments won't have configured, and
    wiring a real (if lazy) transcriber regardless would make every run's
    audio-transcript race job attempt a `transcribe()` call that
    immediately raises `RuntimeError`, logged at ERROR with a full
    traceback on every single run (see `deps.py`'s own docstring). `None`
    is the same "capability not available" signal
    `disambiguation_chat_client` already uses, and makes
    `pipeline/waterfall.py`'s `_prepare_audio`/
    `_extract_from_audio_transcript` skip the audio work entirely.
    """
    monkeypatch.setenv("TMDB_API_KEY", "fake-tmdb-token")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("VISION_BACKEND", raising=False)
    monkeypatch.delenv("INSTAGRAM_COOKIES_FILE", raising=False)
    monkeypatch.delenv("WHISPER_CPP_MODEL_PATH", raising=False)

    deps = build_default_pipeline_deps()

    assert deps.audio_transcriber is None


def test_audio_transcriber_is_wired_when_whisper_cpp_model_path_set(monkeypatch):
    """When `WHISPER_CPP_MODEL_PATH` IS set, `build_default_pipeline_deps()`
    must wire a real (lazy) `AudioTranscriber` -- still deferring the
    actual `WhisperCppTranscriber` construction/`WHISPER_CPP_BINARY` read
    until `.transcribe()` is called (see `_LazyWhisperCppTranscriber`'s
    docstring), never eagerly at construction time.
    """
    monkeypatch.setenv("TMDB_API_KEY", "fake-tmdb-token")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("VISION_BACKEND", raising=False)
    monkeypatch.delenv("INSTAGRAM_COOKIES_FILE", raising=False)
    monkeypatch.setenv("WHISPER_CPP_MODEL_PATH", "/fake/model.bin")

    deps = build_default_pipeline_deps()

    assert deps.audio_transcriber is not None


def test_pipeline_deps_audio_transcriber_defaults_to_none():
    """A `PipelineDeps` built directly (e.g. by a test, not via
    `build_default_pipeline_deps()`) without specifying `audio_transcriber`
    must default to `None` -- "no audio-transcript capability available",
    not an error -- so every pre-existing direct `PipelineDeps(...)`
    construction (predating the audio-transcript race job) keeps working
    unmodified.
    """
    deps = PipelineDeps(
        ingestor=None,
        text_extractor=None,
        poster_detector=None,
        tmdb_client=None,
    )

    assert deps.audio_transcriber is None
