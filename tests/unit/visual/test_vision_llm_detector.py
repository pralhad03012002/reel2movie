"""Tests for `visual/vision_llm_detector.py`.

No live API calls anywhere: `VisionLLMPosterDetector` is tested against a
`FakeVisionChatClient` test double, and `AnthropicVisionChatClient` is
tested with the `anthropic` SDK's client mocked out — never a real
`anthropic.Anthropic()` instance, never a real key, never the network.
"""

from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from reel2movie.core.models import Candidate, FrameSample, SourceTag
from reel2movie.tmdb.resolver import _extract_year_hint
from reel2movie.visual.vision_llm_detector import (
    AnthropicVisionChatClient,
    ClaudeCodeVisionChatClient,
    ClaudeCodeVisionError,
    VisionLLMPosterDetector,
)


class FakeVisionChatClient:
    """A `VisionChatClient` test double returning a canned string."""

    def __init__(self, response_text: str) -> None:
        self.response_text = response_text
        self.last_image_path: Path | None = None
        self.last_prompt: str | None = None

    def chat(self, image_path: Path, prompt: str) -> str:
        self.last_image_path = image_path
        self.last_prompt = prompt
        return self.response_text


def _frame(path: str = "/tmp/frame_000.jpg") -> FrameSample:
    return FrameSample(path=Path(path), timestamp_seconds=1.23)


class TestVisionLLMPosterDetectorSingleMovieWithYear:
    def test_single_movie_with_year(self) -> None:
        fake = FakeVisionChatClient(
            json.dumps([{"title": "Inception", "year": 2010, "confidence": "high"}])
        )
        detector = VisionLLMPosterDetector(fake)
        frame = _frame()

        result = detector.detect(frame)

        assert result == [
            Candidate(
                raw_text="Inception (2010)",
                source=SourceTag.FRAME_VISUAL,
                confidence=0.8,
            )
        ]
        # confirms the detector actually calls through the chat client with
        # this frame's path and some prompt text
        assert fake.last_image_path == frame.path
        assert isinstance(fake.last_prompt, str) and fake.last_prompt

    def test_raw_text_year_round_trips_through_resolver(self) -> None:
        fake = FakeVisionChatClient(
            json.dumps([{"title": "Inception", "year": 2010, "confidence": "high"}])
        )
        detector = VisionLLMPosterDetector(fake)

        [candidate] = detector.detect(_frame())

        assert _extract_year_hint(candidate.raw_text) == 2010


class TestVisionLLMPosterDetectorSingleMovieWithoutYear:
    def test_single_movie_without_year(self) -> None:
        fake = FakeVisionChatClient(
            json.dumps([{"title": "Interstellar", "confidence": "medium"}])
        )
        detector = VisionLLMPosterDetector(fake)

        result = detector.detect(_frame())

        assert result == [
            Candidate(
                raw_text="Interstellar",
                source=SourceTag.FRAME_VISUAL,
                confidence=0.5,
            )
        ]

    def test_raw_text_without_year_round_trips_through_resolver_as_no_hint(
        self,
    ) -> None:
        fake = FakeVisionChatClient(
            json.dumps([{"title": "Interstellar", "confidence": "medium"}])
        )
        detector = VisionLLMPosterDetector(fake)

        [candidate] = detector.detect(_frame())

        assert _extract_year_hint(candidate.raw_text) is None


class TestVisionLLMPosterDetectorMultiMovie:
    def test_multi_movie_response(self) -> None:
        fake = FakeVisionChatClient(
            json.dumps(
                [
                    {"title": "Inception", "year": 2010, "confidence": "high"},
                    {"title": "Interstellar", "year": 2014, "confidence": "low"},
                ]
            )
        )
        detector = VisionLLMPosterDetector(fake)

        result = detector.detect(_frame())

        assert result == [
            Candidate(
                raw_text="Inception (2010)",
                source=SourceTag.FRAME_VISUAL,
                confidence=0.8,
            ),
            Candidate(
                raw_text="Interstellar (2014)",
                source=SourceTag.FRAME_VISUAL,
                confidence=0.3,
            ),
        ]


class TestVisionLLMPosterDetectorNothingFound:
    def test_explicit_empty_array_returns_empty_list(self) -> None:
        fake = FakeVisionChatClient("[]")
        detector = VisionLLMPosterDetector(fake)

        assert detector.detect(_frame()) == []


