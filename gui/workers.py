"""Background-thread workers + plain helper functions for the GUI.

This module is the ONLY place in the GUI codebase allowed to know about
`QThread`, the local `claude` CLI usability check, and the `VISION_BACKEND`
env-var fallback logic. It contains zero Qt widget code -- just QThread
subclasses and plain functions. Other GUI modules (presentational widgets,
the main window) import from here by the exact names/signatures below; that
interface is a fixed contract other code already assumes, so names and
signatures must not change.
"""

from __future__ import annotations

import os
import shutil
import subprocess

from PySide6.QtCore import QThread, Signal

from reel2movie.core.models import PipelineResult
from reel2movie.pipeline.deps import PipelineDeps, build_default_pipeline_deps

# `dedupe_recommendations` is a public `waterfall.py` function (promoted
# from a leading-underscore `_dedupe` once this cross-module reuse became
# a real contract, not just an internal implementation detail) --
# `tests/unit/pipeline/test_waterfall.py` also imports it directly rather
# than re-deriving its merge behavior. Reusing the exact same function
# here (instead of writing a simpler GUI-side "dedupe by tmdb.id" pass)
# means the `PipelineResult` this `PipelineRunner` emits via `succeeded` is
# byte-for-byte identical to what `run_pipeline()` itself would have
# produced for the same reel -- same same-tmdb-id-keep-highest-confidence
# merge, same unresolved/resolved same-query collapsing, same confidence
# sort -- rather than risking a second, GUI-only dedupe rule silently
# drifting from the "real" one over time.
from reel2movie.pipeline.waterfall import dedupe_recommendations, run_pipeline_streaming


def check_claude_cli_usable(timeout_seconds: float = 5.0) -> bool:
    """True iff `claude` is on PATH AND a cheap invocation succeeds.

    Checks `shutil.which("claude")` first (returns False immediately if
    not found on PATH), then runs `claude --version` with a timeout.
    Never raises -- any missing binary, non-zero exit, timeout, or OSError
    is caught internally and turned into False. Pure function, safe to
    call from any thread.
    """
    if shutil.which("claude") is None:
        return False
    try:
        proc = subprocess.run(
            ["claude", "--version"],
            capture_output=True,
            timeout=timeout_seconds,
        )
    except Exception:
        # Catches subprocess.TimeoutExpired, OSError, and anything else
        # a broken/misbehaving `claude` binary could raise.
        return False
    return proc.returncode == 0


class ClaudeCliCheckWorker(QThread):
    """Runs `check_claude_cli_usable()` off the main thread."""

    finished_check = Signal(bool)  # emitted exactly once when done

    def __init__(self, timeout_seconds: float = 5.0, parent=None) -> None:
        super().__init__(parent)
        self._timeout_seconds = timeout_seconds

    def run(self) -> None:
        usable = check_claude_cli_usable(self._timeout_seconds)
        self.finished_check.emit(usable)


def apply_anthropic_api_fallback(api_key: str) -> None:
    """Switch the process to the `anthropic_api` vision backend.

    Sets `os.environ["ANTHROPIC_API_KEY"] = api_key` and
    `os.environ["VISION_BACKEND"] = "anthropic_api"`. Caller must call
    this BEFORE `build_deps_or_error()` when the claude CLI check came
    back False.
    """
    os.environ["ANTHROPIC_API_KEY"] = api_key
    os.environ["VISION_BACKEND"] = "anthropic_api"


def build_deps_or_error() -> tuple[PipelineDeps | None, str | None]:
    """Wrap `build_default_pipeline_deps()`, never letting it raise.

    Returns `(deps, None)` on success, `(None, human_readable_message)`
    if construction raises (e.g. missing `TMDB_API_KEY`).
    """
    try:
        deps = build_default_pipeline_deps()
    except Exception as exc:
        return None, str(exc)
    return deps, None


class PipelineRunner(QThread):
    """Runs `reel2movie.pipeline.waterfall.run_pipeline_streaming(url, deps)`
    off the main thread, trickling individual results to the GUI as they
    resolve while still honoring the original one-shot `succeeded` contract
    at the end.

    `run_pipeline_streaming` yields raw `Recommendation`s one at a time, in
    TMDB-resolution completion order -- not deduped, not sorted, not input
    order. This class emits each one immediately via `recommendation_ready`
    (for the "trickle in" UX), while *also* accumulating every yielded
    `Recommendation` into a list. Once the stream is exhausted, that list is
    run through `dedupe_recommendations` (the same function `run_pipeline()`
    itself uses) and wrapped in a `PipelineResult`, which is emitted via the existing
    `succeeded` signal -- so every other piece of code that already listens
    for `succeeded` (error/success handling, the final full re-render) needs
    no changes at all.
    """

    succeeded = Signal(object)  # emits the final, deduped PipelineResult instance
    failed = Signal(str)  # emits str(exception) message
    recommendation_ready = Signal(object)  # emits each raw Recommendation as it streams in

    def __init__(self, url: str, deps: PipelineDeps, parent=None) -> None:
        super().__init__(parent)
        self._url = url
        self._deps = deps

    def run(self) -> None:
        recommendations = []
        try:
            for recommendation in run_pipeline_streaming(self._url, self._deps):
                recommendations.append(recommendation)
                self.recommendation_ready.emit(recommendation)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        result = PipelineResult(
            reel_url=self._url, recommendations=dedupe_recommendations(recommendations)
        )
        self.succeeded.emit(result)
