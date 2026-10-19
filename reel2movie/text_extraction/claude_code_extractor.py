"""`claude`-CLI-backed `CandidateExtractor` for natural-prose text.

`regex_extractor.py`'s `RegexCandidateExtractor` only catches explicit,
structurally-regular shapes ("Title (YYYY)", quoted spans, numbered lists).
A real caption like "Dhobi Ghat ... is a 2010 Indian drama film directed by
Kiran Rao" states a movie title + year in plain prose with none of those
shapes, which regex cannot structurally parse. This module is the fallback
for exactly that case: it shells out to the `claude` CLI (no file/image
access needed -- pure text reasoning) and asks the model to read the text
and identify any movie title(s) it explicitly states or clearly implies.

Design note, mirroring `visual/vision_llm_detector.py`'s rationale: the
actual provider call is wrapped behind a tiny local `TextChatClient`
Protocol defined in *this* module (same pattern as that module's local
`VisionChatClient`), so `ClaudeCodeCandidateExtractor`'s own logic (prompt
construction, JSON parsing, confidence mapping) stays fully decoupled from
HOW the chat call happens.

Confidence mapping -- deliberately text-tier (`HIGH_CONFIDENCE`/
`MEDIUM_CONFIDENCE`, imported from `regex_extractor.py`), NOT
`vision_llm_detector.py`'s dampened 0.8/0.5/0.3 vision-guessing scale: a
piece of text that explicitly, unambiguously states "X is a 2010 film" is
just as certain a signal as regex's own HIGH tier (a quoted/parenthesized
"Title (YYYY)") -- it's merely in a shape regex can't parse. Vision
detection is inherently a guess from pixels (hence the dampened scale);
reading an explicit textual claim is not. `HIGH_CONFIDENCE`/
`MEDIUM_CONFIDENCE` are imported directly from `regex_extractor.py` rather
than re-declared, per this project's established convention of binding
shared constants by import, not duplicating magic numbers (see
`pipeline/waterfall.py`'s `CONFIDENCE_THRESHOLD`).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from reel2movie._candidate_parsing import parse_movie_candidates
from reel2movie._claude_cli import ClaudeCliError, run_claude_cli
from reel2movie.core.models import Candidate, SourceTag
from reel2movie.text_extraction.regex_extractor import (
    HIGH_CONFIDENCE,
    MEDIUM_CONFIDENCE,
)


@runtime_checkable
class TextChatClient(Protocol):
    """A minimal "send one text prompt, get text back" chat seam.

    Same pattern as `visual/vision_llm_detector.py`'s local
    `VisionChatClient` Protocol, minus the image: this is pure text
    reasoning, no file/image access required.
    """

    def chat(self, prompt: str) -> str: ...


# Alias (not a subclass) of the shared `ClaudeCliError` raised by
# `run_claude_cli()` -- see `reel2movie._claude_cli` for the actual
# error-raising logic this used to duplicate (same pattern as
# `visual.vision_llm_detector.ClaudeCodeVisionError`). Kept under this name
# since external code/tests still import/reference it as
# `ClaudeCodeTextError`.
ClaudeCodeTextError = ClaudeCliError


class ClaudeCodeTextChatClient:
    """`TextChatClient` backed by shelling out to the `claude` CLI.

    No image/file access is needed for text-only reasoning, so tools are
    disabled entirely (`--tools ""`) rather than granting `Read` as
    `ClaudeCodeVisionChatClient` does.
    """

    def __init__(self, claude_binary: str = "claude", timeout_seconds: float = 60.0) -> None:
        self._claude_binary = claude_binary
        self._timeout_seconds = timeout_seconds

    def chat(self, prompt: str) -> str:
        """Ask the `claude` CLI to answer `prompt`, return the text reply.

        Raises:
            ClaudeCodeTextError: on subprocess timeout, the `claude`
                binary being missing/not on `PATH`/not executable (any
                `OSError` from `subprocess.run` itself), non-zero exit,
                non-JSON stdout, `is_error: true`, or a non-empty
                `permission_denials` list in the parsed reply.
        """
        return run_claude_cli(
            [
                self._claude_binary,
                "-p",
                "--output-format",
                "json",
                "--tools",
                "",
                "--permission-mode",
                "bypassPermissions",
                "--no-session-persistence",
                prompt,
            ],
            claude_binary=self._claude_binary,
            timeout_seconds=self._timeout_seconds,
            context="extracting movie titles from text",
        )


_PROMPT_TEMPLATE = """You are reading a piece of text (e.g. an Instagram reel caption or comment).

Read the text below and determine: does it explicitly state, or clearly
imply, that one or more specific movies are being discussed or
recommended? This includes natural prose statements of fact (e.g. "X,
released internationally as Y, is a 2010 Indian drama film directed by
Z..."), not just quoted titles or numbered lists.

- If you can identify one or more movies, name each movie's title (and
  the release year, if explicitly stated).
- If nothing identifiable is a movie recommendation/discussion, return an
  empty list.

Respond with ONLY a JSON array, and nothing else: no prose before or after
it, no markdown code fences. Each element must be an object with keys
"title" (string, required), "year" (integer, optional -- omit or use null
if unknown), and "confidence" (one of the strings "high" or "medium",
required -- "high" only if the text explicitly and unambiguously states
the title as fact, "medium" otherwise).

Example of a response with one movie identified:
[{"title": "Dhobi Ghat", "year": 2010, "confidence": "high"}]

Example of a response with nothing identifiable:
[]

Text to read:
\"\"\"
{text}
\"\"\"
"""

# Maps the prompt's confidence labels to this extraction layer's numeric
# confidence. Deliberately bound to regex_extractor.py's own tiers by
# import (not a parallel literal) -- see module docstring for why this is
# text-tier, not vision-tier, confidence.
_CONFIDENCE_MAP: dict[str, float] = {
    "high": HIGH_CONFIDENCE,
    "medium": MEDIUM_CONFIDENCE,
}

# Fallback for a missing/unrecognized confidence label -- a safe middle
# default, deliberately NOT HIGH_CONFIDENCE (that would be too permissive
# for a label the model didn't actually give us).
_DEFAULT_CONFIDENCE = MEDIUM_CONFIDENCE


class ClaudeCodeCandidateExtractor:
    """`CandidateExtractor` that asks the `claude` CLI about raw text.

    Structurally satisfies `core.protocols.CandidateExtractor`
    (`extract(text, source) -> list[Candidate]`) without inheriting from
    it.
    """

    def __init__(self, chat_client: TextChatClient) -> None:
        self._chat_client = chat_client

    def extract(self, text: str, source: SourceTag) -> list[Candidate]:
        """Ask the chat client about `text`, parse the reply into Candidates.

        Skips the CLI call entirely (returns `[]`) for empty/whitespace-
        only text -- no point spending a subprocess call on nothing.

        Never raises on a malformed/non-JSON/unexpected-shape reply from
        the model -- a single bad extraction shouldn't crash the whole
        pipeline, so any parsing failure is logged and `[]` is returned
        instead.
        """
        if not text or not text.strip():
            return []

        prompt = _PROMPT_TEMPLATE.replace("{text}", text)
        raw_response = self._chat_client.chat(prompt)

        return parse_movie_candidates(
            raw_response,
            confidence_map=_CONFIDENCE_MAP,
            default_confidence=_DEFAULT_CONFIDENCE,
            source=source,
            log_context="claude CLI text extraction response",
        )
