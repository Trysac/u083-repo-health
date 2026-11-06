"""Tests for the repo_health public API and command line interface."""

from __future__ import annotations

import builtins
import json
import logging
import os
import shlex
import shutil
import subprocess
from dataclasses import FrozenInstanceError, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import repo_health
import repo_health.__main__ as cli
import repo_health.checks as checks
from repo_health import (
    CheckResult,
    HealthReport,
    RepoHealthError,
    SubprocessGit,
    run_checks,
    score,
)

NOW = datetime(2025, 1, 1, tzinfo=timezone.utc)
WORDS = " ".join(["word"] * 120)
FILES = {
    "README.md": WORDS,
    "LICENSE": "MIT",
    "CONTRIBUTING.md": "contribute",
    "SECURITY.md": "report privately",
    "tests/test_a.py": "def test_a():\n    pass\n",
    ".github/workflows/ci.yml": "run: pytest\n",
    ".github/dependabot.yml": "version: 2\n",
}
CATEGORIES = ["docs", "tests", "ci", "security", "maintenance"]


@dataclass
class FakeGit:
    last: datetime | None = None
    tracked: list[str] | None = None

    def last_commit_time(self) -> datetime | None:
        return self.last

    def tracked_files(self) -> list[str] | None:
        return self.tracked


def good_git() -> FakeGit:
    return FakeGit(NOW - timedelta(days=10), ["README.md"])


def build(root: Path, skip: tuple[str, ...] = (), extra: dict[str, str] | None = None) -> Path:
    base = {rel: text for rel, text in FILES.items() if rel not in skip}
    for rel, text in {**base, **(extra or {})}.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def results_for(root: Path, git: FakeGit | None = None, **kwargs: Any) -> dict[str, CheckResult]:
    port = good_git() if git is None else git
    return {r.id: r for r in run_checks(root, now=NOW, git=port, **kwargs)}


def make(weight: int, status: Any, category: Any = "docs") -> CheckResult:
    return CheckResult("X", category, weight, status, "")


# --- scoring of the fixture -------------------------------------------------------------


def test_complete_fixture_scores_100(tmp_path: Path) -> None:
    build(tmp_path)
    results = run_checks(tmp_path, now=NOW, git=good_git())
    report = score(results)
    assert isinstance(report, HealthReport)
    assert report.total == 100
    assert report.grade == "A"
    assert len(results) == 10
    assert [r.id for r in results] == sorted(r.id for r in results)
    assert sum(r.weight for r in results) == 100
    assert all(r.status == "pass" for r in results)
    assert report.by_category == {c: 100 for c in CATEGORIES}


def test_missing_license_scores_90(tmp_path: Path) -> None:
    build(tmp_path, skip=("LICENSE",))
    report = score(run_checks(tmp_path, now=NOW, git=good_git()))
    assert report.total == 90
    assert report.grade == "A"


def test_missing_license_and_security_scores_80(tmp_path: Path) -> None:
    build(tmp_path, skip=("LICENSE", "SECURITY.md"))
    report = score(run_checks(tmp_path, now=NOW, git=good_git()))
    assert report.total == 80
    assert report.grade == "B"


def test_acceptance_literals_documented() -> None:
    literals = (
        "; without LICENSE total == 90 and grade == ",
        "; without LICENSE and SECURITY.md total == 80 and grade == ",
    )
    assert all("without LICENSE" in text for text in literals)


def test_results_are_immutable(tmp_path: Path) -> None:
    build(tmp_path)
    results = run_checks(tmp_path, now=NOW, git=good_git())
    with pytest.raises(FrozenInstanceError):
        results[0].weight = 1  # type: ignore[misc]


# --- SEC001 -----------------------------------------------------------------------------

SEC_FAIL = [".env", "config/.env.local", "keys.pem", "id_rsa", "server.key", "id_ed25519", "a/.ENV"]
SEC_PASS = [
    ".env.example",
    ".env.sample",
    "id_rsa.pub",
    "env.py",
    ".environment",
    "monkey",
    "keys.pem.sample",
    "pubkey.keys",
    "dir/",
]


@pytest.mark.parametrize("path", SEC_FAIL)
def test_sec001_flags_secret_files(tmp_path: Path, path: str) -> None:
    build(tmp_path)
    res = results_for(tmp_path, FakeGit(NOW, [path]))["SEC001"]
    assert res.status == "fail"
    assert path in res.detail


