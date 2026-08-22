"""Source-grounded completeness and data-driven table contracts.

This module is intentionally independent from narrative generation.  It is the
read-only contract seam used before approval, rendering, and delivery.  Legacy
template fields are accepted as adapters, but every adapter action is recorded
so a reviewer can see where compatibility was applied.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from study_type_branches import branch_for_study_type, canonical_study_type


CONTRACT_VERSION = "2026-08-21"


def _get(data: Any, path: str) -> Any:
    current = data
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            current = current[index] if index < len(current) else None
        else:
            return None
    return current


def _meaningful(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(_meaningful(child) for child in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_meaningful(child) for child in value)
    return True


def _render(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _signature(value: Any) -> str | None:
    if isinstance(value, dict) and "value" in value:
        value = value["value"]
    if not _meaningful(value):
        return None
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value.strip()).casefold()
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _set_path(data: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    current: Any = data
    for part in parts[:-1]:
        if not isinstance(current, dict):
            return
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    if isinstance(current, dict):
        current[parts[-1]] = value


def _path_with_value(reference: dict[str, Any], paths: list[str]) -> tuple[str | None, Any]:
    for path in paths:
        value = _get(reference, path)
        if _meaningful(value):
            return path, value
    return None, None


DOCUMENT_CONTROL_FIELDS = [
    {"field": "meta.protocol_number", "label": "Protocol number", "aliases": ["template_fields.protocolNumber"]},
    {"field": "meta.version", "label": "Protocol version", "aliases": ["template_fields.version"]},
    {"field": "meta.date", "label": "Protocol date", "aliases": ["template_fields.date"]},
    {"field": "study.title", "label": "Study title", "aliases": ["template_fields.title"]},
    {
        "field": "parties.principal_investigator.name",
        "label": "Principal investigator",
        "aliases": ["template_fields.investigatorName"],
    },
    {
        "field": "parties.principal_investigator.title",
        "label": "Principal investigator title or degree",
        "aliases": ["template_fields.investigatorTitle"],
    },
    {
        "field": "parties.sub_investigators",
        "label": "Sub-investigator information or explicit none",
        "aliases": ["parties.sub_investigator", "template_fields.subInvestigatorName", "template_fields.subInvestigatorHas"],
    },
    {"field": "parties.sponsor.name", "label": "Sponsor", "aliases": ["template_fields.sponsortName", "template_fields.sponsorName"]},
    {"field": "parties.sponsor.address", "label": "Sponsor address", "aliases": ["template_fields.sponsortAdress", "template_fields.sponsorAdress"]},
    {"field": "sites", "label": "Participating sites", "aliases": ["template_fields.facilityName"]},
    {"field": "population.study_population", "label": "Study population", "aliases": ["study.population"]},
    {"field": "study.timeline", "label": "Study duration or timeline", "aliases": ["study.duration", "procedures.duration", "template_fields.AI_duration"]},
]


TABLE_SCHEMAS = {
    "visit_schedule": {
        "label": "Schedule of Assessments",
        "required_columns": ["visitNumber", "visitName", "visitWindow"],
        "optional_columns": ["CRFnumber", "assessments", "armQualification"],
        "required_row_fields": ["visitNumber", "visitName", "visitWindow"],
        "allow_blank": ["CRFnumber", "assessments", "armQualification"],
        "ordered": True,
    },
    "sample_size_evidence": {
        "label": "Sample-size evidence",
        "required_columns": ["evidence", "value", "source"],
        "optional_columns": ["study", "timePoint", "meanChange", "standardError", "estimatedStandardDeviation"],
        "required_row_fields": ["evidence", "value", "source"],
        "allow_blank": [],
        "ordered": False,
    },
}


def table_schema(name: str) -> dict[str, Any] | None:
    return copy.deepcopy(TABLE_SCHEMAS.get(name))


def _table_errors(name: str, table: Any) -> list[dict[str, Any]]:
    schema = TABLE_SCHEMAS[name]
    findings: list[dict[str, Any]] = []
    prefix = f"template_fields.data_driven_tables.{name}"
    if not isinstance(table, dict):
        return [{"field": prefix, "issue": "Table must be an object with columns and rows.", "severity": "blocking"}]
    columns = table.get("columns")
    rows = table.get("rows")
    if not isinstance(columns, list) or not columns:
        findings.append({"field": f"{prefix}.columns", "issue": "Table must declare its columns.", "severity": "blocking"})
        return findings
    keys = []
    labels = set()
    for index, column in enumerate(columns, start=1):
        if not isinstance(column, dict) or not _meaningful(column.get("key")) or not _meaningful(column.get("label")):
            findings.append({"field": f"{prefix}.columns.{index - 1}", "issue": "Every table column needs a key and label.", "severity": "blocking"})
            continue
        key = str(column["key"])
        if key in keys:
            findings.append({"field": f"{prefix}.columns.{index - 1}.key", "issue": f"Duplicate column `{key}`.", "severity": "blocking"})
        keys.append(key)
        labels.add(str(column["label"]).strip().casefold())
    missing_columns = [key for key in schema["required_columns"] if key not in keys]
    if missing_columns:
        findings.append({"field": f"{prefix}.columns", "issue": "Missing required column(s): " + ", ".join(missing_columns) + ".", "severity": "blocking"})
    unexpected = [key for key in keys if key not in schema["required_columns"] + schema["optional_columns"]]
    if unexpected:
        findings.append({"field": f"{prefix}.columns", "issue": "Unsupported column(s): " + ", ".join(unexpected) + ".", "severity": "blocking"})
    expected_count = table.get("validation", {}).get("column_count") if isinstance(table.get("validation"), dict) else None
    if isinstance(expected_count, int) and expected_count != len(keys):
        findings.append({"field": f"{prefix}.columns", "issue": f"Expected {expected_count} columns, found {len(keys)}.", "severity": "blocking"})
    if not isinstance(rows, list) or not rows:
        findings.append({"field": f"{prefix}.rows", "issue": "Table must contain at least one source row.", "severity": "blocking"})
        return findings
    for row_index, row in enumerate(rows):
        row_field = f"{prefix}.rows.{row_index}"
        if not isinstance(row, dict):
            findings.append({"field": row_field, "issue": "Every table row must be an object.", "severity": "blocking"})
            continue
        for key in schema["required_row_fields"]:
            if key not in row or (not _meaningful(row[key]) and key not in schema["allow_blank"]):
                findings.append({"field": f"{row_field}.{key}", "issue": f"Required table value `{key}` is missing or blank.", "severity": "blocking"})
        for key in row:
            if key not in keys:
                findings.append({"field": f"{row_field}.{key}", "issue": f"Row value `{key}` is not declared by the table header.", "severity": "blocking"})
    if schema["ordered"]:
        numbers = []
        for row in rows:
            if isinstance(row, dict):
                match = re.search(r"\d+", _render(row.get("visitNumber")))
                if match:
                    numbers.append(int(match.group(0)))
        if numbers and numbers != sorted(numbers) or len(numbers) != len(rows):
            findings.append({"field": f"{prefix}.rows", "issue": "visit order must be explicit, numeric, and ascending; no visit may be collapsed or omitted.", "severity": "blocking"})
    return findings


def _find_table(reference: dict[str, Any], name: str) -> Any:
    root = _get(reference, "template_fields.data_driven_tables")
    if isinstance(root, dict) and name in root:
        return root[name]
    if name == "visit_schedule":
        return _get(reference, "generated.protocol.visitScheduleTable") or _get(reference, "procedures.visit_schedule_table")
    if name == "sample_size_evidence":
        sample = (
            _get(reference, "statistics.sample_size_evidence")
            or _get(reference, "population.sample_size_evidence")
            or _get(reference, "generated.protocol.sampleSizeEvidenceTable")
        )
        if isinstance(sample, list):
            keys = {str(key) for row in sample if isinstance(row, dict) for key in row}
            ordered = [key for key in TABLE_SCHEMAS[name]["required_columns"] if key in keys]
            ordered.extend(key for key in TABLE_SCHEMAS[name]["optional_columns"] if key in keys)
            return {
                "columns": [{"key": key, "label": key} for key in ordered],
                "rows": sample,
            }
        return sample
    return None


def validate_data_driven_tables(reference: dict[str, Any], *, require_sample_size: bool = False) -> list[dict[str, Any]]:
    """Validate all supplied table data without converting prose or mutating it."""
    findings: list[dict[str, Any]] = []
    schedule = _find_table(reference, "visit_schedule")
    if isinstance(schedule, list):
        schedule = {
            "columns": [{"key": key, "label": label} for key, label in (
                ("visitNumber", "Visit Number"), ("visitName", "Visit Name"),
                ("visitWindow", "Visit Window"), ("CRFnumber", "CRF Number"),
            )],
            "rows": schedule,
        }
    if schedule is None:
        findings.append({"field": "template_fields.data_driven_tables.visit_schedule.rows", "issue": "Schedule of Assessments requires structured visit rows; legacy prose is not unambiguous.", "severity": "blocking"})
    else:
        findings.extend(_table_errors("visit_schedule", schedule))
    sample = _find_table(reference, "sample_size_evidence")
    if sample is not None:
        findings.extend(_table_errors("sample_size_evidence", sample))
    elif require_sample_size:
        findings.append({"field": "template_fields.data_driven_tables.sample_size_evidence.rows", "issue": "Sample-size evidence table is required for auditability.", "severity": "blocking"})
    return findings


def _required_inputs(reference: dict[str, Any], branch: dict[str, Any]) -> list[dict[str, Any]]:
    # Keep the full alias catalog above for normalization/audit, while limiting
    # intake blockers to the branch's approved required-source contract.
    required = copy.deepcopy([
        item for item in DOCUMENT_CONTROL_FIELDS
        if item["field"] in {
            "study.title",
            "parties.principal_investigator.name",
            "parties.principal_investigator.title",
            "parties.sponsor.name",
            "parties.sponsor.address",
            "sites",
            "study.timeline",
        }
    ])
    required.extend([
        {"field": "design.study_design", "label": "Study design", "paths": ["design.study_design"]},
        {"field": "endpoints.primary", "label": "Primary endpoint hierarchy", "paths": ["endpoints.primary"]},
        {"field": "procedures.assessments", "label": "Study assessments", "paths": ["procedures.assessments"]},
        {"field": "population.sample_size", "label": "Sample size", "paths": ["population.sample_size"]},
        {"field": "population.sample_justification", "label": "Sample-size justification", "paths": ["population.sample_justification", "statistics.sample_size_justification"]},
        {"field": "population.inclusion_criteria", "label": "Inclusion criteria", "paths": ["population.inclusion_criteria"]},
        {"field": "population.exclusion_criteria", "label": "Exclusion criteria", "paths": ["population.exclusion_criteria"]},
    ])
    if branch["canonical_study_type"] in {"Prospective", "Ambispective"}:
        required.append({
            "field": "risks_benefits.compensation_or_reimbursement",
            "label": "Participant compensation or reimbursement",
            "paths": [
                "risks_benefits.compensation_or_reimbursement",
                "risks_benefits.compensation",
                "risks_benefits.reimbursement",
            ],
        })
        operational_paths = {
            "procedures.retention": ["procedures.retention"],
            "risks_benefits.injury_handling": ["risks_benefits.injury_handling", "risks_benefits.injury"],
            "procedures.discontinuation": ["procedures.discontinuation", "procedures.withdrawal_rules"],
            "procedures.replacement": ["procedures.replacement", "procedures.replacement_rules"],
            "safety.roles": ["safety.roles", "safety.adverse_events", "safety.general_information"],
        }
        # Once a source elects to supply the enhanced operational family, keep
        # that family internally complete. Its total absence remains nonblocking
        # at the original n8n intake gate.
        if any(_meaningful(_get(reference, path)) for paths in operational_paths.values() for path in paths):
            for field, paths in operational_paths.items():
                required.append({
                    "field": field,
                    "label": field.replace("_", " ").replace(".", " / "),
                    "paths": paths,
                })
    return required


def normalize_reference(reference: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]], list[dict[str, Any]]]:
    """Return a copy with safe legacy aliases materialized and conflicts reported."""
    normalized = copy.deepcopy(reference)
    normalizations: list[dict[str, str]] = []
    conflicts: list[dict[str, Any]] = []
    for item in DOCUMENT_CONTROL_FIELDS:
        field = item["field"]
        structured = _get(normalized, field)
        for alias in item.get("aliases", []):
            alias_value = _get(normalized, alias)
            if not _meaningful(alias_value):
                continue
            if _meaningful(structured):
                if _signature(structured) != _signature(alias_value):
                    if alias.startswith("template_fields."):
                        normalizations.append({
                            "from": alias,
                            "to": field,
                            "reason": "Canonical approved source value was retained over a legacy template projection.",
                        })
                    else:
                        conflicts.append({
                            "field": field,
                            "issue": f"Structured value `{_render(structured)}` conflicts with legacy value `{_render(alias_value)}`.",
                            "evidence_required": "Source evidence and an explicit reviewer decision selecting one canonical value.",
                            "severity": "blocking",
                            "sources": [field, alias],
                        })
                continue
            _set_path(normalized, field, alias_value)
            normalizations.append({"from": alias, "to": field, "reason": "Placeholder Compatibility alias was materialized explicitly."})
            structured = alias_value
            break
    canonical = canonical_study_type(_get(normalized, "meta.study_type"))
    if canonical and _get(normalized, "meta.study_type") != canonical:
        normalizations.append({"from": "meta.study_type", "to": "meta.study_type", "reason": f"Study type normalized to {canonical}."})
        _set_path(normalized, "meta.study_type", canonical)
    return normalized, normalizations, conflicts


def _candidate_conflicts(reference: dict[str, Any], requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    source = reference.get("source") if isinstance(reference.get("source"), dict) else {}
    candidates = source.get("field_candidates") if isinstance(source.get("field_candidates"), dict) else {}
    findings = []
    for requirement in requirements:
        keys = [requirement["field"], *requirement.get("paths", []), *requirement.get("aliases", [])]
        values: list[Any] = []
        for key in keys:
            raw = candidates.get(key)
            if raw is not None:
                values.extend(raw if isinstance(raw, list) else [raw])
        signatures = {_signature(value) for value in values}
        signatures.discard(None)
        if len(signatures) > 1:
            findings.append({
                "field": requirement["field"],
                "issue": f"{len(signatures)} distinct source candidates were supplied for {requirement['label']}.",
                "evidence_required": "Reviewer must reconcile the cited source evidence and approve one value.",
                "severity": "blocking",
                "sources": keys,
            })
    return findings


def validate_source_contract(
    reference: dict[str, Any],
    *,
    require_approval: bool = True,
    require_tables: bool = True,
    require_structured_source: bool = False,
    run_dir: Path | None = None,
) -> dict[str, Any]:
    """Validate branch-aware source facts and return an auditable report."""
    normalized, normalizations, conflicts = normalize_reference(reference)
    meta = normalized.get("meta") if isinstance(normalized.get("meta"), dict) else {}
    branch = branch_for_study_type(meta.get("study_type"))
    findings: list[dict[str, Any]] = []
    if not branch:
        findings.append({"field": "meta.study_type", "issue": "Study type must be Prospective, Ambispective, or Retrospective.", "evidence_required": "Approved source evidence identifying the study branch.", "severity": "blocking"})
    else:
        for requirement in _required_inputs(normalized, branch):
            paths = [requirement["field"], *requirement.get("paths", []), *requirement.get("aliases", [])]
            if not any(_meaningful(_get(normalized, path)) for path in paths):
                findings.append({"field": requirement["field"], "issue": f"Missing required source input: {requirement['label']}.", "evidence_required": f"Approved Source-of-Truth evidence for {requirement['label']}.", "severity": "blocking"})
        expected_docs = set(branch["required_document_set"])
        actual_docs = set(meta.get("document_set") or [])
        for document in sorted(expected_docs - actual_docs):
            findings.append({"field": "meta.document_set", "issue": f"{branch['canonical_study_type']} branch requires `{document}`.", "evidence_required": "Branch selection and the corresponding approved document request.", "severity": "blocking"})
        if branch["canonical_study_type"] in {"Prospective", "Ambispective"}:
            choice = str(meta.get("icf_template") or "").strip().casefold()
            if choice not in {"advarra", "sterling", "provided", "custom"}:
                findings.append({"field": "meta.icf_template", "issue": "Prospective and Ambispective runs require an explicit Advarra or Sterling ICF Template Choice.", "evidence_required": "The client's selected ICF template recorded in run metadata.", "severity": "blocking"})
        if require_tables:
            if branch["canonical_study_type"] in {"Prospective", "Ambispective"}:
                findings.extend(validate_data_driven_tables(normalized, require_sample_size=True))
            else:
                sample = _find_table(normalized, "sample_size_evidence")
                if sample is not None:
                    findings.extend(_table_errors("sample_size_evidence", sample))
        elif require_structured_source:
            # Source review must establish the repeated schedule rows before
            # approval; post-approval adapters may add derived table fields.
            schedule = _find_table(normalized, "visit_schedule")
            if schedule is None or isinstance(schedule, str):
                findings.append({
                    "field": "procedures.visit_schedule_table",
                    "issue": "Repeated visit content must be represented as structured rows before approval; prose alone is not sufficient.",
                    "evidence_required": "Reviewer-provided visit schedule rows with visit number, name, and window.",
                    "severity": "blocking",
                })
    findings.extend(conflicts)
    findings.extend(_candidate_conflicts(normalized, _required_inputs(normalized, branch) if branch else []))
    findings.extend(_contamination_findings(normalized))
    if require_approval:
        approval = normalized.get("approval") if isinstance(normalized.get("approval"), dict) else {}
        if str(approval.get("status") or "").strip().lower() != "approved":
            findings.append({"field": "approval.status", "issue": "Final generation requires an explicitly approved Source-of-Truth.", "evidence_required": "Reviewer approval of the recorded source-of-truth Markdown.", "severity": "blocking"})
        source = normalized.get("source") if isinstance(normalized.get("source"), dict) else {}
        source_file = source.get("source_of_truth_file") or source.get("source_of_truth_md")
        if not _meaningful(source_file):
            findings.append({"field": "source.source_of_truth_file", "issue": "No approved Source-of-Truth Markdown is recorded.", "evidence_required": "The reviewer-facing Source-of-Truth Markdown path and its approval record.", "severity": "blocking"})
        elif isinstance(source_file, str) and not Path(source_file).is_absolute() and not source_file.startswith("reference/"):
            findings.append({"field": "source.source_of_truth_file", "issue": "Source-of-Truth path must be inside the run's reference area.", "evidence_required": "A run-local approved Source-of-Truth Markdown path.", "severity": "blocking"})
        elif run_dir is not None:
            source_path = Path(source_file)
            if not source_path.is_absolute():
                source_path = run_dir / source_path
            if not source_path.is_file():
                findings.append({"field": "source.source_of_truth_file", "issue": "Approved Source-of-Truth Markdown does not exist at the recorded path.", "evidence_required": "The current approved Source-of-Truth Markdown file in the run's reference area.", "severity": "blocking"})
    findings.extend(_review_conflicts(normalized))
    return {
        "contract_version": CONTRACT_VERSION,
        "status": "passed" if not findings else "blocked",
        "study_type": branch["canonical_study_type"] if branch else None,
        "normalized_reference": normalized,
        "normalizations": normalizations,
        "blocking_findings": findings,
        "table_errors": [item for item in findings if str(item.get("field", "")).startswith("template_fields.data_driven_tables")],
    }


def _review_conflicts(reference: dict[str, Any]) -> list[dict[str, Any]]:
    items = reference.get("needs_review") if isinstance(reference.get("needs_review"), list) else []
    findings = []
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or item.get("type") or item.get("reason") or "").casefold()
        if "conflict" in kind or "multiple" in kind:
            field = str(item.get("field") or "needs_review")
            findings.append({"field": field, "issue": str(item.get("issue") or "Conflicting source input remains unresolved."), "evidence_required": "Reviewer resolution of the conflicting source candidates.", "severity": "blocking"})
    return findings


def _generated_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for child in value.values() for item in _generated_strings(child)]
    if isinstance(value, list):
        return [item for child in value for item in _generated_strings(child)]
    return []


def _contamination_findings(reference: dict[str, Any]) -> list[dict[str, Any]]:
    generated = reference.get("generated")
    template_fields = reference.get("template_fields")
    values = _generated_strings(generated) + _generated_strings(template_fields)
    pattern = re.compile(r"\b(?:draft|todo|tbd|needs review|internal only|source[- ]of[- ]truth|finalize later)\b", re.I)
    findings = []
    for value in values:
        match = pattern.search(value)
        if match:
            findings.append({
                "field": "generated",
                "issue": f"Internal drafting language `{match.group(0)}` is present in generated client content.",
                "evidence_required": "A clean approved narrative or a reviewer repair removing internal process language.",
                "severity": "blocking",
            })
    return findings


def repair_report_markdown(findings: list[dict[str, Any]]) -> str:
    lines = [
        "# Repair Report",
        "",
        "Final delivery is blocked until every finding below is resolved and the affected gates are rerun.",
        "",
    ]
    if not findings:
        lines.append("No blocking findings.")
        return "\n".join(lines) + "\n"
    for index, finding in enumerate(findings, start=1):
        lines.extend([
            f"## {index}. `{finding.get('field', 'unknown')}`",
            "",
            f"- Severity: {finding.get('severity', 'blocking')}",
            f"- Why this blocks delivery: {finding.get('issue', 'Review required.')}",
            f"- Evidence required: {finding.get('evidence_required', 'Approved source evidence or an explicit reviewer decision.')}",
        ])
        if finding.get("sources"):
            lines.append("- Candidate/source locations: " + ", ".join(str(item) for item in finding["sources"]))
        lines.append("")
    return "\n".join(lines)
