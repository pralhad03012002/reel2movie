"""Tests for tmdb/resolver.py, using a fake TMDBClient-shaped object."""

from __future__ import annotations

from reel2movie.core.models import Candidate, SourceTag, TMDBSearchResult
from reel2movie.tmdb.resolver import resolve_candidate


class FakeTMDBClient:
    """A minimal fake satisfying the TMDBClient Protocol structurally."""

    def __init__(self, results: list[TMDBSearchResult]) -> None:
        self._results = results
        self.last_query: str | None = None
        self.last_year: int | None = None

    def search_movie(
        self, query: str, year: int | None = None
    ) -> list[TMDBSearchResult]:
        self.last_query = query
        self.last_year = year
        return self._results


def _candidate(raw_text: str) -> Candidate:
    return Candidate(raw_text=raw_text, source=SourceTag.CAPTION, confidence=0.9)


def _search_result(**overrides) -> TMDBSearchResult:
    defaults = dict(
        id=603,
        title="The Matrix",
        year=1999,
        poster_path="/matrix.jpg",
        overview="A hacker learns the truth.",
        popularity=80.0,
        original_rank=0,
    )
    defaults.update(overrides)
    return TMDBSearchResult(**defaults)


def test_extracts_year_hint_from_candidate_text():
    client = FakeTMDBClient([_search_result()])

    resolve_candidate(_candidate("The Matrix (1999)"), client)

    assert client.last_year == 1999
    assert client.last_query == "The Matrix (1999)"


def test_no_year_hint_when_no_parenthesized_year_present():
    client = FakeTMDBClient([_search_result()])

    resolve_candidate(_candidate("The Matrix"), client)

    assert client.last_year is None


def test_maps_winning_result_to_resolved_movie():
    client = FakeTMDBClient([_search_result()])

    resolved = resolve_candidate(_candidate("The Matrix (1999)"), client)

    assert resolved is not None
    assert resolved.id == 603
    assert resolved.title == "The Matrix"
    assert resolved.year == 1999
    assert resolved.poster_path == "/matrix.jpg"
    assert resolved.overview == "A hacker learns the truth."
    assert isinstance(resolved.match_score, float)
    # popularity/original_rank are dropped, not present on ResolvedMovie
    assert not hasattr(resolved, "popularity")
    assert not hasattr(resolved, "original_rank")


def test_returns_none_when_nothing_resolves():
    client = FakeTMDBClient([])

    resolved = resolve_candidate(_candidate("Some Obscure Nonexistent Title"), client)

    assert resolved is None


def test_returns_none_when_best_result_is_low_confidence():
    client = FakeTMDBClient(
        [_search_result(title="Completely Unrelated Thing", year=None, original_rank=7)]
    )

    resolved = resolve_candidate(_candidate("The Matrix"), client)

    assert resolved is None


def test_year_hint_uses_last_parenthesized_year_not_first():
    """Regression for Subtask 3 review finding #2: raw_text can contain
    an embedded "(YYYY)"-shaped substring that isn't the real year (e.g.
    a quoted title that itself mentions a year), with the real trailing
    release year appended after it by text_extraction/regex_extractor.py.
    `_extract_year_hint()` must pick the LAST match, not the first."""
    client = FakeTMDBClient([_search_result()])

    raw_text = 'Experience Paris (1920) like never before (2023)'
    resolve_candidate(_candidate(raw_text), client)

    assert client.last_year == 2023
