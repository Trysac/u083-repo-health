"""Command line interface: ``python -m repo_health``."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from repo_health.checks import RepoHealthError, SubprocessGit, run_checks
from repo_health.report import score

_MAX_NUMBER_CHARS = 16
_MAX_TIMESTAMP_CHARS = 64


def _min_score(text: str) -> int:
    if len(text) > _MAX_NUMBER_CHARS:
        raise argparse.ArgumentTypeError("number is too long")
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if not 0 <= value <= 100:
        raise argparse.ArgumentTypeError("must be between 0 and 100")
    return value


def _timestamp(text: str) -> datetime:
    if len(text) > _MAX_TIMESTAMP_CHARS:
        raise argparse.ArgumentTypeError("timestamp is too long")
    value = f"{text[:-1]}+00:00" if text.endswith(("Z", "z")) else text
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an ISO 8601 timestamp") from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repo-health",
        description="Score a local repository checkout with ten weighted offline checks.",
    )
    parser.add_argument("path", nargs="?", default=".", help="repository root (default: .)")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--min-score", type=_min_score, default=None, metavar="N")
    parser.add_argument("--now", type=_timestamp, default=None, metavar="ISO8601")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return the exit code.

    0: success; 1: score below ``--min-score`` or a domain failure; 2: usage or IO error.
    """
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code
        return code if isinstance(code, int) else 2
    now = args.now if args.now is not None else datetime.now(timezone.utc)
    root = Path(args.path)
    try:
        results = run_checks(root, now=now, git=SubprocessGit(root))
    except RepoHealthError as exc:
        print(f"repo-health: error: {exc.code}: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"repo-health: error: {exc.strerror or 'io error'}", file=sys.stderr)
        return 2
    report = score(results)
    print(report.to_json() if args.format == "json" else report.to_text())
    if args.min_score is not None and report.total < args.min_score:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
