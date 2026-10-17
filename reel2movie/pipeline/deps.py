"""`PipelineDeps` + the one place allowed to wire up the real system.

`PipelineDeps` is typed entirely against the Protocols in
`core/protocols.py` -- `pipeline/waterfall.py` only ever touches those
Protocol types. `build_default_pipeline_deps()` is deliberately the sole
exception: its whole job is importing and constructing concrete classes
from every other subpackage (`ingest/`, `text_extraction/`, `visual/`,
`tmdb/`) and handing back a `PipelineDeps` that satisfies the Protocols
structurally.
"""

from __future__ import annotations

from dataclasses import dataclass

from reel2movie import config
from reel2movie.core.protocols import (
    CandidateExtractor,
    Ingestor,
    PosterDetector,
    TMDBClient,
)
from reel2movie.ingest.instagram import InstagramIngestor
from reel2movie.ingest.ytdlp_client import YtDlpClient
from reel2movie.text_extraction.regex_extractor import RegexCandidateExtractor
from reel2movie.tmdb.client import TMDBHttpClient
from reel2movie.visual.vision_llm_detector import (
    AnthropicVisionChatClient,
    ClaudeCodeVisionChatClient,
    VisionLLMPosterDetector,
)

# How many frames `run_pipeline`'s visual-fallback step samples when a
# `PipelineDeps` doesn't override it. Not tuned against real data -- a
# round, modest number for "a handful of equally-spaced samples", per
# flow.md step [4]'s "not a dense scan" instruction.
_DEFAULT_FRAME_COUNT = 6


@dataclass
class PipelineDeps:
    """Everything `run_pipeline` needs, typed against Protocols only.

    `waterfall.py` never constructs any of these itself -- a caller
    (`build_default_pipeline_deps()` for real runs, or a test with fakes)
    always supplies them.
    """

    ingestor: Ingestor
    text_extractor: CandidateExtractor
    poster_detector: PosterDetector
    tmdb_client: TMDBClient
    frame_count: int = _DEFAULT_FRAME_COUNT


def build_default_pipeline_deps() -> PipelineDeps:
    """Wire the real implementations together, reading secrets from env.

    - `ingestor` -- `InstagramIngestor` over a real `YtDlpClient`, with
      `config.get_instagram_cookies_file()` passed through (may be
      `None`; `InstagramIngestor` itself tolerates that).
    - `text_extractor` -- `RegexCandidateExtractor` (no config needed).
    - `poster_detector` -- `VisionLLMPosterDetector` over whichever
      `VisionChatClient` `config.get_vision_backend()` selects:
      `"claude_code"` (the default) wires a `ClaudeCodeVisionChatClient`
      (shells out to the local `claude` CLI, no API key needed);
      `"anthropic_api"` wires an `AnthropicVisionChatClient` constructed
      with `config.get_anthropic_key()`.
    - `tmdb_client` -- `TMDBHttpClient` constructed with
      `config.get_tmdb_token()`.

    Raises whatever `config.get_tmdb_token()` raises (a clear
    `RuntimeError` naming the missing env var) if that required credential
    is unset -- deliberately not caught here, since there is no sensible
    fallback for a missing credential and failing fast at startup is
    preferable to failing deep inside a pipeline run.

    Critical: `config.get_anthropic_key()` is called ONLY inside the
    `"anthropic_api"` branch below, never eagerly/unconditionally -- a
    caller using the default `"claude_code"` backend must never hit a
    missing-`ANTHROPIC_API_KEY` error anywhere, since that backend doesn't
    need the key at all.
    """
    ingestor = InstagramIngestor(
        YtDlpClient(), cookies_file=config.get_instagram_cookies_file()
    )
    text_extractor = RegexCandidateExtractor()

    backend = config.get_vision_backend()
    if backend == "claude_code":
        chat_client = ClaudeCodeVisionChatClient()
    elif backend == "anthropic_api":
        chat_client = AnthropicVisionChatClient(config.get_anthropic_key())
    else:
        raise RuntimeError(
            f"Unknown VISION_BACKEND {backend!r}; expected 'claude_code' or "
            f"'anthropic_api'"
        )
    poster_detector = VisionLLMPosterDetector(chat_client)

    tmdb_client = TMDBHttpClient(config.get_tmdb_token())

    return PipelineDeps(
        ingestor=ingestor,
        text_extractor=text_extractor,
        poster_detector=poster_detector,
        tmdb_client=tmdb_client,
    )
