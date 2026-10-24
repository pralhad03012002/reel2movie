"""Environment-variable based configuration loading.

No secret value is ever hardcoded here: every credential is read from
``os.environ`` at call time. See ``.env.example`` at the project root for the
exact variable names expected and what each one is for.
"""

from __future__ import annotations

import os
from pathlib import Path

_ENV_EXAMPLE_HINT = "see .env.example at the project root for the expected variables"


def get_tmdb_token() -> str:
    """Return the TMDB v4 API Read Access Token from ``TMDB_API_KEY``.

    Raises:
        RuntimeError: if the env var is unset or empty.
    """
    value = os.environ.get("TMDB_API_KEY", "")
    if not value:
        raise RuntimeError(
            f"TMDB_API_KEY is not set ({_ENV_EXAMPLE_HINT})."
        )
    return value


def get_anthropic_key() -> str:
    """Return the Anthropic API key from ``ANTHROPIC_API_KEY``.

    Raises:
        RuntimeError: if the env var is unset or empty.
    """
    value = os.environ.get("ANTHROPIC_API_KEY", "")
    if not value:
        raise RuntimeError(
            f"ANTHROPIC_API_KEY is not set ({_ENV_EXAMPLE_HINT})."
        )
    return value


_VALID_VISION_BACKENDS = {"claude_code", "anthropic_api"}


def get_vision_backend() -> str:
    """Return the vision backend to use, from ``VISION_BACKEND``.

    Defaults to ``"claude_code"`` when the env var is unset or empty --
    this is the free/subscription-based path (shells out to the `claude`
    CLI, billed against an existing Claude Pro/Max subscription) and is
    the deliberate default going forward, to avoid requiring a separate
    metered Anthropic API key unless the caller opts in. The other valid
    value is ``"anthropic_api"`` (calls the Anthropic API directly via
    ``get_anthropic_key()``, separately billed, no CLI dependency).

    Raises:
        RuntimeError: if the env var is explicitly set to anything other
            than ``"claude_code"`` or ``"anthropic_api"``. An unset var
            never raises -- the default silently applies.
    """
    value = os.environ.get("VISION_BACKEND", "")
    if not value:
        return "claude_code"
    if value not in _VALID_VISION_BACKENDS:
        raise RuntimeError(
            f"VISION_BACKEND={value!r} is not a recognized value; expected "
            f"one of {sorted(_VALID_VISION_BACKENDS)} ({_ENV_EXAMPLE_HINT})."
        )
    return value


def get_whisper_cpp_binary() -> str:
    """Return the whisper.cpp CLI binary name/path from ``WHISPER_CPP_BINARY``.

    Defaults to ``"whisper-cli"`` when the env var is unset or empty --
    the current whisper.cpp CLI binary name (the older `main` name is
    historical; `whisper-cli` is what the current Homebrew `whisper.cpp`
    formula installs on macOS). Mirrors ``get_vision_backend()``'s
    "optional, sensible default, never raises on unset" style rather than
    ``get_anthropic_key()``'s "required" style: not every pipeline run
    reaches the audio-transcript fallback, so this must never raise just
    because the env var wasn't set.
    """
    return os.environ.get("WHISPER_CPP_BINARY", "") or "whisper-cli"


def get_whisper_cpp_model_path() -> Path:
    """Return the configured whisper.cpp ggml model path from
    ``WHISPER_CPP_MODEL_PATH``.

    Mirrors ``get_anthropic_key()``'s "conditional, only required when
    actually needed" style rather than ``get_vision_backend()``'s
    always-has-a-default style: unlike the CLI binary name (one
    reasonable default exists), there is no safe default *model file
    path* to assume -- ggml model files are multi-hundred-MB-to-multi-GB
    downloads this project never bundles, so guessing a path would just
    defer an unset-config error from here to a more confusing "file not
    found" deeper inside ``audio/whisper_cpp_transcriber.py``. This is
    only called (and so only required) when the pipeline actually reaches
    the audio-transcript fallback step -- never eagerly at import time.

    Raises:
        RuntimeError: if the env var is unset or empty.
    """
    value = os.environ.get("WHISPER_CPP_MODEL_PATH", "")
    if not value:
        raise RuntimeError(
            f"WHISPER_CPP_MODEL_PATH is not set ({_ENV_EXAMPLE_HINT})."
        )
    return Path(value)


def get_instagram_cookies_file() -> Path | None:
    """Return the configured Instagram cookies file path, if any.

    Reads ``INSTAGRAM_COOKIES_FILE``. This is optional: not every pipeline
    run needs live Instagram access (e.g. unit tests use recorded fixtures),
    so ``None`` is returned when the env var is unset rather than raising.
    Existence of the file is not validated here; that is the ingest
    module's responsibility when it actually tries to use it.
    """
    value = os.environ.get("INSTAGRAM_COOKIES_FILE", "")
    if not value:
        return None
    return Path(value)
