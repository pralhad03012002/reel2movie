"""Tests for `visual/vision_llm_detector.py`.

No live API calls anywhere: `VisionLLMPosterDetector` is tested against a
`FakeVisionChatClient` test double, and `AnthropicVisionChatClient` is
tested with the `anthropic` SDK's client mocked out — never a real
`anthropic.Anthropic()` instance, never a real key, never the network.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from reel2movie.core.models import Candidate, FrameSample, SourceTag
from reel2movie.tmdb.resolver import _extract_year_hint
from reel2movie.visual.vision_llm_detector import (
    AnthropicVisionChatClient,
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
