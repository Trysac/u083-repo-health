# Offline checks behind a GitPort with hardened git invocation

Status: accepted (generated, pending human review)

## Context

The tool must score any local checkout on docs, tests, CI, security and maintenance without hosting APIs, network access or executing repository code. Checkouts can be hostile: .git/config can name fsmonitor commands, symlinks can point outside the tree, and files or trees can be arbitrarily large. Tests must be deterministic and independent of a real git repository.

## Decision

Implement ten fixed, weighted checks over a symlink-free file walk, with git data supplied through a GitPort protocol. SubprocessGit runs git with shell=False, --no-pager, core.fsmonitor=false, GIT_CONFIG_NOSYSTEM=1, GIT_TERMINAL_PROMPT=0 and a timeout, and returns None on any failure so the dependent checks are skipped and excluded from the score denominator. Scores use integer arithmetic (200*p + w) // (2*w) to round half up. Size limits (max_file_bytes, max_files) are enforced before reading and while walking, and a typed RepoHealthError with stable codes reports domain failures.

## Consequences

The score is reproducible and unit-testable with a FakeGit; only one test needs a real git repository. Repositories without git history are scored on the remaining checks rather than penalised. A malicious git binary on PATH is not defended against, and SEC001 inspects file names only. Weights are fixed in code, so changing them is a breaking change to scores.
