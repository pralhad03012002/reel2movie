"""Tests for InstagramIngestor against a FakeYtDlpClient (no yt_dlp, no network).

FakeYtDlpClient implements the same call signature as
reel2movie.ingest.ytdlp_client.YtDlpClient but just returns canned dicts
and records how it was called, so these tests exercise InstagramIngestor's
own field-mapping logic in isolation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from reel2movie.core.models import Platform
from reel2movie.ingest.instagram import IngestError, InstagramIngestor

_FIXTURE_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "instagram_post_sample.json"


def _load_fixture() -> dict[str, Any]:
    with _FIXTURE_PATH.open() as f:
        return json.load(f)


class FakeYtDlpClient:
    """Test double standing in for YtDlpClient - no yt_dlp, no network."""

    def __init__(self, metadata_response=None, download_response=None):
        self.metadata_response = metadata_response
        self.download_response = download_response
        self.calls: list[dict[str, Any]] = []

    def extract_info(self, url, *, cookies_file=None, download=False):
        self.calls.append(
            {"url": url, "cookies_file": cookies_file, "download": download}
        )
        return self.download_response if download else self.metadata_response


def test_fetch_metadata_maps_caption_from_description():
    fixture = _load_fixture()
    client = FakeYtDlpClient(metadata_response=fixture)
    ingestor = InstagramIngestor(client)

    result = ingestor.fetch_metadata("https://www.instagram.com/reel/CxSampleReelId123/")

    assert result.caption == fixture["description"]


def test_fetch_metadata_maps_creator_account_id_from_uploader_id():
    fixture = _load_fixture()
    client = FakeYtDlpClient(metadata_response=fixture)
    ingestor = InstagramIngestor(client)

    result = ingestor.fetch_metadata("https://www.instagram.com/reel/x/")

    assert result.creator_account_id == "cinephile_creator"


def test_fetch_metadata_maps_duration_and_platform_and_url():
    fixture = _load_fixture()
    client = FakeYtDlpClient(metadata_response=fixture)
    ingestor = InstagramIngestor(client)

    url = "https://www.instagram.com/reel/CxSampleReelId123/"
    result = ingestor.fetch_metadata(url)

    assert result.duration_seconds == 42.5
    assert result.platform == Platform.INSTAGRAM
    assert result.url == url
    assert result.video_path is None


def test_fetch_metadata_maps_comments_with_correct_author_id_and_text():
    fixture = _load_fixture()
    client = FakeYtDlpClient(metadata_response=fixture)
    ingestor = InstagramIngestor(client)

    result = ingestor.fetch_metadata("https://www.instagram.com/reel/x/")

    assert len(result.comments) == 3
    by_id = {c.id: c for c in result.comments}
    creator_comment = by_id["17895000000000001"]
    assert creator_comment.author_id == "cinephile_creator"
    assert creator_comment.text == "Forgot to mention - also check out Inception (2010)!"
    assert creator_comment.like_count == 54


def test_fetch_metadata_marks_top_level_comments_as_not_reply():
    fixture = _load_fixture()
    client = FakeYtDlpClient(metadata_response=fixture)
    ingestor = InstagramIngestor(client)

    result = ingestor.fetch_metadata("https://www.instagram.com/reel/x/")

    by_id = {c.id: c for c in result.comments}
    assert by_id["17895000000000001"].is_reply is False  # parent == "root"
    assert by_id["17895000000000002"].is_reply is False  # parent == "root"


def test_fetch_metadata_marks_reply_comment_as_is_reply():
    fixture = _load_fixture()
    client = FakeYtDlpClient(metadata_response=fixture)
    ingestor = InstagramIngestor(client)

    result = ingestor.fetch_metadata("https://www.instagram.com/reel/x/")

    by_id = {c.id: c for c in result.comments}
    reply = by_id["17895000000000003"]
    assert reply.is_reply is True  # parent == "17895000000000002", not "root"


def test_fetch_metadata_treats_missing_parent_as_top_level():
    fixture = _load_fixture()
    fixture = dict(fixture)
    fixture["comments"] = [
        {"id": "1", "author_id": "someone", "text": "hi", "like_count": None}
    ]
    client = FakeYtDlpClient(metadata_response=fixture)
    ingestor = InstagramIngestor(client)

    result = ingestor.fetch_metadata("https://www.instagram.com/reel/x/")

    assert result.comments[0].is_reply is False


def test_fetch_metadata_like_count_none_when_absent():
    fixture = dict(_load_fixture())
    fixture["comments"] = [
        {"id": "1", "author_id": "someone", "text": "hi", "parent": "root"}
    ]
    client = FakeYtDlpClient(metadata_response=fixture)
    ingestor = InstagramIngestor(client)

    result = ingestor.fetch_metadata("https://www.instagram.com/reel/x/")

    assert result.comments[0].like_count is None


def test_fetch_metadata_raises_ingest_error_when_uploader_id_missing():
    fixture = dict(_load_fixture())
    del fixture["uploader_id"]
    client = FakeYtDlpClient(metadata_response=fixture)
    ingestor = InstagramIngestor(client)

    with pytest.raises(IngestError, match="uploader_id"):
        ingestor.fetch_metadata("https://www.instagram.com/reel/x/")


def test_fetch_metadata_raises_ingest_error_when_comment_missing_author_id():
    fixture = dict(_load_fixture())
    fixture["comments"] = [{"id": "1", "text": "no author here", "parent": "root"}]
    client = FakeYtDlpClient(metadata_response=fixture)
    ingestor = InstagramIngestor(client)

    with pytest.raises(IngestError, match="author_id"):
        ingestor.fetch_metadata("https://www.instagram.com/reel/x/")


def test_fetch_metadata_passes_cookies_file_through_to_client():
    fixture = _load_fixture()
    client = FakeYtDlpClient(metadata_response=fixture)
    cookies_path = Path("/fake/cookies.txt")
    ingestor = InstagramIngestor(client, cookies_file=cookies_path)

    ingestor.fetch_metadata("https://www.instagram.com/reel/x/")

    assert client.calls[0]["cookies_file"] == cookies_path
    assert client.calls[0]["download"] is False


def test_ensure_video_returns_path_from_requested_downloads_filepath():
    fixture = _load_fixture()
    client = FakeYtDlpClient(metadata_response=fixture)
    ingestor = InstagramIngestor(client)
    url = "https://www.instagram.com/reel/CxSampleReelId123/"
    result = ingestor.fetch_metadata(url)

    client.download_response = {
        **fixture,
        "requested_downloads": [{"filepath": "/tmp/downloads/reel123.mp4"}],
    }

    video_path = ingestor.ensure_video(result)

    assert video_path == Path("/tmp/downloads/reel123.mp4")
    assert client.calls[-1]["download"] is True
    assert client.calls[-1]["url"] == url


def test_ensure_video_falls_back_to_filename_key():
    fixture = _load_fixture()
    client = FakeYtDlpClient(metadata_response=fixture)
    ingestor = InstagramIngestor(client)
    result = ingestor.fetch_metadata("https://www.instagram.com/reel/x/")

    client.download_response = {**fixture, "_filename": "/tmp/downloads/other.mp4"}

    video_path = ingestor.ensure_video(result)

    assert video_path == Path("/tmp/downloads/other.mp4")


def test_ensure_video_raises_ingest_error_when_no_path_available():
    fixture = _load_fixture()
    client = FakeYtDlpClient(metadata_response=fixture)
    ingestor = InstagramIngestor(client)
    result = ingestor.fetch_metadata("https://www.instagram.com/reel/x/")

    client.download_response = {**fixture}  # no requested_downloads, no _filename

    with pytest.raises(IngestError, match="filepath"):
        ingestor.ensure_video(result)


def test_ensure_video_passes_cookies_file_through_to_client():
    fixture = _load_fixture()
    client = FakeYtDlpClient(metadata_response=fixture)
    cookies_path = Path("/fake/cookies.txt")
    ingestor = InstagramIngestor(client, cookies_file=cookies_path)
    result = ingestor.fetch_metadata("https://www.instagram.com/reel/x/")

    client.download_response = {
        **fixture,
        "requested_downloads": [{"filepath": "/tmp/x.mp4"}],
    }
    ingestor.ensure_video(result)

    assert client.calls[-1]["cookies_file"] == cookies_path
