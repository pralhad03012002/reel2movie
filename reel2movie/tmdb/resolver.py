"""Ties the TMDB client + scoring together to resolve a single candidate."""

from __future__ import annotations

import re

from reel2movie.core.models import Candidate, ResolvedMovie
from reel2movie.core.protocols import TMDBClient
from reel2movie.tmdb.scoring import pick_best, score_result

_YEAR_IN_PARENS = re.compile(r"\((\d{4})\)")


def _extract_year_hint(raw_text: str) -> int | None:
    """Pull an obvious "(YYYY)" year out of candidate text, if present.

    A simple regex, not real date parsing — just enough to pass a year
    hint through to TMDB search / scoring when it's clearly spelled out.
    """
    match = _YEAR_IN_PARENS.search(raw_text)
    return int(match.group(1)) if match else None


def resolve_candidate(
    candidate: Candidate, client: TMDBClient
) -> ResolvedMovie | None:
    """Resolve a single candidate against TMDB, or None if nothing resolves.

    Signals "nothing resolved" only — per flow.md, it's the caller's (a
    later pipeline subtask's) job to decide whether to keep the candidate
    with `tmdb=None` rather than dropping it.
    """
    year_hint = _extract_year_hint(candidate.raw_text)
    results = client.search_movie(candidate.raw_text, year=year_hint)
    best = pick_best(candidate.raw_text, year_hint, results)
    if best is None:
        return None

    return ResolvedMovie(
        id=best.id,
        title=best.title,
        year=best.year,
        poster_path=best.poster_path,
        overview=best.overview,
        match_score=score_result(candidate.raw_text, year_hint, best),
    )
