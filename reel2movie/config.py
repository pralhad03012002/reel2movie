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
