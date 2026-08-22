"""Build the source-grounded structured protocol used by final generation."""

from __future__ import annotations

import copy
import re
from typing import Any


class ProtocolCompletenessError(ValueError):
    """Raised when approved source material cannot support a complete protocol."""


def _get(data: Any, path: str, default: Any = "") -> Any:
    current = data
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part, default)
        else:
            return default
    return current


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "\n".join(_text(item) for item in value if _text(item))
    if isinstance(value, dict):
        return _text(
            value.get("text")
            or value.get("description")
            or value.get("name")
            or value.get("label")
            or value.get("measure")
            or value.get("outcome_measure")
            or value.get("outcomeMeasure")
            or ""
        )
    return ""


def _items(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_text(item) for item in value if _text(item)]
    rendered = _text(value)
    return [line.strip(" •*-\t") for line in rendered.splitlines() if line.strip()]


def _paragraphs(*values: Any) -> list[str]:
    result: list[str] = []
    for value in values:
        rendered = _text(value)
        if rendered:
            result.extend(part.strip() for part in re.split(r"\n\s*\n", rendered) if part.strip())
    return result


def _table(name: str, caption: str, columns: list[dict[str, str]], rows: list[dict[str, str]]) -> dict[str, Any]:
    return {"name": name, "caption": caption, "columns": columns, "rows": rows}


def _first_text(reference: dict[str, Any], *paths: str) -> str:
    for path in paths:
        value = _text(_get(reference, path))
        if value:
            return value
    return ""


def _final_follow_up(reference: dict[str, Any]) -> tuple[str, str]:
    """Return the final scheduled contact and its window from approved data."""
    protocol = _get(reference, "generated.protocol", {})
    schedule = _get(protocol, "visitScheduleTable") or _get(reference, "procedures.visit_schedule_table")
    if isinstance(schedule, list):
        rows = [row for row in schedule if isinstance(row, dict)]
        if rows:
            final = rows[-1]
            return (
                _text(final.get("visitName")) or _text(final.get("name")),
                _text(final.get("visitWindow")) or _text(final.get("window")),
            )
    details = _first_text(reference, "generated.protocol.visitScheduleDetails", "procedures.visit_schedule")
    lines = [line.strip() for line in details.splitlines() if line.strip()]
    if lines:
        return lines[-1].split(":", 1)[0].strip(" ."), ""
    return "", ""


def _scheduled_contacts(reference: dict[str, Any]) -> list[str]:
    protocol = _get(reference, "generated.protocol", {})
    schedule = _get(protocol, "visitScheduleTable") or _get(reference, "procedures.visit_schedule_table")
    if not isinstance(schedule, list):
        return []
    return [
        _text(row.get("visitName")) or _text(row.get("name"))
        for row in schedule
        if isinstance(row, dict) and (_text(row.get("visitName")) or _text(row.get("name")))
    ]


