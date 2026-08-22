"""Executable certification seams for the Branch Acceptance Corpus.

The runner deliberately depends on the four public workflow operations rather
than importing implementation stages.  A small callable injection point makes
the inventory and orchestration contract testable without requiring an office
renderer or model calls in unit tests.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from acceptance_corpus import (
    AcceptanceFixture,
    canonical_fixtures,
    contracted_template_cases,
    drafting_task_budget,
    verification_task_budget,
)


WorkflowCase = Callable[[AcceptanceFixture, Optional[str]], dict[str, Any]]


@dataclass
class CertificationResult:
    """Aggregated, machine-readable result for one corpus certification."""

    status: str
    elapsed_seconds: float
    cases: list[dict[str, Any]] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.status == "passed"


def _case_matrix() -> list[tuple[AcceptanceFixture, str | None]]:
    cases: list[tuple[AcceptanceFixture, str | None]] = []
    for study_type, template in contracted_template_cases():
        for profile in ("sparse-complete", "rich-complete"):
            fixture = next(
                item
                for item in canonical_fixtures()
                if item.study_type == study_type and item.profile == profile
            )
            cases.append((fixture, template))
    return cases


def certify_corpus(run_case: WorkflowCase) -> CertificationResult:
    """Run every sparse/rich fixture through every contracted public case.

    ``run_case`` owns temporary-run setup and calls ``prepare``, ``approve``,
    ``validate``, and ``generate``.  The runner checks only observable contract
    results, keeping this certification independent of implementation details.
    """
    started = time.perf_counter()
    failures: list[str] = []
    cases: list[dict[str, Any]] = []
    for fixture, template in _case_matrix():
        label = f"{fixture.fixture_id}:{template or 'none'}"
        try:
            result = run_case(fixture, template)
        except Exception as exc:  # certification must report all cases
            failures.append(f"{label}: raised {type(exc).__name__}: {exc}")
            cases.append({"case": label, "status": "failed", "error": str(exc)})
            continue
        status = result.get("status") if isinstance(result, dict) else None
        if status != "passed":
            failures.append(f"{label}: expected passed, got {status!r}")
        if isinstance(result, dict):
            failures.extend(f"{label}: {failure}" for failure in assert_task_budget(fixture.study_type, result))
        cases.append({"case": label, **(result if isinstance(result, dict) else {"status": status})})
    elapsed = round(time.perf_counter() - started, 3)
    if elapsed >= 600:
        failures.append(f"corpus exceeded ten-minute target: {elapsed}s")
    return CertificationResult("passed" if not failures else "failed", elapsed, cases, failures)


def assert_task_budget(study_type: str, result: dict[str, Any]) -> list[str]:
    """Return budget violations from a public workflow result."""
    workflow = result.get("replacement_workflow") or {}
    failures: list[str] = []
    if len(workflow.get("drafting_batches", [])) != drafting_task_budget(study_type):
        failures.append(f"{study_type}: drafting task budget mismatch")
    if len(workflow.get("verification_tasks", [])) != verification_task_budget(study_type):
        failures.append(f"{study_type}: verification task budget mismatch")
    return failures


__all__ = ["CertificationResult", "assert_task_budget", "certify_corpus"]
