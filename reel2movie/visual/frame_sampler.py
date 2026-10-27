"""Sample still frames from a video, either sparsely (N equally-spaced
timestamps) or densely (every `interval_seconds`).

This is the visual-fallback path only (per `flow.md`, reached rarely in the
real pipeline, only once caption and creator-comment extraction both fail to
yield a confident candidate) — kept deliberately simple: no retry logic, no
parallel extraction, no video-reading library beyond the already-declared
`imageio-ffmpeg` dependency.

Uses `imageio_ffmpeg.get_ffmpeg_exe()` to locate the bundled ffmpeg binary
(no system ffmpeg/Homebrew install required or assumed) and invokes it
directly as a subprocess per timestamp with `-ss <timestamp> -frames:v 1` —
the standard, reliable way to grab a single frame at an exact seek point.
imageio's higher-level frame-reading API is not used here: it's built around
sequential/streamed reads, which is awkward for a handful of independent,
arbitrary-timestamp seeks.

Two public sampling strategies live here, for two different jobs:

- `sample_frames` — sparse, N equally-spaced samples within the *inner*
  5%-95% window of the video, used for poster/title-card detection. A
  poster/title card is typically held on screen for a while and is never
  the very first/last thing shown (intro bumpers, outros, black frames
  tend to sit at the very start/end), so skipping those edges avoids
  wasting samples on frames unlikely to show a poster at all.
- `sample_frames_at_interval` — dense, fixed-interval samples covering the
  WHOLE video including both edges, used for reading transient on-screen
  TEXT overlays (see `pipeline/waterfall.py`'s `_extract_from_visual` and
  this subtask's `PROGRESS.md` entry). Unlike a poster, a creator-burned
  text caption naming a movie can appear for as little as 1-2 seconds and
  can appear right at the start or end of a reel (e.g. a "swipe up for
  more" style intro card, or a final "which one's your favorite" card) —
  the 5%-95%-window dodge that's correct for poster detection would
  actively defeat dense text-reading sampling by skipping exactly the
  frames most likely to carry a quick title-card overlay. Its sampled
  range includes the ragged tail of the stream, so unlike `sample_frames`
  it tolerates a single timestamp's extraction failing: that timestamp is
  skipped (logged as a warning) and the remaining frames are still
  returned, rather than the whole call raising -- see its docstring's
  "Best-effort vs. all-or-nothing" section for the real-world bug that
  motivated this.

Both strategies share the same per-timestamp ffmpeg invocation (see
`_extract_frame_at`) — only which timestamps get requested, the output
filename pattern, and (as of the fix above) how a single timestamp's
failure is handled, differ between them.
"""

from __future__ import annotations

import logging
import re
import subprocess
import tempfile
import threading
from pathlib import Path

import imageio_ffmpeg

from reel2movie._subprocess_util import SubprocessCancelled, run_cancelable
from reel2movie.core.models import FrameSample

logger = logging.getLogger(__name__)


class FrameExtractionError(RuntimeError):
    """Raised when the ffmpeg subprocess fails to extract a frame.

    The message always includes ffmpeg's captured stderr when available
    (never swallowed), so the caller can see exactly why the extraction
    failed (bad video path, corrupt file, seek past EOF, timeout, an
    "exit 0 but wrote nothing" quirk, etc.) rather than just "ffmpeg
    exited 1".
    """


# A single-frame extraction should never legitimately take this long; a
# hung/corrupt input is treated as a failure rather than blocking forever.
_FFMPEG_TIMEOUT_SECONDS = 30

# Matches ffmpeg's stderr line of the form "Duration: 00:01:23.45" (also
# tolerates "N/A" durations not matching -- those correctly fail to match
# and are treated as "no Duration line found" below).
_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d\d):(\d\d\.\d+)")


def _compute_timestamps(n: int, duration_seconds: float) -> list[float]:
    """N equally-spaced timestamps within [0.05*duration, 0.95*duration].

    Excludes the first/last ~5% of duration to dodge intro bumpers, black
    frames, and outros. For n == 1, returns just the midpoint
    (0.5 * duration) rather than an edge of the 5%/95% window, since a
    single sample should be the most "representative" frame available.
    """
    if n == 1:
        return [0.5 * duration_seconds]

    start = 0.05 * duration_seconds
    end = 0.95 * duration_seconds
    step = (end - start) / (n - 1)
    return [start + i * step for i in range(n)]