class TestVisionLLMPosterDetectorMalformedResponse:
    def test_non_json_response_returns_empty_list_without_raising(self) -> None:
        fake = FakeVisionChatClient("Sorry, I can't help with that request.")
        detector = VisionLLMPosterDetector(fake)

        assert detector.detect(_frame()) == []

    def test_json_object_instead_of_array_returns_empty_list(self) -> None:
        fake = FakeVisionChatClient(
            json.dumps({"title": "Inception", "year": 2010, "confidence": "high"})
        )
        detector = VisionLLMPosterDetector(fake)

        assert detector.detect(_frame()) == []

    def test_markdown_fenced_json_is_treated_as_malformed(self) -> None:
        fake = FakeVisionChatClient(
            "```json\n"
            + json.dumps([{"title": "Inception", "confidence": "high"}])
            + "\n```"
        )
        detector = VisionLLMPosterDetector(fake)

        assert detector.detect(_frame()) == []

    def test_list_item_missing_title_is_skipped_not_fatal(self) -> None:
        fake = FakeVisionChatClient(
            json.dumps(
                [
                    {"confidence": "high"},
                    {"title": "Interstellar", "confidence": "medium"},
                ]
            )
        )
        detector = VisionLLMPosterDetector(fake)

        result = detector.detect(_frame())

        assert result == [
            Candidate(
                raw_text="Interstellar",
                source=SourceTag.FRAME_VISUAL,
                confidence=0.5,
            )
        ]

    def test_unrecognized_confidence_label_falls_back_to_default(self) -> None:
        fake = FakeVisionChatClient(
            json.dumps([{"title": "Interstellar", "confidence": "very sure"}])
        )
        detector = VisionLLMPosterDetector(fake)

        [candidate] = detector.detect(_frame())

        assert candidate.confidence == 0.5


class TestVisionLLMPosterDetectorSourceTag:
    def test_source_is_frame_visual_on_every_returned_candidate(self) -> None:
        fake = FakeVisionChatClient(
            json.dumps(
                [
                    {"title": "Inception", "year": 2010, "confidence": "high"},
                    {"title": "Interstellar", "confidence": "low"},
                ]
            )
        )
        detector = VisionLLMPosterDetector(fake)

        result = detector.detect(_frame())

        assert len(result) == 2
        assert all(c.source is SourceTag.FRAME_VISUAL for c in result)


# ---------------------------------------------------------------------------
# AnthropicVisionChatClient: mocks the anthropic SDK entirely. No real
# anthropic.Anthropic() client is ever constructed with a real key, and no
# network call is made.
# ---------------------------------------------------------------------------


class TestAnthropicVisionChatClient:
    def _fake_image_bytes(self) -> bytes:
        return b"\xff\xd8\xff\xe0fake-jpeg-bytes"

    def test_chat_reads_encodes_image_and_passes_prompt_through(
        self, tmp_path: Path
    ) -> None:
        image_path = tmp_path / "frame_000.jpg"
        image_bytes = self._fake_image_bytes()
        image_path.write_bytes(image_bytes)

        fake_response = SimpleNamespace(
            content=[SimpleNamespace(type="text", text='[{"title": "X"}]')]
        )

        with patch(
            "reel2movie.visual.vision_llm_detector.anthropic.Anthropic"
        ) as mock_anthropic_cls:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = fake_response
            mock_anthropic_cls.return_value = mock_client

            client = AnthropicVisionChatClient(api_key="fake-key")
            result = client.chat(image_path, "describe this image")

        assert result == '[{"title": "X"}]'

        mock_anthropic_cls.assert_called_once_with(api_key="fake-key")
        mock_client.messages.create.assert_called_once()
        _, kwargs = mock_client.messages.create.call_args

        assert kwargs["model"] == "claude-sonnet-5-5"
        [message] = kwargs["messages"]
        assert message["role"] == "user"
        image_block, text_block = message["content"]

        assert image_block["type"] == "image"
        assert image_block["source"]["type"] == "base64"
        assert image_block["source"]["media_type"] == "image/jpeg"
        assert image_block["source"]["data"] == base64.standard_b64encode(
            image_bytes
        ).decode("utf-8")

        assert text_block == {"type": "text", "text": "describe this image"}

    def test_chat_extracts_text_from_multiple_content_blocks(
        self, tmp_path: Path
    ) -> None:
        image_path = tmp_path / "frame_000.png"
        image_path.write_bytes(self._fake_image_bytes())

        # Simulate a response with a non-text block mixed in (e.g. a
        # thinking block) to confirm only text blocks are concatenated.
        fake_response = SimpleNamespace(
            content=[
                SimpleNamespace(type="thinking", text="(ignored)"),
                SimpleNamespace(type="text", text="[]"),
            ]
        )

        with patch(
            "reel2movie.visual.vision_llm_detector.anthropic.Anthropic"
        ) as mock_anthropic_cls:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = fake_response
            mock_anthropic_cls.return_value = mock_client

            client = AnthropicVisionChatClient(api_key="fake-key", model="custom-model")
            result = client.chat(image_path, "prompt")

        assert result == "[]"
        _, kwargs = mock_client.messages.create.call_args
        assert kwargs["model"] == "custom-model"
        image_block, _ = kwargs["messages"][0]["content"]
        assert image_block["source"]["media_type"] == "image/png"

    def test_unsupported_extension_raises_value_error(self, tmp_path: Path) -> None:
        image_path = tmp_path / "frame_000.gif"
        image_path.write_bytes(self._fake_image_bytes())

        with patch("reel2movie.visual.vision_llm_detector.anthropic.Anthropic"):
            client = AnthropicVisionChatClient(api_key="fake-key")
            with pytest.raises(ValueError, match="Unsupported image extension"):
                client.chat(image_path, "prompt")


