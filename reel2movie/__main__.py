"""Enables ``python -m reel2movie <reel_url>``."""

from __future__ import annotations

from reel2movie.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
