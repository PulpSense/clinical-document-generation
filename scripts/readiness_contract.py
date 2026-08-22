"""Readiness evidence and change-boundary contract for the skill."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from quality_contract import validate_source_contract
from study_type_branches import branch_for_study_type, content_completeness_missing


def readiness_report(
    reference: dict[str, Any],
    *,
    require_approval: bool = True,
    run_dir: Path | None = None,
) -> dict[str, Any]:
    """Report source, branch, content, and handoff readiness without mutation."""
    meta = reference.get("meta") if isinstance(reference.get("meta"), dict) else {}
    branch = branch_for_study_type(meta.get("study_type"))
    source = validate_source_contract(
        reference,
        require_approval=require_approval,
        require_tables=True,
        run_dir=run_dir,
    )
    content = content_completeness_missing(reference)
    required_documents = list(branch["required_document_set"]) if branch else []
    actual_documents = meta.get("document_set") if isinstance(meta.get("document_set"), list) else []
    missing_documents = sorted(set(required_documents) - set(actual_documents))
    findings = list(source["blocking_findings"])
    findings.extend(
        {
            "field": item["field"],
            "issue": item["issue"],
            "severity": "blocking",
            "evidence_required": "Branch-specific generated content or a source-grounded repair.",
        }
        for item in content
    )
    findings.extend(
        {
            "field": "meta.document_set",
            "issue": f"Required {source['study_type'] or 'study'} output `{document}` is not configured.",
            "severity": "blocking",
            "evidence_required": "The approved branch document set and its templates.",
        }
        for document in missing_documents
    )
    return {
        "status": "passed" if not findings else "blocked",
        "study_type": source["study_type"],
        "required_document_set": required_documents,
        "document_set": actual_documents,
        "missing_documents": missing_documents,
        "source_contract": source,
        "content_completeness_missing": content,
        "findings": findings,
    }


READINESS_CONTRACT_VERSION = "2026-08-21"

REQUIRED_BLOCKING_SCENARIOS = [
    "missing_required_source_input",
    "conflicting_source_candidates",
    "unapproved_source_of_truth",
    "missing_or_ambiguous_icf_template_choice",
    "internally_contaminated_generated_content",
    "invalid_data_driven_table",
    "missing_required_branch_output",
    "failed_docx_package_or_structure_gate",
    "failed_render_or_static_toc_gate",
]

FINDING_CATEGORIES = {
    "contract_bug": "A required behavior or validation rule disagrees with this readiness contract.",
    "reference_defect": "The embedded client reference or bundled template has a presentation defect that must be corrected without changing the contract.",
    "new_requirement": "The report asks for a new branch, document type, source fact, or user choice outside this destination.",
}


def classify_future_finding(category: str) -> dict[str, str]:
    """Return the agreed action for a future report category."""
    if category not in FINDING_CATEGORIES:
        raise ValueError(f"Unknown readiness finding category: {category}")
    return {"category": category, "action": FINDING_CATEGORIES[category]}


def readiness_evidence(
    reference: dict[str, Any],
    *,
    pipeline: dict[str, Any] | None = None,
    outputs: list[str] | None = None,
    run_dir: Path | None = None,
) -> dict[str, Any]:
    """Build the auditable readiness record without mutating the run."""
    report = readiness_report(reference, require_approval=True, run_dir=run_dir)
    branch = branch_for_study_type((reference.get("meta") or {}).get("study_type"))
    gates = {
        "source_completeness": "required",
        "content_completeness": "required",
        "docx_package_and_structure": "required",
        "prs_xml": "required" if branch and branch["canonical_study_type"] in {"Prospective", "Ambispective"} else "not_applicable",
        "visual_layout": "required_when_renderer_available",
        "static_toc": "required_when_renderer_available",
        "client_handoff_filter": "required",
    }
    observed_outputs = outputs or []
    pipeline_status = pipeline.get("status") if isinstance(pipeline, dict) else None
    status = "passed" if report["status"] == "passed" and (pipeline_status in {None, "passed"}) else "blocked"
    return {
        "contract_version": READINESS_CONTRACT_VERSION,
        "status": status,
        "study_type": report["study_type"],
        "required_document_set": report["required_document_set"],
        "observed_outputs": observed_outputs,
        "required_gates": gates,
        "blocking_scenarios": list(REQUIRED_BLOCKING_SCENARIOS),
        "change_boundary": {category: classify_future_finding(category) for category in FINDING_CATEGORIES},
        "branch_readiness": report,
        "delivery_pipeline_status": pipeline_status,
    }
