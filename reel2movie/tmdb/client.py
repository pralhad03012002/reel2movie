"""HTTP client for TMDB's `search/multi` endpoint.

Uses TMDB's v4 Bearer "API Read Access Token" auth style (per
vast-wobbling-owl.md's "TMDB auth style" decision), not the older v3
`api_key` query-param style.

Searches movies AND TV shows (see PROGRESS.md's "Follow-up" section for
why: a reel can recommend either, and resolving against `/search/movie`
alone let an unrelated movie win over the actually-correct TV show when
both happen to share a title). Verified live against the real TMDB API:
each `/search/multi` result row carries a `media_type` of `"movie"`,
`"tv"`, or `"person"`; movie rows use `title`/`release_date`, TV rows use
`name`/`first_air_date`. `person` rows are filtered out entirely -- a
person is never a valid recommendation target.
"""

from __future__ import annotations

import time

import requests

from reel2movie.core.models import TMDBSearchResult

_SEARCH_MULTI_URL = "https://api.themoviedb.org/3/search/multi"

# Retry budget for transient connection-level failures only (confirmed via
# real-world testing: TLS handshake resets against the real TMDB API,
# roughly 40-60% failure rate observed, resolving within a retry or two).
# Kept small and fast since this is a human-facing CLI call, not a
# background batch job — 3 total attempts, backing off 0.5s then 1s between
# them (so worst case adds 1.5s, not tens of seconds).
_MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = [0.5, 1.0]


def _parse_year(release_date: str | None) -> int | None:
    """Extract just the year out of a TMDB `release_date` string.

    `release_date` is a full date string (e.g. "1999-03-31") or an empty
    string when TMDB has no release date on file. Returns None if missing
    or unparseable rather than raising.
    """
    if not release_date:
        return None
    year_part = release_date.split("-", 1)[0]
    try:
        return int(year_part)
    except ValueError:
        return None


class TMDBHttpClient:
    """Real TMDB client, structurally satisfying the `TMDBClient` Protocol.

    Takes a bearer token directly; does not call `config.get_tmdb_token()`
    itself, so it stays constructible with any token string for testing.
    """

    def __init__(self, bearer_token: str) -> None:
        self._bearer_token = bearer_token

    def search(
        self, query: str, year: int | None = None
    ) -> list[TMDBSearchResult]:
        """Search TMDB movies AND TV shows via `/search/multi`.

        `person` rows are filtered out (not valid recommendation targets).
        Each remaining row is normalized into `TMDBSearchResult`: `title`
        comes from `title` (movie rows) or `name` (tv rows); `year` is
        parsed from `release_date` (movie) or `first_air_date` (tv), via
        the same `_parse_year` logic either way.

        Raises on HTTP errors via `response.raise_for_status()` rather than
        swallowing them; it's the caller's job to decide how to handle
        failures. HTTP errors (`requests.exceptions.HTTPError`, e.g. a real
        4xx/5xx response) are NOT retried here — a real API-level response
        indicates an actual problem (bad auth, bad request, server error),
        not a transient connection issue, so retrying would risk masking a
        real bug or hammering a server that's deliberately erroring.

        Connection-level transient failures (`requests.exceptions.
        ConnectionError`, `requests.exceptions.Timeout` — e.g. a TLS
        handshake reset, which is what's actually been observed against the
        real TMDB API) ARE retried, up to `_MAX_ATTEMPTS` total attempts
        with a short exponential backoff between them. If every attempt is
        exhausted, the final exception is raised as before — the caller
        (`tmdb/resolver.py`'s `resolve_candidate`, via `pipeline/
        waterfall.py`'s `_resolve_all`) already catches and logs this
        per-candidate.

        Note (confirmed live against the real API): unlike `/search/movie`,
        `/search/multi` does NOT support a `year` filter at all — passing
        `year` is silently ignored server-side (identical `total_results`
        and ordering with `year=1999` vs. an impossible `year=2199` against
        the same query, verified during this change). `year` is still sent
        here (harmless) and, more importantly, still passed straight
        through to `scoring.py`'s `year_bonus` term client-side — that's
        where year-based disambiguation now actually happens.
        """
        params: dict[str, str | int] = {"query": query}
        if year is not None:
            params["year"] = year

        for attempt in range(_MAX_ATTEMPTS):
            try:
                response = requests.get(
                    _SEARCH_MULTI_URL,
                    headers={"Authorization": f"Bearer {self._bearer_token}"},
                    params=params,
                    timeout=10,
                )
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
                if attempt == _MAX_ATTEMPTS - 1:
                    raise
                time.sleep(_BACKOFF_SECONDS[attempt])
                continue
            break

        response.raise_for_status()
        payload = response.json()

        results = []
        rank = 0
        for item in payload.get("results", []):
            media_type = item.get("media_type")
            if media_type == "person":
                continue
            if media_type == "tv":
                title = item["name"]
                date_field = item.get("first_air_date")
            else:
                title = item["title"]
                date_field = item.get("release_date")
            results.append(
                TMDBSearchResult(
                    id=item["id"],
                    title=title,
                    year=_parse_year(date_field),
                    poster_path=item.get("poster_path"),
                    overview=item.get("overview", ""),
                    popularity=item.get("popularity", 0.0),
                    original_rank=rank,
                    media_type=media_type,
                )
            )
            rank += 1

        return results
