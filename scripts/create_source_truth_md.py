#!/usr/bin/env python3
"""Create an editable Markdown source-of-truth input map."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from check_required_inputs import missing_inputs, write_report
from icf_template_selection import ensure_run_icf_template


STANDARD_REFERENCE = "reference/study.reference.json"
STANDARD_MISSING_REPORT = "reference/missing-inputs.md"
EXCLUDED_REVIEW_PREFIXES = (
    "generated.",
    "template_fields.",
    "source.",
    "approval.",
    "needs_review.",
)

# Keep this list input-only. Generated prose belongs in final outputs, not in
# the reviewer source document.
SECTION_SPECS: list[tuple[str, list[str]]] = [
    (
        "Study Identification",
        [
            "meta.study_type",
            "meta.protocol_number",
            "meta.version",
            "meta.date",
            "study.title",
            "study.short_title",
            "study.acronym",
            "study.condition",
            "study.status",
        ],
    ),
    (
        "Study Rationale",
        [
            "study.background",
            "study.significance",
            "study.unmet_need",
            "study.hypothesis",
            "study.timeline",
        ],
    ),
    (
        "Sponsor And Study Team",
        [
            "parties.sponsor",
            "parties.funding_source",
            "parties.principal_investigator",
            "parties.sub_investigator",
            "parties.subinvestigator",
            "parties.study_coordinator",
            "parties.overall_contact",
            "parties.overall_contact_backup",
            "parties.responsible_party",
            "parties.collaborator",
        ],
    ),
    ("IRB And Ethics", ["parties.irb", "parties.ethics_committee"]),
    ("Sites And Facilities", ["sites"]),
    (
        "Population And Eligibility",
        [
            "population.sample_size",
            "population.sample_justification",
            "population.study_population",
            "population.minimum_age",
            "population.maximum_age",
            "population.gender",
            "population.sex",
            "population.healthy_volunteers",
            "population.inclusion_criteria",
            "population.exclusion_criteria",
        ],
    ),
    (
        "Design And Interventions",
        [
            "design.study_design",
            "design.number_of_sites",
            "design.study_arm",
            "design.arms",
            "design.groups",
            "design.interventions",
            "design.intervention_type",
            "design.intervention_name",
            "design.intervention",
            "design.test_articles",
            "design.control_articles",
            "design.masking",
            "design.blinding",
            "design.data_sources",
            "design.sampling_method",
        ],
    ),
    (
        "Objectives And Endpoints",
        [
            "objectives.primary",
            "objectives.secondary",
            "objectives.exploratory",
            "endpoints.primary",
            "endpoints.secondary",
            "endpoints.other",
            "endpoints.exploratory",
            "endpoints.safety",
        ],
    ),
    (
        "Procedures And Assessments",
        [
            "procedures.visit_schedule",
            "procedures.visit_schedule_table",
            "procedures.assessments",
            "procedures.assessment_details",
            "procedures.data_sources",
            "procedures.study_procedure",
            "procedures.methods",
            "procedures.privacy_protocol",
            "procedures.minimum_days_before_screening_without_participation",
        ],
    ),
    (
        "Dates And Follow-Up",
        [
            "procedures.start_date",
            "procedures.start_date_type",
            "procedures.end_date",
            "procedures.end_date_type",
            "procedures.primary_completion_date",
            "procedures.primary_completion_date_type",
            "procedures.last_follow_up_date",
            "procedures.last_follow_up_date_type",
        ],
    ),
    (
        "Statistics",
        [
            "statistics.enrollment",
            "statistics.groups",
            "statistics.sample_size_justification",
            "statistics.analysis_plan",
            "statistics.methodology",
            "statistics.software",
        ],
    ),
    (
        "Risks Benefits And Payment",
        [
            "risks_benefits.risks",
            "risks_benefits.benefits",
            "risks_benefits.side_effects",
            "risks_benefits.compensation_or_reimbursement",
            "risks_benefits.compensation",
            "risks_benefits.reimbursement",
            "risks_benefits.payment",
            "risks_benefits.privacy",
            "risks_benefits.voluntary_participation",
            "risks_benefits.contact",
        ],
    ),
    (
        "Regulatory And PRS Inputs",
        [
            "regulatory.jurisdiction",
            "regulatory.fda_regulated_drug",
            "regulatory.fda_regulated_device",
            "regulatory.prs.provider_study_id",
            "regulatory.prs.provider_name",
            "regulatory.prs.org_name",
            "regulatory.prs.overall_status",
            "regulatory.prs.irb_approval_status",
            "regulatory.prs.study_uid",
            "regulatory.prs.lead_sponsor_agency",
            "regulatory.prs.collaborator_agency",
            "regulatory.prs.responsible_party_type",
            "regulatory.prs.enrollment_type",
            "regulatory.prs.start_date_type",
            "regulatory.prs.primary_completion_date_type",
            "regulatory.prs.observational_study_design",
            "regulatory.prs.study_timing",
            "regulatory.prs.healthy_volunteers",
            "regulatory.prs.fda_regulated_drug",
            "regulatory.prs.fda_regulated_device",
            "regulatory.prs.last_follow_up_date",
            "regulatory.prs.last_follow_up_date_type",
        ],
    ),
    ("References Provided By Reviewer", ["references"]),
]


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def display_path(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.name


def text_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value).strip()
    return ""


def slugify(value: Any, fallback: str, max_length: int = 72) -> str:
    rendered = text_value(value) or fallback
    normalized = unicodedata.normalize("NFKD", rendered)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        slug = fallback
    return slug[:max_length].strip("-") or fallback


def default_output_path(run_dir: Path, reference: dict) -> Path:
    protocol = slugify(get_path(reference, "meta.protocol_number"), "no-protocol", 36)
    title = slugify(
        get_path(reference, "study.short_title") or get_path(reference, "study.title"),
        "study",
        84,
    )
    return run_dir / "reference" / f"source-of-truth--{protocol}--{title}.md"


def get_path(data: Any, dotted_path: str) -> Any:
    current = data
    for part in dotted_path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            current = current[index] if index < len(current) else None
        else:
            return None
        if current is None:
            return None
    return current


def is_scalar(value: Any) -> bool:
    return not isinstance(value, (dict, list))


def flatten_review_values(value: Any, prefix: str) -> list[tuple[str, Any]]:
    if isinstance(value, dict):
        rows: list[tuple[str, Any]] = []
        for key in sorted(value):
            rows.extend(flatten_review_values(value[key], f"{prefix}.{key}" if prefix else str(key)))
        return rows
    if isinstance(value, list):
        if not value:
            return []
        if all(is_scalar(item) for item in value):
            return [(prefix, value)]
        rows = []
        for index, item in enumerate(value):
            rows.extend(flatten_review_values(item, f"{prefix}.{index}" if prefix else str(index)))
        return rows
    return [(prefix, value)]


def value_to_markdown(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        lines = []
        for item in value:
            if item is None:
                continue
            rendered = value_to_markdown(item).strip()
            if rendered:
                lines.append(f"- {rendered}")
        return "\n".join(lines)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def label_for(path: str) -> str:
    parts = [part for part in path.split(".") if not part.isdigit()]
    if not parts:
        return path
    label = parts[-1].replace("_", " ").replace("-", " ")
    return label[:1].upper() + label[1:]


def section_fields(reference: dict) -> list[tuple[str, list[tuple[str, str, str]]]]:
    used: set[str] = set()
    sections = []
    for title, paths in SECTION_SPECS:
        rows: list[tuple[str, str, str]] = []
        for path in paths:
            value = get_path(reference, path)
            if value is None:
                continue
            for field_id, field_value in flatten_review_values(value, path):
                if not field_id or field_id in used:
                    continue
                if field_id.startswith(EXCLUDED_REVIEW_PREFIXES):
                    continue
                used.add(field_id)
                rows.append((field_id, label_for(field_id), value_to_markdown(field_value)))
        if rows:
            sections.append((title, rows))
    return sections


def document_markdown(reference: dict) -> str:
    title = get_path(reference, "study.title") or "Structured Study Source"
    lines = [
        "# Study Input Source Of Truth",
        "",
        f"Study preview, not editable: {title}",
        "",
        "The editable source inputs start at the `## Editable Study Inputs Start Here` heading below.",
        "Edit only the text between each `<!-- field: ... -->` marker and `<!-- /field -->` marker.",
        "Do not edit the preview line above, and do not edit or delete the marker lines. Generated protocol, ICF, summary, and XML prose are intentionally excluded.",
        "",
        "<!-- source-truth-format: clinical-document-generation/v1 -->",
        "",
        "## Editable Study Inputs Start Here",
        "",
    ]
    for section_title, fields in section_fields(reference):
        lines.extend([f"## {section_title}", ""])
        for field_id, label, value in fields:
            lines.extend(
                [
                    f"### {label}",
                    f"<!-- field: {field_id} -->",
                    value,
                    "<!-- /field -->",
                    "",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def update_source_metadata(reference_path: Path, reference: dict, output_path: Path, run_dir: Path) -> None:
    source = reference.get("source")
    if not isinstance(source, dict):
        source = {}
    rel_path = display_path(output_path, run_dir)
    source["source_of_truth_file"] = rel_path
    source["source_of_truth_md"] = rel_path
    source["source_of_truth_status"] = "draft_generated"
    source["source_of_truth_generated_at"] = datetime.now(timezone.utc).isoformat()
    reference["source"] = source

    approval = reference.get("approval")
    if not isinstance(approval, dict):
        approval = {}
    approval["review_file"] = rel_path
    approval["status"] = "pending_review"
    approval["approved_by"] = None
    approval["approved_at"] = None
    reference["approval"] = approval

    reference_path.write_text(json.dumps(reference, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, help="Run directory containing reference/study.reference.json.")
    parser.add_argument("--reference", help="Reference JSON path. Defaults to reference/study.reference.json.")
    parser.add_argument(
        "--output",
        help="Markdown output path. Defaults to reference/source-of-truth--<protocol>--<study-slug>.md.",
    )
    parser.add_argument("--require-complete", action="store_true", help="Fail if required source inputs are missing.")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser().resolve()
    reference_path = Path(args.reference).expanduser().resolve() if args.reference else run_dir / STANDARD_REFERENCE
    reference = load_json(reference_path)
    selection = ensure_run_icf_template(run_dir, reference)
    if selection.get("choice"):
        reference_path.write_text(json.dumps(reference, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    output_path = Path(args.output).expanduser().resolve() if args.output else default_output_path(run_dir, reference)

    missing = missing_inputs(reference)
    if args.require_complete and missing:
        write_report(run_dir / STANDARD_MISSING_REPORT, run_dir, missing)
        print(json.dumps({"created": None, "missing_count": len(missing), "missing_report": STANDARD_MISSING_REPORT}, indent=2))
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(document_markdown(reference), encoding="utf-8")
    update_source_metadata(reference_path, reference, output_path, run_dir)
    print(json.dumps({"created": display_path(output_path, run_dir), "field_count": sum(len(rows) for _, rows in section_fields(reference))}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
