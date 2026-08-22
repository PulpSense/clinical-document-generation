"""Single public workflow seam for clinical document generation.

The conversational agent supplies and reviews the study facts; this module
provides the deterministic run-state transitions and client handoff boundary.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from check_required_inputs import missing_inputs
from create_source_truth_md import (
    default_output_path,
    document_markdown,
    section_fields,
    update_source_metadata,
)
from delivery_pipeline import run_delivery_pipeline
from icf_template_selection import ensure_run_icf_template
from quality_contract import repair_report_markdown, validate_source_contract
from parse_source_truth_md import parse_source_truth
from readiness_contract import readiness_evidence, readiness_report
from revisions import create_revision, invalidate_changed_source, publish_revision
from render_templates import run_generation
from study_type_branches import branch_for_study_type


STANDARD_REFERENCE = "reference/study.reference.json"


def branch_contract(reference: dict[str, Any]) -> dict[str, Any]:
    """Return the approved branch document contract for the public workflow."""
    branch = branch_for_study_type((reference.get("meta") or {}).get("study_type"))
    if branch is None:
        raise ValueError("Study type must be Prospective, Ambispective, or Retrospective.")
    configured = (reference.get("meta") or {}).get("document_set")
    document_set = configured if isinstance(configured, list) else list(branch["required_document_set"])
    required = list(branch["required_document_set"])
    return {
        "study_type": branch["canonical_study_type"],
        "document_set": list(document_set),
        "required_document_set": required,
        "missing_documents": sorted(set(required) - set(document_set)),
        "icf_required": branch["canonical_study_type"] in {"Prospective", "Ambispective"},
    }


def validated_client_outputs(run_dir: Path, report: dict[str, Any]) -> list[Path]:
    """Return only outputs named by a passed public workflow report."""
    if report.get("status") != "passed":
        return []
    return [
        run_dir / relative
        for relative in report.get("client_outputs", [])
        if (run_dir / relative).is_file()
    ]


def validate_run(run_dir: Path, *, require_approval: bool = True) -> dict[str, Any]:
    """Return the single consolidated readiness report for a run.

    This is the public pre-generation check. It deliberately does not render,
    repair, or mutate client documents; it gives the conversational workflow
    one deterministic blocker report to resolve before approval or delivery.
    """
    run_dir = run_dir.resolve()
    _, reference = _load_reference(run_dir)
    invalidation = invalidate_changed_source(run_dir, reference)
    if invalidation:
        reference = json.loads((run_dir / STANDARD_REFERENCE).read_text(encoding="utf-8"))
    report = readiness_report(reference, require_approval=require_approval, run_dir=run_dir)
    return {
        "status": report["status"],
        "stage": "readiness",
        "readiness_report": report,
        "source_invalidation": invalidation,
        "client_outputs": [],
    }


def _load_reference(run_dir: Path) -> tuple[Path, dict[str, Any]]:
    path = run_dir / STANDARD_REFERENCE
    return path, json.loads(path.read_text(encoding="utf-8"))


def _write_reference(path: Path, reference: dict[str, Any]) -> None:
    path.write_text(json.dumps(reference, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _merge_findings(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for group in groups:
        for finding in group:
            field = str(finding.get("field") or "unknown")
            issue = str(finding.get("issue") or "Review required.")
            key = (field, issue)
            if key in seen:
                continue
            seen.add(key)
            merged.append({**finding, "field": field, "issue": issue, "severity": finding.get("severity", "blocking")})
    return merged


def _merge_nonempty(target: dict[str, Any], incoming: dict[str, Any]) -> None:
    """Apply adapter values without erasing approved/generated content."""
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge_nonempty(target[key], value)
        elif value not in (None, "", [], {}):
            target[key] = value


def _write_input_blockers(run_dir: Path, findings: list[dict[str, Any]]) -> None:
    lines = [
        "# Missing Inputs",
        "",
        "The skill cannot create the Source-of-Truth Markdown or final documents yet.",
        "Provide or resolve every item below together, then rerun the workflow.",
        "",
    ]
    for index, finding in enumerate(findings, start=1):
        lines.extend([
            f"## {index}. `{finding['field']}`",
            "",
            f"- Why it is required: {finding['issue']}",
            f"- Evidence needed: {finding.get('evidence_required', 'Client-provided source evidence or an explicit client decision.')}",
            "",
        ])
    path = run_dir / "reference/missing-inputs.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _populate_branch_fields(run_dir: Path, reference_path: Path, reference: dict[str, Any]) -> dict[str, Any]:
    """Materialize deterministic template adapters after source approval."""
    branch = branch_for_study_type((reference.get("meta") or {}).get("study_type"))
    if branch is None:
        raise ValueError("Study type must be Prospective, Ambispective, or Retrospective.")
    if branch["canonical_study_type"] in {"Prospective", "Ambispective"}:
        from build_n8n_prospective_fields import build_fields

        fields = build_fields(reference)
    else:
        from build_n8n_retrospective_protocol_fields import build_fields

        fields = build_fields(reference)
    merged = reference.get("template_fields")
    if not isinstance(merged, dict):
        merged = {}
    _merge_nonempty(merged, fields)
    reference["template_fields"] = merged
    prs_missing: list[dict[str, Any]] = []
    if branch["canonical_study_type"] in {"Prospective", "Ambispective"}:
        xml_template = run_dir / "templates/study.template.xml"
        if xml_template.is_file():
            from build_prs_xml_fields import build_fields as build_prs_fields

            prs_fields, prs_missing = build_prs_fields(reference, xml_template)
            _merge_nonempty(reference["template_fields"], prs_fields)
    _write_reference(reference_path, reference)
    return {"branch": branch["canonical_study_type"], "field_count": len(fields), "prs_missing": prs_missing}


def prepare_run(run_dir: Path, *, requested_icf_choice: Any = None) -> dict[str, Any]:
    """Create one consolidated input request or the approval Markdown."""
    run_dir = run_dir.resolve()
    reference_path, reference = _load_reference(run_dir)
    invalidation = invalidate_changed_source(run_dir, reference)
    if invalidation:
        reference = json.loads(reference_path.read_text(encoding="utf-8"))
    branch = branch_for_study_type((reference.get("meta") or {}).get("study_type"))
    selection = ensure_run_icf_template(run_dir, reference, requested_choice=requested_icf_choice)
    if selection.get("choice"):
        _write_reference(reference_path, reference)

    legacy_findings = missing_inputs(reference)
    # Repeated source structures are reviewed before approval; generated prose
    # and format-specific adapters remain post-approval concerns.
    contract = validate_source_contract(
        reference,
        require_approval=False,
        require_tables=False,
        require_structured_source=True,
    )
    findings = _merge_findings(legacy_findings, contract["blocking_findings"])
    if findings:
        _write_input_blockers(run_dir, findings)
        return {
            "status": "blocked",
            "stage": "input_collection",
            "study_type": branch["canonical_study_type"] if branch else None,
            "missing_count": len(findings),
            "missing": findings,
            "source_of_truth": None,
            "client_outputs": [],
            "source_invalidation": invalidation,
        }

    (run_dir / "reference/missing-inputs.md").unlink(missing_ok=True)
    output_path = default_output_path(run_dir, reference)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(document_markdown(reference), encoding="utf-8")
    update_source_metadata(reference_path, reference, output_path, run_dir)
    return {
        "status": "awaiting_approval",
        "stage": "source_review",
        "study_type": branch["canonical_study_type"] if branch else None,
        "source_of_truth": output_path.relative_to(run_dir).as_posix(),
        "field_count": sum(len(rows) for _, rows in section_fields(reference)),
        "client_outputs": [],
        "source_invalidation": invalidation,
    }


def generate_approved_run(run_dir: Path, *, require_renderer: bool = False) -> dict[str, Any]:
    """Generate and gate the complete Branch Document Set after approval."""
    run_dir = run_dir.resolve()
    reference_path, reference = _load_reference(run_dir)
    invalidation = invalidate_changed_source(run_dir, reference)
    if invalidation:
        return {"status": "blocked", "stage": "approval_gate", "findings": [invalidation], "client_outputs": []}
    # Table adapters are materialized below by _populate_branch_fields.
    contract = validate_source_contract(reference, require_approval=True, require_tables=False, run_dir=run_dir)
    if contract["status"] != "passed":
        repair_path = run_dir / "reference/repair-report.md"
        repair_path.parent.mkdir(parents=True, exist_ok=True)
        repair_path.write_text(repair_report_markdown(contract["blocking_findings"]), encoding="utf-8")
        return {
            "status": "blocked",
            "stage": "approval_gate",
            "findings": contract["blocking_findings"],
            "client_outputs": [],
        }

    try:
        adapter_report = _populate_branch_fields(run_dir, reference_path, reference)
        generation = run_generation(
            run_dir,
            reference_path,
            require_approval=True,
            require_source_contract=True,
        )
        pipeline = run_delivery_pipeline(
            run_dir,
            generation["outputs"],
            require_source_contract=True,
            require_renderer=require_renderer,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"status": "blocked", "stage": "generation", "error": str(exc), "client_outputs": []}

    approval = reference.get("approval") if isinstance(reference.get("approval"), dict) else {}
    revision_id = approval.get("run_revision")
    revision = None
    if revision_id:
        manifest_path = run_dir / "revisions" / str(revision_id) / "generation-manifest.json"
        if manifest_path.is_file():
            revision = json.loads(manifest_path.read_text(encoding="utf-8"))
    if revision is None:
        revision = create_revision(run_dir, reference_path, Path(reference["source"]["source_of_truth_file"]))
    revision_id = revision.get("revision_id") if isinstance(revision, dict) else revision_id
    evidence = readiness_evidence(
        json.loads(reference_path.read_text(encoding="utf-8")),
        pipeline=pipeline,
        outputs=generation["outputs"],
        run_dir=run_dir,
    )
    evidence_path = run_dir / "logs/readiness-evidence.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    client_outputs = pipeline.get("client_outputs", []) if pipeline["status"] == "passed" else []
    if pipeline["status"] == "passed" and revision_id:
        publish_revision(run_dir, str(revision_id), client_outputs)
    return {
        "status": "passed" if pipeline["status"] == "passed" else "blocked",
        "stage": "delivery",
        "generation": generation,
        "branch_adapters": adapter_report,
        "delivery_pipeline": pipeline,
        "readiness_evidence": evidence,
        "run_revision": revision,
        "client_outputs": client_outputs,
    }


def approve_source(
    run_dir: Path,
    *,
    approved_by: str = "client",
    source_md: Path | None = None,
) -> dict[str, Any]:
    """Parse the current source Markdown and record explicit client approval."""
    run_dir = run_dir.resolve()
    reference_path, reference = _load_reference(run_dir)
    source = reference.get("source") if isinstance(reference.get("source"), dict) else {}
    source_file = source_md or source.get("source_of_truth_file") or source.get("source_of_truth_md")
    if not source_file:
        raise ValueError("No Source-of-Truth Markdown is recorded for this run.")
    source_path = Path(source_file)
    if not source_path.is_absolute():
        source_path = run_dir / source_path
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    result = parse_source_truth(
        run_dir,
        source_path,
        approval_status="approved",
        approved_by=approved_by,
        reference_path=reference_path,
    )
    revision = create_revision(run_dir, reference_path, source_path)
    result["run_revision"] = revision
    updated = json.loads(reference_path.read_text(encoding="utf-8"))
    approval = updated.setdefault("approval", {})
    approval["run_revision"] = revision["revision_id"]
    approval["revision_path"] = revision["path"]
    _write_reference(reference_path, updated)
    return result


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--stage", choices=["prepare", "approve", "validate", "generate"], required=True)
    parser.add_argument("--approved-by", default="client")
    parser.add_argument("--source-md", help="Optional client-edited Source-of-Truth Markdown path.")
    parser.add_argument("--icf-choice", choices=["advarra", "sterling"])
    parser.add_argument("--require-renderer", action="store_true")
    args = parser.parse_args(argv)
    run_dir = Path(args.run_dir).expanduser().resolve()
    if args.stage == "prepare":
        result = prepare_run(run_dir, requested_icf_choice=args.icf_choice)
    elif args.stage == "approve":
        result = approve_source(
            run_dir,
            approved_by=args.approved_by,
            source_md=Path(args.source_md).expanduser() if args.source_md else None,
        )
    elif args.stage == "validate":
        result = validate_run(run_dir)
    else:
        result = generate_approved_run(run_dir, require_renderer=args.require_renderer)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    status = result.get("status")
    return 0 if status in {"awaiting_approval", "passed"} or args.stage == "approve" else 1


if __name__ == "__main__":
    raise SystemExit(main())
