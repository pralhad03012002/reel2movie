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

import os
import subprocess
import threading
import time
from pathlib import Path
from unittest.mock import patch

import imageio_ffmpeg
import pytest

from reel2movie._subprocess_util import SubprocessCancelled
from reel2movie.visual.frame_sampler import (
    FrameExtractionError,
    _extract_frame_at,
    probe_duration_seconds,
    sample_frames,
    sample_frames_at_interval,
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
    with patch("reel2movie.visual.frame_sampler.run_cancelable") as mock_run_cancelable:
        mock_run_cancelable.return_value = subprocess.CompletedProcess(
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
    with patch("reel2movie.visual.frame_sampler.run_cancelable") as mock_run_cancelable:
        mock_run_cancelable.return_value = subprocess.CompletedProcess(
            args=["ffmpeg"], returncode=0, stdout="", stderr=fake_stderr
        )
        with pytest.raises(FrameExtractionError, match=fake_stderr):
            sample_frames(sample_video, n=1, duration_seconds=VIDEO_DURATION_SECONDS, output_dir=tmp_path)


def test_ffmpeg_timeout_raises_frame_extraction_error(sample_video: Path, tmp_path: Path) -> None:
    with patch("reel2movie.visual.frame_sampler.run_cancelable") as mock_run_cancelable:
        mock_run_cancelable.side_effect = subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=30)
        with pytest.raises(FrameExtractionError, match="timed out"):
            sample_frames(sample_video, n=1, duration_seconds=VIDEO_DURATION_SECONDS, output_dir=tmp_path)


# ---------------------------------------------------------------------------
# sample_frames_at_interval
# ---------------------------------------------------------------------------


def test_sample_frames_at_interval_returns_correctly_spaced_timestamps(
    sample_video: Path, tmp_path: Path
) -> None:
    interval = 2.0
    samples = sample_frames_at_interval(
        sample_video, interval, VIDEO_DURATION_SECONDS, output_dir=tmp_path
    )

    # 0.0, 2.0, 4.0 -- 6.0 is excluded (duration_seconds is exclusive).
    timestamps = [s.timestamp_seconds for s in samples]
    assert timestamps == pytest.approx([0.0, 2.0, 4.0])

    for sample in samples:
        assert sample.path.exists()
        assert sample.path.stat().st_size > 0


def test_sample_frames_at_interval_includes_timestamp_at_the_very_start(
    sample_video: Path, tmp_path: Path
) -> None:
    """Unlike `sample_frames`'s 5%-95% window, this must include a sample
    at/near 0.0 -- the whole point being that transient on-screen text can
    appear right at the start of the video."""
    samples = sample_frames_at_interval(
        sample_video, 1.0, VIDEO_DURATION_SECONDS, output_dir=tmp_path
    )

    assert samples[0].timestamp_seconds == pytest.approx(0.0)


def test_sample_frames_at_interval_includes_a_timestamp_near_the_tail(
    sample_video: Path, tmp_path: Path
) -> None:
    """The last sampled timestamp must be close to the video's actual end
    (within one interval of it), unlike `sample_frames`'s 95% cutoff which
    would exclude the final ~5% entirely."""
    interval = 1.0
    samples = sample_frames_at_interval(
        sample_video, interval, VIDEO_DURATION_SECONDS, output_dir=tmp_path
    )

    last_timestamp = samples[-1].timestamp_seconds
    assert VIDEO_DURATION_SECONDS - interval <= last_timestamp < VIDEO_DURATION_SECONDS


@pytest.mark.parametrize("bad_interval", [0.0, -1.0])
def test_sample_frames_at_interval_invalid_interval_raises_value_error(
    sample_video: Path, tmp_path: Path, bad_interval: float
) -> None:
    with pytest.raises(ValueError, match="interval_seconds must be"):
        sample_frames_at_interval(
            sample_video, bad_interval, VIDEO_DURATION_SECONDS, output_dir=tmp_path
        )


@pytest.mark.parametrize("bad_duration", [0.0, -1.0])
def test_sample_frames_at_interval_invalid_duration_raises_value_error(
    sample_video: Path, tmp_path: Path, bad_duration: float
) -> None:
    with pytest.raises(ValueError, match="duration_seconds must be"):
        sample_frames_at_interval(
            sample_video, 1.0, bad_duration, output_dir=tmp_path
        )


def test_sample_frames_at_interval_skips_one_failing_timestamp_and_returns_the_rest(
    sample_video: Path, tmp_path: Path
) -> None:
    """Regression test for the real-world bug (see the docstring's
    "Best-effort vs. all-or-nothing" section): a single timestamp hitting
    ffmpeg's "exit code 0 but the output file is missing/empty" quirk
    (observed in production at timestamp 158.0s on a real Instagram reel)
    must not discard every OTHER successfully-extracted frame. Here,
    `interval=1.0` over a 6s video asks for timestamps
    [0, 1, 2, 3, 4, 5]; only the timestamp-3 extraction is made to fail
    (exit code 0, no output file written), matching the real quirk
    exactly -- the other five must still come back.
    """
    from reel2movie._subprocess_util import run_cancelable as real_run_cancelable

    def fake_run_cancelable(command, **kwargs):
        timestamp_str = command[2]  # ["ffmpeg", "-ss", "<timestamp>", ...]
        if timestamp_str == "3.0":
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout="",
                stderr="Output file is empty, nothing was encoded",
            )
        return real_run_cancelable(command, **kwargs)

    with patch(
        "reel2movie.visual.frame_sampler.run_cancelable",
        side_effect=fake_run_cancelable,
    ):
        samples = sample_frames_at_interval(
            sample_video, 1.0, VIDEO_DURATION_SECONDS, output_dir=tmp_path
        )

    timestamps = [s.timestamp_seconds for s in samples]
    assert timestamps == pytest.approx([0.0, 1.0, 2.0, 4.0, 5.0])
    for sample in samples:
        assert sample.path.exists()
        assert sample.path.stat().st_size > 0


