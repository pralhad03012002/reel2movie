"""Shared `claude` CLI subprocess-running plumbing.

Internal module (leading underscore, not part of the public package
surface): used only by `visual/vision_llm_detector.py`'s
`ClaudeCodeVisionChatClient.chat()` and
`text_extraction/claude_code_extractor.py`'s `ClaudeCodeTextChatClient.chat()`,
which previously duplicated this subprocess/JSON-parsing pipeline almost
line-for-line. Both callers build their own CLI `args` (differing flags:
`--tools Read` + an image-read prompt prefix for vision, `--tools ""` for
text) and hand them to `run_claude_cli()` here.
"""

from __future__ import annotations

import json
import subprocess
import threading

from reel2movie._subprocess_util import SubprocessCancelled, run_cancelable


class ClaudeCliError(RuntimeError):
    """Raised when the `claude` CLI subprocess fails to produce a usable reply.

    Covers: the subprocess timing out, the `claude` binary being missing,
    not on PATH, or otherwise not runnable (any OSError from subprocess.run
    itself, e.g. FileNotFoundError/PermissionError), a non-zero exit code,
    stdout that isn't valid JSON, a parsed reply with is_error: true, and a
    parsed reply with a non-empty permission_denials list (a tool call was
    blocked, so the model's reply cannot be trusted as a real answer).
    """


class ClaudeCliCancelled(ClaudeCliError, SubprocessCancelled):
    """Raised when `cancel_event` fires while the `claude` CLI call is in flight.

    A distinct subclass (not just a `ClaudeCliError` message string) so a
    caller -- e.g. a future parallel-race orchestrator -- can tell "this
    job lost the race, nothing actually went wrong" apart from a real
    failure (timeout, bad exit code, malformed reply, etc.), which all
    still raise the plain `ClaudeCliError`.

    Also inherits from `SubprocessCancelled` (multiple inheritance, not
    just `ClaudeCliError`): `ClaudeCliCancelled` and `SubprocessCancelled`
    used to share no common ancestor beyond `Exception` itself, which
    forced every caller that wants to catch "this was cancelled" (e.g.
    `pipeline/waterfall.py`'s `_CANCELLED_EXCEPTIONS`) to hardcode a
    two-exception tuple of both concrete types rather than catching one
    shared type. Any future cancellable component built on
    `run_cancelable`/`SubprocessCancelled` is automatically covered by a
    plain `except SubprocessCancelled` now, without that tuple needing to
    grow. Safe as multiple inheritance here: neither `ClaudeCliError`
    (a `RuntimeError` subclass) nor `SubprocessCancelled` (a plain
    `Exception` subclass) defines a custom `__init__`, so the MRO
    (`ClaudeCliCancelled` -> `ClaudeCliError` -> `RuntimeError` ->
    `SubprocessCancelled` -> `Exception` -> `BaseException`) resolves
    cleanly with no diamond ambiguity.
    """


def run_claude_cli(
    args: list[str],
    *,
    claude_binary: str,
    timeout_seconds: float,
    context: str,
    cancel_event: "threading.Event | None" = None,
) -> str:
    """Run `claude_binary` with `args`, parse its `--output-format json`
    reply, and return the `result` text.

    `context` is used only to make error messages identify what was being
    processed (e.g. an image path, or a text-extraction context string) --
    it has no effect on parsing or control flow.

    `cancel_event`, if given, lets a caller abort the in-flight subprocess
    early (real OS-level termination, not just abandoning the wait) -- see
    `reel2movie._subprocess_util.run_cancelable`. Defaults to `None`,
    which disables cancellation entirely and behaves exactly as before.

    Raises:
        ClaudeCliCancelled: if `cancel_event` fires before the subprocess
            finishes (a `ClaudeCliError` subclass -- see its docstring).
        ClaudeCliError: on subprocess timeout, the `claude` binary being
            missing/not on PATH/not executable (any OSError from
            `subprocess.run` itself), a non-zero exit code, stdout that
            isn't valid JSON, a parsed reply with `is_error: true`, or a
            parsed reply with a non-empty `permission_denials` list.
    """
    try:
        result = run_cancelable(
            args,
            timeout_seconds=timeout_seconds,
            cancel_event=cancel_event,
        )
    except SubprocessCancelled as exc:
        raise ClaudeCliCancelled(
            f"`{claude_binary}` CLI call was cancelled {context}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ClaudeCliError(
            f"`{claude_binary}` CLI timed out after {timeout_seconds}s {context}"
        ) from exc
    except OSError as exc:
        raise ClaudeCliError(
            f"could not run the 'claude' CLI (binary: {claude_binary!r}) -- "
            f"is it installed and on PATH? ({exc})"
        ) from exc

    if result.returncode != 0:
        raise ClaudeCliError(
            f"`{claude_binary}` CLI exited {result.returncode} {context}: "
            f"{result.stderr.strip()}"
        )

    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ClaudeCliError(
            f"`{claude_binary}` CLI returned non-JSON stdout {context}: "
            f"{result.stdout!r}"
        ) from exc

    if parsed.get("is_error"):
        raise ClaudeCliError(
            f"`{claude_binary}` CLI reported is_error=true {context}: "
            f"{parsed.get('result')!r}"
        )

    if parsed.get("permission_denials"):
        raise ClaudeCliError(
            f"`{claude_binary}` CLI's tool call was denied {context} "
            f"(permission_denials={parsed['permission_denials']!r}); "
            f"the model's reply cannot be trusted"
        )

    return parsed["result"]
