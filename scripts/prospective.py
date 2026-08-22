"""Replacement-workflow contract for Prospective and Ambispective Protocols.

The model-facing drafting boundary is deliberately small: batches identify the
section IDs and approved input families a drafting task may receive.  Python
keeps ownership of contract order, structural validation, and atomic delivery.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Iterable, Mapping

from retrospective import SectionContract, SectionDraft, RetryLedger, reuse_accepted_drafts, verify_rendered_pages


PROSPECTIVE_SECTIONS: tuple[SectionContract, ...] = (
    SectionContract("title-page", "1.", "TITLE PAGE", "container"),
    SectionContract("investigator-agreement", "2.", "INVESTIGATOR AGREEMENT", "container"),
    SectionContract("general-information", "3.", "GENERAL INFORMATION", "container"),
    SectionContract("table-of-contents", "4.", "TABLE OF CONTENTS", "container"),
    SectionContract("introduction", "5.", "INTRODUCTION"),
    SectionContract("objectives", "6.", "OBJECTIVE(S)"),
    SectionContract("subjects", "7.", "SUBJECTS", "container"),
    SectionContract("subjects.population", "7.1.", "Subject Population"),
    SectionContract("subjects.inclusion", "7.2.", "Inclusion Criteria"),
    SectionContract("subjects.exclusion", "7.3.", "Exclusion Criteria"),
    SectionContract("study-design", "8.", "STUDY DESIGN", "container"),
    SectionContract("study-design.design", "8.1.", "Study Design"),
    SectionContract("study-design.bias", "8.2.", "Methods Used to Minimize Bias"),
    SectionContract("study-procedure", "9.", "STUDY PROCEDURE", "container"),
    SectionContract("study-procedure.consent", "9.1.", "Informed Consent / Subject Enrollment"),
    SectionContract("study-procedure.visits", "9.2.", "Visits and Examinations"),
    SectionContract("study-procedure.measurements", "9.3.", "Study Methods and Measurements"),
    SectionContract("study-procedure.unscheduled", "9.4.", "Unscheduled Visits"),
    SectionContract("study-procedure.discontinued", "9.5.", "Discontinued Subjects"),
    SectionContract("analysis-plan", "10.", "ANALYSIS PLAN", "container"),
    SectionContract("analysis-plan.datasets", "10.1.", "Analysis Data Sets"),
    SectionContract("analysis-plan.methodology", "10.2.", "Statistical Methodology"),
    SectionContract("analysis-plan.considerations", "10.3.", "General Statistical Considerations"),
    SectionContract("sample-size", "11.", "SAMPLE SIZE JUSTIFICATION"),
    SectionContract("confidentiality-publication", "12.", "CONFIDENTIALITY/PUBLICATION OF THE STUDY"),
    SectionContract("quality-safety", "13.", "QUALITY COMPLAINTS AND ADVERSE EVENTS", "container"),
    SectionContract("quality-safety.general", "13.1.", "General Information"),
    SectionContract("quality-safety.monitoring", "13.2.", "Monitoring for Adverse Events"),
    SectionContract("quality-safety.reporting", "13.3.", "Procedures for Recording and Reporting AEs and SAEs"),
    SectionContract("quality-safety.follow-up", "13.4.", "Follow-Up of Adverse Events and Quality Complaints"),
    SectionContract("quality-safety.analysis", "13.5.", "Safety Analyses"),
    SectionContract("ethics", "14.", "GCP, ICH AND ETHICAL CONSIDERATIONS", "container"),
    SectionContract("ethics.confidentiality", "14.1.", "Confidentiality"),
    SectionContract("evaluation-procedures", "15.", "STANDARD EVALUATION PROCEDURES"),
    SectionContract("confidentiality", "16.", "CONFIDENTIALITY"),
    SectionContract("financial-injury", "17.", "FINANCIAL AND INSURANCE INFORMATION/STUDY RELATED INJURIES"),
    SectionContract("endpoint-criteria", "18.", "STUDY ENDPOINT CRITERIA", "container"),
    SectionContract("endpoint-criteria.completion", "18.1.", "Patient Completion of Study"),
    SectionContract("endpoint-criteria.discontinuation", "18.2.", "Patient Discontinuation"),
    SectionContract("endpoint-criteria.termination", "18.3.", "Patient Termination"),
    SectionContract("endpoint-criteria.study-termination", "18.4.", "Study Termination"),
    SectionContract("endpoint-criteria.study-completion", "18.5.", "Study Completion"),
    SectionContract("risks-benefits", "19.", "SUMMARY OF RISKS AND BENEFITS", "container"),
    SectionContract("risks-benefits.risks", "19.1.", "Summary of risks"),
    SectionContract("risks-benefits.benefits", "19.2.", "Summary of benefits"),
)


@dataclass(frozen=True)
class ProspectiveDraftingBatch:
    batch_id: str
    section_ids: tuple[str, ...]
    approved_field_families: tuple[str, ...]
    prerequisite_ids: tuple[str, ...] = ()


PRS_NARRATIVE_FIELDS = ("brief_summary", "detailed_description")


def prospective_contract() -> tuple[SectionContract, ...]:
    return PROSPECTIVE_SECTIONS


def prospective_batch_plan() -> tuple[ProspectiveDraftingBatch, ...]:
    return (
        ProspectiveDraftingBatch(
            "protocol-foundations",
            ("introduction", "objectives", "subjects", "study-design"),
            ("study", "objectives", "population", "design", "endpoints"),
        ),
        ProspectiveDraftingBatch(
            "protocol-operations",
            ("study-procedure", "evaluation-procedures"),
            ("procedures", "population", "design", "endpoints", "safety"),
            ("protocol-foundations",),
        ),
        ProspectiveDraftingBatch(
            "protocol-analysis-and-oversight",
            ("analysis-plan", "sample-size", "confidentiality-publication", "quality-safety", "ethics", "confidentiality", "financial-injury", "endpoint-criteria", "risks-benefits"),
            ("statistics", "safety", "ethics", "confidentiality", "risks_benefits", "endpoints", "procedures", "population"),
            ("protocol-foundations", "protocol-operations"),
        ),
        ProspectiveDraftingBatch(
            "prs-narrative",
            ("prs-narrative",),
            ("study", "objectives", "design", "endpoints", "generated"),
            ("protocol-foundations",),
        ),
        _icf_batch(),
    )


def _icf_batch(study_type: str = "Prospective", template: str = "Advarra") -> ProspectiveDraftingBatch:
    """Return the one unified participant-facing ICF drafting batch."""
    from icf import unified_icf_batch

    return unified_icf_batch(study_type, template)


def branch_batch_plan(study_type: str = "Prospective", template: str = "Advarra") -> tuple[ProspectiveDraftingBatch, ...]:
    """Return the drafting topology with the selected branch ICF contract."""
    batches = list(prospective_batch_plan())
    batches[-1] = _icf_batch(study_type, template)
    return tuple(batches)


def scoped_batch_input(
    reference: Mapping[str, object], batch: ProspectiveDraftingBatch | str
) -> dict[str, object]:
    """Return a defensive, batch-scoped view of approved reference fields.

    A drafting task receives only the approved top-level families assigned to
    its batch; generated projections and unrelated branch data are excluded.
    """
    selected = batch
    if isinstance(batch, str):
        selected = next((item for item in prospective_batch_plan() if item.batch_id == batch), None)
    if selected is None or not isinstance(selected, ProspectiveDraftingBatch):
        raise ValueError(f"Unknown Prospective drafting batch: {batch}")
    scoped = {
        family: copy.deepcopy(reference[family])
        for family in selected.approved_field_families
        if family in reference
    }
    if selected.batch_id == "prs-narrative":
        # The narrative task receives source facts and accepted foundations,
        # never XML templates, field maps, or a choice of XML taxonomy.
        generated = scoped.get("generated")
        if isinstance(generated, dict):
            scoped["generated"] = {"protocol": copy.deepcopy(generated.get("protocol", {}))}
    return scoped


def validate_prs_narrative(draft: Mapping[str, object]) -> dict[str, str]:
    """Accept only the two prose values the PRS batch is allowed to draft."""
    if not isinstance(draft, Mapping):
        raise ValueError("PRS narrative draft must be a mapping")
    accepted: dict[str, str] = {}
    for field in PRS_NARRATIVE_FIELDS:
        value = draft.get(field, "")
        if value is None:
            value = ""
        if not isinstance(value, str):
            raise ValueError(f"PRS narrative field {field} must be text")
        if re.search(r"</?[A-Za-z_][^>]*>", value):
            raise ValueError("PRS narrative batch must not emit XML markup")
        accepted[field] = value.strip()
    return accepted


def merge_prospective_drafts(drafts: Iterable[SectionDraft]) -> tuple[SectionDraft, ...]:
    known = {item.section_id for item in PROSPECTIVE_SECTIONS}
    by_id: dict[str, SectionDraft] = {}
    for draft in drafts:
        if draft.section_id not in known:
            raise ValueError(f"Unknown Prospective section ID: {draft.section_id}")
        if draft.accepted and draft.section_id in by_id:
            raise ValueError(f"Duplicate accepted Section Draft: {draft.section_id}")
        if draft.accepted:
            by_id[draft.section_id] = draft
    return tuple(by_id[item.section_id] for item in PROSPECTIVE_SECTIONS if item.section_id in by_id)


def verify_prospective_sections(drafts: Iterable[SectionDraft]) -> list[dict[str, str]]:
    values = {draft.section_id: draft.content.strip() for draft in drafts if draft.accepted}
    findings: list[dict[str, str]] = []
    for section in PROSPECTIVE_SECTIONS:
        if section.role == "container":
            continue
        content = values.get(section.section_id, "")
        if not content:
            findings.append({"section_id": section.section_id, "category": "drafting", "issue": "Required leaf section is not substantive."})
        elif any(token in content.casefold() for token in ("{", "todo", "tbd", "needs review", "internal only")):
            findings.append({"section_id": section.section_id, "category": "drafting", "issue": "Section contains an unresolved placeholder or internal drafting language."})
    return findings


__all__ = [
    "PROSPECTIVE_SECTIONS", "ProspectiveDraftingBatch", "prospective_contract",
    "prospective_batch_plan", "branch_batch_plan", "scoped_batch_input", "validate_prs_narrative", "PRS_NARRATIVE_FIELDS", "merge_prospective_drafts", "verify_prospective_sections",
    "RetryLedger", "reuse_accepted_drafts", "verify_rendered_pages",
]
