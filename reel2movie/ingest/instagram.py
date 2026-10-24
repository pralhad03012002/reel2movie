"""InstagramIngestor: an ``Ingestor`` Protocol implementation for Reels.

Built on top of ``YtDlpClient`` (dependency-injected, not imported
directly) so tests can supply a fake without touching ``yt_dlp`` or the
network. Does not call ``reel2movie.config.get_instagram_cookies_file()``
itself — the caller reads env config and passes the resulting path in,
same separation-of-concerns pattern ``tmdb/client.py`` uses for the TMDB
token.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from reel2movie.core.models import Comment, IngestResult, Platform
from reel2movie.ingest.ytdlp_client import YtDlpClient


class IngestError(RuntimeError):
    """Raised when yt-dlp's response is missing a field this module needs.

    Deliberately a plain ``RuntimeError`` subclass (no custom attributes)
    - callers that want to distinguish ingest failures from other
    ``RuntimeError``s can catch this type specifically; everyone else can
    treat it like any other runtime failure.
    """


class InstagramIngestor:
    """Fetches Reel metadata/video via a ``YtDlpClient``.

    Field-mapping assumptions made here (yt-dlp's Instagram extractor
    output is not verified against a live response in this sandbox - see
    PROGRESS.md Subtask 4 for the full list):

    - ``caption`` <- yt-dlp's normalized ``description`` key (not
      Instagram's own ``caption``/``edge_media_to_caption`` API field
      names - yt-dlp flattens those to ``description``).
    - ``creator_account_id`` <- ``uploader_id``.
    - Each comment's ``author_id`` <- ``author_id``, ``text`` <- ``text``.
    - ``is_reply`` <- derived from a ``parent`` field, using the
      YouTube-extractor convention (``parent == "root"`` for top-level,
      ``parent == <comment id>`` for a reply). This is an OPEN RISK per
      the plan: Instagram's yt-dlp extractor is not confirmed to populate
      ``parent`` reliably. A missing ``parent`` key is treated as
      top-level (the conservative assumption - a reply misclassified as
      top-level is a less harmful failure mode for this pipeline than the
      reverse, since the creator's-own-top-level-comment waterfall step
      specifically looks at top-level comments).
    """

    def __init__(self, client: YtDlpClient, *, cookies_file: Path | None = None) -> None:
        self._client = client
        self._cookies_file = cookies_file
        # Keyed by reel URL. Avoids re-downloading when `ensure_video()` is
        # called more than once for the same reel within this instance's
        # lifetime (e.g. a caller invoking it unconditionally/upfront
        # rather than lazily). Only successful downloads are cached -- a
        # failed attempt is not stored, so a retry after a failure (e.g.
        # transient network error) actually retries instead of re-raising
        # a cached failure. Process-local only: no TTL/eviction, no disk
        # persistence.
        self._video_cache: dict[str, Path] = {}

    def fetch_metadata(self, url: str) -> IngestResult:
        """Fetch caption/comments/duration/creator id without downloading video."""
        info = self._client.extract_info(
            url, cookies_file=self._cookies_file, download=False
        )

        uploader_id = info.get("uploader_id")
        if not uploader_id:
            raise IngestError(
                f"yt-dlp metadata response for {url!r} is missing "
                "'uploader_id'; cannot identify the reel's creator account."
            )

        comments = [self._to_comment(raw, url) for raw in info.get("comments") or []]

        return IngestResult(
            platform=Platform.INSTAGRAM,
            url=url,
            caption=info.get("description") or "",
            creator_account_id=uploader_id,
            comments=comments,
            duration_seconds=info.get("duration"),
            video_path=None,
        )

    @staticmethod
    def _to_comment(raw: dict[str, Any], url: str) -> Comment:
        comment_id = raw.get("id")
        author_id = raw.get("author_id")
        if comment_id is None or author_id is None:
            raise IngestError(
                f"yt-dlp comment entry for {url!r} is missing 'id' or "
                f"'author_id': {raw!r}"
            )

        parent = raw.get("parent")
        # See the class docstring: `parent` reliability on Instagram is an
        # unresolved risk, not assumed-solved here. Missing -> top-level.
        is_reply = parent is not None and parent != "root"

        return Comment(
            id=str(comment_id),
            author_id=str(author_id),
            text=raw.get("text") or "",
            is_reply=is_reply,
            like_count=raw.get("like_count"),
        )

    def ensure_video(self, result: IngestResult) -> Path:
        """Download the video for ``result`` and return its local path.

        Idempotent within this instance's lifetime: a second call for a
        URL that was already downloaded successfully returns the cached
        path without re-invoking yt-dlp (see ``self._video_cache``).
        """
        cached = self._video_cache.get(result.url)
        if cached is not None:
            return cached

        info = self._client.extract_info(
            result.url, cookies_file=self._cookies_file, download=True
        )

        requested = info.get("requested_downloads") or []
        filepath = (requested[0].get("filepath") if requested else None) or info.get(
            "_filename"
        )
        if filepath:
            path = Path(filepath)
            self._video_cache[result.url] = path
            return path

        raise IngestError(
            f"yt-dlp download response for {result.url!r} did not include "
            "'requested_downloads[0].filepath' or '_filename'; cannot "
            "determine the downloaded video's local path."
        )
