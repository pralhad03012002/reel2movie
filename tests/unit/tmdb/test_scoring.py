"""Pure function tests for tmdb/scoring.py — no IO, no mocking needed."""

from __future__ import annotations

from reel2movie.core.models import TMDBSearchResult
from reel2movie.tmdb.scoring import (
    MIN_MATCH_SCORE,
    find_exact_matches,
    pick_best,
    score_result,
)


def _result(**overrides) -> TMDBSearchResult:
    defaults = dict(
        id=1,
        title="The Matrix",
        year=1999,
        poster_path="/matrix.jpg",
        overview="A hacker learns the truth.",
        popularity=80.0,
        original_rank=0,
        media_type="movie",
    )
    defaults.update(overrides)
    return TMDBSearchResult(**defaults)


def test_exact_title_match_scores_highest():
    exact = _result(title="The Matrix", original_rank=0, year=None)
    loose = _result(title="The Matrix Reloaded Collection", original_rank=0, year=None)

    exact_score = score_result("The Matrix", None, exact)
    loose_score = score_result("The Matrix", None, loose)

    assert exact_score > loose_score


def test_year_match_boosts_score():
    without_year_hint = _result(title="The Matrix", year=1999, original_rank=0)
    with_year_hint = _result(title="The Matrix", year=1999, original_rank=0)

    score_no_hint = score_result("The Matrix", None, without_year_hint)
    score_with_hint = score_result("The Matrix", 1999, with_year_hint)

    assert score_with_hint > score_no_hint


def test_wrong_year_does_not_get_year_bonus():
    result = _result(title="The Matrix", year=2003, original_rank=0)

    score_matching_year_hint = score_result("The Matrix", 1999, result)
    score_no_hint = score_result("The Matrix", None, result)

    assert score_matching_year_hint == score_no_hint


def test_lower_rank_bonus_for_later_results():
    first_ranked = _result(title="The Matrix", original_rank=0)
    tenth_ranked = _result(title="The Matrix", original_rank=9)

    assert score_result("The Matrix", None, first_ranked) > score_result(
        "The Matrix", None, tenth_ranked
    )


def test_pick_best_returns_none_on_empty_results():
    assert pick_best("The Matrix", None, []) is None


def test_pick_best_returns_none_when_all_low_confidence():
    results = [
        _result(title="Completely Unrelated Documentary", original_rank=5, year=None),
        _result(title="Nothing Like It", original_rank=9, year=None),
    ]

    assert pick_best("The Matrix", None, results) is None


def test_pick_best_returns_argmax_result():
    best = _result(title="The Matrix", original_rank=0, year=1999)
    worse = _result(title="The Matrix Reloaded", original_rank=1, year=2003)

    assert pick_best("The Matrix", 1999, [worse, best]) is best


def test_min_match_score_is_a_float_between_zero_and_one():
    assert 0.0 < MIN_MATCH_SCORE < 1.0


def test_pick_best_prefers_exact_match_over_popular_partial_match():
    """The real-world regression: "Triangle" (2009) vs "Triangle of Sadness"
    (2022) — a popular partial match must not beat the true exact match,
    even though TMDB itself ranks the partial match first."""
    triangle_of_sadness = _result(
        id=882598,
        title="Triangle of Sadness",
        year=2022,
        popularity=120.0,
        original_rank=0,
    )
    triangle = _result(
        id=26466,
        title="Triangle",
        year=2009,
        popularity=15.0,
        original_rank=1,
    )

    result = pick_best("Triangle", None, [triangle_of_sadness, triangle])

    assert result is triangle


def test_pick_best_falls_back_to_fuzzy_scoring_when_no_exact_match_exists():
    """No candidate is a true exact match -- behavior is unchanged from the
    pre-tiered formula: the best fuzzy-scored result still wins."""
    close = _result(title="The Matrix Reloaded", original_rank=0, year=2003)
    far = _result(title="Completely Unrelated Documentary", original_rank=5, year=None)

    result = pick_best("The Matrix", None, [close, far])

    assert result is close


def test_pick_best_among_exact_matches_uses_year_hint_as_tiebreaker():
    """Two different movies share the exact title "Triangle" in different
    years, tied on TMDB rank -- year_hint must still pick the right one
    among exact matches."""
    triangle_2009 = _result(
        id=26466, title="Triangle", year=2009, original_rank=1, popularity=15.0
    )
    triangle_1994 = _result(
        id=999999, title="Triangle", year=1994, original_rank=1, popularity=15.0
    )

    result = pick_best("Triangle", 2009, [triangle_1994, triangle_2009])

    assert result is triangle_2009