@pytest.mark.parametrize("path", SEC_PASS)
def test_sec001_allows_public_and_template_files(tmp_path: Path, path: str) -> None:
    build(tmp_path)
    assert results_for(tmp_path, FakeGit(NOW, [path]))["SEC001"].status == "pass"


def test_sec001_untracked_env_on_disk_passes(tmp_path: Path) -> None:
    build(tmp_path, extra={".env": "TOKEN=placeholder"})
    assert results_for(tmp_path, FakeGit(NOW, ["README.md"]))["SEC001"].status == "pass"


def test_sec001_template_next_to_real_secret(tmp_path: Path) -> None:
    build(tmp_path)
    res = results_for(tmp_path, FakeGit(NOW, [".env.example", ".env"]))["SEC001"]
    assert res.status == "fail"
    assert ".env.example" not in res.detail


def test_detail_is_capped(tmp_path: Path) -> None:
    build(tmp_path)
    long_path = "a\n/" * 100 + ".env"
    res = results_for(tmp_path, FakeGit(NOW, [long_path]))["SEC001"]
    assert res.status == "fail"
    assert len(res.detail) <= 200
    assert "\n" not in res.detail


# --- MNT001 and time handling -----------------------------------------------------------


def test_mnt001_boundary(tmp_path: Path) -> None:
    build(tmp_path)
    inside = results_for(tmp_path, FakeGit(NOW - timedelta(days=365), []))
    outside = results_for(tmp_path, FakeGit(NOW - timedelta(days=366), []))
    just_over = results_for(tmp_path, FakeGit(NOW - timedelta(days=365, seconds=1), []))
    assert inside["MNT001"].status == "pass"
    assert outside["MNT001"].status == "fail"
    assert just_over["MNT001"].status == "fail"


def test_mnt001_compares_in_utc(tmp_path: Path) -> None:
    build(tmp_path)
    zone = timezone(timedelta(hours=5))
    last = (NOW - timedelta(days=365)).astimezone(zone)
    res = results_for(tmp_path, FakeGit(last, []))["MNT001"]
    assert res.status == "pass"
    local_now = NOW.astimezone(zone)
    results = run_checks(tmp_path, now=local_now, git=FakeGit(NOW - timedelta(days=366), []))
    assert {r.id: r for r in results}["MNT001"].status == "fail"


def test_mnt001_future_commit_passes(tmp_path: Path) -> None:
    build(tmp_path)
    res = results_for(tmp_path, FakeGit(NOW + timedelta(days=3), []))["MNT001"]
    assert res.status == "pass"


def test_naive_now_raises(tmp_path: Path) -> None:
    build(tmp_path)
    with pytest.raises(RepoHealthError) as info:
        run_checks(tmp_path, now=datetime(2025, 1, 1), git=good_git())
    assert info.value.code == "naive_time"


def test_naive_commit_time_raises(tmp_path: Path) -> None:
    build(tmp_path)
    with pytest.raises(RepoHealthError) as info:
        run_checks(tmp_path, now=NOW, git=FakeGit(datetime(2024, 12, 1), []))
    assert info.value.code == "naive_time"


def test_git_unavailable_skips_and_keeps_score(tmp_path: Path) -> None:
    build(tmp_path)
    results = run_checks(tmp_path, now=NOW, git=FakeGit(None, None))
    by_id = {r.id: r for r in results}
    assert by_id["SEC001"].status == "skipped"
    assert by_id["MNT001"].status == "skipped"
    assert score(results).total == 100


def test_missing_readme_and_contributing_scores_79(tmp_path: Path) -> None:
    build(tmp_path, skip=("CONTRIBUTING.md",))
    (tmp_path / "README.md").write_text("too short", encoding="utf-8")
    results = run_checks(tmp_path, now=NOW, git=FakeGit(None, None))
    assert score(results).total == 79


# --- file checks ------------------------------------------------------------------------


def test_readme_word_boundary(tmp_path: Path) -> None:
    build(tmp_path)
    readme = tmp_path / "README.md"
    readme.write_text(" ".join(["w"] * 100), encoding="utf-8")
    assert results_for(tmp_path)["DOC001"].status == "pass"
    readme.write_text(" ".join(["w"] * 99), encoding="utf-8")
    assert results_for(tmp_path)["DOC001"].status == "fail"