# ---------------------------------------------------------------------------
# ClaudeCodeVisionChatClient: mocks subprocess.run entirely (same pattern as
# `tests/unit/visual/test_frame_sampler.py`'s ffmpeg-subprocess mocking). No
# real `claude` binary is ever invoked. Canned stdout shapes below mirror a
# REAL captured response from the actual `claude` CLI (see this client's
# class docstring and PROGRESS.md's "Follow-up -- Claude Code CLI vision
# backend" section for the real captured JSON this is grounded in), not a
# guessed/documentation-derived shape.
# ---------------------------------------------------------------------------


def _canned_cli_json(
    *,
    result_text: str = "A color bar test pattern.",
    is_error: bool = False,
    permission_denials: list | None = None,
    subtype: str = "success",
) -> str:
    """Build canned `claude -p --output-format json` stdout for a test.

    Field set matches the real captured response exactly (see module-level
    comment above): `duration_api_ms`, `stop_reason`, `session_id`,
    `total_cost_usd`, `usage`, `modelUsage`, `permission_denials`,
    `terminal_reason`, `is_error`, `num_turns`, `subtype`,
    `api_error_status`, `result`, `type`, `duration_ms`, `uuid`.
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


class TestClaudeCodeVisionChatClient:
    def test_chat_returns_result_field_on_success(self, tmp_path: Path) -> None:
        image_path = tmp_path / "frame_000.jpg"
        image_path.write_bytes(b"fake-jpeg-bytes")
        canned_stdout = _canned_cli_json(
            result_text="This is a classic TV color bar test pattern."
        )

        with patch(
            "reel2movie._claude_cli.subprocess.run"
        ) as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["claude"], returncode=0, stdout=canned_stdout, stderr=""
            )

            client = ClaudeCodeVisionChatClient()
            result = client.chat(image_path, "describe the colors")

        assert result == "This is a classic TV color bar test pattern."

        mock_run.assert_called_once()
        (cmd,), kwargs = mock_run.call_args
        assert cmd[0] == "claude"
        assert "-p" in cmd
        assert "--output-format" in cmd and "json" in cmd
        assert "--tools" in cmd and "Read" in cmd
        assert "--permission-mode" in cmd and "bypassPermissions" in cmd
        assert "--no-session-persistence" in cmd
        combined_prompt = cmd[-1]
        assert str(image_path) in combined_prompt
        assert "describe the colors" in combined_prompt
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        assert kwargs["timeout"] == 60.0

    def test_chat_raises_on_is_error_true(self, tmp_path: Path) -> None:
        image_path = tmp_path / "frame_000.jpg"
        image_path.write_bytes(b"fake-jpeg-bytes")
        canned_stdout = _canned_cli_json(
            is_error=True, subtype="error", result_text="Something went wrong"
        )

        with patch(
            "reel2movie._claude_cli.subprocess.run"
        ) as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["claude"], returncode=0, stdout=canned_stdout, stderr=""
            )

            client = ClaudeCodeVisionChatClient()
            with pytest.raises(ClaudeCodeVisionError, match="is_error"):
                client.chat(image_path, "prompt")

    def test_chat_raises_on_nonempty_permission_denials_even_if_result_looks_fine(
        self, tmp_path: Path
    ) -> None:
        """Subtlest case: is_error is False and `result` reads as a normal,
        plausible answer, but a non-empty `permission_denials` means the
        Read tool call was actually blocked -- the model never saw the
        image, so this must still raise, not be trusted as a real answer.
        """
        image_path = tmp_path / "frame_000.jpg"
        image_path.write_bytes(b"fake-jpeg-bytes")
        canned_stdout = _canned_cli_json(
            is_error=False,
            result_text="This appears to be a nice photo of a mountain landscape.",
            permission_denials=[{"tool_name": "Read", "reason": "denied"}],
        )

        with patch(
            "reel2movie._claude_cli.subprocess.run"
        ) as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["claude"], returncode=0, stdout=canned_stdout, stderr=""
            )

            client = ClaudeCodeVisionChatClient()
            with pytest.raises(ClaudeCodeVisionError, match="permission_denials"):
                client.chat(image_path, "prompt")

    def test_chat_raises_on_non_json_stdout(self, tmp_path: Path) -> None:
        image_path = tmp_path / "frame_000.jpg"
        image_path.write_bytes(b"fake-jpeg-bytes")

        with patch(
            "reel2movie._claude_cli.subprocess.run"
        ) as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["claude"],
                returncode=0,
                stdout="not valid json at all",
                stderr="",
            )

            client = ClaudeCodeVisionChatClient()
            with pytest.raises(ClaudeCodeVisionError, match="non-JSON"):
                client.chat(image_path, "prompt")

    def test_chat_raises_on_nonzero_exit_code(self, tmp_path: Path) -> None:
        image_path = tmp_path / "frame_000.jpg"
        image_path.write_bytes(b"fake-jpeg-bytes")

        with patch(
            "reel2movie._claude_cli.subprocess.run"
        ) as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["claude"],
                returncode=1,
                stdout="",
                stderr="claude: command failed: not logged in",
            )

            client = ClaudeCodeVisionChatClient()
            with pytest.raises(ClaudeCodeVisionError, match="not logged in"):
                client.chat(image_path, "prompt")

    def test_chat_raises_clear_error_on_timeout_not_raw_exception(
        self, tmp_path: Path
    ) -> None:
        image_path = tmp_path / "frame_000.jpg"
        image_path.write_bytes(b"fake-jpeg-bytes")

        with patch(
            "reel2movie._claude_cli.subprocess.run"
        ) as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(
                cmd=["claude"], timeout=60.0
            )

            client = ClaudeCodeVisionChatClient()
            with pytest.raises(ClaudeCodeVisionError, match="timed out"):
                client.chat(image_path, "prompt")

    def test_chat_raises_clear_error_when_binary_missing_not_raw_exception(
        self, tmp_path: Path
    ) -> None:
        image_path = tmp_path / "frame_000.jpg"
        image_path.write_bytes(b"fake-jpeg-bytes")

        with patch(
            "reel2movie._claude_cli.subprocess.run"
        ) as mock_run:
            mock_run.side_effect = FileNotFoundError(
                "[Errno 2] No such file or directory: 'claude'"
            )

            client = ClaudeCodeVisionChatClient()
            with pytest.raises(ClaudeCodeVisionError, match="claude"):
                client.chat(image_path, "prompt")

    def test_custom_binary_and_timeout_are_used(self, tmp_path: Path) -> None:
        image_path = tmp_path / "frame_000.jpg"
        image_path.write_bytes(b"fake-jpeg-bytes")
        canned_stdout = _canned_cli_json(result_text="ok")

        with patch(
            "reel2movie._claude_cli.subprocess.run"
        ) as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["my-claude"], returncode=0, stdout=canned_stdout, stderr=""
            )

            client = ClaudeCodeVisionChatClient(
                claude_binary="my-claude", timeout_seconds=12.5
            )
            result = client.chat(image_path, "prompt")

        assert result == "ok"
        (cmd,), kwargs = mock_run.call_args
        assert cmd[0] == "my-claude"
        assert kwargs["timeout"] == 12.5
