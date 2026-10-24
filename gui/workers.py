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

from reel2movie.pipeline.deps import PipelineDeps, build_default_pipeline_deps
from reel2movie.pipeline.waterfall import run_pipeline


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
    """Runs `reel2movie.pipeline.waterfall.run_pipeline(url, deps)` off
    the main thread."""

    succeeded = Signal(object)  # emits the PipelineResult instance
    failed = Signal(str)  # emits str(exception) message

    def __init__(self, url: str, deps: PipelineDeps, parent=None) -> None:
        super().__init__(parent)
        self._url = url
        self._deps = deps

    def run(self) -> None:
        try:
            result = run_pipeline(self._url, self._deps)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.succeeded.emit(result)
