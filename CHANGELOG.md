# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Added `repo_health`: ten weighted offline repository health checks (docs, tests, CI, security, maintenance) with `run_checks`, `score`, `SubprocessGit` and a `python -m repo_health` CLI with `--format`, `--min-score` and `--now`.
- Initial project structure from the factory utility template.
