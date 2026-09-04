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
import unicodedata
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping
from xml.etree import ElementTree as ET


CONTRACT_VERSION = "clinical-documents-v2.19"
BOILERPLATE_VERSION = "clinical-boilerplate-v8"
CONTRACTED_TEMPLATE_BUNDLE_SCHEMA = "contracted-template-bundle/v2"
LAYOUT_PRESERVATION_BASELINE_SCHEMA = "layout-preservation-baseline/v1"
APPROVED_FONT_PLAN_VERSION = "approved-font-plan/v1"
SAFETY_ROLE_RESPONSIBILITY_CONCEPTS = {
    "assess_safety_events",
    "report_safety_events",
}

RECOVERY_POLICIES = {
    "adapter_fault": "advance_adapter",
    "font_capability_uncertainty": "bounded_smoke_render",
    "document_structure_defect": "preserve_and_stop",
    "visual_defect": "targeted_layout_repair",
    "drafting_defect": "retry_drafting_target",
    "verifier_transient": "retry_verifier",
    "transport_fault": "retry_exact_bytes",
}


def recovery_finding(
    finding: Mapping[str, Any],
    recovery_class: str,
    *,
    action: str | None = None,
) -> dict[str, Any]:
    """Attach one governed Recovery Class without interpreting issue prose."""
    if recovery_class not in RECOVERY_POLICIES:
        raise ValueError(f"Unknown Recovery Class: {recovery_class}")
    return {
        **dict(finding),
        "recovery_class": recovery_class,
        "action": action or RECOVERY_POLICIES[recovery_class],
    }

LAYOUT_REPAIR_RULES = {
    "protocol": ("heading_cohesion", "table_pagination"),
    "icf": ("heading_cohesion", "heading_whitespace_cohesion", "table_pagination"),
}

BUNDLED_FONT_FILES = {
    "Liberation Sans": "LiberationSans-Regular.ttf",
    "Liberation Serif": "LiberationSerif-Regular.ttf",
    "Liberation Mono": "LiberationMono-Regular.ttf",
}

APPROVED_PACKAGED_FONT_FALLBACKS = {
    "arial": "Liberation Sans",
    "arial unicode ms": "Liberation Sans",
    "aptos": "Liberation Sans",
    "calibri": "Liberation Sans",
    "dejavu sans": "Liberation Sans",
    "helvetica": "Liberation Sans",
    "noto sans": "Liberation Sans",
    "noto sans symbols": "Liberation Sans",
    "segoe ui symbol": "Liberation Sans",
    "symbol": "Liberation Sans",
    "verdana": "Liberation Sans",
    "times new roman": "Liberation Serif",
    "courier new": "Liberation Mono",
}

PACKAGED_FONT_ASSETS = (
    "assets/fallback-fonts/LiberationMono-Bold.ttf",
    "assets/fallback-fonts/LiberationMono-BoldItalic.ttf",
    "assets/fallback-fonts/LiberationMono-Italic.ttf",
    "assets/fallback-fonts/LiberationMono-Regular.ttf",
    "assets/fallback-fonts/LiberationSans-Bold.ttf",
    "assets/fallback-fonts/LiberationSans-BoldItalic.ttf",
    "assets/fallback-fonts/LiberationSans-Italic.ttf",
    "assets/fallback-fonts/LiberationSans-Regular.ttf",
    "assets/fallback-fonts/LiberationSerif-Bold.ttf",
    "assets/fallback-fonts/LiberationSerif-BoldItalic.ttf",
    "assets/fallback-fonts/LiberationSerif-Italic.ttf",
    "assets/fallback-fonts/LiberationSerif-Regular.ttf",
)

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
    fidelity_evidence: tuple[str, ...] = ()

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


class ContractedTemplateBundleError(ValueError):
    """One fail-closed error for an incomplete or inconsistent bundle."""

    def __init__(self, problems: Iterable[str]):
        details = tuple(dict.fromkeys(str(problem) for problem in problems if str(problem)))
        self.finding = {
            "category": "contract",
            "field": "contracted_template_bundle",
            "issue": "Contracted Template Bundle is incomplete or inconsistent: " + "; ".join(details),
            "required": "Restore one complete contracted resource set and retry before drafting.",
        }
        super().__init__(self.finding["issue"])


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
        "statistics.sample_size_evidence",
        ("population.sample_size_evidence",),
        "sample-size evidence rows",
    ),
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
        "endpoint-criteria.completion": "Name every approved visit and time point, then state the participant-completion rule without omitting supplied follow-up.",
        "endpoint-criteria.study-completion": "Name every approved visit and time point, then state the study-completion rule without omitting supplied follow-up.",
        "analysis-plan.datasets": "Identify the analysis populations or data sets supported by the approved analysis plan.",
        "analysis-plan.methodology": "Explain the approved statistical methods and map them explicitly to every supplied primary and secondary endpoint.",
        "analysis-plan.considerations": "Explain the approved analysis conventions, software/version, and interpretation considerations, including only source-supported handling of paired or missing observations.",
        "sample-size": "State the approved sample size and explain its approved justification.",
        "confidentiality-publication": "Preserve the approved publication, records, and retention requirements without substituting generic policy language.",
        "study-procedure.discontinued": "Preserve the approved operational handling for discontinued subjects, including any supplied safety follow-up.",
        "quality-safety": (
            "For each approved safety.roles record, write a separate direct active-voice sentence beginning "
            "with the exact approved party name, state only that party's approved safety-event responsibilities, "
            "and name no other responsible party; also explain the approved risks and safety boundary."
        ),
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
        "study-procedure.discontinued",
        "evaluation-procedures", "endpoint-criteria.completion",
        "endpoint-criteria.discontinuation", "endpoint-criteria.study-completion", "analysis-plan.datasets",
        "analysis-plan.methodology", "analysis-plan.considerations", "sample-size", "confidentiality-publication", "confidentiality",
        "financial-injury", "risks-benefits.risks", "risks-benefits.benefits",
        "icf.procedures", "icf.risks", "icf.benefits", "icf.payment", "icf.privacy",
    }
    return "all_material_items" if section_id in item_complete_sections else "all_material_evidence"


