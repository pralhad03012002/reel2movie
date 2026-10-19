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


def _is_exact_title_match(query: str, title: str) -> bool:
    """True if `title` is a strict (case/whitespace-insensitive) match for `query`.

    Deliberately NOT fuzzy/partial — this is a normalized equality check,
    not a similarity score. `fuzz.WRatio` (used in `score_result`) scores a
    short query as a near-perfect match against a longer title that merely
    *contains* it as a substring (e.g. "Triangle" vs "Triangle of Sadness"),
    which is exactly the confusion this function exists to avoid.
    """
    return query.strip().casefold() == title.strip().casefold()


def _exact_tier_rank(result: TMDBSearchResult, year_hint: int | None) -> float:
    """Rank a result that's already known to be an exact title match.

    `title_similarity` is deliberately skipped here, not recomputed via
    `score_result`: within the exact-match tier it's a perfect conceptual
    match by definition (that's what "exact" means), so there's nothing
    for it to contribute, and `score_result`'s `fuzz.WRatio`-based
    `title_similarity` term is case-sensitive, which would otherwise let a
    casing difference (e.g. query "UP" vs title "Up") wrongly cost an
    exact match the tiebreak or the `MIN_MATCH_SCORE` floor (neither of
    which should ever apply to a confirmed exact match). Same 0.25/0.10
    weights as `score_result`, just without the inapplicable 0.65 term.
    """
    rank_bonus = 1 / (1 + result.original_rank)
    year_bonus = 1.0 if year_hint and result.year == year_hint else 0.0
    return 0.25 * rank_bonus + 0.10 * year_bonus


def pick_best(
    query: str, year_hint: int | None, results: list[TMDBSearchResult]
) -> TMDBSearchResult | None:
    """Return the best-matching result, or None if nothing clears the bar.

    Tiered selection: name matching categorically outranks popularity,
    per brainstorm.md. A query like "Triangle" must resolve to the movie
    literally titled "Triangle", never to "Triangle of Sadness" just
    because TMDB's popularity-driven ranking (and `score_result`'s
    `rank_bonus` term) favors the latter.

    1. If any result's title is a true exact match (`_is_exact_title_match`),
       the pick comes from ONLY that group — a fuzzy/partial match can
       never win once a real exact match exists, no matter how popular or
       highly ranked it is. Ties within this group are broken by
       `_exact_tier_rank` (`rank_bonus`/`year_bonus` only — e.g. two
       different movies both exactly titled "Triangle" in different
       years: `year_hint` picks the right one; TMDB's own rank is the
       secondary tiebreaker among genuine ties). `MIN_MATCH_SCORE` does
       NOT apply within this tier — an exact title match is never
       rejected for "not matching enough".
    2. Otherwise (no exact match at all), fall back to the original
       behavior: score every result with `score_result` and take the
       best, subject to the `MIN_MATCH_SCORE` floor — unchanged.
    """
    if not results:
        return None

    exact_matches = [r for r in results if _is_exact_title_match(query, r.title)]
    if exact_matches:
        return max(exact_matches, key=lambda r: _exact_tier_rank(r, year_hint))

    best = max(results, key=lambda result: score_result(query, year_hint, result))
    if score_result(query, year_hint, best) < MIN_MATCH_SCORE:
        return None
    return best