def _section18_content(reference: dict[str, Any]) -> dict[str, list[str]]:
    """Build conservative endpoint criteria from source facts and safe rules."""
    protocol = _get(reference, "generated.protocol", {})

    def clean(value: Any) -> str:
        return _text(value).strip().rstrip(" .;")

    design = clean(_first_text(reference, "design.study_design", "generated.protocol.studyDesignLong"))
    intervention = clean(_first_text(reference, "design.intervention_name", "design.intervention.name"))
    duration = clean(_first_text(reference, "generated.protocol.duration", "study.timeline"))
    final_visit, final_window = _final_follow_up(reference)
    final_visit, final_window = clean(final_visit), clean(final_window)
    scheduled_contacts = _scheduled_contacts(reference)
    endpoint = "; ".join(clean(item) for item in _items(_get(reference, "endpoints.primary") or _get(reference, "generated.protocol.endpointCriteria")))
    secondary = "; ".join(clean(item) for item in _items(_get(reference, "endpoints.secondary")))
    safety = _first_text(
        reference,
        "safety.adverse_events",
        "safety.general_information",
        "safety.monitoring",
        "risks_benefits.risks",
        "generated.protocol.risks",
    )
    withdrawal = _first_text(
        reference,
        "procedures.discontinuation",
        "procedures.withdrawal_rules",
        "generated.protocol.discontinuation",
    )

    duration_text = duration[:1].lower() + duration[1:] if duration else ""
    duration_clause = f" Prospective participation is expected to last {duration_text}." if duration_text else ""
    final_contact = final_visit if final_visit else "the final scheduled contact"
    if final_window and final_window.casefold() != final_visit.casefold():
        final_contact += f" ({final_window})"
    contacts_clause = f" Scheduled contacts are {', '.join(scheduled_contacts)}." if scheduled_contacts else ""
    study_clause = f"the {design or 'approved study'}"
    if intervention:
        study_clause += f" using the {intervention}"
    safety_clause = (
        f" Safety information will be recorded and followed according to the approved safety procedures: {clean(safety)}."
        if safety
        else " Safety concerns identified during study participation will be evaluated by the investigator and managed according to applicable study procedures."
    )
    withdrawal_clause = (
        clean(withdrawal) + "."
        if withdrawal
        else "Participants may discontinue participation or withdraw consent at any time without penalty or loss of entitled care. The reason, available follow-up information, and data collected before discontinuation will be documented as permitted by consent and applicable requirements."
    )

    endpoint_paragraph = f"The primary endpoint is {clean(endpoint)}."
    if secondary:
        endpoint_paragraph += f" Secondary endpoints are {clean(secondary)}."
    endpoint_paragraph += f" These endpoint criteria apply to {study_clause}.{contacts_clause}{duration_clause}"

    return {
        "18.": [endpoint_paragraph],
        "18.1.": [f"A participant completes the study after completing required study activities through {final_contact} and after all available endpoint assessments have been documented.{contacts_clause}{duration_clause}"],
        "18.2.": [withdrawal_clause],
        "18.3.": [f"The investigator may terminate a participant's study participation when continued participation is not appropriate, including for a safety concern, an eligibility or protocol issue, inability to complete required follow-up, or loss to follow-up. The reason and data collected before termination will be documented when available.{safety_clause}"],
        "18.4.": ["The sponsor or investigator may terminate or stop the study for participant safety, feasibility, operational, regulatory, or other reasons that make continuation inappropriate. The decision, affected participants, required notifications, and closeout activities will be documented."],
        "18.5.": [f"The study is complete after the final enrolled participant has completed required follow-up through {final_contact}, or has been discontinued or terminated, and after planned endpoint data and study closeout activities have been completed."],
    }


def section18_completeness_missing(reference: dict[str, Any]) -> list[dict[str, str]]:
    """Identify decisions that cannot be safely inferred for Section 18."""
    final_visit, _ = _final_follow_up(reference)
    endpoint = _first_text(reference, "endpoints.primary", "generated.protocol.endpointCriteria")
    missing = []
    if not endpoint:
        missing.append({"field": "endpoints.primary", "issue": "Section 18 requires a primary endpoint or endpoint criterion."})
    if not final_visit:
        missing.append({"field": "procedures.visit_schedule", "issue": "Section 18 requires a final scheduled visit or follow-up contact to define completion."})
    return missing