def _extract_frame_at(
    video_path: Path,
    timestamp: float,
    frame_path: Path,
    *,
    cancel_event: "threading.Event | None" = None,
) -> None:
    """Extract a single frame from `video_path` at `timestamp` into `frame_path`.

    Shared by `sample_frames` and `sample_frames_at_interval` — the only
    difference between those two callers is WHICH timestamps/filenames get
    requested, never how a single frame is actually pulled out of the
    video, so that one subprocess invocation (with its timeout/error
    handling) lives here exactly once rather than being copy-pasted per
    caller.

    Invokes the `imageio_ffmpeg`-bundled ffmpeg binary directly:
    `ffmpeg -ss <timestamp> -i <video_path> -frames:v 1 -pix_fmt yuvj420p
    -y <frame_path>`, via `run_cancelable` so an in-flight extraction can
    be killed early if `cancel_event` fires (default `None` -- no
    cancellation, same behavior as before).

    Raises:
        FrameExtractionError: if the ffmpeg subprocess times out, returns
            a nonzero exit code, or returns exit code 0 but the expected
            output file is missing or empty (ffmpeg can exit 0 while
            writing nothing, e.g. "Output file is empty, nothing was
            encoded" when seeking near the edge of a sparse video) — the
            message includes ffmpeg's captured stderr when available.
        SubprocessCancelled: if `cancel_event` fires before ffmpeg
            finishes -- propagated as-is (not wrapped in
            `FrameExtractionError`), so callers can distinguish "this lost
            the race" from a real extraction failure.
    """
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    # -pix_fmt yuvj420p: forces a pixel format the mjpeg encoder always
    # accepts. Some source videos (including this module's own synthetic
    # testsrc fixture) decode to a pixel format (e.g. yuv444p, or
    # non-full-range yuv420p) that ffmpeg's mjpeg encoder rejects with
    # "Non full-range YUV is non-standard" / "Error while opening encoder"
    # and silently writes zero bytes. Forcing the format here is cheap and
    # fixes that without depending on how any given input video happens to
    # be encoded.
    command = [
        ffmpeg_exe,
        "-ss",
        str(timestamp),
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-pix_fmt",
        "yuvj420p",
        "-y",
        str(frame_path),
    ]
    try:
        result = run_cancelable(
            command,
            timeout_seconds=_FFMPEG_TIMEOUT_SECONDS,
            cancel_event=cancel_event,
        )
    except subprocess.TimeoutExpired as exc:
        raise FrameExtractionError(
            f"ffmpeg timed out after {_FFMPEG_TIMEOUT_SECONDS}s extracting "
            f"frame at timestamp {timestamp:.3f}s from {video_path}"
        ) from exc

    if result.returncode != 0:
        raise FrameExtractionError(
            f"ffmpeg failed to extract frame at timestamp {timestamp:.3f}s "
            f"from {video_path} (exit code {result.returncode}): "
            f"{result.stderr}"
        )

    # ffmpeg can exit 0 while writing nothing at all (observed: seeking
    # near the edge of a sparse video produces "Output file is empty,
    # nothing was encoded" in stderr alongside a zero exit code). Trust
    # the output file, not the exit code: it must exist and be non-empty.
    if not frame_path.exists() or frame_path.stat().st_size == 0:
        raise FrameExtractionError(
            f"ffmpeg reported success (exit code 0) extracting frame at "
            f"timestamp {timestamp:.3f}s from {video_path}, but the "
            f"output file {frame_path} is missing or empty. ffmpeg "
            f"stderr: {result.stderr}"
        )


