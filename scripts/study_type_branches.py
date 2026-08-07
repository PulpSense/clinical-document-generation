"""Study-type branch rules derived from the existing generation workflow."""

from __future__ import annotations

import json
import re
from typing import Any


DOC_TEMPLATES = {
    "protocol_docx": "templates/protocol.template.docx",
    "icf_docx": "templates/icf.template.docx",
    "short_docx": "templates/short.template.docx",
    "xml": "templates/study.template.xml",
    "main_docx": "templates/main.template.docx",
}


# These are the 35 fields/groups marked with `*` in both the prospective and
# ambispective Fillout intakes. `field` is the stable reporting/candidate key;
# `paths` are accepted locations in study.reference.json.
STARRED_FILLOUT_FIELDS = [
    {"field": "study.title", "label": "Full title of the study", "paths": ["study.title"]},
    {
        "field": "study.background",
        "label": "Background and significance of the study",
        "paths": ["study.background"],
    },
    {
        "field": "objectives.primary",
        "label": "Primary objectives",
        "paths": ["objectives.primary"],
    },
    {"field": "study.hypothesis", "label": "Study hypothesis", "paths": ["study.hypothesis"]},
    {
        "field": "design.study_design",
        "label": "Study design",
        "paths": ["design.study_design"],
    },
    {
        "field": "design.intervention_name",
        "label": "Intervention name",
        "paths": ["design.intervention_name", "design.intervention.name", "design.intervention"],
    },
    {
        "field": "design.intervention_type",
        "label": "Intervention type",
        "paths": ["design.intervention_type", "design.intervention.type"],
    },
    {
        "field": "design.number_of_sites",
        "label": "Number of investigational sites",
        "paths": ["design.number_of_sites"],
        "kind": "site_count",
    },
    {
        "field": "endpoints.primary",
        "label": "Primary and secondary endpoints",
        "paths": ["endpoints.primary"],
    },
    {
        "field": "procedures.assessments",
        "label": "Planned assessments and schedule",
        "paths": ["procedures.assessments", "procedures.visit_schedule"],
    },
    {
        "field": "population.inclusion_criteria",
        "label": "Inclusion criteria",
        "paths": ["population.inclusion_criteria"],
    },
    {
        "field": "population.exclusion_criteria",
        "label": "Exclusion criteria",
        "paths": ["population.exclusion_criteria"],
    },
    {
        "field": "procedures.minimum_days_before_screening_without_participation",
        "label": "Minimum days before screening without another study",
        "paths": ["procedures.minimum_days_before_screening_without_participation"],
    },
    {
        "field": "population.sample_size",
        "label": "Sample size",
        "paths": ["population.sample_size"],
    },
    {
        "field": "population.sample_justification",
        "label": "Sample justification",
        "paths": ["population.sample_justification", "statistics.sample_size_justification"],
    },
    {
        "field": "risks_benefits.compensation_or_reimbursement",
        "label": "Participant compensation or travel reimbursement",
        "paths": [
            "risks_benefits.compensation_or_reimbursement",
            "risks_benefits.compensation",
            "risks_benefits.reimbursement",
            "risks_benefits.payment",
        ],
    },
    {
        "field": "statistics.analysis_plan",
        "label": "Statistical analysis plan",
        "paths": ["statistics.analysis_plan"],
    },
    {"field": "study.timeline", "label": "Study timeline", "paths": ["study.timeline"]},
    {
        "field": "parties.irb.name",
        "label": "IRB or ethics committee name",
        "paths": ["parties.irb.name", "parties.ethics_committee.name"],
    },
    {
        "field": "parties.irb.affiliation",
        "label": "IRB affiliation",
        "paths": ["parties.irb.affiliation", "parties.ethics_committee.affiliation"],
    },
    {
        "field": "parties.irb.phone",
        "label": "IRB phone number",
        "paths": ["parties.irb.phone", "parties.ethics_committee.phone"],
    },
    {
        "field": "parties.irb.email",
        "label": "IRB contact email",
        "paths": ["parties.irb.email", "parties.ethics_committee.email"],
    },
    {
        "field": "parties.irb.address",
        "label": "IRB full address",
        "paths": [
            "parties.irb.address",
            "parties.irb.full_address",
            "parties.ethics_committee.address",
            "parties.ethics_committee.full_address",
        ],
    },
    {
        "field": "parties.sponsor.name",
        "label": "Sponsor or funding body name",
        "paths": ["parties.sponsor.name"],
    },
    {
        "field": "parties.sponsor.address",
        "label": "Sponsor or funding body full address",
        "paths": ["parties.sponsor.address"],
    },
    {
        "field": "parties.principal_investigator.name",
        "label": "Principal investigator name",
        "paths": ["parties.principal_investigator.name"],
    },
    {
        "field": "parties.principal_investigator.title",
        "label": "Principal investigator title or degree",
        "paths": ["parties.principal_investigator.title", "parties.principal_investigator.degree"],
    },
    {
        "field": "parties.study_coordinator.name",
        "label": "Study coordinator name",
        "paths": ["parties.study_coordinator.name"],
    },
    {
        "field": "parties.study_coordinator.title",
        "label": "Study coordinator title or degree",
        "paths": ["parties.study_coordinator.title", "parties.study_coordinator.degree"],
    },
    {
        "field": "parties.study_coordinator.business_phone",
        "label": "Study coordinator business phone",
        "paths": ["parties.study_coordinator.business_phone"],
    },
    {
        "field": "parties.study_coordinator.office_phone",
        "label": "Study coordinator office phone",
        "paths": ["parties.study_coordinator.office_phone"],
    },
    {
        "field": "parties.study_coordinator.email",
        "label": "Study coordinator email",
        "paths": ["parties.study_coordinator.email"],
    },
    {
        "field": "sites.facilities",
        "label": "Facilities table",
        "paths": ["sites"],
        "kind": "facilities_table",
    },
    {
        "field": "sites.contacts",
        "label": "Contacts table",
        "paths": ["sites"],
        "kind": "contacts_table",
    },
    {
        "field": "sites.investigators",
        "label": "Investigators table",
        "paths": ["sites"],
        "kind": "investigators_table",
    },
]

