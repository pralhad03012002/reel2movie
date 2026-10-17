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
