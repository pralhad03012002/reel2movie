"""Thin wrapper around ``yt_dlp.YoutubeDL``.

This is the ONLY module in reel2movie that imports ``yt_dlp`` directly.
Callers (e.g. ``ingest/instagram.py``) depend on this wrapper's interface
rather than on yt-dlp's own internals, so they can be tested against a
fake implementing the same method signature without mocking a
third-party library's internals.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yt_dlp


class YtDlpClient:
    """Configures and invokes ``yt_dlp.YoutubeDL.extract_info``."""

    def extract_info(
        self,
        url: str,
        *,
        cookies_file: Path | None = None,
        download: bool = False,
    ) -> dict[str, Any]:
        """Run yt-dlp against ``url`` and return its raw info dict.

        Always requests comments (``getcomments: True``) since both the
        caption and the creator's own comment are candidate-extraction
        sources per the pipeline's waterfall. The video file itself is
        only downloaded when ``download=True`` (``skip_download`` is set
        to the inverse of ``download``) — metadata-only calls should
        never pay for a video download.
        """
        opts: dict[str, Any] = {
            "getcomments": True,
            "skip_download": not download,
            "quiet": True,
            "no_warnings": True,
        }
        if cookies_file is not None:
            opts["cookiefile"] = str(cookies_file)

        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=download)
