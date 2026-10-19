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
    # Regression for the TMDB query-dilution bug: the literal "(1999)"
    # must NOT be sent as part of the search query string (confirmed
    # against the live TMDB API that a baked-in "(YYYY)" can return zero
    # results even for an exact title match) -- the year is passed
    # separately via `year=`.
    assert client.last_query == "The Matrix"


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


def test_query_strips_only_trailing_year_not_embedded_one():
    """Regression for the TMDB query-dilution bug, combined with the
    embedded-year edge case: only the TRAILING "(2023)" should be
    stripped from the search query, leaving the title's own embedded
    "(1920)" untouched (same "trailing only" anchoring as
    `_extract_year_hint`)."""
    client = FakeTMDBClient([_search_result()])

    raw_text = "Experience Paris (1920) like never before (2023)"
    resolve_candidate(_candidate(raw_text), client)

    assert client.last_query == "Experience Paris (1920) like never before"


def test_query_strips_trailing_year_for_high_confidence_candidate():
    """The exact real-world bug case: a "Title (YYYY)" candidate must be
    searched with just the title -- confirmed against the live TMDB API
    that the literal "(YYYY)" baked into the query can return zero
    results even for an exact title match."""
    client = FakeTMDBClient([_search_result(title="Inception", year=2010)])

    resolve_candidate(_candidate("Inception (2010)"), client)

    assert client.last_query == "Inception"
    assert client.last_year == 2010


def test_query_unchanged_when_no_year_present():
    """A MEDIUM-confidence bare-title candidate (no year in raw_text) has
    nothing to strip -- the query passed to TMDB must be exactly the
    original raw_text, untouched."""
    client = FakeTMDBClient([_search_result(title="Interstellar", year=2014)])

    resolve_candidate(_candidate("Interstellar"), client)

    assert client.last_query == "Interstellar"
    assert client.last_year is None


def test_query_strips_adjacent_double_trailing_year():
    """Regression for the review-blocking adjacent-double-trailing-year
    case: a caption like `Rewatching "Se7en (1995)" (2015) tonight` --
    reachable via RegexCandidateExtractor's quoted-title pattern, which
    has no restriction against parens inside a quoted title -- produces
    raw_text='Se7en (1995) (2015)'. A single-pass strip only removes the
    outer "(2015)", leaving "Se7en (1995)" -- itself still
    trailing-year-shaped, reproducing the exact zero-result TMDB dilution
    bug this whole fix exists to close (confirmed live:
    search_movie("Se7en (1995)", year=2015) -> 0 results;
    search_movie("Se7en", year=2015) -> 7 results). The query sent must be
    fully stripped down to "Se7en"."""
    client = FakeTMDBClient([_search_result(title="Se7en", year=1995)])

    raw_text = "Se7en (1995) (2015)"
    resolve_candidate(_candidate(raw_text), client)

    assert client.last_query == "Se7en"
    assert client.last_year == 2015


def test_query_falls_back_to_raw_text_when_fully_stripped_to_empty():
    """Regression for the cycle-2 review-blocking empty-query case: a
    candidate whose raw_text is made ENTIRELY of chained "(YYYY)"-shaped
    groups, with no other content, strips all the way down to "" via the
    adjacent-year loop above. This is reachable through the real
    RegexCandidateExtractor's quoted-title pattern -- a caption like
    `Watch "(1999)" (2010) now` produces
    Candidate(raw_text='(1999) (2010)', confidence=0.9) because the
    quoted-title capture group has no restriction against the quoted text
    itself looking like a year. Sending an empty query to TMDB is strictly
    worse than the original dilution bug (which at least sent some
    non-empty text), so the fallback must be the full original raw_text,
    not "".
    """
    client = FakeTMDBClient([_search_result()])

    raw_text = "(1999) (2010)"
    resolve_candidate(_candidate(raw_text), client)

    assert client.last_query == raw_text
    assert client.last_query != ""
    assert client.last_year == 2010


def test_query_strips_three_adjacent_trailing_years():
    """Loop-termination stress test (from the cycle-2 review): three
    adjacent "(YYYY)"-shaped trailing groups must still fully reduce to
    the bare title, confirming the empty-query guard didn't regress the
    already-working multi-strip behavior."""
    client = FakeTMDBClient([_search_result(title="Title", year=2020)])

    raw_text = "Title (1111) (2222) (2020)"
    resolve_candidate(_candidate(raw_text), client)

    assert client.last_query == "Title"
    assert client.last_year == 2020


def test_match_score_uses_stripped_query_not_raw_text_with_year():
    """`score_result`/`pick_best` must also receive the stripped query --
    not the original raw_text with the year still baked in -- since the
    fuzzy-match comparand is diluted the same way the search query is.

    Verified by comparing the actual resolved `match_score` against what
    `score_result` would produce for the stripped vs. unstripped query:
    the trailing "(2010)" in the raw, unstripped query measurably lowers
    the fuzzy title-similarity term against a bare TMDB title, so the two
    scores differ, and the resolved score must match the stripped one.
    """
    from reel2movie.tmdb.scoring import score_result

    result = _search_result(title="Inception", year=2010, original_rank=0)
    client = FakeTMDBClient([result])

    resolved = resolve_candidate(_candidate("Inception (2010)"), client)

    assert resolved is not None
    stripped_score = score_result("Inception", 2010, result)
    unstripped_score = score_result("Inception (2010)", 2010, result)
    assert stripped_score != unstripped_score
    assert resolved.match_score == stripped_score
