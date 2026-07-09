"""Study-type branch rules derived from the existing generation workflow."""

from __future__ import annotations

from typing import Any


DOC_TEMPLATES = {
    "protocol_docx": "templates/protocol.template.docx",
    "icf_docx": "templates/icf.template.docx",
    "short_docx": "templates/short.template.docx",
    "xml": "templates/study.template.xml",
    "main_docx": "templates/main.template.docx",
}

BRANCHES = {
    "prospective": {
        "canonical_study_type": "Prospective",
        "required_document_set": ["protocol_docx", "icf_docx", "xml"],
        "optional_document_set": ["short_docx"],
        "source_required_paths": [
            "meta.protocol_number",
            "meta.study_type",
            "study.title",
            "parties.sponsor.name",
            "parties.principal_investigator.name",
            "parties.principal_investigator.affiliation",
            "sites",
            "population.sample_size",
            "population.inclusion_criteria",
            "population.exclusion_criteria",
            "design.study_design",
            "objectives.primary",
            "endpoints.primary",
            "risks_benefits",
            "regulatory.prs.provider_study_id",
            "regulatory.prs.org_name",
            "regulatory.prs.overall_status",
            "regulatory.prs.irb_approval_status",
            "regulatory.prs.study_uid",
            "parties.overall_contact",
        ],
        "required_paths": [
            "meta.protocol_number",
            "meta.study_type",
            "study.title",
            "parties.sponsor.name",
            "parties.principal_investigator.name",
            "parties.principal_investigator.affiliation",
            "sites",
            "population.inclusion_criteria",
            "population.exclusion_criteria",
            "design.study_design",
            "objectives.primary",
            "endpoints.primary",
            "risks_benefits",
            "generated.protocol",
            "generated.icf",
            "regulatory.xml_profile",
            "regulatory.prs.provider_study_id",
            "regulatory.prs.org_name",
            "regulatory.prs.overall_status",
            "regulatory.prs.irb_approval_status",
            "regulatory.prs.study_uid",
            "parties.overall_contact",
        ],
    },
    "ambispective": {
        "canonical_study_type": "Ambispective",
        "required_document_set": ["protocol_docx", "icf_docx", "xml"],
        "optional_document_set": ["short_docx"],
        "source_required_paths": [
            "meta.protocol_number",
            "meta.study_type",
            "study.title",
            "parties.sponsor.name",
            "parties.principal_investigator.name",
            "parties.principal_investigator.affiliation",
            "sites",
            "population.sample_size",
            "population.inclusion_criteria",
            "population.exclusion_criteria",
            "design.study_design",
            "objectives.primary",
            "endpoints.primary",
            "risks_benefits",
            "regulatory.prs.provider_study_id",
            "regulatory.prs.org_name",
            "regulatory.prs.overall_status",
            "regulatory.prs.irb_approval_status",
            "regulatory.prs.study_uid",
            "parties.overall_contact",
        ],
        "required_paths": [
            "meta.protocol_number",
            "meta.study_type",
            "study.title",
            "parties.sponsor.name",
            "parties.principal_investigator.name",
            "parties.principal_investigator.affiliation",
            "sites",
            "population.inclusion_criteria",
            "population.exclusion_criteria",
            "design.study_design",
            "objectives.primary",
            "endpoints.primary",
            "risks_benefits",
            "generated.protocol",
            "generated.icf",
            "regulatory.xml_profile",
            "regulatory.prs.provider_study_id",
            "regulatory.prs.org_name",
            "regulatory.prs.overall_status",
            "regulatory.prs.irb_approval_status",
            "regulatory.prs.study_uid",
            "parties.overall_contact",
        ],
    },
    "retrospective": {
        "canonical_study_type": "Retrospective",
        "required_document_set": ["protocol_docx"],
        "optional_document_set": ["short_docx"],
        "source_required_paths": [
            "meta.protocol_number",
            "meta.study_type",
            "study.title",
            "parties.sponsor.name",
            "parties.principal_investigator.name",
            "sites",
            "population.sample_size",
            "population.inclusion_criteria",
            "population.exclusion_criteria",
            "design.study_design",
            "objectives.primary",
            "endpoints.primary",
        ],
        "required_paths": [
            "meta.protocol_number",
            "meta.study_type",
            "study.title",
            "parties.sponsor.name",
            "parties.principal_investigator.name",
            "sites",
            "population.inclusion_criteria",
            "population.exclusion_criteria",
            "design.study_design",
            "objectives.primary",
            "endpoints.primary",
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
