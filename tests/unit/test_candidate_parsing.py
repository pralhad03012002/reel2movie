"""Tests for the shared `reel2movie._candidate_parsing.parse_movie_candidates`
helper -- the "parse a JSON array of movie mentions into Candidates" logic
previously duplicated between `VisionLLMPosterDetector.detect()` and
`ClaudeCodeCandidateExtractor.extract()`.
"""

from __future__ import annotations

import json

from reel2movie._candidate_parsing import parse_movie_candidates
from reel2movie.core.models import Candidate, SourceTag

_CONFIDENCE_MAP = {"high": 0.8, "medium": 0.5, "low": 0.3}


class TestParseMovieCandidates:
    def test_single_item_with_year_and_known_confidence(self) -> None:
        raw = json.dumps([{"title": "Inception", "year": 2010, "confidence": "high"}])

        result = parse_movie_candidates(
            raw,
            confidence_map=_CONFIDENCE_MAP,
            default_confidence=0.5,
            source=SourceTag.FRAME_VISUAL,
            log_context="test",
        )

        assert result == [
            Candidate(
                raw_text="Inception (2010)",
                source=SourceTag.FRAME_VISUAL,
                confidence=0.8,
            )
        ]

    def test_item_without_year(self) -> None:
        raw = json.dumps([{"title": "Interstellar", "confidence": "medium"}])

        result = parse_movie_candidates(
            raw,
            confidence_map=_CONFIDENCE_MAP,
            default_confidence=0.5,
            source=SourceTag.CAPTION,
            log_context="test",
        )

        assert result == [
            Candidate(
                raw_text="Interstellar", source=SourceTag.CAPTION, confidence=0.5
            )
        ]

    def test_empty_array_returns_empty_list(self) -> None:
        assert (
            parse_movie_candidates(
                "[]",
                confidence_map=_CONFIDENCE_MAP,
                default_confidence=0.5,
                source=SourceTag.CAPTION,
                log_context="test",
            )
            == []
        )

    def test_non_json_response_returns_empty_list_without_raising(self) -> None:
        assert (
            parse_movie_candidates(
                "not json",
                confidence_map=_CONFIDENCE_MAP,
                default_confidence=0.5,
                source=SourceTag.CAPTION,
                log_context="test",
            )
            == []
        )

    def test_json_object_instead_of_array_returns_empty_list(self) -> None:
        assert (
            parse_movie_candidates(
                json.dumps({"title": "Inception"}),
                confidence_map=_CONFIDENCE_MAP,
                default_confidence=0.5,
                source=SourceTag.CAPTION,
                log_context="test",
            )
            == []
        )

    def test_item_missing_title_is_skipped_not_fatal(self) -> None:
        raw = json.dumps(
            [
                {"confidence": "high"},
                {"title": "Interstellar", "confidence": "medium"},
            ]
        )

        result = parse_movie_candidates(
            raw,
            confidence_map=_CONFIDENCE_MAP,
            default_confidence=0.5,
            source=SourceTag.CAPTION,
            log_context="test",
        )

        assert result == [
            Candidate(
                raw_text="Interstellar", source=SourceTag.CAPTION, confidence=0.5
            )
        ]

    def test_unrecognized_confidence_label_falls_back_to_default(self) -> None:
        raw = json.dumps([{"title": "Interstellar", "confidence": "very sure"}])

        [candidate] = parse_movie_candidates(
            raw,
            confidence_map=_CONFIDENCE_MAP,
            default_confidence=0.5,
            source=SourceTag.CAPTION,
            log_context="test",
        )

        assert candidate.confidence == 0.5

    def test_different_callers_can_use_different_confidence_maps(self) -> None:
        """The whole point of taking `confidence_map` as a parameter: two
        different callers (vision's 0.8/0.5/0.3 vs. text's HIGH/MEDIUM
        tiers) get their own numeric confidence for the same label.
        """
        raw = json.dumps([{"title": "X", "confidence": "high"}])

        vision_result = parse_movie_candidates(
            raw,
            confidence_map={"high": 0.8},
            default_confidence=0.5,
            source=SourceTag.FRAME_VISUAL,
            log_context="test",
        )
        text_result = parse_movie_candidates(
            raw,
            confidence_map={"high": 0.95},
            default_confidence=0.6,
            source=SourceTag.CAPTION,
            log_context="test",
        )

        assert vision_result[0].confidence == 0.8
        assert text_result[0].confidence == 0.95
