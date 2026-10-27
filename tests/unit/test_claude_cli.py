"""Tests for the shared `reel2movie._claude_cli` subprocess-running helper.

Covers, once against the shared helper directly, the same error-case
coverage previously duplicated per-caller in
`tests/unit/visual/test_vision_llm_detector.py`'s
`TestClaudeCodeVisionChatClient` and
`tests/unit/text_extraction/test_claude_code_extractor.py`'s
`TestClaudeCodeTextChatClient`: timeout, missing binary, non-zero exit,
non-JSON stdout, is_error, and permission_denials. No real `claude` binary
is ever invoked -- `run_claude_cli` now delegates its actual subprocess
work to `reel2movie._subprocess_util.run_cancelable` (see that module's
own tests for the real-subprocess/cancellation coverage), so these tests
mock `run_cancelable` itself rather than `subprocess.run`.
"""

from __future__ import annotations

import json
import subprocess
import threading
from unittest.mock import patch

import pytest

from reel2movie._claude_cli import ClaudeCliCancelled, ClaudeCliError, run_claude_cli
from reel2movie._subprocess_util import SubprocessCancelled


def _canned_cli_json(
    *,
    result_text: str = "ok",
    is_error: bool = False,
    permission_denials: list | None = None,
    subtype: str = "success",
) -> str:
    """Build canned `claude -p --output-format json` stdout for a test.

    Same field set as the real captured response both callers' own tests
    are grounded in (see `test_vision_llm_detector.py`'s module comment).
    """
    return json.dumps(
        {
            "duration_api_ms": 4057,
            "stop_reason": "end_turn",
            "session_id": "aa89cba6-ce5b-4089-978a-a77f37a9e9dc",
            "total_cost_usd": 0.0609246,
            "usage": {},
            "modelUsage": {"claude-sonnet-5": {"costBasis": "list"}},
            "permission_denials": permission_denials or [],
            "terminal_reason": "completed",
            "is_error": is_error,
            "num_turns": 2,
            "subtype": subtype,
            "api_error_status": None,
            "result": result_text,
            "type": "result",
            "duration_ms": 4195,
            "uuid": "6784baa3-fa8b-48b5-9871-2e34909c7397",
        }
    )