def sample_frames(
    video_path: Path,
    n: int,
    duration_seconds: float,
    *,
    output_dir: Path | None = None,
    cancel_event: "threading.Event | None" = None,
) -> list[FrameSample]:
    """Extract N equally-spaced frames from `video_path` as JPEGs.

    Timestamps are computed by `_compute_timestamps` (see its docstring).
    Each frame is extracted via `_extract_frame_at` (a direct subprocess
    call to the `imageio_ffmpeg`-bundled ffmpeg binary).

    `cancel_event`, if given, lets a caller abort early (default `None` --
    no cancellation, same behavior as before), consistent with this
    module's other two functions (`sample_frames_at_interval`,
    `probe_duration_seconds`). Unlike `sample_frames_at_interval`'s
    best-effort partial-result contract, this function's contract stays
    all-or-nothing (see its docstring's rationale for why): cancelling
    simply lets whichever `_extract_frame_at` call is currently in flight
    raise `SubprocessCancelled`, which propagates straight out of this
    function uncaught -- there is no partial list of `FrameSample`s to
    salvage, since callers of this sparse, fixed-`n` function want exactly
    N frames or nothing.

    Output directory handling (caller-ownership question, resolved here):
    if `output_dir` is given, frames are written there (caller owns it,
    caller owns cleanup). If `output_dir` is None, a fresh directory is
    created via `tempfile.mkdtemp()` — deliberately NOT
    `tempfile.TemporaryDirectory()` as a context manager, because that
    context manager deletes the directory (and every frame in it) as soon
    as its `with` block exits, which would be *before* this function
    returns the `FrameSample`s pointing into it — the files would already
    be gone by the time the caller got the paths. `mkdtemp()` creates a
    directory that persists until something explicitly removes it, which
    is what we need: the caller receives live paths and is responsible for
    cleaning up that temp directory itself (e.g. `shutil.rmtree`) once it's
    done with the frames. This is documented here and in PROGRESS.md rather
    than silently handing back paths that evaporate.

    Raises:
        ValueError: if `n < 1` or `duration_seconds <= 0`.
        FrameExtractionError: if, for any timestamp, the ffmpeg subprocess
            times out, returns a nonzero exit code, or returns exit code 0
            but the expected output file is missing or empty (ffmpeg can
            exit 0 while writing nothing, e.g. "Output file is empty,
            nothing was encoded" when seeking near the edge of a sparse
            video) — the message includes ffmpeg's captured stderr when
            available.
        SubprocessCancelled: if `cancel_event` fires before the
            in-flight timestamp's ffmpeg call finishes -- propagated as-is
            (not wrapped in `FrameExtractionError`), same as
            `_extract_frame_at`'s own contract.
    """
    if n < 1:
        raise ValueError(f"n must be >= 1, got {n}")
    if duration_seconds <= 0:
        raise ValueError(f"duration_seconds must be > 0, got {duration_seconds}")

    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix="reel2movie_frames_"))
    else:
        output_dir.mkdir(parents=True, exist_ok=True)

    timestamps = _compute_timestamps(n, duration_seconds)

    samples: list[FrameSample] = []
    for i, timestamp in enumerate(timestamps):
        frame_path = output_dir / f"frame_{i:03d}.jpg"
        _extract_frame_at(video_path, timestamp, frame_path, cancel_event=cancel_event)
        samples.append(FrameSample(path=frame_path, timestamp_seconds=timestamp))

    return samples


