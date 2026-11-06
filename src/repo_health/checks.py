"""Ten weighted, offline repository health checks.

The checks never execute repository code. Files are discovered without following symlinks,
files larger than ``max_file_bytes`` are never read, and git is reached only through the
``GitPort`` protocol.
"""

from __future__ import annotations

import fnmatch
import logging
import os
import posixpath
import re
import stat
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Protocol

logger = logging.getLogger(__name__)

Category = Literal["docs", "tests", "ci", "security", "maintenance"]
Status = Literal["pass", "fail", "skipped"]
ErrorCode = Literal["root_missing", "too_many_files", "naive_time"]

_DETAIL_LIMIT = 200
_MIN_README_WORDS = 100
_MAINTAINED_WINDOW = timedelta(days=365)
_WORKFLOW_DIR = ".github/workflows/"
_GITLAB_CI = ".gitlab-ci.yml"
_CI_PATTERN = r"(?<!\w)(?:pytest|npm\s+test|go\s+test|tox|nox|make\s+test)(?!\w)"
_CI_COMMAND = re.compile(_CI_PATTERN)
_README_NAMES = frozenset({"readme", "readme.md", "readme.rst", "readme.txt", "readme.markdown"})
_LICENSE_NAMES = frozenset({"license", "license.md", "license.txt", "copying"})
_CONTRIBUTING_NAMES = frozenset(
    {"contributing", "contributing.md", "contributing.rst", "contributing.txt"}
)
_SECURITY_NAMES = frozenset({"security.md"})
_TEST_PATTERNS = ("test_*.py", "*_test.py", "*_test.go", "*.test.ts", "*.spec.ts")
_UPDATE_FILES = frozenset(
    {
        ".github/dependabot.yml",
        ".github/dependabot.yaml",
        "renovate.json",
        "renovate.json5",
        ".renovaterc",
        ".renovaterc.json",
        ".github/renovate.json",
        ".github/renovate.json5",
        ".gitlab/renovate.json5",
    }
)
_SECRET_KEY_NAMES = frozenset({"id_rsa", "id_ed25519"})

_META: dict[str, tuple[Category, int]] = {
    "DOC001": ("docs", 10),
    "DOC002": ("docs", 10),
    "DOC003": ("docs", 5),
    "DOC004": ("docs", 10),
    "TST001": ("tests", 10),
    "CI001": ("ci", 10),
    "CI002": ("ci", 5),
    "SEC001": ("security", 15),
    "SEC002": ("security", 10),
    "MNT001": ("maintenance", 15),
}


def _clip(text: str, limit: int = _DETAIL_LIMIT) -> str:
    """Replace non-printable characters and cap the length of ``text``."""
    cleaned = "".join(ch if ch.isprintable() else "?" for ch in text)
    return cleaned[:limit]


class RepoHealthError(Exception):
    """Base error of the library.

    Attributes:
        code: stable machine-readable identifier, one of ``root_missing``,
            ``too_many_files`` or ``naive_time``.
    """

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(_clip(message))
        self.code: ErrorCode = code


@dataclass(frozen=True)
class CheckResult:
    """Outcome of a single check."""

    id: str
    category: Category
    weight: int
    status: Status
    detail: str


class GitPort(Protocol):
    """Access to git data; ``None`` means the information is unavailable (check skipped)."""

    def last_commit_time(self) -> datetime | None:
        """Return the committer time of HEAD (timezone-aware) or ``None``."""
        ...

    def tracked_files(self) -> list[str] | None:
        """Return the tracked paths relative to the root or ``None``."""
        ...


