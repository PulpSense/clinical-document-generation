"""Versioned acceptance-corpus inventory and normal-run budgets.

The corpus inventory is deliberately data-only.  The public workflow tests
materialize each record with approved source fixtures, while this module owns
the matrix that must be rerun when a branch contract or contracted template
changes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


_CORPUS_PATH = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "branch-acceptance-corpus.json"


@dataclass(frozen=True)
class AcceptanceFixture:
    fixture_id: str
    study_type: str
    profile: str
    path: str
    regression: bool = False

    @property
    def key(self) -> tuple[str, str]:
        """Stable identity used to prevent accidental fixture duplication."""
        return self.study_type, self.profile


def _load_corpus() -> tuple[AcceptanceFixture, ...]:
    records = json.loads(_CORPUS_PATH.read_text(encoding="utf-8"))
    return tuple(AcceptanceFixture(**record) for record in records)


ACCEPTANCE_CORPUS = _load_corpus()

# None means that the branch has no ICF template choice.
BRANCH_TEMPLATE_MATRIX = (
    ("Prospective", "Advarra"),
    ("Prospective", "Sterling"),
    ("Ambispective", "Advarra"),
    ("Ambispective", "Sterling"),
    ("Retrospective", None),
)


def drafting_task_budget(study_type: str) -> int:
    """Return the normal first-wave drafting task budget for a branch."""
    if study_type in {"Prospective", "Ambispective"}:
        return 5
    if study_type == "Retrospective":
        return 3
    raise ValueError(f"Unsupported study type: {study_type}")


def verification_task_budget(study_type: str) -> int:
    """Return the normal read-only verifier task budget for a branch."""
    if study_type in {"Prospective", "Ambispective", "Retrospective"}:
        return 2
    raise ValueError(f"Unsupported study type: {study_type}")


def canonical_fixtures() -> tuple[AcceptanceFixture, ...]:
    """Return exactly the six runnable sparse/rich certification fixtures."""
    profiles = {"sparse-complete", "rich-complete"}
    fixtures = tuple(fixture for fixture in ACCEPTANCE_CORPUS if fixture.profile in profiles)
    if len(fixtures) != 6 or {fixture.key for fixture in fixtures} != {
        (branch, profile)
        for branch in ("Prospective", "Ambispective", "Retrospective")
        for profile in profiles
    }:
        raise ValueError("Acceptance corpus must contain sparse and rich fixtures for every branch.")
    return fixtures


def contracted_template_cases() -> tuple[tuple[str, str | None], ...]:
    """Return the public branch/template cases, including Retrospective."""
    return BRANCH_TEMPLATE_MATRIX


__all__ = [
    "ACCEPTANCE_CORPUS",
    "AcceptanceFixture",
    "BRANCH_TEMPLATE_MATRIX",
    "drafting_task_budget",
    "verification_task_budget",
    "canonical_fixtures",
    "contracted_template_cases",
]
