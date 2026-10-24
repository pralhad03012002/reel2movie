"""Tests for `reel2movie.audio.audio_extractor`.

No real ffmpeg subprocess is ever invoked here: `run_cancelable` (imported
from `reel2movie._subprocess_util` into this module's namespace) is always
mocked. This follows the same "no live/real external binary" test
philosophy as `tests/unit/test_claude_cli.py` (which mocks `subprocess.run`
rather than invoking a real `claude` binary) -- `tests/unit/visual/
test_frame_sampler.py` is the one deliberate exception to this project's
usual rule, for reasons documented in its own module docstring, and that
exception is not extended here.
"""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from reel2movie._subprocess_util import SubprocessCancelled
from reel2movie.audio.audio_extractor import AudioExtractionError, extract_audio


def _completed(returncode: int, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["ffmpeg"], returncode=returncode, stdout="", stderr=stderr)


class TestExtractAudio:
    def test_success_returns_output_wav_path(self, tmp_path: Path) -> None:
        video_path = tmp_path / "video.mp4"
        video_path.write_bytes(b"fake video bytes")
        output_dir = tmp_path / "out"

        def fake_run_cancelable(args, *, timeout_seconds, cancel_event=None):
            # Simulate ffmpeg actually writing the output file.
            (output_dir / "audio.wav").write_bytes(b"RIFF....fake wav bytes")
            return _completed(0)

        with patch(
            "reel2movie.audio.audio_extractor.run_cancelable",
            side_effect=fake_run_cancelable,
        ) as mock_run:
            result = extract_audio(video_path, output_dir)

        assert result == output_dir / "audio.wav"
        assert result.exists()
        assert result.read_bytes() == b"RIFF....fake wav bytes"
        mock_run.assert_called_once()
        (command,), kwargs = mock_run.call_args
        assert str(video_path) in command
        assert "-ar" in command and "16000" in command
        assert "-ac" in command and "1" in command
        assert "pcm_s16le" in command
        assert kwargs["timeout_seconds"] > 0

    def test_creates_output_dir_if_missing(self, tmp_path: Path) -> None:
        video_path = tmp_path / "video.mp4"
        video_path.write_bytes(b"x")
        output_dir = tmp_path / "does" / "not" / "exist"

        def fake_run_cancelable(args, *, timeout_seconds, cancel_event=None):
            (output_dir / "audio.wav").write_bytes(b"wav")
            return _completed(0)

        with patch(
            "reel2movie.audio.audio_extractor.run_cancelable",
            side_effect=fake_run_cancelable,
        ):
            extract_audio(video_path, output_dir)

        assert output_dir.is_dir()

    def test_ffmpeg_nonzero_exit_raises_with_stderr(self, tmp_path: Path) -> None:
        video_path = tmp_path / "video.mp4"
        video_path.write_bytes(b"x")
        output_dir = tmp_path / "out"

        with patch(
            "reel2movie.audio.audio_extractor.run_cancelable",
            return_value=_completed(1, stderr="ffmpeg: Invalid data found"),
        ):
            with pytest.raises(AudioExtractionError, match="Invalid data found"):
                extract_audio(video_path, output_dir)

    def test_missing_output_file_despite_zero_exit_raises(self, tmp_path: Path) -> None:
        video_path = tmp_path / "video.mp4"
        video_path.write_bytes(b"x")
        output_dir = tmp_path / "out"
        output_dir.mkdir()

        with patch(
            "reel2movie.audio.audio_extractor.run_cancelable",
            return_value=_completed(0, stderr="Output file is empty, nothing was encoded"),
        ):
            with pytest.raises(AudioExtractionError, match="missing or empty"):
                extract_audio(video_path, output_dir)

    def test_empty_output_file_despite_zero_exit_raises(self, tmp_path: Path) -> None:
        video_path = tmp_path / "video.mp4"
        video_path.write_bytes(b"x")
        output_dir = tmp_path / "out"
        output_dir.mkdir()
        (output_dir / "audio.wav").write_bytes(b"")  # zero bytes

        with patch(
            "reel2movie.audio.audio_extractor.run_cancelable",
            return_value=_completed(0),
        ):
            with pytest.raises(AudioExtractionError, match="missing or empty"):
                extract_audio(video_path, output_dir)

    def test_timeout_raises_audio_extraction_error(self, tmp_path: Path) -> None:
        video_path = tmp_path / "video.mp4"
        video_path.write_bytes(b"x")
        output_dir = tmp_path / "out"

        with patch(
            "reel2movie.audio.audio_extractor.run_cancelable",
            side_effect=subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=120.0),
        ):
            with pytest.raises(AudioExtractionError, match="timed out"):
                extract_audio(video_path, output_dir)

    def test_missing_binary_raises_audio_extraction_error(self, tmp_path: Path) -> None:
        video_path = tmp_path / "video.mp4"
        video_path.write_bytes(b"x")
        output_dir = tmp_path / "out"

        with patch(
            "reel2movie.audio.audio_extractor.run_cancelable",
            side_effect=FileNotFoundError("no such file: ffmpeg"),
        ):
            with pytest.raises(AudioExtractionError, match="could not be run"):
                extract_audio(video_path, output_dir)

    def test_cancel_event_set_raises_subprocess_cancelled_cleanly(
        self, tmp_path: Path
    ) -> None:
        video_path = tmp_path / "video.mp4"
        video_path.write_bytes(b"x")
        output_dir = tmp_path / "out"
        cancel_event = threading.Event()
        cancel_event.set()

        with patch(
            "reel2movie.audio.audio_extractor.run_cancelable",
            side_effect=SubprocessCancelled("cancelled"),
        ):
            with pytest.raises(SubprocessCancelled):
                extract_audio(video_path, output_dir, cancel_event=cancel_event)