# Keep branch-specific names available while sharing one field definition.
PROSPECTIVE_STARRED_FIELDS = STARRED_FILLOUT_FIELDS
AMBISPECTIVE_STARRED_FIELDS = STARRED_FILLOUT_FIELDS

# The retrospective Fillout has a smaller, independently confirmed set of 21
# starred fields. It asks for one facility name rather than the three site
# tables used by the prospective and ambispective forms.
RETROSPECTIVE_STARRED_FIELDS = [
    {"field": "study.title", "label": "Full title of the study", "paths": ["study.title"]},
    {
        "field": "study.background",
        "label": "Background and significance of the study",
        "paths": ["study.background"],
    },
    {
        "field": "objectives.primary",
        "label": "Key study objectives",
        "paths": ["objectives.primary"],
    },
    {
        "field": "study.unmet_need",
        "label": "Unmet medical need",
        "paths": ["study.unmet_need", "study.unmet_medical_need"],
    },
    {"field": "study.hypothesis", "label": "Study hypothesis", "paths": ["study.hypothesis"]},
    {
        "field": "design.study_design",
        "label": "Study design",
        "paths": ["design.study_design"],
    },
    {
        "field": "design.number_of_sites",
        "label": "Number of investigational sites",
        "paths": ["design.number_of_sites"],
        "kind": "standalone_site_count",
    },
    {
        "field": "endpoints.primary",
        "label": "Key endpoints",
        "paths": ["endpoints.primary"],
    },
    {
        "field": "procedures.assessments",
        "label": "Assessments conducted and their schedules",
        "paths": ["procedures.assessments", "procedures.visit_schedule"],
    },
    {
        "field": "population.inclusion_criteria",
        "label": "Inclusion criteria",
        "paths": ["population.inclusion_criteria"],
    },
    {
        "field": "population.exclusion_criteria",
        "label": "Exclusion criteria",
        "paths": ["population.exclusion_criteria"],
    },
    {
        "field": "population.sample_size",
        "label": "Sample size",
        "paths": ["population.sample_size"],
    },
    {
        "field": "population.sample_justification",
        "label": "Sample justification",
        "paths": ["population.sample_justification", "statistics.sample_size_justification"],
    },
    {
        "field": "statistics.analysis_plan",
        "label": "Statistical analysis plan",
        "paths": ["statistics.analysis_plan"],
    },
    {
        "field": "parties.irb.name",
        "label": "IRB or ethics committee name",
        "paths": ["parties.irb.name", "parties.ethics_committee.name"],
    },
    {
        "field": "parties.irb.address",
        "label": "IRB or ethics committee full address",
        "paths": [
            "parties.irb.address",
            "parties.irb.full_address",
            "parties.ethics_committee.address",
            "parties.ethics_committee.full_address",
        ],
    },
    {
        "field": "parties.sponsor.name",
        "label": "Sponsor or funding body name",
        "paths": ["parties.sponsor.name"],
    },
    {
        "field": "parties.sponsor.address",
        "label": "Sponsor or funding body full address",
        "paths": ["parties.sponsor.address"],
    },
    {
        "field": "sites.0.facility.name",
        "label": "Facility name",
        "paths": ["sites.0.facility.name"],
    },
    {
        "field": "parties.principal_investigator.name",
        "label": "Principal investigator name",
        "paths": ["parties.principal_investigator.name"],
    },
    {
        "field": "parties.principal_investigator.title",
        "label": "Principal investigator title or degree",
        "paths": ["parties.principal_investigator.title", "parties.principal_investigator.degree"],
    },
]

