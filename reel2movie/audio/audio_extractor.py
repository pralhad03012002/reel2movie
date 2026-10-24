"""Extract a video's audio track into a 16kHz mono WAV file.

This is the demux step of the audio-transcript fallback (see this
subpackage's `__init__.py` and `whisper_cpp_transcriber.py`): a reel's
audio track carries the creator's spoken narration, which can confirm a
movie recommendation even when the caption/comments/on-screen text never
name it.

Uses `imageio_ffmpeg.get_ffmpeg_exe()` to locate the bundled ffmpeg binary
(no system ffmpeg/Homebrew install required or assumed) -- same approach
`visual/frame_sampler.py` already uses for frame extraction. Unlike
`frame_sampler.py`, this invokes ffmpeg via
`reel2movie._subprocess_util.run_cancelable()` rather than bare
`subprocess.run`, so audio extraction participates in the pipeline's
cooperative-cancellation machinery once the parallel-race orchestrator
(built separately) lands.

16kHz mono 16-bit PCM is whisper.cpp's required input format -- its own
README states the CLI "currently runs only with 16-bit WAV files" and
gives `ffmpeg -i input.mp3 -ar 16000 -ac 1 -c:a pcm_s16le output.wav` as
the exact conversion recipe, which `extract_audio` below mirrors.
"""

from __future__ import annotations

import logging
import subprocess
import threading
from pathlib import Path

import imageio_ffmpeg

from reel2movie._subprocess_util import SubprocessCancelled, run_cancelable

logger = logging.getLogger(__name__)


class AudioExtractionError(RuntimeError):
    """Raised when the ffmpeg subprocess fails to extract a video's audio track.

    Mirrors `visual.frame_sampler.FrameExtractionError`'s shape: the
    message always includes ffmpeg's captured stderr when available
    (never swallowed). A zero exit code alone is never trusted either --
    `frame_sampler.py`'s module docstring documents the real-world "ffmpeg
    exits 0 but writes nothing" quirk, and `extract_audio` applies the
    same "check the output file actually exists and is non-empty" lesson
    here.
    """


# A full-file audio demux (not a single frame/seek) -- generous relative
# to frame_sampler.py's 30s single-frame timeout, since this reads the
# entire video stream once.
_FFMPEG_TIMEOUT_SECONDS = 120.0


def extract_audio(
    video_path: Path,
    output_dir: Path,
    *,
    cancel_event: threading.Event | None = None,
) -> Path:
    """Demux and convert `video_path`'s audio track into a 16kHz mono WAV.

    Writes `<output_dir>/audio.wav` via:
        ffmpeg -i <video_path> -vn -ar 16000 -ac 1 -c:a pcm_s16le -y <out>

    Args:
        video_path: local path to the downloaded reel video.
        output_dir: directory to write `audio.wav` into; created if
            missing. Caller owns this directory (same convention as
            `visual.frame_sampler.sample_frames`'s `output_dir` param).
        cancel_event: optional cooperative-cancellation event, passed
            straight through to `run_cancelable`.

    Returns:
        Path to the written `audio.wav`.

    Raises:
        AudioExtractionError: if the ffmpeg subprocess can't be run at
            all (e.g. `OSError` -- not expected in practice since
            `imageio_ffmpeg` bundles its own binary, but defended anyway,
            mirroring `visual.frame_sampler.probe_duration_seconds`),
            times out, returns a nonzero exit code, or returns exit code
            0 but the output file is missing or empty.
        reel2movie._subprocess_util.SubprocessCancelled: if `cancel_event`
            fires while ffmpeg is running.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    audio_path = output_dir / "audio.wav"

    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    command = [
        ffmpeg_exe,
        "-i",
        str(video_path),
        "-vn",
        "-ar",
        "16000",
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        "-y",
        str(audio_path),
    ]

    try:
        result = run_cancelable(
            command,
            timeout_seconds=_FFMPEG_TIMEOUT_SECONDS,
            cancel_event=cancel_event,
        )
    except SubprocessCancelled:
        raise
    except subprocess.TimeoutExpired as exc:
        raise AudioExtractionError(
            f"ffmpeg timed out after {_FFMPEG_TIMEOUT_SECONDS}s extracting "
            f"audio from {video_path}"
        ) from exc
    except OSError as exc:
        raise AudioExtractionError(
            f"ffmpeg could not be run to extract audio from {video_path}: {exc}"
        ) from exc

    if result.returncode != 0:
        raise AudioExtractionError(
            f"ffmpeg failed to extract audio from {video_path} "
            f"(exit code {result.returncode}): {result.stderr}"
        )

    # ffmpeg can exit 0 while writing nothing at all (same quirk
    # `visual.frame_sampler._extract_frame_at` already learned to
    # distrust). Trust the output file, not the exit code: it must exist
    # and be non-empty.
    if not audio_path.exists() or audio_path.stat().st_size == 0:
        raise AudioExtractionError(
            f"ffmpeg reported success (exit code 0) extracting audio from "
            f"{video_path}, but the output file {audio_path} is missing "
            f"or empty. ffmpeg stderr: {result.stderr}"
        )

    return audio_path
