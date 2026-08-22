"""Deterministic replacement-workflow seam for Retrospective Protocols.

Hermes can use these small value objects to draft and retry sections, while
Python remains authoritative for contract order, verification, and delivery.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class SectionContract:
    section_id: str
    number: str
    title: str
    role: str = "leaf"
    required: bool = True


RETROSPECTIVE_SECTIONS: tuple[SectionContract, ...] = (
    SectionContract("title-page", "1.", "TITLE PAGE", "container"),
    SectionContract("investigator-agreement", "2.", "INVESTIGATOR AGREEMENT", "container"),
    SectionContract("table-of-contents", "3.", "TABLE OF CONTENTS", "container"),
    SectionContract("introduction", "4.", "INTRODUCTION"),
    SectionContract("objectives", "5.", "OBJECTIVE(S)"),
    SectionContract("subjects", "6.", "SUBJECTS", "container"),
    SectionContract("subjects.population", "6.1.", "Subject Population"),
    SectionContract("subjects.eligibility", "6.2.", "Inclusion/Exclusion Criteria"),
    SectionContract("study-design", "7.", "STUDY DESIGN", "container"),
    SectionContract("study-design.design", "7.1.", "Study Design"),
    SectionContract("study-design.bias", "7.2.", "Methods Used to Minimize Bias"),
    SectionContract("study-procedure", "8.", "STUDY PROCEDURE", "container"),
    SectionContract("study-procedure.enrollment", "8.1.", "Informed Consent / Subject enrollment"),
    SectionContract("analysis-plan", "9.", "ANALYSIS PLAN", "container"),
    SectionContract("analysis-plan.datasets", "9.1.", "Analysis Data Sets"),
    SectionContract("analysis-plan.methodology", "9.2.", "Statistical Methodology"),
    SectionContract("analysis-plan.considerations", "9.3.", "General Statistical Considerations"),
    SectionContract("sample-size", "10.", "SAMPLE SIZE JUSTIFICATION"),
    SectionContract("confidentiality", "11.", "CONFIDENTIALITY/PUBLICATION OF THE STUDY"),
    SectionContract("quality-safety", "12.", "QUALITY COMPLAINTS AND ADVERSE EVENTS"),
    SectionContract("ethics", "13.", "GCP, ICH and ETHICAL CONSIDERATIONS"),
)

RETROSPECTIVE_TOP_LEVEL_IDS = tuple(item.section_id for item in RETROSPECTIVE_SECTIONS if "." not in item.section_id)


def retrospective_contract() -> tuple[SectionContract, ...]:
    """Return the immutable bundled Retrospective hierarchy in document order."""
    return RETROSPECTIVE_SECTIONS


def retrospective_batch_plan() -> tuple[dict[str, Any], ...]:
    """Return exactly the three Protocol drafting batches for this branch."""
    return (
        {"batch_id": "protocol-foundations", "section_ids": ("introduction", "objectives", "subjects", "study-design")},
        {"batch_id": "protocol-operations", "section_ids": ("study-procedure",)},
        {"batch_id": "protocol-analysis-and-oversight", "section_ids": ("analysis-plan", "sample-size", "confidentiality", "quality-safety", "ethics")},
    )


@dataclass(frozen=True)
class SectionDraft:
    section_id: str
    content: str = ""
    attempt: int = 1
    batch_id: str = ""
    accepted: bool = True


def merge_section_drafts(drafts: Iterable[SectionDraft]) -> tuple[SectionDraft, ...]:
    """Merge by stable ID and return accepted drafts in contract order."""
    by_id: dict[str, SectionDraft] = {}
    known = {item.section_id for item in RETROSPECTIVE_SECTIONS}
    for draft in drafts:
        if draft.section_id not in known:
            raise ValueError(f"Unknown Retrospective section ID: {draft.section_id}")
        if draft.section_id in by_id and by_id[draft.section_id].accepted and draft.accepted:
            raise ValueError(f"Duplicate accepted Section Draft: {draft.section_id}")
        if draft.accepted:
            by_id[draft.section_id] = draft
    return tuple(by_id[item.section_id] for item in RETROSPECTIVE_SECTIONS if item.section_id in by_id)


def reuse_accepted_drafts(
    drafts: Iterable[SectionDraft], failed_section_ids: Iterable[str]
) -> tuple[SectionDraft, ...]:
    """Keep accepted drafts outside the failed target set for a targeted retry."""
    failed = set(failed_section_ids)
    return tuple(draft for draft in drafts if draft.accepted and draft.section_id not in failed)


def verify_retrospective_sections(drafts: Iterable[SectionDraft]) -> list[dict[str, str]]:
    """Read-only content verifier; findings identify exact stable section IDs."""
    values = {draft.section_id: draft.content.strip() for draft in drafts if draft.accepted}
    findings: list[dict[str, str]] = []
    for section in RETROSPECTIVE_SECTIONS:
        if section.role == "container":
            continue
        if not values.get(section.section_id):
            findings.append({"section_id": section.section_id, "category": "drafting", "issue": "Required leaf section is not substantive."})
        elif any(token in values[section.section_id].casefold() for token in ("{", "todo", "tbd", "needs review")):
            findings.append({"section_id": section.section_id, "category": "drafting", "issue": "Section contains an unresolved placeholder or internal drafting language."})
    return findings


@dataclass
class RetryLedger:
    """Bounded target attempts; the initial draft counts as attempt one."""

    max_attempts: int = 3
    attempts: dict[str, int] = field(default_factory=dict)

    def record(self, target: str) -> int:
        next_attempt = self.attempts.get(target, 0) + 1
        if next_attempt > self.max_attempts:
            raise ValueError(f"Retry limit exhausted for {target}")
        self.attempts[target] = next_attempt
        return next_attempt

    def can_attempt(self, target: str) -> bool:
        return self.attempts.get(target, 0) < self.max_attempts

    def retry_targets(self, targets: Iterable[str]) -> tuple[str, ...]:
        """Return only failed targets still eligible for another attempt."""
        return tuple(target for target in targets if self.can_attempt(target))


def verify_rendered_pages(pages: Mapping[int, str]) -> list[dict[str, Any]]:
    """Read-only visual-verifier adapter for rendered page evidence."""
    findings: list[dict[str, Any]] = []
    for page, evidence in pages.items():
        if not str(evidence).strip():
            findings.append({"artifact": "protocol.docx", "page": page, "category": "visual", "issue": "Rendered page has no inspection evidence."})
    return findings


__all__ = ["SectionContract", "SectionDraft", "RetryLedger", "RETROSPECTIVE_SECTIONS", "retrospective_contract", "retrospective_batch_plan", "merge_section_drafts", "reuse_accepted_drafts", "verify_retrospective_sections", "verify_rendered_pages"]