class TestRunClaudeCli:
    def test_returns_result_field_on_success(self) -> None:
        canned_stdout = _canned_cli_json(result_text="This is the answer.")

        with patch("reel2movie._claude_cli.run_cancelable") as mock_run_cancelable:
            mock_run_cancelable.return_value = subprocess.CompletedProcess(
                args=["claude"], returncode=0, stdout=canned_stdout, stderr=""
            )

            result = run_claude_cli(
                ["claude", "-p", "--output-format", "json", "prompt"],
                claude_binary="claude",
                timeout_seconds=60.0,
                context="doing a thing",
            )

        assert result == "This is the answer."
        mock_run_cancelable.assert_called_once()
        (cmd,), kwargs = mock_run_cancelable.call_args
        assert cmd == ["claude", "-p", "--output-format", "json", "prompt"]
        assert kwargs["timeout_seconds"] == 60.0
        assert kwargs["cancel_event"] is None

    def test_raises_on_is_error_true(self) -> None:
        canned_stdout = _canned_cli_json(
            is_error=True, subtype="error", result_text="Something went wrong"
        )

        with patch("reel2movie._claude_cli.run_cancelable") as mock_run_cancelable:
            mock_run_cancelable.return_value = subprocess.CompletedProcess(
                args=["claude"], returncode=0, stdout=canned_stdout, stderr=""
            )

            with pytest.raises(ClaudeCliError, match="is_error"):
                run_claude_cli(
                    ["claude", "prompt"],
                    claude_binary="claude",
                    timeout_seconds=60.0,
                    context="doing a thing",
                )

    def test_raises_on_nonempty_permission_denials_even_if_result_looks_fine(
        self,
    ) -> None:
        """Subtlest case: is_error is False and `result` reads as a normal,
        plausible answer, but a non-empty `permission_denials` means a tool
        call was actually blocked -- this must still raise, not be trusted
        as a real answer.
        """
        canned_stdout = _canned_cli_json(
            is_error=False,
            result_text="This looks like a perfectly normal answer.",
            permission_denials=[{"tool_name": "Read", "reason": "denied"}],
        )

        with patch("reel2movie._claude_cli.run_cancelable") as mock_run_cancelable:
            mock_run_cancelable.return_value = subprocess.CompletedProcess(
                args=["claude"], returncode=0, stdout=canned_stdout, stderr=""
            )

            with pytest.raises(ClaudeCliError, match="permission_denials"):
                run_claude_cli(
                    ["claude", "prompt"],
                    claude_binary="claude",
                    timeout_seconds=60.0,
                    context="doing a thing",
                )

    def test_raises_on_non_json_stdout(self) -> None:
        with patch("reel2movie._claude_cli.run_cancelable") as mock_run_cancelable:
            mock_run_cancelable.return_value = subprocess.CompletedProcess(
                args=["claude"],
                returncode=0,
                stdout="not valid json at all",
                stderr="",
            )

            with pytest.raises(ClaudeCliError, match="non-JSON"):
                run_claude_cli(
                    ["claude", "prompt"],
                    claude_binary="claude",
                    timeout_seconds=60.0,
                    context="doing a thing",
                )

    def test_raises_on_nonzero_exit_code(self) -> None:
        with patch("reel2movie._claude_cli.run_cancelable") as mock_run_cancelable:
            mock_run_cancelable.return_value = subprocess.CompletedProcess(
                args=["claude"],
                returncode=1,
                stdout="",
                stderr="claude: command failed: not logged in",
            )

            with pytest.raises(ClaudeCliError, match="not logged in"):
                run_claude_cli(
                    ["claude", "prompt"],
                    claude_binary="claude",
                    timeout_seconds=60.0,
                    context="doing a thing",
                )

    def test_raises_clear_error_on_timeout_not_raw_exception(self) -> None:
        with patch("reel2movie._claude_cli.run_cancelable") as mock_run_cancelable:
            mock_run_cancelable.side_effect = subprocess.TimeoutExpired(
                cmd=["claude"], timeout=60.0
            )

            with pytest.raises(ClaudeCliError, match="timed out"):
                run_claude_cli(
                    ["claude", "prompt"],
                    claude_binary="claude",
                    timeout_seconds=60.0,
                    context="doing a thing",
                )

    def test_raises_clear_error_when_binary_missing_not_raw_exception(self) -> None:
        with patch("reel2movie._claude_cli.run_cancelable") as mock_run_cancelable:
            mock_run_cancelable.side_effect = FileNotFoundError(
                "[Errno 2] No such file or directory: 'claude'"
            )

            with pytest.raises(ClaudeCliError, match="claude"):
                run_claude_cli(
                    ["claude", "prompt"],
                    claude_binary="claude",
                    timeout_seconds=60.0,
                    context="doing a thing",
                )

    def test_context_is_included_in_error_messages(self) -> None:
        with patch("reel2movie._claude_cli.run_cancelable") as mock_run_cancelable:
            mock_run_cancelable.return_value = subprocess.CompletedProcess(
                args=["claude"],
                returncode=1,
                stdout="",
                stderr="boom",
            )

            with pytest.raises(ClaudeCliError, match="analyzing /tmp/frame.jpg"):
                run_claude_cli(
                    ["claude", "prompt"],
                    claude_binary="claude",
                    timeout_seconds=60.0,
                    context="analyzing /tmp/frame.jpg",
                )

    def test_cancel_event_is_passed_through_to_run_cancelable(self) -> None:
        cancel_event = threading.Event()
        with patch("reel2movie._claude_cli.run_cancelable") as mock_run_cancelable:
            mock_run_cancelable.return_value = subprocess.CompletedProcess(
                args=["claude"], returncode=0, stdout=_canned_cli_json(), stderr=""
            )

            run_claude_cli(
                ["claude", "prompt"],
                claude_binary="claude",
                timeout_seconds=60.0,
                context="doing a thing",
                cancel_event=cancel_event,
            )

        _, kwargs = mock_run_cancelable.call_args
        assert kwargs["cancel_event"] is cancel_event

    def test_subprocess_cancelled_is_raised_as_claude_cli_cancelled(self) -> None:
        with patch("reel2movie._claude_cli.run_cancelable") as mock_run_cancelable:
            mock_run_cancelable.side_effect = SubprocessCancelled("cancelled")

            with pytest.raises(ClaudeCliCancelled):
                run_claude_cli(
                    ["claude", "prompt"],
                    claude_binary="claude",
                    timeout_seconds=60.0,
                    context="doing a thing",
                )

    def test_claude_cli_cancelled_is_a_claude_cli_error(self) -> None:
        """Callers that only catch the base `ClaudeCliError` (pre-existing
        code, unaware of cancellation) must still catch a cancellation --
        `ClaudeCliCancelled` is a subclass, not an unrelated exception."""
        assert issubclass(ClaudeCliCancelled, ClaudeCliError)