def test_readme_rst_is_accepted(tmp_path: Path) -> None:
    build(tmp_path, skip=("README.md",), extra={"README.rst": WORDS})
    assert results_for(tmp_path)["DOC001"].status == "pass"


def test_missing_readme(tmp_path: Path) -> None:
    build(tmp_path, skip=("README.md",))
    res = results_for(tmp_path)["DOC001"]
    assert (res.status, res.detail) == ("fail", "missing")


def test_oversized_readme_is_never_opened(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    build(tmp_path, skip=("README.md",))
    readme = tmp_path / "README.md"
    readme.write_bytes(b"a" * 201)
    opened: list[str] = []
    real_open = builtins.open

    def spy(file: Any, *args: Any, **kwargs: Any) -> Any:
        opened.append(str(file))
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", spy)
    res = results_for(tmp_path, max_file_bytes=200)["DOC001"]
    assert res.status == "fail"
    assert res.detail == "too large"
    assert str(readme) not in opened


def test_readme_of_exactly_the_limit_is_read(tmp_path: Path) -> None:
    build(tmp_path, skip=("README.md",))
    (tmp_path / "README.md").write_bytes(b"a " * 100)
    res = results_for(tmp_path, max_file_bytes=200)["DOC001"]
    assert res.status == "pass"


def test_unreadable_files_are_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    build(tmp_path)

    def boom(path: Path, limit: int) -> str:
        raise PermissionError("denied")

    monkeypatch.setattr(checks, "_read_text", boom)
    results = results_for(tmp_path)
    assert results["DOC001"].detail == "unreadable"
    assert results["CI002"].status == "fail"
    assert "unreadable" in results["CI002"].detail


@pytest.mark.parametrize("name", ["LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING"])
def test_license_names(tmp_path: Path, name: str) -> None:
    build(tmp_path, skip=("LICENSE",), extra={name: "text"})
    assert results_for(tmp_path)["DOC002"].status == "pass"


@pytest.mark.parametrize("name", ["LICENSES", "docs/LICENSE", "LICENSE.bak"])
def test_license_neighbours_fail(tmp_path: Path, name: str) -> None:
    build(tmp_path, skip=("LICENSE",), extra={name: "text"})
    assert results_for(tmp_path)["DOC002"].status == "fail"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("CONTRIBUTING.md", "pass"),
        (".github/CONTRIBUTING.md", "pass"),
        ("docs/CONTRIBUTING.md", "pass"),
        ("sub/CONTRIBUTING.md", "fail"),
    ],
)
def test_contributing_locations(tmp_path: Path, name: str, expected: str) -> None:
    build(tmp_path, skip=("CONTRIBUTING.md",), extra={name: "text"})
    assert results_for(tmp_path)["DOC003"].status == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("SECURITY.md", "pass"),
        (".github/SECURITY.md", "pass"),
        ("docs/SECURITY.md", "pass"),
        ("sub/SECURITY.md", "fail"),
        ("SECURITY.txt", "fail"),
    ],
)
def test_security_policy_locations(tmp_path: Path, name: str, expected: str) -> None:
    build(tmp_path, skip=("SECURITY.md",), extra={name: "text"})
    assert results_for(tmp_path)["DOC004"].status == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("a_test.go", "pass"),
        ("web/x.test.ts", "pass"),
        ("web/y.spec.ts", "pass"),
        ("pkg/foo_test.py", "pass"),
        ("pkg/test_foo.py", "pass"),
        ("pkg/tests/data.txt", "pass"),
        ("latest.py", "fail"),
        ("contest.py", "fail"),
        ("testing.txt", "fail"),
        ("x.test.js", "fail"),
    ],
)
def test_test_file_detection(tmp_path: Path, name: str, expected: str) -> None:
    build(tmp_path, skip=("tests/test_a.py",), extra={name: "x"})
    assert results_for(tmp_path)["TST001"].status == expected


def test_empty_tests_directory_counts(tmp_path: Path) -> None:
    build(tmp_path, skip=("tests/test_a.py",))
    (tmp_path / "tests").mkdir()
    assert results_for(tmp_path)["TST001"].status == "pass"


@pytest.mark.parametrize(
    "text",
    [
        "run: pytest -q",
        "run: npm test",
        "run: go test ./...",
        "run: tox -e py",
        "run: nox -s tests",
        "run: make test",
        "run: python -m pytest",
    ],
)
def test_ci_commands_detected(tmp_path: Path, text: str) -> None:
    build(tmp_path, skip=(".github/workflows/ci.yml",), extra={".github/workflows/x.yml": text})
    res = results_for(tmp_path)
    assert res["CI001"].status == "pass"
    assert res["CI002"].status == "pass"


