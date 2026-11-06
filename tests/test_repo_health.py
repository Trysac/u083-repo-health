"""Behavior tests for the public API of repo_health."""

from __future__ import annotations

import pytest

import repo_health


def test_normalize_trims_and_lowercases() -> None:
    assert repo_health.normalize("  Hello World ") == "hello world"


@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
def test_normalize_rejects_blank_input(value: str) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        repo_health.normalize(value)


def test_version_is_semver() -> None:
    parts = repo_health.__version__.split(".")
    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)
