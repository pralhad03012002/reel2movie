"""HTTP client for TMDB's `search/movie` endpoint.

Uses TMDB's v4 Bearer "API Read Access Token" auth style (per
vast-wobbling-owl.md's "TMDB auth style" decision), not the older v3
`api_key` query-param style.
"""

from __future__ import annotations

import requests

from reel2movie.core.models import TMDBSearchResult

_SEARCH_MOVIE_URL = "https://api.themoviedb.org/3/search/movie"


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

    def search_movie(
        self, query: str, year: int | None = None
    ) -> list[TMDBSearchResult]:
        """Search TMDB movies (movies only — TV is out of scope).

        Raises on HTTP errors via `response.raise_for_status()` rather than
        swallowing them; it's the caller's job to decide how to handle
        failures.
        """
        params: dict[str, str | int] = {"query": query}
        if year is not None:
            params["year"] = year

        response = requests.get(
            _SEARCH_MOVIE_URL,
            headers={"Authorization": f"Bearer {self._bearer_token}"},
            params=params,
        )
        response.raise_for_status()
        payload = response.json()

        return [
            TMDBSearchResult(
                id=item["id"],
                title=item["title"],
                year=_parse_year(item.get("release_date")),
                poster_path=item.get("poster_path"),
                overview=item.get("overview", ""),
                popularity=item.get("popularity", 0.0),
                original_rank=rank,
            )
            for rank, item in enumerate(payload.get("results", []))
        ]
