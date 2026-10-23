"""The strict caption -> creator-comment -> visual-fallback waterfall.

Implements `flow.md` steps [2]-[6] exactly: a confident candidate from an
earlier step skips every later step; TMDB resolution + aggregate/dedupe
happens once, on whichever step's pooled candidates "won" (flow.md step
[5]: "For every candidate gathered from whichever step won"). This module
depends only on the Protocol types in `core/protocols.py`
(`Ingestor`, `CandidateExtractor`, `PosterDetector`, `TMDBClient`) plus the
free functions the task spec explicitly names as already-built and
callable from here (`tmdb.resolver.resolve_candidate`,
`visual.frame_sampler.sample_frames_at_interval`,
`visual.frame_dedup.dedupe_similar_frames`) -- never any concrete *class*
from `ingest/`, `visual/`, `tmdb/`, or `text_extraction/`. The one place
allowed to construct those concrete classes is `pipeline/deps.py`.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from reel2movie.core.models import (
    Candidate,
    IngestResult,
    PipelineResult,
    Recommendation,
    SourceTag,
)
from reel2movie.pipeline.deps import PipelineDeps
from reel2movie.text_extraction.regex_extractor import HIGH_CONFIDENCE
from reel2movie.tmdb.resolver import resolve_candidate
from reel2movie.visual.frame_dedup import dedupe_similar_frames
from reel2movie.visual.frame_sampler import (
    FrameExtractionError,
    probe_duration_seconds,
    sample_frames_at_interval,
)

logger = logging.getLogger(__name__)

# "Confident" reuses text_extraction/regex_extractor.py's own HIGH tier
# value directly (bound by import, not re-declared as a parallel literal,
# so there is no drift window if regex_extractor.py ever re-tiers its
# confidence scoring): HIGH is exactly the tier that extractor reserves
# for its least-ambiguous signal ("Title (YYYY)", quoted or unquoted) --
# the same bar flow.md's "confident" gate is meant to express ("If >= 1
# confident candidate"). A MEDIUM-tier (0.6) candidate (a bare quoted span
# or numbered-list line with no year) does NOT clear this gate, so e.g. a
# numbered list with no years in the caption still correctly falls
# through to the creator-comment step rather than the waterfall
# committing to a weaker signal just because *something* matched.
CONFIDENCE_THRESHOLD = HIGH_CONFIDENCE


def _is_confident(candidates: list[Candidate]) -> bool:
    return any(c.confidence >= CONFIDENCE_THRESHOLD for c in candidates)


def _extract_from_caption(
    result: IngestResult, deps: PipelineDeps
) -> list[Candidate]:
    """flow.md step [2]: parse the caption text."""
    try:
        return deps.text_extractor.extract(result.caption, SourceTag.CAPTION)
    except Exception:
        # An internal failure in this step is "found nothing", not a
        # fatal pipeline error -- fall through to the next step. Only
        # step [1] (fetch_metadata) is allowed to propagate, per
        # flow.md's "unreachable/unsupported link -> fail immediately"
        # rule.
        logger.exception("caption candidate extraction failed; treating as empty")
        return []


def _extract_from_creator_comments(
    result: IngestResult, deps: PipelineDeps
) -> list[Candidate]:
    """flow.md step [3]: the creator's own top-level comment(s)."""
    try:
        creator_top_level_comments = [
            comment
            for comment in result.comments
            if comment.author_id == result.creator_account_id
            and not comment.is_reply
        ]
        candidates: list[Candidate] = []
        for comment in creator_top_level_comments:
            candidates.extend(
                deps.text_extractor.extract(comment.text, SourceTag.CREATOR_COMMENT)
            )
        return candidates
    except Exception:
        logger.exception(
            "creator-comment candidate extraction failed; treating as empty"
        )
        return []