BRANCHES = {
    "prospective": {
        "canonical_study_type": "Prospective",
        "required_document_set": ["protocol_docx", "icf_docx", "xml"],
        "optional_document_set": ["short_docx"],
        "source_required_fields": STARRED_FILLOUT_FIELDS,
        "source_required_paths": [item["field"] for item in STARRED_FILLOUT_FIELDS],
        "required_paths": [
            "generated.protocol",
            "generated.icf",
            "regulatory.xml_profile",
        ],
    },
    "ambispective": {
        "canonical_study_type": "Ambispective",
        "required_document_set": ["protocol_docx", "icf_docx", "xml"],
        "optional_document_set": ["short_docx"],
        "source_required_fields": STARRED_FILLOUT_FIELDS,
        "source_required_paths": [item["field"] for item in STARRED_FILLOUT_FIELDS],
        "required_paths": [
            "generated.protocol",
            "generated.icf",
            "regulatory.xml_profile",
        ],
    },
    "retrospective": {
        "canonical_study_type": "Retrospective",
        "required_document_set": ["protocol_docx"],
        "optional_document_set": ["short_docx"],
        "source_required_fields": RETROSPECTIVE_STARRED_FIELDS,
        "source_required_paths": [item["field"] for item in RETROSPECTIVE_STARRED_FIELDS],
        "required_paths": [
            "generated.protocol",
        ],
    },
}

ALIASES = {
    "prospective": "prospective",
    "prospect": "prospective",
    "ambipective": "ambispective",
    "ambispective": "ambispective",
    "ambidirectional": "ambispective",
    "ambidirectional study": "ambispective",
    "retrospective": "retrospective",
    "retro": "retrospective",
}


def normalize_study_type(value: Any) -> str | None:
    if value is None:
        return None
    key = str(value).strip().lower().replace("-", " ")
    key = " ".join(key.split())
    return ALIASES.get(key)


def branch_for_study_type(value: Any) -> dict | None:
    normalized = normalize_study_type(value)
    if normalized is None:
        return None
    return BRANCHES[normalized]


def canonical_study_type(value: Any) -> str | None:
    branch = branch_for_study_type(value)
    return branch["canonical_study_type"] if branch else None


def default_document_set(value: Any) -> list[str]:
    branch = branch_for_study_type(value)
    return list(branch["required_document_set"]) if branch else []


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


def has_meaningful_value(data: dict, dotted_path: str) -> bool:
    value = get_path(data, dotted_path)
    if value is None:
        return False
    if value == "":
        return False
    if isinstance(value, (list, dict)) and not value:
        return False
    return True


