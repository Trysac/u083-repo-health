# Security

This document is the threat model of `trysac-repo-health`. To report a vulnerability, follow the repository's `SECURITY.md` at the root.

## Threat model

The tool scores a checkout that may come from an untrusted source. The attacker controls the content of the checkout, including `.git/config`, file names, symlinks and file sizes. The tool must not execute code from the checkout, read outside of it, or exhaust memory.

## Defenses

- **No repository code is executed.** Checks only list files and read text files; CI files are searched with a regular expression and never run.
- **Git is hardened.** Git is invoked with `shell=False`, `--no-pager`, `-c core.fsmonitor=false`, `GIT_CONFIG_NOSYSTEM=1`, `GIT_TERMINAL_PROMPT=0` and a timeout of 10 seconds. A cloned `.git/config` can name `core.fsmonitor` commands; the override prevents this.
- **Symlinks are not followed.** Symlinked files and directories are ignored during the walk.
- **Size limits.** Files larger than `max_file_bytes` (default 1 MiB) are never opened. At most `max_files` (default 50,000) files are walked or tracked, otherwise `RepoHealthError` with code `too_many_files` is raised.
- **Bounded output.** Error messages and check details are capped at 200 characters and non-printable characters are replaced.
- **No network, no content logging.** The library logs debug messages only and never logs file contents.

## Not defended

- A malicious `git` binary earlier on `PATH`: the executable is resolved through `PATH`.
- A checkout that is modified concurrently while it is being scanned.
- Secrets tracked under names other than the ones SEC001 recognises; SEC001 checks file names only, not file contents.

## Failure behaviour

`SubprocessGit` returns `None` when git is missing, exits non-zero, times out or prints unparsable output. The dependent checks (SEC001, MNT001) are then skipped and leave the score denominator.
