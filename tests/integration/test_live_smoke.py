"""One live, end-to-end smoke test for the real `reel2movie` CLI.

Deliberately NOT run as part of the normal unit suite (`tests/unit`) and
skipped by default even when collected directly, because it needs things
this sandbox does not have:

- Real `TMDB_API_KEY` / `ANTHROPIC_API_KEY` credentials (see `.env.example`).
- A real `INSTAGRAM_COOKIES_FILE` (per `config.get_instagram_cookies_file()`)
  for authenticated Instagram access via `yt-dlp`.
- Actual network access to Instagram + TMDB + the Anthropic API.
- A real, currently-reachable Instagram Reel URL.

To run this for real, once the above are set up:

    export TMDB_API_KEY=...
    export ANTHROPIC_API_KEY=...
    export INSTAGRAM_COOKIES_FILE=/path/to/cookies.txt
    export REEL2MOVIE_LIVE_TEST_URL="https://www.instagram.com/reel/<id>/"
    python3 -m pytest tests/integration -q

Without `REEL2MOVIE_LIVE_TEST_URL` set, this test is skipped (not silently
passed) -- the `skipif` reason makes that explicit in pytest's output.
"""

from __future__ import annotations

import json
import os

import pytest

from reel2movie.cli import main

_LIVE_URL = os.environ.get("REEL2MOVIE_LIVE_TEST_URL")


@pytest.mark.skipif(
    not _LIVE_URL,
    reason="set REEL2MOVIE_LIVE_TEST_URL and real API keys to run this live smoke test",
)
def test_live_pipeline_end_to_end(capsys):
    exit_code = main([_LIVE_URL])

    assert exit_code == 0

    captured = capsys.readouterr()
    assert captured.err == ""

    payload = json.loads(captured.out)
    assert payload["reel_url"] == _LIVE_URL
    assert "recommendations" in payload
    assert isinstance(payload["recommendations"], list)
