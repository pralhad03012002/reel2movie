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
from reel2movie.text_extraction.claude_code_extractor import (
    ClaudeCodeCandidateExtractor,
    ClaudeCodeTextChatClient,
    TextChatClient,
)
from reel2movie.text_extraction.fallback_extractor import FallbackCandidateExtractor
from reel2movie.text_extraction.regex_extractor import RegexCandidateExtractor
from reel2movie.tmdb.client import TMDBHttpClient
from reel2movie.visual.vision_llm_detector import (
    AnthropicVisionChatClient,
    ClaudeCodeVisionChatClient,
    VisionLLMPosterDetector,
)

# How often (in seconds) `run_pipeline`'s visual-fallback step samples
# frames when a `PipelineDeps` doesn't override it. 1.0 was picked so a
# transient on-screen text overlay held for only 1-2 seconds (per this
# subtask's `PROGRESS.md` entry -- the motivating case: creator-burned
# "movies like X" text cards that can fall entirely between two sparse
# samples) has a near-guaranteed chance of landing in at least one sampled
# frame. NOT yet empirically tuned against real reel footage -- a
# deliberate starting guess, same caveat as `visual/frame_dedup.py`'s
# threshold.
_DEFAULT_FRAME_INTERVAL_SECONDS = 1.0

# Perceptual-dedup threshold (see `visual/frame_dedup.dedupe_similar_frames`)
# applied to the dense frame samples above before any frame reaches the
# (expensive) vision LLM call. Mirrors `frame_dedup.py`'s own default
# exactly -- NOT yet empirically tuned against real reel footage, a
# deliberate starting guess the orchestrating conversation plans to
# validate/adjust against real reels after this subtask lands.
_DEFAULT_FRAME_DEDUP_THRESHOLD = 0.04


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
    # Interval (seconds) between dense frame samples in the visual-fallback
    # step (see `visual/frame_sampler.sample_frames_at_interval`). Replaces
    # the old `frame_count` (sparse, N equally-spaced samples) now that the
    # visual fallback samples densely across the WHOLE video instead -- see
    # `pipeline/waterfall.py`'s `_extract_from_visual` for the full
    # rationale.
    frame_interval_seconds: float = _DEFAULT_FRAME_INTERVAL_SECONDS
    # Perceptual-dedup threshold (see `visual/frame_dedup.dedupe_similar_frames`)
    # applied to those dense samples before any frame reaches the vision
    # LLM call, so a long static shot doesn't burn one Claude call per
    # near-identical frame. Internal-only knob: no CLI flag exposes this
    # (see `cli.py`'s docstring) since no one has asked for it to be
    # user-tunable yet.
    frame_dedup_threshold: float = _DEFAULT_FRAME_DEDUP_THRESHOLD
    # Optional: a `TextChatClient` for `tmdb.resolver.resolve_candidate()`'s
    # caption-context disambiguation step (see PROGRESS.md's "Follow-up —
    # disambiguate tied exact matches" section). Defaults to `None` so any
    # `PipelineDeps` built without one (e.g. existing tests) behaves
    # exactly as before -- `resolve_candidate()` treats a missing
    # chat_client as "disambiguation not available" and falls through to
    # its pre-existing rank/year tiebreak.
    disambiguation_chat_client: TextChatClient | None = None


def build_default_pipeline_deps() -> PipelineDeps:
    """Wire the real implementations together, reading secrets from env.

    - `ingestor` -- `InstagramIngestor` over a real `YtDlpClient`, with
      `config.get_instagram_cookies_file()` passed through (may be
      `None`; `InstagramIngestor` itself tolerates that).
    - `text_extractor` -- `FallbackCandidateExtractor` wrapping
      `RegexCandidateExtractor` (free/instant first pass, no config
      needed) with `ClaudeCodeCandidateExtractor` over a
      `ClaudeCodeTextChatClient` as the fallback for prose regex can't
      parse. This always shells out to the local `claude` CLI for text
      when regex finds nothing -- independent of, and regardless of,
      whatever `config.get_vision_backend()` selects for the *visual*
      poster detector below. The two are separate decisions: the `claude`
      CLI is now a dependency for text extraction unconditionally, not
      just when `VISION_BACKEND=claude_code`.
    - `poster_detector` -- `VisionLLMPosterDetector` over whichever
      `VisionChatClient` `config.get_vision_backend()` selects:
      `"claude_code"` (the default) wires a `ClaudeCodeVisionChatClient`
      (shells out to the local `claude` CLI, no API key needed);
      `"anthropic_api"` wires an `AnthropicVisionChatClient` constructed
      with `config.get_anthropic_key()`.
    - `tmdb_client` -- `TMDBHttpClient` constructed with
      `config.get_tmdb_token()`.
    - `disambiguation_chat_client` -- the SAME `ClaudeCodeTextChatClient`
      instance constructed above for `text_extractor`'s fallback, reused
      rather than constructing a second, identical "shell out to `claude`
      for text" client. Threaded through `pipeline/waterfall.py` into
      `tmdb.resolver.resolve_candidate()`'s caption-context
      disambiguation step.

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
    # Shared with `disambiguation_chat_client` below -- one instance, not
    # two, since both uses are the identical "shell out to the `claude`
    # CLI for a pure-text reply" primitive and the client is stateless.
    claude_text_chat_client = ClaudeCodeTextChatClient()
    text_extractor = FallbackCandidateExtractor(
        RegexCandidateExtractor(),
        ClaudeCodeCandidateExtractor(claude_text_chat_client),
    )

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
        disambiguation_chat_client=claude_text_chat_client,
    )
