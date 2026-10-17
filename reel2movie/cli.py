"""Command-line entry point: ``python -m reel2movie <reel_url>``.

Loads a ``.env`` file (if present) via ``python-dotenv`` before anything
else runs, so the env vars ``config.py`` reads (``TMDB_API_KEY``, etc.) can
come from a local ``.env`` instead of requiring the caller's shell
environment to already have them set. ``load_dotenv()`` never overrides a
variable already set in the real environment.

Wires the real pipeline (``build_default_pipeline_deps()`` +
``run_pipeline()``) to a minimal argparse CLI and serializes the resulting
``PipelineResult`` to the JSON shape documented in ``brainstorm.md``'s
"Output shape (draft)" section, printed to stdout via
``json.dumps(..., indent=2)``.

Both names below are imported directly into this module's namespace (not
accessed via ``reel2movie.pipeline.deps.build_default_pipeline_deps`` /
``reel2movie.pipeline.waterfall.run_pipeline`` at call time) specifically so
tests can monkeypatch them as ``reel2movie.cli.build_default_pipeline_deps``
/ ``reel2movie.cli.run_pipeline`` -- the same seam-patching pattern earlier
subtasks used (e.g. ``tests/unit/pipeline/test_waterfall.py`` patching
``sample_frames`` on the ``waterfall`` module object).

Error handling: ``build_default_pipeline_deps()`` raises a plain
``RuntimeError`` when a required env var (``TMDB_API_KEY`` /
``ANTHROPIC_API_KEY``) is missing (see ``config.py``), and
``run_pipeline()`` lets step [1]'s ``fetch_metadata`` failure (e.g. an
unreachable/unsupported URL) propagate unmodified, per flow.md's "fail
immediately" rule. Both are caught here -- broadly, not just
``RuntimeError`` -- because the contract this CLI promises its caller is
"no unhandled traceback ever reaches stdout/stderr unformatted," not merely
"the one specific exception type we happened to anticipate." Each is turned
into a one-line message on stderr plus a non-zero exit code;
``KeyboardInterrupt``/``SystemExit`` are untouched since they are not
``Exception`` subclasses.
"""

from __future__ import annotations

import argparse
import json
import sys

from dotenv import load_dotenv

from reel2movie.core.models import PipelineResult, Recommendation, ResolvedMovie
from reel2movie.pipeline.deps import build_default_pipeline_deps
from reel2movie.pipeline.waterfall import run_pipeline


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reel2movie",
        description=(
            "Extract movie recommendations from a reel and resolve them "
            "against TMDB."
        ),
    )
    parser.add_argument(
        "reel_url",
        help="URL of the reel to process (e.g. an Instagram Reel link).",
    )
    parser.add_argument(
        "--frame-count",
        type=int,
        default=None,
        help=(
            "Override the number of frames sampled during the visual "
            "fallback step (default: PipelineDeps' own default)."
        ),
    )
    return parser


def _tmdb_to_dict(tmdb: ResolvedMovie | None) -> dict | None:
    """One `ResolvedMovie` -> the `tmdb` object in brainstorm.md's draft shape.

    Deliberately emits only the five fields the draft shape documents
    (`id`, `title`, `year`, `poster_path`, `overview`) -- `match_score` is
    a real field on `ResolvedMovie` but is not part of the documented
    output contract, so it's left out here rather than leaking an
    undocumented extra key into every CLI invocation's output.
    """
    if tmdb is None:
        return None
    return {
        "id": tmdb.id,
        "title": tmdb.title,
        "year": tmdb.year,
        "poster_path": tmdb.poster_path,
        "overview": tmdb.overview,
    }


def _recommendation_to_dict(rec: Recommendation) -> dict:
    return {
        "query": rec.query,
        "source": rec.source.value,
        "confidence": rec.confidence,
        "tmdb": _tmdb_to_dict(rec.tmdb),
    }


def _result_to_dict(result: PipelineResult) -> dict:
    return {
        "reel_url": result.reel_url,
        "recommendations": [
            _recommendation_to_dict(rec) for rec in result.recommendations
        ],
    }


def main(argv: list[str] | None = None) -> int:
    load_dotenv()  # populates os.environ from a .env file, if one is found; never overrides a var already set

    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        deps = build_default_pipeline_deps()
    except Exception as exc:
        print(f"reel2movie: configuration error: {exc}", file=sys.stderr)
        return 1

    if args.frame_count is not None:
        deps.frame_count = args.frame_count

    try:
        result = run_pipeline(args.reel_url, deps)
    except Exception as exc:
        print(f"reel2movie: failed to process {args.reel_url!r}: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(_result_to_dict(result), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
