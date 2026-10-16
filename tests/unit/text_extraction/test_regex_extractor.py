"""Tests for RegexCandidateExtractor.

Confidence-tier boundaries, multi-candidate extraction, the explicitly
accepted "dismissive sentence" / short-ambiguous-title limitations from
brainstorm.md, and that `source` is echoed correctly.
"""

from __future__ import annotations

import pytest

from reel2movie.core.models import Candidate, SourceTag
from reel2movie.text_extraction.regex_extractor import (
    HIGH_CONFIDENCE,
    MEDIUM_CONFIDENCE,
    RegexCandidateExtractor,
)
from reel2movie.tmdb.resolver import _extract_year_hint


@pytest.fixture
def extractor() -> RegexCandidateExtractor:
    return RegexCandidateExtractor()


def test_quoted_title_with_year_is_high_confidence(extractor):
    result = extractor.extract('I loved "The Matrix" (1999)!', SourceTag.CAPTION)

    assert len(result) == 1
    candidate = result[0]
    assert candidate.confidence == HIGH_CONFIDENCE
    assert candidate.raw_text == "The Matrix (1999)"
    assert candidate.source == SourceTag.CAPTION


def test_unquoted_title_with_year_is_high_confidence(extractor):
    # Note: a sentence-initial capitalized word directly adjacent to the
    # title (e.g. "Watch Inception (2010)") is a known, documented
    # limitation of the strict "every word capitalized" unquoted
    # heuristic (see PROGRESS.md) — using "just watched" here so the
    # lowercase word correctly breaks the chain before the real title.
    result = extractor.extract(
        "I just watched Inception (2010) last night", SourceTag.CAPTION
    )

    assert len(result) == 1
    assert result[0].confidence == HIGH_CONFIDENCE
    assert result[0].raw_text == "Inception (2010)"


def test_raw_text_format_matches_what_resolver_expects(extractor):
    """The TMDB resolver's `_extract_year_hint()` looks for exactly
    `\\((\\d{4})\\)` in `candidate.raw_text` — confirm our HIGH-confidence
    output round-trips through it correctly."""
    result = extractor.extract('"Parasite" (2019)', SourceTag.CAPTION)

    assert len(result) == 1
    candidate = result[0]
    assert _extract_year_hint(candidate.raw_text) == 2019


def test_bare_quoted_title_without_year_is_medium_confidence(extractor):
    result = extractor.extract('My favorite is "Her", go watch it.', SourceTag.CAPTION)

    assert len(result) == 1
    candidate = result[0]
    assert candidate.confidence == MEDIUM_CONFIDENCE
    assert candidate.raw_text == "Her"
    assert "(" not in candidate.raw_text


def test_numbered_list_with_three_titles_returns_three_candidates(extractor):
    text = "5 movies like Inception:\n1. The Matrix\n2. Interstellar\n3. Tenet\n"
    result = extractor.extract(text, SourceTag.CAPTION)

    titles = {c.raw_text for c in result}
    assert {"The Matrix", "Interstellar", "Tenet"}.issubset(titles)
    list_candidates = [c for c in result if c.raw_text in titles]
    assert all(c.confidence == MEDIUM_CONFIDENCE for c in list_candidates)
    assert len(result) >= 3


def test_dismissive_sentence_with_quoted_title_is_still_extracted(extractor):
    """Accepted limitation (brainstorm.md): v1 does not do sentiment/intent
    filtering. This asserts the (false-positive) extraction DOES happen —
    it is not a bug to fix here."""
    result = extractor.extract(
        "This is not as good as 'The Godfather' honestly.", SourceTag.CAPTION
    )

    assert any(c.raw_text == "The Godfather" for c in result)


def test_short_ambiguous_quoted_title_is_still_extracted(extractor):
    """Disambiguating "It" is TMDB's/the pipeline's job, not this module's."""
    result = extractor.extract('Have you seen "It"?', SourceTag.CAPTION)

    assert len(result) == 1
    assert result[0].raw_text == "It"
    assert result[0].confidence == MEDIUM_CONFIDENCE


def test_empty_string_returns_empty_list(extractor):
    assert extractor.extract("", SourceTag.CAPTION) == []


def test_no_signal_text_returns_empty_list_and_does_not_crash(extractor):
    result = extractor.extract(
        "just some plain lowercase text with nothing special in it",
        SourceTag.CREATOR_COMMENT,
    )

    assert result == []


def test_source_is_echoed_for_every_candidate(extractor):
    text = '"A" (2001) and "B" and 1. C'
    result = extractor.extract(text, SourceTag.CREATOR_COMMENT)

    assert len(result) >= 1
    assert all(c.source == SourceTag.CREATOR_COMMENT for c in result)


def test_multiple_high_confidence_candidates_in_one_block(extractor):
    text = 'Recommending "Parasite" (2019) and Inception (2010) this week.'
    result = extractor.extract(text, SourceTag.CAPTION)

    raw_texts = {c.raw_text for c in result}
    assert "Parasite (2019)" in raw_texts
    assert "Inception (2010)" in raw_texts
    assert all(c.confidence == HIGH_CONFIDENCE for c in result)


def test_returns_candidate_instances(extractor):
    result = extractor.extract('"Up" (2009)', SourceTag.CAPTION)

    assert len(result) == 1
    assert isinstance(result[0], Candidate)


def test_numbered_list_title_with_connector_words_and_year_is_not_dropped(extractor):
    """Regression for review finding #1 (Subtask 3, cycle 1): a numbered-
    list title with lowercase connector words before its year (e.g. "The
    Lord of the Rings (2001)") used to have its full title silently
    dropped entirely — the unquoted-HIGH pass's all-caps-chain match would
    first claim only the trailing "Rings (2001)" span, then the
    numbered-list pass would see its own full-line span overlap that
    smaller claim and skip emitting anything for the line. Fixed by
    letting `_UNQUOTED_TITLE_YEAR` include lowercase connector words
    ("of", "the", etc.) inside the title-case run, so it claims the
    correct full span itself on the first pass."""
    text = "5 movies like Inception:\n1. The Lord of the Rings (2001)\n2. Interstellar\n"
    result = extractor.extract(text, SourceTag.CAPTION)

    raw_texts = {c.raw_text for c in result}
    assert "The Lord of the Rings (2001)" in raw_texts
    assert not any(t.startswith("Rings") for t in raw_texts)
    assert "Interstellar" in raw_texts


def test_sentence_initial_word_false_positive_not_worsened(extractor):
    """Guard against the connector-word fix above reintroducing/worsening
    the already-documented sentence-initial false positive: "Watch
    Inception (2010)" still wrongly captures "Watch Inception" (an
    accepted, unfixed limitation per PROGRESS.md), not something worse."""
    result = extractor.extract("Watch Inception (2010) tonight", SourceTag.CAPTION)

    assert len(result) == 1
    assert result[0].raw_text == "Watch Inception (2010)"
    assert result[0].confidence == HIGH_CONFIDENCE


def test_quoted_title_containing_own_parenthesized_year_uses_trailing_year(extractor):
    """Regression for review finding #2 (Subtask 3, cycle 1): a quoted
    title whose own text contains a parenthesized 4-digit substring used
    to produce an ambiguous raw_text that resolver.py's
    `_extract_year_hint()` misread (leftmost match, not the real trailing
    year). Fixed in `tmdb/resolver.py` by searching from the right."""
    result = extractor.extract(
        '"Experience Paris (1920) like never before" (2023)', SourceTag.CAPTION
    )

    assert len(result) == 1
    assert _extract_year_hint(result[0].raw_text) == 2023