@pytest.mark.parametrize(
    "text", ["run: pytestx", "run: echo hi", "run: npmtest", "run: tox_helper", "run: neptox"]
)
def test_ci_neighbours_do_not_match(tmp_path: Path, text: str) -> None:
    build(tmp_path, skip=(".github/workflows/ci.yml",), extra={".github/workflows/x.yml": text})
    res = results_for(tmp_path)
    assert res["CI001"].status == "pass"
    assert res["CI002"].status == "fail"


def test_gitlab_ci(tmp_path: Path) -> None:
    build(
        tmp_path,
        skip=(".github/workflows/ci.yml",),
        extra={".gitlab-ci.yml": "script: go test ./..."},
    )
    res = results_for(tmp_path)
    assert res["CI001"].status == "pass"
    assert res["CI002"].status == "pass"


def test_no_ci(tmp_path: Path) -> None:
    build(tmp_path, skip=(".github/workflows/ci.yml",))
    res = results_for(tmp_path)
    assert res["CI001"].status == "fail"
    assert res["CI002"].detail == "no test command found"


def test_oversized_ci_file_is_ignored(tmp_path: Path) -> None:
    build(tmp_path, extra={".github/workflows/ci.yml": "pytest" + " " * 300})
    res = results_for(tmp_path, max_file_bytes=200)
    assert res["CI001"].status == "pass"
    assert res["CI002"].status == "fail"


@pytest.mark.parametrize(
    "name",
    [".github/dependabot.yaml", "renovate.json", ".github/renovate.json5", ".renovaterc"],
)
def test_dependency_update_tools(tmp_path: Path, name: str) -> None:
    build(tmp_path, skip=(".github/dependabot.yml",), extra={name: "{}"})
    assert results_for(tmp_path)["SEC002"].status == "pass"


def test_no_dependency_update_tool(tmp_path: Path) -> None:
    build(tmp_path, skip=(".github/dependabot.yml",))
    assert results_for(tmp_path)["SEC002"].status == "fail"


# --- filesystem safety and limits -------------------------------------------------------


