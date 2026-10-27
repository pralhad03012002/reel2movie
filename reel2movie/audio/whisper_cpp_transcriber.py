"""`AudioTranscriber` backed by shelling out to the whisper.cpp CLI.

Research findings this module is grounded in (verified live against
ggerganov/whisper.cpp's current README and `examples/cli/README.md` at
implementation time, not assumed from stale/prior knowledge):

- **Binary name**: `whisper-cli` is the current CLI example binary (built
  from `examples/cli`; the older `main` name is historical). This is also
  what the current Homebrew `whisper.cpp` formula installs on macOS
  (`brew install whisper.cpp`; the older, now-behind `whisper-cpp`
  formula is a separate, legacy formula). See `config.get_whisper_cpp_binary()`.
- **Model**: a multilingual `large-v3-turbo` ggml model is the current
  recommended speed/multilingual-accuracy balance (confirmed present in
  whisper.cpp's own `models/download-ggml-model.sh` choices, alongside
  quantized `-q5_0`/`-q8_0` variants for a smaller footprint). Model files
  are obtained via that script or directly from the
  `ggerganov/whisper.cpp` Hugging Face repo -- never bundled by this
  project. See `config.get_whisper_cpp_model_path()`.
- **Input format**: whisper.cpp's CLI "currently runs only with 16-bit
  WAV files" per its README, which is why `audio_extractor.extract_audio`
  produces 16kHz mono PCM s16le WAV specifically.
- **Invocation shape**: `whisper-cli -m <model> -f <wav> -l auto -nt
  -otxt -of <prefix>` -- `-l auto` requests language auto-detection
  (multilingual, never hardcoded to English per the task's requirement),
  `-nt` omits timestamps, and `-otxt -of <prefix>` writes a plain-text
  transcript to `<prefix>.txt` rather than relying on stdout, whose
  default output interleaves system-info/progress lines with the
  transcript text (confirmed via `examples/cli/README.md`'s flag list).

This mirrors `reel2movie._claude_cli`'s error-handling shape (clear
messages, the binary's stderr always included, no silent failures)
without that module's Claude-specific JSON-reply parsing, which doesn't
apply here -- whisper.cpp's CLI writes a plain-text file, not a JSON
envelope.
"""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

from reel2movie._subprocess_util import SubprocessCancelled, run_cancelable

# A full reel's audio transcription (not a single frame/seek) -- generous
# relative to the ffmpeg timeouts used elsewhere in this codebase, since
# whisper.cpp's decode pass over a whole audio file is the slowest single
# step in the audio-transcript fallback.
_DEFAULT_TIMEOUT_SECONDS = 600.0


class WhisperCppTranscriberError(RuntimeError):
    """Raised when the whisper.cpp CLI subprocess fails to produce a transcript.

    Covers: the subprocess timing out, the whisper.cpp binary being
    missing/not on PATH/not executable (any `OSError` from the underlying
    subprocess call), a non-zero exit code, and a zero exit code where the
    expected output file was never written. The message always includes
    the binary's captured stderr when available.
    """


class WhisperCppTranscriber:
    """`AudioTranscriber` (see `core.protocols.AudioTranscriber`) backed by
    the whisper.cpp CLI.

    Per this project's separation-of-concerns convention (see
    `config.py`'s module docstring, and `visual/vision_llm_detector.py`'s
    note on the same point), this class never calls
    `config.get_whisper_cpp_binary()` / `config.get_whisper_cpp_model_path()`
    itself -- the binary name and model path are always constructor
    parameters, supplied by the caller (a later `pipeline/deps.py`) after
    it has read env config.
    """

    def __init__(
        self,
        model_path: Path,
        *,
        whisper_binary: str = "whisper-cli",
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._model_path = model_path
        self._whisper_binary = whisper_binary
        self._timeout_seconds = timeout_seconds

    def transcribe(
        self, audio_path: Path, *, cancel_event: threading.Event | None = None
    ) -> str:
        """Transcribe `audio_path` (a 16kHz mono WAV) to plain text.

        Invokes:
            whisper-cli -m <model_path> -f <audio_path> -l auto -nt -otxt
                -of <audio_path, suffix stripped>

        `-l auto` requests multilingual language auto-detection (never
        hardcoded to English); `-nt` omits timestamps; `-otxt -of <prefix>`
        writes the plain transcript to `<prefix>.txt`, which is read back
        and returned (trailing whitespace stripped) rather than parsed out
        of stdout -- stdout also carries progress/system-info lines that
        are not part of the transcript itself.

        An empty transcript (silent/non-speech audio) is a legitimate,
        non-error result: only the output *file*'s existence is checked,
        not its size -- a zero-byte `<prefix>.txt` just means whisper.cpp
        heard nothing worth transcribing, not that the run failed.

        Raises:
            WhisperCppTranscriberError: if the whisper.cpp binary can't be
                run at all (missing/not on PATH/not executable), the
                subprocess times out, it exits non-zero, or it exits zero
                but the expected `<prefix>.txt` output file was never
                written (mirrors `visual.frame_sampler`'s "don't trust a
                zero exit code alone" lesson).
            reel2movie._subprocess_util.SubprocessCancelled: if
                `cancel_event` fires while the subprocess is running.
        """
        output_prefix = audio_path.with_suffix("")
        output_txt_path = output_prefix.with_suffix(".txt")

        # Remove any pre-existing output file from a previous run at this
        # same path BEFORE invoking whisper-cli. Without this, if a caller
        # ever transcribes the same `audio_path` twice (e.g. a retry) and
        # this invocation exits 0 without actually (re)writing the file --
        # the same "reports success but writes nothing" quirk this
        # codebase already distrusts ffmpeg for, see
        # `visual.frame_sampler`'s module docstring -- the existence check
        # below would pass on the STALE file from the earlier run, and a
        # caller would silently get back an unrelated, out-of-date
        # transcript instead of an error.
        output_txt_path.unlink(missing_ok=True)

        command = [
            self._whisper_binary,
            "-m",
            str(self._model_path),
            "-f",
            str(audio_path),
            "-l",
            "auto",
            "-nt",
            "-otxt",
            "-of",
            str(output_prefix),
        ]

        try:
            result = run_cancelable(
                command,
                timeout_seconds=self._timeout_seconds,
                cancel_event=cancel_event,
            )
        except SubprocessCancelled:
            raise
        except subprocess.TimeoutExpired as exc:
            raise WhisperCppTranscriberError(
                f"`{self._whisper_binary}` timed out after "
                f"{self._timeout_seconds}s transcribing {audio_path}"
            ) from exc
        except OSError as exc:
            raise WhisperCppTranscriberError(
                f"could not run the whisper.cpp CLI (binary: "
                f"{self._whisper_binary!r}) -- is it installed and on "
                f"PATH? ({exc})"
            ) from exc

        if result.returncode != 0:
            raise WhisperCppTranscriberError(
                f"`{self._whisper_binary}` exited {result.returncode} "
                f"transcribing {audio_path}: {(result.stderr or '').strip()}"
            )

        if not output_txt_path.exists():
            raise WhisperCppTranscriberError(
                f"`{self._whisper_binary}` reported success (exit code 0) "
                f"transcribing {audio_path}, but the expected output file "
                f"{output_txt_path} was not written. stderr: "
                f"{(result.stderr or '').strip()}"
            )

        return output_txt_path.read_text(encoding="utf-8").strip()