def _fidelity_evidence(section_id: str) -> tuple[str, ...]:
    """Name source fields whose concrete operational qualifiers must survive rendering."""
    return {
        "study-procedure.visits": ("procedures.assessment_details", "procedures.intervention_management"),
        "study-procedure.discontinued": ("procedures.discontinued_subjects",),
        "analysis-plan.datasets": ("statistics.analysis_populations",),
        "analysis-plan.methodology": ("statistics.methodology", "endpoints.other"),
        "analysis-plan.considerations": ("statistics.software",),
        "confidentiality-publication": ("confidentiality.retention",),
        "financial-injury": ("risks_benefits.injury_handling",),
        "risks-benefits.risks": ("risks_benefits.risks",),
        "risks-benefits.benefits": ("risks_benefits.benefits", "risks_benefits.compensation_or_reimbursement"),
        "endpoint-criteria.discontinuation": ("procedures.discontinuation", "procedures.replacement"),
    }.get(section_id, ())


def _section_spec(
    section_id: str,
    number: str,
    title: str,
    batch: str = "",
    evidence: Iterable[str] = (),
    boilerplate: str | None = None,
    role: str = "leaf",
    required: bool = True,
) -> SectionSpec:
    return SectionSpec(
        section_id,
        number,
        title,
        role,
        batch,
        tuple(evidence),
        boilerplate,
        required,
        content_expectations=_content_expectations(section_id, title),
        source_coverage=_source_coverage(section_id),
        fidelity_evidence=_fidelity_evidence(section_id),
    )


