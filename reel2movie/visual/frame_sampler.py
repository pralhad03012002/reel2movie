"""Sample still frames from a video at N equally-spaced timestamps.

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
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

import imageio_ffmpeg

from reel2movie.core.models import FrameSample


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


def sample_frames(
    video_path: Path,
    n: int,
    duration_seconds: float,
    *,
    output_dir: Path | None = None,
) -> list[FrameSample]:
    """Extract N equally-spaced frames from `video_path` as JPEGs.

    Timestamps are computed by `_compute_timestamps` (see its docstring).
    Each frame is extracted via a direct subprocess call to the
    `imageio_ffmpeg`-bundled ffmpeg binary:
    `ffmpeg -ss <timestamp> -i <video_path> -frames:v 1 -y <output_path>`.

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
    """
    if n < 1:
        raise ValueError(f"n must be >= 1, got {n}")
    if duration_seconds <= 0:
        raise ValueError(f"duration_seconds must be > 0, got {duration_seconds}")

    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix="reel2movie_frames_"))
    else:
        output_dir.mkdir(parents=True, exist_ok=True)

    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    timestamps = _compute_timestamps(n, duration_seconds)

    samples: list[FrameSample] = []
    for i, timestamp in enumerate(timestamps):
        frame_path = output_dir / f"frame_{i:03d}.jpg"
        # -pix_fmt yuvj420p: forces a pixel format the mjpeg encoder always
        # accepts. Some source videos (including this module's own
        # synthetic testsrc fixture) decode to a pixel format (e.g.
        # yuv444p, or non-full-range yuv420p) that ffmpeg's mjpeg encoder
        # rejects with "Non full-range YUV is non-standard" / "Error while
        # opening encoder" and silently writes zero bytes. Forcing the
        # format here is cheap and fixes that without depending on how any
        # given input video happens to be encoded.
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
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=_FFMPEG_TIMEOUT_SECONDS,
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

        samples.append(FrameSample(path=frame_path, timestamp_seconds=timestamp))

    return samples


def probe_duration_seconds(video_path: Path) -> float:
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

    Raises:
        FrameExtractionError: if the ffmpeg subprocess times out, the
            ffmpeg binary can't be run at all (`OSError`), or no
            parseable `Duration:` line is found in stderr (e.g. a
            corrupt or non-video file) -- the message includes a
            snippet of ffmpeg's stderr for debuggability.
    """
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    command = [ffmpeg_exe, "-i", str(video_path)]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=_FFMPEG_TIMEOUT_SECONDS,
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
