"""ClinicalTrials.gov PRS XML mapper and structural/semantic validator."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping
from xml.etree import ElementTree as ET

from contracts import get_path, meaningful


TOKEN = re.compile(r"\{[#/^]?([A-Za-z_][A-Za-z0-9_.\-\[\]()&]*)\}")
REPEATED = ("intervention", "location", "arm_group", "primary_outcome", "secondary_outcome", "other_outcome")
ET.register_namespace("prs", "http://clinicaltrials.gov/prs")

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
    parts = _text(value).split(",", 1)[0].split()
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


def _contact_fields(value: Mapping[str, Any]) -> dict[str, str]:
    first, middle, last = _name(_mapping_value(value, "name", "full_name"))
    return {
        "first_name": _mapping_value(value, "first_name", "given_name") or first,
        "middle_name": _mapping_value(value, "middle_name") or middle,
        "last_name": _mapping_value(value, "last_name", "family_name", "surname") or last,
        "degrees": _mapping_value(value, "degrees", "degree", "title"),
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
    """Return the approved total count, never a concatenation of every number."""
    match = re.search(r"(?<!\w)(\d[\d,]*)(?!\w)", _text(value))
    return match.group(1).replace(",", "") if match else ""


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
    pi_first, pi_middle, pi_last = _name(pi.get("name"))
    contact_first, contact_middle, contact_last = _name(coordinator.get("name"))
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
            investigators = site.get("investigators") if isinstance(site.get("investigators"), list) else []
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
    minimum_days = _text(get_path(reference, "procedures.minimum_days_before_screening_without_participation"))
    if minimum_days:
        duration = minimum_days if re.search(r"\bdays?\s*$", minimum_days, re.I) else f"{minimum_days} days"
        participation_scope = "another study"
        for criterion in (*inclusion, *exclusion):
            match = re.search(r"\banother\s+([a-z][a-z -]{0,40}?\s+)?stud(?:y|ies)\b", criterion, re.I)
            if match:
                participation_scope = re.sub(r"\s+", " ", match.group(0)).strip().casefold()
                if participation_scope != "another study":
                    break
        inclusion.append(f"At least {duration} without participation in {participation_scope} before screening")
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
        "overallContactDegrees": _text(coordinator.get("title")), "overallContactPhone": _text(coordinator.get("business_phone")), "overallContactEmail": _text(coordinator.get("email")),
        "overallContactBackupFirstName": overall_backup_fields["first_name"],
        "overallContactBackupMiddleName": overall_backup_fields["middle_name"],
        "overallContactBackupLastName": overall_backup_fields["last_name"],
        "overallContactBackupDegrees": overall_backup_fields["degrees"],
        "overallContactBackupPhone": overall_backup_fields["phone"],
        "overallContactBackupPhoneExt": overall_backup_fields["phone_ext"],
        "overallContactBackupEmail": overall_backup_fields["email"],
        "overallOfficialFirstName": pi_first, "overallOfficialMiddleName": pi_middle, "overallOfficialLastName": pi_last,
        "overallOfficialDegrees": _text(pi.get("title")), "overallOfficialRole": "Principal Investigator", "overallOfficialAffiliation": investigator_affiliation,
        "briefTitle": _text(get_path(reference, "study.short_title")) or title, "officialTitle": title,
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
        "studyTiming": _text(get_path(reference, "regulatory.prs.time_perspective")),
        "patientRegistry": _text(get_path(reference, "regulatory.prs.patient_registry")),
        "targetDurationQuantity": _text(get_path(reference, "regulatory.prs.target_duration_quantity")),
        "targetDurationUnits": _text(get_path(reference, "regulatory.prs.target_duration_units")),
        "allocation": _text(get_path(reference, "regulatory.prs.allocation")),
        "interventionModel": _text(get_path(reference, "regulatory.prs.intervention_model")), "primaryPurpose": _text(get_path(reference, "regulatory.prs.primary_purpose")),
        "masking": _text(get_path(reference, "design.masking")), "numberOfArms": str(len(_items(reference, "design.arms"))),
        "numberOfGroups": str(len(_items(reference, "design.arms"))), "condition": _text(get_path(reference, "study.condition")),
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
        "briefTitle": _source_value(reference, "study.short_title", "study.title"),
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


def _fill_repeated(study: ET.Element, reference: Mapping[str, Any]) -> None:
    interventions = _items(reference, "design.interventions") or ([{"type": get_path(reference, "design.intervention_type"), "name": get_path(reference, "design.intervention_name"), "description": get_path(reference, "design.intervention_description"), "arm_group_label": _text((get_path(reference, "design.arms", [{}]) or [{}])[0])}] if meaningful(get_path(reference, "design.intervention_name")) else [])
    for node, item in zip(_resize(study, "intervention", len(interventions)), interventions):
        _set(node, "intervention_type", item.get("intervention_type") or item.get("type")); _set(node, "intervention_name", item.get("intervention_name") or item.get("name"))
        _set(node, "intervention_description/textblock", item.get("intervention_description") or item.get("description")); _set(node, "arm_group_label", item.get("arm_group_label") or item.get("armGroupLabel"))
    arms = _items(reference, "design.arms")
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
        facility = site.get("facility") if isinstance(site.get("facility"), Mapping) else {}
        address = facility.get("address") if isinstance(facility.get("address"), Mapping) else {}
        city = address.get("city") or facility.get("city")
        state = address.get("state") or facility.get("state")
        country = address.get("country") or facility.get("country")
        postal_code = address.get("zip") or facility.get("zip") or facility.get("postal_code")
        contact = site.get("contact") if isinstance(site.get("contact"), Mapping) else {}; investigator = (site.get("investigators") or [{}])[0]
        contact_fields = _contact_fields(contact)
        backup_fields = _contact_fields(_site_backup_contact(site))
        investigator_fields = _contact_fields(investigator)
        _set(node, "status", site.get("status")); _set(node, "facility/name", facility.get("name")); _set(node, "facility/address/city", city); _set(node, "facility/address/state", state); _set(node, "facility/address/country", country); _set(node, "facility/address/zip", postal_code)
        for field, value in contact_fields.items():
            _set(node, f"contact/{field}", value)
        for field, value in backup_fields.items():
            _set(node, f"contact_backup/{field}", value)
        for field in ("first_name", "middle_name", "last_name", "degrees"):
            _set(node, f"investigator/{field}", investigator_fields[field])
        _set(node, "investigator/role", investigator.get("role"))


def expected_counts(reference: Mapping[str, Any]) -> dict[str, int]:
    interventions = _items(reference, "design.interventions")
    if not interventions and meaningful(get_path(reference, "design.intervention_name")): interventions = [{}]
    return {"intervention": len(interventions), "arm_group": len(_items(reference, "design.arms")), "primary_outcome": len(_items(reference, "endpoints.primary")), "secondary_outcome": len(_items(reference, "endpoints.secondary")), "other_outcome": len(_items(reference, "endpoints.other")), "location": len(get_path(reference, "sites", []) or [])}


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
        expected_present = [tag for tag in expected_tags if tag in actual_tags or tag not in REPEATED]
        if expected_present != actual_tags:
            findings.append(f"{path}: direct-child names or ordering differ")
        for tag in expected_present:
            if tag in actual_by_tag:
                if tag != "__study_design_branch__":
                    compare(expected_by_tag[tag], actual_by_tag[tag], f"{path}/{tag}", findings)
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


def generate(
    template_path: Path,
    output_path: Path,
    reference: Mapping[str, Any],
    narrative: Mapping[str, Any],
    *,
    structural_template: Path | None = None,
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
    findings = validate_output(
        output_path,
        reference,
        structural_template or template_path,
        generation_template=template_path,
    )
    return {"artifact": "xml", "path": output_path.name, "status": "passed" if not findings else "blocked", "findings": findings, "counts": repeated_counts(output_path)}


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
    except (OSError, ET.ParseError) as exc: return [{"category": "xml", "field": path.name, "issue": f"Invalid XML: {exc}"}]
    if TOKEN.search(raw): findings.append({"category": "xml", "field": path.name, "issue": "Unresolved template token remains."})
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
            actual_branch = next((node for node in list(actual_design or []) if node.tag in {"interventional_design", "observational_design"}), None)
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
    study = _study(ET.parse(path).getroot())
    for tag in ("provider_study_id", "org_name", "brief_title", "official_title", "brief_summary", "detailed_description", "enrollment", "study_type"):
        node = study.find(f".//{tag}")
        if node is None or not _text("".join(node.itertext())): findings.append({"category": "xml", "field": tag, "issue": "Required PRS value is empty."})
    scalar_template = generation_template or structural_template
    narrative = {
        "brief_summary": {"text": _text(study.findtext("brief_summary/textblock"))},
        "detailed_description": {"text": _text(study.findtext("detailed_description/textblock"))},
    }
    expected_fields = _fields(reference, narrative)
    for target_path, token_name in _scalar_template_bindings(scalar_template):
        if token_name in {"briefSummary", "detailedDescription"}:
            continue
        target = study.find(target_path)
        if target is None and any(branch in target_path for branch in ("interventional_design", "observational_design")):
            continue
        expected_value = _text(expected_fields.get(token_name))
        actual_value = _text("".join(target.itertext())) if target is not None else ""
        if actual_value != expected_value:
            findings.append({
                "category": "xml",
                "field": target_path,
                "issue": f"Generated PRS scalar value does not match source mapping {token_name}.",
            })
    scalar_sources = {
        "uid": _stable_study_uid(reference),
        "id_info/provider_study_id": _source_value(reference, "regulatory.prs.provider_study_id", "meta.protocol_number"),
        "id_info/org_name": _source_value(reference, "regulatory.prs.org_name", "regulatory.prs.organization_name", "parties.sponsor.name"),
        "brief_title": _source_value(reference, "study.short_title", "study.title"),
        "official_title": get_path(reference, "study.title"),
        "condition": get_path(reference, "study.condition"),
        "study_design/study_type": get_path(reference, "regulatory.prs.study_type"),
        "start_date": get_path(reference, "regulatory.prs.start_date"),
        "start_date_type": get_path(reference, "regulatory.prs.start_date_type"),
        "verification_date": get_path(reference, "regulatory.prs.verification_date"),
        "primary_compl_date": get_path(reference, "regulatory.prs.primary_completion_date"),
        "primary_compl_date_type": get_path(reference, "regulatory.prs.primary_completion_date_type"),
        "last_follow_up_date": get_path(reference, "regulatory.prs.study_completion_date") or get_path(reference, "regulatory.prs.last_follow_up_date"),
        "last_follow_up_date_type": get_path(reference, "regulatory.prs.study_completion_date_type") or get_path(reference, "regulatory.prs.last_follow_up_date_type"),
        "study_design/observational_design/timing": get_path(reference, "regulatory.prs.time_perspective"),
    }
    for target_path, expected_value in scalar_sources.items():
        if not meaningful(expected_value):
            continue
        actual_value = study.findtext(target_path)
        if _text(actual_value) != _text(expected_value):
            findings.append({"category": "xml", "field": target_path.rsplit("/", 1)[-1], "issue": "Generated PRS value does not match the approved source."})
    for target_path, source_paths in SOURCE_SCALAR_BINDINGS.items():
        expected_value = _source_value(reference, *source_paths)
        if expected_value and _text(study.findtext(target_path)) != expected_value:
            findings.append({"category": "xml", "field": target_path.rsplit("/", 1)[-1], "issue": f"Generated PRS value does not preserve approved source field {source_paths[0]}."})
    responsible = _merged_mapping(
        reference,
        "regulatory.prs.responsible_party",
        "parties.responsible_party",
    )
    responsible_sources = {
        "sponsors/resp_party/name_title": _mapping_value(responsible, "name_title", "name"),
        "sponsors/resp_party/organization": _mapping_value(responsible, "organization", "affiliation"),
        "sponsors/resp_party/email": _mapping_value(responsible, "email"),
        "sponsors/resp_party/phone": _mapping_value(responsible, "phone", "business_phone", "office_phone"),
        "sponsors/resp_party/phone_ext": _mapping_value(responsible, "phone_ext", "extension", "ext"),
        "sponsors/resp_party/resp_party_type": _source_value(
            reference,
            "regulatory.prs.responsible_party_type",
            "regulatory.prs.resp_party_type",
        ) or _mapping_value(responsible, "responsible_party_type", "resp_party_type", "type"),
        "sponsors/resp_party/investigator_username": _mapping_value(responsible, "investigator_username", "username"),
        "sponsors/resp_party/investigator_title": _mapping_value(responsible, "investigator_title", "title"),
        "sponsors/resp_party/investigator_affiliation": _mapping_value(responsible, "investigator_affiliation"),
    }
    for target_path, expected_value in responsible_sources.items():
        if expected_value and _text(study.findtext(target_path)) != expected_value:
            findings.append({
                "category": "xml",
                "field": target_path.rsplit("/", 1)[-1],
                "issue": "Generated PRS value does not preserve approved source field parties.responsible_party/regulatory.prs.responsible_party.",
            })
    overall_contact_backup = _merged_mapping(
        reference,
        "regulatory.prs.overall_contact_backup",
        "regulatory.prs.overall_backup_contact",
        "parties.overall_contact_backup",
        "parties.study_coordinator_backup",
        "parties.backup_contact",
    )
    for field, expected_value in _contact_fields(overall_contact_backup).items():
        target_path = f"overall_contact_backup/{field}"
        if expected_value and _text(study.findtext(target_path)) != expected_value:
            findings.append({
                "category": "xml",
                "field": field,
                "issue": "Generated PRS value does not preserve approved source field regulatory.prs.overall_contact_backup/contact alias.",
            })
    source_sites = [item for item in get_path(reference, "sites", []) or [] if isinstance(item, Mapping)]
    generated_locations = study.findall("location")
    for index, site in enumerate(source_sites, start=1):
        if index > len(generated_locations):
            continue
        location = generated_locations[index - 1]
        for field, expected_value in _contact_fields(_site_backup_contact(site)).items():
            if expected_value and _text(location.findtext(f"contact_backup/{field}")) != expected_value:
                findings.append({
                    "category": "xml",
                    "field": f"location[{index}].contact_backup.{field}",
                    "issue": f"Generated PRS value does not preserve approved source field sites[{index - 1}].contact_backup/contact alias.",
                })

    def require_repeated_value(node: ET.Element, target_path: str, expected_value: Any, field: str) -> None:
        if meaningful(expected_value) and _text(node.findtext(target_path)) != _text(expected_value):
            findings.append({
                "category": "xml",
                "field": field,
                "issue": "Generated PRS repeated-block value does not match the approved source.",
            })

    interventions = _items(reference, "design.interventions")
    if not interventions and meaningful(get_path(reference, "design.intervention_name")):
        interventions = [{
            "type": get_path(reference, "design.intervention_type"),
            "name": get_path(reference, "design.intervention_name"),
            "description": get_path(reference, "design.intervention_description"),
            "arm_group_label": _text((get_path(reference, "design.arms", [{}]) or [{}])[0]),
        }]
    for index, (node, item) in enumerate(zip(study.findall("intervention"), interventions), start=1):
        require_repeated_value(node, "intervention_type", item.get("intervention_type") or item.get("type"), f"intervention[{index}].intervention_type")
        require_repeated_value(node, "intervention_name", item.get("intervention_name") or item.get("name"), f"intervention[{index}].intervention_name")
        require_repeated_value(node, "intervention_description/textblock", item.get("intervention_description") or item.get("description"), f"intervention[{index}].intervention_description")
        require_repeated_value(node, "arm_group_label", item.get("arm_group_label") or item.get("armGroupLabel"), f"intervention[{index}].arm_group_label")

    arms = _items(reference, "design.arms")
    for index, (node, item) in enumerate(zip(study.findall("arm_group"), arms), start=1):
        require_repeated_value(node, "arm_group_label", item.get("arm_group_label") or item.get("label") or item.get("name"), f"arm_group[{index}].arm_group_label")
        require_repeated_value(node, "arm_type", item.get("arm_type") or item.get("type"), f"arm_group[{index}].arm_type")
        require_repeated_value(node, "arm_group_description/textblock", item.get("description"), f"arm_group[{index}].arm_group_description")

    for tag, source_path in (("primary_outcome", "endpoints.primary"), ("secondary_outcome", "endpoints.secondary"), ("other_outcome", "endpoints.other")):
        for index, (node, item) in enumerate(zip(study.findall(tag), _items(reference, source_path)), start=1):
            require_repeated_value(node, "outcome_measure", item.get("outcome_measure") or item.get("measure") or item.get("label"), f"{tag}[{index}].outcome_measure")
            require_repeated_value(node, "outcome_time_frame", item.get("outcome_time_frame") or item.get("time_frame") or item.get("time_point"), f"{tag}[{index}].outcome_time_frame")
            require_repeated_value(node, "outcome_description/textblock", item.get("description"), f"{tag}[{index}].outcome_description")

    for index, (node, site) in enumerate(zip(generated_locations, source_sites), start=1):
        facility = site.get("facility") if isinstance(site.get("facility"), Mapping) else {}
        address = facility.get("address") if isinstance(facility.get("address"), Mapping) else {}
        require_repeated_value(node, "status", site.get("status"), f"location[{index}].status")
        require_repeated_value(node, "facility/name", facility.get("name"), f"location[{index}].facility.name")
        for field, expected_value in (
            ("city", address.get("city") or facility.get("city")),
            ("state", address.get("state") or facility.get("state")),
            ("country", address.get("country") or facility.get("country")),
            ("zip", address.get("zip") or facility.get("zip") or facility.get("postal_code")),
        ):
            require_repeated_value(node, f"facility/address/{field}", expected_value, f"location[{index}].facility.address.{field}")
        contact = site.get("contact") if isinstance(site.get("contact"), Mapping) else {}
        investigator = (site.get("investigators") or [{}])[0]
        for field, expected_value in _contact_fields(contact).items():
            require_repeated_value(node, f"contact/{field}", expected_value, f"location[{index}].contact.{field}")
        investigator_fields = _contact_fields(investigator)
        for field, expected_value in {
            **{key: investigator_fields[key] for key in ("first_name", "middle_name", "last_name", "degrees")},
            "role": investigator.get("role"),
        }.items():
            require_repeated_value(node, f"investigator/{field}", expected_value, f"location[{index}].investigator.{field}")
    expected_enrollment = _enrollment_count(get_path(reference, "population.sample_size"))
    if expected_enrollment and _text(study.findtext("enrollment")) != expected_enrollment:
        findings.append({"category": "xml", "field": "enrollment", "issue": "Generated enrollment does not match the approved total sample size."})
    for tag, source_path in (("primary_outcome", "endpoints.primary"), ("secondary_outcome", "endpoints.secondary"), ("other_outcome", "endpoints.other")):
        source_items = get_path(reference, source_path, [])
        if tag == "primary_outcome" and (not isinstance(source_items, list) or not source_items):
            findings.append({"category": "xml", "field": source_path, "issue": "Primary outcomes must be supplied as a non-empty structured list."})
        elif source_items not in (None, "", []) and not isinstance(source_items, list):
            findings.append({"category": "xml", "field": source_path, "issue": "Outcome source data must be a structured list."})
        for index, node in enumerate(study.findall(tag), start=1):
            for child in ("outcome_measure", "outcome_time_frame"):
                target = node.find(child)
                if target is None or not _text("".join(target.itertext())):
                    findings.append({"category": "xml", "field": f"{tag}[{index}].{child}", "issue": "Required outcome value is empty."})
            expected_uid = _stable_study_uid(reference)
            target = node.find("uid")
            if target is None or _text("".join(target.itertext())) != expected_uid:
                findings.append({"category": "xml", "field": f"{tag}[{index}].uid", "issue": "Stable shared outcome UID was not populated."})
    return findings


__all__ = ["compare_structure", "expected_counts", "generate", "repeated_counts", "structural_signature", "validate_output"]
