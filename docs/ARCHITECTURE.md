# Architecture

## Purpose

`trysac-repo-health` is a small, dependency-free Python library and CLI that scores a local repository checkout on docs, tests, CI, security and maintenance with ten weighted offline checks and a grade.

## Shape

```text
caller code / CLI --> repo_health (public API in __init__.py)
                          |
                          +-- checks.py   file scan, ten checks, SubprocessGit
                          +-- report.py   weighted score, grade, text and JSON rendering
                          +-- __main__.py command line interface
```

- **Public API**: the names listed in `__all__` of `src/repo_health/__init__.py`: `CheckResult`, `GitPort`, `HealthReport`, `RepoHealthError`, `SubprocessGit`, `run_checks`, `score`, `__version__`.
- **Errors**: `RepoHealthError` carries a stable `code`. The CLI prints errors to stderr and never raises to the user.
- **Side effects**: reads files under the checkout and runs `git` through `SubprocessGit`. Nothing is written.
- **Logging**: `logging.getLogger(__name__)` with a `NullHandler` only.

## Quality contract

`scripts/check.py` is the single definition of the gates; `fabrica.json` tells the factory and CI how to run it. See [TESTING.md](TESTING.md).

## Decisions

Architecture decisions are recorded in [decisions/](decisions/) as numbered ADRs.
