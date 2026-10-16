"""ClinicalTrials.gov PRS XML mapper and structural/semantic validator."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping
from xml.etree import ElementTree as ET

from contracts import study_short_title, canonical_study_type, facility_projection, get_path, meaningful


TOKEN = re.compile(r"\{[#/^]?([A-Za-z_][A-Za-z0-9_.\-\[\]()&]*)\}")
REPEATED = ("intervention", "location", "arm_group", "primary_outcome", "secondary_outcome", "other_outcome")
ET.register_namespace("prs", "http://clinicaltrials.gov/prs")


def _prs_country(value: Any) -> str:
    """Use the manual PRS reference's country name for explicit US aliases."""
    raw = _text(value)
    if raw.casefold().rstrip(".") in {"usa", "us", "u.s.a", "united states of america"}:
        return "United States"
    return raw


def _observational_timing(reference: Mapping[str, Any]) -> str:
    supplied = _text(get_path(reference, "regulatory.prs.time_perspective"))
    if supplied:
        return supplied
    if (
        _text(get_path(reference, "regulatory.prs.study_type")).casefold() == "observational"
        and canonical_study_type(get_path(reference, "meta.study_type")) == "Prospective"
    ):
        return "Prospective"
    return ""


@dataclass(frozen=True)
class ScreeningIntervalRequirement:
    days: str
    participation_scope: str

SOURCE_SCALAR_BINDINGS: dict[str, tuple[str, ...]] = {
    "oversight_info/fda_regulated_drug": ("regulatory.prs.fda_regulated_drug", "regulatory.fda_regulated_drug"),
    "oversight_info/fda_regulated_device": ("regulatory.prs.fda_regulated_device", "regulatory.fda_regulated_device"),
    "oversight_info/post_prior_to_approval": ("regulatory.prs.post_prior_to_approval",),
    "oversight_info/exported_from_us": ("regulatory.prs.exported_from_us",),
    "oversight_info/ped_postmarket_surv": ("regulatory.prs.pediatric_postmarket_surveillance",),
    "oversight_info/has_dmc": ("regulatory.prs.has_dmc", "regulatory.has_dmc"),
    "oversight_info/export_from_us": ("regulatory.prs.export_from_us",),
    "sponsors/collaborator/agency": ("regulatory.prs.collaborator_agency", "parties.collaborator.name"),
    "isINDStudy": ("regulatory.prs.is_ind_study",),
    "is_ind_study": ("regulatory.prs.is_ind_study",),
    "eligibility/gender": ("population.gender", "population.sex"),
    "eligibility/healthy_volunteers": ("population.healthy_volunteers", "regulatory.prs.healthy_volunteers"),
    "eligibility/sampling_method": ("regulatory.prs.sampling_method", "design.sampling_method"),
    "eligibility/gender_based": ("population.gender_based",),
    "eligibility/gender_description/textblock": ("population.gender_description",),
    "expanded_access_status": ("regulatory.prs.expanded_access_status",),
    "acronym": ("study.acronym",),
    "why_stopped": ("regulatory.prs.why_stopped",),
    "isFDARegulated": ("regulatory.prs.is_fda_regulated_legacy",),
    "is_fda_regulated": ("regulatory.prs.is_fda_regulated",),
    "isSection801": ("regulatory.prs.is_section_801_legacy",),
    "is_section_801": ("regulatory.prs.is_section_801",),
    "delayed_posting": ("regulatory.prs.delayed_posting",),
    "study_design/interventional_design/intervention_model_description": ("regulatory.prs.intervention_model_description", "design.intervention_model_description"),
    "study_design/interventional_design/masking_description": ("regulatory.prs.masking_description",),
    "study_design/observational_design/biospecimen_retention": ("regulatory.prs.biospecimen_retention",),
    "study_design/observational_design/biospecimen_description/textblock": ("regulatory.prs.biospecimen_description",),
    "ipd_sharing_statement/sharingIPD": ("regulatory.prs.sharing_ipd", "regulatory.prs.ipd_sharing"),
    "ipd_sharing_statement/sharing_ipd": ("regulatory.prs.sharing_ipd", "regulatory.prs.ipd_sharing"),
    "ipd_sharing_statement/ipddescription": ("regulatory.prs.ipd_description_legacy",),
    "ipd_sharing_statement/ipdsharingProtocol": ("regulatory.prs.ipd_sharing_protocol",),
    "ipd_sharing_statement/ipdsharingSAP": ("regulatory.prs.ipd_sharing_sap",),
    "ipd_sharing_statement/ipdsharingICF": ("regulatory.prs.ipd_sharing_icf",),
    "ipd_sharing_statement/ipdsharingCSR": ("regulatory.prs.ipd_sharing_csr",),
    "ipd_sharing_statement/ipdsharingAnalyticCode": ("regulatory.prs.ipd_sharing_analytic_code",),
    "ipd_sharing_statement/ipdsharingTimeFrame": ("regulatory.prs.ipd_sharing_time_frame",),
    "ipd_sharing_statement/ipdsharingAccessCriteria": ("regulatory.prs.ipd_sharing_access_criteria",),
    "ipd_sharing_statement/ipdsharingURL": ("regulatory.prs.ipd_sharing_url",),
    "ipd_sharing_statement/ipd_url": ("regulatory.prs.ipd_url",),
    "ipd_sharing_statement/ipd_info_type_protocol": ("regulatory.prs.ipd_info_type_protocol",),
    "ipd_sharing_statement/ipd_info_type_sap": ("regulatory.prs.ipd_info_type_sap",),
    "ipd_sharing_statement/ipd_info_type_icf": ("regulatory.prs.ipd_info_type_icf",),
    "ipd_sharing_statement/ipd_info_type_csr": ("regulatory.prs.ipd_info_type_csr",),
    "ipd_sharing_statement/ipd_info_type_analytic_code": ("regulatory.prs.ipd_info_type_analytic_code",),
    "ipd_sharing_statement/ipd_description/textblock": ("regulatory.prs.ipd_description",),
    "ipd_sharing_statement/ipd_time_frame/textblock": ("regulatory.prs.ipd_time_frame",),
    "ipd_sharing_statement/ipd_access_criteria/textblock": ("regulatory.prs.ipd_access_criteria",),
}


def _text(value: Any) -> str:
    if value is None: return ""
    if isinstance(value, str):
        text = value.strip()
        link = re.fullmatch(r"\[([^\]]+)\]\((?:mailto:)?[^)]+\)", text, re.I)
        return link.group(1).strip() if link else text
    if isinstance(value, (int, float)): return str(value)
    if isinstance(value, Mapping):
        for key in ("label", "measure", "outcome_measure", "name", "title", "description", "text"):
            if meaningful(value.get(key)): return _text(value[key])
        return ""
    if isinstance(value, Iterable): return "\n".join(part for item in value if (part := _text(item)))
    return str(value).strip()


