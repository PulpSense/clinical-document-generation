#!/usr/bin/env python3
"""Build n8n-compatible prospective protocol, ICF, and XML fields."""

from __future__ import annotations

import argparse
import calendar
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STANDARD_REFERENCE = "reference/study.reference.json"
NBSP_BULLET = "•\u00a0\u00a0\u00a0\u00a0"
OPTIONAL_FIELDS = {
    "fundingSourceClarification",
    "fundingSourceName",
    "fundingSourceAdress",
    "subInvestigatorHas",
    "subInvestigatorName",
    "controlArticle(s)",
    "AI_benefits",
    "AI_payment",
    "icfPayment",
    "coordinatorMiddle",
    "investigatorMiddle",
    "InvestigatorLast",
    "irbEmail",
    "irbPhone",
}
REQUIRED_AI_FIELDS = {
    "AI_populationShort",
    "AI_introduction",
    "AI_populationLong",
    "AI_inclusionCriteria",
    "AI_exclusionCriteria",
    "AI_studyDesignLong",
    "AI_methods",
    "AI_visitSchedule",
    "AI_visitScheduleDetails",
    "AI_measurements",
    "AI_measurementsDetails",
    "AI_analysisDataSets",
    "AI_statisticalMethodology",
    "AI_statisticalConsiderations",
    "AI_risks",
    "AI_shortTitle",
    "AI_studyPurpose",
    "AI_icfVisitsOverview",
    "AI_visitsDetails",
    "AI_visitsAndLength",
    "AI_interventionPossibleSideEffects",
}


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


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
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        rendered = []
        for item in value:
            item_text = text(item)
            if item_text:
                rendered.append(item_text)
        return "\n".join(rendered)
    if isinstance(value, dict):
        for key in ("text", "name", "title", "label", "description", "measure", "Article"):
            if value.get(key):
                return text(value[key])
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def first_text(*values: Any) -> str:
    for value in values:
        rendered = text(value).strip()
        if rendered:
            return rendered
    return ""


def normalize_symbols(value: str) -> str:
    return value.replace("≥", ">=").replace("≤", "<=")


def bulletize(value: Any) -> str:
    rendered = normalize_symbols(text(value)).strip()
    if not rendered:
        return ""
    lines = []
    for raw_line in rendered.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^[•*\-]\s*", "", line)
        lines.append(NBSP_BULLET + line)
    return "\n".join(lines)


def join_paragraphs(*values: Any) -> str:
    paragraphs = [text(value).strip() for value in values if text(value).strip()]
    return "\n\n".join(paragraphs)


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


def initials(name: str) -> str:
    first_part = name.split(",", 1)[0].strip()
    value = "".join(part[0].upper() for part in re.split(r"\s+", first_part) if part)
    return value or "PROT"


def protocol_number(reference: dict) -> str:
    explicit = first_text(get_path(reference, "meta.protocol_number"))
    if explicit:
        return explicit
    pi_name = first_text(get_path(reference, "parties.principal_investigator.name"))
    return f"{initials(pi_name)}-{datetime.now(timezone.utc).strftime('%y')}-01"


def add_months(base: datetime, months: int) -> datetime:
    month = base.month - 1 + months
    year = base.year + month // 12
    month = month % 12 + 1
    day = min(base.day, calendar.monthrange(year, month)[1])
    return base.replace(year=year, month=month, day=day)


def date_field(reference: dict, months: int = 0, fmt: str = "%Y-%m-%d") -> str:
    explicit = first_text(get_path(reference, "meta.date"))
    if months == 0 and explicit:
        return explicit
    now = datetime.now(timezone.utc)
    return add_months(now, months).strftime(fmt)


def first_site(reference: dict) -> dict:
    sites = reference.get("sites")
    if isinstance(sites, list) and sites and isinstance(sites[0], dict):
        return sites[0]
    return {}