def operational_detail_missing(reference: dict[str, Any], *, require_replacement: bool = False) -> list[dict[str, str]]:
    """Return missing source-backed conduct details for strict delivery runs.

    Older approved fixtures may not have introduced every newer operational
    field.  A field family is therefore enforced once the source declares that
    family; an absent replacement field remains legacy-compatible, while a
    removed injury, retention, safety, or discontinuation value blocks delivery.
    """
    requirements = [
        ("procedures.retention", ("procedures.retention",), "Retention plan"),
        (
            "risks_benefits.compensation_or_reimbursement",
            (
                "risks_benefits.compensation_or_reimbursement",
                "risks_benefits.compensation",
                "risks_benefits.reimbursement",
            ),
            "Participant compensation or reimbursement",
        ),
        (
            "risks_benefits.injury_handling",
            ("risks_benefits.injury_handling", "risks_benefits.injury"),
            "Research-related injury handling",
        ),
        (
            "procedures.discontinuation",
            ("procedures.discontinuation", "procedures.withdrawal_rules"),
            "Discontinuation rules",
        ),
        (
            "procedures.replacement",
            ("procedures.replacement", "procedures.replacement_rules"),
            "Replacement rules",
        ),
        (
            "safety.roles",
            ("safety.roles", "safety.general_information", "safety.monitoring", "safety.adverse_events"),
            "Safety reporting roles and procedures",
        ),
    ]
    missing: list[dict[str, str]] = []
    for canonical, paths, label in requirements:
        if not require_replacement and canonical == "procedures.replacement" and not any(
            path in {"procedures.replacement", "procedures.replacement_rules"}
            and bool(_text(_get(reference, path)))
            for path in paths
        ):
            # Replacement was not part of older approved protocol references;
            # the source contract enforces it for new source-grounded runs.
            continue
        if not any(_text(_get(reference, path)) for path in paths):
            missing.append({"field": canonical, "issue": f"Missing approved operational detail: {label}."})
    return missing


def protocol_completeness_missing(reference: dict[str, Any], *, strict_operational: bool = False) -> list[dict[str, str]]:
    """Return missing source facts that would otherwise invite fabricated prose."""
    study_type = str(_get(reference, "meta.study_type")).casefold()
    if study_type == "retrospective":
        requirements = [
            ("study.title", "Study title"),
            ("study.background", "Study background"),
            ("objectives.primary", "Primary objective"),
            ("design.study_design", "Study design"),
            ("procedures.assessments", "Completed assessments and their schedule"),
            ("population.inclusion_criteria", "Inclusion criteria"),
            ("population.exclusion_criteria", "Exclusion criteria"),
            ("population.sample_size", "Sample size"),
            ("endpoints.primary", "Primary endpoint"),
            ("statistics.analysis_plan", "Statistical analysis plan"),
        ]
        missing = [
            {"field": path, "issue": f"Missing required source input for complete retrospective protocol: {label}."}
            for path, label in requirements
            if not _text(_get(reference, path))
            and not (path == "procedures.assessments" and _text(_get(reference, "procedures.visit_schedule")))
        ]
        if not _text(_get(reference, "population.sample_justification")) and not _text(_get(reference, "statistics.sample_size_justification")):
            missing.append({"field": "population.sample_justification", "issue": "Missing required source input for complete retrospective protocol: Sample-size justification."})
        values = _all_strings(reference)
        if any(re.search(r"\b(?:draft|todo|tbd|needs review|internal only)\b", value, re.I) for value in values):
            missing.append({"field": "generated.protocol", "issue": "Internal drafting language is present in approved retrospective protocol content."})
        return missing
    requirements = [
        ("study.title", "Study title"),
        ("study.background", "Study background"),
        ("objectives.primary", "Primary objective"),
        ("population.inclusion_criteria", "Inclusion criteria"),
        ("population.exclusion_criteria", "Exclusion criteria"),
        ("design.study_design", "Study design"),
        ("procedures.assessments", "Planned assessments and schedule"),
        ("population.sample_size", "Sample size"),
        ("population.sample_justification", "Sample-size justification"),
        ("endpoints.primary", "Primary endpoint"),
    ]
    missing = [
        {"field": path, "issue": f"Missing required source input for complete protocol: {label}."}
        for path, label in requirements
        if not _text(_get(reference, path)) and not (path == "population.sample_justification" and _text(_get(reference, "statistics.sample_size_justification")))
    ]
    protocol = _get(reference, "generated.protocol", {})
    schedule = _get(protocol, "visitScheduleTable") or _get(reference, "procedures.visit_schedule_table")
    if not isinstance(schedule, list) or not schedule:
        missing.append({"field": "generated.protocol.visitScheduleTable", "issue": "Complete Schedule of Assessments requires at least one structured visit row."})
    values = _all_strings(reference)
    if any(re.search(r"\b(?:draft|todo|tbd|needs review|internal only)\b", value, re.I) for value in values):
        missing.append({"field": "generated.protocol", "issue": "Internal drafting language is present in approved protocol content."})
    known_fields = {item["field"] for item in missing}
    missing.extend(item for item in section18_completeness_missing(reference) if item["field"] not in known_fields)
    # Retention, injury, discontinuation, replacement, and safety-role prose is
    # generated after approval when it was not supplied. These are not starred
    # intake fields and must not be promoted into reviewer blockers.
    return missing


