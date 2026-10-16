"""Vision-LLM based `PosterDetector`: asks Claude whether a sampled video
frame shows a movie poster, title card, or clearly identifiable scene.

This is the visual-fallback path (per `flow.md`, reached only once caption
and creator-comment extraction both fail to yield a confident candidate).

Design note (see vast-wobbling-owl.md "Visual detection approach"): the
actual provider call is wrapped behind a tiny local `VisionChatClient`
Protocol (`chat(image_path, prompt) -> str`) defined in *this* module, not
in `core/protocols.py` — that file holds pipeline-level seams shared across
modules, whereas this Protocol is an implementation detail specific to how
`VisionLLMPosterDetector` talks to whatever chat-capable vision backend it's
given. This keeps the detector's own logic (prompt construction, JSON
parsing, confidence mapping) fully decoupled from HOW the chat call happens:
`VisionLLMPosterDetector` never imports `anthropic` directly, and
`AnthropicVisionChatClient` never imports `core.models`/`core.protocols`.

Per the project's separation-of-concerns rule (see config.py), neither class
here calls `config.get_anthropic_key()` itself — the API key/client is
always a constructor parameter, supplied by the caller (a later
`pipeline/deps.py`).
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Protocol, runtime_checkable

import anthropic

from reel2movie.core.models import Candidate, FrameSample, SourceTag

logger = logging.getLogger(__name__)


@runtime_checkable
class VisionChatClient(Protocol):
    """A minimal "send one image + prompt, get text back" chat seam.

    Deliberately narrower than the full `anthropic` SDK surface, so tests
    can fake it with a trivial object and swap in a different vision
    provider later without touching `VisionLLMPosterDetector` at all.
    """

    def chat(self, image_path: Path, prompt: str) -> str: ...


# Maps a frame file's extension to the Anthropic API's expected image
# media_type. frame_sampler.py's output is always JPEG today, but this is
# detected from the actual file extension rather than hardcoded, so this
# client keeps working if a future caller hands it a PNG frame from
# somewhere else. Anything outside this small set raises clearly in
# `AnthropicVisionChatClient.chat` rather than silently mislabeling the
# image's media type to the API.
_EXTENSION_TO_MEDIA_TYPE = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}


class AnthropicVisionChatClient:
    """`VisionChatClient` backed by a real `anthropic.Anthropic` client."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-5-5") -> None:
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def chat(self, image_path: Path, prompt: str) -> str:
        """Send one image + a text prompt to Claude, return the text reply.

        Raises:
            ValueError: if `image_path`'s extension isn't a recognized
                image type (see `_EXTENSION_TO_MEDIA_TYPE`).
        """
        media_type = _EXTENSION_TO_MEDIA_TYPE.get(image_path.suffix.lower())
        if media_type is None:
            raise ValueError(
                f"Unsupported image extension {image_path.suffix!r} for "
                f"{image_path} (expected one of: "
                f"{sorted(_EXTENSION_TO_MEDIA_TYPE)})"
            )

        image_data = base64.standard_b64encode(image_path.read_bytes()).decode(
            "utf-8"
        )

        response = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            # Simple yes/no-shaped classification call, not an open-ended
            # task — low effort keeps cost/latency down without hurting
            # quality here.
            output_config={"effort": "low"},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_data,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )

        return "".join(
            block.text for block in response.content if block.type == "text"
        )


# Confidence labels the prompt asks the model to use, mapped to this
# extraction layer's numeric confidence. These values feed directly into
# the pipeline's waterfall confidence gate (see core/models.py's
# `Candidate.confidence` docstring) — picked high/medium/low enough that a
# genuine visual hit clears the gate without inflating a weak guess:
#   - high (0.8): a clearly readable poster/title card, unambiguous.
#   - medium (0.5): a recognizable scene or partially-legible title card.
#   - low (0.3): a tentative guess the model itself flagged as uncertain.
CONFIDENCE_MAP: dict[str, float] = {"high": 0.8, "medium": 0.5, "low": 0.3}

# Fallback used when the model's own confidence label is missing or isn't
# one of the three expected values — treated as a middling guess rather
# than silently dropped or treated as maximally confident.
_DEFAULT_CONFIDENCE = CONFIDENCE_MAP["medium"]

_PROMPT = """You are analyzing a single still frame extracted from a video.

Look at the image and determine: is a movie poster, a movie title card, or
a clearly identifiable movie scene visible in this image?

- If you can identify one or more movies, name each movie's title (and the
  release year, if you can tell it).
- If nothing identifiable is visible, say so by returning an empty list.

Respond with ONLY a JSON array, and nothing else: no prose before or after
it, no markdown code fences. Each element must be an object with keys
"title" (string, required), "year" (integer, optional — omit or use null if
unknown), and "confidence" (one of the strings "high", "medium", or "low",
required).

Example of a response with one movie identified:
[{"title": "Inception", "year": 2010, "confidence": "high"}]

Example of a response with multiple movies identified:
[{"title": "Inception", "year": 2010, "confidence": "high"}, {"title": "Interstellar", "confidence": "medium"}]

Example of a response with nothing identifiable:
[]
"""


class VisionLLMPosterDetector:
    """`PosterDetector` that asks a vision-chat-capable LLM about a frame.

    Structurally satisfies `core.protocols.PosterDetector`
    (`detect(frame) -> list[Candidate]`) without inheriting from it.
    """

    def __init__(self, chat_client: VisionChatClient) -> None:
        self._chat_client = chat_client

    def detect(self, frame: FrameSample) -> list[Candidate]:
        """Ask the chat client about `frame`, parse the reply into Candidates.

        Never raises on a malformed/non-JSON/unexpected-shape reply from the
        model — a single bad frame detection shouldn't crash the whole
        pipeline, so any parsing failure is logged and `[]` is returned
        instead.
        """
        raw_response = self._chat_client.chat(frame.path, _PROMPT)

        try:
            parsed = json.loads(raw_response.strip())
        except (json.JSONDecodeError, AttributeError):
            logger.warning(
                "vision LLM returned non-JSON response for frame %s: %r",
                frame.path,
                raw_response,
            )
            return []

        if not isinstance(parsed, list):
            logger.warning(
                "vision LLM JSON response for frame %s was not a list: %r",
                frame.path,
                parsed,
            )
            return []

        candidates: list[Candidate] = []
        for item in parsed:
            if not isinstance(item, dict):
                logger.warning(
                    "vision LLM response for frame %s had a non-object list "
                    "item, skipping: %r",
                    frame.path,
                    item,
                )
                continue

            title = item.get("title")
            if not isinstance(title, str) or not title.strip():
                logger.warning(
                    "vision LLM response for frame %s had an item with no "
                    "usable title, skipping: %r",
                    frame.path,
                    item,
                )
                continue
            title = title.strip()

            year = item.get("year")
            if isinstance(year, bool):
                year = None  # bool is a subclass of int; not a real year
            elif isinstance(year, str) and year.strip().isdigit():
                year = int(year.strip())
            elif not isinstance(year, int):
                year = None
            raw_text = f"{title} ({year})" if year is not None else title

            confidence_label = item.get("confidence")
            if isinstance(confidence_label, str):
                confidence_label = confidence_label.strip().lower()
            confidence = CONFIDENCE_MAP.get(confidence_label, _DEFAULT_CONFIDENCE)

            candidates.append(
                Candidate(
                    raw_text=raw_text,
                    source=SourceTag.FRAME_VISUAL,
                    confidence=confidence,
                )
            )

        return candidates
