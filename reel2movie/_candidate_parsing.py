"""Shared JSON-array-of-movie-mentions parser.

Internal module (leading underscore, not part of the public package
surface): used by both `visual/vision_llm_detector.py`'s
`VisionLLMPosterDetector.detect()` and
`text_extraction/claude_code_extractor.py`'s
`ClaudeCodeCandidateExtractor.extract()`, which previously duplicated this
"parse a JSON array of `{title, year, confidence}`-shaped items into
Candidates, skipping malformed items with a warning" loop nearly verbatim.
Each caller supplies its own confidence-label map and default.
"""

from __future__ import annotations

import json
import logging

from reel2movie.core.models import Candidate, SourceTag

logger = logging.getLogger(__name__)


def parse_movie_candidates(
    raw_response: str,
    *,
    confidence_map: dict[str, float],
    default_confidence: float,
    source: SourceTag,
    log_context: str,
) -> list[Candidate]:
    """Parse `raw_response` into a list of `Candidate`s.

    Expected shape: a JSON array of objects with keys "title" (string,
    required), "year" (int, optional), and "confidence" (a string key into
    `confidence_map`, optional). Malformed items are skipped, not fatal.

    Never raises on a malformed/non-JSON/unexpected-shape `raw_response` --
    any parsing failure is logged (using `log_context` to identify the call
    site) and `[]` is returned instead.
    """
    try:
        parsed = json.loads(raw_response.strip())
    except (json.JSONDecodeError, AttributeError):
        logger.warning(
            "%s: non-JSON response: %r", log_context, raw_response
        )
        return []

    if not isinstance(parsed, list):
        logger.warning("%s: JSON response was not a list: %r", log_context, parsed)
        return []

    candidates: list[Candidate] = []
    for item in parsed:
        if not isinstance(item, dict):
            logger.warning(
                "%s: non-object list item, skipping: %r", log_context, item
            )
            continue

        title = item.get("title")
        if not isinstance(title, str) or not title.strip():
            logger.warning(
                "%s: item with no usable title, skipping: %r", log_context, item
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
        confidence = confidence_map.get(confidence_label, default_confidence)

        candidates.append(
            Candidate(raw_text=raw_text, source=source, confidence=confidence)
        )

    return candidates
