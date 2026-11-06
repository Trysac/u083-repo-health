"""Scoring and rendering of check results."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from repo_health.checks import Category, CheckResult

Grade = Literal["A", "B", "C", "D", "F"]

_CATEGORIES: tuple[Category, ...] = ("docs", "tests", "ci", "security", "maintenance")


def _percent(results: Sequence[CheckResult]) -> int:
    """Weighted percentage of passed checks, rounded half up; skipped checks are ignored."""
    possible = sum(item.weight for item in results if item.status != "skipped")
    if possible == 0:
        return 0
    passed = sum(item.weight for item in results if item.status == "pass")
    return (200 * passed + possible) // (2 * possible)


def _grade(total: int) -> Grade:
    if total >= 90:
        return "A"
    if total >= 80:
        return "B"
    if total >= 70:
        return "C"
    if total >= 60:
        return "D"
    return "F"


@dataclass(frozen=True)
class HealthReport:
    """Aggregated score of a set of check results."""

    total: int
    by_category: dict[str, int]
    grade: Grade
    results: tuple[CheckResult, ...]

    def to_text(self) -> str:
        """Render a human-readable report."""
        lines = [f"Repo health score: {self.total}/100 (grade {self.grade})"]
        lines.append("Categories: " + ", ".join(f"{k} {v}" for k, v in self.by_category.items()))
        for item in sorted(self.results, key=lambda r: r.id):
            status = item.status.upper()
            lines.append(f"{status:7} {item.id} [{item.category}] w{item.weight}: {item.detail}")
        return "\n".join(lines)

    def to_json(self) -> str:
        """Render the results as a JSON list of objects, sorted by id."""
        payload = [
            {
                "id": item.id,
                "category": item.category,
                "weight": item.weight,
                "status": item.status,
                "detail": item.detail,
            }
            for item in sorted(self.results, key=lambda r: r.id)
        ]
        return json.dumps(payload, indent=2)


def score(results: Sequence[CheckResult]) -> HealthReport:
    """Compute the total, per-category scores and grade for ``results``.

    With ``p`` passed weight and ``w`` non-skipped weight, ``total = (200 * p + w) // (2 * w)``
    (round half up). When everything is skipped the total is 0.
    """
    total = _percent(results)
    by_category: dict[str, int] = {
        category: _percent([item for item in results if item.category == category])
        for category in _CATEGORIES
    }
    return HealthReport(total, by_category, _grade(total), tuple(results))
