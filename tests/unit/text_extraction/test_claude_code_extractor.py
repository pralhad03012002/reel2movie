"""Tests for `text_extraction/claude_code_extractor.py`.

No live `claude` CLI calls anywhere: `ClaudeCodeCandidateExtractor` is
tested against a `FakeTextChatClient` test double, and
`ClaudeCodeTextChatClient` is tested with `subprocess.run` mocked out --
same pattern as `tests/unit/visual/test_vision_llm_detector.py`'s
`TestClaudeCodeVisionChatClient`, text-only variant.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from reel2movie.core.models import Candidate, SourceTag
from reel2movie.text_extraction.claude_code_extractor import (
    ClaudeCodeCandidateExtractor,
    ClaudeCodeTextChatClient,
    ClaudeCodeTextError,
)
from reel2movie.text_extraction.regex_extractor import (
    HIGH_CONFIDENCE,
    MEDIUM_CONFIDENCE,
)
from reel2movie.tmdb.resolver import _extract_year_hint


class FakeTextChatClient:
    """A `TextChatClient` test double returning a canned string."""

    def __init__(self, response_text: str) -> None:
        self.response_text = response_text
        self.last_prompt: str | None = None
        self.call_count = 0

    def chat(self, prompt: str) -> str:
        self.call_count += 1
        self.last_prompt = prompt
        return self.response_text


# ---------------------------------------------------------------------------
# ClaudeCodeTextChatClient: mocks subprocess.run entirely. No real `claude`
# binary is ever invoked. Canned stdout shape mirrors the same real
# captured response shape `vision_llm_detector.py`'s client is grounded in.
# ---------------------------------------------------------------------------


def _canned_cli_json(
    *,
    result_text: str = "[]",
    is_error: bool = False,
    permission_denials: list | None = None,
    subtype: str = "success",
) -> str:
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


class TestClaudeCodeTextChatClient:
    def test_chat_returns_result_field_on_success(self) -> None:
        canned_stdout = _canned_cli_json(result_text='[{"title": "Dhobi Ghat"}]')

        with patch(
            "reel2movie._claude_cli.run_cancelable"
        ) as mock_run_cancelable:
            mock_run_cancelable.return_value = subprocess.CompletedProcess(
                args=["claude"], returncode=0, stdout=canned_stdout, stderr=""
            )

            client = ClaudeCodeTextChatClient()
            result = client.chat("extract movie titles from this text")

        assert result == '[{"title": "Dhobi Ghat"}]'

        mock_run_cancelable.assert_called_once()
        (cmd,), kwargs = mock_run_cancelable.call_args
        assert cmd[0] == "claude"
        assert "-p" in cmd
        assert "--output-format" in cmd and "json" in cmd
        assert "--tools" in cmd
        tools_idx = cmd.index("--tools")
        assert cmd[tools_idx + 1] == ""
        assert "--permission-mode" in cmd and "bypassPermissions" in cmd
        assert "--no-session-persistence" in cmd
        assert cmd[-1] == "extract movie titles from this text"
        assert kwargs["timeout_seconds"] == 60.0

    def test_chat_raises_on_is_error_true(self) -> None:
        canned_stdout = _canned_cli_json(
            is_error=True, subtype="error", result_text="Something went wrong"
        )

        with patch(
            "reel2movie._claude_cli.run_cancelable"
        ) as mock_run_cancelable:
            mock_run_cancelable.return_value = subprocess.CompletedProcess(
                args=["claude"], returncode=0, stdout=canned_stdout, stderr=""
            )

            client = ClaudeCodeTextChatClient()
            with pytest.raises(ClaudeCodeTextError, match="is_error"):
                client.chat("prompt")

    def test_chat_raises_on_nonempty_permission_denials_even_if_result_looks_fine(
        self,
    ) -> None:
        canned_stdout = _canned_cli_json(
            is_error=False,
            result_text="[]",
            permission_denials=[{"tool_name": "Read", "reason": "denied"}],
        )

        with patch(
            "reel2movie._claude_cli.run_cancelable"
        ) as mock_run_cancelable:
            mock_run_cancelable.return_value = subprocess.CompletedProcess(
                args=["claude"], returncode=0, stdout=canned_stdout, stderr=""
            )

            client = ClaudeCodeTextChatClient()
            with pytest.raises(ClaudeCodeTextError, match="permission_denials"):
                client.chat("prompt")

    def test_chat_raises_on_non_json_stdout(self) -> None:
        with patch(
            "reel2movie._claude_cli.run_cancelable"
        ) as mock_run_cancelable:
            mock_run_cancelable.return_value = subprocess.CompletedProcess(
                args=["claude"],
                returncode=0,
                stdout="not valid json at all",
                stderr="",
            )

            client = ClaudeCodeTextChatClient()
            with pytest.raises(ClaudeCodeTextError, match="non-JSON"):
                client.chat("prompt")

    def test_chat_raises_on_nonzero_exit_code(self) -> None:
        with patch(
            "reel2movie._claude_cli.run_cancelable"
        ) as mock_run_cancelable:
            mock_run_cancelable.return_value = subprocess.CompletedProcess(
                args=["claude"],
                returncode=1,
                stdout="",
                stderr="claude: command failed: not logged in",
            )

            client = ClaudeCodeTextChatClient()
            with pytest.raises(ClaudeCodeTextError, match="not logged in"):
                client.chat("prompt")

    def test_chat_raises_clear_error_on_timeout_not_raw_exception(self) -> None:
        with patch(
            "reel2movie._claude_cli.run_cancelable"
        ) as mock_run_cancelable:
            mock_run_cancelable.side_effect = subprocess.TimeoutExpired(
                cmd=["claude"], timeout=60.0
            )

            client = ClaudeCodeTextChatClient()
            with pytest.raises(ClaudeCodeTextError, match="timed out"):
                client.chat("prompt")

    def test_chat_raises_clear_error_when_binary_missing_not_raw_exception(
        self,
    ) -> None:
        with patch(
            "reel2movie._claude_cli.run_cancelable"
        ) as mock_run_cancelable:
            mock_run_cancelable.side_effect = FileNotFoundError(
                "[Errno 2] No such file or directory: 'claude'"
            )

            client = ClaudeCodeTextChatClient()
            with pytest.raises(ClaudeCodeTextError, match="claude"):
                client.chat("prompt")

    def test_custom_binary_and_timeout_are_used(self) -> None:
        canned_stdout = _canned_cli_json(result_text="ok")

        with patch(
            "reel2movie._claude_cli.run_cancelable"
        ) as mock_run_cancelable:
            mock_run_cancelable.return_value = subprocess.CompletedProcess(
                args=["my-claude"], returncode=0, stdout=canned_stdout, stderr=""
            )

            client = ClaudeCodeTextChatClient(
                claude_binary="my-claude", timeout_seconds=12.5
            )
            result = client.chat("prompt")

        assert result == "ok"
        (cmd,), kwargs = mock_run_cancelable.call_args
        assert cmd[0] == "my-claude"
        assert kwargs["timeout_seconds"] == 12.5


# ---------------------------------------------------------------------------
# ClaudeCodeCandidateExtractor: a fake TextChatClient returning canned JSON.
# ---------------------------------------------------------------------------


class TestClaudeCodeCandidateExtractorSingleMovieWithYear:
    def test_single_movie_with_year_is_high_confidence(self) -> None:
        fake = FakeTextChatClient(
            json.dumps([{"title": "Dhobi Ghat", "year": 2010, "confidence": "high"}])
        )
        extractor = ClaudeCodeCandidateExtractor(fake)

        result = extractor.extract("some prose caption", SourceTag.CAPTION)

        assert result == [
            Candidate(
                raw_text="Dhobi Ghat (2010)",
                source=SourceTag.CAPTION,
                confidence=HIGH_CONFIDENCE,
            )
        ]

    def test_raw_text_year_round_trips_through_resolver(self) -> None:
        fake = FakeTextChatClient(
            json.dumps([{"title": "Dhobi Ghat", "year": 2010, "confidence": "high"}])
        )
        extractor = ClaudeCodeCandidateExtractor(fake)

        [candidate] = extractor.extract("some prose caption", SourceTag.CAPTION)

        assert _extract_year_hint(candidate.raw_text) == 2010


class TestClaudeCodeCandidateExtractorSingleMovieWithoutYear:
    def test_single_movie_without_year_is_medium_confidence(self) -> None:
        fake = FakeTextChatClient(
            json.dumps([{"title": "Interstellar", "confidence": "medium"}])
        )
        extractor = ClaudeCodeCandidateExtractor(fake)

        result = extractor.extract("some prose caption", SourceTag.CAPTION)

        assert result == [
            Candidate(
                raw_text="Interstellar",
                source=SourceTag.CAPTION,
                confidence=MEDIUM_CONFIDENCE,
            )
        ]

    def test_raw_text_without_year_round_trips_through_resolver_as_no_hint(
        self,
    ) -> None:
        fake = FakeTextChatClient(
            json.dumps([{"title": "Interstellar", "confidence": "medium"}])
        )
        extractor = ClaudeCodeCandidateExtractor(fake)

        [candidate] = extractor.extract("some prose caption", SourceTag.CAPTION)

        assert _extract_year_hint(candidate.raw_text) is None


class TestClaudeCodeCandidateExtractorMultiMovie:
    def test_multi_movie_response(self) -> None:
        fake = FakeTextChatClient(
            json.dumps(
                [
                    {"title": "Dhobi Ghat", "year": 2010, "confidence": "high"},
                    {"title": "Interstellar", "confidence": "medium"},
                ]
            )
        )
        extractor = ClaudeCodeCandidateExtractor(fake)

        result = extractor.extract("some prose caption", SourceTag.CAPTION)

        assert result == [
            Candidate(
                raw_text="Dhobi Ghat (2010)",
                source=SourceTag.CAPTION,
                confidence=HIGH_CONFIDENCE,
            ),
            Candidate(
                raw_text="Interstellar",
                source=SourceTag.CAPTION,
                confidence=MEDIUM_CONFIDENCE,
            ),
        ]


class TestClaudeCodeCandidateExtractorNothingFound:
    def test_explicit_empty_array_returns_empty_list(self) -> None:
        fake = FakeTextChatClient("[]")
        extractor = ClaudeCodeCandidateExtractor(fake)

        assert extractor.extract("no movie here", SourceTag.CAPTION) == []


class TestClaudeCodeCandidateExtractorMalformedResponse:
    def test_non_json_response_returns_empty_list_without_raising(self) -> None:
        fake = FakeTextChatClient("Sorry, I can't help with that request.")
        extractor = ClaudeCodeCandidateExtractor(fake)

        assert extractor.extract("some text", SourceTag.CAPTION) == []

    def test_json_object_instead_of_array_returns_empty_list(self) -> None:
        fake = FakeTextChatClient(
            json.dumps({"title": "Dhobi Ghat", "year": 2010, "confidence": "high"})
        )
        extractor = ClaudeCodeCandidateExtractor(fake)

        assert extractor.extract("some text", SourceTag.CAPTION) == []

    def test_item_missing_title_within_otherwise_good_list_is_skipped(self) -> None:
        fake = FakeTextChatClient(
            json.dumps(
                [
                    {"confidence": "high"},
                    {"title": "Interstellar", "confidence": "medium"},
                ]
            )
        )
        extractor = ClaudeCodeCandidateExtractor(fake)

        result = extractor.extract("some text", SourceTag.CAPTION)

        assert result == [
            Candidate(
                raw_text="Interstellar",
                source=SourceTag.CAPTION,
                confidence=MEDIUM_CONFIDENCE,
            )
        ]

    def test_unrecognized_confidence_label_falls_back_to_medium_default(
        self,
    ) -> None:
        fake = FakeTextChatClient(
            json.dumps([{"title": "Interstellar", "confidence": "very sure"}])
        )
        extractor = ClaudeCodeCandidateExtractor(fake)

        [candidate] = extractor.extract("some text", SourceTag.CAPTION)

        assert candidate.confidence == MEDIUM_CONFIDENCE


class TestClaudeCodeCandidateExtractorSourceTag:
    def test_source_is_echoed_correctly_for_both_values(self) -> None:
        fake = FakeTextChatClient(
            json.dumps([{"title": "Interstellar", "confidence": "high"}])
        )
        extractor = ClaudeCodeCandidateExtractor(fake)

        [caption_candidate] = extractor.extract("some text", SourceTag.CAPTION)
        [comment_candidate] = extractor.extract(
            "some text", SourceTag.CREATOR_COMMENT
        )

        assert caption_candidate.source is SourceTag.CAPTION
        assert comment_candidate.source is SourceTag.CREATOR_COMMENT


class TestClaudeCodeCandidateExtractorEmptyTextShortCircuit:
    def test_empty_string_never_calls_chat_client(self) -> None:
        fake = FakeTextChatClient("[]")
        extractor = ClaudeCodeCandidateExtractor(fake)

        result = extractor.extract("", SourceTag.CAPTION)

        assert result == []
        assert fake.call_count == 0

    def test_whitespace_only_text_never_calls_chat_client(self) -> None:
        fake = FakeTextChatClient("[]")
        extractor = ClaudeCodeCandidateExtractor(fake)

        result = extractor.extract("   \n\t  ", SourceTag.CAPTION)

        assert result == []
        assert fake.call_count == 0
