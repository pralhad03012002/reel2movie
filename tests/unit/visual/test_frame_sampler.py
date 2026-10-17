"""Tests for `reel2movie.visual.frame_sampler`.

These tests DO invoke a real local ffmpeg subprocess (the `imageio-ffmpeg`
bundled binary) — unlike other subtasks' "no live calls" rule (which is
about live network/paid-API calls), running a local offline binary is fine
and expected for this module specifically, since `sample_frames` has no
meaningful behavior to test without actually extracting frames.

No binary `.mp4` fixture is committed to the repo (`.gitignore` already
excludes `tests/fixtures/*.mp4`, but we go further and don't even write one
there for local reuse): a tiny ~6-second, 64x64, 1fps synthetic `testsrc`
video is generated fresh into a pytest `tmp_path`-derived directory by the
`sample_video` fixture below, using the same bundled ffmpeg binary
`sample_frames` itself uses. This is simpler than managing a committed
binary fixture's lifecycle and guarantees the test video is always in sync
with whatever ffmpeg binary `imageio_ffmpeg` resolves to in the current
environment.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import imageio_ffmpeg
import pytest

from reel2movie.visual.frame_sampler import (
    FrameExtractionError,
    probe_duration_seconds,
    sample_frames,
)

VIDEO_DURATION_SECONDS = 6.0


@pytest.fixture(scope="module")
def sample_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate a tiny synthetic test video via ffmpeg's `testsrc` lavfi source.

    Fully offline, no download: ffmpeg generates the test pattern itself.

    Uses `rate=10` (not the 1fps from the task's illustrative example):
    at 1fps a 6-second video only has 6 frames total, and a timestamp near
    the tail of the 5%/95% window (e.g. 5.7s) then falls into a gap where
    ffmpeg's input-side `-ss` seek (as specified for `sample_frames`,
    `-ss` before `-i`) finds no frame to encode and silently produces a
    zero-byte/missing output — a real ffmpeg quirk specific to very sparse
    frame grids, confirmed by hand while writing this test, not a bug in
    `sample_frames` itself. `rate=10` keeps the fixture tiny and offline
    while giving every sampled timestamp an actual nearby frame, which is
    representative of real Instagram reels (normal frame rates, never
    anywhere near this sparse).
    """
    video_dir = tmp_path_factory.mktemp("frame_sampler_fixture")
    video_path = video_dir / "sample_video.mp4"
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    result = subprocess.run(
        [
            ffmpeg_exe,
            "-f",
            "lavfi",
            "-i",
            f"testsrc=duration={VIDEO_DURATION_SECONDS}:size=64x64:rate=10",
            "-y",
            str(video_path),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"failed to generate test fixture video: {result.stderr}"
    return video_path


def test_sample_frames_returns_n_evenly_spaced_frames_within_window(sample_video: Path, tmp_path: Path) -> None:
    samples = sample_frames(sample_video, n=3, duration_seconds=VIDEO_DURATION_SECONDS, output_dir=tmp_path)

    assert len(samples) == 3

    lo = 0.05 * VIDEO_DURATION_SECONDS
    hi = 0.95 * VIDEO_DURATION_SECONDS
    timestamps = [s.timestamp_seconds for s in samples]
    for ts in timestamps:
        assert lo <= ts <= hi

    # Roughly evenly spaced: the two gaps between consecutive timestamps
    # should be (nearly) equal.
    gap1 = timestamps[1] - timestamps[0]
    gap2 = timestamps[2] - timestamps[1]
    assert gap1 == pytest.approx(gap2, abs=0.01)

    # Endpoints should be exactly at the 5%/95% window bounds for n > 1.
    assert timestamps[0] == pytest.approx(lo, abs=1e-9)
    assert timestamps[-1] == pytest.approx(hi, abs=1e-9)

    for sample in samples:
        assert sample.path.exists()
        assert sample.path.stat().st_size > 0


def test_n_1_returns_exactly_one_frame_at_midpoint(sample_video: Path, tmp_path: Path) -> None:
    samples = sample_frames(sample_video, n=1, duration_seconds=VIDEO_DURATION_SECONDS, output_dir=tmp_path)

    assert len(samples) == 1
    assert samples[0].timestamp_seconds == pytest.approx(0.5 * VIDEO_DURATION_SECONDS)
    assert samples[0].path.exists()
    assert samples[0].path.stat().st_size > 0


def test_no_output_dir_uses_a_persistent_temp_dir(sample_video: Path) -> None:
    """When output_dir is omitted, frames land in a fresh dir that outlives the call."""
    samples = sample_frames(sample_video, n=1, duration_seconds=VIDEO_DURATION_SECONDS)

    assert len(samples) == 1
    # The file must still exist on disk after sample_frames has returned —
    # proving the temp dir wasn't torn down (e.g. by a TemporaryDirectory
    # context manager exiting) before the caller could use the path.
    assert samples[0].path.exists()
    assert samples[0].path.stat().st_size > 0


@pytest.mark.parametrize("bad_n", [0, -1])
def test_invalid_n_raises_value_error(sample_video: Path, tmp_path: Path, bad_n: int) -> None:
    with pytest.raises(ValueError, match="n must be"):
        sample_frames(sample_video, n=bad_n, duration_seconds=VIDEO_DURATION_SECONDS, output_dir=tmp_path)


@pytest.mark.parametrize("bad_duration", [0.0, -1.0])
def test_invalid_duration_raises_value_error(sample_video: Path, tmp_path: Path, bad_duration: float) -> None:
    with pytest.raises(ValueError, match="duration_seconds must be"):
        sample_frames(sample_video, n=1, duration_seconds=bad_duration, output_dir=tmp_path)


def test_nonexistent_video_path_raises_frame_extraction_error_with_stderr(tmp_path: Path) -> None:
    missing_video = tmp_path / "does_not_exist.mp4"
    with pytest.raises(FrameExtractionError) as excinfo:
        sample_frames(missing_video, n=1, duration_seconds=VIDEO_DURATION_SECONDS, output_dir=tmp_path)

    # ffmpeg's real stderr must be captured in the message, not swallowed.
    assert str(missing_video) in str(excinfo.value)
    assert len(str(excinfo.value)) > 0


def test_patched_nonzero_ffmpeg_exit_raises_frame_extraction_error_with_stderr(
    sample_video: Path, tmp_path: Path
) -> None:
    fake_stderr = "fake ffmpeg failure: no such filter or seek error"
    with patch("reel2movie.visual.frame_sampler.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["ffmpeg"], returncode=1, stdout="", stderr=fake_stderr
        )
        with pytest.raises(FrameExtractionError, match=fake_stderr):
            sample_frames(sample_video, n=1, duration_seconds=VIDEO_DURATION_SECONDS, output_dir=tmp_path)


def test_exit_code_0_but_empty_output_raises_frame_extraction_error(
    sample_video: Path, tmp_path: Path
) -> None:
    """Reproduces the reviewer's real-world quirk via a mock, not timing.

    ffmpeg can exit 0 while writing nothing (e.g. "Output file is empty,
    nothing was encoded" in stderr when seeking near the edge of a sparse
    video). Mock `subprocess.run` to return a zero-code result without
    actually creating the output file, instead of relying on the real
    sparse-video edge case, which is timing-sensitive.
    """
    fake_stderr = "Output file is empty, nothing was encoded"
    with patch("reel2movie.visual.frame_sampler.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["ffmpeg"], returncode=0, stdout="", stderr=fake_stderr
        )
        with pytest.raises(FrameExtractionError, match=fake_stderr):
            sample_frames(sample_video, n=1, duration_seconds=VIDEO_DURATION_SECONDS, output_dir=tmp_path)


def test_ffmpeg_timeout_raises_frame_extraction_error(sample_video: Path, tmp_path: Path) -> None:
    with patch("reel2movie.visual.frame_sampler.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=30)
        with pytest.raises(FrameExtractionError, match="timed out"):
            sample_frames(sample_video, n=1, duration_seconds=VIDEO_DURATION_SECONDS, output_dir=tmp_path)


# ---------------------------------------------------------------------------
# probe_duration_seconds
# ---------------------------------------------------------------------------


def test_probe_duration_seconds_matches_known_duration_within_tolerance(
    sample_video: Path,
) -> None:
    probed = probe_duration_seconds(sample_video)

    # ffmpeg's own duration reporting has some precision limits (it's
    # parsed from the container's rounded duration field, not re-derived
    # from frame count), so a small tolerance is used rather than exact
    # equality.
    assert probed == pytest.approx(VIDEO_DURATION_SECONDS, abs=0.5)


def test_probe_duration_seconds_on_nonexistent_file_raises_clear_error(
    tmp_path: Path,
) -> None:
    missing_video = tmp_path / "does_not_exist.mp4"
    with pytest.raises(FrameExtractionError) as excinfo:
        probe_duration_seconds(missing_video)

    # A clear, debuggable error -- not a raw regex/parse crash (e.g.
    # `None` unpacking into `match.groups()`) -- and ffmpeg's real stderr
    # is captured in the message, not swallowed.
    assert str(missing_video) in str(excinfo.value)


def test_probe_duration_seconds_on_corrupt_file_raises_clear_error(
    tmp_path: Path,
) -> None:
    corrupt_video = tmp_path / "corrupt.mp4"
    corrupt_video.write_bytes(b"this is not a real video file, just junk bytes")

    with pytest.raises(FrameExtractionError, match="Duration"):
        probe_duration_seconds(corrupt_video)


def test_probe_duration_seconds_timeout_raises_frame_extraction_error(
    sample_video: Path,
) -> None:
    with patch("reel2movie.visual.frame_sampler.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=30)
        with pytest.raises(FrameExtractionError, match="timed out"):
            probe_duration_seconds(sample_video)


def test_probe_duration_seconds_oserror_raises_frame_extraction_error(
    sample_video: Path,
) -> None:
    with patch("reel2movie.visual.frame_sampler.subprocess.run") as mock_run:
        mock_run.side_effect = OSError("ffmpeg binary not found")
        with pytest.raises(FrameExtractionError, match="could not be run"):
            probe_duration_seconds(sample_video)
