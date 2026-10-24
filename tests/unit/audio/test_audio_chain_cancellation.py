"""Whole-chain cancellation: extract_audio -> WhisperCppTranscriber.transcribe.

Covers the scenario the task description calls out explicitly: a
cancel_event set DURING the audio-transcript fallback's two-step chain
(ffmpeg demux succeeds, then whisper.cpp transcription is cancelled) must
make the chain raise cleanly (`SubprocessCancelled`) rather than hang or
silently swallow the cancellation. Per-function cancellation (cancelled
during extraction itself) is already covered by
`test_audio_extractor.py::test_cancel_event_set_raises_subprocess_cancelled_cleanly`
and `test_whisper_cpp_transcriber.py`'s equivalent -- this test's only
additive value is exercising both real functions back-to-back, so it
stays to just that.
"""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from reel2movie._subprocess_util import SubprocessCancelled
from reel2movie.audio.audio_extractor import extract_audio
from reel2movie.audio.whisper_cpp_transcriber import WhisperCppTranscriber


def test_cancel_during_transcription_after_successful_extraction(
    tmp_path: Path,
) -> None:
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"x")
    output_dir = tmp_path / "out"
    cancel_event = threading.Event()

    def fake_ffmpeg(args, *, timeout_seconds, cancel_event=None):
        (output_dir / "audio.wav").write_bytes(b"wav bytes")
        return subprocess.CompletedProcess(args, 0, "", "")

    with patch(
        "reel2movie.audio.audio_extractor.run_cancelable", side_effect=fake_ffmpeg
    ):
        audio_path = extract_audio(video_path, output_dir, cancel_event=cancel_event)

    assert audio_path.exists()

    # Cancellation fires at the transcription step instead.
    cancel_event.set()
    transcriber = WhisperCppTranscriber(tmp_path / "model.bin")
    with patch(
        "reel2movie.audio.whisper_cpp_transcriber.run_cancelable",
        side_effect=SubprocessCancelled("cancelled during whisper-cli"),
    ):
        with pytest.raises(SubprocessCancelled):
            transcriber.transcribe(audio_path, cancel_event=cancel_event)