def sample_frames_at_interval(
    video_path: Path,
    interval_seconds: float,
    duration_seconds: float,
    *,
    output_dir: Path | None = None,
    cancel_event: "threading.Event | None" = None,
) -> list[FrameSample]:
    """Extract frames from `video_path` every `interval_seconds`, start to end.

    Timestamps are `0.0, interval_seconds, 2*interval_seconds, ...` up to
    (exclusive of) `duration_seconds` -- a plain `while t < duration_seconds`
    walk, always yielding at least the `0.0` timestamp since
    `duration_seconds > 0` is enforced below. Deliberately NOT
    `sample_frames`'s 5%-95% window: that dodge exists to avoid intro/outro
    bumpers for POSTER detection, where a poster is unlikely to be the very
    first/last thing shown. This function exists for reading creator-burned
    ON-SCREEN TEXT overlays instead, which can legitimately appear right at
    the very start or end of a reel (e.g. an opening "swipe for more" card
    or a closing "which one's yours" card) -- skipping those edges here
    would defeat the whole point of dense sampling by skipping exactly the
    frames most likely to carry a quick title card. See the module
    docstring for the full `sample_frames` vs. `sample_frames_at_interval`
    rationale.

    Each frame is extracted via `_extract_frame_at` (shared with
    `sample_frames` -- see its docstring) for the actual ffmpeg
    invocation, but this function's *handling* of a per-timestamp failure
    deliberately differs from `sample_frames`'s -- see "Best-effort vs.
    all-or-nothing" below.

    Best-effort vs. all-or-nothing (real-world bug, now fixed): unlike
    `sample_frames`, a `FrameExtractionError` raised by `_extract_frame_at`
    for any ONE timestamp is caught here, logged as a warning (naming the
    failed timestamp and `video_path`), and that timestamp is skipped --
    extraction continues with the remaining timestamps, and whatever
    subset of `FrameSample`s succeeded is returned. If every timestamp
    fails, this returns `[]` rather than raising.

    This is intentionally NOT what `sample_frames` does (it still raises
    on the first failure, all-or-nothing, and that behavior is unchanged
    -- see its docstring and tests). The two functions can afford
    different contracts because their callers want different things:
    `sample_frames`'s sparse, fixed-`n` callers (poster detection) are
    built around getting back exactly the N frames they asked for, so a
    partial result would silently mean "poster detection ran on fewer/
    different samples than the caller thinks it configured" -- raising is
    the honest behavior there. `sample_frames_at_interval`'s dense,
    variable-length-list callers (on-screen text detection via
    `pipeline/waterfall.py`'s `_extract_from_visual`) already treat "how
    many frames came back" as an open question (it depends on video
    length and dedup), and a single bad timestamp out of what can be
    hundreds should not discard every other, perfectly good frame's worth
    of detections.

    This surfaced as a real production bug (not a hypothetical): running
    the full pipeline against a live Instagram reel
    (https://www.instagram.com/reel/DeCngQIST-o/) produced ZERO
    recommendations because a single tail timestamp (158.0s) hit the
    documented "ffmpeg reports exit code 0 but writes nothing" quirk (see
    `_extract_frame_at`'s docstring -- the same quirk `sample_frames`
    dodges by staying within its 5%-95% window). Before this fix, that one
    failing timestamp's `FrameExtractionError` propagated straight out of
    this function and `_extract_from_visual`'s broad
    `except Exception: return []` discarded all ~150 OTHER already-
    successfully-extracted frames' worth of detections along with it --
    silently turning "150 good frames and 1 bad one" into "no results at
    all". Because this function samples the full 0-to-duration range
    (including the ragged tail end of the stream, by design -- see the
    module docstring), any reel whose duration doesn't land cleanly on an
    interval boundary can hit this edge case, making it a routine
    occurrence here in a way it isn't for `sample_frames`'s windowed
    sampling.

    Output directory handling is identical to `sample_frames`'s: caller
    owns `output_dir` if given; otherwise a fresh `tempfile.mkdtemp()`
    directory is created and handed back for the caller to clean up (never
    a `TemporaryDirectory()` context manager -- see `sample_frames`'s
    docstring for why).

    Output filenames use a distinct `frame_{i:04d}.jpg` pattern (4 digits,
    not `sample_frames`'s 3) -- not because 3 digits would overflow at
    realistic reel lengths (a 60s reel at the default 1s interval needs
    only ~60 frames, well under 1000), but to make it visually obvious at a
    glance that these are a different function's output, in case a future
    caller ever points both functions at the same directory (they don't
    today, but nothing stops it from changing).

    Cancellation (`cancel_event`, default `None` -- no cancellation, same
    behavior as before): checked at the TOP of the per-timestamp loop
    (before even starting the next frame's `_extract_frame_at` call) so
    this stops requesting further frames promptly once cancelled, not
    just whenever the one ffmpeg call currently in flight happens to
    notice -- and also passed through to `_extract_frame_at` itself so
    that in-flight call gets killed too, rather than being left to run to
    completion.

    Chosen return contract on cancellation: whatever `FrameSample`s were
    successfully extracted BEFORE the cancellation is returned (a partial,
    best-effort result) -- the same "best effort, not all-or-nothing"
    philosophy this function already applies to a single timestamp's
    extraction failure (see "Best-effort vs. all-or-nothing" above), not a
    raised exception. This is deliberate, not an oversight: a caller
    racing this against other extraction methods wants whatever signal was
    already gathered, not to have it thrown away. To avoid this silently
    looking like "the video just had fewer frames than expected", a
    cancellation is always logged as a warning naming how many of the
    requested timestamps were actually attempted before stopping.

    Raises:
        ValueError: if `interval_seconds <= 0` or `duration_seconds <= 0`.

    Never raises `FrameExtractionError` for a per-timestamp ffmpeg
    failure (see "Best-effort vs. all-or-nothing" above) -- such failures
    are caught, logged, and skipped instead. Never raises
    `SubprocessCancelled` either -- see "Cancellation" above for why a
    cancellation instead returns the partial result gathered so far.
    """
    if interval_seconds <= 0:
        raise ValueError(
            f"interval_seconds must be > 0, got {interval_seconds}"
        )
    if duration_seconds <= 0:
        raise ValueError(f"duration_seconds must be > 0, got {duration_seconds}")

    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix="reel2movie_frames_"))
    else:
        output_dir.mkdir(parents=True, exist_ok=True)

    timestamps: list[float] = []
    t = 0.0
    while t < duration_seconds:
        timestamps.append(t)
        t += interval_seconds

    samples: list[FrameSample] = []

    def _log_cancelled(stage: str) -> None:
        logger.warning(
            "sample_frames_at_interval cancelled %s timestamp %.3fs from "
            "%s -- returning the %d/%d frame(s) already extracted",
            stage,
            timestamp,
            video_path,
            len(samples),
            len(timestamps),
        )

    for i, timestamp in enumerate(timestamps):
        # Checked BEFORE starting the next frame's extraction (not only
        # inside the except-clause below) so a cancellation stops further
        # ffmpeg calls from being requested at all, not just whichever one
        # happens to be in flight -- see the docstring's "Cancellation"
        # section.
        if cancel_event is not None and cancel_event.is_set():
            _log_cancelled("before")
            break

        frame_path = output_dir / f"frame_{i:04d}.jpg"
        try:
            _extract_frame_at(
                video_path, timestamp, frame_path, cancel_event=cancel_event
            )
        except SubprocessCancelled:
            _log_cancelled("mid-extraction at")
            break
        except FrameExtractionError as exc:
            # Best-effort: skip this one timestamp and keep going -- see
            # the docstring's "Best-effort vs. all-or-nothing" section for
            # why this differs from `sample_frames`'s raise-on-first-
            # failure behavior.
            logger.warning(
                "skipping frame at timestamp %.3fs from %s: extraction "
                "failed (%s)",
                timestamp,
                video_path,
                exc,
            )
            continue
        samples.append(FrameSample(path=frame_path, timestamp_seconds=timestamp))

    return samples


