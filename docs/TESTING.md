# Testing

## Running

```sh
uv run pytest --cov=repo_health   # tests with coverage report
uv run python scripts/check.py      # every gate, as CI and the factory run it
```

## Test files

- `tests/test_repo_health.py` is the only test module. It covers the public API and the CLI: the complete fixture scoring 100 and grade A, scores with LICENSE and SECURITY.md removed, SEC001 on tracked secret names (including `.env.example` and `id_rsa.pub` passing), MNT001 at 365 and 366 days, a naive `now` raising `naive_time`, skipped checks when git returns `None`, the `--min-score` exit code, the JSON output keys, the exact git command lines and the `too_many_files` and `max_file_bytes` limits. It uses a `FakeGit` double; a real repository test for the fsmonitor override is skipped when git is not installed.

## Policy

- Tests exercise the public API (`import repo_health`) and assert return values, raised exceptions and their messages.
- Tests are deterministic: no network, a fixed reference time, no dependence on test order.

## Layout

`tests/test_repo_health.py` covers the package. Shared fixtures are not defined beyond that module.