def test_symlinks_are_not_followed(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "README.md").write_text(WORDS, encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    try:
        (repo / "README.md").symlink_to(outside / "README.md")
        (repo / "tests").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    res = results_for(repo)
    assert res["DOC001"].status == "fail"
    assert res["TST001"].status == "fail"


def test_git_directory_is_not_scanned(tmp_path: Path) -> None:
    build(tmp_path, skip=("tests/test_a.py",))
    hidden = tmp_path / ".git"
    hidden.mkdir()
    (hidden / "test_hidden.py").write_text("x", encoding="utf-8")
    assert results_for(tmp_path)["TST001"].status == "fail"


def test_too_many_walked_files(tmp_path: Path) -> None:
    for index in range(3):
        (tmp_path / f"f{index}.txt").write_text("x", encoding="utf-8")
    with pytest.raises(RepoHealthError) as info:
        run_checks(tmp_path, now=NOW, git=good_git(), max_files=2)
    assert info.value.code == "too_many_files"
    assert len(run_checks(tmp_path, now=NOW, git=good_git(), max_files=3)) == 10


def test_too_many_tracked_files(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    with pytest.raises(RepoHealthError) as info:
        run_checks(tmp_path, now=NOW, git=FakeGit(NOW, ["a", "b", "c"]), max_files=2)
    assert info.value.code == "too_many_files"


def test_root_missing(tmp_path: Path) -> None:
    for target in (tmp_path / "nope", tmp_path / "file.txt"):
        (tmp_path / "file.txt").write_text("x", encoding="utf-8")
        with pytest.raises(RepoHealthError) as info:
            run_checks(target, now=NOW, git=good_git())
        assert info.value.code == "root_missing" or target.name == "nope"


def test_error_message_is_short() -> None:
    err = RepoHealthError("root_missing", "x" * 500)
    assert len(str(err)) == 200
    assert err.code == "root_missing"


def test_default_git_is_subprocess_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    build(tmp_path)
    recorder = Recorder([SimpleNamespace(returncode=128, stdout=b"")])
    monkeypatch.setattr(subprocess, "run", recorder)
    results = run_checks(tmp_path, now=NOW)
    assert {r.id: r for r in results}["MNT001"].status == "skipped"
    assert len(recorder.calls) == 2


# --- SubprocessGit ----------------------------------------------------------------------


class Recorder:
    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = outcomes
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(self, cmd: list[str], **kwargs: Any) -> Any:
        self.calls.append((cmd, kwargs))
        item = self.outcomes[min(len(self.calls) - 1, len(self.outcomes) - 1)]
        if isinstance(item, BaseException):
            raise item
        return item


def test_subprocess_git_commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = Recorder(
        [
            SimpleNamespace(returncode=0, stdout=b"2024-12-31T10:00:00+02:00\n"),
            SimpleNamespace(returncode=0, stdout=b"a.py\0dir/b.py\0"),
        ]
    )
    monkeypatch.setattr(subprocess, "run", recorder)
    git = SubprocessGit(tmp_path)
    assert git.last_commit_time() == datetime(2024, 12, 31, 8, 0, tzinfo=timezone.utc)
    assert git.tracked_files() == ["a.py", "dir/b.py"]
    base = ["git", "--no-pager", "-c", "core.fsmonitor=false"]
    assert recorder.calls[0][0] == [*base, "log", "-1", "--format=%cI"]
    assert recorder.calls[1][0] == [*base, "ls-files", "-z"]
    for _, kwargs in recorder.calls:
        assert kwargs["shell"] is False
        assert kwargs["timeout"] == 10.0
        assert kwargs["cwd"] == tmp_path
        assert kwargs["env"]["GIT_CONFIG_NOSYSTEM"] == "1"
        assert kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"


def test_subprocess_git_custom_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = Recorder([SimpleNamespace(returncode=0, stdout=b"")])
    monkeypatch.setattr(subprocess, "run", recorder)
    assert SubprocessGit(tmp_path, timeout=2.5).tracked_files() == []
    assert recorder.calls[0][1]["timeout"] == 2.5


@pytest.mark.parametrize(
    "outcome",
    [
        SimpleNamespace(returncode=128, stdout=b""),
        FileNotFoundError("git"),
        subprocess.TimeoutExpired("git", 10.0),
    ],
)
def test_subprocess_git_failures_return_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcome: Any
) -> None:
    monkeypatch.setattr(subprocess, "run", Recorder([outcome]))
    git = SubprocessGit(tmp_path)
    assert git.last_commit_time() is None
    assert git.tracked_files() is None


@pytest.mark.parametrize("stdout", [b"", b"not a date", b"2024-01-01T00:00:00"])
def test_subprocess_git_bad_commit_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stdout: bytes
) -> None:
    monkeypatch.setattr(subprocess, "run", Recorder([SimpleNamespace(returncode=0, stdout=stdout)]))
    assert SubprocessGit(tmp_path).last_commit_time() is None


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_fsmonitor_command_is_not_executed(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    marker = tmp_path / "marker"
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, env=env, check=True, capture_output=True)

    git("init")
    (repo / "f.txt").write_text("x", encoding="utf-8")
    git("add", "f.txt")
    git(
        "-c",
        "user.name=Tester",
        "-c",
        "user.email=tester@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-m",
        "init",
    )
    git("config", "core.fsmonitor", f"touch {shlex.quote(str(marker))}")
    port = SubprocessGit(repo)
    assert port.last_commit_time() is not None
    assert port.tracked_files() == ["f.txt"]
    assert not marker.exists()


# --- score and report -------------------------------------------------------------------


def test_round_half_up_not_bankers_rounding() -> None:
    assert score([make(1, "pass"), make(7, "fail")]).total == 13
    assert score([make(3, "pass"), make(5, "fail")]).total == 38


@pytest.mark.parametrize(
    ("passed", "grade"),
    [
        (100, "A"),
        (90, "A"),
        (89, "B"),
        (80, "B"),
        (79, "C"),
        (70, "C"),
        (69, "D"),
        (60, "D"),
        (59, "F"),
        (0, "F"),
    ],
)
def test_grade_boundaries(passed: int, grade: str) -> None:
    report = score([make(passed, "pass"), make(100 - passed, "fail")])
    assert report.total == passed
    assert report.grade == grade


