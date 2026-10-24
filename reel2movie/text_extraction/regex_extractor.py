"""Pure regex-based `CandidateExtractor` for caption/comment text.

No IO, no network, no NLP library — `re` from stdlib is sufficient per the
subtask spec. Structurally satisfies `core.protocols.CandidateExtractor`
(`extract(text, source) -> list[Candidate]`) without inheriting from it.

Confidence tiers (see PROGRESS.md "Subtask 3" section for full rationale):
  - HIGH   (0.9) — `"Title (YYYY)"`, quoted or unquoted: least ambiguous,
    since both a title-shaped string *and* a year are present together.
  - MEDIUM (0.6) — a bare quoted span with no year, or a numbered-list
    line's title: still a clear "this is a title" signal (explicit
    delimiter), just missing the year disambiguator.
  - (none) — bare, unquoted, unmarked title-case runs are skipped entirely
    (not tagged LOW) — see PROGRESS.md for why.

Known, accepted limitation (per brainstorm.md): a quoted/parenthesized
title inside a *dismissive* sentence ("not as good as 'X'") is still
extracted — this module does no sentiment/intent filtering. That is a
deliberate scope limit, not a bug.
"""

from __future__ import annotations

import re
import threading

from reel2movie.core.models import Candidate, SourceTag

HIGH_CONFIDENCE = 0.9
MEDIUM_CONFIDENCE = 0.6

# "Title (YYYY)" with the title in matching quotes.
_QUOTED_TITLE_YEAR = re.compile(
    r"""(?:"([^"\n]{1,100})"|'([^'\n]{1,100})')\s*\((\d{4})\)"""
)

# "Title (YYYY)" with no quotes: the title must start with an
# uppercase-leading word, and every subsequent word must either also start
# with an uppercase letter, or be one of a small set of lowercase
# connector words (so "The Lord of the Rings (2001)" matches as one run,
# not just the trailing "Rings (2001)"), directly followed by a 4-digit
# parenthesized year. A sentence-initial capitalized word directly
# adjacent to the real title (e.g. "Watch Inception (2010)") is a known,
# accepted false-positive source of this heuristic — unaffected by the
# connector-word allowance, since it's about an *extra* leading uppercase
# word, not a lowercase one — see PROGRESS.md open questions.
_CONNECTOR_WORD = r"(?:of|the|and|a|an|in|on|to|for|at|by|vs|with)"
_UNQUOTED_TITLE_YEAR = re.compile(
    r"\b([A-Z][\w'&:-]*(?:\s+(?:[A-Z][\w'&:-]*|" + _CONNECTOR_WORD + r"))*)"
    r"\s*\((\d{4})\)"
)

# Any quoted span, matching-quote-type only, capped at 100 chars and not
# spanning newlines (keeps a stray apostrophe from a contraction pairing
# with an unrelated single quote far away in the text).
_QUOTED_SPAN = re.compile(r"""(?:"([^"\n]{1,100})"|'([^'\n]{1,100})')""")

# "1. Title" / "2) Title" — a numbered-list line; group(1) is everything
# after the marker on that line.
_NUMBERED_LIST = re.compile(r"^\s*\d+[.)]\s+(.+)$", re.MULTILINE)

_Span = tuple[int, int]


def _claim(span: _Span, claimed: list[_Span]) -> bool:
    """Return True and record `span` if it doesn't overlap anything
    already claimed; return False (and record nothing) if it does.

    This is how earlier (higher-confidence) regex passes stop later
    passes from emitting a duplicate candidate for the same text.
    """
    start, end = span
    for claimed_start, claimed_end in claimed:
        if start < claimed_end and claimed_start < end:
            return False
    claimed.append(span)
    return True


def _clean_list_title(raw: str) -> str:
    """Strip whitespace, matching outer quotes, and trailing punctuation
    from a numbered-list line's captured title text."""
    title = raw.strip()
    if len(title) >= 2 and title[0] == title[-1] and title[0] in "\"'":
        title = title[1:-1].strip()
    return title.rstrip(" .,;:")


class RegexCandidateExtractor:
    """Pure, stateless `CandidateExtractor`: regex/string logic only."""

    def extract(
        self,
        text: str,
        source: SourceTag,
        *,
        cancel_event: threading.Event | None = None,
    ) -> list[Candidate]:
        # cancel_event is accepted only for signature compatibility with
        # core.protocols.CandidateExtractor -- this extractor is pure
        # regex/string logic with no subprocess or I/O, so there is
        # nothing in flight to actually cancel. Not an oversight.
        if not text:
            return []

        claimed: list[_Span] = []
        candidates: list[Candidate] = []

        for match in _QUOTED_TITLE_YEAR.finditer(text):
            if not _claim(match.span(), claimed):
                continue
            title = (match.group(1) or match.group(2) or "").strip()
            if not title:
                continue
            year = match.group(3)
            candidates.append(
                Candidate(
                    raw_text=f"{title} ({year})",
                    source=source,
                    confidence=HIGH_CONFIDENCE,
                )
            )

        for match in _UNQUOTED_TITLE_YEAR.finditer(text):
            if not _claim(match.span(), claimed):
                continue
            title = match.group(1).strip()
            year = match.group(2)
            candidates.append(
                Candidate(
                    raw_text=f"{title} ({year})",
                    source=source,
                    confidence=HIGH_CONFIDENCE,
                )
            )

        for match in _QUOTED_SPAN.finditer(text):
            if not _claim(match.span(), claimed):
                continue
            title = (match.group(1) or match.group(2) or "").strip()
            if not title:
                continue
            candidates.append(
                Candidate(raw_text=title, source=source, confidence=MEDIUM_CONFIDENCE)
            )

        for match in _NUMBERED_LIST.finditer(text):
            if not _claim(match.span(1), claimed):
                continue
            title = _clean_list_title(match.group(1))
            if not title:
                continue
            candidates.append(
                Candidate(raw_text=title, source=source, confidence=MEDIUM_CONFIDENCE)
            )

        return candidates