def test_sample_frames_at_interval_every_timestamp_failing_returns_empty_list(
    sample_video: Path, tmp_path: Path
) -> None:
    """If literally every timestamp fails, this returns `[]` rather than
    raising -- `_extract_from_visual`'s existing fallback-to-empty
    handling already treats an empty frame list the same as "no frames",
    so there is nothing further for this function to signal by raising.
    """
    fake_stderr = "fake ffmpeg failure: no such filter or seek error"
    with patch("reel2movie.visual.frame_sampler.run_cancelable") as mock_run_cancelable:
        mock_run_cancelable.return_value = subprocess.CompletedProcess(
            args=["ffmpeg"], returncode=1, stdout="", stderr=fake_stderr
        )
        samples = sample_frames_at_interval(
            sample_video, 1.0, VIDEO_DURATION_SECONDS, output_dir=tmp_path
        )

    assert samples == []


def test_sample_frames_at_interval_uses_distinct_filename_pattern(
    sample_video: Path, tmp_path: Path
) -> None:
    """Output filenames use `frame_{i:04d}.jpg`, distinct from
    `sample_frames`'s `frame_{i:03d}.jpg` pattern."""
    samples = sample_frames_at_interval(
        sample_video, 2.0, VIDEO_DURATION_SECONDS, output_dir=tmp_path
    )

    assert samples[0].path.name == "frame_0000.jpg"


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
    with patch("reel2movie.visual.frame_sampler.run_cancelable") as mock_run_cancelable:
        mock_run_cancelable.side_effect = subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=30)
        with pytest.raises(FrameExtractionError, match="timed out"):
            probe_duration_seconds(sample_video)


def test_probe_duration_seconds_oserror_raises_frame_extraction_error(
    sample_video: Path,
) -> None:
    with patch("reel2movie.visual.frame_sampler.run_cancelable") as mock_run_cancelable:
        mock_run_cancelable.side_effect = OSError("ffmpeg binary not found")
        with pytest.raises(FrameExtractionError, match="could not be run"):
            probe_duration_seconds(sample_video)


def test_probe_duration_seconds_passes_cancel_event_through_to_run_cancelable(
    sample_video: Path,
) -> None:
    cancel_event = threading.Event()
    with patch("reel2movie.visual.frame_sampler.run_cancelable") as mock_run_cancelable:
        mock_run_cancelable.return_value = subprocess.CompletedProcess(
            args=["ffmpeg"],
            returncode=1,
            stdout="",
            stderr="Duration: 00:00:06.00, start: 0.000000, bitrate: 1 kb/s",
        )
        probe_duration_seconds(sample_video, cancel_event=cancel_event)

    _, kwargs = mock_run_cancelable.call_args
    assert kwargs["cancel_event"] is cancel_event


