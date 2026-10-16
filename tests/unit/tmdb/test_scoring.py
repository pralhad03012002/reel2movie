"""Pure function tests for tmdb/scoring.py — no IO, no mocking needed."""

from __future__ import annotations

from reel2movie.core.models import TMDBSearchResult
from reel2movie.tmdb.scoring import MIN_MATCH_SCORE, pick_best, score_result


def _result(**overrides) -> TMDBSearchResult:
    defaults = dict(
        id=1,
        title="The Matrix",
        year=1999,
        poster_path="/matrix.jpg",
        overview="A hacker learns the truth.",
        popularity=80.0,
        original_rank=0,
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
