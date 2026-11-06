"""Score a local repository checkout with ten weighted, offline health checks."""

from __future__ import annotations

import logging

from repo_health.checks import (
    CheckResult,
    GitPort,
    RepoHealthError,
    SubprocessGit,
    run_checks,
)
from repo_health.report import HealthReport, score

__all__ = [
    "CheckResult",
    "GitPort",
    "HealthReport",
    "RepoHealthError",
    "SubprocessGit",
    "__version__",
    "run_checks",
    "score",
]

__version__ = "0.1.0"

logging.getLogger(__name__).addHandler(logging.NullHandler())