def _extract_from_visual(result: IngestResult, deps: PipelineDeps) -> list[Candidate]:
    """flow.md step [4]: sample frames and run poster/title-card detection.

    This is the last fallback: whatever it produces is used as-is, even
    if sparse or empty -- there is no further step to fall through to.

    Duration determination (this is a fallback-probe-then-decide flow,
    not a check-before-downloading one): `result.duration_seconds` (from
    yt-dlp/Instagram metadata) is used directly when it's a valid
    positive number -- it's free, no extra ffmpeg call needed. But
    yt-dlp/Instagram can legitimately omit duration for a given reel
    (`IngestResult.duration_seconds` is typed `float | None`), and a
    missing/invalid *reported* duration must NOT by itself prevent this
    last-resort fallback from running. So `deps.ingestor.ensure_video`
    now runs unconditionally whenever this step is reached (this step
    already needs the downloaded video for frame sampling regardless),
    and when metadata duration is missing/invalid,
    `frame_sampler.probe_duration_seconds` is used instead to determine
    the duration directly from the downloaded file -- independent of
    whatever Instagram/yt-dlp did or didn't report. Only when probing
    ALSO fails (raises `FrameExtractionError`) or ALSO yields an invalid
    (`<= 0`) value is duration treated as genuinely undeterminable.

    Three distinct outcomes are deliberately logged/handled differently,
    so a later debugging session can tell them apart instead of seeing
    the same opaque `[]`:

    1. Duration genuinely undeterminable: metadata was missing/invalid
       *and* probing the downloaded file also failed or also produced an
       invalid value. Logged as its own warning and returns `[]` without
       ever calling `sample_frames_at_interval`. Note `ensure_video` has already run
       by this point -- a reel whose video is corrupt/unprobeable now
       always pays for the download attempt, which the old
       check-before-downloading flow could sometimes skip. Accepted cost
       of making probing possible at all; see PROGRESS.md.
    2. Any other internal failure (`ensure_video` itself raising, ffmpeg
       frame extraction, poster detection) -- caught by the
       `except Exception` below and logged via `logger.exception` with a
       different message, same as the other waterfall steps.
    3. Success, via either metadata or probed duration -- which source
       won is logged (debug for metadata, info for probed), since
       probing is new, not-yet-proven-reliable behavior worth being able
       to distinguish from metadata-sourced duration in logs.

    Frame-directory lifecycle: `sample_frames_at_interval` (per its own
    docstring, shared with `sample_frames`) hands back a *caller-owned*
    temp directory of JPEGs when no `output_dir` is given -- nothing in
    `visual/frame_sampler.py` ever cleans it up. This function is that
    caller: it creates its own temp directory, passes it explicitly as
    `output_dir`, and removes it with `shutil.rmtree` once poster
    detection has read every frame (frames are only needed transiently for
    `deps.poster_detector.detect()`, not after), inside a `finally` so
    cleanup happens even if poster detection or frame extraction raises
    partway through.

    Sampling strategy (changed in this subtask -- see PROGRESS.md "Subtask
    9"): dense, fixed-interval sampling across the WHOLE video
    (`sample_frames_at_interval`, every `deps.frame_interval_seconds`,
    including the very first/last frame) replaced the old sparse,
    N-equally-spaced, 5%-95%-windowed `sample_frames` call. Rationale: a
    creator-burned on-screen text overlay naming a movie (as opposed to a
    poster/title card) can be on screen for as little as 1-2 seconds and
    can appear right at the start or end of a reel -- both of which the
    old sparse sampling could miss entirely (the text window falling
    between two of the 6 sparse samples, or the 5%-95% window excluding
    the very edges where an intro/outro text card lives). Dense sampling
    alone would multiply the number of expensive vision-LLM calls per
    reel, so `dedupe_similar_frames` runs as a cheap, local,
    Pillow-based pre-filter immediately after sampling and BEFORE any
    `deps.poster_detector.detect()` call -- collapsing a long static shot
    (a held poster, a talking-head segment) down to the one frame that
    actually represents it, so a long static run doesn't burn one Claude
    call per near-duplicate frame.
    """
    frames_dir = Path(tempfile.mkdtemp(prefix="reel2movie_frames_"))
    try:
        video_path = deps.ingestor.ensure_video(result)

        if result.duration_seconds is not None and result.duration_seconds > 0:
            duration_seconds = result.duration_seconds
            logger.debug(
                "visual fallback: using metadata-reported duration %.3fs "
                "for %s",
                duration_seconds,
                video_path,
            )
        else:
            try:
                duration_seconds = probe_duration_seconds(video_path)
            except FrameExtractionError:
                logger.warning(
                    "cannot run visual fallback: unknown reel duration "
                    "(metadata duration_seconds=%r was missing/invalid, "
                    "and probing the downloaded video file at %s for its "
                    "actual duration also failed); skipping frame "
                    "sampling and poster detection for this reel",
                    result.duration_seconds,
                    video_path,
                )
                return []
            if duration_seconds <= 0:
                logger.warning(
                    "cannot run visual fallback: unknown reel duration "
                    "(metadata duration_seconds=%r was missing/invalid, "
                    "and probing %s also yielded an invalid duration "
                    "%r); skipping frame sampling and poster detection "
                    "for this reel",
                    result.duration_seconds,
                    video_path,
                    duration_seconds,
                )
                return []
            logger.info(
                "visual fallback: metadata duration missing/invalid "
                "(duration_seconds=%r); probed actual video file at %s "
                "for duration instead -> %.3fs",
                result.duration_seconds,
                video_path,
                duration_seconds,
            )

        frames = sample_frames_at_interval(
            video_path,
            deps.frame_interval_seconds,
            duration_seconds,
            output_dir=frames_dir,
        )
        unique_frames = dedupe_similar_frames(
            frames, threshold=deps.frame_dedup_threshold
        )
        candidates: list[Candidate] = []
        for frame in unique_frames:
            candidates.extend(deps.poster_detector.detect(frame))
        return candidates
    except Exception:
        logger.exception("visual fallback extraction failed; treating as empty")
        return []
    finally:
        shutil.rmtree(frames_dir, ignore_errors=True)