PROTOCOL_1_TO_19: tuple[SectionSpec, ...] = (
    _section_spec("title-page", "1.", "TITLE PAGE", role="container"),
    _section_spec("investigator-agreement", "2.", "INVESTIGATOR AGREEMENT", role="container"),
    _section_spec("general-information", "3.", "GENERAL INFORMATION", role="container"),
    _section_spec("table-of-contents", "4.", "TABLE OF CONTENTS", role="container"),
    _section_spec("introduction", "5.", "INTRODUCTION", "protocol-foundations", ("study.background", "study.title", "study.hypothesis", "endpoints.primary")),
    _section_spec("objectives", "6.", "OBJECTIVE(S)", "protocol-foundations", ("objectives.primary", "objectives.secondary", "study.hypothesis", "endpoints.primary", "endpoints.secondary", "endpoints.other")),
    _section_spec("subjects", "7.", "SUBJECTS", role="container"),
    _section_spec("subjects.population", "7.1.", "Subject Population", "protocol-foundations", ("population.study_population", "population.sample_size")),
    _section_spec("subjects.inclusion", "7.2.", "Inclusion Criteria", "protocol-foundations", ("population.inclusion_criteria", "procedures.minimum_days_before_screening_without_participation")),
    _section_spec("subjects.exclusion", "7.3.", "Exclusion Criteria", "protocol-foundations", ("population.exclusion_criteria",)),
    _section_spec("study-design", "8.", "STUDY DESIGN", role="container"),
    _section_spec("study-design.design", "8.1.", "Study Design", "protocol-foundations", ("design.study_design",)),
    _section_spec("study-design.bias", "8.2.", "Methods Used to Minimize Bias", "protocol-foundations", ("design.study_design",), "bias"),
    _section_spec(
        "study-design.assignment",
        "8.3.",
        "Method of Assigning Subjects to Treatment Arms",
        evidence=("design.assignment_method",),
        role="source",
        required=False,
    ),
    _section_spec("study-procedure", "9.", "STUDY PROCEDURE", role="container"),
    _section_spec("study-procedure.consent", "9.1.", "Informed Consent / Subject Enrollment", "protocol-operations", ("procedures.consent",), "consent"),
    _section_spec("study-procedure.visits", "9.2.", "Visits and Examinations", "protocol-operations", ("procedures.assessments", "procedures.visit_schedule", "procedures.assessment_details", "procedures.intervention_management")),
    _section_spec("study-procedure.measurements", "9.3.", "Study Methods and Measurements", "protocol-operations", ("procedures.methods", "procedures.assessments", "procedures.visit_schedule", "procedures.assessment_details", "study.hypothesis", "endpoints.primary", "endpoints.secondary", "endpoints.other")),
    _section_spec("study-procedure.unscheduled", "9.4.", "Unscheduled Visits", "protocol-operations", ("procedures.unscheduled_visits",), "unscheduled"),
    _section_spec("study-procedure.discontinued", "9.5.", "Discontinued Subjects", "protocol-operations", ("procedures.discontinued_subjects",), "discontinued-subjects"),
    _section_spec("analysis-plan", "10.", "ANALYSIS PLAN", role="container"),
    _section_spec("analysis-plan.datasets", "10.1.", "Analysis Data Sets", "protocol-analysis-and-oversight", ("statistics.analysis_plan", "statistics.analysis_populations", "endpoints.primary", "endpoints.secondary", "endpoints.other")),
    _section_spec("analysis-plan.methodology", "10.2.", "Statistical Methodology", "protocol-analysis-and-oversight", ("statistics.methodology", "statistics.analysis_plan", "endpoints.primary", "endpoints.secondary", "endpoints.other")),
    _section_spec("analysis-plan.considerations", "10.3.", "General Statistical Considerations", "protocol-analysis-and-oversight", ("statistics.analysis_plan", "statistics.software", "endpoints.primary", "endpoints.secondary")),
    _section_spec("sample-size", "11.", "SAMPLE SIZE JUSTIFICATION", "protocol-analysis-and-oversight", ("population.sample_size", "population.sample_justification", "population.sample_size_evidence", "statistics.sample_size_evidence")),
    _section_spec("confidentiality-publication", "12.", "CONFIDENTIALITY/PUBLICATION OF THE STUDY", "protocol-analysis-and-oversight", ("confidentiality.publication", "confidentiality.retention"), "publication"),
    _section_spec("quality-safety", "13.", "QUALITY COMPLAINTS AND ADVERSE EVENTS", role="container"),
    _section_spec("quality-safety.general", "13.1.", "General Information", "protocol-analysis-and-oversight", ("safety.general_information", "risks_benefits.risks"), "safety-general"),
    _section_spec("quality-safety.monitoring", "13.2.", "Monitoring for Adverse Events", "protocol-analysis-and-oversight", ("safety.monitoring",), "safety-monitoring"),
    _section_spec("quality-safety.reporting", "13.3.", "Procedures for Recording and Reporting AEs and SAEs", "protocol-analysis-and-oversight", ("safety.adverse_events",), "safety-reporting"),
    _section_spec("quality-safety.follow-up", "13.4.", "Follow-Up of Adverse Events and Quality Complaints", "protocol-analysis-and-oversight", ("safety.follow_up",), "safety-followup"),
    _section_spec("quality-safety.analysis", "13.5.", "Safety Analyses", "protocol-analysis-and-oversight", ("statistics.analysis_plan", "safety.adverse_events"), "safety-analysis"),
    _section_spec("ethics", "14.", "GCP, ICH AND ETHICAL CONSIDERATIONS", boilerplate="ethics", role="container"),
    _section_spec("ethics.confidentiality", "14.1.", "Confidentiality", "protocol-analysis-and-oversight", ("ethics.confidentiality", "confidentiality.data_handling"), "confidentiality-cross-reference"),
    _section_spec("evaluation-procedures", "15.", "STANDARD EVALUATION PROCEDURES", "protocol-operations", ("procedures.assessments", "procedures.visit_schedule")),
    _section_spec("confidentiality", "16.", "CONFIDENTIALITY", "protocol-analysis-and-oversight", ("confidentiality.data_handling", "risks_benefits.privacy"), "confidentiality"),
    _section_spec("financial-injury", "17.", "FINANCIAL AND INSURANCE INFORMATION/STUDY RELATED INJURIES", "protocol-analysis-and-oversight", ("risks_benefits.compensation_or_reimbursement", "risks_benefits.injury_handling"), "injury"),
    _section_spec("endpoint-criteria", "18.", "STUDY ENDPOINT CRITERIA", role="container"),
    _section_spec("endpoint-criteria.completion", "18.1.", "Patient Completion of Study", "protocol-operations", ("study.timeline", "procedures.visit_schedule", "procedures.assessments"), "completion"),
    _section_spec("endpoint-criteria.discontinuation", "18.2.", "Patient Discontinuation", "protocol-operations", ("procedures.discontinuation", "procedures.replacement"), "discontinuation"),
    _section_spec("endpoint-criteria.termination", "18.3.", "Patient Termination", "protocol-operations", ("procedures.termination", "risks_benefits.risks"), "termination"),
    _section_spec("endpoint-criteria.study-termination", "18.4.", "Study Termination", "protocol-operations", ("procedures.study_termination",), "study-termination"),
    _section_spec("endpoint-criteria.study-completion", "18.5.", "Study Completion", "protocol-operations", ("study.timeline", "procedures.visit_schedule", "procedures.assessments"), "study-completion"),
    _section_spec("risks-benefits", "19.", "SUMMARY OF RISKS AND BENEFITS", role="container"),
    _section_spec("risks-benefits.risks", "19.1.", "Summary of risks", "protocol-analysis-and-oversight", ("risks_benefits.risks",), "protocol-sparse-risks"),
    _section_spec("risks-benefits.benefits", "19.2.", "Summary of benefits", "protocol-analysis-and-oversight", ("risks_benefits.benefits", "risks_benefits.compensation_or_reimbursement"), "protocol-sparse-benefits"),
)