class SubprocessGit:
    """``GitPort`` backed by the ``git`` executable.

    Git is run without a shell, without a pager, with ``core.fsmonitor`` disabled, with the
    system configuration ignored and with terminal prompts disabled. Any failure (missing git,
    non-zero exit, timeout, unparsable output) yields ``None``.
    """

    def __init__(self, root: Path, *, timeout: float = 10.0) -> None:
        self._root = root
        self._timeout = timeout

    def _run(self, *args: str) -> bytes | None:
        cmd = ["git", "--no-pager", "-c", "core.fsmonitor=false", *args]
        env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"}
        try:
            proc = subprocess.run(
                cmd,
                cwd=self._root,
                env=env,
                capture_output=True,
                check=False,
                shell=False,
                timeout=self._timeout,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logger.debug("git unavailable: %s", type(exc).__name__)
            return None
        if proc.returncode != 0:
            logger.debug("git exited with status %s", proc.returncode)
            return None
        stdout: bytes = proc.stdout
        return stdout

    def last_commit_time(self) -> datetime | None:
        """Return the committer time of HEAD or ``None``."""
        out = self._run("log", "-1", "--format=%cI")
        if out is None:
            return None
        text = out.decode("utf-8", errors="replace").strip()
        if not text:
            return None
        if text.endswith(
            "Z"
        ):  # newer git prints UTC as "Z", which fromisoformat accepts only from Python 3.11
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            logger.debug("unparsable commit time")
            return None
        if parsed.utcoffset() is None:
            return None
        return parsed

    def tracked_files(self) -> list[str] | None:
        """Return the tracked paths (``git ls-files -z``) or ``None``."""
        out = self._run("ls-files", "-z")
        if out is None:
            return None
        names = out.decode("utf-8", errors="replace").split("\0")
        return [name for name in names if name]


class _TooLargeError(Exception):
    """Raised internally when a file exceeds the configured size limit."""


def _read_text(path: Path, limit: int) -> str:
    """Read a regular file of at most ``limit`` bytes; never opens larger files."""
    info = os.lstat(path)
    if not stat.S_ISREG(info.st_mode):
        raise OSError("not a regular file")
    if info.st_size > limit:
        raise _TooLargeError
    with open(path, "rb") as handle:
        data = handle.read(limit)
    return data.decode("utf-8", errors="replace")


@dataclass(frozen=True)
class _Tree:
    root: Path
    files: tuple[str, ...]
    dirs: frozenset[str]
    max_file_bytes: int

    def find(self, folders: Sequence[str], names: frozenset[str]) -> str | None:
        """Return the first file in one of ``folders`` whose lower-cased name is in ``names``."""
        for rel in self.files:
            folder, _, base = rel.rpartition("/")
            if folder in folders and base.lower() in names:
                return rel
        return None

    def read(self, rel: str) -> str:
        return _read_text(self.root / rel, self.max_file_bytes)


def _scan(root: Path, max_files: int) -> tuple[tuple[str, ...], frozenset[str]]:
    """List regular files and directories below ``root`` without following symlinks."""
    files: list[str] = []
    dirs: set[str] = {""}
    pending = [""]
    while pending:
        folder = pending.pop()
        with os.scandir(root / folder if folder else root) as entries:
            for entry in entries:
                if entry.name == ".git" or entry.is_symlink():
                    continue
                rel = f"{folder}/{entry.name}" if folder else entry.name
                if entry.is_dir(follow_symlinks=False):
                    dirs.add(rel)
                    pending.append(rel)
                elif entry.is_file(follow_symlinks=False):
                    files.append(rel)
                    if len(files) > max_files:
                        raise RepoHealthError("too_many_files", "too many files in the checkout")
    return tuple(sorted(files)), frozenset(dirs)


def _result(check_id: str, ok: bool | None, detail: str) -> CheckResult:
    category, weight = _META[check_id]
    status: Status = "skipped" if ok is None else ("pass" if ok else "fail")
    return CheckResult(check_id, category, weight, status, _clip(detail))


def _require_aware(value: datetime, what: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RepoHealthError("naive_time", f"{what} must be timezone-aware")


def _doc001(tree: _Tree) -> CheckResult:
    rel = tree.find(("",), _README_NAMES)
    if rel is None:
        return _result("DOC001", False, "missing")
    try:
        text = tree.read(rel)
    except _TooLargeError:
        return _result("DOC001", False, "too large")
    except OSError:
        return _result("DOC001", False, "unreadable")
    words = len(text.split())
    return _result("DOC001", words >= _MIN_README_WORDS, f"{words} words")


def _presence(
    tree: _Tree, check_id: str, folders: Sequence[str], names: frozenset[str]
) -> CheckResult:
    rel = tree.find(folders, names)
    if rel is None:
        return _result(check_id, False, "missing")
    return _result(check_id, True, f"found {rel}")


def _tst001(tree: _Tree) -> CheckResult:
    for rel in tree.files:
        base = rel.rpartition("/")[2]
        if any(fnmatch.fnmatchcase(base, pattern) for pattern in _TEST_PATTERNS):
            return _result("TST001", True, f"test file {rel}")
    for folder in sorted(tree.dirs):
        if folder.rpartition("/")[2] == "tests":
            return _result("TST001", True, f"tests directory {folder}")
    return _result("TST001", False, "no test files")


def _ci_files(tree: _Tree) -> list[str]:
    return [rel for rel in tree.files if rel.startswith(_WORKFLOW_DIR) or rel == _GITLAB_CI]


def _ci001(tree: _Tree) -> CheckResult:
    found = _ci_files(tree)
    if found:
        return _result("CI001", True, f"CI configuration {found[0]}")
    return _result("CI001", False, "no CI configuration")


def _ci002(tree: _Tree) -> CheckResult:
    unreadable = 0
    for rel in _ci_files(tree):
        try:
            text = tree.read(rel)
        except (_TooLargeError, OSError):
            unreadable += 1
            continue
        if _CI_COMMAND.search(text):
            return _result("CI002", True, f"test command in {rel}")
    if unreadable:
        return _result("CI002", False, f"no test command found ({unreadable} unreadable)")
    return _result("CI002", False, "no test command found")


def _is_secret_name(path: str) -> bool:
    name = posixpath.basename(path).lower()
    if name.endswith((".example", ".sample")):
        return False
    return (
        name == ".env"
        or name.startswith(".env.")
        or name.endswith((".pem", ".key"))
        or name in _SECRET_KEY_NAMES
    )


def _sec001(tracked: list[str] | None) -> CheckResult:
    if tracked is None:
        return _result("SEC001", None, "git unavailable")
    bad = [path for path in tracked if _is_secret_name(path)]
    if bad:
        return _result("SEC001", False, "tracked secret files: " + ", ".join(bad[:5]))
    return _result("SEC001", True, "no tracked secret files")


def _sec002(tree: _Tree) -> CheckResult:
    for rel in tree.files:
        if rel in _UPDATE_FILES:
            return _result("SEC002", True, f"found {rel}")
    return _result("SEC002", False, "no dependency update configuration")


def _mnt001(last: datetime | None, now: datetime) -> CheckResult:
    if last is None:
        return _result("MNT001", None, "git unavailable")
    _require_aware(last, "commit time")
    age = now.astimezone(timezone.utc) - last.astimezone(timezone.utc)
    return _result("MNT001", age <= _MAINTAINED_WINDOW, f"last commit {age.days} days ago")


def run_checks(
    root: Path,
    *,
    now: datetime,
    git: GitPort | None = None,
    max_file_bytes: int = 1_048_576,
    max_files: int = 50_000,
) -> list[CheckResult]:
    """Run the ten checks against the checkout at ``root``.

    Args:
        root: directory of the checkout.
        now: timezone-aware reference time (compared in UTC).
        git: git access; defaults to ``SubprocessGit(root)``.
        max_file_bytes: files larger than this are never read.
        max_files: maximum number of walked or tracked files.

    Returns:
        The results sorted by check id.

    Raises:
        RepoHealthError: ``naive_time``, ``root_missing`` or ``too_many_files``.
        OSError: if a directory cannot be listed.
    """
    _require_aware(now, "now")
    if not root.is_dir():
        raise RepoHealthError("root_missing", "root is not a directory")
    files, dirs = _scan(root, max_files)
    tree = _Tree(root, files, dirs, max_file_bytes)
    port: GitPort = SubprocessGit(root) if git is None else git
    tracked = port.tracked_files()
    if tracked is not None and len(tracked) > max_files:
        raise RepoHealthError("too_many_files", "too many tracked files")
    last = port.last_commit_time()
    results = [
        _doc001(tree),
        _presence(tree, "DOC002", ("",), _LICENSE_NAMES),
        _presence(tree, "DOC003", ("", ".github", "docs"), _CONTRIBUTING_NAMES),
        _presence(tree, "DOC004", ("", ".github", "docs"), _SECURITY_NAMES),
        _tst001(tree),
        _ci001(tree),
        _ci002(tree),
        _sec001(tracked),
        _sec002(tree),
        _mnt001(last, now),
    ]
    return sorted(results, key=lambda item: item.id)