def _all_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        result: list[str] = []
        for child in value.values():
            result.extend(_all_strings(child))
        return result
    if isinstance(value, list):
        result: list[str] = []
        for child in value:
            result.extend(_all_strings(child))
        return result
    return []


def build_complete_protocol(reference: dict[str, Any]) -> dict[str, Any]:
    """Create sectioned protocol content without inventing unsupported facts."""
    if str(_get(reference, "meta.study_type")).casefold() == "retrospective":
        return build_retrospective_protocol(reference)
    missing = protocol_completeness_missing(reference)
    if missing:
        raise ProtocolCompletenessError("Complete Protocol Gate failed: " + "; ".join(item["issue"] for item in missing))
    protocol = _get(reference, "generated.protocol", {})
    endpoints = _get(reference, "endpoints", {})
    risks = _get(reference, "risks_benefits", {})
    sections: list[dict[str, Any]] = []

    def add(number: str, title: str, paragraphs: list[str], *, lists: list[list[str]] | None = None, tables: list[dict[str, Any]] | None = None) -> None:
        sections.append({"number": number, "title": title, "paragraphs": paragraphs, "lists": lists or [], "tables": tables or []})

    add("5.", "INTRODUCTION", _paragraphs(_get(protocol, "introduction"), _get(reference, "study.background"), _get(reference, "study.hypothesis")))
    add("6.", "OBJECTIVE(S)", _paragraphs(_get(protocol, "objectivesIntro"), _get(reference, "objectives.primary"), _get(reference, "objectives.secondary")))
    add("7.", "SUBJECTS", _paragraphs(_get(protocol, "populationLong"), _get(reference, "population.study_population")))
    add("7.1.", "Subject Population", _paragraphs(_get(protocol, "populationLong"), _get(reference, "population.study_population")))
    add("7.2.", "Inclusion Criteria", [], lists=[_items(_get(reference, "population.inclusion_criteria"))])
    add("7.3.", "Exclusion Criteria", [], lists=[_items(_get(reference, "population.exclusion_criteria"))])
    add("8.", "STUDY DESIGN", _paragraphs(_get(protocol, "studyDesignLong"), _get(reference, "design.study_design")))
    add("8.1.", "Study Design", _paragraphs(_get(protocol, "studyDesignLong"), _get(reference, "design.study_design")))
    add("8.2.", "Methods Used to Minimize Bias", _paragraphs(_get(protocol, "methods"), _get(reference, "procedures.methods")))
    add("9.", "STUDY PROCEDURE", _paragraphs(_get(protocol, "studyProcedure"), _get(reference, "procedures.assessments")))
    add("9.1.", "Informed Consent / Subject Enrollment", _paragraphs(_get(protocol, "consent"), _get(reference, "procedures.consent")))
    add("9.2.", "Visits and Examinations", _paragraphs(_get(protocol, "visitScheduleDetails"), _get(reference, "procedures.visit_schedule")))
    add("9.3.", "Study Methods and Measurements", _paragraphs(_get(protocol, "measurementsDetails"), _get(reference, "procedures.assessment_details")))
    add("9.4.", "Unscheduled Visits", _paragraphs(_get(protocol, "unscheduledVisits"), _get(reference, "procedures.unscheduled_visits")))
    add("9.5.", "Discontinued Subjects", _paragraphs(_get(protocol, "discontinuedSubjects"), _get(reference, "procedures.discontinued_subjects")))
    add("10.", "ANALYSIS PLAN", _paragraphs(_get(protocol, "analysisDataSets"), _get(protocol, "statisticalMethodology"), _get(protocol, "statisticalConsiderations"), _get(reference, "statistics.analysis_plan")))
    add("10.1.", "Analysis Data Sets", _paragraphs(_get(protocol, "analysisDataSets"), _get(reference, "statistics.analysis_plan")))
    add("10.2.", "Statistical Methodology", _paragraphs(_get(protocol, "statisticalMethodology"), _get(reference, "statistics.methodology")))
    add("10.3.", "General Statistical Considerations", _paragraphs(_get(protocol, "statisticalConsiderations"), _get(reference, "statistics.software")))
    supplied_sample_rows = _get(reference, "statistics.sample_size_evidence") or _get(reference, "population.sample_size_evidence") or _get(protocol, "sampleSizeEvidenceTable.rows")
    if isinstance(supplied_sample_rows, list) and supplied_sample_rows:
        sample_rows = [copy.deepcopy(row) for row in supplied_sample_rows if isinstance(row, dict)]
        sample_columns = _table_columns_for_rows(sample_rows, (("evidence", "Evidence"), ("value", "Value"), ("source", "Source")))
    else:
        sample_rows = [
            {"evidence": "Planned sample size", "value": _text(_get(reference, "population.sample_size")), "source": "Approved study source"},
            {"evidence": "Sample-size justification", "value": _text(_get(reference, "population.sample_justification")) or _text(_get(reference, "statistics.sample_size_justification")), "source": "Approved study source"},
        ]
    if not isinstance(supplied_sample_rows, list) or not supplied_sample_rows:
        sample_columns = [{"key": key, "label": label} for key, label in (("evidence", "Evidence"), ("value", "Value"), ("source", "Source"))]
    add("11.", "SAMPLE SIZE JUSTIFICATION", _paragraphs(_get(protocol, "sampleSizeJustification"), _get(reference, "population.sample_justification"), _get(reference, "statistics.sample_size_justification")), tables=[_table("sample_size_evidence", "11.1 Sample Size Evidence", sample_columns, sample_rows)])
    add("12.", "CONFIDENTIALITY/PUBLICATION OF THE STUDY", _paragraphs(_get(protocol, "confidentialityPublication"), _get(reference, "confidentiality.publication")))
    add("13.", "QUALITY COMPLAINTS AND ADVERSE EVENTS", _paragraphs(_get(protocol, "risks"), _get(reference, "safety.adverse_events"), _get(reference, "risks_benefits.risks")))
    add("13.1.", "General Information", _paragraphs(_get(protocol, "generalSafety"), _get(reference, "safety.general_information")))
    add("13.2.", "Monitoring for Adverse Events", _paragraphs(_get(protocol, "safetyMonitoring"), _get(reference, "safety.monitoring")))
    add("13.3.", "Procedures for Recording and Reporting AEs and SAEs", _paragraphs(_get(protocol, "adverseEventReporting"), _get(reference, "safety.adverse_events")))
    add("13.4.", "Follow-Up of Adverse Events and Quality Complaints", _paragraphs(_get(protocol, "adverseEventFollowUp"), _get(reference, "safety.follow_up"), _get(reference, "risks_benefits.risks")))
    add("13.5.", "Safety Analyses", _paragraphs(_get(protocol, "safetyAnalyses"), _get(reference, "statistics.analysis_plan")))
    add("14.", "GCP, ICH AND ETHICAL CONSIDERATIONS", _paragraphs(_get(protocol, "ethics"), _get(reference, "ethics.considerations")))
    add("14.1", "Confidentiality", _paragraphs(_get(protocol, "ethicalConfidentiality"), _get(reference, "ethics.confidentiality")))
    schedule = _get(protocol, "visitScheduleTable") or _get(reference, "procedures.visit_schedule_table")
    schedule_columns = [{"key": key, "label": label} for key, label in (("visitNumber", "Visit Number"), ("visitName", "Visit Name"), ("visitWindow", "Visit Window"), ("CRFnumber", "CRF Number"))]
    add("15.", "STANDARD EVALUATION PROCEDURES", _paragraphs(_get(protocol, "measurements"), _get(reference, "procedures.assessments")), tables=[_table("schedule_of_assessments", "15.1 Proposed Visits and Study Assessments", schedule_columns, schedule)])
    add("16.", "CONFIDENTIALITY", _paragraphs(_get(protocol, "confidentiality"), _get(reference, "confidentiality.data_handling")))
    add("17.", "FINANCIAL AND INSURANCE INFORMATION/STUDY RELATED INJURIES", _paragraphs(_get(protocol, "injury_compensation"), _get(reference, "risks_benefits.compensation_or_reimbursement"), _get(reference, "risks_benefits.injury_handling")))
    section18 = _section18_content(reference)
    add("18.", "STUDY ENDPOINT CRITERIA", _paragraphs(_get(protocol, "endpointCriteria")) or section18["18."], tables=[])
    add("18.1.", "Patient Completion of Study", _paragraphs(_get(protocol, "completion"), _get(reference, "procedures.retention")) or section18["18.1."])
    add("18.2.", "Patient Discontinuation", _paragraphs(_get(protocol, "discontinuation"), _get(reference, "procedures.discontinuation")) or section18["18.2."])
    add("18.3.", "Patient Termination", _paragraphs(_get(protocol, "termination"), _get(reference, "procedures.termination")) or section18["18.3."])
    add("18.4.", "Study Termination", _paragraphs(_get(protocol, "studyTermination"), _get(reference, "procedures.study_termination")) or section18["18.4."])
    add("18.5.", "Study Completion", _paragraphs(_get(protocol, "studyCompletion"), _get(reference, "procedures.study_completion")) or section18["18.5."])
    add("19.", "SUMMARY OF RISKS AND BENEFITS", _paragraphs(_get(protocol, "risks"), _get(risks, "risks"), _get(protocol, "benefits"), _get(risks, "benefits")))
    add("19.1", "Summary of risks", _paragraphs(_get(protocol, "risks"), _get(risks, "risks")))
    add("19.2", "Summary of benefits", _paragraphs(_get(protocol, "benefits"), _get(risks, "benefits")))
    return {"title": _text(_get(reference, "study.title")), "sections": sections}