def address(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        full_address = text(value.get("full_address")).strip()
        if full_address:
            return full_address
        ordered = ["line1", "address_line1", "street", "city", "state", "country", "zip"]
        return ", ".join(text(value.get(key)).strip() for key in ordered if text(value.get(key)).strip())
    return text(value)


def street_address(value: Any) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return text(value)
    street = first_text(value.get("line1"), value.get("address_line1"), value.get("street"))
    if street:
        return street
    full_address = text(value.get("full_address")).strip()
    city = text(value.get("city")).strip()
    marker = f", {city}," if city else ""
    if full_address and marker and marker in full_address:
        return full_address.split(marker, 1)[0]
    return full_address


def list_article_names(value: Any) -> str:
    if isinstance(value, list):
        names = []
        for item in value:
            if isinstance(item, dict):
                names.append(first_text(item.get("Article"), item.get("article"), item.get("name"), item.get("label")))
            else:
                names.append(text(item))
        return "\n".join(item for item in names if item)
    return text(value)


def criteria_text(items: Any) -> str:
    if isinstance(items, list):
        return "\n".join(text(item) for item in items if text(item))
    return text(items)


#: Columns of Table 15.1, whose caption pairs visits with their assessments.
ASSESSMENT_TABLE_HEADER = ("Visit Number", "Visit Name", "Visit Window", "Assessments")


def normalized_matrix(value: Any) -> dict | None:
    """A generated Data-Driven Table matrix, or None when there is not one."""
    if not isinstance(value, dict):
        return None
    cells = value.get("cells")
    if not isinstance(cells, list) or not cells:
        return None
    try:
        columns = int(value.get("totalColumns") or 0)
    except (TypeError, ValueError):
        return None
    if columns <= 0:
        return None
    rows = -(-len(cells) // columns)
    return {
        "cells": [text(cell) for cell in cells],
        "totalColumns": columns,
        "totalRows": rows,
    }


def assessment_matrix(reference: dict, visit_table: list[dict]) -> dict:
    """Build Table 15.1 from data the branch already holds.

    No Required Source Input carries an assessment-per-visit matrix, so a
    generated one is used when the model supplied it and the visit schedule
    supplies it otherwise. A study with no assessment detail still renders a
    complete table; the assessments column falls back to the study-level text.
    """
    generated = normalized_matrix(get_path(reference, "generated.protocol.visitsTable"))
    if generated:
        return generated

    if not visit_table:
        # Nothing to tabulate. The section is empty and the gates say so,
        # rather than a lone header row implying a table that has no content.
        return {"cells": [], "totalColumns": 0, "totalRows": 0}

    study_assessments = first_text(
        get_path(reference, "procedures.assessments"),
        get_path(reference, "generated.protocol.measurements"),
        get_path(reference, "procedures.assessment_details"),
    )
    cells = list(ASSESSMENT_TABLE_HEADER)
    for row in visit_table:
        cells.extend(
            [
                first_text(row.get("visitNumber")),
                first_text(row.get("visitName")),
                first_text(row.get("visitWindow")),
                first_text(row.get("assessments")) or study_assessments,
            ]
        )
    columns = len(ASSESSMENT_TABLE_HEADER)
    return {"cells": cells, "totalColumns": columns, "totalRows": len(cells) // columns}


def visit_rows(reference: dict) -> list[dict]:
    generated = reference.get("generated") if isinstance(reference.get("generated"), dict) else {}
    protocol = generated.get("protocol") if isinstance(generated.get("protocol"), dict) else {}
    rows = (
        protocol.get("visitScheduleTable")
        or protocol.get("visit_schedule_table")
        or get_path(reference, "procedures.visit_schedule_table")
        or []
    )
    if isinstance(rows, list) and rows:
        return [row for row in rows if isinstance(row, dict)]
    visit_schedule = first_text(
        protocol.get("visitSchedule"),
        get_path(reference, "procedures.visit_schedule"),
        get_path(reference, "study.timeline"),
    )
    if visit_schedule:
        return [
            {
                "visitNumber": "1",
                "visitName": visit_schedule,
                "visitWindow": first_text(get_path(reference, "study.timeline"), "Per protocol"),
                "CRFnumber": "1",
            }
        ]
    return []


def outcome_item(endpoint: dict) -> dict:
    description = endpoint.get("outcome_description")
    if isinstance(description, dict):
        description_text = first_text(description.get("textblock"), description.get("text"))
    else:
        description_text = first_text(description, endpoint.get("description"), endpoint.get("text"))
    return {
        "outcome_measure": first_text(endpoint.get("outcome_measure"), endpoint.get("measure"), endpoint.get("text")),
        "outcome_time_frame": first_text(endpoint.get("outcome_time_frame"), endpoint.get("time_frame"), endpoint.get("timeframe"), "Per protocol"),
        "outcome_description": {"textblock": description_text},
    }


def outcome_json(reference: dict, key: str) -> str:
    endpoints = get_path(reference, f"endpoints.{key}") or []
    if not isinstance(endpoints, list):
        endpoints = [{"text": text(endpoints)}] if text(endpoints) else []
    return json.dumps([outcome_item(item if isinstance(item, dict) else {"text": text(item)}) for item in endpoints])


def enrollment_value(reference: dict) -> str:
    generated = reference.get("generated") if isinstance(reference.get("generated"), dict) else {}
    protocol = generated.get("protocol") if isinstance(generated.get("protocol"), dict) else {}
    value = first_text(protocol.get("enrollment"), get_path(reference, "population.sample_size"))
    match = re.search(r"\d+", value)
    return match.group(0) if match else value


def location_array(reference: dict) -> str:
    locations = []
    for site in reference.get("sites") or []:
        if not isinstance(site, dict):
            continue
        facility = site.get("facility") if isinstance(site.get("facility"), dict) else {}
        site_address = facility.get("address") if isinstance(facility.get("address"), dict) else {}
        locations.append(
            {
                "facility": first_text(facility.get("name")),
                "city": first_text(site_address.get("city")),
                "state": first_text(site_address.get("state")),
                "country": first_text(site_address.get("country")),
                "zip": first_text(site_address.get("zip")),
            }
        )
    return json.dumps(locations, ensure_ascii=False)


def display_path(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.name


def build_fields(reference: dict) -> dict:
    generated = reference.get("generated") if isinstance(reference.get("generated"), dict) else {}
    protocol = generated.get("protocol") if isinstance(generated.get("protocol"), dict) else {}
    icf = generated.get("icf") if isinstance(generated.get("icf"), dict) else {}
    site = first_site(reference)
    facility = site.get("facility") if isinstance(site.get("facility"), dict) else {}
    facility_address = facility.get("address") if isinstance(facility.get("address"), dict) else {}

    pi_name = first_text(get_path(reference, "parties.principal_investigator.name"))
    pi_first, pi_middle, pi_last = split_name(pi_name)
    coordinator_name = first_text(get_path(reference, "parties.study_coordinator.name"))
    coordinator_first, coordinator_middle, coordinator_last = split_name(coordinator_name)
    subinvestigator = first_text(
        get_path(reference, "parties.sub_investigator.name"),
        get_path(reference, "parties.subinvestigator.name"),
        get_path(reference, "parties.sub_investigator"),
    )
    funding_name = first_text(get_path(reference, "parties.funding_source.name"))
    funding_address = first_text(address(get_path(reference, "parties.funding_source.address")))
    visit_table = visit_rows(reference)

    study_design_short = first_text(get_path(reference, "design.study_design"))
    study_arm = first_text(protocol.get("studyArm"), get_path(reference, "design.study_arm"))
    sampling_method = "Probability Simple" if study_arm.lower() == "single arm" else "Non-Probability Simple"
    icf_payment = first_text(
        icf.get("icfPayment"),
        icf.get("payment"),
        get_path(reference, "risks_benefits.compensation_or_reimbursement"),
        get_path(reference, "risks_benefits.compensation"),
        get_path(reference, "risks_benefits.reimbursement"),
    )
    facility_address_text = first_text(street_address(facility.get("address")))

    fields = {
        "visitsTable": assessment_matrix(reference, visit_table),
        "studyCordinatorName": coordinator_name,
        "studyCordinatorPhone": first_text(
            get_path(reference, "parties.study_coordinator.business_phone"),
            get_path(reference, "parties.study_coordinator.phone"),
        ),
        "studyCordinatorEmail": first_text(get_path(reference, "parties.study_coordinator.email")),
        "studyCordinator24Phone": first_text(
            get_path(reference, "parties.study_coordinator.office_phone"),
            get_path(reference, "parties.study_coordinator.phone"),
        ),
        "sudyCordinatorOfficePhone": first_text(
            get_path(reference, "parties.study_coordinator.office_phone"),
            get_path(reference, "parties.study_coordinator.phone"),
        ),
        "subInvestigatorHas": "Sub-Investigator" if subinvestigator else "",
        "subInvestigatorName": subinvestigator,
        "protocolNumber": protocol_number(reference),
        "fundingSourceClarification": (
            "\n\n" + first_text(get_path(reference, "parties.funding_source.clarification"), "funding only, this is an investigator-initiated study")
        )
        if funding_name
        else "",
        "fundingSourceName": f"\n{funding_name}" if funding_name else "",
        "fundingSourceAdress": f"\n{funding_address}" if funding_address else "",
        "title": first_text(get_path(reference, "study.title")),
        "ibrName": first_text(get_path(reference, "parties.irb.name"), get_path(reference, "parties.ethics_committee.name")),
        "ibrAdress": first_text(get_path(reference, "parties.irb.address"), get_path(reference, "parties.ethics_committee.address")),
        "sponsortName": first_text(get_path(reference, "parties.sponsor.name")),
        "sponsortAdress": first_text(address(get_path(reference, "parties.sponsor.address"))),
        "testArticle(s)": first_text(
            list_article_names(get_path(reference, "design.test_articles")),
            list_article_names(get_path(reference, "design.arms")),
            get_path(reference, "design.intervention_name"),
            get_path(reference, "design.intervention.name"),
            get_path(reference, "source.n8n_form_fields.areThereAnyTestArticles"),
        ),
        "investigatorName": pi_name,
        "investigatorTitle": first_text(get_path(reference, "parties.principal_investigator.title")),
        "objective": first_text(criteria_text(get_path(reference, "objectives.primary"))),
        "controlArticle(s)": first_text(list_article_names(get_path(reference, "design.control_articles"))),
        "sampleSize": first_text(get_path(reference, "population.sample_size")),
        "AI_populationShort": first_text(protocol.get("populationShort"), get_path(reference, "population.study_population")),
        "sitesNumber": first_text(get_path(reference, "design.number_of_sites"), len(reference.get("sites") or [])),
        "studyDesignShort": study_design_short,
        "AI_masked": first_text(protocol.get("masked"), get_path(reference, "design.masking"), "Not applicable"),
        "AI_variables": first_text(protocol.get("variables"), join_paragraphs(get_path(reference, "endpoints.primary"), get_path(reference, "endpoints.secondary"))),
        "AI_duration": first_text(protocol.get("duration"), get_path(reference, "study.timeline")),
        "AI_introduction": first_text(protocol.get("introduction"), join_paragraphs(protocol.get("introduction_background"), protocol.get("introduction_purpose"))),
        "AI_populationLong": normalize_symbols(first_text(protocol.get("populationLong"), protocol.get("population_long"), get_path(reference, "population.study_population"))),
        "AI_inclusionCriteria": bulletize(first_text(protocol.get("inclusionCriteria"), protocol.get("inclusion_criteria_bullets"), criteria_text(get_path(reference, "population.inclusion_criteria")))),
        "AI_exclusionCriteria": bulletize(first_text(protocol.get("exclusionCriteria"), protocol.get("exclusion_criteria_bullets"), criteria_text(get_path(reference, "population.exclusion_criteria")))),
        "AI_studyDesignLong": first_text(protocol.get("studyDesignLong"), protocol.get("study_design"), study_design_short),
        "AI_methods": first_text(protocol.get("methods"), get_path(reference, "procedures.methods")),
        "AI_visitSchedule": first_text(
            protocol.get("visitSchedule"),
            get_path(reference, "procedures.visit_schedule"),
            get_path(reference, "study.timeline"),
        ),
        "AI_visitScheduleDetails": first_text(
            protocol.get("visitScheduleDetails"),
            get_path(reference, "procedures.visit_schedule_details"),
            protocol.get("studyProcedure"),
            protocol.get("study_procedure"),
            get_path(reference, "procedures.study_procedure"),
        ),
        "AI_measurements": first_text(protocol.get("measurements"), get_path(reference, "procedures.assessments"), get_path(reference, "procedures.data_sources")),
        "AI_measurementsDetails": first_text(
            protocol.get("measurementsDetails"),
            get_path(reference, "procedures.assessment_details"),
            protocol.get("studyProcedure"),
            protocol.get("study_procedure"),
            get_path(reference, "procedures.study_procedure"),
        ),
        # Structured rows drive the protocol's Data-Driven visit table. The
        # newline-joined `AI_visit*` fields below stay as compatibility values
        # for older external templates; they cannot satisfy a real visit table.
        "visits": [
            {
                "visitNumber": first_text(row.get("visitNumber")),
                "visitName": first_text(row.get("visitName")),
                "visitWindow": first_text(row.get("visitWindow")),
                "CRFnumber": first_text(row.get("CRFnumber")),
            }
            for row in visit_table
        ],
        "AI_visitNumber": "\n".join(first_text(row.get("visitNumber")) for row in visit_table),
        "AI_visitName": "\n".join(first_text(row.get("visitName")) for row in visit_table),
        "AI_visitWindow": "\n".join(first_text(row.get("visitWindow")) for row in visit_table),
        "AI_CRFnumber": "\n".join(first_text(row.get("CRFnumber")) for row in visit_table),
        "AI_analysisDataSets": first_text(protocol.get("analysisDataSets"), protocol.get("analysis_data_sets"), get_path(reference, "statistics.analysis_plan")),
        "AI_benefits": first_text(protocol.get("benefits"), get_path(reference, "risks_benefits.benefits")),
        "AI_statisticalMethodology": first_text(protocol.get("statisticalMethodology"), protocol.get("statistical_methodology"), get_path(reference, "statistics.methodology"), get_path(reference, "statistics.analysis_plan")),
        "AI_statisticalConsiderations": first_text(protocol.get("statisticalConsiderations"), protocol.get("statistical_considerations"), get_path(reference, "statistics.software")),
        "sampleSizeJustification": first_text(protocol.get("sampleSizeJustification"), protocol.get("sample_size_justification"), get_path(reference, "population.sample_justification"), get_path(reference, "statistics.sample_size_justification")),
        "totalVisits": first_text(len(visit_table)),
        "AI_risks": first_text(protocol.get("risks"), get_path(reference, "risks_benefits.risks")),
        "date": date_field(reference, fmt="%d %b %Y"),
        "AI_shortTitle": first_text(protocol.get("shortTitle"), get_path(reference, "study.short_title")),
        "startDate": first_text(protocol.get("startDate"), get_path(reference, "procedures.start_date"), date_field(reference, 2)),
        "endDate": first_text(protocol.get("endDate"), get_path(reference, "procedures.end_date"), date_field(reference, 14)),
        "investigatorFirst": first_text(protocol.get("investigatorFirst"), pi_first),
        "investigatorMiddle": first_text(protocol.get("investigatorMiddle"), pi_middle),
        "InvestigatorLast": first_text(protocol.get("investigatorLast"), pi_last),
        "verificationDate": datetime.now(timezone.utc).strftime("%Y-%m"),
        "primaryOutcome": first_text(protocol.get("primaryOutcome"), protocol.get("primary_outcome"), outcome_json(reference, "primary")),
        "secondaryOutcome": first_text(protocol.get("secondaryOutcome"), protocol.get("secondary_outcome"), outcome_json(reference, "secondary")),
        "ibrAffiliation": first_text(get_path(reference, "parties.irb.affiliation"), get_path(reference, "parties.ethics_committee.affiliation")),
        "ibrPhoneNumber": first_text(get_path(reference, "parties.irb.phone"), get_path(reference, "parties.ethics_committee.phone")),
        "ibrEmail": first_text(get_path(reference, "parties.irb.email"), get_path(reference, "parties.ethics_committee.email")),
        "lastFollowUpDate": first_text(get_path(reference, "procedures.last_follow_up_date"), date_field(reference, 14)),
        "primaryCompleteDate": first_text(get_path(reference, "procedures.primary_completion_date"), date_field(reference, 14)),
        "enrollment": enrollment_value(reference),
        "minimumAge": first_text(protocol.get("minimumAge"), get_path(reference, "population.minimum_age"), "N/A"),
        "maximumAge": first_text(protocol.get("maximumAge"), get_path(reference, "population.maximum_age"), "N/A"),
        "groupsNumber": first_text(protocol.get("groups"), get_path(reference, "design.groups"), len(get_path(reference, "design.arms") or [])),
        "coordinatorFirst": first_text(protocol.get("coordinatorFirst"), coordinator_first),
        "coordinatorMiddle": first_text(protocol.get("coordinatorMiddle"), coordinator_middle),
        "coordinatorLast": first_text(protocol.get("coordinatorLast"), coordinator_last),
        "locationArray": location_array(reference),
        "regulatedDrug": "Yes" if get_path(reference, "regulatory.fda_regulated_drug") else "No",
        "regulatedDevice": "Yes" if get_path(reference, "regulatory.fda_regulated_device") else "No",
        "interventionType": first_text(get_path(reference, "design.intervention_type"), get_path(reference, "design.intervention.type")),
        "interventionName": first_text(get_path(reference, "design.intervention_name"), get_path(reference, "design.intervention"), get_path(reference, "design.test_articles")),
        "samplingMethod": sampling_method,
        "facilityName": first_text(facility.get("name"), get_path(reference, "parties.sponsor.name")),
        "facilityAddress": facility_address_text,
        "facilityLocation": ", ".join(
            item
            for item in [
                first_text(facility_address.get("city")),
                first_text(facility_address.get("state")),
                first_text(facility_address.get("country")),
                first_text(facility_address.get("zip")),
            ]
            if item
        ),
        "daysBeforeScreening": re.sub(
            r"\s*days?\s*$",
            "",
            first_text(get_path(reference, "procedures.minimum_days_before_screening_without_participation"), "N/A"),
            flags=re.IGNORECASE,
        ),
        "studyPurpose": first_text(icf.get("icfPurpose"), icf.get("study_purpose")),
        "icfEligibilityBullets": bulletize(first_text(icf.get("icfEligibilityBullets"), criteria_text(get_path(reference, "population.inclusion_criteria")))),
        "icfVisitsOverview": first_text(icf.get("icfVisitOverview"), icf.get("visits_overview"), icf.get("procedures"), get_path(reference, "procedures.visit_schedule")),
        "icfVisitsDetails": first_text(icf.get("icfVisitDetails"), icf.get("visits_details"), icf.get("procedures")),
        "icfStudyLenght&Participants": first_text(icf.get("icfStudyLengthAndParticipants"), icf.get("study_length_and_participants"), get_path(reference, "study.timeline"), get_path(reference, "population.sample_size")),
        "icfSideEffects": first_text(icf.get("icfSideEffects"), icf.get("risks"), get_path(reference, "risks_benefits.risks")),
        "icfBenefits": first_text(icf.get("icfBenefits"), icf.get("benefits"), get_path(reference, "risks_benefits.benefits")),
        "icfPayment": icf_payment,
        "facilityCity": first_text(facility_address.get("city")),
    }

    # ICF template aliases from Batch:update ICF Variables1.
    fields.update(
        {
            "sponsorName": fields["sponsortName"],
            "studyTitle": fields["title"],
            "principalInvestigatorName": fields["investigatorName"],
            "sponsorAdress": fields["sponsortAdress"],
            "AI_studyPurpose": fields["studyPurpose"],
            "inclusionCriteria": fields["icfEligibilityBullets"],
            "AI_icfVisitsOverview": fields["icfVisitsOverview"],
            "AI_visitsDetails": fields["icfVisitsDetails"],
            "AI_visitsAndLength": fields["icfStudyLenght&Participants"],
            "AI_interventionPossibleSideEffects": fields["icfSideEffects"],
            "AI_payment": fields["icfPayment"],
            "irbName": fields["ibrName"],
            "irbAdress": fields["ibrAdress"],
            "irbEmail": fields["ibrEmail"],
            "irbPhone": fields["ibrPhoneNumber"],
            "sterlingIrbId": first_text(
                get_path(reference, "parties.irb.id"),
                get_path(reference, "regulatory.sterling_irb_id"),
                get_path(reference, "regulatory.irb_id"),
            ),
            "AI_alternatives": first_text(
                icf.get("alternatives"),
                get_path(reference, "risks_benefits.alternatives"),
                "You may choose not to participate in this study and discuss other available options with your doctor.",
            ),
            "AI_costs": first_text(
                icf.get("costs"),
                get_path(reference, "risks_benefits.costs"),
                "The study team will explain any study-related costs before you decide whether to participate.",
            ),
            "AI_injuryCompensation": first_text(
                icf.get("injury_compensation"),
                get_path(reference, "risks_benefits.injury_compensation"),
                "The study team will explain what medical care or compensation may be available for a research-related injury.",
            ),
            "AI_privacy": first_text(
                icf.get("privacy"),
                get_path(reference, "risks_benefits.privacy"),
                "Your research information will be stored securely and accessed only by authorized individuals as permitted by law.",
            ),
            "AI_authorizationDuration": first_text(
                icf.get("authorization_duration"),
                get_path(reference, "risks_benefits.authorization_duration"),
                "This permission (also called authorization) will not expire.",
            ),
            "sterlingSecondaryPhone": (
                fields["sudyCordinatorOfficePhone"]
                if fields["sudyCordinatorOfficePhone"] != fields["studyCordinatorPhone"]
                else ""
            ),
            "studyContactPhones": " or ".join(
                dict.fromkeys(
                    phone
                    for phone in (fields["studyCordinatorPhone"], fields["sudyCordinatorOfficePhone"])
                    if phone
                )
            ),
        }
    )
    return fields


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, help="Run directory containing reference/study.reference.json.")
    parser.add_argument("--reference", help="Reference JSON path. Defaults to reference/study.reference.json.")
    parser.add_argument("--check", action="store_true", help="Do not write the reference; report blank required fields.")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser().resolve()
    reference_path = Path(args.reference).expanduser().resolve() if args.reference else run_dir / STANDARD_REFERENCE
    reference = load_json(reference_path)
    fields = build_fields(reference)
    blank_required = sorted(
        key for key in REQUIRED_AI_FIELDS if key not in OPTIONAL_FIELDS and not str(fields.get(key, "")).strip()
    )

    if args.check:
        print(json.dumps({"blank_required_fields": blank_required, "template_fields": fields}, indent=2, ensure_ascii=False))
        return 1 if blank_required else 0

    merged = reference.get("template_fields")
    if not isinstance(merged, dict):
        merged = {}
    merged.update(fields)
    reference["template_fields"] = merged
    reference_path.write_text(json.dumps(reference, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "updated": display_path(reference_path, run_dir),
                "field_count": len(fields),
                "blank_required_fields": blank_required,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