def is_meaningful_value(value: Any) -> bool:
    """Use strict starred-field semantics: whitespace and empty containers are missing."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(is_meaningful_value(child) for child in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(is_meaningful_value(child) for child in value)
    return True


def _sites(reference: dict) -> list[dict]:
    value = reference.get("sites")
    if not isinstance(value, list):
        return []
    return [site for site in value if isinstance(site, dict)]


def _facility_rows(reference: dict) -> list[Any]:
    rows = []
    for site in _sites(reference):
        facility = site.get("facility")
        if is_meaningful_value(facility):
            rows.append(facility)
    return rows


def _contact_rows(reference: dict) -> list[Any]:
    rows = []
    for site in _sites(reference):
        for key in ("contact", "contacts"):
            value = site.get(key)
            if is_meaningful_value(value):
                rows.append(value)
    return rows


def _investigator_rows(reference: dict) -> list[Any]:
    rows = []
    for site in _sites(reference):
        for key in ("investigator", "investigators"):
            value = site.get(key)
            if is_meaningful_value(value):
                rows.append(value)
    return rows


def starred_requirement_value(reference: dict, requirement: dict) -> Any:
    kind = requirement.get("kind")
    if kind == "site_count":
        return get_path(reference, "design.number_of_sites")
    if kind == "facilities_table":
        return _facility_rows(reference)
    if kind == "contacts_table":
        return _contact_rows(reference)
    if kind == "investigators_table":
        return _investigator_rows(reference)
    for path in requirement.get("paths", []):
        value = get_path(reference, path)
        if is_meaningful_value(value):
            return value
    return None


def _candidate_value(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value:
        return value.get("value")
    return value


def _count_signature(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return str(int(value)) if float(value).is_integer() else str(value)
    rendered = str(value).strip().lower()
    words = {
        "zero": "0",
        "one": "1",
        "two": "2",
        "three": "3",
        "four": "4",
        "five": "5",
        "six": "6",
        "seven": "7",
        "eight": "8",
        "nine": "9",
        "ten": "10",
    }
    if rendered in words:
        return words[rendered]
    match = re.search(r"\d+(?:\.\d+)?", rendered)
    return match.group(0) if match else rendered or None


def _candidate_signature(value: Any, kind: str | None = None) -> str | None:
    value = _candidate_value(value)
    if not is_meaningful_value(value):
        return None
    if kind in {"site_count", "standalone_site_count"}:
        return _count_signature(value)
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def starred_candidate_values(reference: dict, requirement: dict) -> list[Any]:
    source = reference.get("source") if isinstance(reference.get("source"), dict) else {}
    candidate_map = source.get("field_candidates") if isinstance(source.get("field_candidates"), dict) else {}
    candidates: list[Any] = []
    for key in [requirement["field"], *requirement.get("paths", [])]:
        if key not in candidate_map:
            continue
        raw = candidate_map[key]
        candidates.extend(raw if isinstance(raw, list) else [raw])

    if requirement.get("kind") == "site_count":
        explicit = get_path(reference, "design.number_of_sites")
        if is_meaningful_value(explicit):
            candidates.append(explicit)
        facilities = _facility_rows(reference)
        if facilities:
            candidates.append(len(facilities))
    return candidates


def starred_distinct_candidate_count(reference: dict, requirement: dict) -> int:
    signatures = {
        signature
        for value in starred_candidate_values(reference, requirement)
        if (signature := _candidate_signature(value, requirement.get("kind"))) is not None
    }
    return len(signatures)


def starred_requirement_for_field(field: Any, requirements: list[dict] | None = None) -> dict | None:
    rendered = str(field or "").strip()
    if not rendered:
        return None
    for requirement in requirements or STARRED_FILLOUT_FIELDS:
        for candidate in [requirement["field"], *requirement.get("paths", [])]:
            if rendered == candidate or candidate.startswith(rendered + "."):
                return requirement
    return None


def starred_review_item_is_blocking(item: Any, requirements: list[dict] | None = None) -> bool:
    if not isinstance(item, dict):
        return False
    if not starred_requirement_for_field(item.get("field"), requirements):
        return False
    kind = str(item.get("kind") or item.get("type") or item.get("reason") or "").strip().lower()
    return kind in {"conflict", "multiple_inputs", "multiple_distinct_inputs"}


def active_template_rels(reference: dict, available_rels: list[str]) -> tuple[list[str], list[dict], list[dict]]:
    document_set = reference.get("meta", {}).get("document_set") or []
    if not document_set:
        return available_rels, [], []

    active = []
    warnings = []
    missing = []
    available = set(available_rels)

    for doc_key in document_set:
        rel = DOC_TEMPLATES.get(doc_key)
        if not rel:
            warnings.append(
                {
                    "field": "meta.document_set",
                    "issue": f"Unknown document key `{doc_key}` in document_set.",
                }
            )
            continue
        if rel in available:
            active.append(rel)
        else:
            missing.append(
                {
                    "field": "meta.document_set",
                    "issue": f"Document set requires `{doc_key}`, but `{rel}` is missing.",
                }
            )

    inactive = sorted(available - set(active))
    for rel in inactive:
        warnings.append(
            {
                "field": rel,
                "issue": "Template is present but not included in meta.document_set; it will not be rendered.",
            }
        )
    return active, missing, warnings


def validate_branch(reference: dict, available_rels: list[str]) -> tuple[list[dict], list[dict], list[str]]:
    missing = []
    warnings = []
    meta = reference.get("meta") or {}
    study_type = meta.get("study_type")
    branch = branch_for_study_type(study_type)

    if not branch:
        missing.append(
            {
                "field": "meta.study_type",
                "issue": "Study type must be Prospective, Ambispective, or Retrospective.",
            }
        )
        active, template_missing, template_warnings = active_template_rels(reference, available_rels)
        return missing + template_missing, warnings + template_warnings, active

    canonical = branch["canonical_study_type"]
    if study_type != canonical:
        warnings.append(
            {
                "field": "meta.study_type",
                "issue": f"Normalize study type to `{canonical}`.",
            }
        )

    document_set = meta.get("document_set") or []
    required_docs = set(branch["required_document_set"])
    optional_docs = set(branch.get("optional_document_set", []))
    document_docs = set(document_set)

    for doc_key in sorted(required_docs - document_docs):
        missing.append(
            {
                "field": "meta.document_set",
                "issue": f"{canonical} studies require `{doc_key}`.",
            }
        )

    for doc_key in sorted(document_docs - required_docs - optional_docs):
        warnings.append(
            {
                "field": "meta.document_set",
                "issue": f"`{doc_key}` is not part of the standard {canonical} branch.",
            }
        )

    if branch.get("source_required_fields"):
        for requirement in branch["source_required_fields"]:
            if starred_distinct_candidate_count(reference, requirement) > 1:
                missing.append(
                    {
                        "field": requirement["field"],
                        "issue": f"Conflicting inputs were found for starred {canonical.lower()} field `{requirement['label']}`.",
                    }
                )
            elif not is_meaningful_value(starred_requirement_value(reference, requirement)):
                missing.append(
                    {
                        "field": requirement["field"],
                        "issue": f"Missing starred {canonical.lower()} input: {requirement['label']}.",
                    }
                )
        existing_fields = {item.get("field") for item in missing}
        for item in reference.get("needs_review") or []:
            if not starred_review_item_is_blocking(item, branch["source_required_fields"]):
                continue
            requirement = starred_requirement_for_field(item.get("field"), branch["source_required_fields"])
            if requirement and requirement["field"] not in existing_fields:
                missing.append(
                    {
                        "field": requirement["field"],
                        "issue": str(item.get("issue") or "Conflicting inputs were found for this starred field."),
                    }
                )
                existing_fields.add(requirement["field"])

    for field in branch["required_paths"]:
        if not has_meaningful_value(reference, field):
            missing.append(
                {
                    "field": field,
                    "issue": f"Required for {canonical} studies.",
                }
            )

    active, template_missing, template_warnings = active_template_rels(reference, available_rels)
    missing.extend(template_missing)
    warnings.extend(template_warnings)
    return missing, warnings, active
