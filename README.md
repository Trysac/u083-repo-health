# repo-health

[![PyPI version](https://img.shields.io/pypi/v/trysac-repo-health)](https://pypi.org/project/trysac-repo-health/)
[![License: MIT](https://img.shields.io/pypi/l/trysac-repo-health)](LICENSE)
[![CI](https://github.com/Trysac/u083-repo-health/actions/workflows/ci.yml/badge.svg)](https://github.com/Trysac/u083-repo-health/actions/workflows/ci.yml)

Score a local repository checkout on docs, tests, CI, security and maintenance with ten weighted offline checks and a grade

## Problem

Describe in two or three sentences the concrete problem this utility solves, who hits it, and what
they do today without it. Replace this paragraph when the first real feature lands.

## Install

```sh
pip install trysac-repo-health
# or
uv add trysac-repo-health
```

Requires Python 3.10 or newer. No runtime dependencies.

## Usage

```python
import repo_health

# normalize() trims surrounding whitespace and lower-cases the text.
print(repo_health.normalize("  Hello World "))  # -> "hello world"

# Blank input is rejected explicitly instead of returning an empty string.
try:
    repo_health.normalize("   ")
except ValueError as exc:
    print(f"rejected: {exc}")
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) and [decisions](docs/decisions/)
- [Testing](docs/TESTING.md) and [security](docs/SECURITY.md)
- [Project record](docs/PROJECT.md) and [stack](docs/STACK.md)
- [Changelog](CHANGELOG.md) and [contributing guide](CONTRIBUTING.md)

## License

[MIT](LICENSE) (c) 2026 Miguel Gomez