def test_pick_best_exact_match_wins_despite_huge_popularity_gap():
    """Direct proof that name matching beats popularity categorically: the
    non-exact result has a much stronger rank_bonus (original_rank=0, i.e.
    TMDB's own top pick) than the exact match (original_rank=9), yet the
    exact match must still be chosen."""
    non_exact_top_ranked = _result(
        title="Triangle of Sadness", year=2022, original_rank=0, popularity=500.0
    )
    exact_low_ranked = _result(
        title="Triangle", year=2009, original_rank=9, popularity=1.0
    )

    result = pick_best("Triangle", None, [non_exact_top_ranked, exact_low_ranked])

    assert result is exact_low_ranked


def test_pick_best_exact_match_is_case_and_whitespace_insensitive():
    lowercase_query_match = _result(title="The Matrix", original_rank=0, year=1999)
    other = _result(title="The Matrix Reloaded", original_rank=0, year=2003)

    result = pick_best("the matrix", None, [other, lowercase_query_match])

    assert result is lowercase_query_match

    padded_query_match = _result(title="Inception", original_rank=5, year=2010)
    other2 = _result(title="Inception: The Cobol Job", original_rank=0, year=2010)

    result2 = pick_best(" Inception ", None, [other2, padded_query_match])

    assert result2 is padded_query_match


def test_pick_best_exact_match_not_penalized_by_case_sensitive_wratio():
    """Regression: an exact (case-insensitive) match must never be rejected
    by MIN_MATCH_SCORE, or lose a tiebreak, purely because `fuzz.WRatio` is
    case-sensitive (`fuzz.WRatio("UP", "Up") == 50.0`, not 100). Before the
    fix, `pick_best("UP", None, [up_all_night, up])` returned None, because
    `up`'s own exact-tier score was computed via `score_result` (case-
    sensitive) and fell below `MIN_MATCH_SCORE` -- discarding the real
    exact match entirely instead of picking it."""
    up = _result(id=1, title="Up", year=2009, popularity=50.0, original_rank=3)
    up_all_night = _result(
        id=2, title="Up All Night", year=2011, popularity=90.0, original_rank=0
    )

    result = pick_best("UP", None, [up_all_night, up])

    assert result is not None
    assert result is up
    assert result.title == "Up"


def test_find_exact_matches_returns_all_tied_exact_matches_in_order():
    """Regression for the real "Don't Be Shy" disambiguation case: TMDB can
    return several DIFFERENT entries that all exactly match the query --
    `find_exact_matches` must return the whole tied group (for a caller
    like the disambiguation step to pick among), not just one winner."""
    exact_a = _result(id=1, title="Don't Be Shy", original_rank=0)
    exact_b = _result(id=2, title="DON'T BE SHY", original_rank=3)
    not_exact = _result(id=3, title="Don't Be Shy!", original_rank=1)
    not_a_match = _result(id=4, title="Keine Scheu vor heiklen Fragen", original_rank=2)

    result = find_exact_matches("Don't Be Shy", [exact_a, not_exact, not_a_match, exact_b])

    assert result == [exact_a, exact_b]


def test_find_exact_matches_returns_empty_list_when_none_match():
    results = [_result(title="Completely Unrelated Thing", original_rank=0)]

    assert find_exact_matches("The Matrix", results) == []


def test_find_exact_matches_normalizes_curly_apostrophe_against_straight():
    """Regression for the real "Don't Be Shy" bug: live TMDB data for this
    exact title included rows using a Unicode right single quotation mark
    (U+2019, "Don’t Be Shy") instead of a straight apostrophe
    (U+0027), while the real extracted candidate text always uses the
    straight form. Without normalizing both to one form first, the curly
    variant would be silently excluded from the exact-match tier."""
    straight = _result(id=1, title="Don't Be Shy", original_rank=0)
    curly = _result(id=2, title="Don’t Be Shy", original_rank=1)

    result = find_exact_matches("Don't Be Shy", [straight, curly])

    assert result == [straight, curly]


def test_find_exact_matches_normalizes_left_curly_apostrophe_too():
    left_curly = _result(id=1, title="Don‘t Be Shy", original_rank=0)

    result = find_exact_matches("Don't Be Shy", [left_curly])

    assert result == [left_curly]


def test_pick_best_uses_find_exact_matches_internally_for_curly_apostrophe():
    """`pick_best()` itself must benefit from the same normalization --
    not just the newly-extracted `find_exact_matches()` helper."""
    curly = _result(id=1, title="Don’t Be Shy", original_rank=0, popularity=1.0)
    unrelated_popular = _result(
        id=2, title="Something Else Entirely", original_rank=0, popularity=500.0
    )

    result = pick_best("Don't Be Shy", None, [unrelated_popular, curly])

    assert result is curly
