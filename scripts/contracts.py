"""Branch, source, drafting, and document contracts.

This is the single deterministic authority for the study branches and for the
sections that drafting, rendering, and quality assurance must agree on.  It is
not a workflow entrypoint.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


CONTRACT_VERSION = "clinical-documents-v2.9"
BOILERPLATE_VERSION = "clinical-boilerplate-v8"

DOCUMENT_SETS: dict[str, tuple[str, ...]] = {
    "Prospective": ("protocol.docx", "icf.docx", "study.xml"),
    "Ambispective": ("protocol.docx", "icf.docx", "study.xml"),
    "Retrospective": ("protocol.docx",),
}

STUDY_TYPE_ALIASES = {
    "prospective": "Prospective",
    "forward-looking": "Prospective",
    "ambispective": "Ambispective",
    "hybrid": "Ambispective",
    "retrospective": "Retrospective",
    "chart review": "Retrospective",
}

PRS_STUDY_TYPES = {
    "observational": "Observational",
    "interventional": "Interventional",
}

PRS_CLASSIFICATION_ASSERTIONS = (
    re.compile(r"^(?P<classification>observational|interventional)\.?$"),
    re.compile(
        r"^study type:\s*(?P<classification>observational|interventional)\.?$"
    ),
    re.compile(
        r"^(?P<classification>observational|interventional),\s+"
        r"(?:randomized|non-randomized|nonrandomized)\s+study\.?$"
    ),
    re.compile(
        r"^(?P<classification>observational|interventional)(?:\s+device)?\s+study\.?$"
    ),
    re.compile(
        r"^(?:this|the study|the trial)\s+is\s+(?:an?\s+)?"
        r"(?P<classification>observational|interventional)(?:\s+device)?\s+study\.?$"
    ),
    re.compile(
        r"^(?:prospective|ambispective|retrospective),\s+"
        r"(?:(?:single|multi)-(?:center|site|arm),\s+)*"
        r"(?:(?:single|multi)-(?:center|site|arm)\s+)?"
        r"(?P<classification>observational|interventional)(?:\s+device)?\s+study"
        r"(?:\s+(?:combining historical abstraction and prospective follow-up"
        r"|with historical chart review and prospective follow-up"
        r"|based on historical record abstraction))?\.?$"
    ),
)

FORBIDDEN_DRAFT_LANGUAGE = (
    "the approved source provides",
    "the approved source identifies",
    "no additional study-specific claim",
    "needs review",
    "internal only",
    "insert text",
    "to be completed",
    "tbd",
    "todo",
    "as an ai",
)


@dataclass(frozen=True)
class RequiredInput:
    field: str
    aliases: tuple[str, ...] = ()
    label: str = ""
    kind: str = "value"


@dataclass(frozen=True)
class SectionSpec:
    section_id: str
    number: str
    title: str
    role: str = "leaf"
    batch_id: str = ""
    evidence: tuple[str, ...] = ()
    boilerplate_key: str | None = None
    required: bool = True
    content_expectations: tuple[str, ...] = ()
    source_coverage: str = "all_material_evidence"

    def public(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BatchSpec:
    batch_id: str
    artifact: str
    section_ids: tuple[str, ...]
    field_families: tuple[str, ...]
    prerequisites: tuple[str, ...] = ()

    def public(self) -> dict[str, Any]:
        return asdict(self)


PROSPECTIVE_REQUIRED: tuple[RequiredInput, ...] = (
    RequiredInput("study.title"),
    RequiredInput("study.background"),
    RequiredInput("objectives.primary"),
    RequiredInput("study.hypothesis"),
    RequiredInput("design.study_design"),
    RequiredInput("design.intervention_name"),
    RequiredInput("design.intervention_type"),
    RequiredInput("design.number_of_sites"),
    RequiredInput("endpoints.primary"),
    RequiredInput("procedures.assessments", ("procedures.visit_schedule",)),
    RequiredInput("population.inclusion_criteria"),
    RequiredInput("population.exclusion_criteria"),
    RequiredInput("procedures.minimum_days_before_screening_without_participation"),
    RequiredInput("population.sample_size"),
    RequiredInput("population.sample_justification", ("statistics.sample_size_justification",)),
    RequiredInput(
        "risks_benefits.compensation_or_reimbursement",
        ("risks_benefits.compensation", "risks_benefits.reimbursement", "risks_benefits.payment"),
    ),
    RequiredInput("statistics.analysis_plan"),
    RequiredInput("study.timeline"),
    RequiredInput("parties.irb.name"),
    RequiredInput("parties.irb.affiliation"),
    RequiredInput("parties.irb.phone"),
    RequiredInput("parties.irb.email"),
    RequiredInput("parties.irb.address"),
    RequiredInput("parties.sponsor.name"),
    RequiredInput("parties.sponsor.address"),
    RequiredInput("parties.principal_investigator.name"),
    RequiredInput("parties.principal_investigator.title", ("parties.principal_investigator.degree",)),
    RequiredInput("parties.study_coordinator.name"),
    RequiredInput("parties.study_coordinator.title", ("parties.study_coordinator.degree",)),
    RequiredInput("parties.study_coordinator.business_phone"),
    RequiredInput("parties.study_coordinator.office_phone"),
    RequiredInput("parties.study_coordinator.email"),
    RequiredInput("sites.facilities", kind="site_facilities"),
    RequiredInput("sites.contacts", kind="site_contacts"),
    RequiredInput("sites.investigators", kind="site_investigators"),
    RequiredInput("regulatory.prs.provider_study_id", ("meta.protocol_number",), "PRS provider study ID"),
    RequiredInput("regulatory.prs.study_type", label="PRS study type (Observational or Interventional)"),
)

RETROSPECTIVE_REQUIRED: tuple[RequiredInput, ...] = (
    RequiredInput("study.title"),
    RequiredInput("study.background"),
    RequiredInput("objectives.primary"),
    RequiredInput("study.unmet_need", ("study.unmet_medical_need",)),
    RequiredInput("study.hypothesis"),
    RequiredInput("design.study_design"),
    RequiredInput("design.number_of_sites"),
    RequiredInput("endpoints.primary"),
    RequiredInput("procedures.assessments", ("procedures.visit_schedule",)),
    RequiredInput("population.inclusion_criteria"),
    RequiredInput("population.exclusion_criteria"),
    RequiredInput("population.sample_size"),
    RequiredInput("population.sample_justification", ("statistics.sample_size_justification",)),
    RequiredInput("statistics.analysis_plan"),
    RequiredInput("parties.irb.name"),
    RequiredInput("parties.irb.address"),
    RequiredInput("parties.sponsor.name"),
    RequiredInput("parties.sponsor.address"),
    RequiredInput("sites.0.facility.name"),
    RequiredInput("parties.principal_investigator.name"),
    RequiredInput("parties.principal_investigator.title", ("parties.principal_investigator.degree",)),
)


def _content_expectations(section_id: str, title: str) -> tuple[str, ...]:
    specific = {
        "introduction": "Name the study and explain its approved clinical background, hypothesis, primary endpoint, and rationale.",
        "objectives": "Distinguish the approved objective, hypothesis, and every supplied primary, secondary, and exploratory endpoint; reconcile different clinical constructs rather than silently substituting one for another.",
        "subjects.population": "Describe the approved population and planned sample size without adding eligibility facts.",
        "subjects.inclusion": "Preserve every approved inclusion criterion and the approved minimum interval without participation in another study before screening as distinct, usable criteria.",
        "subjects.exclusion": "Preserve every approved exclusion criterion as a distinct, usable criterion.",
        "subjects.eligibility": "Preserve every approved inclusion and exclusion criterion and keep the two groups distinct.",
        "study-design.design": "Explain the approved design, setting, arms, intervention, and masking details that are supplied.",
        "study-design.bias": "Explain applicable bias controls and use only the listed boilerplate when source detail is sparse.",
        "study-procedure.visits": "Account for every approved visit, time point, and visit-specific procedure.",
        "study-procedure.measurements": "Account for every approved assessment and endpoint in operational language, including the supplied time points; do not invent an instrument, scoring rule, denominator, or definition that is absent from the source.",
        "study-procedure.enrollment": "Describe the approved record-review or enrollment sequence, time points, and timeline.",
        "evaluation-procedures": "Account for every approved assessment and visit in the Schedule of Assessments narrative.",
        "analysis-plan.datasets": "Identify the analysis populations or data sets supported by the approved analysis plan.",
        "analysis-plan.methodology": "Explain the approved statistical methods and map them explicitly to every supplied primary and secondary endpoint.",
        "analysis-plan.considerations": "Explain the approved analysis conventions and interpretation considerations, including only source-supported handling of paired or missing observations.",
        "sample-size": "State the approved sample size and explain its approved justification.",
        "icf.study-purpose": "Explain the study purpose, hypothesis, primary endpoint, and background in clear participant-facing language.",
        "icf.procedures": "Explain every approved visit, procedure, and minimum interval without participation in another study before screening in participant-facing sequence.",
        "icf.duration": "State the approved participation duration and relevant time points.",
        "icf.risks": "Disclose every approved risk or discomfort without minimizing or inventing risk.",
        "icf.benefits": "State the approved potential benefits and explicitly preserve any no-direct-benefit statement.",
        "icf.payment": "State the approved payment or reimbursement terms exactly enough for participant use.",
        "icf.privacy": "Explain the approved privacy and confidentiality handling in participant-facing language.",
    }
    return (
        specific.get(section_id, f"Explain {title.lower()} using all material approved facts supplied for this section."),
        "Do not replace supplied detail with generic clinical prose.",
    )


def _source_coverage(section_id: str) -> str:
    item_complete_sections = {
        "objectives",
        "subjects.inclusion", "subjects.exclusion", "subjects.eligibility",
        "study-procedure.visits", "study-procedure.measurements", "study-procedure.enrollment",
        "evaluation-procedures", "icf.procedures",
    }
    return "all_material_items" if section_id in item_complete_sections else "all_material_evidence"


def _section_spec(
    section_id: str,
    number: str,
    title: str,
    batch: str = "",
    evidence: Iterable[str] = (),
    boilerplate: str | None = None,
    role: str = "leaf",
) -> SectionSpec:
    return SectionSpec(
        section_id,
        number,
        title,
        role,
        batch,
        tuple(evidence),
        boilerplate,
        content_expectations=_content_expectations(section_id, title),
        source_coverage=_source_coverage(section_id),
    )


PROTOCOL_1_TO_19: tuple[SectionSpec, ...] = (
    _section_spec("title-page", "1.", "TITLE PAGE", role="container"),
    _section_spec("investigator-agreement", "2.", "INVESTIGATOR AGREEMENT", role="container"),
    _section_spec("general-information", "3.", "GENERAL INFORMATION", role="container"),
    _section_spec("table-of-contents", "4.", "TABLE OF CONTENTS", role="container"),
    _section_spec("introduction", "5.", "INTRODUCTION", "protocol-foundations", ("study.background", "study.title", "study.hypothesis", "endpoints.primary")),
    _section_spec("objectives", "6.", "OBJECTIVE(S)", "protocol-foundations", ("objectives.primary", "objectives.secondary", "study.hypothesis", "endpoints.primary", "endpoints.secondary")),
    _section_spec("subjects", "7.", "SUBJECTS", role="container"),
    _section_spec("subjects.population", "7.1.", "Subject Population", "protocol-foundations", ("population.study_population", "population.sample_size")),
    _section_spec("subjects.inclusion", "7.2.", "Inclusion Criteria", "protocol-foundations", ("population.inclusion_criteria", "procedures.minimum_days_before_screening_without_participation")),
    _section_spec("subjects.exclusion", "7.3.", "Exclusion Criteria", "protocol-foundations", ("population.exclusion_criteria",)),
    _section_spec("study-design", "8.", "STUDY DESIGN", role="container"),
    _section_spec("study-design.design", "8.1.", "Study Design", "protocol-foundations", ("design.study_design",)),
    _section_spec("study-design.bias", "8.2.", "Methods Used to Minimize Bias", "protocol-foundations", ("design.study_design",), "bias"),
    _section_spec("study-procedure", "9.", "STUDY PROCEDURE", role="container"),
    _section_spec("study-procedure.consent", "9.1.", "Informed Consent / Subject Enrollment", "protocol-operations", ("procedures.consent",), "consent"),
    _section_spec("study-procedure.visits", "9.2.", "Visits and Examinations", "protocol-operations", ("procedures.assessments", "procedures.visit_schedule")),
    _section_spec("study-procedure.measurements", "9.3.", "Study Methods and Measurements", "protocol-operations", ("procedures.methods", "procedures.assessments", "procedures.visit_schedule", "study.hypothesis", "endpoints.primary", "endpoints.secondary")),
    _section_spec("study-procedure.unscheduled", "9.4.", "Unscheduled Visits", "protocol-operations", ("procedures.unscheduled_visits",), "unscheduled"),
    _section_spec("study-procedure.discontinued", "9.5.", "Discontinued Subjects", "protocol-operations", ("procedures.discontinued_subjects", "procedures.discontinuation"), "discontinued-subjects"),
    _section_spec("analysis-plan", "10.", "ANALYSIS PLAN", role="container"),
    _section_spec("analysis-plan.datasets", "10.1.", "Analysis Data Sets", "protocol-analysis-and-oversight", ("statistics.analysis_plan", "endpoints.primary", "endpoints.secondary")),
    _section_spec("analysis-plan.methodology", "10.2.", "Statistical Methodology", "protocol-analysis-and-oversight", ("statistics.methodology", "statistics.analysis_plan", "endpoints.primary", "endpoints.secondary")),
    _section_spec("analysis-plan.considerations", "10.3.", "General Statistical Considerations", "protocol-analysis-and-oversight", ("statistics.analysis_plan", "endpoints.primary", "endpoints.secondary")),
    _section_spec("sample-size", "11.", "SAMPLE SIZE JUSTIFICATION", "protocol-analysis-and-oversight", ("population.sample_size", "population.sample_justification")),
    _section_spec("confidentiality-publication", "12.", "CONFIDENTIALITY/PUBLICATION OF THE STUDY", "protocol-analysis-and-oversight", ("confidentiality.publication",), "publication"),
    _section_spec("quality-safety", "13.", "QUALITY COMPLAINTS AND ADVERSE EVENTS", role="container"),
    _section_spec("quality-safety.general", "13.1.", "General Information", "protocol-analysis-and-oversight", ("safety.general_information", "risks_benefits.risks"), "safety-general"),
    _section_spec("quality-safety.monitoring", "13.2.", "Monitoring for Adverse Events", "protocol-analysis-and-oversight", ("safety.monitoring",), "safety-monitoring"),
    _section_spec("quality-safety.reporting", "13.3.", "Procedures for Recording and Reporting AEs and SAEs", "protocol-analysis-and-oversight", ("safety.adverse_events",), "safety-reporting"),
    _section_spec("quality-safety.follow-up", "13.4.", "Follow-Up of Adverse Events and Quality Complaints", "protocol-analysis-and-oversight", ("safety.follow_up",), "safety-followup"),
    _section_spec("quality-safety.analysis", "13.5.", "Safety Analyses", "protocol-analysis-and-oversight", ("statistics.analysis_plan", "safety.adverse_events"), "safety-analysis"),
    _section_spec("ethics", "14.", "GCP, ICH AND ETHICAL CONSIDERATIONS", role="container"),
    _section_spec("ethics.confidentiality", "14.1.", "Confidentiality", "protocol-analysis-and-oversight", ("ethics.confidentiality", "confidentiality.data_handling"), "confidentiality-cross-reference"),
    _section_spec("evaluation-procedures", "15.", "STANDARD EVALUATION PROCEDURES", "protocol-operations", ("procedures.assessments", "procedures.visit_schedule")),
    _section_spec("confidentiality", "16.", "CONFIDENTIALITY", "protocol-analysis-and-oversight", ("confidentiality.data_handling", "risks_benefits.privacy"), "confidentiality"),
    _section_spec("financial-injury", "17.", "FINANCIAL AND INSURANCE INFORMATION/STUDY RELATED INJURIES", "protocol-analysis-and-oversight", ("risks_benefits.compensation_or_reimbursement", "risks_benefits.injury_handling"), "injury"),
    _section_spec("endpoint-criteria", "18.", "STUDY ENDPOINT CRITERIA", role="container"),
    _section_spec("endpoint-criteria.completion", "18.1.", "Patient Completion of Study", "protocol-operations", ("study.timeline", "procedures.visit_schedule"), "completion"),
    _section_spec("endpoint-criteria.discontinuation", "18.2.", "Patient Discontinuation", "protocol-operations", ("procedures.discontinuation",), "discontinuation"),
    _section_spec("endpoint-criteria.termination", "18.3.", "Patient Termination", "protocol-operations", ("procedures.termination", "risks_benefits.risks"), "termination"),
    _section_spec("endpoint-criteria.study-termination", "18.4.", "Study Termination", "protocol-operations", ("procedures.study_termination",), "study-termination"),
    _section_spec("endpoint-criteria.study-completion", "18.5.", "Study Completion", "protocol-operations", ("study.timeline", "procedures.visit_schedule"), "study-completion"),
    _section_spec("risks-benefits", "19.", "SUMMARY OF RISKS AND BENEFITS", role="container"),
    _section_spec("risks-benefits.risks", "19.1.", "Summary of risks", "protocol-analysis-and-oversight", ("risks_benefits.risks",), "protocol-sparse-risks"),
    _section_spec("risks-benefits.benefits", "19.2.", "Summary of benefits", "protocol-analysis-and-oversight", ("risks_benefits.benefits",), "protocol-sparse-benefits"),
)

RETROSPECTIVE_1_TO_13: tuple[SectionSpec, ...] = (
    _section_spec("title-page", "1.", "TITLE PAGE", role="container"),
    _section_spec("investigator-agreement", "2.", "INVESTIGATOR AGREEMENT", role="container"),
    _section_spec("table-of-contents", "3.", "TABLE OF CONTENTS", role="container"),
    _section_spec("introduction", "4.", "INTRODUCTION", "protocol-foundations", ("study.background", "study.unmet_need")),
    _section_spec("objectives", "5.", "OBJECTIVE(S)", "protocol-foundations", ("objectives.primary", "endpoints.primary")),
    _section_spec("subjects", "6.", "SUBJECTS", role="container"),
    _section_spec("subjects.population", "6.1.", "Subject Population", "protocol-foundations", ("population.study_population", "population.sample_size")),
    _section_spec("subjects.eligibility", "6.2.", "Inclusion/Exclusion Criteria", "protocol-foundations", ("population.inclusion_criteria", "population.exclusion_criteria")),
    _section_spec("study-design", "7.", "STUDY DESIGN", role="container"),
    _section_spec("study-design.design", "7.1.", "Study Design", "protocol-foundations", ("design.study_design",)),
    _section_spec("study-design.bias", "7.2.", "Methods Used to Minimize Bias", "protocol-foundations", ("design.study_design",), "retrospective-bias"),
    _section_spec("study-procedure", "8.", "STUDY PROCEDURE", role="container"),
    _section_spec("study-procedure.enrollment", "8.1.", "Informed Consent / Subject Enrollment", "protocol-operations", ("procedures.assessments", "procedures.visit_schedule_table", "procedures.visit_schedule", "study.timeline"), "retrospective-consent"),
    _section_spec("analysis-plan", "9.", "ANALYSIS PLAN", role="container"),
    _section_spec("analysis-plan.datasets", "9.1.", "Analysis Data Sets", "protocol-analysis-and-oversight", ("statistics.analysis_plan",)),
    _section_spec("analysis-plan.methodology", "9.2.", "Statistical Methodology", "protocol-analysis-and-oversight", ("statistics.methodology", "statistics.analysis_plan")),
    _section_spec("analysis-plan.considerations", "9.3.", "General Statistical Considerations", "protocol-analysis-and-oversight", ("statistics.analysis_plan",)),
    _section_spec("sample-size", "10.", "SAMPLE SIZE JUSTIFICATION", "protocol-analysis-and-oversight", ("population.sample_size", "population.sample_justification")),
    _section_spec("confidentiality", "11.", "CONFIDENTIALITY/PUBLICATION OF THE STUDY", "protocol-analysis-and-oversight", ("risks_benefits.privacy", "confidentiality.data_handling"), "retrospective-confidentiality"),
    _section_spec("quality-safety", "12.", "QUALITY COMPLAINTS AND ADVERSE EVENTS", "protocol-analysis-and-oversight", ("risks_benefits.risks",), "retrospective-safety"),
    _section_spec("ethics", "13.", "GCP, ICH AND ETHICAL CONSIDERATIONS", "protocol-analysis-and-oversight", ("parties.irb.name",), "ethics"),
)

ICF_STUDY_SECTIONS: tuple[SectionSpec, ...] = (
    _section_spec("icf.study-purpose", "", "Study purpose", "icf-narrative", ("objectives.primary", "study.background", "study.hypothesis", "endpoints.primary")),
    _section_spec("icf.procedures", "", "What will happen", "icf-narrative", ("procedures.assessments", "procedures.visit_schedule", "procedures.minimum_days_before_screening_without_participation")),
    _section_spec("icf.duration", "", "Length and participation", "icf-narrative", ("study.timeline", "population.sample_size")),
    _section_spec("icf.risks", "", "Risks and discomforts", "icf-narrative", ("risks_benefits.risks",), "icf-sparse-risks"),
    _section_spec("icf.benefits", "", "Potential benefits", "icf-narrative", ("risks_benefits.benefits",), "icf-sparse-benefits"),
    _section_spec("icf.payment", "", "Payment", "icf-narrative", ("risks_benefits.compensation_or_reimbursement",)),
    _section_spec("icf.costs", "", "Costs", "icf-narrative", ("risks_benefits.costs",), "costs"),
    _section_spec("icf.alternatives", "", "Alternatives", "icf-narrative", ("risks_benefits.alternatives",), "alternatives"),
    _section_spec("icf.privacy", "", "Privacy", "icf-narrative", ("risks_benefits.privacy", "confidentiality.data_handling"), "icf-privacy-authorization"),
    _section_spec("icf.injury", "", "Research injury", "icf-narrative", ("risks_benefits.injury_handling",), "injury"),
)

ICF_RETAINED_SHELL_SECTIONS = {
    "advarra-prospective": (
        ("icf.introduction", "INTRODUCTION"),
        ("icf.legal-rights", "LEGAL RIGHTS"),
        ("icf.contact-information", "WHOM TO CONTACT ABOUT THIS STUDY"),
        ("icf.leaving-study", "LEAVING THE STUDY"),
        ("icf.agreement", "AGREEMENT TO BE IN THE STUDY"),
    ),
    "advarra-ambispective": (
        ("icf.introduction", "INTRODUCTION"),
        ("icf.legal-rights", "LEGAL RIGHTS"),
        ("icf.new-findings", "NEW FINDINGS"),
        ("icf.contact-information", "WHOM TO CONTACT ABOUT THIS STUDY"),
        ("icf.leaving-study", "LEAVING THE STUDY"),
        ("icf.agreement", "AGREEMENT TO BE IN THE STUDY"),
    ),
    "sterling": (
        ("icf.authorization-introduction", "AUTHORIZATION TO USE AND DISCLOSE MEDICAL INFORMATION"),
        ("icf.key-information", "KEY INFORMATION"),
        ("icf.background", "BACKGROUND"),
        ("icf.information", "INFORMATION"),
        ("icf.voluntary-participation", "VOLUNTARY PARTICIPATION/WITHDRAWAL"),
        ("icf.contact-information", "QUESTIONS"),
        ("icf.participant-authorization", "PARTICIPANT STATEMENT AUTHORIZATION"),
    ),
}


def protocol_contract(study_type: str) -> tuple[SectionSpec, ...]:
    return RETROSPECTIVE_1_TO_13 if canonical_study_type(study_type) == "Retrospective" else PROTOCOL_1_TO_19


def icf_contract(study_type: str, icf_template: str = "Advarra") -> tuple[SectionSpec, ...]:
    branch = canonical_study_type(study_type)
    if branch == "Retrospective":
        return ()
    if branch == "Prospective" and str(icf_template).strip().casefold() != "sterling":
        return tuple(section for section in ICF_STUDY_SECTIONS if section.section_id != "icf.injury")
    return ICF_STUDY_SECTIONS


def icf_retained_sections(study_type: str, icf_template: str = "Advarra") -> tuple[tuple[str, str], ...]:
    branch = canonical_study_type(study_type)
    if branch == "Retrospective":
        return ()
    if str(icf_template).strip().casefold() == "sterling":
        return ICF_RETAINED_SHELL_SECTIONS["sterling"]
    key = "advarra-ambispective" if branch == "Ambispective" else "advarra-prospective"
    return ICF_RETAINED_SHELL_SECTIONS[key]


def batch_plan(study_type: str, icf_template: str = "Advarra") -> tuple[BatchSpec, ...]:
    branch = canonical_study_type(study_type)
    sections = protocol_contract(branch or "")
    plans = []
    for batch_id, families in (
        ("protocol-foundations", ("study", "objectives", "population", "design", "endpoints", "procedures")),
        ("protocol-operations", ("study", "procedures", "population", "design", "endpoints", "risks_benefits")),
        ("protocol-analysis-and-oversight", ("statistics", "safety", "ethics", "confidentiality", "risks_benefits", "endpoints", "procedures", "population", "parties")),
    ):
        plans.append(BatchSpec(batch_id, "protocol", tuple(s.section_id for s in sections if s.batch_id == batch_id), families))
    if branch != "Retrospective":
        plans.append(BatchSpec("icf-narrative", "icf", tuple(s.section_id for s in icf_contract(branch or "", icf_template)), ("study", "objectives", "endpoints", "population", "design", "procedures", "risks_benefits", "confidentiality", "parties")))
        plans.append(BatchSpec("prs-narrative", "prs", ("prs.brief-summary", "prs.detailed-description"), ("study", "objectives", "design", "endpoints", "population", "procedures"), ("protocol-foundations",)))
    return tuple(plans)


def canonical_study_type(value: Any) -> str | None:
    text = str(value or "").strip()
    if text in DOCUMENT_SETS:
        return text
    lowered = text.casefold()
    for alias, canonical in STUDY_TYPE_ALIASES.items():
        if alias in lowered:
            return canonical
    return None


def _prs_study_type_from_design(reference: Mapping[str, Any]) -> str | None:
    design = " ".join(str(get_path(reference, "design.study_design") or "").casefold().split())
    matches = {
        PRS_STUDY_TYPES[match.group("classification")]
        for assertion in PRS_CLASSIFICATION_ASSERTIONS
        if (match := assertion.match(design)) is not None
    }
    return next(iter(matches)) if len(matches) == 1 else None


def document_set(value: Any) -> tuple[str, ...]:
    return DOCUMENT_SETS.get(canonical_study_type(value) or "", ())


def get_path(data: Any, dotted_path: str, default: Any = None) -> Any:
    current = data
    for part in dotted_path.split("."):
        if isinstance(current, Mapping):
            current = current.get(part, default)
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return default
    return current


def set_path(data: dict[str, Any], dotted_path: str, value: Any) -> None:
    parts = dotted_path.split(".")
    current: Any = data
    for index, part in enumerate(parts[:-1]):
        next_part = parts[index + 1]
        if isinstance(current, list):
            while len(current) <= int(part):
                current.append({})
            current = current[int(part)]
            continue
        if next_part.isdigit():
            current = current.setdefault(part, [])
        else:
            current = current.setdefault(part, {})
    final = parts[-1]
    if isinstance(current, list) and final.isdigit():
        while len(current) <= int(final):
            current.append(None)
        current[int(final)] = value
    elif isinstance(current, dict):
        current[final] = value


def meaningful(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return any(meaningful(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(meaningful(item) for item in value)
    return True


def _site_group(reference: Mapping[str, Any], kind: str) -> Any:
    sites = reference.get("sites") if isinstance(reference.get("sites"), list) else []
    key = {"site_facilities": "facility", "site_contacts": "contact", "site_investigators": "investigator"}[kind]
    values: list[Any] = []
    for site in sites:
        if not isinstance(site, Mapping):
            continue
        if key == "investigator":
            value = site.get("investigator") or site.get("investigators")
        elif key == "contact":
            value = site.get("contact") or site.get("contacts")
        else:
            value = site.get("facility")
        if meaningful(value):
            values.append(value)
    return values


def required_input_value(reference: Mapping[str, Any], requirement: RequiredInput) -> Any:
    if requirement.kind.startswith("site_"):
        return _site_group(reference, requirement.kind)
    for path in (requirement.field, *requirement.aliases):
        value = get_path(reference, path)
        if meaningful(value):
            return value
    return None


def _candidate_signature(value: Any) -> str | None:
    if isinstance(value, Mapping) and "value" in value:
        value = value.get("value")
    if not meaningful(value):
        return None
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value).strip().casefold()
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).casefold()


def _sample_size_signature(value: Any) -> str | None:
    """Normalize common count forms such as 40 and '40 participants'."""
    if isinstance(value, Mapping) and "value" in value:
        value = value.get("value")
    if not meaningful(value):
        return None
    text = re.sub(r"\s+", " ", str(value)).strip().casefold()
    count = re.search(r"(?<!\w)(\d[\d,]*(?:\.\d+)?)", text)
    return count.group(1).replace(",", "") if count else text


def _duration_days(value: Any) -> float | None:
    """Convert a simple reviewer-supplied duration into comparable days."""
    text = re.sub(r"\s+", " ", str(value or "")).strip().casefold()
    number_words = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13", "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17", "eighteen": "18", "nineteen": "19", "twenty": "20"}
    for word, number in number_words.items():
        text = re.sub(rf"\b{word}\b", number, text)
    number_first = re.findall(r"(\d+(?:\.\d+)?)\s*[- ]?(day|days|week|weeks|month|months|year|years)\b", text)
    unit_first = [(number, unit) for unit, number in re.findall(r"\b(day|week|month|year)\s*[- ]?(\d+(?:\.\d+)?)", text)]
    matches = [*number_first, *unit_first]
    if not matches:
        return None
    factors = {"day": 1.0, "days": 1.0, "week": 7.0, "weeks": 7.0, "month": 30.4375, "months": 30.4375, "year": 365.25, "years": 365.25}
    return max(float(number) * factors[unit] for number, unit in matches)


def _scheduled_duration_days(reference: Mapping[str, Any]) -> float | None:
    values: list[Any] = []

    def collect(value: Any) -> None:
        if isinstance(value, Mapping):
            for item in value.values(): collect(item)
        elif isinstance(value, list):
            for item in value: collect(item)
        elif value not in (None, ""):
            values.append(value)

    collect(get_path(reference, "procedures.assessments", []))
    collect(get_path(reference, "procedures.visit_schedule_table", []))
    collect(get_path(reference, "procedures.visit_schedule", []))
    for outcome_kind in ("primary", "secondary", "other"):
        outcome_rows = get_path(reference, f"endpoints.{outcome_kind}", []) or []
        if isinstance(outcome_rows, (str, Mapping)):
            outcome_rows = [outcome_rows]
        for row in outcome_rows:
            if isinstance(row, Mapping): values.append(row.get("outcome_time_frame") or row.get("time_frame") or row.get("time_point"))
            else: values.append(row)
    durations = [days for value in values if (days := _duration_days(value)) is not None]
    return max(durations) if durations else None


def input_findings(reference: Mapping[str, Any]) -> list[dict[str, Any]]:
    branch = canonical_study_type(get_path(reference, "meta.study_type"))
    if not branch:
        return [{"category": "source-evidence", "field": "meta.study_type", "issue": "Study type must be Prospective, Ambispective, or Retrospective.", "required": "One supported study type."}]
    requirements = RETROSPECTIVE_REQUIRED if branch == "Retrospective" else PROSPECTIVE_REQUIRED
    findings: list[dict[str, Any]] = []
    candidates = get_path(reference, "source.field_candidates", {})
    candidates = candidates if isinstance(candidates, Mapping) else {}
    for requirement in requirements:
        if not meaningful(required_input_value(reference, requirement)):
            findings.append({"category": "source-evidence", "field": requirement.field, "issue": "Required Source Input is missing.", "required": requirement.label or requirement.field})
        signatures = {_candidate_signature(value) for value in candidates.get(requirement.field, []) if _candidate_signature(value)}
        if len(signatures) > 1:
            findings.append({"category": "source-evidence", "field": requirement.field, "issue": "Required Source Input has conflicting source candidates.", "required": "One reviewer-selected value."})
    if branch != "Retrospective":
        prs_study_type = get_path(reference, "regulatory.prs.study_type")
        if meaningful(prs_study_type) and str(prs_study_type) not in PRS_STUDY_TYPES.values():
            findings.append({
                "category": "source-evidence",
                "field": "regulatory.prs.study_type",
                "issue": "PRS study type must be Observational or Interventional.",
                "required": "Observational or Interventional.",
            })
    sample_size = _sample_size_signature(get_path(reference, "population.sample_size"))
    for evidence_path in ("population.sample_size_evidence", "statistics.sample_size_evidence"):
        rows = get_path(reference, evidence_path, [])
        if not isinstance(rows, list):
            continue
        evidence_sizes = {_sample_size_signature(row) for row in rows if _sample_size_signature(row)}
        if sample_size and any(value != sample_size for value in evidence_sizes):
            findings.append({"category": "source-evidence", "field": evidence_path, "issue": "Sample-size evidence conflicts with the approved planned sample size.", "required": "Evidence rows that use the same participant count as population.sample_size."})
    timeline_days = _duration_days(get_path(reference, "study.timeline"))
    scheduled_days = _scheduled_duration_days(reference)
    tolerance = max(1.0, timeline_days * 0.02) if timeline_days is not None else 0.0
    if timeline_days is not None and scheduled_days is not None and scheduled_days > timeline_days + tolerance:
        findings.append({"category": "source-evidence", "field": "study.timeline", "issue": "The approved visit/outcome schedule extends beyond the stated study timeline.", "required": "A timeline at least as long as the latest approved visit or outcome time point."})
    if branch != "Retrospective":
        choice = str(get_path(reference, "meta.icf_template", "")).strip().casefold()
        if choice not in {"advarra", "sterling"}:
            findings.append({"category": "source-evidence", "field": "meta.icf_template", "issue": "ICF Template Choice is unresolved.", "required": "Advarra or Sterling."})
        for outcome_kind in ("primary", "secondary", "other"):
            value = get_path(reference, f"endpoints.{outcome_kind}", [])
            if outcome_kind == "primary" and (not isinstance(value, list) or not value):
                findings.append({"category": "source-evidence", "field": "endpoints.primary", "issue": "Primary outcomes must be a non-empty structured list.", "required": "One or more outcome rows with measure and time frame."})
                continue
            if value in (None, "", []):
                continue
            if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
                findings.append({"category": "source-evidence", "field": f"endpoints.{outcome_kind}", "issue": "Outcome data must be a structured list, not free text.", "required": "Outcome rows with measure and time frame."})
                continue
            for index, item in enumerate(value):
                measure = item.get("outcome_measure") or item.get("measure") or item.get("label")
                time_frame = item.get("outcome_time_frame") or item.get("time_frame") or item.get("time_point")
                if not meaningful(measure):
                    findings.append({"category": "source-evidence", "field": f"endpoints.{outcome_kind}.{index}.measure", "issue": "Outcome measure is missing.", "required": "Reviewer-approved outcome measure."})
                if not meaningful(time_frame):
                    findings.append({"category": "source-evidence", "field": f"endpoints.{outcome_kind}.{index}.time_frame", "issue": "Outcome time frame is missing.", "required": "Reviewer-approved outcome time frame."})
    count = get_path(reference, "design.number_of_sites")
    sites = _site_group(reference, "site_facilities")
    try:
        count_number = int(str(count).strip())
    except (TypeError, ValueError):
        count_number = None
    if branch != "Retrospective" and count_number is not None and sites and count_number != len(sites):
        findings.append({"category": "source-evidence", "field": "design.number_of_sites", "issue": f"Site count is {count_number}, but {len(sites)} facility entries were approved.", "required": "Consistent site count and facility rows."})
    design_text = str(get_path(reference, "design.study_design", "")).casefold()
    if count_number == 1 and "multicenter" in design_text:
        findings.append({"category": "source-evidence", "field": "design.study_design", "issue": "Study design says multicenter but the approved site count is one.", "required": "A consistent center description and site count."})
    if count_number and count_number > 1 and ("single-center" in design_text or "single center" in design_text):
        findings.append({"category": "source-evidence", "field": "design.study_design", "issue": "Study design says single-center but the approved site count is greater than one.", "required": "A consistent center description and site count."})
    return findings


def source_contract(
    reference: Mapping[str, Any],
    *,
    require_approval: bool = False,
    run_dir: Path | None = None,
    derive_prs_study_type: bool = False,
) -> dict[str, Any]:
    normalized = copy.deepcopy(dict(reference))
    for legacy_key in ("template_fields", "generated", "needs_review"):
        normalized.pop(legacy_key, None)
    branch = canonical_study_type(get_path(normalized, "meta.study_type"))
    if branch:
        normalized.setdefault("meta", {})["study_type"] = branch
        normalized["meta"]["document_set"] = [name.replace(".docx", "_docx").replace("study.xml", "xml") for name in DOCUMENT_SETS[branch]]
    raw_prs_study_type = get_path(normalized, "regulatory.prs.study_type")
    if derive_prs_study_type and branch != "Retrospective" and not meaningful(raw_prs_study_type):
        if prs_study_type := _prs_study_type_from_design(normalized):
            set_path(normalized, "regulatory.prs.study_type", prs_study_type)
    findings = input_findings(normalized)
    if require_approval:
        if str(get_path(normalized, "approval.status", "")).casefold() != "approved":
            findings.append({"category": "approval", "field": "approval.status", "issue": "The current Source-of-Truth Markdown has not been explicitly approved.", "required": "Explicit approval of the current file."})
        review_file = get_path(normalized, "approval.review_file")
        if not review_file or (run_dir is not None and not (run_dir / str(review_file)).is_file()):
            findings.append({"category": "approval", "field": "approval.review_file", "issue": "The approved Source-of-Truth Markdown file is unavailable.", "required": "An existing reviewer-facing Markdown file."})
    return {"status": "passed" if not findings else "blocked", "study_type": branch, "blocking_findings": findings, "normalized_reference": normalized}


def evidence_available(reference: Mapping[str, Any], paths: Iterable[str]) -> list[str]:
    return [path for path in paths if meaningful(get_path(reference, path))]


def contract_payload(reference: Mapping[str, Any]) -> dict[str, Any]:
    branch = canonical_study_type(get_path(reference, "meta.study_type")) or ""
    icf_template = str(get_path(reference, "meta.icf_template", "Advarra"))
    return {
        "version": CONTRACT_VERSION,
        "study_type": branch,
        "document_set": list(DOCUMENT_SETS.get(branch, ())),
        "protocol_sections": [section.public() for section in protocol_contract(branch)],
        "icf_sections": [section.public() for section in icf_contract(branch, icf_template)],
        "retained_icf_sections": [dict(section_id=section_id, title=title) for section_id, title in icf_retained_sections(branch, icf_template)],
        "batches": [batch.public() for batch in batch_plan(branch, icf_template)],
        "boilerplate_version": BOILERPLATE_VERSION,
    }


def contract_hash(reference: Mapping[str, Any]) -> str:
    encoded = json.dumps(contract_payload(reference), sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


EDITABLE_ROOTS = ("meta", "study", "parties", "sites", "population", "design", "objectives", "endpoints", "procedures", "statistics", "safety", "ethics", "confidentiality", "risks_benefits", "regulatory")
OPERATIONAL_META = {"document_set", "run_id"}
FIELD_RE = re.compile(r"<!--\s*field:\s*([^>]+?)\s*-->(.*?)<!--\s*/field\s*-->", re.DOTALL | re.I)


def _flatten_row(value: Mapping[str, Any], prefix: str = "") -> dict[str, str]:
    result: dict[str, str] = {}
    for key, item in value.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(item, Mapping):
            result.update(_flatten_row(item, path))
        elif isinstance(item, list) and item and all(isinstance(part, Mapping) for part in item):
            for index, part in enumerate(item):
                result.update(_flatten_row(part, f"{path}.{index}"))
        elif isinstance(item, list):
            result[path] = "; ".join(str(part) for part in item)
        else:
            result[path] = "" if item is None else str(item)
    return result


def _unflatten_row(value: Mapping[str, str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for path, item in value.items():
        set_path(result, path, item)
    return result


def _table(value: list[Mapping[str, Any]]) -> str:
    rows = [_flatten_row(item) for item in value]
    columns = sorted({column for row in rows for column in row})
    if not columns:
        return ""
    escape = lambda item: str(item).replace("|", "\\|").replace("\n", "<br>")
    lines = ["| " + " | ".join(escape(item) for item in columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    lines.extend("| " + " | ".join(escape(row.get(column, "")) for column in columns) + " |" for row in rows)
    return "\n".join(lines)


def _format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list) and all(isinstance(item, Mapping) for item in value):
        return _table(value)
    if isinstance(value, list):
        return "\n".join(f"- {item}" for item in value)
    return str(value)


def _editable_fields(reference: Mapping[str, Any]) -> list[tuple[str, Any]]:
    fields: list[tuple[str, Any]] = []

    def walk(value: Any, path: str) -> None:
        if path == "meta" and isinstance(value, Mapping):
            for key, item in value.items():
                if key not in OPERATIONAL_META:
                    walk(item, f"meta.{key}")
            return
        if isinstance(value, Mapping):
            for key, item in value.items():
                walk(item, f"{path}.{key}" if path else str(key))
        elif isinstance(value, list) and value and all(isinstance(item, Mapping) for item in value):
            fields.append((path, value))
        else:
            fields.append((path, value))

    for root in EDITABLE_ROOTS:
        if root in reference:
            walk(reference[root], root)
    return fields


def source_truth_markdown(reference: Mapping[str, Any]) -> str:
    title = str(get_path(reference, "study.title", "Untitled study"))
    lines = [
        "# Clinical Study Source of Truth",
        "",
        f"Preview only (do not edit): {title}",
        "",
        "Edit only values inside the marked field blocks below. Lists use Markdown bullets and repeated records use Markdown tables.",
        "",
        "## Editable Study Inputs Start Here",
        "",
    ]
    for path, value in _editable_fields(reference):
        label = path.replace("_", " ").replace(".", " / ").title()
        lines.extend((f"### {label}", f"<!-- field: {path} -->", _format_value(value), "<!-- /field -->", ""))
    return "\n".join(lines).rstrip() + "\n"


def _split_table_line(line: str) -> list[str]:
    raw = line.strip().strip("|")
    parts = re.split(r"(?<!\\)\|", raw)
    return [part.strip().replace("\\|", "|").replace("<br>", "\n") for part in parts]


def _parse_value(text: str) -> Any:
    value = text.strip()
    if not value:
        return None
    lines = [line.rstrip() for line in value.splitlines() if line.strip()]
    if len(lines) >= 2 and lines[0].lstrip().startswith("|") and re.match(r"^\|?\s*:?-+", lines[1]):
        columns = _split_table_line(lines[0])
        return [_unflatten_row(dict(zip(columns, _split_table_line(line)))) for line in lines[2:] if line.lstrip().startswith("|")]
    if all(line.lstrip().startswith(("- ", "* ")) for line in lines):
        return [line.lstrip()[2:].strip() for line in lines]
    return value


def parse_source_truth(markdown: str, prior_reference: Mapping[str, Any]) -> dict[str, Any]:
    matches = list(FIELD_RE.finditer(markdown))
    if not matches:
        raise ValueError("Source-of-Truth Markdown contains no mapped field blocks.")
    result: dict[str, Any] = {
        "meta": {key: copy.deepcopy(value) for key, value in dict(prior_reference.get("meta") or {}).items() if key in OPERATIONAL_META},
        "source": copy.deepcopy(dict(prior_reference.get("source") or {})),
        "approval": copy.deepcopy(dict(prior_reference.get("approval") or {})),
    }
    seen: set[str] = set()
    for match in matches:
        path = match.group(1).strip()
        if path in seen:
            raise ValueError(f"Source-of-Truth Markdown repeats field marker: {path}")
        if path.split(".", 1)[0] not in EDITABLE_ROOTS:
            raise ValueError(f"Source-of-Truth Markdown contains unsupported field marker: {path}")
        seen.add(path)
        set_path(result, path, _parse_value(match.group(2)))
    expected = {path for path, _value in _editable_fields(prior_reference)}
    if seen != expected:
        missing = sorted(expected - seen)
        added = sorted(seen - expected)
        raise ValueError(
            "Source-of-Truth Markdown field marker set changed; "
            f"missing={missing}, added={added}. Preserve every generated marker exactly."
        )
    branch = canonical_study_type(get_path(result, "meta.study_type"))
    if branch:
        result["meta"]["study_type"] = branch
        result["meta"]["document_set"] = [name.replace(".docx", "_docx").replace("study.xml", "xml") for name in DOCUMENT_SETS[branch]]
    return result


def repair_report(findings: Iterable[Mapping[str, Any]]) -> str:
    items = list(findings)
    lines = ["# Clinical Document Repair Report", "", "The Branch Document Set was not released.", ""]
    for finding in items:
        lines.extend((f"## {finding.get('field') or finding.get('target') or 'Run blocker'}", f"- Category: {finding.get('category', 'unknown')}", f"- Problem: {finding.get('issue', 'Unspecified failure.')}", f"- Next action: {finding.get('next_action') or finding.get('required') or 'Correct the named target and retry.'}", ""))
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "BOILERPLATE_VERSION", "CONTRACT_VERSION", "DOCUMENT_SETS", "FORBIDDEN_DRAFT_LANGUAGE",
    "BatchSpec", "ICF_RETAINED_SHELL_SECTIONS", "ICF_STUDY_SECTIONS", "PROTOCOL_1_TO_19", "RETROSPECTIVE_1_TO_13", "SectionSpec",
    "batch_plan", "canonical_study_type", "contract_hash", "contract_payload", "document_set",
    "evidence_available", "get_path", "input_findings", "meaningful", "parse_source_truth",
    "icf_contract", "icf_retained_sections", "protocol_contract", "repair_report", "set_path", "source_contract", "source_truth_markdown",
]
