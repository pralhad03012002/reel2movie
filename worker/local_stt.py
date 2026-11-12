"""Local audio -> 16 kHz mono -> speech detection -> text, on this Mac (faster-whisper, CPU INT8).

Ported from reel_Audio_extraction/transcribe.py: decode_media and the transcribe_media settings
are unchanged. Usage: local_stt.py <media file>; prints one JSON object {"text", "language"}.
"""

from __future__ import annotations

import itertools
import json
import os
import sys
from pathlib import Path

SAMPLE_RATE = 16000
MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_SECONDS = 180.0
MODEL = os.environ.get("LOCAL_STT_MODEL", "small.en")
LANGUAGE = os.environ.get("LOCAL_STT_LANGUAGE", "en")  # Whisper language code or "auto"


class ExperimentError(RuntimeError):
    """An input or pipeline failure that must be visible to the caller."""


def decode_media(path: Path, max_seconds: float):
    import av
    import numpy as np

    if not path.is_file():
        raise ExperimentError(f"Media file not found: {path}")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ExperimentError("Media exceeds the 100 MiB experiment limit.")
    chunks = []
    sample_count = 0
    resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
    try:
        with av.open(str(path)) as container:
            if not container.streams.audio:
                raise ExperimentError("Media contains no audio stream.")
            for frame in itertools.chain(container.decode(audio=0), [None]):
                if frame is not None:
                    frame.pts = None
                for converted in resampler.resample(frame):
                    chunk = converted.to_ndarray().reshape(-1)
                    sample_count += chunk.size
                    if sample_count > max_seconds * SAMPLE_RATE:
                        raise ExperimentError(
                            f"Audio exceeds the {max_seconds:g}-second experiment limit."
                        )
                    chunks.append(chunk)
    except av.error.FFmpegError as exc:
        raise ExperimentError(f"Cannot decode media: {exc}") from exc
    if sample_count == 0:
        raise ExperimentError("Media contains no decodable audio samples.")
    return np.concatenate(chunks).astype(np.float32) / 32768.0


def transcribe_media(model, path: Path, *, language: str, max_seconds: float) -> dict:
    audio = decode_media(path, max_seconds)
    segments, info = model.transcribe(
        audio,
        language=None if language == "auto" else language,
        beam_size=5,
        temperature=0.0,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        word_timestamps=True,
        condition_on_previous_text=False,
        hotwords=None,
    )
    text = " ".join(s.text.strip() for s in segments if s.text.strip())
    return {"text": text, "language": info.language}


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: local_stt.py <media file>", file=sys.stderr)
        return 2
    if MODEL.endswith(".en") and LANGUAGE != "en":
        print("English-only models require LOCAL_STT_LANGUAGE=en; use a multilingual model otherwise.", file=sys.stderr)
        return 2
    try:
        from faster_whisper import WhisperModel

        model = WhisperModel(
            MODEL, device="cpu", compute_type="int8",
            download_root=str(Path(__file__).parent / "models"),
        )
        result = transcribe_media(model, Path(argv[0]), language=LANGUAGE, max_seconds=MAX_SECONDS)
    except (ExperimentError, ImportError, OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
