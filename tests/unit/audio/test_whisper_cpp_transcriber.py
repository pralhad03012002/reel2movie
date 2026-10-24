"""Tests for `reel2movie.audio.whisper_cpp_transcriber`.

Same mocking approach as `tests/unit/audio/test_audio_extractor.py` and
`tests/unit/test_claude_cli.py`: no real whisper.cpp binary is ever
invoked -- `run_cancelable` is always mocked.
"""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from reel2movie._subprocess_util import SubprocessCancelled
from reel2movie.audio.whisper_cpp_transcriber import (
    WhisperCppTranscriber,
    WhisperCppTranscriberError,
)


def _completed(returncode: int, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["whisper-cli"], returncode=returncode, stdout="", stderr=stderr
    )


class TestWhisperCppTranscriber:
    def test_success_reads_output_txt_and_strips_whitespace(
        self, tmp_path: Path
    ) -> None:
        audio_path = tmp_path / "audio.wav"
        audio_path.write_bytes(b"fake wav bytes")
        model_path = tmp_path / "ggml-large-v3-turbo.bin"
        transcriber = WhisperCppTranscriber(model_path)

        def fake_run_cancelable(args, *, timeout_seconds, cancel_event=None):
            (tmp_path / "audio.txt").write_text("  Hello, this is a movie.  \n")
            return _completed(0)

        with patch(
            "reel2movie.audio.whisper_cpp_transcriber.run_cancelable",
            side_effect=fake_run_cancelable,
        ) as mock_run:
            result = transcriber.transcribe(audio_path)

        assert result == "Hello, this is a movie."
        mock_run.assert_called_once()
        (command,), kwargs = mock_run.call_args
        assert command[0] == "whisper-cli"
        assert "-m" in command and str(model_path) in command
        assert "-f" in command and str(audio_path) in command
        assert "-l" in command and "auto" in command  # multilingual auto-detect
        assert "-nt" in command
        assert "-otxt" in command
        assert kwargs["timeout_seconds"] > 0

    def test_empty_transcript_is_not_an_error(self, tmp_path: Path) -> None:
        audio_path = tmp_path / "audio.wav"
        audio_path.write_bytes(b"x")
        transcriber = WhisperCppTranscriber(tmp_path / "model.bin")

        def fake_run_cancelable(args, *, timeout_seconds, cancel_event=None):
            (tmp_path / "audio.txt").write_text("")
            return _completed(0)

        with patch(
            "reel2movie.audio.whisper_cpp_transcriber.run_cancelable",
            side_effect=fake_run_cancelable,
        ):
            result = transcriber.transcribe(audio_path)

        assert result == ""

    def test_missing_binary_raises_clear_error(self, tmp_path: Path) -> None:
        audio_path = tmp_path / "audio.wav"
        audio_path.write_bytes(b"x")
        transcriber = WhisperCppTranscriber(
            tmp_path / "model.bin", whisper_binary="whisper-cli"
        )

        with patch(
            "reel2movie.audio.whisper_cpp_transcriber.run_cancelable",
            side_effect=FileNotFoundError("no such file: whisper-cli"),
        ):
            with pytest.raises(WhisperCppTranscriberError, match="installed and on"):
                transcriber.transcribe(audio_path)

    def test_nonzero_exit_raises_with_stderr(self, tmp_path: Path) -> None:
        audio_path = tmp_path / "audio.wav"
        audio_path.write_bytes(b"x")
        transcriber = WhisperCppTranscriber(tmp_path / "model.bin")

        with patch(
            "reel2movie.audio.whisper_cpp_transcriber.run_cancelable",
            return_value=_completed(1, stderr="error: failed to load model"),
        ):
            with pytest.raises(WhisperCppTranscriberError, match="failed to load model"):
                transcriber.transcribe(audio_path)

    def test_missing_output_file_despite_zero_exit_raises(self, tmp_path: Path) -> None:
        audio_path = tmp_path / "audio.wav"
        audio_path.write_bytes(b"x")
        transcriber = WhisperCppTranscriber(tmp_path / "model.bin")

        with patch(
            "reel2movie.audio.whisper_cpp_transcriber.run_cancelable",
            return_value=_completed(0),
        ):
            with pytest.raises(WhisperCppTranscriberError, match="was not written"):
                transcriber.transcribe(audio_path)

    def test_timeout_raises_clear_error(self, tmp_path: Path) -> None:
        audio_path = tmp_path / "audio.wav"
        audio_path.write_bytes(b"x")
        transcriber = WhisperCppTranscriber(tmp_path / "model.bin")

        with patch(
            "reel2movie.audio.whisper_cpp_transcriber.run_cancelable",
            side_effect=subprocess.TimeoutExpired(cmd=["whisper-cli"], timeout=600.0),
        ):
            with pytest.raises(WhisperCppTranscriberError, match="timed out"):
                transcriber.transcribe(audio_path)

    def test_cancel_event_set_raises_subprocess_cancelled_cleanly(
        self, tmp_path: Path
    ) -> None:
        audio_path = tmp_path / "audio.wav"
        audio_path.write_bytes(b"x")
        transcriber = WhisperCppTranscriber(tmp_path / "model.bin")
        cancel_event = threading.Event()
        cancel_event.set()

        with patch(
            "reel2movie.audio.whisper_cpp_transcriber.run_cancelable",
            side_effect=SubprocessCancelled("cancelled"),
        ):
            with pytest.raises(SubprocessCancelled):
                transcriber.transcribe(audio_path, cancel_event=cancel_event)

    def test_default_binary_is_whisper_cli(self, tmp_path: Path) -> None:
        transcriber = WhisperCppTranscriber(tmp_path / "model.bin")
        assert transcriber._whisper_binary == "whisper-cli"