def build_retrospective_protocol(reference: dict[str, Any]) -> dict[str, Any]:
    """Build the contracted retrospective 1–13 hierarchy from approved facts."""
    protocol = _get(reference, "generated.protocol", {})
    sample_justification = _first_text(reference, "population.sample_justification", "statistics.sample_size_justification")

    def first(*values: Any) -> str:
        return next((value for value in (_text(item) for item in values) if value), "")

    def add(number: str, title: str, paragraphs: list[str], *, lists: list[list[str]] | None = None, tables: list[dict[str, Any]] | None = None) -> None:
        sections.append({"number": number, "title": title, "paragraphs": [item for item in paragraphs if item], "lists": lists or [], "tables": tables or []})

    sections: list[dict[str, Any]] = []
    add("4.", "INTRODUCTION", [first(protocol.get("introduction"), _get(reference, "study.background"), _get(reference, "study.unmet_need"))])
    add("5.", "OBJECTIVE(S)", [first(protocol.get("objectivesIntro"), _get(reference, "objectives.primary"), _get(reference, "study.hypothesis"))])
    add("6.", "SUBJECTS", [])
    add("6.1.", "Subject Population", [first(protocol.get("populationLong"), _get(reference, "population.study_population"), f"The retrospective study will review approximately {_text(_get(reference, 'population.sample_size'))} eligible records or subjects.")])
    add("6.2.", "Inclusion/Exclusion Criteria", [], lists=[_items(_get(reference, "population.inclusion_criteria")) + _items(_get(reference, "population.exclusion_criteria"))])
    add("7.", "STUDY DESIGN", [])
    add("7.1.", "Study Design", [first(protocol.get("studyDesignLong"), _get(reference, "design.study_design"))])
    add("7.2.", "Methods Used to Minimize Bias", [first(protocol.get("methods"), "Standardized eligibility criteria, source abstraction procedures, and predefined analysis methods will be used to minimize bias.")])
    add("8.", "STUDY PROCEDURE", [])
    add("8.1.", "Informed Consent / Subject enrollment", [first(protocol.get("studyProcedure"), _get(reference, "procedures.assessments"), _get(reference, "procedures.visit_schedule"))])
    add("9.", "ANALYSIS PLAN", [])
    add("9.1.", "Analysis Data Sets", [first(protocol.get("analysisDataSets"), _get(reference, "statistics.analysis_plan"))])
    add("9.2.", "Statistical Methodology", [first(protocol.get("statisticalMethodology"), _get(reference, "statistics.methodology"), _get(reference, "statistics.analysis_plan"))])
    add("9.3.", "General Statistical Considerations", [first(protocol.get("statisticalConsiderations"), _get(reference, "statistics.software"), "Missing, unavailable, and excluded records will be identified and summarized in the final analysis.")])
    sample_rows = [{"evidence": "Planned retrospective sample", "value": _text(_get(reference, "population.sample_size")), "source": "Approved study source"}, {"evidence": "Sample-size justification", "value": sample_justification, "source": "Approved study source"}]
    add("10.", "SAMPLE SIZE JUSTIFICATION", [first(protocol.get("sampleSizeJustification"), sample_justification)], tables=[_table("sample_size_evidence", "10.1 Sample Size Evidence", [{"key": "evidence", "label": "Evidence"}, {"key": "value", "label": "Value"}, {"key": "source", "label": "Source"}], sample_rows)])
    add("11.", "CONFIDENTIALITY/PUBLICATION OF THE STUDY", [first(protocol.get("confidentialityPublication"), _get(reference, "confidentiality.publication"), "Study records will be handled confidentially and reported in aggregate without direct subject identifiers.")])
    add("12.", "QUALITY COMPLAINTS AND ADVERSE EVENTS", [first(protocol.get("risks"), _get(reference, "safety.adverse_events"), _get(reference, "risks_benefits.risks"), "Any safety information identified in the reviewed records will be recorded and assessed according to the approved study procedures.")])
    add("13.", "GCP, ICH and ETHICAL CONSIDERATIONS", [first(protocol.get("ethics"), _get(reference, "ethics.considerations"), "The retrospective study will be conducted in accordance with applicable ethical requirements, GCP, and ICH principles.")])
    return {"title": _text(_get(reference, "study.title")), "sections": sections}


def _table_columns_for_rows(rows: list[dict[str, Any]], preferred: tuple[tuple[str, str], ...]) -> list[dict[str, str]]:
    """Preserve declared evidence columns while providing stable legacy defaults."""
    keys = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    labels = dict(preferred)
    return [{"key": key, "label": labels.get(key, re.sub(r"([a-z])([A-Z])", r"\1 \2", key).replace("_", " ").title())} for key in keys]


def with_complete_protocol(reference: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(reference)
    generated = result.setdefault("generated", {})
    protocol = generated.setdefault("protocol", {})
    protocol.update(build_complete_protocol(result))
    return result