def _resolve_all(
    candidates: list[Candidate], deps: PipelineDeps, result: IngestResult
) -> list[Recommendation]:
    """flow.md step [5]: resolve every winning candidate against TMDB.

    Per flow.md's explicit rule, a candidate that fails to resolve is
    KEPT with `tmdb=None`, never dropped. A `resolve_candidate` call that
    raises (rather than cleanly returning `None`) is treated the same
    way -- one candidate's lookup failing is not a reason to lose every
    other candidate's recommendation or abort the run.

    `result` (the original `IngestResult`) is threaded through here only
    for `result.caption` -- passed as `resolve_candidate()`'s `context`
    for its caption-context disambiguation step (see PROGRESS.md's
    "Follow-up — disambiguate tied exact matches" section). The caption
    is the most reliably-present single text signal per flow.md's own
    design, which is why it -- not the comment/visual text that may have
    actually produced the winning candidate -- is used as the
    disambiguation context for every candidate, regardless of which
    waterfall step it came from.
    """
    recommendations: list[Recommendation] = []
    for candidate in candidates:
        try:
            resolved = resolve_candidate(
                candidate,
                deps.tmdb_client,
                context=result.caption,
                chat_client=deps.disambiguation_chat_client,
            )
        except Exception:
            logger.exception(
                "TMDB resolution failed for %r; keeping as unresolved",
                candidate.raw_text,
            )
            resolved = None
        recommendations.append(
            Recommendation(
                query=candidate.raw_text,
                source=candidate.source,
                confidence=candidate.confidence,
                tmdb=resolved,
            )
        )
    return recommendations


def _dedupe(recommendations: list[Recommendation]) -> list[Recommendation]:
    """flow.md step [6]: merge same-TMDB-id recommendations, sort by confidence.

    Merge rule: group the resolved recommendations by `tmdb.id`; within a
    group, keep the single `Recommendation` with the highest `confidence`
    verbatim (not a field-by-field blend). `query`/`source`/`confidence`
    describe *how a recommendation was found*, which only makes sense to
    report for one winning extraction per movie, not averaged/combined
    across several near-duplicate extractions of the same movie.
    Unresolved recommendations (`tmdb is None`) have no id to group on, so
    they are never merged with anything or with each other -- EXCEPT: if
    an unresolved recommendation's `query` string exactly matches the
    `query` of some other recommendation that DID resolve (e.g. the same
    poster detected in two sampled frames, one TMDB lookup transiently
    failing), that unresolved copy is a redundant duplicate of an already-
    answered question, not a genuinely-unresolved candidate, so it's
    dropped. An unresolved recommendation with no same-query resolved
    sibling is kept as-is, per flow.md's rule. The final list is sorted by
    `confidence` descending.
    """
    unresolved = [rec for rec in recommendations if rec.tmdb is None]
    resolved = [rec for rec in recommendations if rec.tmdb is not None]

    resolved_queries = {rec.query for rec in resolved}
    unresolved = [rec for rec in unresolved if rec.query not in resolved_queries]

    best_by_tmdb_id: dict[int, Recommendation] = {}
    for rec in resolved:
        assert rec.tmdb is not None  # narrowed by the filter above
        existing = best_by_tmdb_id.get(rec.tmdb.id)
        if existing is None or rec.confidence > existing.confidence:
            best_by_tmdb_id[rec.tmdb.id] = rec

    deduped = [*best_by_tmdb_id.values(), *unresolved]
    deduped.sort(key=lambda rec: rec.confidence, reverse=True)
    return deduped


def run_pipeline(url: str, deps: PipelineDeps) -> PipelineResult:
    """Run the full waterfall for `url` and return a `PipelineResult`.

    Step [1] (`deps.ingestor.fetch_metadata`) is deliberately NOT wrapped
    in a try/except: an unreachable/unsupported link must fail the whole
    pipeline immediately, per flow.md's error-handling rule, so any
    exception it raises propagates straight out of `run_pipeline`. Every
    later step's own internal failure is caught inside its own helper
    (`_extract_from_caption` / `_extract_from_creator_comments` /
    `_extract_from_visual` / each candidate's `resolve_candidate` call in
    `_resolve_all`) and treated as "found nothing for this step", falling
    through to the next step rather than aborting.
    """
    result = deps.ingestor.fetch_metadata(url)

    candidates = _extract_from_caption(result, deps)
    if not _is_confident(candidates):
        comment_candidates = _extract_from_creator_comments(result, deps)
        if _is_confident(comment_candidates):
            candidates = comment_candidates
        else:
            candidates = _extract_from_visual(result, deps)

    recommendations = _resolve_all(candidates, deps, result)
    deduped_recommendations = _dedupe(recommendations)
    return PipelineResult(reel_url=url, recommendations=deduped_recommendations)
