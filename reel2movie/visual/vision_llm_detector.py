"""Vision-LLM based `PosterDetector`: asks Claude whether a sampled video
frame shows a movie poster/title card, OR a creator-burned on-screen text
overlay naming a movie/show.

This is the visual-fallback path (per `flow.md`, reached only once caption
and creator-comment extraction both fail to yield a confident candidate).

Widened scope (see this subtask's `PROGRESS.md` entry): the original
version of this detector only asked about posters/title cards/identifiable
scenes. That alone misses a common "rate these movies" / "movies like X"
reel pattern where the creator types the title directly onto the video as
a caption/lower-third/listicle-style text card -- never a poster at all.
Rather than add a second model/backend/call, the SAME single Claude call
per frame (`VisionChatClient.chat`, unchanged Protocol) now asks about BOTH
things at once via `_PROMPT` below: this is additive to what the model is
asked to look for, not a new architecture, new billing path, or schema
change -- the output JSON contract
(`[{"title", "year", "confidence"}, ...]`) is identical either way.

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
from pathlib import Path
from typing import Protocol, runtime_checkable

import anthropic

from reel2movie._candidate_parsing import parse_movie_candidates
from reel2movie._claude_cli import ClaudeCliError, run_claude_cli
from reel2movie.core.models import Candidate, FrameSample, SourceTag


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


# Alias (not a subclass) of the shared `ClaudeCliError` raised by
# `run_claude_cli()` -- see `reel2movie._claude_cli` for the actual
# error-raising logic this used to duplicate. Kept under this name since
# external code/tests still import/reference it as `ClaudeCodeVisionError`.
ClaudeCodeVisionError = ClaudeCliError


class ClaudeCodeVisionChatClient:
    """`VisionChatClient` backed by shelling out to the `claude` CLI.

    Alternative to `AnthropicVisionChatClient`: instead of calling the
    Anthropic API directly (metered, separate billing), this drives the
    user's locally-installed `claude` CLI, so the visual-fallback step
    draws on an existing Claude Pro/Max subscription's usage instead of a
    separate API key. See `config.get_vision_backend()` for how a caller
    picks between the two.

    The exact JSON shape parsed here (`result`, `is_error`,
    `permission_denials`, `subtype`, `type`) is grounded in a REAL,
    user-captured response from running:

        claude -p --output-format json --tools Read \
            --permission-mode bypassPermissions --no-session-persistence \
            "Read the image file at <path> using your Read tool, then ..."

    -- not guessed from documentation. See this subtask's `PROGRESS.md`
    entry ("Follow-up -- Claude Code CLI vision backend") for the full
    captured response this was built against; future maintainers changing
    this parsing should re-capture a live response rather than assume the
    shape from memory, since it isn't part of any published, versioned API
    contract.
    """

    def __init__(self, claude_binary: str = "claude", timeout_seconds: float = 60.0) -> None:
        self._claude_binary = claude_binary
        self._timeout_seconds = timeout_seconds

    def chat(self, image_path: Path, prompt: str) -> str:
        """Ask the `claude` CLI to read `image_path` then answer `prompt`.

        Raises:
            ClaudeCodeVisionError: on subprocess timeout, the `claude`
                binary being missing/not on `PATH`/not executable (any
                `OSError` from `subprocess.run` itself), non-zero exit,
                non-JSON stdout, `is_error: true`, or a non-empty
                `permission_denials` list in the parsed reply.
        """
        combined_prompt = (
            f"Read the image file at {image_path} using your Read tool. {prompt}"
        )

        return run_claude_cli(
            [
                self._claude_binary,
                "-p",
                "--output-format",
                "json",
                "--tools",
                "Read",
                "--permission-mode",
                "bypassPermissions",
                "--no-session-persistence",
                combined_prompt,
            ],
            claude_binary=self._claude_binary,
            timeout_seconds=self._timeout_seconds,
            context=f"analyzing {image_path}",
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

Look at the image and determine EITHER of the following:

1. Is a movie poster, a movie title card, or a clearly identifiable movie
   scene visible in this image?
2. Is there any creator-added ON-SCREEN TEXT overlay in this image (a
   caption, a lower-third, a listicle-style text card, etc. -- text that
   was added on top of the video, not text that's part of the scene
   itself) that names a movie or TV show? This is common in "rate these
   movies" / "movies like X" style videos, where the creator types each
   title directly onto the frame instead of showing a poster.

- If you can identify one or more movies/shows via EITHER signal above,
  name each one's title (and the release year, if you can tell it).
- If nothing identifiable is visible via either signal, say so by
  returning an empty list.

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
    (`detect(frame) -> list[Candidate]`) without inheriting from it. Per
    `_PROMPT` above, "about a frame" covers both posters/title cards/scenes
    AND creator-burned on-screen text overlays naming a movie/show -- the
    class/Protocol name stays `VisionLLMPosterDetector`/`PosterDetector`
    (not renamed to something broader) since those names are structural
    identifiers used across `core/protocols.py`, `pipeline/deps.py`,
    `pipeline/waterfall.py`, and their tests -- renaming is out of scope
    for a prompt-only widening and would ripple pointlessly.
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

        return parse_movie_candidates(
            raw_response,
            confidence_map=CONFIDENCE_MAP,
            default_confidence=_DEFAULT_CONFIDENCE,
            source=SourceTag.FRAME_VISUAL,
            log_context=f"vision LLM response for frame {frame.path}",
        )
