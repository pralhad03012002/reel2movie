"""Tests for YtDlpClient with yt_dlp.YoutubeDL itself faked out.

These tests never construct a real YoutubeDL (which would try to touch
the network) - `yt_dlp.YoutubeDL` is patched at the point `ytdlp_client`
imports it, and the fake records how it was constructed/called so we can
assert on the options dict and arguments without any real yt-dlp or
network behavior.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from reel2movie.ingest.ytdlp_client import YtDlpClient


def _patched_youtubedl(canned_info: dict):
    """Return a MagicMock standing in for the yt_dlp.YoutubeDL class.

    Configured so `with YoutubeDL(opts) as ydl: ydl.extract_info(...)`
    works, and `ydl.extract_info(...)` returns `canned_info`.
    """
    mock_class = MagicMock(name="YoutubeDL_class")
    mock_instance = mock_class.return_value
    mock_instance.__enter__.return_value = mock_instance
    mock_instance.__exit__.return_value = False
    mock_instance.extract_info.return_value = canned_info
    return mock_class


def test_extract_info_sets_getcomments_and_skip_download_when_not_downloading():
    canned = {"id": "abc"}
    mock_class = _patched_youtubedl(canned)

    with patch("reel2movie.ingest.ytdlp_client.yt_dlp.YoutubeDL", mock_class):
        result = YtDlpClient().extract_info("https://example.com/reel/1", download=False)

    assert result == canned
    (opts,), _ = mock_class.call_args
    assert opts["getcomments"] is True
    assert opts["skip_download"] is True
    assert "cookiefile" not in opts


def test_extract_info_sets_skip_download_false_when_downloading():
    mock_class = _patched_youtubedl({"id": "abc"})

    with patch("reel2movie.ingest.ytdlp_client.yt_dlp.YoutubeDL", mock_class):
        YtDlpClient().extract_info("https://example.com/reel/1", download=True)

    (opts,), _ = mock_class.call_args
    assert opts["getcomments"] is True
    assert opts["skip_download"] is False


def test_extract_info_passes_cookies_file_when_given():
    mock_class = _patched_youtubedl({"id": "abc"})
    cookies_path = Path("/fake/cookies.txt")

    with patch("reel2movie.ingest.ytdlp_client.yt_dlp.YoutubeDL", mock_class):
        YtDlpClient().extract_info(
            "https://example.com/reel/1", cookies_file=cookies_path, download=False
        )

    (opts,), _ = mock_class.call_args
    assert opts["cookiefile"] == str(cookies_path)


def test_extract_info_omits_cookies_file_when_none():
    mock_class = _patched_youtubedl({"id": "abc"})

    with patch("reel2movie.ingest.ytdlp_client.yt_dlp.YoutubeDL", mock_class):
        YtDlpClient().extract_info("https://example.com/reel/1", cookies_file=None)

    (opts,), _ = mock_class.call_args
    assert "cookiefile" not in opts


def test_extract_info_calls_download_with_url_and_download_flag():
    mock_class = _patched_youtubedl({"id": "abc"})
    mock_instance = mock_class.return_value

    with patch("reel2movie.ingest.ytdlp_client.yt_dlp.YoutubeDL", mock_class):
        YtDlpClient().extract_info("https://example.com/reel/1", download=True)

    mock_instance.extract_info.assert_called_once_with(
        "https://example.com/reel/1", download=True
    )


def test_extract_info_returns_the_raw_dict_yt_dlp_produces():
    canned = {"id": "abc", "description": "hello", "comments": []}
    mock_class = _patched_youtubedl(canned)

    with patch("reel2movie.ingest.ytdlp_client.yt_dlp.YoutubeDL", mock_class):
        result = YtDlpClient().extract_info("https://example.com/reel/1")

    assert result is canned
