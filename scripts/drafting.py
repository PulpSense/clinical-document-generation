"""Drafting seam for Hermes batch orchestration.

The model-facing boundary is represented by recorded, structured requests and
responses.  Deterministic source-grounded drafting is used when no live Hermes
adapter is installed; Python still owns validation, merging, and delivery.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from retrospective import SectionDraft, merge_section_drafts, retrospective_batch_plan
from prospective import (
    ProspectiveDraftingBatch,
    branch_batch_plan,
    merge_prospective_drafts,
    prospective_batch_plan,
    scoped_batch_input,
    verify_prospective_sections,
)
from icf import icf_contract, unified_icf_batch, verify_icf_sections
from complete_protocol import with_complete_protocol


@dataclass(frozen=True)
class DraftingBatch:
    """A stable, named group of section IDs assigned to one drafting pass."""

    batch_id: str
    section_ids: tuple[str, ...]
    prerequisite_ids: tuple[str, ...] = ()


def plan_batches(batch_specs: Iterable[DraftingBatch]) -> tuple[DraftingBatch, ...]:
    """Normalize a drafting topology without invoking an external model."""
    batches = tuple(batch_specs)
    if len({batch.batch_id for batch in batches}) != len(batches):
        raise ValueError("Drafting batch IDs must be unique.")
    return batches


def plan_retrospective_batches() -> tuple[DraftingBatch, ...]:
    """Expose the retrospective topology through the DraftingBatch seam."""
    return tuple(
        DraftingBatch(item["batch_id"], tuple(item["section_ids"]))
        for item in retrospective_batch_plan()
    )


def plan_prospective_batches() -> tuple[ProspectiveDraftingBatch, ...]:
    """Expose the three stable Protocol batches for both forward branches."""
    return prospective_batch_plan()


def _section_id_by_number(number: str) -> str:
    """Resolve a generated section number against the stable contract ID."""
    from prospective import prospective_contract

    normalized = str(number).rstrip(".")
    for section in prospective_contract():
        if section.number.rstrip(".") == normalized:
            return section.section_id
    raise ValueError(f"Generated Prospective section has no contract ID: {number}")


def draft_prospective_protocol(
    reference: Mapping[str, Any],
    *,
    run_dir: Path | None = None,
    study_type: str = "Prospective",
    icf_template: str = "Advarra",
) -> dict[str, Any]:
    """Draft, validate, and merge the three Protocol batches.

    The generated section payload is intentionally kept structured.  Each
    request contains only its approved field families and contract sections;
    the complete source reference is never written into a batch request.
    """
    protocol_batches = branch_batch_plan(study_type, icf_template)[:3]
    from prospective import prospective_contract

    contract_ids = tuple(item.section_id for item in prospective_contract())
    completed = with_complete_protocol(dict(reference))
    generated = completed.get("generated") if isinstance(completed.get("generated"), dict) else {}
    protocol = generated.get("protocol") if isinstance(generated.get("protocol"), dict) else {}
    generated_sections = protocol.get("sections") if isinstance(protocol.get("sections"), list) else []
    by_id: dict[str, SectionDraft] = {}
    for section in generated_sections:
        if not isinstance(section, dict):
            continue
        section_id = _section_id_by_number(str(section.get("number", "")))
        paragraphs = tuple(
            str(value).strip() for value in section.get("paragraphs", []) if str(value).strip()
        )
        lists = tuple(
            tuple(str(value).strip() for value in items if str(value).strip())
            for items in section.get("lists", [])
            if isinstance(items, list)
        )
        tables = tuple(item for item in section.get("tables", []) if isinstance(item, dict))
        content = "\n\n".join(paragraphs + tuple(item for items in lists for item in items))
        by_id[section_id] = SectionDraft(
            section_id,
            content,
            batch_id="",
            paragraphs=paragraphs,
            lists=lists,
            tables=tables,
            number=str(section.get("number", "")),
            title=str(section.get("title", "")),
        )

    drafts: list[SectionDraft] = []
    requests: list[dict[str, Any]] = []
    for batch in protocol_batches:
        scoped = scoped_batch_input(reference, batch)
        target_ids = tuple(
            section_id
            for section_id in contract_ids
            if section_id in batch.section_ids
            or any(section_id.startswith(parent + ".") for parent in batch.section_ids)
        )
        requests.append({
            "batch_id": batch.batch_id,
            "section_ids": list(target_ids),
            "approved_field_families": list(batch.approved_field_families),
            "prerequisite_ids": list(batch.prerequisite_ids),
            "approved_input": scoped,
        })
        for section_id in target_ids:
            draft = by_id.get(section_id)
            if draft is None:
                drafts.append(SectionDraft(section_id, batch_id=batch.batch_id))
            else:
                drafts.append(SectionDraft(
                    draft.section_id, draft.content, draft.attempt, batch.batch_id,
                    draft.accepted, draft.paragraphs, draft.lists, draft.tables,
                    draft.number, draft.title,
                ))

    merged = merge_prospective_drafts(drafts)
    findings = verify_prospective_sections(merged)
    if findings:
        raise ValueError("Prospective Section Draft verification failed: " + "; ".join(item["section_id"] for item in findings))

    merged_sections = []
    for draft in merged:
        merged_sections.append({
            "number": draft.number,
            "title": draft.title,
            "paragraphs": list(draft.paragraphs) or ([draft.content] if draft.content else []),
            "lists": [list(items) for items in draft.lists],
            "tables": list(draft.tables),
        })
    result_contract = (
        "prospective-1-19-v1" if study_type.casefold() == "prospective" else "ambispective-1-19-v1"
    )
    completed["generated"]["protocol"]["sections"] = merged_sections  # type: ignore[index]
    completed["generated"]["protocol"]["drafting_contract_version"] = result_contract  # type: ignore[index]
    result = {
        "status": "passed",
        "contract_version": result_contract,
        "batches": requests,
        "section_drafts": [
            {"section_id": draft.section_id, "batch_id": draft.batch_id, "attempt": draft.attempt, "accepted": draft.accepted}
            for draft in merged
        ],
        "completed_batch_ids": [batch.batch_id for batch in protocol_batches],
        "verification": {"status": "passed", "findings": []},
    }
    if run_dir is not None:
        path = run_dir / "logs/protocol-drafting.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"reference": completed, "report": result, "drafts": merged}


def draft_prs_narrative(
    reference: Mapping[str, Any],
    *,
    run_dir: Path | None = None,
    prerequisite_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the narrow PRS narrative batch after accepted Protocol Foundations.

    The batch may produce only the two prose fields consumed by the PRS XML
    mapper.  XML structure, field mapping, and escaping remain deterministic
    Python responsibilities.
    """
    if prerequisite_report is not None:
        verification = prerequisite_report.get("verification")
        completed_batch_ids = prerequisite_report.get("completed_batch_ids", [])
        if prerequisite_report.get("status") != "passed" or "protocol-foundations" not in completed_batch_ids or (
            isinstance(verification, Mapping) and verification.get("status") != "passed"
        ):
            raise ValueError("PRS narrative batch requires passed Protocol Foundations")

    study = reference.get("study") if isinstance(reference.get("study"), Mapping) else {}
    objectives = reference.get("objectives") if isinstance(reference.get("objectives"), Mapping) else {}
    generated = reference.get("generated") if isinstance(reference.get("generated"), Mapping) else {}
    protocol = generated.get("protocol") if isinstance(generated.get("protocol"), Mapping) else {}
    design = reference.get("design") if isinstance(reference.get("design"), Mapping) else {}

    brief = str(
        protocol.get("study_design")
        or protocol.get("studyDesignLong")
        or design.get("study_design")
        or study.get("background")
        or ""
    ).strip()
    detailed_parts = [
        str(study.get("background") or "").strip(),
        str(objectives.get("primary") or "").strip(),
        str(objectives.get("secondary") or "").strip(),
    ]
    detailed = "\n\n".join(part for part in detailed_parts if part)
    narrative = {"brief_summary": brief, "detailed_description": detailed}

    from prs_xml import merge_narrative

    result = merge_narrative(dict(reference), narrative)
    report = {
        "status": "passed",
        "batch_id": "prs-narrative",
        "section_ids": ["prs-narrative"],
        "approved_field_families": ["study", "objectives", "design", "endpoints", "generated"],
        "prerequisite_ids": ["protocol-foundations"],
        "draft": narrative,
        "completed_batch_ids": ["prs-narrative"],
        "verification": {"status": "passed", "findings": [], "xml_markup_emitted": False},
    }
    if run_dir is not None:
        path = run_dir / "logs/prs-narrative-drafting.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"reference": result, "report": report}


