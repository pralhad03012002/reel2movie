"""Scoring TMDB search results against a candidate query.

Combines TMDB's own relevance ordering with a title-similarity check (per
brainstorm.md: "a near-exact title hit outranks a loosely related result
TMDB returns first").
"""

from __future__ import annotations

from rapidfuzz import fuzz

from reel2movie.core.models import TMDBSearchResult

# Below this score, treat it as "no confident match" rather than guessing.
# A reasonable floor, not derived from any real data.
MIN_MATCH_SCORE = 0.5


def score_result(
    query: str, year_hint: int | None, result: TMDBSearchResult
) -> float:
    """Score one TMDB search result against a query (+ optional year hint).

    `0.65 * title_similarity + 0.25 * rank_bonus + 0.10 * year_bonus`.
    """
    title_similarity = fuzz.WRatio(query, result.title) / 100
    rank_bonus = 1 / (1 + result.original_rank)
    year_bonus = 1.0 if year_hint and result.year == year_hint else 0.0
    return 0.65 * title_similarity + 0.25 * rank_bonus + 0.10 * year_bonus


def pick_best(
    query: str, year_hint: int | None, results: list[TMDBSearchResult]
) -> TMDBSearchResult | None:
    """Return the best-scoring result, or None if nothing clears the bar."""
    if not results:
        return None

    best = max(results, key=lambda result: score_result(query, year_hint, result))
    if score_result(query, year_hint, best) < MIN_MATCH_SCORE:
        return None
    return best
