"""Tests for TMDBHttpClient. No live network calls — requests.get is mocked."""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
import requests

from reel2movie.tmdb.client import TMDBHttpClient

_CANNED_RESPONSE = {
    "results": [
        {
            "id": 603,
            "title": "The Matrix",
            "media_type": "movie",
            "release_date": "1999-03-30",
            "poster_path": "/matrix.jpg",
            "overview": "A hacker learns the truth.",
            "popularity": 80.5,
        },
        {
            "id": 604,
            "title": "The Matrix Reloaded",
            "media_type": "movie",
            "release_date": "",
            "poster_path": None,
            "overview": "The sequel.",
            "popularity": 40.1,
        },
    ]
}

_MULTI_RESPONSE_WITH_MOVIE_TV_AND_PERSON = {
    "results": [
        {
            "id": 5920,
            "name": "The Mentalist",
            "media_type": "tv",
            "first_air_date": "2008-09-23",
            "poster_path": "/mentalist.jpg",
            "overview": "A former psychic medium solves crimes.",
            "popularity": 358.5,
        },
        {
            "id": 648544,
            "title": "The Mentalist",
            "media_type": "movie",
            "release_date": "2011-11-10",
            "poster_path": "/mentalist-id.jpg",
            "overview": "Two mentalists compete.",
            "popularity": 1.2,
        },
        {
            "id": 31,
            "name": "Tom Hanks",
            "media_type": "person",
            "popularity": 14.3,
            # person rows have no title/release_date/name-as-title shape at all
        },
    ]
}


def _mock_get_response(json_payload: dict, status_ok: bool = True) -> Mock:
    response = Mock()
    response.json.return_value = json_payload
    if status_ok:
        response.raise_for_status.return_value = None
    else:
        response.raise_for_status.side_effect = requests.HTTPError("boom")
    return response


@patch("reel2movie.tmdb.client.requests.get")
def test_search_sets_bearer_auth_header(mock_get):
    mock_get.return_value = _mock_get_response({"results": []})
    client = TMDBHttpClient("my-token")

    client.search("The Matrix")

    _, kwargs = mock_get.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer my-token"


@patch("reel2movie.tmdb.client.requests.get")
def test_search_passes_query_param(mock_get):
    mock_get.return_value = _mock_get_response({"results": []})
    client = TMDBHttpClient("token")

    client.search("The Matrix")

    _, kwargs = mock_get.call_args
    assert kwargs["params"]["query"] == "The Matrix"
    assert "year" not in kwargs["params"]


@patch("reel2movie.tmdb.client.requests.get")
def test_search_passes_year_param_when_given(mock_get):
    mock_get.return_value = _mock_get_response({"results": []})
    client = TMDBHttpClient("token")

    client.search("The Matrix", year=1999)

    _, kwargs = mock_get.call_args
    assert kwargs["params"]["year"] == 1999


@patch("reel2movie.tmdb.client.requests.get")
def test_search_hits_search_multi_endpoint(mock_get):
    mock_get.return_value = _mock_get_response({"results": []})
    client = TMDBHttpClient("token")

    client.search("The Matrix")

    args, _ = mock_get.call_args
    assert args[0] == "https://api.themoviedb.org/3/search/multi"


@patch("reel2movie.tmdb.client.requests.get")
def test_search_maps_fields_and_rank(mock_get):
    mock_get.return_value = _mock_get_response(_CANNED_RESPONSE)
    client = TMDBHttpClient("token")

    results = client.search("The Matrix")

    assert len(results) == 2

    first = results[0]
    assert first.id == 603
    assert first.title == "The Matrix"
    assert first.year == 1999
    assert first.poster_path == "/matrix.jpg"
    assert first.overview == "A hacker learns the truth."
    assert first.popularity == 80.5
    assert first.original_rank == 0
    assert first.media_type == "movie"

    second = results[1]
    assert second.id == 604
    assert second.original_rank == 1
    # empty release_date -> year is None, not an error
    assert second.year is None
    assert second.poster_path is None