def probe_duration_seconds(
    video_path: Path, *, cancel_event: "threading.Event | None" = None
) -> float:
    """Determine a video's duration by probing the actual file on disk.

    `imageio-ffmpeg` bundles only the `ffmpeg` binary, not `ffprobe`, so
    this uses the standard "ffmpeg with no output" technique: running
    `ffmpeg -i <video_path>` with no output path given makes ffmpeg exit
    non-zero (there's nothing for it to encode), but before it gives up it
    prints a line like `Duration: 00:01:23.45` to stderr -- parsed here
    regardless of the exit code, since the exit code itself carries no
    information for this call (there was never an output to succeed at
    writing).

    This has no dependency on yt-dlp/Instagram metadata whatsoever -- that
    is the point: it's an independent, metadata-agnostic way to determine
    duration from a real downloaded file, for use as a fallback when a
    platform's own reported duration is missing or invalid (see
    `pipeline/waterfall.py`'s `_extract_from_visual`).

    `cancel_event`, if given, lets a caller kill the in-flight ffmpeg
    probe early (default `None` -- no cancellation, same behavior as
    before); see `reel2movie._subprocess_util.run_cancelable`.

    Raises:
        FrameExtractionError: if the ffmpeg subprocess times out, the
            ffmpeg binary can't be run at all (`OSError`), or no
            parseable `Duration:` line is found in stderr (e.g. a
            corrupt or non-video file) -- the message includes a
            snippet of ffmpeg's stderr for debuggability.
        SubprocessCancelled: if `cancel_event` fires before ffmpeg
            finishes -- propagated as-is (not wrapped in
            `FrameExtractionError`), so callers can distinguish "this lost
            the race" from a real probing failure.
    """
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    command = [ffmpeg_exe, "-i", str(video_path)]
    try:
        result = run_cancelable(
            command,
            timeout_seconds=_FFMPEG_TIMEOUT_SECONDS,
            cancel_event=cancel_event,
        )
    except subprocess.TimeoutExpired as exc:
        raise FrameExtractionError(
            f"ffmpeg timed out after {_FFMPEG_TIMEOUT_SECONDS}s probing "
            f"duration of {video_path}"
        ) from exc
    except OSError as exc:
        raise FrameExtractionError(
            f"ffmpeg could not be run to probe duration of {video_path}: {exc}"
        ) from exc

    match = _DURATION_RE.search(result.stderr)
    if match is None:
        stderr_snippet = result.stderr[:500] if result.stderr else "<empty>"
        raise FrameExtractionError(
            f"could not find a parseable 'Duration:' line in ffmpeg's "
            f"stderr while probing {video_path} (corrupt file or not a "
            f"video?). ffmpeg stderr: {stderr_snippet}"
        )

    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
