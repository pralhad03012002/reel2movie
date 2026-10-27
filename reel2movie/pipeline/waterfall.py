"""The parallel candidate-extraction race + TMDB resolution pipeline.

Historical note: this module used to implement a strict, sequential
caption -> creator-comment -> visual-fallback *waterfall* (flow.md steps
[2]-[6]), where a confident candidate from an earlier step skipped every
later step entirely. It has been replaced by a parallel RACE: all four
candidate-generating jobs (caption, creator-comment, audio-transcript,
visual) now always launch concurrently, racing to be the first to produce
a confident candidate (see `_race_candidate_jobs`'s docstring for the full
contract). The module name/filename stays `waterfall.py` purely to avoid a
pointless rename ripple across imports -- the waterfall's step [1]
(fetch metadata) and steps [5]-[6] (resolve + dedupe) are otherwise
unchanged.

Video download + audio extraction are themselves two more fire-and-forget
background jobs (`_prepare_video`/`_prepare_audio`, started on their own
daemon threads alongside the four candidate jobs by
`_race_candidate_jobs` -- see `_run_in_daemon_thread` for why daemon
threads), not a blocking prerequisite run before the race starts. Caption
and creator-comment need neither and can finish almost instantly
regardless of how long the download takes; the audio-transcript and
visual jobs are the only ones that actually need that data, so they (and
only they) block internally -- within their own job function, on a
`Future` for the relevant prep step -- rather than making the whole race
wait. See each job function's own docstring for the cancel_event-checking
details, and `_race_candidate_jobs` for how everything is wired up and
why the orchestrator itself never waits for a prep step that nobody still
needs. The four actual race jobs themselves ALSO run on daemon threads
(not a `ThreadPoolExecutor`) for the same process-exit-hang reason -- see
`_run_in_daemon_thread`'s docstring's note on this generalization.

Fix 2 (known, accepted limitation): `_extract_from_visual`'s OWN nested
per-frame vision-LLM pool (`frame_executor`) remains a real
`ThreadPoolExecutor`, not daemon threads. Under the non-default
`VISION_BACKEND=anthropic_api` backend, `AnthropicVisionChatClient.chat()`
cannot honor `cancel_event` (a blocking HTTP call, no local process to
kill -- see its own docstring) -- if a frame-detection call is still
in-flight when another job wins the race, that thread stays blocked on
the live HTTP request inside `frame_executor`, a real pool whose worker
threads ARE joined by `concurrent.futures.thread`'s process-wide `atexit`
hook, so a short-lived caller's process can hang at exit waiting for it.
This was investigated and deliberately NOT converted to daemon threads in
this pass: unlike the outer race-job pool (exactly 4 jobs, no real
concurrency cap needed), `frame_executor` enforces a genuine bounded
concurrency limit (`_FRAME_DETECTION_MAX_WORKERS`) over a variable,
unbounded number of frames, plus `cancel_futures=True` drop-not-yet-started
-vs-already-running semantics and a bounded abandon-grace wait -- all
already tested, load-bearing logic that a raw-daemon-thread
rewrite (e.g. a semaphore-gated spawner) would have to carefully
reproduce without a regression, for a benefit that only matters under a
non-default backend most runs don't use. Accepted as-is; see
`_extract_from_visual`'s docstring and
`tests/unit/pipeline/test_waterfall.py`'s
`test_frame_detection_pool_threads_are_real_threadpool_workers_known_limitation`
for a test that documents (rather than silently passing over) this gap.

This module depends only on the Protocol types in `core/protocols.py`
(`Ingestor`, `CandidateExtractor`, `PosterDetector`, `TMDBClient`,
`AudioTranscriber` -- the latter two accessed only via `PipelineDeps`)
plus the free functions the task spec explicitly names as already-built
and callable from here (`tmdb.resolver.resolve_candidate`,
`tmdb.resolver.resolve_candidate_with_retry`,
`audio.audio_extractor.extract_audio`,
`visual.frame_sampler.sample_frames_at_interval`,
`visual.frame_sampler.probe_duration_seconds`,
`visual.frame_dedup.dedupe_similar_frames`) -- never any concrete *class*
from `ingest/`, `visual/`, `tmdb/`, `text_extraction/`, or `audio/`. The one
place allowed to construct those concrete classes is `pipeline/deps.py`.

Error-isolation policy for the four race jobs (`_extract_from_caption`,
`_extract_from_creator_comments`, `_extract_from_audio_transcript`,
`_extract_from_visual`) -- a single, consistent policy applied identically
to all four via one shared wrapper, `_run_job_safely()`, rather than
hand-copied into each job function:

- Every job function is called ONLY through `_run_job_safely()`, which
  wraps the call in a try/except so NO job function's exception ever
  reaches `_race_candidate_jobs` directly -- `_run_job_safely()` always
  returns a `_JobOutcome` (possibly with empty `candidates`), never
  raises. This is what lets `_race_candidate_jobs` safely call
  `future.result()` on every job without one job's failure taking down
  the whole race or the other three jobs (they run as independent OS
  threads either way, but a raised exception would otherwise still need
  handling at the call site, and a crash in one job must never be
  mistaken for "the whole reel failed"). The job functions themselves are
  free to just let an exception propagate -- `_run_job_safely()` is the
  only place that decides what that means.
- A `reel2movie._subprocess_util.SubprocessCancelled` means this job *lost
  the race* cooperatively -- nothing went wrong. Catching this one type is
  enough to cover every concrete cancellation signal this codebase's
  cancellable subprocess machinery actually raises:
  `reel2movie._claude_cli.ClaudeCliCancelled` is ALSO a `SubprocessCancelled`
  (multiple inheritance -- see its own docstring for why), and
  `WhisperCppTranscriberError` never wraps a cancellation at all, it
  raises `SubprocessCancelled` directly. Logged at INFO (not as an
  error/exception), and treated exactly like "found nothing": an
  empty-candidates outcome for this job's `SourceTag`.
- Any OTHER exception is a genuine, unexpected internal failure. It is
  still logged -- via `logger.exception`, full traceback -- so a real bug
  is never silently swallowed/undiscoverable, but it is NOT allowed to
  propagate: the job still returns an empty-candidates outcome for its
  `SourceTag`, same shape as the cancelled case, so one job crashing can
  never crash the race, the other three jobs, or the whole pipeline run.
  (The two cases are deliberately indistinguishable to the race
  orchestrator itself -- only the log severity/message differs -- since
  "this job contributed nothing" is the only decision the orchestrator
  ever needs to make either way.)
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor, as_completed, wait
from dataclasses import dataclass, field
from pathlib import Path

from reel2movie._subprocess_util import SubprocessCancelled
from reel2movie.audio.audio_extractor import extract_audio
from reel2movie.core.models import (
    Candidate,
    Comment,
    IngestResult,
    PipelineResult,
    Recommendation,
    SourceTag,
)
from reel2movie.pipeline.deps import PipelineDeps
from reel2movie.text_extraction.candidate_disambiguation import (
    select_primary_candidates,
)
from reel2movie.text_extraction.regex_extractor import HIGH_CONFIDENCE
from reel2movie.tmdb.resolver import resolve_candidate_with_retry
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


@dataclass(frozen=True, slots=True)
class _JobOutcome:
    """One race job's result: which `SourceTag` it ran as, the candidates
    it produced (possibly empty -- "found nothing", "lost the race", and
    "crashed" are all represented as an empty list here per this module's
    error-isolation policy, see the module docstring), and, only for the
    audio-transcript job, the raw transcript text itself (`raw_text`) --
    needed later as extra disambiguation context (see `_resolve_all`).
    """

    source: SourceTag
    candidates: list[Candidate] = field(default_factory=list)
    raw_text: str | None = None


# Poll interval `_wait_or_cancelled` uses while blocked on a prep
# `Future` -- same order of magnitude as `run_cancelable`'s own poll
# interval (~0.2s), so a cancellation is noticed and acted on about as
# promptly here as it is anywhere else in this codebase's cancellation
# machinery.
_PREP_WAIT_POLL_INTERVAL_SECONDS = 0.2


def _wait_or_cancelled(
    future: "Future", cancel_event: threading.Event
) -> tuple[object, bool]:
    """Block on `future`, but wake up every
    `_PREP_WAIT_POLL_INTERVAL_SECONDS` to check `cancel_event` instead of
    blocking on it unboundedly.

    This is what actually makes the "check cancel_event before/after
    waiting on the prep Future" contract (see `_extract_from_audio_transcript`/
    `_extract_from_visual`'s docstrings) hold even in the case where a job
    starts waiting a moment BEFORE `cancel_event` gets set: a plain,
    unbounded `future.result()` call would commit this thread to waiting
    for however long the prep step (e.g. a video download) takes
    regardless of a cancellation that fires moments later, which would in
    turn make `_race_candidate_jobs`'s own bounded grace-wait for the
    other race jobs (`_RACE_LOSER_GRACE_SECONDS`) block for that same
    unbounded duration too -- defeating this subtask's whole point.
    Polling instead means a job that's merely waiting on a prep step
    (rather than doing its own real work) notices cancellation within
    about one poll interval no matter when, relative to the wait
    starting, the race actually gets decided.

    Returns `(future.result(), False)` if `future` finishes before
    `cancel_event` does, or `(None, True)` as soon as `cancel_event` fires
    first -- in the latter case `future` is left running in the
    background, exactly as every other still-in-flight job/prep step is
    once cancelled (see module docstring's Fix 1 note); this function
    never waits for it to actually finish. If `cancel_event` is already
    set when this is called, the loop below never runs its body at all
    and falls straight through to that same `(None, True)` result.
    """
    while not cancel_event.is_set():
        done, _not_done = wait([future], timeout=_PREP_WAIT_POLL_INTERVAL_SECONDS)
        if done:
            return future.result(), False
    return None, True


# Human-readable label per race `SourceTag`, used only for `_run_job_safely`'s
# log messages (e.g. "caption candidate extraction failed; treating as
# empty") -- kept as one small lookup table rather than a parallel if/elif
# chain or hand-written string per job.
_JOB_LABELS: dict[SourceTag, str] = {
    SourceTag.CAPTION: "caption",
    SourceTag.CREATOR_COMMENT: "creator-comment",
    SourceTag.AUDIO_TRANSCRIPT: "audio-transcript",
    SourceTag.FRAME_VISUAL: "visual",
}


def _run_job_safely(source: SourceTag, fn: Callable[[], _JobOutcome]) -> _JobOutcome:
    """Shared error-isolation wrapper for all four race job functions --
    the single place this module's "Error-isolation policy" (see module
    docstring) is actually implemented, rather than hand-copied per job.

    Calls `fn()` and returns whatever it returns. If `fn()` raises
    `SubprocessCancelled` (which also catches `ClaudeCliCancelled`, a
    `SubprocessCancelled` subclass -- see that class's own docstring),
    that's logged at INFO as "lost the race", not an error. Any other
    exception is logged via `logger.exception` (full traceback) as a
    genuine internal failure. Either way, an empty `_JobOutcome` for
    `source` is returned instead of letting the exception propagate --
    this function itself never raises.
    """
    label = _JOB_LABELS[source]
    try:
        return fn()
    except SubprocessCancelled:
        logger.info("%s candidate extraction job lost the race (cancelled)", label)
        return _JobOutcome(source=source)
    except Exception:
        logger.exception("%s candidate extraction failed; treating as empty", label)
        return _JobOutcome(source=source)


def _extract_from_caption(
    result: IngestResult, deps: PipelineDeps, cancel_event: threading.Event
) -> _JobOutcome:
    """Race job body (always invoked through `_run_job_safely`, which owns
    this module's error-isolation policy -- see its docstring): parse the
    caption text (flow.md's old step [2])."""
    candidates = deps.text_extractor.extract(
        result.caption, SourceTag.CAPTION, cancel_event=cancel_event
    )
    return _JobOutcome(source=SourceTag.CAPTION, candidates=candidates)


def _creator_top_level_comments(result: IngestResult) -> list[Comment]:
    """The creator's own top-level (non-reply) comments on `result` --
    shared filter predicate used by both `_extract_from_creator_comments`
    (what the creator-comment race job actually extracts from) and
    `_primary_candidate_source_text` (what source text gets attributed to
    a winning `SourceTag.CREATOR_COMMENT` outcome) -- factored out so the
    two stay trivially in sync instead of each hand-rolling the same
    `comment.author_id == result.creator_account_id and not comment.is_reply`
    predicate.
    """
    return [
        comment
        for comment in result.comments
        if comment.author_id == result.creator_account_id and not comment.is_reply
    ]


def _extract_from_creator_comments(
    result: IngestResult, deps: PipelineDeps, cancel_event: threading.Event
) -> _JobOutcome:
    """Race job body (see `_extract_from_caption`'s docstring note on
    `_run_job_safely`): the creator's own top-level comment(s) (old step
    [3]).

    `cancel_event` is checked at the top of each loop iteration, not just
    passed through to `deps.text_extractor.extract()` itself: a reel with
    several creator comments, each requiring its own (possibly slow,
    e.g. claude-CLI-backed) extraction call, must not keep launching NEW
    extraction calls for the remaining comments once the race has already
    been lost -- the in-flight call for whichever comment is currently
    being extracted still finishes/gets cancelled on its own via
    `cancel_event` being passed through as usual, but no comment AFTER
    that one gets a new call started at all.
    """
    creator_top_level_comments = _creator_top_level_comments(result)
    candidates: list[Candidate] = []
    for comment in creator_top_level_comments:
        if cancel_event.is_set():
            break
        candidates.extend(
            deps.text_extractor.extract(
                comment.text, SourceTag.CREATOR_COMMENT, cancel_event=cancel_event
            )
        )
    return _JobOutcome(source=SourceTag.CREATOR_COMMENT, candidates=candidates)


def _extract_from_audio_transcript(
    audio_future: "Future[Path | None]",
    deps: PipelineDeps,
    cancel_event: threading.Event,
) -> _JobOutcome:
    """Race job body (see `_extract_from_caption`'s docstring note on
    `_run_job_safely`): transcribe the reel's audio track, then extract
    candidates from the transcript text.

    `audio_future` is `_prepare_audio`'s background job `Future` (see the
    module docstring's Fix 1 note and `_race_candidate_jobs`) -- this
    function waits on it via `_wait_or_cancelled` (polling, not a plain
    unbounded `audio_future.result()`) to get the extracted audio path,
    since there is nothing to transcribe until extraction finishes.
    Polling means `cancel_event` firing at ANY point during that wait --
    before it starts, or at any point while still blocked on a
    possibly-still-running extraction -- is noticed within about one poll
    interval, not only if it happened to already be set before this
    function started waiting. Either way, `_prepare_audio`'s own
    extraction (and the `ensure_video` download it itself waits on) is
    left running to completion in the background regardless -- its result
    is simply unused by this function once cancelled, and its temp
    directory is removed by a separate background job,
    `_cleanup_audio_temp_dir`, not by this function (so cleanup still
    happens whether or not this function ever actually reads the file).

    `audio_future` resolving to `None` means either `_prepare_video`'s
    download or `_prepare_audio`'s extraction itself failed for this reel
    -- either way there is nothing to transcribe. `deps.audio_transcriber`
    being `None` means no `AudioTranscriber` is configured at all (see
    `PipelineDeps.audio_transcriber`'s docstring). Both cases mean this
    job immediately contributes an empty outcome, same as every other
    "this job has nothing to work with" case.
    """
    if deps.audio_transcriber is None:
        # No point waiting on `audio_future` at all in this case -- unlike
        # every other early-return below, this one doesn't depend on the
        # prep result, so there's nothing to gain from blocking on it
        # first (and no `AudioTranscriber` configured is the common case
        # for a `PipelineDeps` that never sets one -- waiting here would
        # needlessly tie this job's thread to however long video
        # download + audio extraction takes for no reason).
        return _JobOutcome(source=SourceTag.AUDIO_TRANSCRIPT)

    audio_path, cancelled = _wait_or_cancelled(audio_future, cancel_event)
    if cancelled or audio_path is None:
        return _JobOutcome(source=SourceTag.AUDIO_TRANSCRIPT)

    transcript = deps.audio_transcriber.transcribe(audio_path, cancel_event=cancel_event)
    if cancel_event.is_set():
        # The race may have been lost WHILE transcribing (which can
        # itself take a while) -- `transcribe()` already got cancelled
        # promptly via `cancel_event`/`run_cancelable` if it was still
        # running when that happened, but checking again here avoids
        # starting a whole separate extraction call (potentially another
        # slow, claude-CLI-backed one) on a transcript nobody will use.
        return _JobOutcome(source=SourceTag.AUDIO_TRANSCRIPT)
    candidates = deps.text_extractor.extract(
        transcript, SourceTag.AUDIO_TRANSCRIPT, cancel_event=cancel_event
    )
    return _JobOutcome(
        source=SourceTag.AUDIO_TRANSCRIPT,
        candidates=candidates,
        raw_text=transcript,
    )


# Bounded concurrency for the per-frame vision-LLM calls inside
# `_extract_from_visual` (each an independent network/subprocess
# round-trip with no data dependency between frames -- see that
# function's docstring). 4 mirrors `_race_candidate_jobs`'s own
# one-worker-per-job sizing philosophy: enough to meaningfully overlap
# several slow calls, not so many that a long static reel with dozens of
# surviving unique frames fires them all at once.
_FRAME_DETECTION_MAX_WORKERS = 4

# Bounded grace period, after cancelling the frame-detection pool, for
# whatever `detect()` call(s) were already RUNNING (not just queued) to
# actually finish before `frames_dir` gets removed out from under them.
# `shutdown(wait=False, cancel_futures=True)` only drops futures that
# hadn't started yet -- an already-in-flight `detect()` call (reading the
# frame's JPEG, or a `claude` CLI subprocess with that file open) keeps
# running regardless, and without this wait the enclosing `finally`'s
# `shutil.rmtree(frames_dir)` could delete that file mid-read, causing a
# silent `FileNotFoundError` in an abandoned thread nobody ever checks
# (`.result()` is never called on it again). Not unbounded: a real
# `detect()` call already has `cancel_event` threaded through to
# `run_cancelable`, so it should self-terminate well within this budget
# on its own; this is just enough slack to let that actually happen
# before cleanup, not a promise that cleanup never proceeds without it.
_FRAME_DETECTION_ABANDON_GRACE_SECONDS = 3.0


def _extract_from_visual(
    result: IngestResult,
    deps: PipelineDeps,
    video_future: "Future[Path | None]",
    cancel_event: threading.Event,
) -> _JobOutcome:
    """Race job body (see `_extract_from_caption`'s docstring note on
    `_run_job_safely`): sample frames and run poster/title-card detection
    (old step [4]).

    `video_future` is `_prepare_video`'s background job `Future` (see the
    module docstring's Fix 1 note and `_race_candidate_jobs`) -- this
    function waits on it via `_wait_or_cancelled` (polling, same reasoning
    as `_extract_from_audio_transcript`'s identical use of it) to get the
    downloaded video path, since there are no frames to sample until the
    download finishes. Polling means `cancel_event` firing at any point
    during that wait is noticed within about one poll interval, not only
    if it happened to already be set before this function started
    waiting. `_prepare_video`'s download itself is left running to
    completion in the background regardless (see module docstring and
    `ingest.instagram.InstagramIngestor.ensure_video`'s docstring: it
    isn't built on `run_cancelable`, so there is no cheap way to abort it
    mid-flight -- its result is simply discarded here once nobody needs
    it).

    `video_future` resolving to `None` means `_prepare_video`'s download
    itself failed for this reel -- there is nothing to sample frames
    from, so this job immediately contributes an empty outcome.

    Duration determination (unchanged from the old waterfall):
    `result.duration_seconds` (from yt-dlp/Instagram metadata) is used
    directly when it's a valid positive number -- it's free, no extra
    ffmpeg call needed. But yt-dlp/Instagram can legitimately omit
    duration for a given reel (`IngestResult.duration_seconds` is typed
    `float | None`), and a missing/invalid *reported* duration must NOT by
    itself prevent this fallback from running. So when metadata duration
    is missing/invalid, `frame_sampler.probe_duration_seconds` is used
    instead to determine the duration directly from the downloaded file --
    independent of whatever Instagram/yt-dlp did or didn't report. Only
    when probing ALSO fails (raises `FrameExtractionError`) or ALSO
    yields an invalid (`<= 0`) value is duration treated as genuinely
    undeterminable.

    Three distinct outcomes are deliberately logged/handled differently,
    so a later debugging session can tell them apart instead of seeing
    the same opaque empty outcome:

    1. Duration genuinely undeterminable: metadata was missing/invalid
       *and* probing the downloaded file also failed or also produced an
       invalid value. Logged as its own warning and returns an empty
       outcome without ever calling `sample_frames_at_interval`.
    2. Any other internal failure (ffmpeg frame extraction, poster
       detection) -- left to propagate to `_run_job_safely`, which logs it
       via `logger.exception` and converts it to an empty outcome, same
       as the other race jobs (see module docstring's error-isolation
       policy).
    3. Success, via either metadata or probed duration -- which source
       won is logged (debug for metadata, info for probed).

    Frame-directory lifecycle: `sample_frames_at_interval` (per its own
    docstring, shared with `sample_frames`) hands back a *caller-owned*
    temp directory of JPEGs when no `output_dir` is given -- nothing in
    `visual/frame_sampler.py` ever cleans it up. This function is that
    caller: it creates its own temp directory, passes it explicitly as
    `output_dir`, and removes it with `shutil.rmtree` once poster
    detection has read every frame (frames are only needed transiently for
    `deps.poster_detector.detect()`, not after), inside a `finally` so
    cleanup happens even if poster detection, frame extraction, or a
    cancellation raises partway through.

    Sampling strategy (unchanged): dense, fixed-interval sampling across
    the WHOLE video (`sample_frames_at_interval`, every
    `deps.frame_interval_seconds`, including the very first/last frame).
    `dedupe_similar_frames` runs as a cheap, local, Pillow-based
    pre-filter immediately after sampling and BEFORE any
    `deps.poster_detector.detect()` call -- collapsing a long static shot
    down to the one frame that actually represents it, so a long static
    run doesn't burn one Claude call per near-duplicate frame.

    Per-frame detection concurrency: the surviving unique frames are each
    an independent `deps.poster_detector.detect()` call with no data
    dependency on one another, so they run through a bounded
    `ThreadPoolExecutor` (`_FRAME_DETECTION_MAX_WORKERS` workers) via
    `as_completed()`, rather than one at a time -- this is typically the
    single slowest race job, so overlapping these calls matters most here.
    `cancel_event` is checked as each result arrives (not just once at the
    top of the loop), so a cancellation stops accumulating/consuming
    further frame-detection results promptly once it fires mid-way. A
    single frame's `detect()` call raising is NOT isolated per-frame --
    it propagates out of this function to `_run_job_safely`, which treats
    the whole visual job as having found nothing (consistent with this
    module's existing, tested error-isolation contract: one bad frame
    fails the JOB, not the whole race/pipeline).

    Known, accepted limitation (see module docstring's Fix 2 note):
    `frame_executor` below is a real `ThreadPoolExecutor`, not daemon
    threads, unlike every other job this module starts. Under
    `VISION_BACKEND=anthropic_api` (non-default), a `detect()` call still
    in-flight when cancelled stays blocked on `AnthropicVisionChatClient
    .chat()`'s uncancellable HTTP request -- that worker thread is then
    joined by `concurrent.futures.thread`'s process-wide `atexit` hook,
    which can hang a short-lived caller's process exit. Deliberately not
    converted to daemon threads in this pass: this pool's bounded
    concurrency + `cancel_futures=True` + abandon-grace-wait logic is
    genuine, tested, load-bearing behavior (unlike the outer race-job
    pool, which only ever hosted exactly 4 jobs and gained nothing from
    being a real pool), and reproducing it correctly with raw daemon
    threads was judged too risky for the benefit, which only matters
    under this non-default backend.
    """
    video_path, cancelled = _wait_or_cancelled(video_future, cancel_event)
    if cancelled or video_path is None:
        return _JobOutcome(source=SourceTag.FRAME_VISUAL)

    frames_dir = Path(tempfile.mkdtemp(prefix="reel2movie_frames_"))
    try:
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
                duration_seconds = probe_duration_seconds(
                    video_path, cancel_event=cancel_event
                )
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
                return _JobOutcome(source=SourceTag.FRAME_VISUAL)
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
                return _JobOutcome(source=SourceTag.FRAME_VISUAL)
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
            cancel_event=cancel_event,
        )
        unique_frames = dedupe_similar_frames(
            frames, threshold=deps.frame_dedup_threshold
        )

        candidates: list[Candidate] = []
        # Deliberately NOT a `with ThreadPoolExecutor(...) as frame_executor:`
        # block: `Executor.__exit__` always calls `shutdown(wait=True)`
        # regardless of why the block was exited, which would make the
        # `break` below pointless -- it would only skip adding a few
        # already-finished results to `candidates`, while still blocking
        # here until EVERY submitted `detect()` call (including ones not
        # yet even started, still queued behind
        # `_FRAME_DETECTION_MAX_WORKERS` concurrency) finishes, exactly
        # the "doesn't stop promptly" bug this bounded pool was supposed
        # to avoid. Managed manually instead, so the cancelled path can
        # call `shutdown(wait=False, cancel_futures=True)` -- dropping
        # every not-yet-started queued frame immediately and not waiting
        # on whichever are already mid-flight (those already have
        # `cancel_event` passed through to `run_cancelable`, so they
        # self-terminate promptly on their own regardless).
        frame_executor = ThreadPoolExecutor(max_workers=_FRAME_DETECTION_MAX_WORKERS)
        try:
            frame_futures = {
                frame_executor.submit(
                    deps.poster_detector.detect, frame, cancel_event=cancel_event
                ): frame
                for frame in unique_frames
            }
            for future in as_completed(frame_futures):
                if cancel_event.is_set():
                    logger.info(
                        "visual fallback candidate extraction job lost the "
                        "race (cancelled) after detecting %d/%d frame(s)",
                        len(candidates),
                        len(unique_frames),
                    )
                    break
                candidates.extend(future.result())
        finally:
            # `cancel_futures=True` requires Python 3.9+; this project
            # requires >=3.11 (see pyproject.toml). Also reached, not just
            # the cancelled `break` above, if `future.result()` raised --
            # dropping queued/abandoned frame futures promptly here too.
            frame_executor.shutdown(wait=False, cancel_futures=True)
            # `cancel_futures=True` only drops futures that hadn't
            # started yet; whichever were already running keep running
            # in the background regardless. Give those a bounded window
            # to finish before this function's own `finally` (below)
            # removes `frames_dir` -- see `_FRAME_DETECTION_ABANDON_GRACE_SECONDS`.
            wait(frame_futures, timeout=_FRAME_DETECTION_ABANDON_GRACE_SECONDS)
        return _JobOutcome(source=SourceTag.FRAME_VISUAL, candidates=candidates)
    finally:
        shutil.rmtree(frames_dir, ignore_errors=True)


def _run_in_daemon_thread(fn: Callable[..., object], *args: object) -> "Future":
    """Run `fn(*args)` in a plain daemon thread, returning a `Future` for
    its result -- used for every job `_race_candidate_jobs` starts
    (`_prepare_video`/`_prepare_audio`/`_cleanup_audio_temp_dir`, AND all
    four actual race jobs) instead of submitting them to a
    `ThreadPoolExecutor`.

    Why NOT a pool: `concurrent.futures.thread` registers a process-wide
    `atexit` hook that joins EVERY worker thread of EVERY
    `ThreadPoolExecutor` ever created in the process before the process is
    allowed to exit at all -- regardless of that executor's own
    `shutdown()` having already been called with `wait=False`. For a
    long-running caller (the GUI) that's invisible: nothing waits on the
    process actually exiting. But for a short-lived one
    (`reel2movie/cli.py`: fetch one reel, print the result, exit) it would
    silently reintroduce exactly the latency this fix eliminates --
    `run_pipeline()` itself would still return promptly, but the PROCESS
    would then hang at exit for however long the backgrounded video
    download/audio extraction (or any other still-in-flight job) takes. A
    `daemon=True` `threading.Thread` is not tracked by that hook, so the
    process can exit immediately once nothing else is keeping it alive --
    the thread is simply abandoned mid-flight if that happens, the same
    "runs to completion or gets abandoned, result discarded" contract as
    everywhere else in this fix.

    Originally used only for the three fire-and-forget prep/cleanup jobs,
    with the four actual race jobs still on their own `ThreadPoolExecutor`
    -- generalized to cover those too once it became clear an
    uncancellable blocking call inside a race job (e.g.
    `VISION_BACKEND=anthropic_api`'s `AnthropicVisionChatClient.chat()`,
    which cannot honor `cancel_event`) could leave a pool worker thread
    blocked past `_race_candidate_jobs`'s own bounded grace period too,
    reintroducing the exact same process-exit-hang bug this function was
    built to eliminate, just via a different code path. Safe to
    generalize: daemon-ness only affects whether the interpreter waits for
    a thread at process exit, never in-process behavior (results,
    exceptions, and `as_completed()`/`wait()`'s handling of the returned
    `Future`s are all unaffected), so this was a mechanical substitution,
    not a logic change -- see `_race_candidate_jobs`'s docstring. (The
    nested per-frame vision-LLM pool inside `_extract_from_visual`
    remains a real `ThreadPoolExecutor` -- that one was judged too risky
    to convert the same way in this pass; see its own docstring and the
    module docstring's Fix 2 note.)

    The returned `Future` behaves exactly like one `ThreadPoolExecutor.submit()`
    would hand back (same class, from the same `concurrent.futures`
    module) -- `_wait_or_cancelled`/`as_completed()`/`wait()`/`.result()`
    callers can't tell the difference and don't need to.
    """
    future: Future = Future()

    def _run() -> None:
        try:
            future.set_result(fn(*args))
        except BaseException as exc:  # pragma: no cover -- fn()s here never raise
            future.set_exception(exc)

    threading.Thread(target=_run, daemon=True).start()
    return future


def _prepare_video(result: IngestResult, deps: PipelineDeps) -> Path | None:
    """Background job: download the video for `result`.

    Runs on its own daemon thread (via `_run_in_daemon_thread` -- see its
    docstring for why not the race pool), started immediately alongside
    the four candidate jobs by `_race_candidate_jobs` rather than as a
    blocking prerequisite step run before the race even starts (see
    module docstring's Fix 1 note) -- this is what lets the caption and
    creator-comment jobs, which need neither video nor audio, finish
    without ever waiting on a download.

    Never raises: `deps.ingestor.ensure_video()` failing is caught and
    represented as `None` instead -- `_extract_from_visual` (directly) and
    `_extract_from_audio_transcript` (via `_prepare_audio`) both already
    treat a `None` video path as "nothing to work with, contribute an
    empty outcome" rather than erroring.
    """
    try:
        return deps.ingestor.ensure_video(result)
    except Exception:
        logger.exception(
            "ensure_video failed; visual and audio-transcript race jobs "
            "will be skipped for this reel"
        )
        return None


# Bounded safety-net timeout for `_prepare_audio`'s wait on
# `_prepare_video`'s `Future`. `InstagramIngestor.ensure_video()` (the
# yt-dlp download `_prepare_video` blocks on) has no cancellation/timeout
# support of its own (see its own docstring) -- if its network call
# genuinely hangs forever (sustained throttling, a dropped connection
# yt-dlp's own retries never recover from), `_prepare_video`'s daemon
# thread leaks permanently regardless of anything here. Without this
# timeout, `_prepare_audio` blocking unboundedly on `video_future.result()`
# would leak a SECOND permanently-blocked daemon thread on top of that,
# and `_cleanup_audio_temp_dir` a THIRD waiting on `_prepare_audio`'s own
# future in turn -- 2-3 leaked threads per problem reel instead of 1,
# accumulating for the life of a long-lived caller (the GUI). This bounds
# that cascade to just `_prepare_video`'s own (unavoidable from here) leak
# -- it does NOT fix that leak itself, which needs yt-dlp's own
# cancellation support (out of scope). 300s (a few minutes) mirrors this
# codebase's other "a few minutes is a reasonable worst case for one
# reel" budget (`tmdb/resolver.py`'s `resolve_candidate_with_retry()`
# default `deadline_seconds`).
_VIDEO_DOWNLOAD_WAIT_TIMEOUT_SECONDS = 300.0


def _prepare_audio(
    video_future: "Future[Path | None]",
    deps: PipelineDeps,
    cancel_event: threading.Event,
) -> Path | None:
    """Background job: wait for `_prepare_video`'s result, then extract
    its audio track.

    Takes `video_future` rather than a `video_path` directly because
    `_prepare_video` and `_prepare_audio` both run on their own daemon
    threads (via `_run_in_daemon_thread`), started together by
    `_race_candidate_jobs` -- this function's own thread does the waiting
    via `video_future.result()`, not the orchestrator.

    `cancel_event` is passed straight through to `extract_audio`, which
    (unlike `ensure_video`/yt-dlp -- see `ingest.instagram.InstagramIngestor
    .ensure_video`'s docstring) already supports it: once a text job has
    won the race and set `cancel_event`, an audio extraction still in
    flight gets killed promptly via `run_cancelable` instead of needlessly
    running to completion.

    Never raises: returns `None` on either `_prepare_video` having failed
    (nothing to extract audio from) or `extract_audio` itself failing
    (including being cancelled) -- both already tolerated by
    `_extract_from_audio_transcript` as "nothing to work with". The temp
    directory `extract_audio` writes into is cleaned up immediately on
    failure here (nothing will ever read it); on success, cleanup is the
    separate `_cleanup_audio_temp_dir` background job's responsibility,
    since the audio-transcript race job still needs the file to exist
    after this function returns.

    Logging follows this module's error-isolation policy (see module
    docstring), even though this job isn't run through `_run_job_safely`
    itself: `extract_audio` raising `SubprocessCancelled` is the NORMAL,
    expected outcome whenever a fast text job wins the race while audio
    extraction is still in flight -- the common case for most successful
    runs once an `AudioTranscriber` is configured -- so it's logged at
    INFO ("lost the race"), not as an error. Any OTHER exception is a
    genuine unexpected failure and is still logged via `logger.exception`
    (full traceback).

    Also returns `None` immediately, without even waiting on
    `video_future`, when `deps.audio_transcriber` is `None` (no
    `AudioTranscriber` configured at all -- see
    `PipelineDeps.audio_transcriber`'s docstring): nothing will ever read
    the extracted audio in that case (`_extract_from_audio_transcript`
    bails out just as early, for the same reason), so there is no point
    running a real ffmpeg subprocess -- or even waiting for the video
    download to finish -- only to throw the result away unused. This is
    the common case for a `PipelineDeps` that never sets one.

    `video_future.result()` is bounded by
    `_VIDEO_DOWNLOAD_WAIT_TIMEOUT_SECONDS`, not waited on unboundedly --
    see that constant's own comment for why: `_prepare_video`'s own
    `ensure_video()` (yt-dlp) has no cancellation/timeout support at all,
    so if its network call genuinely hangs forever, THIS function
    blocking on it unboundedly would leak a second permanently-blocked
    daemon thread on top of `_prepare_video`'s own leaked one (and
    `_cleanup_audio_temp_dir` a third, waiting on this function's future
    in turn) -- this timeout stops that cascade, though it does not (and
    cannot, from here) fix `_prepare_video`'s own thread leaking if
    `ensure_video()` truly never returns.
    """
    if deps.audio_transcriber is None:
        return None

    try:
        video_path = video_future.result(
            timeout=_VIDEO_DOWNLOAD_WAIT_TIMEOUT_SECONDS
        )
    except TimeoutError:
        logger.warning(
            "timed out after %.0fs waiting for the video download before "
            "extracting audio; audio-transcript race job will be skipped "
            "for this reel (the download itself is left running in the "
            "background -- see _VIDEO_DOWNLOAD_WAIT_TIMEOUT_SECONDS)",
            _VIDEO_DOWNLOAD_WAIT_TIMEOUT_SECONDS,
        )
        return None
    # Anything else: _prepare_video never raises.
    if video_path is None:
        return None

    try:
        audio_temp_dir = Path(tempfile.mkdtemp(prefix="reel2movie_audio_"))
    except OSError:
        logger.exception(
            "failed to create a temp directory for audio extraction; "
            "audio-transcript race job will be skipped for this reel"
        )
        return None

    try:
        return extract_audio(video_path, audio_temp_dir, cancel_event=cancel_event)
    except SubprocessCancelled:
        logger.info(
            "audio extraction lost the race (cancelled); audio-transcript "
            "race job will be skipped for this reel"
        )
        shutil.rmtree(audio_temp_dir, ignore_errors=True)
        return None
    except Exception:
        logger.exception(
            "extract_audio failed; audio-transcript race job will be "
            "skipped for this reel"
        )
        shutil.rmtree(audio_temp_dir, ignore_errors=True)
        return None


def _cleanup_audio_temp_dir(
    audio_future: "Future[Path | None]",
    audio_transcript_job_future: "Future[_JobOutcome]",
) -> None:
    """Background job: remove `_prepare_audio`'s temp directory once BOTH
    it and the audio-transcript race job (the only job that ever reads
    `audio.wav`) have finished.

    Waiting for both -- not just `_prepare_audio` -- matters: deleting the
    directory as soon as extraction finishes would race with the
    transcript job still reading `audio.wav` if it hasn't gotten to it
    yet. A dedicated background job (rather than inline cleanup inside
    `_extract_from_audio_transcript` itself) means this works uniformly no
    matter how the transcript job ends -- success, cancelled, crashed, or
    never having touched `audio_future` at all (e.g. no `AudioTranscriber`
    configured, or it lost the race before extraction even finished) --
    without that job needing any cleanup logic of its own.

    Runs on its own daemon thread (via `_run_in_daemon_thread`), like the
    two prep jobs and for the same reason -- its own future is never
    waited on by the orchestrator, it simply finishes in the background
    whenever `_prepare_audio` and the transcript job both do.
    """
    audio_path = audio_future.result()  # _prepare_audio never raises
    audio_transcript_job_future.result()  # never raises; see _run_job_safely
    if audio_path is not None:
        shutil.rmtree(audio_path.parent, ignore_errors=True)


# Fixed submission order for the four race jobs, reused by
# `_race_candidate_jobs` for the no-winner pooled return's stable
# ordering.
_RACE_SOURCES: tuple[SourceTag, ...] = (
    SourceTag.CAPTION,
    SourceTag.CREATOR_COMMENT,
    SourceTag.AUDIO_TRANSCRIPT,
    SourceTag.FRAME_VISUAL,
)

# After a winner is found, how long `_race_candidate_jobs` gives the other
# three race jobs to react to `cancel_event` and finish on their own
# before giving up on them and returning anyway. In the overwhelmingly
# common case this is never actually used up: a losing caption/comment
# job is either already done or finishes within about one
# `run_cancelable` poll interval (~0.2s) of `cancel_event` firing, and a
# losing audio-transcript/visual job bails out immediately without
# touching its prep `Future` at all once it sees `cancel_event` already
# set (see their docstrings) -- so this grace period's only real job is
# capping the narrow, unlikely race where one of those two jobs started
# running and began blocking on a slow `_prepare_video`/`_prepare_audio`
# Future a moment BEFORE `cancel_event` was set, so it's not left
# waiting on an arbitrarily slow, uncancellable download/extraction
# (defeating this subtask's whole point) just to log its own loss.
_RACE_LOSER_GRACE_SECONDS = 2.0


def _race_candidate_jobs(result: IngestResult, deps: PipelineDeps) -> list[_JobOutcome]:
    """Run the four candidate-generating jobs concurrently -- together
    with video download + audio extraction as two more fire-and-forget
    background jobs (see module docstring's Fix 1 note) -- and return
    whichever outcome(s) "won".

    All four race jobs AND the two prep jobs now run via
    `_run_in_daemon_thread` (plain daemon threads, not a
    `ThreadPoolExecutor`) -- see that function's docstring for why: a
    `ThreadPoolExecutor` worker thread is joined by a process-wide
    `atexit` hook regardless of the executor's own `shutdown(wait=False)`,
    which can hang a short-lived caller's process exit on however long an
    in-flight job takes. This used to apply only to the three
    fire-and-forget prep jobs, with the four actual race jobs still on
    their own `ThreadPoolExecutor` -- but an uncancellable blocking call
    inside a race job (e.g. `VISION_BACKEND=anthropic_api`'s
    `AnthropicVisionChatClient.chat()`, which cannot honor `cancel_event`
    -- see its own docstring) could leave that pool's worker thread
    blocked past this function's own bounded grace period too, which the
    atexit hook would then still wait on. Generalizing to daemon threads
    here closes that gap: daemon-ness only affects whether the
    interpreter waits for a thread at process exit, never in-process
    behavior, so this is a mechanical substitution for
    `ThreadPoolExecutor.submit()` -- `_run_in_daemon_thread` already
    returns a plain `concurrent.futures.Future`, which `as_completed()`/
    `wait()` consume identically regardless of what created it. (The
    nested per-frame vision-LLM pool inside `_extract_from_visual` is a
    separate, SEPARATELY-DECIDED case -- see that function's docstring
    and the module docstring's Fix 2 note for why it is NOT converted the
    same way.)

    One shared `threading.Event`, passed as every job's `cancel_event`.
    The four race jobs' futures are consumed via `as_completed()` in
    actual completion order (not submission order); the two prep jobs'
    and the cleanup job's are not part of that loop at all:
    `_extract_from_visual` and `_extract_from_audio_transcript` each wait
    on the relevant prep `Future` internally, within their own job
    function, so only the race jobs that actually need that data ever
    wait for it.

    As each of the four race jobs completes, its outcome is checked with
    `_is_confident()` (imported `HIGH_CONFIDENCE` bar, same as the old
    waterfall's "confident" gate). The FIRST job whose outcome passes it
    wins: the shared `cancel_event` is set immediately (so the other race
    jobs stop/get killed within about one `run_cancelable` poll interval,
    ~0.2s), and the loop stops consuming further completions.

    Unlike the original sequential waterfall, this function does NOT wait
    unboundedly for every submitted job to finish before returning once a
    winner is found. After setting `cancel_event`, it gives the other
    three race jobs up to `_RACE_LOSER_GRACE_SECONDS` (a short, bounded
    grace period -- see that constant's own comment for why this is
    almost never actually waited out in practice) to react and finish on
    their own, then returns regardless of whether they have. Since EVERY
    job here (all four race jobs plus the two prep jobs and the cleanup
    job) runs on a plain daemon thread rather than inside a
    `ThreadPoolExecutor`, this function returning never leaves anything
    behind that a process-wide `atexit` hook would still wait on at exit
    -- NEITHER this function NOR the process itself ever ends up blocked
    on however long a still-running job takes, which matters not just for
    this function returning promptly but for a short-lived caller's whole
    PROCESS being able to exit promptly too (see `_run_in_daemon_thread`'s
    docstring). This is the actual point of this subtask's fix: a fast,
    confident caption/comment job must not pay for however long the video
    download + audio extraction (or a slow/uncancellable race job) takes.

    If NO job ever crosses the confidence bar, every one of the four race
    jobs is necessarily waited for in full (the loop never had a reason to
    stop early) -- which also means `_extract_from_visual`/
    `_extract_from_audio_transcript` have each already finished waiting on
    their own prep `Future` by then, so pooling ALL FOUR jobs' candidates
    together (union, not just one) never actually needs to wait on the
    prep jobs again itself.

    Return shape (chosen for a clean, unambiguous call site in both
    `run_pipeline` and `run_pipeline_streaming`): a 1-element list
    `[winner]` when a job won the race: `winner.raw_text` (if set) is the
    one and only piece of extra disambiguation context available. A
    4-element list `[outcome, outcome, outcome, outcome]` (one per job, in
    `_RACE_SOURCES` order) when no job won -- every job's `candidates`
    must be pooled, and (per `_resolve_all`'s docstring) no single job's
    `raw_text` is treated as "the" disambiguation context in this case
    even if the audio job happened to produce one. Callers can distinguish
    the two cases with `len(outcomes) == 1`.
    """
    cancel_event = threading.Event()
    # Every job below -- the two prep jobs and all four race jobs -- runs
    # on its own plain daemon thread via `_run_in_daemon_thread`, NOT a
    # `ThreadPoolExecutor` (see this function's and `_run_in_daemon_thread`'s
    # docstrings for why: a pool worker thread is joined by a process-wide
    # `atexit` hook regardless of `shutdown(wait=False)`, which matters
    # for a short-lived caller like `reel2movie/cli.py`).
    video_future = _run_in_daemon_thread(_prepare_video, result, deps)
    audio_future = _run_in_daemon_thread(_prepare_audio, video_future, deps, cancel_event)

    caption_future = _run_in_daemon_thread(
        _run_job_safely,
        SourceTag.CAPTION,
        lambda: _extract_from_caption(result, deps, cancel_event),
    )
    comment_future = _run_in_daemon_thread(
        _run_job_safely,
        SourceTag.CREATOR_COMMENT,
        lambda: _extract_from_creator_comments(result, deps, cancel_event),
    )
    audio_transcript_future = _run_in_daemon_thread(
        _run_job_safely,
        SourceTag.AUDIO_TRANSCRIPT,
        lambda: _extract_from_audio_transcript(audio_future, deps, cancel_event),
    )
    visual_future = _run_in_daemon_thread(
        _run_job_safely,
        SourceTag.FRAME_VISUAL,
        lambda: _extract_from_visual(result, deps, video_future, cancel_event),
    )
    _run_in_daemon_thread(_cleanup_audio_temp_dir, audio_future, audio_transcript_future)

    race_futures = [caption_future, comment_future, audio_transcript_future, visual_future]

    outcomes_by_source: dict[SourceTag, _JobOutcome] = {}
    winner: _JobOutcome | None = None
    for future in as_completed(race_futures):
        outcome = future.result()  # _run_job_safely never raises
        outcomes_by_source[outcome.source] = outcome
        if _is_confident(outcome.candidates):
            winner = outcome
            cancel_event.set()
            break

    if winner is not None:
        # Bounded, best-effort grace period for the other three race
        # jobs to react to `cancel_event` and finish -- see
        # `_RACE_LOSER_GRACE_SECONDS`'s comment for why this hardly
        # ever actually blocks for the full period. Not waiting at
        # all here would make e.g. a losing job's own error-isolation
        # log line (or a test observing its cancellation) a pure
        # race against this function returning; this still returns
        # promptly either way regardless of whether this grace period
        # was fully used -- no executor to shut down here, and a
        # still-running daemon thread past this point is simply
        # abandoned, exactly like every other background job in this
        # function.
        wait(race_futures, timeout=_RACE_LOSER_GRACE_SECONDS)
        return [winner]

    # No winner: every race job was necessarily waited for above (the
    # loop never broke early), so pool all four -- in stable,
    # submission order.
    return [outcomes_by_source[source] for source in _RACE_SOURCES]


def _disambiguation_context(result: IngestResult, transcript: str | None) -> str:
    """Build the disambiguation `context` string: the caption, plus the
    audio transcript concatenated on when one is available (never a
    replacement for the caption -- both are kept).

    `transcript` is `None` unless `_race_candidate_jobs` returned a single
    *winning* outcome that came from the audio-transcript job (see
    `_race_candidate_jobs`'s and `_resolve_all`'s docstrings) -- in the
    no-winner pooled case, or when any other job won, this stays `None`
    and the context is just the caption, exactly as before this feature.
    """
    if not transcript:
        return result.caption
    return f"{result.caption}\n\n{transcript}"


def _resolve_all(
    candidates: list[Candidate],
    deps: PipelineDeps,
    result: IngestResult,
    *,
    transcript: str | None = None,
) -> list[Recommendation]:
    """flow.md step [5]: resolve every winning candidate against TMDB.

    Resolves sequentially, one candidate at a time, via
    `resolve_candidate_with_retry()` -- the SAME capped-exponential-backoff
    retry wrapper `run_pipeline_streaming()` uses, not the plain
    `resolve_candidate()` this function used before this fix. Deliberately
    kept sequential rather than switched to concurrent resolution like
    `run_pipeline_streaming()`: `run_pipeline()`'s return contract is one
    complete, already-deduped `PipelineResult` (no streaming, no
    completion-order concern), so there is no behavior here that actually
    needs concurrency -- going concurrent would only add complexity
    without changing what gets returned, since every resolution has to
    finish before `dedupe_recommendations` runs regardless. Sequential-but-retried is the
    smallest change that closes the actual gap (every candidate now gets
    the same ~5-minute transient-TMDB-failure resilience
    `run_pipeline_streaming()` already had, instead of giving up after
    `tmdb/client.py`'s own internal 3 attempts).

    Per flow.md's explicit rule, a candidate that fails to resolve is
    KEPT with `tmdb=None`, never dropped. A `resolve_candidate_with_retry`
    call that raises (rather than cleanly returning `None` once its
    deadline is exhausted) is treated the same way -- one candidate's
    lookup failing is not a reason to lose every other candidate's
    recommendation or abort the run.

    `result` (the original `IngestResult`) is threaded through here only
    for `result.caption` -- passed as `resolve_candidate()`'s `context`
    for its caption-context disambiguation step (see PROGRESS.md's
    "Follow-up — disambiguate tied exact matches" section). The caption
    is the most reliably-present single text signal per flow.md's own
    design, which is why it -- not the comment/visual text that may have
    actually produced the winning candidate -- is used as the baseline
    disambiguation context for every candidate, regardless of which race
    job it came from.

    `transcript`, if given (only ever the WINNING race outcome's
    `raw_text`, and only when that winner was the audio-transcript job --
    see `run_pipeline`/`run_pipeline_streaming`), is concatenated onto the
    caption (`f"{result.caption}\\n\\n{transcript}"`, via
    `_disambiguation_context` -- never a replacement for it) to give the
    disambiguation step extra context from what the creator actually said
    out loud.
    """
    context = _disambiguation_context(result, transcript)
    return [_resolve_one(candidate, deps, context) for candidate in candidates]


def _resolve_one(candidate: Candidate, deps: PipelineDeps, context: str) -> Recommendation:
    """Resolve one candidate against TMDB and wrap the result in a
    `Recommendation` -- the "resolve, then build a `Recommendation`,
    keeping it with `tmdb=None` on failure" logic `_resolve_all` and
    `run_pipeline_streaming` both need, factored out so it's written once
    instead of twice.

    `candidate.media_type_hint` (set by `select_primary_candidates()` --
    see `_apply_primary_candidate_filter` -- or `None` for a candidate
    that was never passed through that filter) is threaded straight
    through to `resolve_candidate_with_retry()`'s own `media_type_hint`
    param.

    Never raises: a `resolve_candidate_with_retry` call that raises
    (rather than cleanly returning `None` once its deadline is exhausted)
    is logged via `logger.exception` and treated the same as a clean
    `None` -- one candidate's lookup failing is never a reason to lose
    its `Recommendation` entirely (per flow.md's "kept, not dropped"
    rule) or to propagate out to either caller.
    """
    try:
        resolved = resolve_candidate_with_retry(
            candidate,
            deps.tmdb_client,
            context=context,
            chat_client=deps.disambiguation_chat_client,
            media_type_hint=candidate.media_type_hint,
        )
    except Exception:
        logger.exception(
            "TMDB resolution failed for %r; keeping as unresolved",
            candidate.raw_text,
        )
        resolved = None
    return Recommendation(
        query=candidate.raw_text,
        source=candidate.source,
        confidence=candidate.confidence,
        tmdb=resolved,
    )


def dedupe_recommendations(recommendations: list[Recommendation]) -> list[Recommendation]:
    """flow.md step [6]: merge same-TMDB-id recommendations, sort by confidence.

    Public (not module-private): `gui/workers.py`'s `PipelineRunner` calls
    this directly across the package boundary to post-process
    `run_pipeline_streaming()`'s raw yielded `Recommendation`s into the
    same deduped/sorted shape `run_pipeline()` itself returns -- see its
    own docstring for why. Promoted from the old `_dedupe` name once that
    cross-module reuse became a real, load-bearing contract rather than
    an internal implementation detail.

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


def _fetch_and_race(
    url: str, deps: PipelineDeps
) -> tuple[IngestResult, list[_JobOutcome]]:
    """Shared step [1]-[4] sequence for both `run_pipeline` and
    `run_pipeline_streaming`: fetch metadata, then race the four
    candidate-generating jobs (video download + audio extraction run as
    two more jobs in that same race -- see module docstring's Fix 1 note
    and `_race_candidate_jobs` -- not as a blocking step beforehand).

    Step [1] (`deps.ingestor.fetch_metadata`) is deliberately NOT wrapped
    in a try/except: an unreachable/unsupported link must fail the whole
    pipeline immediately, per flow.md's error-handling rule, so any
    exception it raises propagates straight out of this function (and
    thus out of both callers).

    Returns the original `IngestResult` (both callers need `result.caption`
    for disambiguation context) plus `_race_candidate_jobs`'s outcome list
    (see its docstring for the exact return shape).
    """
    result = deps.ingestor.fetch_metadata(url)
    outcomes = _race_candidate_jobs(result, deps)
    return result, outcomes


def _pool_candidates_and_transcript(
    outcomes: list[_JobOutcome],
) -> tuple[list[Candidate], str | None]:
    """Flatten `_race_candidate_jobs`'s outcome list into `(candidates,
    transcript)`.

    `candidates` is always every outcome's candidates concatenated --
    for a single winning outcome (`len(outcomes) == 1`) that's just the
    winner's own candidates; for the no-winner pooled case
    (`len(outcomes) == 4`) that's the union of all four, per
    `_race_candidate_jobs`'s contract.

    `transcript` is the winning outcome's `raw_text` ONLY when there IS a
    single winner (never in the 4-outcome pooled case, even though the
    audio job may have produced a transcript there too) -- see
    `_resolve_all`'s docstring for why only a genuine winner's transcript
    is ever used as disambiguation context.
    """
    candidates = [c for outcome in outcomes for c in outcome.candidates]
    transcript = outcomes[0].raw_text if len(outcomes) == 1 else None
    return candidates, transcript


def _primary_candidate_source_text(winner: _JobOutcome, result: IngestResult) -> str:
    """The text that actually PRODUCED `winner`'s candidates -- handed to
    `select_primary_candidates()` (see `_apply_primary_candidate_filter`)
    as the "what is this text actually recommending" signal, so noise-
    filtering decisions are judged against the text that produced the
    candidates, not always `result.caption` (which would defeat the
    point of this fix for a non-caption winner).

    - `SourceTag.CAPTION`: `result.caption` itself.
    - `SourceTag.CREATOR_COMMENT`: every creator top-level comment's text
      joined together (the SAME comments `_extract_from_creator_comments`
      reads -- see its docstring for the exact filter) -- there is no
      single "the" comment once a creator has posted more than one, and a
      candidate from any of them could be the real recommendation.
      Falls back to `result.caption` in the (should-be-unreachable) case
      a creator-comment job won with no matching comments.
    - `SourceTag.AUDIO_TRANSCRIPT`: `winner.raw_text` (the transcript
      text) -- the only race outcome that ever carries one, see
      `_JobOutcome`'s docstring. Falls back to `result.caption` if it's
      somehow unset.
    - `SourceTag.FRAME_VISUAL` (or any other/future source): no raw TEXT
      signal exists for this source at all -- it's extracted from pixels,
      not words -- so `result.caption` is the best available fallback,
      same baseline every resolution already uses for disambiguation
      context.
    """
    if winner.source == SourceTag.CAPTION:
        return result.caption
    if winner.source == SourceTag.CREATOR_COMMENT:
        creator_comment_texts = [
            comment.text for comment in _creator_top_level_comments(result)
        ]
        return "\n\n".join(creator_comment_texts) or result.caption
    if winner.source == SourceTag.AUDIO_TRANSCRIPT:
        return winner.raw_text or result.caption
    return result.caption


def _apply_primary_candidate_filter(
    outcomes: list[_JobOutcome],
    candidates: list[Candidate],
    result: IngestResult,
    deps: PipelineDeps,
) -> list[Candidate]:
    """Filter noise out of the race WINNER's candidate pool via
    `text_extraction.candidate_disambiguation.select_primary_candidates`
    (Problem A -- see that module's docstring), called exactly ONCE, right
    after the race resolves and before TMDB resolution starts.

    Only applies when there IS a single winning outcome
    (`len(outcomes) == 1`, per `_race_candidate_jobs`'s return contract):
    in the no-winner pooled case (`len(outcomes) == 4`), each of the four
    jobs independently contributed at most its own handful of candidates,
    and there is no single coherent `source_text` to hand the model --
    caption, comment, transcript, and visual are four unrelated signals,
    none of which is uniquely "the" text that produced this pool -- so
    filtering is skipped there and every pooled candidate is resolved
    exactly as before this feature existed.

    Reuses `deps.disambiguation_chat_client` (no new `PipelineDeps` field)
    -- when it's `None` (not configured), this filter is skipped
    entirely, same "feature not available" posture `resolve_candidate()`'s
    pre-existing disambiguation step already takes for a missing
    chat_client.
    """
    if len(outcomes) != 1 or deps.disambiguation_chat_client is None:
        return candidates

    winner = outcomes[0]
    source_text = _primary_candidate_source_text(winner, result)
    return select_primary_candidates(
        candidates, source_text, deps.disambiguation_chat_client
    )


def run_pipeline(url: str, deps: PipelineDeps) -> PipelineResult:
    """Run the full candidate-extraction race + TMDB resolution for `url`,
    returning one complete, deduped `PipelineResult` -- unchanged return
    contract from the old sequential waterfall, for every existing caller
    (the CLI, existing tests).

    Internally: `_fetch_and_race` runs the shared fetch/race sequence (see
    its docstring); `_apply_primary_candidate_filter` then filters noise
    out of the winner's pool (see its own docstring for when it does/
    doesn't apply); the surviving candidates are resolved against TMDB
    via `_resolve_all` (sequential, with the same
    `resolve_candidate_with_retry` resilience `run_pipeline_streaming`
    uses -- see `_resolve_all`'s docstring) and `dedupe_recommendations`.
    """
    result, outcomes = _fetch_and_race(url, deps)
    candidates, transcript = _pool_candidates_and_transcript(outcomes)
    candidates = _apply_primary_candidate_filter(outcomes, candidates, result, deps)

    recommendations = _resolve_all(candidates, deps, result, transcript=transcript)
    deduped_recommendations = dedupe_recommendations(recommendations)
    return PipelineResult(reel_url=url, recommendations=deduped_recommendations)


def run_pipeline_streaming(
    url: str, deps: PipelineDeps
) -> Iterator[Recommendation]:
    """Run the same fetch/race sequence as `run_pipeline`, then resolve the
    winning pool's candidates against TMDB CONCURRENTLY, yielding each
    `Recommendation` as soon as it resolves -- not deduped, not sorted,
    raw, one at a time, in completion order (not necessarily input
    order).

    Uses a SEPARATE `concurrent.futures.ThreadPoolExecutor` (distinct from
    `_race_candidate_jobs`'s, which has already finished by this point),
    running `_resolve_one` (the same per-candidate resolve-then-wrap
    helper `_resolve_all` uses) per candidate via `as_completed()`.
    `_resolve_one` never raises (see its own docstring), so there is
    nothing for this generator to catch -- a candidate whose resolution
    failed already comes back as an unresolved (`tmdb=None`)
    `Recommendation`, not an exception, so one candidate's lookup failing
    is never a reason to abort the whole stream for every other
    candidate.

    Same `_apply_primary_candidate_filter` noise-filtering pass as
    `run_pipeline`, applied right after pooling and before building
    `context`/launching any resolution.
    """
    result, outcomes = _fetch_and_race(url, deps)
    candidates, transcript = _pool_candidates_and_transcript(outcomes)
    candidates = _apply_primary_candidate_filter(outcomes, candidates, result, deps)
    context = _disambiguation_context(result, transcript)

    with ThreadPoolExecutor() as executor:
        futures = [
            executor.submit(_resolve_one, candidate, deps, context)
            for candidate in candidates
        ]
        for future in as_completed(futures):
            yield future.result()