@patch("reel2movie.tmdb.client.requests.get")
def test_search_filters_out_person_and_maps_movie_and_tv_distinctly(mock_get):
    """Regression for the real "The Mentalist" bug: a `/search/multi`
    response with a movie, a tv show, AND a person must filter the person
    out entirely, and map the tv show's `name`/`first_air_date` to
    `title`/`year` with `media_type="tv"`, while the movie's
    `title`/`release_date` still map correctly with `media_type="movie"`.
    """
    mock_get.return_value = _mock_get_response(_MULTI_RESPONSE_WITH_MOVIE_TV_AND_PERSON)
    client = TMDBHttpClient("token")

    results = client.search("The Mentalist")

    # The person (id=31, "Tom Hanks") must be filtered out entirely.
    assert len(results) == 2
    assert all(r.media_type != "person" for r in results)
    assert all(r.id != 31 for r in results)

    tv_result = next(r for r in results if r.media_type == "tv")
    assert tv_result.id == 5920
    assert tv_result.title == "The Mentalist"
    assert tv_result.year == 2008
    assert tv_result.original_rank == 0

    movie_result = next(r for r in results if r.media_type == "movie")
    assert movie_result.id == 648544
    assert movie_result.title == "The Mentalist"
    assert movie_result.year == 2011
    # The movie is ranked second in the raw payload, but ranks right after
    # the tv result once the person row (also ranked lower, between them
    # in index but filtered) is excluded -- sequential rank over the
    # KEPT rows, not the raw payload index.
    assert movie_result.original_rank == 1


@patch("reel2movie.tmdb.client.requests.get")
def test_search_raises_on_http_error(mock_get):
    mock_get.return_value = _mock_get_response({}, status_ok=False)
    client = TMDBHttpClient("token")

    with pytest.raises(requests.HTTPError):
        client.search("The Matrix")

    # A genuine HTTP error response is not a transient connection failure
    # and must not be retried.
    assert mock_get.call_count == 1


@patch("reel2movie.tmdb.client.time.sleep")
@patch("reel2movie.tmdb.client.requests.get")
def test_search_retries_connection_error_then_succeeds(mock_get, mock_sleep):
    mock_get.side_effect = [
        requests.exceptions.ConnectionError("reset by peer"),
        requests.exceptions.ConnectionError("reset by peer"),
        _mock_get_response(_CANNED_RESPONSE),
    ]
    client = TMDBHttpClient("token")

    results = client.search("The Matrix")

    assert len(results) == 2
    assert results[0].title == "The Matrix"
    assert mock_get.call_count == 3
    assert mock_sleep.call_args_list == [((0.5,),), ((1.0,),)]


@patch("reel2movie.tmdb.client.time.sleep")
@patch("reel2movie.tmdb.client.requests.get")
def test_search_exhausts_retries_and_raises_connection_error(
    mock_get, mock_sleep
):
    mock_get.side_effect = requests.exceptions.ConnectionError("reset by peer")
    client = TMDBHttpClient("token")

    with pytest.raises(requests.exceptions.ConnectionError):
        client.search("The Matrix")

    # Exactly 3 attempts total (not 2, not 4) — the retry budget is fixed.
    assert mock_get.call_count == 3
    assert mock_sleep.call_args_list == [((0.5,),), ((1.0,),)]


@patch("reel2movie.tmdb.client.time.sleep")
@patch("reel2movie.tmdb.client.requests.get")
def test_search_retries_timeout_then_succeeds(mock_get, mock_sleep):
    mock_get.side_effect = [
        requests.exceptions.Timeout("timed out"),
        _mock_get_response(_CANNED_RESPONSE),
    ]
    client = TMDBHttpClient("token")

    results = client.search("The Matrix")

    assert len(results) == 2
    assert mock_get.call_count == 2
    assert mock_sleep.call_args_list == [((0.5,),)]
