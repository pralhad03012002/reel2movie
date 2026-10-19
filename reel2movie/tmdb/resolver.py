"""Ties the TMDB client + scoring together to resolve a single candidate."""

from __future__ import annotations

import re

from reel2movie.core.models import Candidate, ResolvedMovie
from reel2movie.core.protocols import TMDBClient
from reel2movie.tmdb.scoring import pick_best, score_result

_YEAR_IN_PARENS = re.compile(r"\((\d{4})\)")
_TRAILING_YEAR_IN_PARENS = re.compile(r"\s*\((\d{4})\)\s*$")


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


def _strip_trailing_year(raw_text: str) -> str:
    """Remove a trailing "(YYYY)" from raw_text for use as the TMDB search
    query / fuzzy-match comparand.

    Confirmed against the live TMDB API: searching with a literal "(YYYY)"
    baked into the query can return ZERO results even when the bare title
    matches perfectly (e.g. "Dhobi Ghat (2010)" -> no results; "Dhobi Ghat"
    -> exact match). Only strips a year-in-parens anchored at the very end
    of the string (matching exactly how regex_extractor.py / the claude-CLI
    extractor build raw_text as f"{title} ({year})"), so a title containing
    its OWN embedded parenthetical year earlier in the string (not at the
    end) is left untouched -- same "trailing only" philosophy as
    _extract_year_hint()'s "search from the right" reasoning.

    Loops the substitution: a raw_text ending in TWO adjacent "(YYYY)"
    groups (e.g. a quoted title whose own text happens to end in a year,
    like 'Se7en (1995) (2015)' from a caption such as `Rewatching "Se7en
    (1995)" (2015) tonight`) would otherwise only have its outermost
    trailing year stripped, leaving a still trailing-year-shaped query
    ("Se7en (1995)") that reproduces the exact zero-result dilution bug
    this helper exists to fix. No-ops safely on a string with no trailing
    year match (first iteration's substitution changes nothing).

    Falls back to the original, unstripped `raw_text` if the loop would
    otherwise strip the string down to nothing. This is reachable, not
    just defensive: a candidate whose entire `raw_text` is made of
    chained "(YYYY)"-shaped groups with no other content (e.g. a quoted
    title that is itself just a year, like the real
    `RegexCandidateExtractor` output `'(1999) (2010)'` from a caption
    such as `Watch "(1999)" (2010) now`) loops all the way down to `""`.
    An empty TMDB search query is worse than the original dilution bug:
    it sends no title text at all, instead of merely a diluted one, so a
    non-empty (if imperfect) fallback query is strictly preferable to a
    blank one.
    """
    stripped = raw_text
    while True:
        new = _TRAILING_YEAR_IN_PARENS.sub("", stripped).strip()
        if new == stripped:
            break
        stripped = new
    return stripped or raw_text


def resolve_candidate(
    candidate: Candidate, client: TMDBClient
) -> ResolvedMovie | None:
    """Resolve a single candidate against TMDB, or None if nothing resolves.

    Signals "nothing resolved" only — per flow.md, it's the caller's (a
    later pipeline subtask's) job to decide whether to keep the candidate
    with `tmdb=None` rather than dropping it.
    """
    year_hint = _extract_year_hint(candidate.raw_text)
    query_title = _strip_trailing_year(candidate.raw_text)
    results = client.search(query_title, year=year_hint)
    best = pick_best(query_title, year_hint, results)
    if best is None:
        return None

    return ResolvedMovie(
        id=best.id,
        title=best.title,
        year=best.year,
        poster_path=best.poster_path,
        overview=best.overview,
        match_score=score_result(query_title, year_hint, best),
        media_type=best.media_type,
    )
