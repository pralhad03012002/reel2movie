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
            "release_date": "1999-03-30",
            "poster_path": "/matrix.jpg",
            "overview": "A hacker learns the truth.",
            "popularity": 80.5,
        },
        {
            "id": 604,
            "title": "The Matrix Reloaded",
            "release_date": "",
            "poster_path": None,
            "overview": "The sequel.",
            "popularity": 40.1,
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
def test_search_movie_sets_bearer_auth_header(mock_get):
    mock_get.return_value = _mock_get_response({"results": []})
    client = TMDBHttpClient("my-token")

    client.search_movie("The Matrix")

    _, kwargs = mock_get.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer my-token"


@patch("reel2movie.tmdb.client.requests.get")
def test_search_movie_passes_query_param(mock_get):
    mock_get.return_value = _mock_get_response({"results": []})
    client = TMDBHttpClient("token")

    client.search_movie("The Matrix")

    _, kwargs = mock_get.call_args
    assert kwargs["params"]["query"] == "The Matrix"
    assert "year" not in kwargs["params"]


@patch("reel2movie.tmdb.client.requests.get")
def test_search_movie_passes_year_param_when_given(mock_get):
    mock_get.return_value = _mock_get_response({"results": []})
    client = TMDBHttpClient("token")

    client.search_movie("The Matrix", year=1999)

    _, kwargs = mock_get.call_args
    assert kwargs["params"]["year"] == 1999


@patch("reel2movie.tmdb.client.requests.get")
def test_search_movie_hits_search_movie_endpoint(mock_get):
    mock_get.return_value = _mock_get_response({"results": []})
    client = TMDBHttpClient("token")

    client.search_movie("The Matrix")

    args, _ = mock_get.call_args
    assert args[0] == "https://api.themoviedb.org/3/search/movie"


@patch("reel2movie.tmdb.client.requests.get")
def test_search_movie_maps_fields_and_rank(mock_get):
    mock_get.return_value = _mock_get_response(_CANNED_RESPONSE)
    client = TMDBHttpClient("token")

    results = client.search_movie("The Matrix")

    assert len(results) == 2

    first = results[0]
    assert first.id == 603
    assert first.title == "The Matrix"
    assert first.year == 1999
    assert first.poster_path == "/matrix.jpg"
    assert first.overview == "A hacker learns the truth."
    assert first.popularity == 80.5
    assert first.original_rank == 0

    second = results[1]
    assert second.id == 604
    assert second.original_rank == 1
    # empty release_date -> year is None, not an error
    assert second.year is None
    assert second.poster_path is None


@patch("reel2movie.tmdb.client.requests.get")
def test_search_movie_raises_on_http_error(mock_get):
    mock_get.return_value = _mock_get_response({}, status_ok=False)
    client = TMDBHttpClient("token")

    with pytest.raises(requests.HTTPError):
        client.search_movie("The Matrix")

    # A genuine HTTP error response is not a transient connection failure
    # and must not be retried.
    assert mock_get.call_count == 1


@patch("reel2movie.tmdb.client.time.sleep")
@patch("reel2movie.tmdb.client.requests.get")
def test_search_movie_retries_connection_error_then_succeeds(mock_get, mock_sleep):
    mock_get.side_effect = [
        requests.exceptions.ConnectionError("reset by peer"),
        requests.exceptions.ConnectionError("reset by peer"),
        _mock_get_response(_CANNED_RESPONSE),
    ]
    client = TMDBHttpClient("token")

    results = client.search_movie("The Matrix")

    assert len(results) == 2
    assert results[0].title == "The Matrix"
    assert mock_get.call_count == 3
    assert mock_sleep.call_args_list == [((0.5,),), ((1.0,),)]


@patch("reel2movie.tmdb.client.time.sleep")
@patch("reel2movie.tmdb.client.requests.get")
def test_search_movie_exhausts_retries_and_raises_connection_error(
    mock_get, mock_sleep
):
    mock_get.side_effect = requests.exceptions.ConnectionError("reset by peer")
    client = TMDBHttpClient("token")

    with pytest.raises(requests.exceptions.ConnectionError):
        client.search_movie("The Matrix")

    # Exactly 3 attempts total (not 2, not 4) — the retry budget is fixed.
    assert mock_get.call_count == 3
    assert mock_sleep.call_args_list == [((0.5,),), ((1.0,),)]


@patch("reel2movie.tmdb.client.time.sleep")
@patch("reel2movie.tmdb.client.requests.get")
def test_search_movie_retries_timeout_then_succeeds(mock_get, mock_sleep):
    mock_get.side_effect = [
        requests.exceptions.Timeout("timed out"),
        _mock_get_response(_CANNED_RESPONSE),
    ]
    client = TMDBHttpClient("token")

    results = client.search_movie("The Matrix")

    assert len(results) == 2
    assert mock_get.call_count == 2
    assert mock_sleep.call_args_list == [((0.5,),)]
