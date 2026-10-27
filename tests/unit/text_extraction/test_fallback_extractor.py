"""Tests for `text_extraction/fallback_extractor.py`.

Uses fake primary/fallback `CandidateExtractor`-shaped test doubles that
record whether they were called -- no real regex/claude extractor needed,
since `FallbackCandidateExtractor` is meant to be generic.
"""

from __future__ import annotations

import threading

from reel2movie.core.models import Candidate, SourceTag
from reel2movie.text_extraction.fallback_extractor import FallbackCandidateExtractor


class FakeExtractor:
    """A `CandidateExtractor` test double that records whether it was called."""

    def __init__(self, result: list[Candidate]) -> None:
        self._result = result
        self.called = False
        self.last_text: str | None = None
        self.last_source: SourceTag | None = None

    def extract(self, text: str, source: SourceTag) -> list[Candidate]:
        self.called = True
        self.last_text = text
        self.last_source = source
        return self._result


class FakeExtractorAcceptingCancelEvent:
    """Same as `FakeExtractor`, but also records any `cancel_event` it was
    called with -- used to confirm `FallbackCandidateExtractor` actually
    forwards it, without requiring every pre-existing `FakeExtractor` in
    this file to know about the parameter."""

    def __init__(self, result: list[Candidate]) -> None:
        self._result = result
        self.called = False
        self.last_cancel_event: threading.Event | None = None

    def extract(
        self,
        text: str,
        source: SourceTag,
        *,
        cancel_event: threading.Event | None = None,
    ) -> list[Candidate]:
        self.called = True
        self.last_cancel_event = cancel_event
        return self._result


def _candidate(raw_text: str = "Some Movie") -> Candidate:
    return Candidate(raw_text=raw_text, source=SourceTag.CAPTION, confidence=0.9)


class TestFallbackCandidateExtractor:
    def test_primary_nonempty_short_circuits_fallback(self) -> None:
        primary = FakeExtractor([_candidate("Primary Movie")])
        fallback = FakeExtractor([_candidate("Fallback Movie")])
        extractor = FallbackCandidateExtractor(primary, fallback)

        result = extractor.extract("some text", SourceTag.CAPTION)

        assert result == [_candidate("Primary Movie")]
        assert primary.called is True
        assert fallback.called is False

    def test_primary_empty_calls_fallback_and_returns_its_result(self) -> None:
        primary = FakeExtractor([])
        fallback = FakeExtractor([_candidate("Fallback Movie")])
        extractor = FallbackCandidateExtractor(primary, fallback)

        result = extractor.extract("some text", SourceTag.CAPTION)

        assert result == [_candidate("Fallback Movie")]
        assert primary.called is True
        assert fallback.called is True

    def test_both_empty_returns_empty_list_without_error(self) -> None:
        primary = FakeExtractor([])
        fallback = FakeExtractor([])
        extractor = FallbackCandidateExtractor(primary, fallback)

        result = extractor.extract("some text", SourceTag.CAPTION)

        assert result == []
        assert primary.called is True
        assert fallback.called is True

    def test_text_and_source_are_passed_through_to_primary(self) -> None:
        primary = FakeExtractor([_candidate()])
        fallback = FakeExtractor([])
        extractor = FallbackCandidateExtractor(primary, fallback)

        extractor.extract("caption text", SourceTag.CREATOR_COMMENT)

        assert primary.last_text == "caption text"
        assert primary.last_source is SourceTag.CREATOR_COMMENT

    def test_text_and_source_are_passed_through_to_fallback(self) -> None:
        primary = FakeExtractor([])
        fallback = FakeExtractor([_candidate()])
        extractor = FallbackCandidateExtractor(primary, fallback)

        extractor.extract("caption text", SourceTag.CREATOR_COMMENT)

        assert fallback.last_text == "caption text"
        assert fallback.last_source is SourceTag.CREATOR_COMMENT

    def test_no_cancel_event_does_not_pass_the_kwarg_to_a_legacy_primary(self) -> None:
        """A pre-existing `CandidateExtractor`-shaped test double that only
        implements `extract(text, source)` (predating `cancel_event`) must
        keep working when no cancel_event is given -- confirming
        `FallbackCandidateExtractor` doesn't unconditionally forward the
        kwarg."""
        primary = FakeExtractor([_candidate("Primary Movie")])
        fallback = FakeExtractor([])
        extractor = FallbackCandidateExtractor(primary, fallback)

        result = extractor.extract("some text", SourceTag.CAPTION)

        assert result == [_candidate("Primary Movie")]

    def test_cancel_event_is_forwarded_to_primary_when_given(self) -> None:
        cancel_event = threading.Event()
        primary = FakeExtractorAcceptingCancelEvent([_candidate("Primary Movie")])
        fallback = FakeExtractorAcceptingCancelEvent([])
        extractor = FallbackCandidateExtractor(primary, fallback)

        extractor.extract("some text", SourceTag.CAPTION, cancel_event=cancel_event)

        assert primary.last_cancel_event is cancel_event

    def test_cancel_event_is_forwarded_to_fallback_when_primary_is_empty(self) -> None:
        cancel_event = threading.Event()
        primary = FakeExtractorAcceptingCancelEvent([])
        fallback = FakeExtractorAcceptingCancelEvent([_candidate("Fallback Movie")])
        extractor = FallbackCandidateExtractor(primary, fallback)

        result = extractor.extract(
            "some text", SourceTag.CAPTION, cancel_event=cancel_event
        )

        assert result == [_candidate("Fallback Movie")]
        assert primary.last_cancel_event is cancel_event
        assert fallback.last_cancel_event is cancel_event
