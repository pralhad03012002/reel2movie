"""Generic "try cheap first, fall back to expensive" `CandidateExtractor` composer.

Motivation: `regex_extractor.py`'s `RegexCandidateExtractor` is free/instant
but only catches explicit, structurally-regular title shapes. A real
caption stating a movie title in natural prose (no quotes, no year
immediately in parens, no numbered list) is a common case regex
structurally cannot handle -- but regex should still run first for the
common explicit-format case, since it costs nothing. `FallbackCandidateExtractor`
is a thin, generic composition wrapper for exactly this "try primary, only
pay for fallback if primary finds nothing" pattern -- it is deliberately
not specific to regex+claude: both constructor parameters are typed
against the `CandidateExtractor` Protocol (structural), so this class
works for any two `CandidateExtractor`-shaped objects.
"""

from __future__ import annotations

from reel2movie.core.models import Candidate, SourceTag
from reel2movie.core.protocols import CandidateExtractor


class FallbackCandidateExtractor:
    """Tries `primary` first; only calls `fallback` if primary finds nothing.

    Structurally satisfies `core.protocols.CandidateExtractor`
    (`extract(text, source) -> list[Candidate]`) without inheriting from
    it.
    """

    def __init__(self, primary: CandidateExtractor, fallback: CandidateExtractor) -> None:
        self._primary = primary
        self._fallback = fallback

    def extract(self, text: str, source: SourceTag) -> list[Candidate]:
        primary_result = self._primary.extract(text, source)
        if primary_result:
            return primary_result
        return self._fallback.extract(text, source)
