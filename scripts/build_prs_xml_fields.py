#!/usr/bin/env python3
"""Build ClinicalTrials.gov PRS XML fields from the reviewed study reference."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from study_type_branches import branch_for_study_type, starred_requirement_for_field


STANDARD_REFERENCE = "reference/study.reference.json"
STANDARD_TEMPLATE = "templates/study.template.xml"
TOKEN_RE = re.compile(r"\{([A-Za-z0-9_.\-\[\]\(\)&]+)\}")
EMPTY_LITERALS = {"none", "n/a", "na", "not applicable", "http://", "https://"}


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def display_path(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.name


def get_path(data: Any, dotted_path: str, default: Any = None) -> Any:
    current = data
    for part in dotted_path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            current = current[index] if index < len(current) else default
        else:
            return default
        if current is None:
            return default
    return current


def text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(item for item in (clean(item) for item in value) if item)
    if isinstance(value, dict):
        for key in (
            "text",
            "name",
            "title",
            "label",
            "measure",
            "outcome_measure",
            "description",
            "Article",
        ):
            if value.get(key) is not None:
                return text(value[key])
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def clean(value: Any) -> str:
    rendered = text(value).replace("\u00a0", " ").strip()
    return "" if rendered.lower() in EMPTY_LITERALS else rendered


def first_text(*values: Any) -> str:
    for value in values:
        rendered = clean(value)
        if rendered:
            return rendered
    return ""


def first_path(reference: dict, *paths: str) -> str:
    return first_text(*(get_path(reference, path) for path in paths))


def split_name(full_name: str) -> tuple[str, str, str]:
    name = full_name.split(",", 1)[0].strip()
    parts = [part for part in re.split(r"\s+", name) if part]
    if not parts:
        return "", "", ""
    if len(parts) == 1:
        return parts[0], "", ""
    if len(parts) == 2:
        return parts[0], "", parts[1]
    return parts[0], " ".join(parts[1:-1]), parts[-1]


def boolish(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    rendered = clean(value).lower()
    if rendered in {"yes", "true", "1", "y"}:
        return True
    if rendered in {"no", "false", "0", "n"}:
        return False
    return None


def yes_no(value: Any, default: str = "") -> str:
    parsed = boolish(value)
    if parsed is None:
        return default
    return "Yes" if parsed else "No"


def normalize_country(value: Any) -> str:
    rendered = clean(value)
    if rendered.upper() == "USA":
        return "United States"
    return rendered


def normalize_prs_approval_status(value: Any) -> str:
    rendered = clean(value)
    lower = rendered.lower()
    if not rendered:
        return ""
    if "not yet submitted" in lower:
        return "Pending"
    if "pending" in lower:
        return "Pending"
    if lower == "submitted":
        return "Pending"
    if "exempt" in lower:
        return "Exempt"
    if lower in {"approved", "not approved"}:
        return rendered[:1].upper() + rendered[1:]
    return rendered


def normalize_sampling_method(value: Any) -> str:
    rendered = clean(value)
    lower = rendered.lower()
    if not rendered:
        return "Non-Probability Sample"
    if "non-probability" in lower or ("non" in lower and "probability" in lower):
        return "Non-Probability Sample"
    if "probability" in lower:
        return "Probability Sample"
    return rendered


def normalize_prs_study_type(reference: dict, intervention_items: list[dict]) -> str:
    explicit = first_path(reference, "regulatory.prs.study_type", "regulatory.study_type")
    if explicit:
        return explicit[:1].upper() + explicit[1:].lower()
    observational_design = first_path(reference, "regulatory.prs.observational_study_design")
    if observational_design.lower() in {"not applicable", "n/a", "none"}:
        return "Interventional"
    if intervention_items:
        return "Interventional"
    return "Observational"


def infer_allocation(reference: dict) -> str:
    explicit = first_path(reference, "regulatory.prs.allocation", "design.allocation")
    if explicit:
        return explicit
    design = " ".join(
        clean(value)
        for value in [
            first_path(reference, "design.study_design"),
            first_path(reference, "design.randomization"),
        ]
        if clean(value)
    ).lower()
    return "Randomized" if "random" in design else "Non-Randomized"


def infer_intervention_model(reference: dict, arm_items: list[dict]) -> str:
    explicit = first_path(reference, "regulatory.prs.intervention_model", "design.intervention_model")
    if explicit:
        return explicit
    return "Parallel Assignment" if len(arm_items) > 1 else "Single Group Assignment"


def infer_primary_purpose(reference: dict) -> str:
    return first_path(reference, "regulatory.prs.primary_purpose", "design.primary_purpose") or "Treatment"


def infer_masking(reference: dict) -> str:
    explicit = first_path(reference, "regulatory.prs.masking", "design.masking_type")
    if explicit:
        return explicit
    masking = first_path(reference, "design.masking", "design.blinding")
    if not masking:
        return "None"
    lower = masking.lower()
    if "not masked" in lower or "open label" in lower or "open-label" in lower:
        return "None"
    return "Single"


def first_number_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            return str(int(value)) if value.is_integer() else str(value)
        rendered = clean(value)
        if not rendered:
            continue
        match = re.search(r"\d[\d,]*(?:\.\d+)?", rendered)
        if match:
            number = match.group(0).replace(",", "")
            return number[:-2] if number.endswith(".0") else number
    return ""


def normalize_age(value: Any) -> str:
    rendered = clean(value)
    if not rendered:
        return ""
    match = re.search(r"\d[\d,]*(?:\.\d+)?", rendered)
    if not match:
        return rendered
    number = match.group(0).replace(",", "")
    number = number[:-2] if number.endswith(".0") else number
    lower = rendered.lower()
    units = ""
    if "year" in lower or re.search(r"\byr", lower):
        units = "Years"
    elif "month" in lower or re.search(r"\bmo", lower):
        units = "Months"
    elif "week" in lower or re.search(r"\bwk", lower):
        units = "Weeks"
    elif "day" in lower:
        units = "Days"
    elif "hour" in lower:
        units = "Hours"
    elif "minute" in lower:
        units = "Minutes"
    return f"{number} {units}" if units else rendered


def normalize_prs_date(value: Any) -> str:
    rendered = clean(value)
    if not rendered:
        return ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", rendered):
        return rendered
    candidate = re.sub(r"\b(\d{1,2})(st|nd|rd|th)\b", r"\1", rendered, flags=re.IGNORECASE)
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(candidate, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    for fmt in ("%B %Y", "%b %Y"):
        try:
            datetime.strptime(candidate, fmt)
            return ""
        except ValueError:
            continue
    return rendered


def normalize_verification_date(value: Any) -> str:
    rendered = clean(value)
    if not rendered:
        return ""
    if re.fullmatch(r"\d{4}-\d{2}", rendered):
        return rendered
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", rendered):
        return rendered[:7]
    candidate = re.sub(r"\b(\d{1,2})(st|nd|rd|th)\b", r"\1", rendered, flags=re.IGNORECASE)
    for fmt in ("%B %Y", "%b %Y", "%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(candidate, fmt).strftime("%Y-%m")
        except ValueError:
            continue
    return rendered


def normalize_group_count(reference: dict, arm_items: list[dict], intervention_items: list[dict]) -> str:
    explicit = first_number_text(
        get_path(reference, "regulatory.prs.number_of_groups"),
        get_path(reference, "statistics.number_of_groups"),
    )
    if explicit:
        return explicit
    groups = get_path(reference, "statistics.groups")
    if isinstance(groups, list) and groups:
        return str(len(groups))
    grouped_text = first_number_text(groups)
    if grouped_text:
        return grouped_text
    return str(len(arm_items) or len(intervention_items) or 1)


def parse_jsonish(value: Any) -> Any:
    if isinstance(value, str):
        candidate = value.strip()
        if candidate.startswith("[") or candidate.startswith("{"):
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                return value
    return value


def as_list(value: Any) -> list[Any]:
    value = parse_jsonish(value)
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    rendered = clean(value)
    return [{"text": rendered}] if rendered else []


def criteria_block(reference: dict, template_fields: dict) -> str:
    explicit = first_path(reference, "regulatory.prs.eligibility_criteria")
    if explicit:
        return explicit
    inclusion = first_text(template_fields.get("AI_inclusionCriteria"), get_path(reference, "population.inclusion_criteria"))
    exclusion = first_text(template_fields.get("AI_exclusionCriteria"), get_path(reference, "population.exclusion_criteria"))
    chunks = []
    if inclusion:
        chunks.append("Inclusion Criteria:\n" + inclusion)
    if exclusion:
        chunks.append("Exclusion Criteria:\n" + exclusion)
    return "\n\n".join(chunks)


def endpoint_items(reference: dict, template_fields: dict, kind: str) -> list[dict]:
    paths_by_kind = {
        "primary": ["generated.xml.primary_outcome", "endpoints.primary"],
        "secondary": ["generated.xml.secondary_outcome", "endpoints.secondary"],
        "other": ["generated.xml.other_outcome", "generated.xml.other_outcomes", "endpoints.other", "endpoints.exploratory"],
    }
    values = [get_path(reference, path) for path in paths_by_kind[kind]]
    if kind == "primary":
        values.append(template_fields.get("primaryOutcome"))
    elif kind == "secondary":
        values.append(template_fields.get("secondaryOutcome"))

    raw_items: list[Any] = []
    for value in values:
        raw_items = as_list(value)
        if raw_items:
            break

    items = []
    for item in raw_items:
        if not isinstance(item, dict):
            item = {"text": clean(item)}
        description = item.get("outcome_description")
        if isinstance(description, dict):
            description_text = first_text(description.get("textblock"), description.get("text"))
        else:
            description_text = first_text(description, item.get("description"), item.get("text"))
        items.append(
            {
                "measure": first_text(item.get("outcome_measure"), item.get("measure"), item.get("text")),
                "time_frame": first_text(item.get("outcome_time_frame"), item.get("time_frame"), item.get("timeframe")),
                "uid": first_text(item.get("uid"), item.get("outcome_uid")),
                "description": description_text,
            }
        )
    return [item for item in items if item["measure"] or item["time_frame"] or item["description"]]


def arms(reference: dict) -> list[dict]:
    raw_arms = as_list(get_path(reference, "design.arms"))
    normalized = []
    for item in raw_arms:
        if not isinstance(item, dict):
            item = {"label": clean(item)}
        normalized.append(
            {
                "label": first_text(item.get("label"), item.get("arm_group_label"), item.get("name")),
                "type": first_text(item.get("type"), item.get("arm_type")),
                "description": first_text(item.get("description"), item.get("arm_group_description")),
                "intervention_type": first_text(item.get("intervention_type"), item.get("intervention", {}).get("type") if isinstance(item.get("intervention"), dict) else ""),
                "intervention_name": first_text(item.get("intervention_name"), item.get("intervention", {}).get("name") if isinstance(item.get("intervention"), dict) else ""),
                "intervention_description": first_text(item.get("intervention_description"), item.get("description")),
            }
        )
    return [item for item in normalized if item["label"] or item["intervention_name"]]


def interventions(reference: dict, arm_items: list[dict]) -> list[dict]:
    raw_interventions = as_list(get_path(reference, "design.interventions"))
    if raw_interventions:
        items = []
        for item in raw_interventions:
            if not isinstance(item, dict):
                item = {"name": clean(item)}
            items.append(
                {
                    "type": first_text(item.get("type"), item.get("intervention_type"), first_path(reference, "design.intervention_type")),
                    "name": first_text(item.get("name"), item.get("intervention_name")),
                    "description": first_text(item.get("description"), item.get("intervention_description")),
                    "arm_group_label": first_text(item.get("arm_group_label"), item.get("arm")),
                }
            )
        return [item for item in items if item["name"] or item["arm_group_label"]]

    default_type = first_path(reference, "design.intervention_type", "regulatory.prs.intervention_type")
    return [
        {
            "type": first_text(item["intervention_type"], default_type),
            "name": first_text(item["intervention_name"], item["label"]),
            "description": first_text(item["intervention_description"], item["description"]),
            "arm_group_label": item["label"],
        }
        for item in arm_items
    ]


def first_site(reference: dict) -> dict:
    sites = reference.get("sites")
    if isinstance(sites, list) and sites and isinstance(sites[0], dict):
        return sites[0]
    return {}


def contact(reference: dict, site: dict, key: str) -> dict:
    paths = {
        "overall": ["parties.overall_contact", "parties.study_contact", "parties.study_coordinator"],
        "overall_backup": ["parties.overall_contact_backup", "parties.study_contact_backup"],
        "location": ["sites.0.contact", "parties.study_coordinator"],
        "location_backup": ["sites.0.contact_backup", "parties.study_contact_backup"],
    }
    for path in paths[key]:
        value = get_path(reference, path)
        if isinstance(value, dict):
            return value
    if key == "location" and isinstance(site.get("contact"), dict):
        return site["contact"]
    if key == "location_backup" and isinstance(site.get("contact_backup"), dict):
        return site["contact_backup"]
    return {}


def contact_fields(prefix: str, value: dict) -> dict:
    first, middle, last = split_name(first_text(value.get("name")))
    return {
        f"{prefix}FirstName": first_text(value.get("first_name"), value.get("first"), first),
        f"{prefix}MiddleName": first_text(value.get("middle_name"), value.get("middle"), middle),
        f"{prefix}LastName": first_text(value.get("last_name"), value.get("last"), last),
        f"{prefix}Degrees": first_text(value.get("degrees"), value.get("title")),
        f"{prefix}Phone": first_text(value.get("phone"), value.get("business_phone"), value.get("office_phone")),
        f"{prefix}PhoneExt": first_text(value.get("phone_ext"), value.get("ext")),
        f"{prefix}Email": first_text(value.get("email")),
    }


def placeholders(template_path: Path) -> set[str]:
    if not template_path.exists():
        return set()
    return set(TOKEN_RE.findall(template_path.read_text(encoding="utf-8")))


def add_review_item(reference: dict, field: str, issue: str) -> None:
    items = reference.get("needs_review")
    if not isinstance(items, list):
        items = []
    for item in items:
        if isinstance(item, dict) and item.get("field") == field and item.get("issue") == issue:
            reference["needs_review"] = items
            return
    items.append({"field": field, "issue": issue, "source": "prs_xml_mapper"})
    reference["needs_review"] = items


def blocking_missing_items(reference: dict, missing: list[dict]) -> list[dict]:
    meta = reference.get("meta") if isinstance(reference.get("meta"), dict) else {}
    branch = branch_for_study_type(meta.get("study_type"))
    if not branch or not branch.get("source_required_fields"):
        return missing
    requirements = branch["source_required_fields"]
    return [item for item in missing if starred_requirement_for_field(item.get("field"), requirements)]


def add_indexed_outcome_fields(fields: dict, prefix: str, item: dict) -> None:
    fields[f"{prefix}Measure"] = item["measure"]
    fields[f"{prefix}OutcomeMeasure"] = item["measure"]
    fields[f"{prefix}TimeFrame"] = item["time_frame"]
    fields[f"{prefix}OutcomeTimeFrame"] = item["time_frame"]
    fields[f"{prefix}Uid"] = item["uid"]
    fields[f"{prefix}Description"] = item["description"]


def build_fields(reference: dict, template_path: Path) -> tuple[dict, list[dict]]:
    existing = reference.get("template_fields") if isinstance(reference.get("template_fields"), dict) else {}
    fields = {name: "" for name in placeholders(template_path)}
    fields.update({key: "" for key in existing if key.startswith("__prs_")})

    site = first_site(reference)
    facility = site.get("facility") if isinstance(site.get("facility"), dict) else {}
    facility_address = facility.get("address") if isinstance(facility.get("address"), dict) else {}
    pi = get_path(reference, "parties.principal_investigator") or {}
    if not isinstance(pi, dict):
        pi = {"name": clean(pi)}
    pi_first, pi_middle, pi_last = split_name(first_text(pi.get("name")))
    regulatory = reference.get("regulatory") if isinstance(reference.get("regulatory"), dict) else {}
    study_type = first_path(reference, "meta.study_type")
    arm_items = arms(reference)
    intervention_items = interventions(reference, arm_items)
    prs_study_type = normalize_prs_study_type(reference, intervention_items)
    interventional_design = prs_study_type == "Interventional"
    primary_items = endpoint_items(reference, existing, "primary")
    secondary_items = endpoint_items(reference, existing, "secondary")
    other_items = endpoint_items(reference, existing, "other")
    outcome_uid = first_path(reference, "regulatory.prs.outcome_uid", "regulatory.prs.study_uid", "regulatory.study_uid")
    study_uid = first_path(reference, "regulatory.prs.study_uid", "regulatory.study_uid", "regulatory.prs.outcome_uid")
    for item in primary_items + secondary_items + other_items:
        if outcome_uid:
            item["uid"] = outcome_uid

    explicit_device = boolish(get_path(reference, "regulatory.fda_regulated_device"))
    device_regulated = explicit_device is True or any(clean(item.get("type")).lower() == "device" for item in intervention_items)
    explicit_drug = boolish(get_path(reference, "regulatory.fda_regulated_drug"))
    fda_drug = "No" if device_regulated else ("Yes" if explicit_drug is not False else "No")
    fda_device = "Yes" if device_regulated else "No"

    overall_status = first_path(reference, "regulatory.prs.overall_status", "regulatory.overall_status", "study.status")
    irb_status = normalize_prs_approval_status(
        first_path(reference, "regulatory.prs.irb_approval_status", "regulatory.irb_approval_status", "parties.irb.approval_status")
    )
    last_follow_up = first_path(reference, "regulatory.prs.last_follow_up_date", "procedures.last_follow_up_date", "lastFollowUpDate")
    last_follow_up_type = first_path(reference, "regulatory.prs.last_follow_up_date_type", "procedures.last_follow_up_date_type", "lastFollowUpDateType")
    verification_date = normalize_verification_date(
        first_path(reference, "regulatory.prs.verification_date", "regulatory.verification_date")
    ) or datetime.now(timezone.utc).strftime("%Y-%m")

    fields.update(
        {
            "__xml_profile": "clinicaltrials-prs",
            "providerStudyId": first_path(reference, "regulatory.prs.provider_study_id", "regulatory.provider_study_id"),
            "orgName": first_path(reference, "regulatory.prs.org_name", "regulatory.org_name"),
            "protocolNumber": first_path(reference, "meta.protocol_number") or text(existing.get("protocolNumber")),
            "providerName": first_path(reference, "regulatory.prs.provider_name", "regulatory.provider_name") or "NLM_DES",
            "overallStatus": overall_status,
            "fdaRegulatedDrug": first_path(reference, "regulatory.prs.fda_regulated_drug") or fda_drug,
            "fdaRegulatedDevice": first_path(reference, "regulatory.prs.fda_regulated_device") or fda_device,
            "postPriorToApproval": first_path(reference, "regulatory.prs.post_prior_to_approval") or "No",
            "exportedFromUs": first_path(reference, "regulatory.prs.exported_from_us") or "Yes",
            "pediatricPostmarketSurveillance": first_path(reference, "regulatory.prs.pediatric_postmarket_surveillance") or "No",
            "irbApprovalNumber": first_path(reference, "parties.irb.approval_number", "regulatory.prs.irb_approval_number") or first_path(reference, "meta.protocol_number"),
            "irbName": first_path(reference, "parties.irb.name"),
            "irbAffiliation": first_path(reference, "parties.irb.affiliation", "regulatory.prs.irb_affiliation"),
            "irbFullAddress": first_path(reference, "parties.irb.full_address", "parties.irb.address"),
            "irbPhone": first_path(reference, "parties.irb.phone"),
            "irbPhoneExt": first_path(reference, "parties.irb.phone_ext", "parties.irb.ext"),
            "irbEmail": first_path(reference, "parties.irb.email"),
            "irbApprovalStatus": irb_status,
            "irbExt": first_path(reference, "parties.irb.ext"),
            "hasDmc": first_path(reference, "regulatory.prs.has_dmc", "regulatory.has_dmc") or "No",
            "exportFromUs": first_path(reference, "regulatory.prs.export_from_us") or "Yes",
            "leadSponsorAgency": first_path(reference, "regulatory.prs.lead_sponsor_agency", "parties.sponsor.name"),
            "collaboratorAgency": first_path(reference, "regulatory.prs.collaborator_agency", "parties.collaborator.name"),
            "responsiblePartyNameTitle": first_path(reference, "parties.responsible_party.name_title"),
            "responsiblePartyOrganization": first_path(reference, "parties.responsible_party.organization"),
            "responsiblePartyEmail": first_path(reference, "parties.responsible_party.email"),
            "responsiblePartyPhone": first_path(reference, "parties.responsible_party.phone"),
            "responsiblePartyPhoneExt": first_path(reference, "parties.responsible_party.phone_ext"),
            "responsiblePartyType": first_path(reference, "parties.responsible_party.type", "regulatory.prs.responsible_party_type") or "Sponsor",
            "responsiblePartyInvestigatorUsername": first_path(reference, "parties.responsible_party.investigator_username"),
            "responsiblePartyInvestigatorTitle": first_path(reference, "parties.responsible_party.investigator_title", "parties.principal_investigator.title"),
            "responsiblePartyInvestigatorAffiliation": first_path(reference, "parties.responsible_party.investigator_affiliation", "parties.principal_investigator.affiliation"),
            "isINDStudy": first_path(reference, "regulatory.prs.is_ind_study") or "No",
            "isIndStudy": first_path(reference, "regulatory.prs.is_ind_study") or "No",
            "briefTitle": first_path(reference, "study.short_title") or first_text(existing.get("AI_shortTitle")),
            "officialTitle": first_path(reference, "study.title"),
            "briefSummary": first_path(reference, "generated.xml.brief_summary", "generated.protocol.study_design") or first_text(existing.get("AI_studyDesignLong")),
            "detailedDescription": first_path(reference, "generated.xml.detailed_description", "study.background"),
            "eligibilityCriteria": criteria_block(reference, existing),
            "eligibilityGender": first_path(reference, "population.gender", "population.sex") or "All",
            "healthyVolunteers": first_path(reference, "population.healthy_volunteers", "regulatory.prs.healthy_volunteers") or "No",
            "samplingMethod": normalize_sampling_method(first_path(reference, "design.sampling_method") or first_text(existing.get("samplingMethod"))),
            "genderBased": first_path(reference, "population.gender_based"),
            "studyPopulation": first_path(reference, "population.study_population") or first_text(existing.get("AI_populationShort")),
            "genderDescription": first_path(reference, "population.gender_description"),
            "minimumAge": normalize_age(first_path(reference, "population.minimum_age") or first_text(existing.get("minimumAge"))),
            "maximumAge": normalize_age(first_path(reference, "population.maximum_age") or first_text(existing.get("maximumAge"))),
            "enrollment": first_number_text(first_path(reference, "statistics.enrollment"), first_text(existing.get("enrollment"), get_path(reference, "population.sample_size"))),
            "startDate": normalize_prs_date(first_path(reference, "regulatory.prs.start_date", "procedures.start_date") or first_text(existing.get("startDate"))),
            "endDate": normalize_prs_date(first_path(reference, "regulatory.prs.end_date", "procedures.end_date") or first_text(existing.get("endDate"))),
            "lastFollowUpDate": normalize_prs_date(last_follow_up),
            "verificationDate": verification_date,
            "expandedAccessStatus": first_path(reference, "regulatory.prs.expanded_access_status"),
            "acronym": first_path(reference, "study.acronym"),
            "whyStopped": first_path(reference, "regulatory.prs.why_stopped"),
            "lastFollowUpDateType": last_follow_up_type,
            "enrollmentType": first_path(reference, "regulatory.prs.enrollment_type") or ("Actual" if overall_status.lower() == "completed" else "Anticipated"),
            "isFDARegulated": first_path(reference, "regulatory.prs.is_fda_regulated_legacy"),
            "isFdaRegulated": first_path(reference, "regulatory.prs.is_fda_regulated"),
            "isSection801": first_path(reference, "regulatory.prs.is_section_801_legacy"),
            "isSection801SnakeCase": first_path(reference, "regulatory.prs.is_section_801"),
            "delayedPosting": first_path(reference, "regulatory.prs.delayed_posting") or "No",
            "primaryCompletionDate": normalize_prs_date(first_path(reference, "regulatory.prs.primary_completion_date", "procedures.primary_completion_date") or first_text(existing.get("primaryCompleteDate"))),
            "primaryCompletionDateType": first_path(reference, "regulatory.prs.primary_completion_date_type") or ("Actual" if overall_status.lower() == "completed" else "Anticipated"),
            "startDateType": first_path(reference, "regulatory.prs.start_date_type") or ("Actual" if overall_status.lower() == "completed" else "Anticipated"),
            "studyType": prs_study_type,
            "interventionalDesign": {
                "allocation": infer_allocation(reference),
                "interventionModel": infer_intervention_model(reference, arm_items),
                "interventionModelDescription": first_path(reference, "regulatory.prs.intervention_model_description", "design.intervention_model_description"),
                "primaryPurpose": infer_primary_purpose(reference),
                "masking": infer_masking(reference),
                "maskingDescription": first_path(reference, "regulatory.prs.masking_description", "design.masking"),
                "numberOfArms": first_number_text(first_path(reference, "regulatory.prs.number_of_arms"), len(arm_items) or len(intervention_items) or 1),
            }
            if interventional_design
            else [],
            "observationalDesign": [] if interventional_design else {"observationalStudyDesign": first_path(reference, "regulatory.prs.observational_study_design") or "Cohort"},
            "allocation": infer_allocation(reference),
            "interventionModel": infer_intervention_model(reference, arm_items),
            "interventionModelDescription": first_path(reference, "regulatory.prs.intervention_model_description", "design.intervention_model_description"),
            "primaryPurpose": infer_primary_purpose(reference),
            "masking": infer_masking(reference),
            "maskingDescription": first_path(reference, "regulatory.prs.masking_description", "design.masking"),
            "numberOfArms": first_number_text(first_path(reference, "regulatory.prs.number_of_arms"), len(arm_items) or len(intervention_items) or 1),
            "observationalStudyDesign": first_path(reference, "regulatory.prs.observational_study_design") or "Cohort",
            "biospecimenRetention": first_path(reference, "regulatory.prs.biospecimen_retention") or "None Retained",
            "studyTiming": first_path(reference, "regulatory.prs.study_timing") or study_type,
            "targetDurationQuantity": first_path(reference, "regulatory.prs.target_duration_quantity"),
            "targetDurationUnits": first_path(reference, "regulatory.prs.target_duration_units"),
            "patientRegistry": first_path(reference, "regulatory.prs.patient_registry"),
            "numberOfGroups": normalize_group_count(reference, arm_items, intervention_items),
            "biospecimenDescription": first_path(reference, "regulatory.prs.biospecimen_description"),
            "sharingIPD": first_path(reference, "regulatory.prs.sharing_ipd") or "No",
            "sharingIpd": first_path(reference, "regulatory.prs.sharing_ipd") or "No",
            "ipdDescriptionLegacy": first_path(reference, "regulatory.prs.ipd_description_legacy"),
            "ipdSharingProtocol": first_path(reference, "regulatory.prs.ipd_sharing_protocol"),
            "ipdSharingSAP": first_path(reference, "regulatory.prs.ipd_sharing_sap"),
            "ipdSharingICF": first_path(reference, "regulatory.prs.ipd_sharing_icf"),
            "ipdSharingCSR": first_path(reference, "regulatory.prs.ipd_sharing_csr"),
            "ipdSharingAnalyticCode": first_path(reference, "regulatory.prs.ipd_sharing_analytic_code"),
            "ipdSharingTimeFrame": first_path(reference, "regulatory.prs.ipd_sharing_time_frame"),
            "ipdSharingAccessCriteria": first_path(reference, "regulatory.prs.ipd_sharing_access_criteria"),
            "ipdSharingURL": first_path(reference, "regulatory.prs.ipd_sharing_url"),
            "ipdUrl": first_path(reference, "regulatory.prs.ipd_url"),
            "ipdInfoTypeProtocol": first_path(reference, "regulatory.prs.ipd_info_type_protocol"),
            "ipdInfoTypeSap": first_path(reference, "regulatory.prs.ipd_info_type_sap"),
            "ipdInfoTypeIcf": first_path(reference, "regulatory.prs.ipd_info_type_icf"),
            "ipdInfoTypeCsr": first_path(reference, "regulatory.prs.ipd_info_type_csr"),
            "ipdInfoTypeAnalyticCode": first_path(reference, "regulatory.prs.ipd_info_type_analytic_code"),
            "ipdDescription": first_path(reference, "regulatory.prs.ipd_description"),
            "ipdTimeFrame": first_path(reference, "regulatory.prs.ipd_time_frame"),
            "ipdAccessCriteria": first_path(reference, "regulatory.prs.ipd_access_criteria"),
            "overallOfficialFirstName": first_text(pi.get("first_name"), pi_first),
            "overallOfficialMiddleName": first_text(pi.get("middle_name"), pi_middle),
            "overallOfficialLastName": first_text(pi.get("last_name"), pi_last),
            "overallOfficialDegrees": first_text(pi.get("degrees"), pi.get("title")),
            "overallOfficialRole": first_path(reference, "parties.principal_investigator.role") or "Principal Investigator",
            "overallOfficialAffiliation": first_path(reference, "parties.principal_investigator.affiliation", "parties.sponsor.name"),
            "locationStatus": first_text(site.get("status")) or overall_status,
            "facilityName": first_text(facility.get("name")),
            "facilityCity": first_text(facility_address.get("city")),
            "facilityState": first_text(facility_address.get("state")),
            "facilityCountry": normalize_country(facility_address.get("country")) or "United States",
            "facilityZip": first_text(facility_address.get("zip")),
            "locationInvestigatorFirstName": first_text(pi.get("first_name"), pi_first),
            "locationInvestigatorMiddleName": first_text(pi.get("middle_name"), pi_middle),
            "locationInvestigatorLastName": first_text(pi.get("last_name"), pi_last),
            "locationInvestigatorDegrees": first_text(pi.get("degrees"), pi.get("title")),
            "locationInvestigatorRole": first_path(reference, "parties.principal_investigator.role") or "Principal Investigator",
            "condition": first_path(reference, "study.condition"),
            "studyUid": study_uid,
            "nctId": first_path(reference, "regulatory.prs.nct_id", "regulatory.nct_id"),
        }
    )

    fields.update(contact_fields("overallContact", contact(reference, site, "overall")))
    fields.update(contact_fields("overallContactBackup", contact(reference, site, "overall_backup")))
    fields.update(contact_fields("locationContact", contact(reference, site, "location")))
    fields.update(contact_fields("locationContactBackup", contact(reference, site, "location_backup")))

    for index, item in enumerate(intervention_items, start=1):
        fields[f"intervention{index}Type"] = item["type"]
        fields[f"intervention{index}InterventionType"] = item["type"]
        fields[f"intervention{index}Name"] = item["name"]
        fields[f"intervention{index}InterventionName"] = item["name"]
        fields[f"intervention{index}Description"] = item["description"]
        fields[f"intervention{index}ArmGroupLabel"] = item["arm_group_label"]
    for index, item in enumerate(arm_items, start=1):
        fields[f"armGroup{index}Label"] = item["label"]
        fields[f"armGroup{index}ArmGroupLabel"] = item["label"]
        fields[f"armGroup{index}Type"] = item["type"]
        fields[f"armGroup{index}Description"] = item["description"]
    for index, item in enumerate(primary_items, start=1):
        prefix = "primaryOutcome" if index == 1 else f"primaryOutcome{index}"
        add_indexed_outcome_fields(fields, prefix, item)
    for index, item in enumerate(secondary_items, start=1):
        add_indexed_outcome_fields(fields, f"secondaryOutcome{index}", item)
    for index, item in enumerate(other_items, start=1):
        add_indexed_outcome_fields(fields, f"otherOutcome{index}", item)

    counts = {
        "intervention": len(intervention_items),
        "arm_group": len(arm_items),
        "primary_outcome": len(primary_items),
        "secondary_outcome": len(secondary_items),
        "other_outcome": len(other_items),
    }
    fields["__prs_counts"] = counts
    fields["__prs_template"] = "clinicaltrials_prs_full_placeholder_template.xml"

    missing: list[dict] = []

    def require(field: str, value: Any, issue: str) -> None:
        if not clean(value):
            missing.append({"field": field, "issue": issue})

    require("regulatory.prs.provider_study_id", fields.get("providerStudyId"), "PRS provider study ID is required for ClinicalTrials.gov XML.")
    require("regulatory.prs.org_name", fields.get("orgName"), "PRS org_name must come from the source/client correction.")
    require("regulatory.prs.overall_status", fields.get("overallStatus"), "overall_status must follow the reviewed source status.")
    require("regulatory.prs.irb_approval_status", fields.get("irbApprovalStatus"), "IRB approval status must come from the source/client correction.")
    require("parties.overall_contact", first_text(fields.get("overallContactFirstName"), fields.get("overallContactLastName"), fields.get("overallContactEmail")), "overall_contact must be supplied for PRS XML.")
    require("sites.0.facility.name", fields.get("facilityName"), "Primary facility name is required for PRS XML.")
    require("sites.0.facility.address.city", fields.get("facilityCity"), "Primary facility city is required for PRS XML.")
    require("sites.0.facility.address.country", fields.get("facilityCountry"), "Primary facility country is required for PRS XML.")
    require("regulatory.prs.study_uid", study_uid if primary_items or secondary_items or other_items else "not needed", "Outcome UID/study UID must come from the source/manual PRS export.")
    if last_follow_up and not last_follow_up_type:
        missing.append({"field": "regulatory.prs.last_follow_up_date_type", "issue": "last_follow_up_date_type is required when last_follow_up_date is present."})
    if not primary_items:
        missing.append({"field": "endpoints.primary", "issue": "At least one primary outcome is required for PRS XML."})
    for index, item in enumerate(intervention_items, start=1):
        require(f"design.interventions.{index - 1}.type", item.get("type"), "Each PRS intervention must have an intervention_type.")
        require(f"design.interventions.{index - 1}.name", item.get("name"), "Each PRS intervention must have an intervention_name.")
        require(f"design.interventions.{index - 1}.arm_group_label", item.get("arm_group_label"), "Each PRS intervention must reference an arm_group_label.")
    for collection, name in [(primary_items, "primary"), (secondary_items, "secondary"), (other_items, "other")]:
        for index, item in enumerate(collection, start=1):
            require(f"endpoints.{name}.{index - 1}.measure", item.get("measure"), "Each PRS outcome must have outcome_measure.")
            require(f"endpoints.{name}.{index - 1}.time_frame", item.get("time_frame"), "Each PRS outcome must have outcome_time_frame.")
            require(f"endpoints.{name}.{index - 1}.uid", item.get("uid"), "Each PRS outcome must have uid.")

    for key, value in list(fields.items()):
        if isinstance(value, str):
            fields[key] = clean(value)

    return fields, missing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, help="Run directory containing reference/study.reference.json.")
    parser.add_argument("--reference", help="Reference JSON path. Defaults to reference/study.reference.json.")
    parser.add_argument("--template", help="PRS XML template path. Defaults to templates/study.template.xml.")
    parser.add_argument("--check", action="store_true", help="Do not write; report fields and missing PRS inputs.")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser().resolve()
    reference_path = Path(args.reference).expanduser().resolve() if args.reference else run_dir / STANDARD_REFERENCE
    template_path = Path(args.template).expanduser().resolve() if args.template else run_dir / STANDARD_TEMPLATE
    reference = load_json(reference_path)
    fields, missing = build_fields(reference, template_path)
    blocking_missing = blocking_missing_items(reference, missing)

    if args.check:
        print(
            json.dumps(
                {
                    "missing_count": len(missing),
                    "blocking_missing_count": len(blocking_missing),
                    "missing": missing,
                    "blocking_missing": blocking_missing,
                    "template_fields": fields,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 1 if blocking_missing else 0

    merged = reference.get("template_fields") if isinstance(reference.get("template_fields"), dict) else {}
    merged.update(fields)
    reference["template_fields"] = merged
    regulatory = reference.get("regulatory") if isinstance(reference.get("regulatory"), dict) else {}
    regulatory["xml_profile"] = "clinicaltrials-prs"
    reference["regulatory"] = regulatory
    for item in missing:
        add_review_item(reference, item["field"], item["issue"])
    reference_path.write_text(json.dumps(reference, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "updated": display_path(reference_path, run_dir),
                "field_count": len(fields),
                "missing_count": len(missing),
                "blocking_missing_count": len(blocking_missing),
                "missing": missing,
                "blocking_missing": blocking_missing,
                "prs_counts": fields["__prs_counts"],
            },
            indent=2,
        )
    )
    return 1 if blocking_missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