RETROSPECTIVE_1_TO_13: tuple[SectionSpec, ...] = (
    _section_spec("title-page", "1.", "TITLE PAGE", role="container"),
    _section_spec("investigator-agreement", "2.", "INVESTIGATOR AGREEMENT", role="container"),
    _section_spec("table-of-contents", "3.", "TABLE OF CONTENTS", role="container"),
    _section_spec("introduction", "4.", "INTRODUCTION", "protocol-foundations", ("study.background", "study.unmet_need", "study.title", "study.hypothesis", "endpoints.primary")),
    _section_spec("objectives", "5.", "OBJECTIVE(S)", "protocol-foundations", ("objectives.primary", "objectives.secondary", "study.hypothesis", "endpoints.primary", "endpoints.secondary")),
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
    _section_spec("quality-safety", "12.", "QUALITY COMPLAINTS AND ADVERSE EVENTS", "protocol-analysis-and-oversight", ("risks_benefits.risks", "safety.roles"), "retrospective-safety"),
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


SAMPLE_SIZE_EVIDENCE_COLUMNS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("study", "Study", ()),
    ("timepoint", "Timepoint", ("time_point",)),
    ("mean_change_ods_vas", "Mean Change ODS-VAS", ()),
    ("se", "SE", ("standard_error",)),
    ("estimated_sd", "Estimated SD", ("estimated_standard_deviation",)),
    ("evidence", "Evidence", ()),
    ("value", "Value", ()),
    ("source", "Source", ()),
)
DETAILED_SAMPLE_SIZE_COLUMNS = (
    "study",
    "timepoint",
    "mean_change_ods_vas",
    "se",
    "estimated_sd",
)
LEGACY_SAMPLE_SIZE_COLUMNS = ("evidence", "value", "source")


def _table_value(row: Mapping[str, Any], key: str, aliases: tuple[str, ...]) -> str:
    for candidate in (key, *aliases):
        if meaningful(row.get(candidate)):
            return str(row[candidate]).strip()
    return ""


def _sample_size_evidence_records(
    reference: Mapping[str, Any],
) -> list[tuple[str, int, Mapping[str, Any]]]:
    """Combine unique rows while preserving each row's approved source path."""
    records: list[tuple[str, int, Mapping[str, Any]]] = []
    seen: set[str] = set()
    for path in ("statistics.sample_size_evidence", "population.sample_size_evidence"):
        value = get_path(reference, path, [])
        if not isinstance(value, list):
            continue
        for index, row in enumerate(value):
            if not isinstance(row, Mapping):
                continue
            identity = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
            if identity not in seen:
                records.append((path, index, row))
                seen.add(identity)
    return records