def _name(value: Any) -> tuple[str, str, str]:
    name = re.sub(r"^(?:(?:Dr|Doctor|Prof|Professor|Mr|Mrs|Ms|Mx)\.?\s+)+", "", _text(value), flags=re.I)
    parts = name.split(",", 1)[0].split()
    if not parts: return "", "", ""
    if len(parts) == 1: return parts[0], "", ""
    return parts[0], " ".join(parts[1:-1]), parts[-1]


def _address(value: Any) -> str:
    if isinstance(value, str): return value
    if not isinstance(value, Mapping): return _text(value)
    return ", ".join(_text(value.get(key)) for key in ("line1", "street", "city", "state", "country", "zip") if _text(value.get(key)))


def _items(reference: Mapping[str, Any], path: str) -> list[Mapping[str, Any]]:
    value = get_path(reference, path, [])
    return [item if isinstance(item, Mapping) else {"label": _text(item)} for item in value] if isinstance(value, list) else []


def _observational_cohorts(reference: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    arms = _items(reference, "design.arms")
    if arms:
        return arms
    if _text(get_path(reference, "regulatory.prs.study_type")).casefold() != "observational":
        return []
    design = _text(get_path(reference, "design.study_design"))
    if re.search(r"\b(?:single|one)[ -]+(?:observational[ -]+)?(?:cohort|group)\b", design, re.I):
        return [{"name": "Single observational cohort", "description": design}]
    return []


def _source_value(reference: Mapping[str, Any], *paths: str) -> str:
    for path in paths:
        value = get_path(reference, path)
        if meaningful(value):
            return _text(value)
    return ""


def _merged_mapping(reference: Mapping[str, Any], *paths: str) -> dict[str, Any]:
    """Merge structured aliases while preserving left-to-right precedence."""
    merged: dict[str, Any] = {}
    for path in reversed(paths):
        value = get_path(reference, path)
        if isinstance(value, Mapping):
            merged.update(value)
    return merged


def _mapping_value(value: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        candidate = value.get(key)
        if meaningful(candidate):
            return _text(candidate)
    return ""


def _person_degrees(value: Mapping[str, Any]) -> str:
    """Prefer explicit credentials, including an explicitly empty field.

    Legacy title fields mix credentials and employment roles. Only recognized
    credential tokens may be projected from that ambiguous field; unfamiliar
    credentials remain supported through the explicit degree fields.
    """
    for key in ("degrees", "degree"):
        if key in value:
            return _text(value[key])
    credentials = {"md", "do", "phd", "dphil", "mbbs", "mbchb", "mb", "bch", "bao",
                   "od", "dds", "dmd", "pharmd", "dnp", "dpt", "otd", "drph", "scd",
                   "edd", "med", "mmed", "bmed", "jd", "rn", "bsn", "msn", "np", "pa",
                   "mph", "ms", "msc", "bs", "bsc", "ma", "mba"}
    parts = re.split(r"[,;/\s]+", _mapping_value(value, "title"))
    return ", ".join(part.strip() for part in parts
                     if re.sub(r"[.\s]", "", part).casefold() in credentials)


def _contact_fields(value: Mapping[str, Any]) -> dict[str, str]:
    first, middle, last = _name(_mapping_value(value, "name", "full_name"))
    supplied_first = _mapping_value(value, "first_name", "given_name")
    supplied_last = _mapping_value(value, "last_name", "family_name", "surname")
    if supplied_first or supplied_last:
        remaining = " ".join(part for part in (first, middle, last) if part).split()
        consistent = True
        if supplied_first:
            prefix = supplied_first.split()
            consistent = remaining[:len(prefix)] == prefix
            remaining = remaining[len(prefix):] if consistent else []
            first = supplied_first
        if supplied_last:
            suffix = supplied_last.split()
            consistent = consistent and remaining[-len(suffix):] == suffix
            remaining = remaining[:-len(suffix)] if consistent else []
            last = supplied_last
        if not supplied_first:
            first = remaining.pop(0) if remaining else ''
        if not supplied_last:
            last = remaining.pop() if remaining else ''
        middle = ' '.join(remaining) if consistent else ''
    return {
        "first_name": _mapping_value(value, "first_name", "given_name") or first,
        "middle_name": _text(value["middle_name"]) if "middle_name" in value else middle,
        "last_name": _mapping_value(value, "last_name", "family_name", "surname") or last,
        "degrees": _person_degrees(value),
        "phone": _mapping_value(value, "phone", "business_phone", "office_phone"),
        "phone_ext": _mapping_value(value, "phone_ext", "extension", "ext"),
        "email": _mapping_value(value, "email"),
    }


def _site_backup_contact(site: Mapping[str, Any]) -> dict[str, Any]:
    candidates: list[Any] = [
        site.get("contact_backup"),
        site.get("backup_contact"),
        site.get("contacts_backup"),
        site.get("backup_contacts"),
    ]
    contacts = site.get("contacts")
    if isinstance(contacts, Mapping):
        candidates.extend((contacts.get("backup"), contacts.get("contact_backup"), contacts.get("backup_contact")))
    merged: dict[str, Any] = {}
    for candidate in reversed(candidates):
        if isinstance(candidate, Mapping):
            merged.update(candidate)
    return merged


def _site_investigator(site: Mapping[str, Any]) -> Mapping[str, Any]:
    investigators = site.get("investigators")
    investigators = investigators if isinstance(investigators, list) else []
    investigator = site.get("investigator")
    # The designated first investigator retains precedence. An empty primary
    # placeholder must not hide the named singular investigator behind it.
    candidates = [*investigators[:1], investigator, *investigators[1:]]
    for candidate in candidates:
        if isinstance(candidate, Mapping) and any(
            meaningful(candidate.get(key)) for key in ("name", "first_name", "last_name")
        ):
            return candidate
    return investigator if isinstance(investigator, Mapping) else {}


def _stable_study_uid(reference: Mapping[str, Any]) -> str:
    explicit = _source_value(reference, "regulatory.prs.study_uid", "regulatory.prs.uid")
    if explicit:
        return explicit
    protocol = re.sub(r"[^A-Za-z0-9]+", "-", _text(get_path(reference, "meta.protocol_number"))).strip("-").upper()
    identity_payload = {
        "protocol_number": get_path(reference, "meta.protocol_number"),
        "title": get_path(reference, "study.title"),
        "sponsor": get_path(reference, "parties.sponsor.name"),
    }
    identity = hashlib.sha256(json.dumps(identity_payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:10].upper()
    return f"{protocol or 'STUDY'}-{identity}-UID"


def _enrollment_count(value: Any) -> str:
    """Prefer an explicitly identified total over a preceding subgroup count."""
    text = _text(value)
    number = r"(?<!\w)(\d[\d,]*)(?!\w)"
    patterns = (
        number + r"\s*(?:(?:subjects?|participants?|patients?)\s+)?(?:in\s+)?(?:total|overall)\b",
        r"\b(?:total|overall)\s*(?:(?:planned\s+)?(?:sample\s+size|enrollment|subjects?|participants?|patients?))?\s*(?:is|of|:|=)?\s*" + number,
    )
    totals = {match.group(1).replace(",", "") for pattern in patterns for match in re.finditer(pattern, text, re.I)}
    if totals:
        return next(iter(totals)) if len(totals) == 1 else ""
    # A leading study-wide count followed by a parenthetical breakdown retains
    # the established mapping. Do not mistake an explicitly per-group first
    # count for a study-wide count when no total was supplied.
    match = re.search(number, text)
    if match and not re.search(r"\b(?:arm|group|cohort)\b", text[:match.start()], re.I) and not re.match(
        r"\s*(?:(?:subjects?|participants?|patients?)\s+)?(?:per\s+|(?:in\s+)?each\s+|in\s+(?:the\s+)?)(?:arm|group|cohort)\b",
        text[match.end():], re.I,
    ):
        return match.group(1).replace(",", "")
    return ""


def _normalize_participation_scope(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value).strip().casefold()
    normalized = re.sub(r"^(?:an?|the)\s+", "another ", normalized)
    return re.sub(r"\bstudies\b$", "study", normalized)


def _equivalent_screening_criterion(value: str, requirement: ScreeningIntervalRequirement, *, exclusion: bool = False) -> bool:
    """Recognize source ownership of the same participation scope and interval.

    Preserve the source's anchor and exceptions rather than adding an inverse
    criterion with a different anchor. Different intervals/scopes remain distinct.
    """
    text = re.sub(r"\s+", " ", value).strip().casefold()
    text = re.sub(r"\b(?:an?|the)(?=(?:\s+[a-z][a-z-]*){0,5}\s+stud(?:y|ies)\b)", "another", text)
    days = re.escape(requirement.days)
    scope = re.escape(requirement.participation_scope.casefold())
    anchor = r"(?:screening|day\s*0|enrollment|enrolment)\b"
    return bool(
        re.search(rf"\b(?:no|without) participation in {scope} (?:during|within|in) (?:the )?{days} days? (?:before|prior to) {anchor}", text)
        or re.search(rf"\bat least {days} days? without participation in {scope} (?:before|prior to) {anchor}", text)
        or exclusion and re.search(
            rf"\bparticipation in {scope} (?:during|within|in) (?:the )?{days} days? (?:before|prior to) {anchor}", text)
    )


def screening_interval_requirement(
    reference: Mapping[str, Any],
) -> ScreeningIntervalRequirement | None:
    raw = _text(get_path(reference, "procedures.minimum_days_before_screening_without_participation"))
    if not raw:
        return None
    match = re.fullmatch(
        r"(?:at\s+least\s+)?(?P<days>\d+(?:\.\d+)?)\s*(?:days?)?"
        r"(?:\s+before\s+screening)?\s*\.?",
        raw,
        re.I,
    )
    if not match:
        return None
    participation_scope = "another study"
    inclusion = get_path(reference, "population.inclusion_criteria", []) or []
    exclusion = get_path(reference, "population.exclusion_criteria", []) or []
    for criterion in (*inclusion, *exclusion):
        scope_match = re.search(
            r"\b(?:another|an?|the)(?:\s+[a-z][a-z-]*){0,5}\s+stud(?:y|ies)\b",
            _text(criterion),
            re.I,
        )
        if scope_match:
            candidate = _normalize_participation_scope(scope_match.group(0))
            participation_scope = candidate
            if candidate != "another study":
                break
    return ScreeningIntervalRequirement(
        days=match.group("days"),
        participation_scope=participation_scope,
    )


def _screening_interval_requirement_from_xml(
    study: ET.Element,
) -> ScreeningIntervalRequirement | None:
    criteria = study.find("eligibility/criteria")
    text = " ".join(criteria.itertext()) if criteria is not None else ""
    match = re.search(
        r"\bat\s+least\s+(?P<days>\d+(?:\.\d+)?)\s+days?\s+without\s+participation\s+in\s+"
        r"(?P<scope>another(?:\s+[a-z][a-z-]*){0,5}\s+stud(?:y|ies))\s+before\s+screening\b",
        text,
        re.I,
    )
    if not match:
        return None
    normalized_scope = re.sub(r"\s+", " ", match.group("scope")).strip().casefold()
    normalized_scope = re.sub(r"\bstudies\b$", "study", normalized_scope)
    return ScreeningIntervalRequirement(
        days=match.group("days"),
        participation_scope=normalized_scope,
    )


def _validation_screening_interval_requirement(
    reference: Mapping[str, Any],
) -> ScreeningIntervalRequirement | None:
    source_value = get_path(
        reference,
        "procedures.minimum_days_before_screening_without_participation",
    )
    source_text = str(source_value).strip() if source_value is not None else ""
    source_match = re.fullmatch(
        r"(?:at\s+least\s+)?(?P<quantity>\d+(?:\.\d+)?)\s*(?:day|days)?"
        r"(?:\s+before\s+screening)?\s*\.?",
        source_text,
        re.I,
    )
    if not source_match:
        return None
    scope = "another study"
    criteria_values = [
        *(get_path(reference, "population.inclusion_criteria", []) or []),
        *(get_path(reference, "population.exclusion_criteria", []) or []),
    ]
    for criterion in criteria_values:
        criterion_match = re.search(
            r"\banother(?:\s+[a-z][a-z-]*){0,5}\s+stud(?:y|ies)\b",
            str(criterion),
            re.I,
        )
        if criterion_match:
            candidate = re.sub(r"\s+", " ", criterion_match.group(0)).strip().casefold()
            candidate = re.sub(r"\bstudies\b$", "study", candidate)
            scope = candidate
            if candidate != "another study":
                break
    return ScreeningIntervalRequirement(
        days=source_match.group("quantity"),
        participation_scope=scope,
    )


def _fields(reference: Mapping[str, Any], narrative: Mapping[str, Any]) -> dict[str, str]:
    pi = get_path(reference, "parties.principal_investigator", {}) or {}
    coordinator = get_path(reference, "parties.study_coordinator", {}) or {}
    irb = get_path(reference, "parties.irb", {}) or {}
    sponsor = get_path(reference, "parties.sponsor", {}) or {}
    overall_contact_backup = _merged_mapping(
        reference,
        "regulatory.prs.overall_contact_backup",
        "regulatory.prs.overall_backup_contact",
        "parties.overall_contact_backup",
        "parties.study_coordinator_backup",
        "parties.backup_contact",
    )
    overall_backup_fields = _contact_fields(overall_contact_backup)
    pi_fields = _contact_fields(pi)
    coordinator_fields = _contact_fields(coordinator)
    pi_first, pi_middle, pi_last = (pi_fields[key] for key in ("first_name", "middle_name", "last_name"))
    contact_first, contact_middle, contact_last = (coordinator_fields[key] for key in ("first_name", "middle_name", "last_name"))
    responsible = _merged_mapping(
        reference,
        "regulatory.prs.responsible_party",
        "parties.responsible_party",
    )
    responsible_type = _source_value(
        reference,
        "regulatory.prs.responsible_party_type",
        "regulatory.prs.resp_party_type",
    ) or _mapping_value(responsible, "responsible_party_type", "resp_party_type", "type")
    investigator_affiliation = _text(
        get_path(reference, "regulatory.prs.overall_official_affiliation")
        or pi.get("affiliation")
    )
    if not investigator_affiliation:
        pi_name = _text(pi.get("name")).casefold()
        for site in get_path(reference, "sites", []) or []:
            if not isinstance(site, Mapping):
                continue
            investigators = site.get("investigators") if isinstance(site.get("investigators"), list) else [_site_investigator(site)]
            if not any(isinstance(item, Mapping) and _text(item.get("name")).casefold() == pi_name for item in investigators):
                continue
            facility = site.get("facility") if isinstance(site.get("facility"), Mapping) else {}
            investigator_affiliation = _text(facility.get("name"))
            if investigator_affiliation:
                break
    responsible_is_investigator = bool(responsible_type and "investigator" in responsible_type.casefold())
    responsible_is_sponsor = bool(responsible_type and "sponsor" in responsible_type.casefold())
    title = _text(get_path(reference, "study.title"))
    study_type = _text(get_path(reference, "regulatory.prs.study_type"))
    observational = _text(get_path(reference, "regulatory.prs.observational_study_design"))
    inclusion = [_text(item) for item in get_path(reference, "population.inclusion_criteria", []) or []]
    exclusion = [_text(item) for item in get_path(reference, "population.exclusion_criteria", []) or []]
    screening_interval = screening_interval_requirement(reference)
    if screening_interval and not (
        any(_equivalent_screening_criterion(item, screening_interval) for item in inclusion)
        or any(_equivalent_screening_criterion(item, screening_interval, exclusion=True) for item in exclusion)
    ):
        inclusion.append(
            f"At least {screening_interval.days} days without participation in "
            f"{screening_interval.participation_scope} before screening"
        )
    criteria = "Inclusion Criteria:\n" + "\n".join(f"• {item}" for item in inclusion)
    criteria += "\n\nExclusion Criteria:\n" + "\n".join(f"• {item}" for item in exclusion)
    brief = narrative.get("brief_summary", {}) if isinstance(narrative.get("brief_summary"), Mapping) else narrative.get("brief_summary")
    detailed = narrative.get("detailed_description", {}) if isinstance(narrative.get("detailed_description"), Mapping) else narrative.get("detailed_description")
    values = {
        "providerStudyId": _source_value(reference, "regulatory.prs.provider_study_id", "meta.protocol_number"), "protocolNumber": _text(get_path(reference, "meta.protocol_number")),
        "orgName": _source_value(reference, "regulatory.prs.org_name", "regulatory.prs.organization_name", "parties.sponsor.name"),
        "providerName": _source_value(reference, "regulatory.prs.provider_name"), "leadSponsorAgency": _source_value(reference, "regulatory.prs.lead_sponsor_agency", "parties.sponsor.name"),
        "overallStatus": _text(get_path(reference, "regulatory.prs.overall_status")), "irbApprovalNumber": _text(irb.get("approval_number")),
        "irbName": _text(irb.get("name")), "irbAffiliation": _text(irb.get("affiliation")), "irbFullAddress": _address(irb.get("address")),
        "irbPhone": _text(irb.get("phone")), "irbEmail": _text(irb.get("email")), "irbApprovalStatus": _text(irb.get("approval_status")),
        "responsiblePartyNameTitle": _mapping_value(responsible, "name_title", "name") or _text(pi.get("name") if responsible_is_investigator else ""),
        "responsiblePartyOrganization": _mapping_value(responsible, "organization", "affiliation") or _text(sponsor.get("name") if responsible_is_sponsor else ""),
        "responsiblePartyEmail": _mapping_value(responsible, "email") or _text(pi.get("email") if responsible_is_investigator else ""),
        "responsiblePartyPhone": _mapping_value(responsible, "phone", "business_phone", "office_phone") or _text(pi.get("phone") if responsible_is_investigator else ""),
        "responsiblePartyType": responsible_type,
        "responsiblePartyInvestigatorTitle": _mapping_value(responsible, "investigator_title", "title") or _text(pi.get("title") if responsible_is_investigator else ""),
        "responsiblePartyInvestigatorAffiliation": _mapping_value(responsible, "investigator_affiliation") or _text(investigator_affiliation if responsible_is_investigator else ""),
        "overallContactFirstName": contact_first, "overallContactMiddleName": contact_middle, "overallContactLastName": contact_last,
        "overallContactDegrees": _person_degrees(coordinator), "overallContactPhone": _text(coordinator.get("business_phone")), "overallContactEmail": _text(coordinator.get("email")),
        "overallContactBackupFirstName": overall_backup_fields["first_name"],
        "overallContactBackupMiddleName": overall_backup_fields["middle_name"],
        "overallContactBackupLastName": overall_backup_fields["last_name"],
        "overallContactBackupDegrees": overall_backup_fields["degrees"],
        "overallContactBackupPhone": overall_backup_fields["phone"],
        "overallContactBackupPhoneExt": overall_backup_fields["phone_ext"],
        "overallContactBackupEmail": overall_backup_fields["email"],
        "overallOfficialFirstName": pi_first, "overallOfficialMiddleName": pi_middle, "overallOfficialLastName": pi_last,
        "overallOfficialDegrees": pi_fields["degrees"], "overallOfficialRole": "Principal Investigator", "overallOfficialAffiliation": investigator_affiliation,
        "briefTitle": study_short_title(reference), "officialTitle": title,
        "briefSummary": _text(brief), "detailedDescription": _text(detailed), "eligibilityCriteria": criteria,
        "eligibilityGender": _text(get_path(reference, "population.sex")), "healthyVolunteers": _text(get_path(reference, "population.healthy_volunteers")),
        "samplingMethod": _text(get_path(reference, "regulatory.prs.sampling_method")), "studyPopulation": _text(get_path(reference, "population.study_population")),
        "minimumAge": _text(get_path(reference, "population.minimum_age")), "maximumAge": _text(get_path(reference, "population.maximum_age")),
        "enrollment": _enrollment_count(get_path(reference, "population.sample_size")),
        "enrollmentType": _text(get_path(reference, "regulatory.prs.enrollment_type")), "startDate": _text(get_path(reference, "regulatory.prs.start_date")),
        "startDateType": _text(get_path(reference, "regulatory.prs.start_date_type")),
        "endDate": _text(get_path(reference, "regulatory.prs.end_date")), "verificationDate": _text(get_path(reference, "regulatory.prs.verification_date")),
        "lastFollowUpDate": _text(get_path(reference, "regulatory.prs.study_completion_date") or get_path(reference, "regulatory.prs.last_follow_up_date")),
        "lastFollowUpDateType": _text(get_path(reference, "regulatory.prs.study_completion_date_type") or get_path(reference, "regulatory.prs.last_follow_up_date_type")),
        "primaryCompletionDate": _text(get_path(reference, "regulatory.prs.primary_completion_date")),
        "primaryCompletionDateType": _text(get_path(reference, "regulatory.prs.primary_completion_date_type")), "studyType": study_type,
        "observationalStudyDesign": observational,
        "studyTiming": _observational_timing(reference),
        "patientRegistry": _text(get_path(reference, "regulatory.prs.patient_registry")),
        "targetDurationQuantity": _text(get_path(reference, "regulatory.prs.target_duration_quantity")),
        "targetDurationUnits": _text(get_path(reference, "regulatory.prs.target_duration_units")),
        "allocation": _text(get_path(reference, "regulatory.prs.allocation")),
        "interventionModel": _text(get_path(reference, "regulatory.prs.intervention_model")), "primaryPurpose": _text(get_path(reference, "regulatory.prs.primary_purpose")),
        "masking": _text(get_path(reference, "design.masking")), "numberOfArms": str(len(_items(reference, "design.arms"))),
        "numberOfGroups": str(len(_observational_cohorts(reference))) if _observational_cohorts(reference) else "", "condition": _text(get_path(reference, "study.condition")),
        "sharingIPD": _text(get_path(reference, "regulatory.prs.ipd_sharing")), "sharingIpd": _text(get_path(reference, "regulatory.prs.ipd_sharing")),
        "studyUid": _stable_study_uid(reference), "nctId": _text(get_path(reference, "regulatory.prs.nct_id")),
    }
    values.update({
        "fdaRegulatedDrug": _source_value(reference, "regulatory.prs.fda_regulated_drug", "regulatory.fda_regulated_drug"),
        "fdaRegulatedDevice": _source_value(reference, "regulatory.prs.fda_regulated_device", "regulatory.fda_regulated_device"),
        "postPriorToApproval": _source_value(reference, "regulatory.prs.post_prior_to_approval"),
        "exportedFromUs": _source_value(reference, "regulatory.prs.exported_from_us"),
        "pediatricPostmarketSurveillance": _source_value(reference, "regulatory.prs.pediatric_postmarket_surveillance"),
        "irbPhoneExt": _source_value(reference, "parties.irb.phone_ext", "parties.irb.ext"),
        "irbExt": _source_value(reference, "parties.irb.ext"),
        "hasDmc": _source_value(reference, "regulatory.prs.has_dmc", "regulatory.has_dmc"),
        "exportFromUs": _source_value(reference, "regulatory.prs.export_from_us"),
        "collaboratorAgency": _source_value(reference, "regulatory.prs.collaborator_agency", "parties.collaborator.name"),
        "responsiblePartyPhoneExt": _mapping_value(responsible, "phone_ext", "extension", "ext"),
        "responsiblePartyInvestigatorUsername": _mapping_value(responsible, "investigator_username", "username"),
        "isINDStudy": _source_value(reference, "regulatory.prs.is_ind_study"),
        "isIndStudy": _source_value(reference, "regulatory.prs.is_ind_study"),
        "overallContactPhoneExt": _source_value(reference, "parties.study_coordinator.phone_ext"),
        "briefTitle": study_short_title(reference),
        "eligibilityGender": _source_value(reference, "population.gender", "population.sex"),
        "healthyVolunteers": _source_value(reference, "population.healthy_volunteers", "regulatory.prs.healthy_volunteers"),
        "samplingMethod": _source_value(reference, "regulatory.prs.sampling_method", "design.sampling_method"),
        "genderBased": _source_value(reference, "population.gender_based"),
        "genderDescription": _source_value(reference, "population.gender_description"),
        "expandedAccessStatus": _source_value(reference, "regulatory.prs.expanded_access_status"),
        "acronym": _source_value(reference, "study.acronym"),
        "whyStopped": _source_value(reference, "regulatory.prs.why_stopped"),
        "isFDARegulated": _source_value(reference, "regulatory.prs.is_fda_regulated_legacy"),
        "isFdaRegulated": _source_value(reference, "regulatory.prs.is_fda_regulated"),
        "isSection801": _source_value(reference, "regulatory.prs.is_section_801_legacy"),
        "isSection801SnakeCase": _source_value(reference, "regulatory.prs.is_section_801"),
        "delayedPosting": _source_value(reference, "regulatory.prs.delayed_posting"),
        "interventionModelDescription": _source_value(reference, "regulatory.prs.intervention_model_description", "design.intervention_model_description"),
        "maskingDescription": _source_value(reference, "regulatory.prs.masking_description"),
        "biospecimenRetention": _source_value(reference, "regulatory.prs.biospecimen_retention"),
        "biospecimenDescription": _source_value(reference, "regulatory.prs.biospecimen_description"),
        "sharingIPD": _source_value(reference, "regulatory.prs.sharing_ipd", "regulatory.prs.ipd_sharing"),
        "sharingIpd": _source_value(reference, "regulatory.prs.sharing_ipd", "regulatory.prs.ipd_sharing"),
        "ipdDescriptionLegacy": _source_value(reference, "regulatory.prs.ipd_description_legacy"),
        "ipdSharingProtocol": _source_value(reference, "regulatory.prs.ipd_sharing_protocol"),
        "ipdSharingSAP": _source_value(reference, "regulatory.prs.ipd_sharing_sap"),
        "ipdSharingICF": _source_value(reference, "regulatory.prs.ipd_sharing_icf"),
        "ipdSharingCSR": _source_value(reference, "regulatory.prs.ipd_sharing_csr"),
        "ipdSharingAnalyticCode": _source_value(reference, "regulatory.prs.ipd_sharing_analytic_code"),
        "ipdSharingTimeFrame": _source_value(reference, "regulatory.prs.ipd_sharing_time_frame"),
        "ipdSharingAccessCriteria": _source_value(reference, "regulatory.prs.ipd_sharing_access_criteria"),
        "ipdSharingURL": _source_value(reference, "regulatory.prs.ipd_sharing_url"),
        "ipdUrl": _source_value(reference, "regulatory.prs.ipd_url"),
        "ipdInfoTypeProtocol": _source_value(reference, "regulatory.prs.ipd_info_type_protocol"),
        "ipdInfoTypeSap": _source_value(reference, "regulatory.prs.ipd_info_type_sap"),
        "ipdInfoTypeIcf": _source_value(reference, "regulatory.prs.ipd_info_type_icf"),
        "ipdInfoTypeCsr": _source_value(reference, "regulatory.prs.ipd_info_type_csr"),
        "ipdInfoTypeAnalyticCode": _source_value(reference, "regulatory.prs.ipd_info_type_analytic_code"),
        "ipdDescription": _source_value(reference, "regulatory.prs.ipd_description"),
        "ipdTimeFrame": _source_value(reference, "regulatory.prs.ipd_time_frame"),
        "ipdAccessCriteria": _source_value(reference, "regulatory.prs.ipd_access_criteria"),
    })
    # Local, explicit source-to-transport conversions. Unknowns survive so the
    # independent validator can diagnose them; approved source is never edited.
    transports = {
        "eligibilityGender": {"all sexes": "All", "both": "All", "all": "All", "male": "Male", "female": "Female"},
        "samplingMethod": {"probability sample": "Probability Sample", "non-probability sample": "Non-Probability Sample"},
        "studyType": {"observational": "Observational", "interventional": "Interventional", "expanded access": "Expanded Access"},
        "primaryCompletionDateType": {"actual": "Actual", "anticipated": "Anticipated"},
        "lastFollowUpDateType": {"actual": "Actual", "anticipated": "Anticipated"},
    }
    for token, mapping in transports.items():
        values[token] = mapping.get(" ".join(values[token].split()).casefold(), values[token])
    return values


def _study(root: ET.Element) -> ET.Element:
    if root.tag == "clinical_study": return root
    for child in root.iter("clinical_study"): return child
    raise ValueError("PRS XML lacks clinical_study.")


def _resize(study: ET.Element, tag: str, count: int) -> list[ET.Element]:
    children = list(study); matches = [(i, child) for i, child in enumerate(children) if child.tag == tag]
    if not matches and count: raise ValueError(f"PRS template lacks <{tag}>.")
    template = matches[0][1] if matches else None; insert_at = matches[0][0] if matches else len(children)
    for _, child in reversed(matches): study.remove(child)
    result = []
    for offset in range(count):
        clone = copy.deepcopy(template); study.insert(insert_at + offset, clone); result.append(clone)
    return result


def _set(node: ET.Element, path: str, value: Any) -> None:
    target = node.find(path)
    if target is not None: target.text = _text(value)


def _matched_candidate_indices(text: str, candidates: list[str]) -> set[int]:
    """Prefer the longest named cohort when labels overlap in intervention text."""
    matches = [
        (match.start(), match.end(), index)
        for index, name in enumerate(candidates) if name
        for match in re.finditer(r"(?<!\w)" + re.escape(name) + r"(?!\w)", text, re.I)
    ]
    accepted: list[tuple[int, int, int]] = []
    for start, end, index in sorted(matches, key=lambda item: item[1] - item[0], reverse=True):
        if not any(start < previous_end and end > previous_start for previous_start, previous_end, _ in accepted):
            accepted.append((start, end, index))
    return {index for _, _, index in accepted}


def _intervention_items(reference: Mapping[str, Any]) -> list[dict[str, Any]]:
    explicit = _items(reference, "design.interventions")
    items = explicit or ([{
        "type": get_path(reference, "design.intervention_type"),
        "name": get_path(reference, "design.intervention_name"),
        "description": get_path(reference, "design.intervention_description"),
    }] if meaningful(get_path(reference, "design.intervention_name")) else [])
    arm_items = _observational_cohorts(reference)
    arms = [_text(item.get("arm_group_label") or item.get("label") or item.get("name")) for item in arm_items]
    if not explicit and len(arm_items) > 1 and len(items) == 1:
        combined_name = _text(items[0].get("name"))
        names = [re.sub(r"\s+(?:cohort|group|arm)$", "", label, flags=re.I).strip() for label in arms]
        if all(names) and len({name.casefold() for name in names}) == len(names):
            if _matched_candidate_indices(combined_name, names) == set(range(len(arm_items))):
                return [{
                    "name": name,
                    "type": "Device" if _text(items[0].get("type")).casefold().startswith("medical device") else items[0].get("type"),
                    "description": arm.get("description"),
                    "arm_group_labels": [label],
                } for name, arm, label in zip(names, arm_items, arms)]
    result = []
    for original in items:
        item = dict(original)
        supplied = item.get("arm_group_labels") or item.get("arm_group_label") or item.get("armGroupLabel")
        if supplied:
            labels = [_text(label) for label in supplied] if isinstance(supplied, list) else [_text(supplied)]
        elif not explicit:
            # Infer only exact cohort names present in the supplied combined
            # intervention name. Never link an unrelated comparator by position.
            name = _text(item.get("intervention_name") or item.get("name"))
            matched = _matched_candidate_indices(name, arms)
            labels = [arm for index, arm in enumerate(arms) if index in matched]
            if not labels and len(arms) == 1:
                labels = arms
        elif len(arms) == 1 and not _items(reference, "design.arms"):
            labels = arms
        else:
            labels = []
        item["arm_group_labels"] = list(dict.fromkeys(labels))
        result.append(item)
    return result


def _fill_repeated(study: ET.Element, reference: Mapping[str, Any]) -> None:
    interventions = _intervention_items(reference)
    for node, item in zip(_resize(study, "intervention", len(interventions)), interventions):
        _set(node, "intervention_type", item.get("intervention_type") or item.get("type")); _set(node, "intervention_name", item.get("intervention_name") or item.get("name"))
        _set(node, "intervention_description/textblock", item.get("intervention_description") or item.get("description"))
        prototype = node.find("arm_group_label")
        if prototype is not None:
            position = list(node).index(prototype)
            for old in node.findall("arm_group_label"):
                node.remove(old)
            for offset, label in enumerate(item["arm_group_labels"] or [""]):
                child = copy.deepcopy(prototype); child.text = label
                node.insert(position + offset, child)
    arms = _observational_cohorts(reference)
    for node, item in zip(_resize(study, "arm_group", len(arms)), arms):
        _set(node, "arm_group_label", item.get("arm_group_label") or item.get("label") or item.get("name")); _set(node, "arm_type", item.get("arm_type") or item.get("type")); _set(node, "arm_group_description/textblock", item.get("description"))
    for tag, path in (("primary_outcome", "endpoints.primary"), ("secondary_outcome", "endpoints.secondary"), ("other_outcome", "endpoints.other")):
        items = _items(reference, path)
        shared_uid = _stable_study_uid(reference)
        for index, (node, item) in enumerate(zip(_resize(study, tag, len(items)), items), start=1):
            _set(node, "outcome_measure", item.get("outcome_measure") or item.get("measure") or item.get("label")); _set(node, "outcome_time_frame", item.get("outcome_time_frame") or item.get("time_frame") or item.get("time_point"))
            _set(node, "uid", shared_uid); _set(node, "outcome_description/textblock", item.get("description"))
    sites = [item for item in get_path(reference, "sites", []) or [] if isinstance(item, Mapping)]
    for node, site in zip(_resize(study, "location", len(sites)), sites):
        facility_value = site.get("facility")
        facility: Mapping[str, Any] = facility_value if isinstance(facility_value, Mapping) else {}
        facility_fields = facility_projection(facility)
        contact = site.get("contact") if isinstance(site.get("contact"), Mapping) else {}; investigator = _site_investigator(site)
        contact_fields = _contact_fields(contact)
        backup_fields = _contact_fields(_site_backup_contact(site))
        investigator_fields = _contact_fields(investigator)
        _set(node, "status", site.get("status")); _set(node, "facility/name", facility_fields["name"]); _set(node, "facility/address/city", facility_fields["city"]); _set(node, "facility/address/state", facility_fields["state"]); _set(node, "facility/address/country", _prs_country(facility_fields["country"])); _set(node, "facility/address/zip", facility_fields["postal_code"])
        for field, value in contact_fields.items():
            _set(node, f"contact/{field}", value)
        for field, value in backup_fields.items():
            _set(node, f"contact_backup/{field}", value)
        for field in ("first_name", "middle_name", "last_name", "degrees"):
            _set(node, f"investigator/{field}", investigator_fields[field])
        _set(node, "investigator/role", investigator.get("role"))


def expected_counts(reference: Mapping[str, Any]) -> dict[str, int]:
    interventions = _intervention_items(reference)
    return {"intervention": len(interventions), "arm_group": len(_observational_cohorts(reference)), "primary_outcome": len(_items(reference, "endpoints.primary")), "secondary_outcome": len(_items(reference, "endpoints.secondary")), "other_outcome": len(_items(reference, "endpoints.other")), "location": len(get_path(reference, "sites", []) or [])}


def repeated_counts(path: Path) -> dict[str, int]:
    study = _study(ET.parse(path).getroot())
    return {tag: sum(child.tag == tag for child in study) for tag in REPEATED}


def structural_signature(path: Path) -> tuple[Any, ...]:
    def shape(node: ET.Element) -> tuple[Any, ...]:
        seen = set(); children = []
        for child in node:
            if child.tag in REPEATED and child.tag in seen: continue
            seen.add(child.tag); children.append(shape(child))
        return node.tag, tuple(children)
    return shape(_study(ET.parse(path).getroot()))


def compare_structure(reference_path: Path, candidate_path: Path) -> list[str]:
    def compare(expected: ET.Element, actual: ET.Element, path: str, findings: list[str]) -> None:
        expected_children, actual_children = list(expected), list(actual)
        expected_tags, actual_tags = [], []
        expected_by_tag, actual_by_tag = {}, {}
        design_branches = {"interventional_design", "observational_design"}
        def contract_tag(tag: str) -> str:
            return "__study_design_branch__" if tag in design_branches else tag
        for child in expected_children:
            key = contract_tag(child.tag)
            expected_by_tag.setdefault(key, child)
            if key not in expected_tags: expected_tags.append(key)
        for child in actual_children:
            key = contract_tag(child.tag)
            actual_by_tag.setdefault(key, child)
            if key not in actual_tags: actual_tags.append(key)
        for tag in actual_tags:
            if tag not in REPEATED and sum(contract_tag(child.tag) == tag for child in actual_children) != 1:
                findings.append(f"{path}/{tag}: scalar cardinality differs")
        expected_present = [tag for tag in expected_tags if tag in actual_tags or tag not in REPEATED]
        if expected_present != actual_tags:
            findings.append(f"{path}: direct-child names or ordering differ")
        for tag in expected_present:
            if tag in actual_by_tag:
                if tag != "__study_design_branch__":
                    for child in actual_children:
                        if contract_tag(child.tag) == tag:
                            compare(expected_by_tag[tag], child, f"{path}/{tag}", findings)
    try:
        findings: list[str] = []
        compare(_study(ET.parse(reference_path).getroot()), _study(ET.parse(candidate_path).getroot()), "clinical_study", findings)
        return findings
    except (OSError, ET.ParseError, ValueError) as exc: return [f"PRS XML structural parse error: {exc}"]


def _scalar_template_bindings(template_path: Path) -> list[tuple[str, str]]:
    """Map non-repeated template tokens to their deterministic XML paths."""
    study = _study(ET.parse(template_path).getroot())
    bindings: list[tuple[str, str]] = []

    def visit(node: ET.Element, path: str) -> None:
        for child in node:
            child_path = f"{path}/{child.tag}" if path else child.tag
            if child.tag in REPEATED:
                continue
            match = TOKEN.fullmatch((child.text or "").strip())
            if match:
                bindings.append((child_path, match.group(1)))
            visit(child, child_path)

    visit(study, "")
    return bindings


def _expected_transport_value(target: str, source: Any) -> str:
    """Source-fidelity oracle independent of _fields and its mapping table."""
    value = _text(source)
    normalized = " ".join(value.split()).casefold()
    if target == "eligibility/gender" and normalized in {"all sexes", "both"}:
        return "All"
    vocabulary = {
        "eligibility/gender": ("All", "Female", "Male"),
        "eligibility/sampling_method": ("Probability Sample", "Non-Probability Sample"),
        "study_design/study_type": ("Interventional", "Observational", "Expanded Access"),
        "primary_compl_date_type": ("Anticipated", "Actual"),
        "last_follow_up_date_type": ("Anticipated", "Actual"),
    }
    return next((word for word in vocabulary.get(target, ()) if word.casefold() == normalized), value)


def quality_report(path: Path, reference: Mapping[str, Any]) -> dict[str, Any]:
    """Audit queried scalars without claiming a complete registrable record.

    This is advisory, separate from validate_output's existing blocking gate.
    Upload XSD optionality is not registration requiredness. No intake fields,
    calendar anchors, healthy-volunteer answers or condition terms are inferred.
    """
    study = _study(ET.parse(path).getroot())
    bindings = {
        "eligibility/gender": SOURCE_SCALAR_BINDINGS["eligibility/gender"],
        "eligibility/healthy_volunteers": SOURCE_SCALAR_BINDINGS["eligibility/healthy_volunteers"],
        "eligibility/sampling_method": SOURCE_SCALAR_BINDINGS["eligibility/sampling_method"],
        "condition": ("study.condition",),
        "start_date": ("regulatory.prs.start_date",),
        "start_date_type": ("regulatory.prs.start_date_type",),
        "primary_compl_date": ("regulatory.prs.primary_completion_date",),
        "primary_compl_date_type": ("regulatory.prs.primary_completion_date_type",),
        "last_follow_up_date": ("regulatory.prs.study_completion_date", "regulatory.prs.last_follow_up_date"),
        "last_follow_up_date_type": ("regulatory.prs.study_completion_date_type", "regulatory.prs.last_follow_up_date_type"),
        "verification_date": ("regulatory.prs.verification_date",),
        "end_date": ("regulatory.prs.end_date",),
    }
    provenance = {}
    for target, paths in bindings.items():
        selected = next((key for key in paths if meaningful(get_path(reference, key))), None)
        raw = get_path(reference, selected) if selected else None
        expected = _expected_transport_value(target, raw)
        actual = _text(study.findtext(target))
        status = ("mapped" if actual == expected else "mapping_failure") if selected else (
            "unsourced_output" if actual else "missing_source")
        provenance[target] = {
            "source_paths": list(paths), "source_path": selected,
            "source_value": copy.deepcopy(raw), "expected_value": expected,
            "output_value": actual, "status": status,
        }
    study_type = _source_value(reference, "regulatory.prs.study_type")
    observational = study_type.casefold() == "observational"
    interventional = study_type.casefold() == "interventional"
    fields = {target: {"applicability": "review_registration_definitions",
                       "source_status": item["status"]} for target, item in provenance.items()}
    fields["end_date"]["applicability"] = "deprecated"
    fields["eligibility/sampling_method"]["applicability"] = (
        "observational_only" if observational else "not_applicable" if interventional else "review_study_type")
    # Registration definitions distinguish observational optionality from
    # interventional review. This is not a new mandatory intake requirement.
    fields["eligibility/healthy_volunteers"]["applicability"] = (
        "optional_observational" if observational else "review_interventional" if interventional else "review_study_type")
    return {
        "source_provenance": provenance,
        "registration_readiness": {
            "status": "not_assessed", "blocking": False,
            "study_type": study_type,
            "overall_status": _source_value(reference, "regulatory.prs.overall_status"),
            "fields": fields,
            "note": "Transport/source validation is not certification of registration completeness. Review current registration definitions and recruitment-status/date rules separately; missing optional upload values are not mapping failures. Deprecated end_date is not a readiness blocker.",
            "upload_documentation": "https://cdn.clinicaltrials.gov/documents/xsd/prs/ProtocolRecordSchema.xsd",
            "registration_definitions": "https://clinicaltrials.gov/policy/protocol-definitions",
        },
    }


def generate(
    template_path: Path,
    output_path: Path,
    reference: Mapping[str, Any],
    narrative: Mapping[str, Any],
    *,
    structural_template: Path | None = None,
    check_output: bool = True,
) -> dict[str, Any]:
    tree = ET.parse(template_path); root = tree.getroot(); study = _study(root)
    study_type = _text(get_path(reference, "regulatory.prs.study_type")).casefold()
    design = study.find("study_design")
    if design is not None:
        remove = "observational_design" if study_type == "interventional" else "interventional_design"
        node = design.find(remove)
        if node is not None: design.remove(node)
        if design.text: design.text = TOKEN.sub("", design.text)
        for child in design:
            if child.tail: child.tail = TOKEN.sub("", child.tail)
    _fill_repeated(study, reference)
    fields = _fields(reference, narrative)
    for element in root.iter():
        if element.text: element.text = TOKEN.sub(lambda match: fields.get(match.group(1), ""), element.text)
        if element.tail: element.tail = TOKEN.sub(lambda match: fields.get(match.group(1), ""), element.tail)
    ET.indent(tree, space="  "); output_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(output_path, encoding="utf-8", xml_declaration=True)
    if not check_output:
        return {"artifact": "xml", "path": output_path.name, "status": "unreviewed", "findings": []}
    findings = validate_output(
        output_path,
        reference,
        structural_template or template_path,
        generation_template=template_path,
    )
    return {"artifact": "xml", "path": output_path.name, "status": "passed" if not findings else "blocked", "findings": findings, "counts": repeated_counts(output_path), **quality_report(output_path, reference)}


def validate_output(
    path: Path,
    reference: Mapping[str, Any],
    structural_template: Path,
    *,
    generation_template: Path | None = None,
) -> list[dict[str, str]]:
    findings = []
    try:
        raw = path.read_text(encoding="utf-8"); ET.parse(path)
    except (OSError, UnicodeError, ET.ParseError) as exc: return [{"category": "xml", "field": path.name, "issue": f"Invalid XML: {exc}"}]
    actual, expected = repeated_counts(path), expected_counts(reference)
    for tag, count in expected.items():
        if actual[tag] != count: findings.append({"category": "xml", "field": tag, "issue": f"Expected {count} source-derived blocks; generated {actual[tag]}."})
    structure_differences = compare_structure(structural_template, path)
    if generation_template is not None:
        try:
            expected_study = _study(ET.parse(generation_template).getroot())
            actual_study = _study(ET.parse(path).getroot())
            expected_design = expected_study.find("study_design")
            actual_design = actual_study.find("study_design")
            actual_branch = next((node for node in (list(actual_design) if actual_design is not None else []) if node.tag in {"interventional_design", "observational_design"}), None)
            expected_branch = expected_design.find(actual_branch.tag) if expected_design is not None and actual_branch is not None else None
            if actual_branch is None or expected_branch is None:
                structure_differences.append("clinical_study/study_design: selected design branch is missing from the governed generation template")
            else:
                def compare_branch(expected: ET.Element, actual: ET.Element, branch_path: str) -> None:
                    expected_tags = [child.tag for child in expected]
                    actual_tags = [child.tag for child in actual]
                    if expected_tags != actual_tags:
                        structure_differences.append(
                            f"{branch_path}: direct-child names or ordering differ"
                        )
                    for expected_child, actual_child in zip(expected, actual):
                        if expected_child.tag == actual_child.tag:
                            compare_branch(
                                expected_child,
                                actual_child,
                                f"{branch_path}/{expected_child.tag}",
                            )

                compare_branch(
                    expected_branch,
                    actual_branch,
                    f"clinical_study/study_design/{actual_branch.tag}",
                )
        except (OSError, ET.ParseError, ValueError) as exc:
            structure_differences.append(f"PRS XML branch-template parse error: {exc}")
    for difference in structure_differences: findings.append({"category": "xml", "field": "structure", "issue": difference})
    return findings


__all__ = ["ScreeningIntervalRequirement", "compare_structure", "expected_counts", "generate", "repeated_counts", "screening_interval_requirement", "structural_signature", "validate_output", "quality_report"]