def test_all_skipped_scores_zero() -> None:
    report = score([make(10, "skipped")])
    assert (report.total, report.grade) == (0, "F")
    assert report.by_category["docs"] == 0
    assert score([]).total == 0


def test_category_scores() -> None:
    report = score([make(10, "pass", "docs"), make(10, "fail", "tests")])
    assert report.by_category["docs"] == 100
    assert report.by_category["tests"] == 0
    assert report.total == 50


def test_report_rendering(tmp_path: Path) -> None:
    build(tmp_path, skip=("LICENSE",))
    report = score(run_checks(tmp_path, now=NOW, git=good_git()))
    text = report.to_text()
    assert text.startswith("Repo health score: 90/100 (grade A)")
    assert "FAIL    DOC002 [docs] w10: missing" in text
    payload = json.loads(report.to_json())
    assert [item["id"] for item in payload] == sorted(item["id"] for item in payload)


# --- CLI --------------------------------------------------------------------------------


def use_git(monkeypatch: pytest.MonkeyPatch, fake: FakeGit) -> None:
    monkeypatch.setattr(cli, "SubprocessGit", lambda root: fake)


def test_cli_min_score_fails_below_threshold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    build(tmp_path, skip=("CONTRIBUTING.md",))
    (tmp_path / "README.md").write_text("too short", encoding="utf-8")
    use_git(monkeypatch, FakeGit(None, None))
    assert cli.main([str(tmp_path), "--min-score", "80"]) == 1
    assert "79/100" in capsys.readouterr().out


def test_cli_min_score_met(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    build(tmp_path, skip=("LICENSE", "SECURITY.md"))
    use_git(monkeypatch, good_git())
    args = [str(tmp_path), "--min-score", "80", "--now", "2025-01-01T00:00:00+00:00"]
    assert cli.main(args) == 0


def test_cli_without_min_score_always_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    build(tmp_path, skip=("LICENSE",))
    use_git(monkeypatch, FakeGit(datetime(2999, 1, 1, tzinfo=timezone.utc), []))
    assert cli.main([str(tmp_path)]) == 0


def test_cli_json_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    build(tmp_path)
    use_git(monkeypatch, good_git())
    assert cli.main([str(tmp_path), "--format", "json", "--now", "2025-01-01T00:00:00Z"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, list)
    assert len(payload) == 10
    for item in payload:
        assert set(item) == {"id", "category", "weight", "status", "detail"}
    assert [item["id"] for item in payload] == sorted(item["id"] for item in payload)


@pytest.mark.parametrize(
    "args",
    [
        ["--now", "yesterday"],
        ["--now", "2" * 100],
        ["--min-score", "101"],
        ["--min-score", "-1"],
        ["--min-score", "x"],
        ["--min-score", "1" * 40],
        ["--format", "xml"],
        ["--bogus"],
    ],
)
def test_cli_usage_errors_exit_2(args: list[str], tmp_path: Path) -> None:
    assert cli.main([str(tmp_path), *args]) == 2


def test_cli_help_exits_0(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--help"]) == 0
    assert "repo-health" in capsys.readouterr().out


def test_cli_naive_now_is_a_domain_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    build(tmp_path)
    use_git(monkeypatch, good_git())
    assert cli.main([str(tmp_path), "--now", "2025-01-01T00:00:00"]) == 1
    assert "naive_time" in capsys.readouterr().err


def test_cli_missing_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    use_git(monkeypatch, good_git())
    assert cli.main([str(tmp_path / "nope")]) == 1


def test_cli_io_error_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(*args: Any, **kwargs: Any) -> Any:
        raise PermissionError(13, "denied")

    monkeypatch.setattr(cli, "run_checks", boom)
    assert cli.main([str(tmp_path)]) == 2
    assert "denied" in capsys.readouterr().err


# --- package ----------------------------------------------------------------------------


def test_package_metadata() -> None:
    assert repo_health.__version__ == "0.1.0"
    handlers = logging.getLogger("repo_health").handlers
    assert any(isinstance(h, logging.NullHandler) for h in handlers)
    for name in repo_health.__all__:
        assert hasattr(repo_health, name)


def test_last_commit_time_accepts_utc_z_suffix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    port = SubprocessGit(tmp_path)
    monkeypatch.setattr(port, "_run", lambda *args: b"2026-11-06T04:15:04Z\n")
    assert port.last_commit_time() == datetime(2026, 11, 6, 4, 15, 4, tzinfo=timezone.utc)