# ---------------------------------------------------------------------------
# sample_frames_at_interval: cancel_event
# ---------------------------------------------------------------------------


def test_sample_frames_at_interval_cancel_event_set_before_the_loop_returns_no_frames(
    sample_video: Path, tmp_path: Path
) -> None:
    """Checked at the TOP of the loop, before the first extraction even
    starts -- a cancel_event that's already set returns an empty, partial
    result rather than raising or extracting anything."""
    cancel_event = threading.Event()
    cancel_event.set()

    samples = sample_frames_at_interval(
        sample_video,
        1.0,
        VIDEO_DURATION_SECONDS,
        output_dir=tmp_path,
        cancel_event=cancel_event,
    )

    assert samples == []


def test_sample_frames_at_interval_cancel_mid_extraction_returns_partial_result(
    sample_video: Path, tmp_path: Path
) -> None:
    """A cancellation that fires partway through (simulated here via one
    timestamp's extraction raising SubprocessCancelled, standing in for a
    real OS-level kill mid-ffmpeg-call) stops further extraction and
    returns whatever frames were already gathered -- it must not look
    like "the video just had fewer frames" (that case is covered by the
    best-effort FrameExtractionError-skipping tests above, which keep
    going; this one stops)."""
    from reel2movie._subprocess_util import run_cancelable as real_run_cancelable

    cancel_event = threading.Event()

    def fake_run_cancelable(command, **kwargs):
        timestamp_str = command[2]  # ["ffmpeg", "-ss", "<timestamp>", ...]
        if timestamp_str == "2.0":
            raise SubprocessCancelled("cancelled mid-extraction")
        return real_run_cancelable(command, **kwargs)

    with patch(
        "reel2movie.visual.frame_sampler.run_cancelable",
        side_effect=fake_run_cancelable,
    ):
        samples = sample_frames_at_interval(
            sample_video,
            1.0,
            VIDEO_DURATION_SECONDS,
            output_dir=tmp_path,
            cancel_event=cancel_event,
        )

    # Timestamps 0.0 and 1.0 succeeded before the cancellation at 2.0;
    # nothing after 2.0 was even attempted.
    timestamps = [s.timestamp_seconds for s in samples]
    assert timestamps == pytest.approx([0.0, 1.0])


def test_extract_frame_at_cancel_event_kills_a_real_slow_ffmpeg_call(
    tmp_path: Path,
) -> None:
    """End-to-end (no mocking of run_cancelable at all): a real ffmpeg
    subprocess, started via the real `_extract_frame_at` ->
    `run_cancelable` chain, is actually killed when cancel_event fires --
    not just abandoned."""
    # A real video file is irrelevant here: ffmpeg will hang retrying to
    # open a named pipe that's never written to, which is enough to prove
    # cancellation actually tears down a real, still-running ffmpeg
    # process. A plain nonexistent path exits near-instantly instead
    # (no slow operation to cancel), so a FIFO is used to force ffmpeg to
    # block.
    fifo_path = tmp_path / "blocking.fifo"
    os.mkfifo(fifo_path)

    cancel_event = threading.Event()

    def _trigger() -> None:
        time.sleep(0.5)
        cancel_event.set()

    trigger_thread = threading.Thread(target=_trigger, daemon=True)
    trigger_thread.start()
    try:
        start = time.monotonic()
        try:
            _extract_frame_at(
                fifo_path, 0.0, tmp_path / "out.jpg", cancel_event=cancel_event
            )
        except SubprocessCancelled:
            elapsed = time.monotonic() - start
            assert elapsed < 3.0
        except FrameExtractionError:
            # ffmpeg didn't block on the unwritten FIFO long enough for
            # the 0.5s cancel trigger to matter on this platform/ffmpeg
            # build -- this test's premise (a real, slow-enough ffmpeg
            # call to actually cancel) doesn't hold here. Real-subprocess
            # cancellation itself is still fully covered, platform-
            # independently, by test_subprocess_util.py's sleep-based
            # tests, so skip rather than fail on this environment quirk.
            pytest.skip(
                "ffmpeg did not block on the FIFO long enough to exercise "
                "cancellation on this platform/build"
            )
    finally:
        # Always join, even if the assertion/skip above fired early --
        # otherwise a stray thread (still sleeping toward setting
        # cancel_event) is left running past this test's end.
        trigger_thread.join(timeout=2.0)