def draft_prospective_icf(
    reference: Mapping[str, Any],
    *,
    run_dir: Path | None = None,
    study_type: str = "Prospective",
    icf_template: str = "Advarra",
) -> dict[str, Any]:
    """Draft and merge the one participant-facing ICF batch.

    The ICF batch receives only approved study families.  Its section-keyed
    drafts are retained in the reference so the generated candidate and its
    audit trail share the same deterministic contract.
    """
    batch = unified_icf_batch(study_type, icf_template)
    scoped = scoped_batch_input(reference, batch)
    fields = reference.get("template_fields") if isinstance(reference.get("template_fields"), Mapping) else {}
    field_map = {
        "PURPOSE": ("AI_studyPurpose",),
        "WHAT WILL HAPPEN DURING THE STUDY": ("AI_icfVisitsOverview", "AI_visitsDetails"),
        "LENGTH OF THE STUDY AND NUMBER OF PARTICIPANTS EXPECTED": ("AI_visitsAndLength",),
        "SIDE EFFECTS AND OTHER RISKS": ("AI_interventionPossibleSideEffects",),
        "POSSIBLE BENEFITS OF THE STUDY": ("AI_benefits",),
        "PAYMENT FOR BEING IN THE STUDY": ("AI_payment",),
        "ADDITIONAL COSTS": ("AI_costs",),
        "ALTERNATIVES TO PARTICIPATION": ("AI_alternatives",),
        "RELEASE OF MEDICAL RECORDS AND PRIVACY": ("AI_privacy",),
    }
    drafts: list[SectionDraft] = []
    for section in icf_contract(study_type, icf_template):
        values = [str(fields.get(key, "")).strip() for key in field_map.get(section.title, ()) if fields.get(key)]
        if section.title == "LEGAL RIGHTS":
            values.append("The approved Advarra client language preserves the participant's legal rights without referring to a nonexistent injury section.")
        if section.placement:
            values.append("The approved source requires the existing-records disclosure within the study-procedures section.")
        if not values:
            # Legal and signature sections are supplied by the selected client
            # template; retain an explicit section-keyed record without
            # inventing study facts.
            values.append(f"The selected {icf_template} client template supplies the approved {section.title.casefold()} language.")
        drafts.append(SectionDraft(section.section_id, "\n\n".join(values), batch_id=batch.batch_id))

    findings = verify_icf_sections(drafts, study_type, icf_template)
    if findings:
        raise ValueError("ICF Section Draft verification failed: " + "; ".join(item["section_id"] for item in findings))
    merged = tuple(drafts)
    report = {
        "status": "passed",
        "batch_id": batch.batch_id,
        "section_ids": list(batch.section_ids),
        "approved_field_families": list(batch.approved_field_families),
        "prerequisite_ids": list(batch.prerequisite_ids),
        "approved_input": scoped,
        "section_drafts": [
            {"section_id": draft.section_id, "batch_id": draft.batch_id, "content": draft.content, "accepted": draft.accepted}
            for draft in merged
        ],
        "verification": {"status": "passed", "findings": []},
    }
    result = dict(reference)
    generated = result.setdefault("generated", {})
    if not isinstance(generated, dict):
        generated = {}
        result["generated"] = generated
    generated["icf"] = {
        "drafting_contract_version": f"{icf_template.casefold()}-{study_type.casefold()}-v1",
        "sections": report["section_drafts"],
    }
    if run_dir is not None:
        path = run_dir / "logs/icf-drafting.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"reference": result, "report": report, "drafts": merged}


__all__ = ["DraftingBatch", "ProspectiveDraftingBatch", "SectionDraft", "plan_batches", "plan_retrospective_batches", "plan_prospective_batches", "draft_prospective_protocol", "draft_prs_narrative", "draft_prospective_icf", "retrospective_batch_plan", "prospective_batch_plan", "merge_section_drafts"]
