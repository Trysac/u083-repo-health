# repo-health

[![PyPI version](https://img.shields.io/pypi/v/trysac-repo-health)](https://pypi.org/project/trysac-repo-health/)
[![License: MIT](https://img.shields.io/pypi/l/trysac-repo-health)](LICENSE)
[![CI](https://github.com/Trysac/u083-repo-health/actions/workflows/ci.yml/badge.svg)](https://github.com/Trysac/u083-repo-health/actions/workflows/ci.yml)

Score a local repository checkout on docs, tests, CI, security and maintenance with ten weighted offline checks and a grade

## Problem

Maintainers of many repositories cannot tell at a glance which ones lack a license, tests, CI or a security policy. OpenSSF Scorecard needs the GitHub API and focuses on supply-chain security. repo-health is an offline command that scores any local checkout with documented weights, without running repository code, so gaps are visible and CI can gate on a minimum score.

## Install

```sh
pip install trysac-repo-health
# or
uv add trysac-repo-health
```

Requires Python 3.10 or newer. No runtime dependencies.

## Usage

```python
from datetime import datetime, timezone
from pathlib import Path

from repo_health import SubprocessGit, run_checks, score

root = Path(".")
results = run_checks(root, now=datetime.now(timezone.utc), git=SubprocessGit(root))
print(score(results).to_text())
```

Command line: `python -m repo_health [PATH] [--format text|json] [--min-score N] [--now ISO8601]`. Exit codes: 0 success, 1 score below `--min-score` or a domain error, 2 usage or IO error.

## Public API

- `CheckResult`: frozen dataclass with `id`, `category`, `weight`, `status` (`pass`, `fail`, `skipped`) and `detail`.
- `GitPort`: protocol with `last_commit_time()` and `tracked_files()`; a `None` result means the data is unavailable and the check is skipped.
- `SubprocessGit(root, *, timeout=10.0)`: `GitPort` backed by the `git` executable; any failure yields `None`.
- `run_checks(root, *, now, git=None, max_file_bytes=1_048_576, max_files=50_000)`: runs the ten checks and returns them sorted by id.
- `HealthReport`: frozen dataclass with `total`, `by_category`, `grade` and `results`, plus `to_text()` and `to_json()`.
- `score(results)`: computes the weighted total (round half up), per-category scores and grade (A >= 90, B >= 80, C >= 70, D >= 60, else F).
- `RepoHealthError`: raised with `code` `root_missing`, `too_many_files` or `naive_time`.

Checks and weights: DOC001 README with at least 100 words (10); DOC002 license file (10); DOC003 contributing guide (5); DOC004 security policy (10); TST001 test files or a tests directory (10); CI001 CI configuration (10); CI002 CI runs a test command (5); SEC001 no tracked secret-like files (15); SEC002 dependency update configuration (10); MNT001 last commit within 365 days (15).

Limits: files larger than `max_file_bytes` are never read; more than `max_files` files raises `too_many_files`; symlinks are not followed. Timestamps must be timezone-aware.

## Why not OpenSSF Scorecard

Scorecard analyses repositories through the hosting API and focuses on supply-chain security. repo-health works offline on any checkout, covers documentation and maintenance as well, and has no dependencies.

## Security

See [docs/SECURITY.md](docs/SECURITY.md) for the threat model, defenses and limits.

## Documentation

- [Architecture](docs/ARCHITECTURE.md) and [decisions](docs/decisions/)
- [Testing](docs/TESTING.md) and [security](docs/SECURITY.md)
- [Project record](docs/PROJECT.md) and [stack](docs/STACK.md)
- [Changelog](CHANGELOG.md) and [contributing guide](CONTRIBUTING.md)

## License

[MIT](LICENSE) (c) 2026 Miguel Gomez
