"""Minimal construction check for `build_default_pipeline_deps()`.

Per the subtask spec, this is wiring, not logic -- no behavioral tests
here, just confirming it builds a `PipelineDeps` without raising when the
required env vars are present. No live network/API call happens during
construction of any of the wired classes.
"""

from __future__ import annotations

from reel2movie.pipeline.deps import PipelineDeps, build_default_pipeline_deps


def test_builds_without_raising_when_required_env_vars_present(monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "fake-tmdb-token")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-anthropic-key")
    monkeypatch.delenv("INSTAGRAM_COOKIES_FILE", raising=False)

    deps = build_default_pipeline_deps()

    assert isinstance(deps, PipelineDeps)
    assert deps.frame_count > 0