def _sample_size_evidence_rows(reference: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [row for _path, _index, row in _sample_size_evidence_records(reference)]


def protocol_table_contracts(reference: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Return typed, source-derived Protocol table matrices for rendering and QA."""
    schedule = get_path(reference, "procedures.visit_schedule", [])
    visits = [item for item in schedule if isinstance(item, Mapping)] if isinstance(schedule, list) else []
    assessment_rows: list[list[str]] = []
    if visits:
        normalized_visits = []
        for index, visit in enumerate(visits, 1):
            name = str(visit.get("visit") or visit.get("visitName") or f"Visit {index}").strip()
            timing = str(visit.get("timing") or visit.get("visitWindow") or "").strip()
            raw_procedures = visit.get("procedures")
            procedures = (
                [str(item).strip() for item in raw_procedures if meaningful(item)]
                if isinstance(raw_procedures, list)
                else [item.strip() for item in re.split(r"[;\n]", str(raw_procedures or "")) if item.strip()]
            )
            normalized_visits.append({"name": name, "timing": timing, "procedures": procedures})
        activities = list(dict.fromkeys(
            activity for visit in normalized_visits for activity in visit["procedures"]
        ))
        if activities:
            def header_label(visit: Mapping[str, Any]) -> str:
                name, timing = str(visit["name"]), str(visit["timing"])
                if not timing:
                    return name
                normalized_name = re.sub(r"\s+", " ", name).strip().casefold()
                normalized_timing = re.sub(r"\s+", " ", timing).strip().casefold()
                return name if normalized_name == normalized_timing else f"{name}\n({timing})"

            assessment_rows = [
                ["Activity", *[header_label(visit) for visit in normalized_visits]],
                ["Activity", *[f"Visit {index}" for index, _visit in enumerate(normalized_visits, 1)]],
                *[
                    [activity, *["X" if activity in visit["procedures"] else "" for visit in normalized_visits]]
                    for activity in activities
                ],
            ]
    if not assessment_rows:
        entries = []
        schedule_table = get_path(reference, "procedures.visit_schedule_table", [])
        if isinstance(schedule_table, list):
            for item in schedule_table:
                if not isinstance(item, Mapping):
                    continue
                label = str(item.get("visitName") or item.get("visit") or "").strip()
                timing = str(item.get("visitWindow") or item.get("timing") or "").strip()
                if label:
                    entries.append([label, timing])
        if entries:
            assessment_rows = [["Approved visit or assessment", "Approved timing"], *entries]
        else:
            assessments = get_path(reference, "procedures.assessments", [])
            if isinstance(assessments, list):
                labels = [str(item).strip() for item in assessments if meaningful(item)]
            else:
                labels = [
                    item.strip()
                    for item in re.split(r",\s*(?:including\s+|and\s+)?|\n", str(assessments or "").rstrip("."), flags=re.I)
                    if item.strip()
                ]
            def assessment_timing(label: str) -> str:
                match = re.search(r"\b(?:Month|Week|Day)\s+[+-]?\d+\b", label, re.I)
                if match:
                    return match.group(0)
                lowered = label.casefold()
                if "baseline" in lowered:
                    return "Baseline"
                if "historical" in lowered:
                    return "Historical record review"
                if "screening" in lowered:
                    return "Screening"
                return "Per approved schedule"
            if labels:
                assessment_rows = [
                    ["Approved visit or assessment", "Approved timing"],
                    *[[label, assessment_timing(label)] for label in labels],
                ]

    evidence_rows = _sample_size_evidence_rows(reference)
    selected_columns = [
        (key, label, aliases)
        for key, label, aliases in SAMPLE_SIZE_EVIDENCE_COLUMNS
        if any(_table_value(row, key, aliases) for row in evidence_rows)
    ]
    sample_rows = (
        [
            [label for _key, label, _aliases in selected_columns],
            *[
                [_table_value(row, key, aliases) for key, _label, aliases in selected_columns]
                for row in evidence_rows
            ],
        ]
        if evidence_rows and selected_columns
        else []
    )
    return {
        "schedule-of-assessments": {
            "section_id": "evaluation-procedures",
            "caption": "Table 15.1. Proposed Visits and Study Assessments",
            "header_rows": 2 if assessment_rows and assessment_rows[0][0] == "Activity" else 1,
            "rows": assessment_rows,
        },
        "sample-size-evidence": {
            "section_id": "sample-size",
            "caption": "Table 11-1. Sample Size Supporting Evidence",
            "header_rows": 1,
            "rows": sample_rows,
        },
    }


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
    if isinstance(value, Mapping):
        explicit = next((
            value.get(key)
            for key in ("planned_sample_size", "sample_size", "participants", "participant_count", "enrollment", "value")
            if meaningful(value.get(key))
        ), None)
        if explicit is None:
            return None
        value = explicit
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


def _valid_safety_role_record(item: Any) -> bool:
    if (
        not isinstance(item, Mapping)
        or set(item) != {"party", "responsibilities"}
        or not isinstance(item.get("party"), str)
        or not meaningful(item.get("party"))
        or not isinstance(item.get("responsibilities"), str)
    ):
        return False
    concepts = {
        part.strip()
        for part in item["responsibilities"].split(";")
        if part.strip()
    }
    return bool(concepts) and concepts <= SAFETY_ROLE_RESPONSIBILITY_CONCEPTS


def _safety_party_identity(value: str) -> str:
    words = re.findall(r"[^\W_]+|\d+", unicodedata.normalize("NFC", value).casefold())
    if words[:1] == ["the"]:
        words = words[1:]
    return " ".join(words)


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
        if meaningful(rows) and not isinstance(rows, list):
            findings.append({
                "category": "source-evidence",
                "field": evidence_path,
                "issue": "Sample-size evidence must be a list of typed row objects.",
                "required": "A list using only the approved sample-size evidence columns.",
            })
            continue
        if not isinstance(rows, list):
            continue
        allowed_keys = {
            candidate
            for key, _label, aliases in SAMPLE_SIZE_EVIDENCE_COLUMNS
            for candidate in (key, *aliases)
        }
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping):
                findings.append({
                    "category": "source-evidence",
                    "field": f"{evidence_path}.{index}",
                    "issue": "Sample-size evidence rows must be typed objects.",
                    "required": "One object using only the approved sample-size evidence columns.",
                })
                continue
            unsupported = sorted(str(key) for key in set(row) - allowed_keys)
            if unsupported:
                findings.append({
                    "category": "source-evidence",
                    "field": f"{evidence_path}.{index}",
                    "issue": "Sample-size evidence contains unsupported columns that cannot be rendered without data loss: " + ", ".join(unsupported),
                    "required": "Use the approved sample-size evidence schema or extend the versioned contract before approval.",
                })
            for key, _label, aliases in SAMPLE_SIZE_EVIDENCE_COLUMNS:
                values = {
                    str(row[candidate]).strip()
                    for candidate in (key, *aliases)
                    if meaningful(row.get(candidate))
                }
                if len(values) > 1:
                    findings.append({
                        "category": "source-evidence",
                        "field": f"{evidence_path}.{index}.{key}",
                        "issue": "Sample-size evidence aliases contain conflicting values.",
                        "required": "One approved value for the column.",
                    })
        evidence_sizes = {_sample_size_signature(row) for row in rows if _sample_size_signature(row)}
        if sample_size and any(value != sample_size for value in evidence_sizes):
            findings.append({"category": "source-evidence", "field": evidence_path, "issue": "Sample-size evidence conflicts with the approved planned sample size.", "required": "Evidence rows that use the same participant count as population.sample_size."})
    combined_records = _sample_size_evidence_records(reference)
    combined_evidence = [row for _path, _index, row in combined_records]
    if branch != "Retrospective" and combined_evidence:
        present_columns = {
            key
            for key, _label, aliases in SAMPLE_SIZE_EVIDENCE_COLUMNS
            if any(_table_value(row, key, aliases) for row in combined_evidence)
        }
        detailed_present = set(DETAILED_SAMPLE_SIZE_COLUMNS) & present_columns
        legacy_present = set(LEGACY_SAMPLE_SIZE_COLUMNS) & present_columns
        schema = DETAILED_SAMPLE_SIZE_COLUMNS if detailed_present else LEGACY_SAMPLE_SIZE_COLUMNS
        missing = [column for column in schema if column not in present_columns]
        if missing:
            findings.append({
                "category": "source-evidence",
                "field": "statistics.sample_size_evidence",
                "issue": "Sample-size evidence is missing required table columns: " + ", ".join(missing),
                "required": "A complete detailed evidence schema or the complete approved legacy evidence schema.",
            })
        if detailed_present and legacy_present:
            findings.append({
                "category": "source-evidence",
                "field": "statistics.sample_size_evidence",
                "issue": "Sample-size evidence mixes detailed and legacy table schemas.",
                "required": "Use one complete approved sample-size evidence schema per study.",
            })
        column_aliases = {
            key: aliases for key, _label, aliases in SAMPLE_SIZE_EVIDENCE_COLUMNS
        }
        aggregate_labels = {"average", "pooled", "combined", "overall"}
        for evidence_path, source_index, row in combined_records:
            allowed_blanks: set[str] = set()
            if schema == DETAILED_SAMPLE_SIZE_COLUMNS:
                label = _table_value(row, "study", column_aliases["study"]).casefold()
                if label in aggregate_labels:
                    allowed_blanks = {"timepoint", "se"}
            row_missing = [
                column
                for column in schema
                if column not in allowed_blanks
                and not _table_value(row, column, column_aliases[column])
            ]
            if row_missing:
                findings.append({
                    "category": "source-evidence",
                    "field": f"{evidence_path}.{source_index}",
                    "issue": "Sample-size evidence row is missing required values: " + ", ".join(row_missing),
                    "required": "Populate every required cell; only aggregate rows may leave timepoint and SE blank.",
                })
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
    else:
        safety_roles = get_path(reference, "safety.roles")
        if meaningful(safety_roles) and (
            not isinstance(safety_roles, list)
            or any(not _valid_safety_role_record(item) for item in safety_roles)
            or len({_safety_party_identity(item["party"]) for item in safety_roles if isinstance(item, Mapping)}) != len(safety_roles)
        ):
            findings.append({
                "category": "source-evidence",
                "field": "safety.roles",
                "issue": "Retrospective safety roles must be structured party/responsibility records.",
                "required": (
                    "One or more exact {party, responsibilities} text records; responsibilities use "
                    "semicolon-separated assess_safety_events/report_safety_events concepts."
                ),
            })
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


def section_applies(reference: Mapping[str, Any], section: SectionSpec) -> bool:
    """Return the single contract decision used to scope a document section."""
    return section.required or bool(evidence_available(reference, section.evidence))


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


_PROTOCOL_TEMPLATES = {
    "Prospective": "assets/client-templates/docx/prospective-protocol.template.docx",
    "Ambispective": "assets/client-templates/docx/ambispective-protocol.template.docx",
    "Retrospective": "assets/client-templates/docx/retrospective-protocol.template.docx",
}

_ICF_TEMPLATES = {
    ("Prospective", "Advarra"): "assets/client-templates/docx/prospective-icf.template.docx",
    ("Prospective", "Sterling"): "assets/client-templates/docx/sterling-icf.template.docx",
    ("Ambispective", "Advarra"): "assets/client-templates/docx/ambispective-icf.template.docx",
    ("Ambispective", "Sterling"): "assets/client-templates/docx/sterling-icf.template.docx",
}

_CLIENT_AUTHORITIES = {
    "protocol": "assets/client-templates/reference/protocol-reference.docx",
    "Advarra": "assets/client-templates/reference/advarra-icf-reference.docx",
    "Sterling": "assets/client-templates/reference/sterling-icf-reference.docx",
}

_PRS_RESOURCES = {
    "generation_template": "assets/client-templates/prs/clinicaltrials_prs_full_placeholder_template.xml",
    "structural_reference": "assets/client-templates/reference/prs-manual-reference.xml",
}

_BOILERPLATE_RESOURCE = "references/fixed-clinical-boilerplate.json"


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _identity_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _governed_asset_problem(path: Path, relative: str) -> str | None:
    if path.suffix.casefold() == ".docx":
        try:
            with zipfile.ZipFile(path) as package:
                names = set(package.namelist())
                required = {"[Content_Types].xml", "word/document.xml"}
                if missing := sorted(required - names):
                    return f"governed DOCX lacks required package parts: {relative} ({', '.join(missing)})"
                if corrupt := package.testzip():
                    return f"governed DOCX has a corrupt package part: {relative} ({corrupt})"
                for name in names:
                    if name.endswith((".xml", ".rels")):
                        ET.fromstring(package.read(name))
        except (OSError, ET.ParseError, KeyError, zipfile.BadZipFile) as exc:
            return f"governed DOCX is invalid: {relative} ({exc})"
    elif relative in _PRS_RESOURCES.values():
        try:
            root = ET.parse(path).getroot()
        except (OSError, ET.ParseError) as exc:
            return f"governed PRS XML is invalid: {relative} ({exc})"
        local_name = root.tag.rsplit("}", 1)[-1]
        child_names = [child.tag.rsplit("}", 1)[-1] for child in root]
        if local_name != "study_collection" or child_names.count("clinical_study") != 1:
            return f"governed PRS XML has an inconsistent study_collection structure: {relative}"
    elif path.suffix.casefold() == ".ttf":
        try:
            header = path.read_bytes()
            if len(header) < 12 or header[:4] not in {b"\x00\x01\x00\x00", b"OTTO", b"true", b"typ1"}:
                return f"governed packaged font has an invalid sfnt header: {relative}"
            table_count = int.from_bytes(header[4:6], "big")
            directory_end = 12 + (16 * table_count)
            if not table_count or directory_end > len(header):
                return f"governed packaged font has an invalid table directory: {relative}"
            for offset in range(12, directory_end, 16):
                table_offset = int.from_bytes(header[offset + 8:offset + 12], "big")
                table_length = int.from_bytes(header[offset + 12:offset + 16], "big")
                if table_offset + table_length > len(header):
                    return f"governed packaged font has an out-of-range table: {relative}"
        except OSError as exc:
            return f"governed packaged font is unreadable: {relative} ({exc})"
    return None


def contracted_template_bundle(repo_root: Path, reference: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve the one complete governed resource identity for a study selection."""
    root = repo_root.resolve()
    problems: list[str] = []
    branch = canonical_study_type(get_path(reference, "meta.study_type"))
    if branch not in DOCUMENT_SETS:
        raise ContractedTemplateBundleError(("study branch is missing or uncontracted",))

    icf_family: str | None = None
    if branch != "Retrospective":
        raw_family = str(get_path(reference, "meta.icf_template", "")).strip()
        icf_family = next((family for family in ("Advarra", "Sterling") if family.casefold() == raw_family.casefold()), None)
        if icf_family is None:
            raise ContractedTemplateBundleError(("ICF Template Choice is missing or uncontracted",))

    resource_hashes: dict[str, str] = {}

    def resource(relative: str) -> dict[str, str]:
        path = root / relative
        if not path.is_file():
            problems.append(f"governed resource is missing: {relative}")
            digest = ""
        else:
            try:
                digest = _sha256_path(path)
                if problem := _governed_asset_problem(path, relative):
                    problems.append(problem)
            except OSError as exc:
                problems.append(f"governed resource cannot be read: {relative} ({exc})")
                digest = ""
        resource_hashes[relative] = digest
        return {"path": relative, "sha256": digest}

    contracted_templates = {"protocol": resource(_PROTOCOL_TEMPLATES[branch])}
    client_authorities = {"protocol": resource(_CLIENT_AUTHORITIES["protocol"])}
    if icf_family is not None:
        contracted_templates["icf"] = resource(_ICF_TEMPLATES[(branch, icf_family)])
        client_authorities["icf"] = resource(_CLIENT_AUTHORITIES[icf_family])

    prs_authority = (
        {name: resource(relative) for name, relative in _PRS_RESOURCES.items()}
        if branch != "Retrospective"
        else None
    )
    boilerplate = resource(_BOILERPLATE_RESOURCE)
    boilerplate_payload: dict[str, Any] = {}
    if boilerplate["sha256"]:
        try:
            value = json.loads((root / _BOILERPLATE_RESOURCE).read_text(encoding="utf-8"))
            if isinstance(value, dict):
                boilerplate_payload = value
            else:
                problems.append("Fixed Clinical Boilerplate is not a JSON object")
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            problems.append(f"Fixed Clinical Boilerplate is unreadable: {exc}")
    if boilerplate_payload.get("version") != BOILERPLATE_VERSION:
        problems.append("Fixed Clinical Boilerplate version does not match the Document Section Contract")
    sections = boilerplate_payload.get("sections")
    if not isinstance(sections, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in sections.items()):
        problems.append("Fixed Clinical Boilerplate must contain a string map named sections")
        sections = {}
    governed_sections = list(protocol_contract(branch))
    if icf_family is not None:
        governed_sections.extend(icf_contract(branch, icf_family))
    missing_boilerplate = sorted({section.boilerplate_key for section in governed_sections if section.boilerplate_key and section.boilerplate_key not in sections})
    if missing_boilerplate:
        problems.append("Document Section Contract references missing Fixed Clinical Boilerplate: " + ", ".join(missing_boilerplate))

    font_assets = {relative: resource(relative) for relative in PACKAGED_FONT_ASSETS}
    fallback_targets = set(APPROVED_PACKAGED_FONT_FALLBACKS.values())
    if fallback_targets != set(BUNDLED_FONT_FILES):
        problems.append("approved fallback families and packaged font families do not match")
    for family, filename in BUNDLED_FONT_FILES.items():
        relative = f"assets/fallback-fonts/{filename}"
        if relative not in font_assets:
            problems.append(f"approved fallback family lacks its regular packaged font: {family}")
    font_plan_payload = {
        "version": APPROVED_FONT_PLAN_VERSION,
        "available_font_policy": "preserve",
        "missing_font_policy": "approved_packaged_substitute",
        "unknown_inventory_policy": "preserve_then_resolve_by_smoke_render",
        "approved_fallbacks": dict(sorted(APPROVED_PACKAGED_FONT_FALLBACKS.items())),
        "packaged_families": dict(sorted(BUNDLED_FONT_FILES.items())),
        "packaged_font_assets": font_assets,
    }
    approved_font_plan = {**font_plan_payload, "sha256": _identity_hash(font_plan_payload)}

    layout_baseline_payload = {
        "schema_version": LAYOUT_PRESERVATION_BASELINE_SCHEMA,
        "artifacts": {
            artifact: {
                "contracted_template": dict(template),
                "client_template_authority": dict(client_authorities[artifact]),
            }
            for artifact, template in contracted_templates.items()
        },
    }
    layout_preservation_baseline = {
        **layout_baseline_payload,
        "sha256": _identity_hash(layout_baseline_payload),
    }

    if problems:
        raise ContractedTemplateBundleError(problems)

    payload = {
        "schema_version": CONTRACTED_TEMPLATE_BUNDLE_SCHEMA,
        "selection": {"study_type": branch, "icf_family": icf_family},
        "contracted_templates": contracted_templates,
        "client_template_authorities": client_authorities,
        "document_section_contract": {
            "version": CONTRACT_VERSION,
            "sha256": contract_hash(reference),
        },
        "fixed_clinical_boilerplate": {
            "version": BOILERPLATE_VERSION,
            **boilerplate,
        },
        "approved_font_plan": approved_font_plan,
        "layout_preservation_baseline": layout_preservation_baseline,
        "prs_authority": prs_authority,
        "resource_hashes": dict(sorted(resource_hashes.items())),
    }
    return {**payload, "identity_sha256": _identity_hash(payload)}


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
    "APPROVED_FONT_PLAN_VERSION", "APPROVED_PACKAGED_FONT_FALLBACKS", "BOILERPLATE_VERSION", "BUNDLED_FONT_FILES",
    "CONTRACT_VERSION", "CONTRACTED_TEMPLATE_BUNDLE_SCHEMA", "DOCUMENT_SETS", "FORBIDDEN_DRAFT_LANGUAGE", "PACKAGED_FONT_ASSETS", "RECOVERY_POLICIES", "SAFETY_ROLE_RESPONSIBILITY_CONCEPTS",
    "BatchSpec", "ContractedTemplateBundleError", "ICF_RETAINED_SHELL_SECTIONS", "ICF_STUDY_SECTIONS", "PROTOCOL_1_TO_19", "RETROSPECTIVE_1_TO_13", "SectionSpec",
    "batch_plan", "canonical_study_type", "contract_hash", "contract_payload", "contracted_template_bundle", "document_set",
    "evidence_available", "get_path", "input_findings", "meaningful", "parse_source_truth",
    "icf_contract", "icf_retained_sections", "protocol_contract", "protocol_table_contracts", "recovery_finding", "repair_report", "section_applies", "set_path", "source_contract", "source_truth_markdown",
]
