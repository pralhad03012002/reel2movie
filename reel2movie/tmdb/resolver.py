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

    Uses the LAST "(YYYY)"-shaped match, not the first: `raw_text` is
    always built (by `text_extraction/regex_extractor.py`) as
    `f"{title} ({year})"`, with the real release year appended at the very
    end. If the title itself happens to contain its own parenthesized
    4-digit substring (e.g. a quoted title like "Experience Paris (1920)
    like never before" followed by the real trailing "(2023)"), searching
    from the left would wrongly pick up the title's own embedded year
    instead of the real one. Searching from the right is unambiguous.
    """
    matches = _YEAR_IN_PARENS.findall(raw_text)
    return int(matches[-1]) if matches else None


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
