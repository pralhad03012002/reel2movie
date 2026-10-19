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


class ClaudeCliError(RuntimeError):
    """Raised when the `claude` CLI subprocess fails to produce a usable reply.

    Covers: the subprocess timing out, the `claude` binary being missing,
    not on PATH, or otherwise not runnable (any OSError from subprocess.run
    itself, e.g. FileNotFoundError/PermissionError), a non-zero exit code,
    stdout that isn't valid JSON, a parsed reply with is_error: true, and a
    parsed reply with a non-empty permission_denials list (a tool call was
    blocked, so the model's reply cannot be trusted as a real answer).
    """


def run_claude_cli(
    args: list[str], *, claude_binary: str, timeout_seconds: float, context: str
) -> str:
    """Run `claude_binary` with `args`, parse its `--output-format json`
    reply, and return the `result` text.

    `context` is used only to make error messages identify what was being
    processed (e.g. an image path, or a text-extraction context string) --
    it has no effect on parsing or control flow.

    Raises:
        ClaudeCliError: on subprocess timeout, the `claude` binary being
            missing/not on PATH/not executable (any OSError from
            `subprocess.run` itself), a non-zero exit code, stdout that
            isn't valid JSON, a parsed reply with `is_error: true`, or a
            parsed reply with a non-empty `permission_denials` list.
    """
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
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
