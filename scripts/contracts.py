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


CONTRACT_VERSION = "clinical-documents-v2.29-sterling-source-gates"
BOILERPLATE_VERSION = "clinical-boilerplate-v12"
STERLING_CLAUSE_CONTRACT_VERSION = "sterling-icf-modules/v2"
STERLING_CLAUSE_CONTRACT_RESOURCE = "references/sterling-clause-contract.json"
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
    "deterministic_structure_defect": "rebuild_deterministic_structure",
    "visual_defect": "targeted_layout_repair",
    "drafting_defect": "retry_drafting_target",
    "verifier_transient": "retry_verifier",
    "transport_fault": "retry_exact_bytes",
    "capability_gap": "preserve_and_stop",
}
RECOVERY_OWNERS = {
    "adapter_fault": "capability_gap",
    "font_capability_uncertainty": "capability_gap",
    "document_structure_defect": "construction",
    "deterministic_structure_defect": "construction",
    "visual_defect": "layout",
    "drafting_defect": "drafting",
    "verifier_transient": "reviewer",
    "transport_fault": "transport",
    "capability_gap": "capability_gap",
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
        "owner": RECOVERY_OWNERS[recovery_class],
    }

LAYOUT_REPAIR_RULES = {
    "protocol": (
        "heading_cohesion", "heading_whitespace_cohesion",
        "heading_page_boundary", "table_pagination", "table_page_boundary",
    ),
    "icf": (
        "heading_cohesion", "heading_whitespace_cohesion",
        "heading_page_boundary", "table_pagination", "table_page_boundary",
        "sterling_study_site_alignment",
    ),
}

LAYOUT_FAMILY_ARTIFACTS = {
    "retrospective-protocol": "protocol",
    "prospective-protocol": "protocol",
    "ambispective-protocol": "protocol",
    "advarra-icf": "icf",
    "sterling-icf": "icf",
}

# This base policy is copied into each Contracted Template family below so the
# runtime must select a family before it can select a visual disposition. A
# shared disposition is intentional; family-specific exceptions remain exact-
# target decisions in the deterministic planner.
_VISUAL_CHECK_DISPOSITION_BASE = {
    "clipping": "fail_closed",
    "overlap": "fail_closed",
    "overflow": "fail_closed",
    "orphan_heading": "repair:heading_cohesion",
    "bad_table_split": "repair:table_pagination",
    "blank_page": "prevention:render_audit",
    "footer_collision": "fail_closed",
    "unreadable_text": "fail_closed",
    "duplicate_section": "prevention:content_audit",
    "inconsistent_style": "prevention:template_contract",
    "missing_header_footer": "prevention:template_contract",
    "toc_mismatch": "prevention:toc_refresh",
    "excessive_whitespace": "repair:heading_cohesion",
    # Standalone body pagination is unsafe to rewrite. When it is derivative
    # evidence for the same exact split table, the planner lawfully coalesces
    # it into that table's narrower repair.
    "artificial_pagination": "fail_closed",
}

# Every mandatory visual check has a declared family-specific disposition. A
# prevention disposition is enforced by construction/audit; repair
# dispositions are bounded Word-native repairs; fail-closed checks retain
# evidence for governed corpus expansion rather than silently guessing.
VISUAL_CHECK_DISPOSITIONS = {
    family: dict(_VISUAL_CHECK_DISPOSITION_BASE)
    for family in LAYOUT_FAMILY_ARTIFACTS
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
    evidence_scopes: tuple[tuple[str, tuple[str, ...]], ...] = ()
    summary_concepts: tuple[str, ...] = ()
    owned_concepts: tuple[str, ...] = ()
    brief_reference_concepts: tuple[str, ...] = ()
    do_not_restate_concepts: tuple[str, ...] = ()
    boilerplate_keys: tuple[str, ...] = ()

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


# Source-intake requirements mirror the documented starred fields exactly.
# Optional supplied evidence and PRS values retain their technical validators;
# downstream output requirements must not become extra missing-input gates.
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
        "study-design.design": "Explain the approved design, setting, arms, intervention, masking, and research-versus-routine-care assignment boundary. Use the normalized study classification consistently and do not infer assignment from procedures.",
        "study-design.bias": "Explain applicable bias controls and use only the listed boilerplate when source detail is sparse.",
        "study-procedure.visits": "Account for every approved visit, time point, and visit-specific procedure.",
        "study-procedure.measurements": "Explain what is measured, when, and how in operational language. Group related endpoints where scientific meaning is preserved; do not reproduce the Objectives endpoint inventory or the complete visit schedule, and do not invent an instrument, scoring rule, denominator, or definition absent from the source.",
        "study-procedure.enrollment": "Describe the approved record-review or enrollment sequence, time points, and timeline.",
        "evaluation-procedures": "Account for every approved assessment and visit in the Schedule of Assessments narrative.",
        "endpoint-criteria.completion": "Reference every approved visit and time point concisely when stating the participant-completion rule, without repeating the complete visit or assessment inventory owned by Section 15.",
        "endpoint-criteria.study-completion": "Reference every approved visit and time point concisely when stating the study-level timeline and completion rule, without repeating the complete participant visit or assessment inventory.",
        "analysis-plan.datasets": "Identify which observations enter each source-supported analysis population or data set. Do not reproduce the endpoint inventory owned by Objectives.",
        "analysis-plan.methodology": "Explain how each endpoint is summarized or analyzed. Group endpoints sharing one method, use concise cross-references to Objectives, and do not reproduce a standalone endpoint inventory.",
        "analysis-plan.considerations": "State only source-supported cross-cutting analysis conventions or software/version details, and otherwise cross-reference Section 10.2 without repeating its methods or endpoint inventory.",
        "sample-size": "State the approved sample size and explain only its approved statistical or feasibility basis and any source-supported attrition allowance. Do not call a sample sufficient or infer an attrition rate without that support.",
        "confidentiality-publication": "Preserve the approved publication, records, and retention requirements without substituting generic policy language.",
        "study-procedure.discontinued": "Preserve the approved operational handling for discontinued subjects, including any supplied safety follow-up.",
        "quality-safety": (
            "For each approved safety.roles record, write a separate direct active-voice sentence beginning "
            "with the exact approved party name, state only that party's approved safety-event responsibilities, "
            "and name no other responsible party; also explain the approved risks and safety boundary."
        ),
        "quality-safety.analysis": (
            "Explain only the approved adverse-event or safety-analysis facts supplied for this subsection; "
            "do not restate unrelated efficacy endpoints, confidence intervals, sensor outcomes, usability, "
            "or missing-data methods from a broader analysis-plan field."
        ),
        "financial-injury": "State the approved participant-cost allocation, compensation or reimbursement terms, and research-injury care, payment, and financial responsibility. Generic promises to explain these facts later are not sufficient.",
        "risks-benefits.risks": "State every approved study-specific foreseeable risk and mitigation without replacing surgery, device, postoperative, visual-symptom, or study-procedure facts with generic inconvenience language.",
        "risks-benefits.benefits": "State that direct benefit is not guaranteed when supported and describe only source-supported knowledge benefits using the study's outcomes and intervention terminology. Do not include compensation or reimbursement.",
        "icf.study-purpose": "State the study purpose, hypothesis, and primary endpoint concisely in participant-facing language. Do not repeat the lens descriptions, comparative evidence, unmet evidence gap, or complete rationale owned by BACKGROUND.",
        "icf.key-information-summary": "Give five concise participant-facing summary blocks covering the study purpose, expected participation and duration, principal risks, possible benefit or absence of direct benefit, and alternatives plus voluntary participation. Do not copy detailed-section prose.",
        "icf.procedures": "Explain every approved eligibility criterion and age bound, visit, procedure, intervention location, research-measurement role, assignment boundary, non-treatment boundary, and minimum interval without participation in another study before screening in participant-facing sequence.",
        "icf.duration": "State only the approved participation duration and relevant time points; do not repeat planned enrollment.",
        "icf.risks": "Disclose every approved risk or discomfort and every approved risk-mitigation instruction without minimizing, inventing, or hiding safeguards.",
        "icf.benefits": "State the approved potential benefits and explicitly preserve any no-direct-benefit statement. Use study-specific outcomes and intervention terminology; do not use generic condition/intervention/procedure wording or discuss compensation or reimbursement.",
        "icf.payment": "State the approved payment or reimbursement terms exactly enough for participant use.",
        "icf.costs": "State the approved allocation of sponsor/study costs and participant/insurer or ordinary-care costs. Generic promises that the study team will explain costs later are not sufficient.",
        "icf.alternatives": "State that participation is optional and that the person may decline research while continuing or discussing ordinary care with the treating doctor; do not invent specific alternatives.",
        "icf.injury": "State who provides or arranges research-injury care, whether payment or compensation is available, and who is financially responsible. Generic deferral language is not sufficient.",
        "icf.privacy": "Explain the approved privacy and confidentiality handling in participant-facing language. Give each distinct source-specific privacy supplement a stable module_id so deterministic composition can preserve it exactly once.",
    }
    return (
        specific.get(section_id, f"Explain {title.lower()} using all material approved facts supplied for this section."),
        "Do not replace supplied detail with generic clinical prose.",
    )


def _source_coverage(section_id: str) -> str:
    if section_id in {
        "analysis-plan.considerations",
        "endpoint-criteria.completion",
        "endpoint-criteria.study-completion",
    }:
        # These sections must cite approved evidence but should reference—not
        # reproduce—the complete methods or visit/assessment inventory owned elsewhere.
        return "concept_reference"
    item_complete_sections = {
        "objectives",
        "subjects.inclusion", "subjects.exclusion", "subjects.eligibility",
        "study-procedure.visits", "study-procedure.enrollment",
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
        "financial-injury": ("risks_benefits.injury_handling", "risks_benefits.costs"),
        "risks-benefits.risks": ("risks_benefits.risks", "risks_benefits.risk_mitigation"),
        "risks-benefits.benefits": ("risks_benefits.benefits",),
        "endpoint-criteria.discontinuation": ("procedures.discontinuation", "procedures.replacement"),
        "icf.procedures": ("design.intervention_description",),
        "icf.risks": ("risks_benefits.risks", "risks_benefits.risk_mitigation"),
    }.get(section_id, ())


def _evidence_scopes(section_id: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Limit broad source fields to the clauses owned by a narrow section."""
    return {
        "quality-safety.analysis": (
            ("statistics.analysis_plan", ("adverse event", "safety")),
        ),
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
    *,
    summary_concepts: Iterable[str] = (),
    owned_concepts: Iterable[str] = (),
    brief_reference_concepts: Iterable[str] = (),
    do_not_restate_concepts: Iterable[str] = (),
    boilerplate_keys: Iterable[str] = (),
    content_expectations: Iterable[str] | None = None,
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
        content_expectations=tuple(content_expectations) if content_expectations is not None else _content_expectations(section_id, title),
        source_coverage=_source_coverage(section_id),
        fidelity_evidence=_fidelity_evidence(section_id),
        evidence_scopes=_evidence_scopes(section_id),
        summary_concepts=tuple(summary_concepts),
        owned_concepts=tuple(owned_concepts),
        brief_reference_concepts=tuple(brief_reference_concepts),
        do_not_restate_concepts=tuple(do_not_restate_concepts),
        boilerplate_keys=tuple(boilerplate_keys),
    )


PROTOCOL_1_TO_19: tuple[SectionSpec, ...] = (
    _section_spec("title-page", "1.", "TITLE PAGE", role="container"),
    _section_spec("investigator-agreement", "2.", "INVESTIGATOR AGREEMENT", role="container"),
    _section_spec("general-information", "3.", "GENERAL INFORMATION", role="summary", owned_concepts=("protocol-synopsis",), brief_reference_concepts=("endpoint-inventory",), do_not_restate_concepts=("endpoint-inventory",)),
    _section_spec("table-of-contents", "4.", "TABLE OF CONTENTS", role="container"),
    _section_spec("introduction", "5.", "INTRODUCTION", "protocol-foundations", ("study.background", "study.title", "study.hypothesis", "endpoints.primary"), owned_concepts=("clinical-rationale",), brief_reference_concepts=("study-objectives", "primary-endpoint")),
    _section_spec("objectives", "6.", "OBJECTIVE(S)", "protocol-foundations", ("objectives.primary", "objectives.secondary", "study.hypothesis", "endpoints.primary", "endpoints.secondary", "endpoints.other"), owned_concepts=("study-objectives", "endpoint-inventory"), brief_reference_concepts=("clinical-rationale", "primary-endpoint"), do_not_restate_concepts=("clinical-rationale",)),
    _section_spec("subjects", "7.", "SUBJECTS", role="container"),
    _section_spec("subjects.population", "7.1.", "Subject Population", "protocol-foundations", ("population.study_population", "population.sample_size")),
    _section_spec("subjects.inclusion", "7.2.", "Inclusion Criteria", "protocol-foundations", ("population.inclusion_criteria", "population.minimum_age", "population.maximum_age", "procedures.minimum_days_before_screening_without_participation")),
    _section_spec("subjects.exclusion", "7.3.", "Exclusion Criteria", "protocol-foundations", ("population.exclusion_criteria",)),
    _section_spec("study-design", "8.", "STUDY DESIGN", role="container"),
    _section_spec("study-design.design", "8.1.", "Study Design", "protocol-foundations", ("design.study_design", "design.assignment_method", "design.intervention_description"), owned_concepts=("study-design", "intervention-assignment")),
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
    _section_spec("study-procedure.visits", "9.2.", "Visits and Examinations", "protocol-operations", ("procedures.assessments", "procedures.visit_schedule", "procedures.assessment_details", "procedures.intervention_management"), owned_concepts=("complete-visit-schedule",)),
    _section_spec("study-procedure.measurements", "9.3.", "Study Methods and Measurements", "protocol-operations", ("procedures.methods", "procedures.assessment_details", "study.hypothesis", "endpoints.primary", "endpoints.secondary", "endpoints.other"), owned_concepts=("endpoint-measurement-methods",), brief_reference_concepts=("complete-visit-schedule", "endpoint-inventory"), do_not_restate_concepts=("complete-visit-schedule", "endpoint-inventory")),
    _section_spec("study-procedure.unscheduled", "9.4.", "Unscheduled Visits", "protocol-operations", ("procedures.unscheduled_visits",), "unscheduled"),
    _section_spec("study-procedure.discontinued", "9.5.", "Discontinued Subjects", "protocol-operations", ("procedures.discontinued_subjects",), "discontinued-subjects"),
    _section_spec("analysis-plan", "10.", "ANALYSIS PLAN", role="container"),
    _section_spec("analysis-plan.datasets", "10.1.", "Analysis Data Sets", "protocol-analysis-and-oversight", ("statistics.analysis_plan", "statistics.analysis_populations"), owned_concepts=("analysis-populations",), brief_reference_concepts=("endpoint-inventory",), do_not_restate_concepts=("endpoint-inventory",)),
    _section_spec("analysis-plan.methodology", "10.2.", "Statistical Methodology", "protocol-analysis-and-oversight", ("statistics.methodology", "statistics.analysis_plan", "endpoints.primary", "endpoints.secondary", "endpoints.other"), owned_concepts=("statistical-methods",), brief_reference_concepts=("primary-endpoint", "secondary-endpoints", "endpoint-inventory"), do_not_restate_concepts=("endpoint-inventory",)),
    _section_spec("analysis-plan.considerations", "10.3.", "General Statistical Considerations", "protocol-analysis-and-oversight", ("statistics.software",), "analysis-considerations-cross-reference", brief_reference_concepts=("statistical-methods", "endpoint-inventory"), do_not_restate_concepts=("statistical-methods", "endpoint-inventory")),
    _section_spec("sample-size", "11.", "SAMPLE SIZE JUSTIFICATION", "protocol-analysis-and-oversight", ("population.sample_size", "population.sample_justification", "population.sample_size_evidence", "statistics.sample_size_evidence")),
    _section_spec("confidentiality-publication", "12.", "CONFIDENTIALITY/PUBLICATION OF THE STUDY", "protocol-analysis-and-oversight", ("confidentiality.publication", "confidentiality.retention"), "publication"),
    _section_spec("quality-safety", "13.", "QUALITY COMPLAINTS AND ADVERSE EVENTS", role="container"),
    _section_spec("quality-safety.general", "13.1.", "General Information", "protocol-analysis-and-oversight", ("safety.general_information", "risks_benefits.risks"), "safety-general", owned_concepts=("ae-sae-definitions",)),
    _section_spec("quality-safety.monitoring", "13.2.", "Monitoring for Adverse Events", "protocol-analysis-and-oversight", ("safety.monitoring",), "safety-monitoring"),
    _section_spec("quality-safety.reporting", "13.3.", "Procedures for Recording and Reporting AEs and SAEs", "protocol-analysis-and-oversight", ("safety.adverse_events",), "safety-reporting"),
    _section_spec("quality-safety.follow-up", "13.4.", "Follow-Up of Adverse Events and Quality Complaints", "protocol-analysis-and-oversight", ("safety.follow_up",), "safety-followup"),
    _section_spec("quality-safety.analysis", "13.5.", "Safety Analyses", "protocol-analysis-and-oversight", ("statistics.analysis_plan", "safety.adverse_events"), "safety-analysis"),
    _section_spec("ethics", "14.", "GCP, ICH AND ETHICAL CONSIDERATIONS", boilerplate="ethics", role="container"),
    _section_spec("ethics.confidentiality", "14.1.", "Confidentiality", "protocol-analysis-and-oversight", ("ethics.confidentiality", "confidentiality.data_handling"), "confidentiality-cross-reference"),
    _section_spec("evaluation-procedures", "15.", "STANDARD EVALUATION PROCEDURES", "protocol-operations", ("procedures.assessments", "procedures.evaluation", "procedures.visit_schedule", "procedures.visit_schedule_table", "safety.monitoring", "safety.adverse_events", "procedures.consent")),
    _section_spec("confidentiality", "16.", "CONFIDENTIALITY", "protocol-analysis-and-oversight", ("confidentiality.data_handling", "risks_benefits.privacy"), "confidentiality"),
    _section_spec("financial-injury", "17.", "FINANCIAL AND INSURANCE INFORMATION/STUDY RELATED INJURIES", "protocol-analysis-and-oversight", ("risks_benefits.compensation_or_reimbursement", "risks_benefits.costs", "risks_benefits.injury_handling"), "injury"),
    _section_spec("endpoint-criteria", "18.", "STUDY ENDPOINT CRITERIA", role="container"),
    _section_spec("endpoint-criteria.completion", "18.1.", "Patient Completion of Study", "protocol-operations", ("procedures.completion", "study.timeline", "procedures.visit_schedule", "procedures.visit_schedule_table", "procedures.assessments"), "completion", brief_reference_concepts=("complete-visit-schedule",), do_not_restate_concepts=("complete-visit-schedule",)),
    _section_spec("endpoint-criteria.discontinuation", "18.2.", "Patient Discontinuation", "protocol-operations", ("procedures.discontinuation", "procedures.replacement"), "discontinuation"),
    _section_spec("endpoint-criteria.termination", "18.3.", "Patient Termination", evidence=("procedures.termination",), role="source", required=False),
    _section_spec("endpoint-criteria.study-termination", "18.4.", "Study Termination", evidence=("procedures.study_termination",), role="source", required=False),
    _section_spec("endpoint-criteria.study-completion", "18.5.", "Study Completion", "protocol-operations", ("study.timeline", "procedures.visit_schedule", "procedures.assessments"), "study-completion", brief_reference_concepts=("complete-visit-schedule",), do_not_restate_concepts=("complete-visit-schedule",)),
    _section_spec("risks-benefits", "19.", "SUMMARY OF RISKS AND BENEFITS", role="container"),
    _section_spec("risks-benefits.risks", "19.1.", "Summary of risks", "protocol-analysis-and-oversight", ("risks_benefits.risks", "risks_benefits.risk_mitigation"), "protocol-sparse-risks"),
    _section_spec("risks-benefits.benefits", "19.2.", "Summary of benefits", "protocol-analysis-and-oversight", ("risks_benefits.benefits",), "protocol-sparse-benefits"),
)

RETROSPECTIVE_1_TO_13: tuple[SectionSpec, ...] = (
    _section_spec("title-page", "1.", "TITLE PAGE", role="container"),
    _section_spec("investigator-agreement", "2.", "INVESTIGATOR AGREEMENT", role="container"),
    _section_spec("table-of-contents", "3.", "TABLE OF CONTENTS", role="container"),
    _section_spec("introduction", "4.", "INTRODUCTION", "protocol-foundations", ("study.background", "study.unmet_need", "study.title", "study.hypothesis", "endpoints.primary"), owned_concepts=("clinical-rationale",), brief_reference_concepts=("study-objectives", "primary-endpoint")),
    _section_spec("objectives", "5.", "OBJECTIVE(S)", "protocol-foundations", ("objectives.primary", "objectives.secondary", "study.hypothesis", "endpoints.primary", "endpoints.secondary"), owned_concepts=("study-objectives", "endpoint-inventory"), brief_reference_concepts=("clinical-rationale", "primary-endpoint"), do_not_restate_concepts=("clinical-rationale",)),
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
    _section_spec("analysis-plan.methodology", "9.2.", "Statistical Methodology", "protocol-analysis-and-oversight", ("statistics.methodology", "statistics.analysis_plan"), owned_concepts=("statistical-methods",)),
    _section_spec("analysis-plan.considerations", "9.3.", "General Statistical Considerations", "protocol-analysis-and-oversight", ("statistics.software",), "analysis-considerations-cross-reference", brief_reference_concepts=("statistical-methods", "endpoint-inventory"), do_not_restate_concepts=("statistical-methods", "endpoint-inventory")),
    _section_spec("sample-size", "10.", "SAMPLE SIZE JUSTIFICATION", "protocol-analysis-and-oversight", ("population.sample_size", "population.sample_justification")),
    _section_spec("confidentiality", "11.", "CONFIDENTIALITY/PUBLICATION OF THE STUDY", "protocol-analysis-and-oversight", ("risks_benefits.privacy", "confidentiality.data_handling"), "retrospective-confidentiality"),
    _section_spec("quality-safety", "12.", "QUALITY COMPLAINTS AND ADVERSE EVENTS", "protocol-analysis-and-oversight", ("risks_benefits.risks", "safety.roles"), "retrospective-safety"),
    _section_spec("ethics", "13.", "GCP, ICH AND ETHICAL CONSIDERATIONS", "protocol-analysis-and-oversight", ("parties.irb.name",), "ethics"),
)

ICF_STUDY_SECTIONS: tuple[SectionSpec, ...] = (
    _section_spec(
        "icf.key-information-summary", "", "KEY INFORMATION summary", "icf-narrative",
        (
            "objectives.primary", "study.background", "study.hypothesis", "endpoints.primary",
            "design.intervention_description", "design.interventions", "design.arms", "design.intervention_name",
            "procedures.assessments", "procedures.visit_schedule", "study.timeline", "population.sample_size",
            "risks_benefits.risks", "risks_benefits.risk_mitigation", "risks_benefits.benefits",
            "risks_benefits.alternatives",
        ),
        summary_concepts=(
            "study-purpose", "participation-duration", "principal-risks",
            "possible-benefit", "alternatives-voluntariness",
        ),
        boilerplate_keys=("icf-sparse-risks", "icf-sparse-benefits", "alternatives", "icf-voluntary"),
    ),
    _section_spec("icf.study-purpose", "", "Study purpose", "icf-narrative", ("objectives.primary", "study.hypothesis", "endpoints.primary"), owned_concepts=("study-purpose", "study-hypothesis", "primary-endpoint"), do_not_restate_concepts=("clinical-background", "comparative-evidence", "study-rationale")),
    _section_spec("icf.procedures", "", "What will happen", "icf-narrative", ("procedures.assessments", "procedures.visit_schedule", "design.assignment_method", "design.intervention_description", "population.inclusion_criteria", "population.exclusion_criteria", "population.minimum_age", "population.maximum_age", "procedures.minimum_days_before_screening_without_participation")),
    _section_spec("icf.duration", "", "Length and participation", "icf-narrative", ("study.timeline",)),
    _section_spec("icf.risks", "", "Risks and discomforts", "icf-narrative", ("risks_benefits.risks", "risks_benefits.risk_mitigation"), "icf-sparse-risks"),
    _section_spec("icf.benefits", "", "Potential benefits", "icf-narrative", ("risks_benefits.benefits",), "icf-sparse-benefits"),
    _section_spec("icf.payment", "", "Payment", "icf-narrative", ("risks_benefits.compensation_or_reimbursement",)),
    _section_spec("icf.costs", "", "Costs", "icf-narrative", ("risks_benefits.costs",), "costs"),
    _section_spec("icf.alternatives", "", "Alternatives", "icf-narrative", ("risks_benefits.alternatives",), "alternatives"),
    _section_spec("icf.privacy", "", "Privacy", "icf-narrative", ("risks_benefits.privacy", "confidentiality.data_handling"), "icf-privacy-authorization"),
    _section_spec("icf.injury", "", "Research injury", "icf-narrative", ("risks_benefits.injury_handling",), "injury"),
)

STERLING_BACKGROUND_SECTION = _section_spec(
    "icf.background",
    "",
    "Background",
    "icf-narrative",
    ("study.background",),
    owned_concepts=(
        "clinical-background", "comparative-evidence", "evidence-gap", "study-rationale",
    ),
    content_expectations=(
        "Explain the approved clinical and study context, relevant comparative evidence, evidence gap, and study rationale in participant-facing language.",
        "Translate technical terms for participants without adding unsupported clinical claims.",
        "Do not repeat the complete purpose, hypothesis, or primary endpoint owned by PURPOSE.",
    ),
)

ADVARRA_PURPOSE_SECTION = _section_spec(
    "icf.study-purpose",
    "",
    "Purpose of the study",
    "icf-narrative",
    ("study.background", "objectives.primary", "study.hypothesis", "endpoints.primary"),
    owned_concepts=(
        "clinical-background", "comparative-evidence", "evidence-gap", "study-rationale",
        "study-purpose", "study-hypothesis", "primary-endpoint",
    ),
    content_expectations=(
        "Give concise participant-facing context from the approved background, then state the study purpose, hypothesis, and primary endpoint when supplied.",
        "Do not duplicate the same background passage elsewhere in the Advarra ICF.",
    ),
)


def icf_summary_obligations(reference: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Return representation-neutral evidence obligations for KEY INFORMATION."""
    candidates = {
        "study-purpose": (
            "objectives.primary", "study.background", "study.hypothesis", "endpoints.primary",
            "design.intervention_description", "design.interventions", "design.arms", "design.intervention_name",
        ),
        "participation-duration": ("procedures.assessments", "procedures.visit_schedule", "study.timeline", "population.sample_size"),
        "principal-risks": ("risks_benefits.risks", "risks_benefits.risk_mitigation"),
        "possible-benefit": ("risks_benefits.benefits",),
        "alternatives-voluntariness": ("risks_benefits.alternatives",),
    }
    boilerplate_fallbacks = {
        "principal-risks": ("boilerplate:icf-sparse-risks",),
        "possible-benefit": ("boilerplate:icf-sparse-benefits",),
        "alternatives-voluntariness": ("boilerplate:alternatives",),
    }
    required_boilerplate = {
        "alternatives-voluntariness": ("icf-voluntary",),
    }
    result = {}
    for concept, paths in candidates.items():
        source_refs = [f"source:{path}" for path in paths if meaningful(get_path(reference, path))]
        boilerplate_refs = [] if source_refs else list(boilerplate_fallbacks.get(concept, ()))
        result[concept] = {
            "source_refs": source_refs,
            "boilerplate_refs": [ref.removeprefix("boilerplate:") for ref in boilerplate_refs],
            "required_boilerplate_refs": list(required_boilerplate.get(concept, ())),
            "evidence_refs": source_refs + boilerplate_refs + [
                f"boilerplate:{ref}" for ref in required_boilerplate.get(concept, ())
            ],
        }
    return result


def protocol_concept_ownership(study_type: str) -> dict[str, dict[str, list[str]]]:
    """Expose section-specific concept ownership without similarity scores."""
    return {
        section.section_id: {
            "owns": list(section.owned_concepts),
            "brief_reference_only": list(section.brief_reference_concepts),
            "do_not_restate": list(section.do_not_restate_concepts),
        }
        for section in protocol_contract(study_type)
        if section.owned_concepts or section.brief_reference_concepts or section.do_not_restate_concepts
    }


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
    sterling = str(icf_template).strip().casefold() == "sterling"
    sections = ICF_STUDY_SECTIONS
    if sterling:
        sections = tuple(
            item
            for section in sections
            for item in (
                (section, STERLING_BACKGROUND_SECTION)
                if section.section_id == "icf.key-information-summary"
                else (section,)
            )
        )
    else:
        sections = tuple(
            ADVARRA_PURPOSE_SECTION if section.section_id == "icf.study-purpose" else section
            for section in sections
            if section.section_id != "icf.key-information-summary"
        )
    if branch == "Prospective" and not sterling:
        sections = tuple(section for section in sections if section.section_id != "icf.injury")
    return sections


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
        ("protocol-operations", ("study", "procedures", "population", "design", "endpoints", "risks_benefits", "safety")),
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


def _normalized_words(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _lens_assignment_classification(reference: Mapping[str, Any]) -> str | None:
    """Classify only affirmative, source-supported lens-assignment assertions."""
    assertions: set[str] = set()
    structured = get_path(reference, "design.assignment_classification")
    if isinstance(structured, Mapping):
        value = structured.get("value")
        provenance = _normalized_words(structured.get("provenance"))
        if value in PRS_STUDY_TYPES.values() and provenance in {
            "approved source", "approved_source", "reviewer approved", "reviewer_approved",
        }:
            assertions.add(str(value))

    assignment = _normalized_words(get_path(reference, "design.assignment_method"))
    governing_negation_start = re.compile(
        r"\b(?:not\s+(?:the\s+case|true)|"
        r"it\s+(?:(?:is|was)\s+not|(?:isn|wasn)['’]?t)\s+(?:the\s+case|true)|"
        r"it\s+(?:cannot|can['’]?t)\s+be\s+(?:the\s+case|true)|"
        r"it['’]?s\s+not\s+(?:the\s+case|true))\b",
        re.I,
    )
    independent_clause_boundary = re.compile(
        r";|\bbut\b|\bhowever\b|,\s*(?:and|while|whereas|yet)\b|"
        r"\band\s+(?=(?:"
        r"(?:the\s+)?(?:intraocular\s+)?(?:lens|intervention)"
        r"(?:\s+(?:selection|assignment))?|"
        r"(?:the\s+)?(?:study|research)\s+protocol|"
        r"(?:the\s+)?(?:investigator|doctor|surgeon)"
        r")\b)",
        re.I,
    )

    def governing_scope_boundary(governed: str) -> tuple[int, int] | None:
        """Return the first unambiguous clause boundary outside the governed span."""
        protected: list[tuple[int, int]] = []
        dashes = [match.start() for match in re.finditer("—", governed)]
        if len(dashes) % 2:
            return None
        protected.extend(zip(dashes[::2], dashes[1::2]))

        for opening_quote, closing_quote in (
            ("'", "'"),
            ('"', '"'),
            ("‘", "’"),
            ("“", "”"),
        ):
            if opening_quote == closing_quote:
                positions = [
                    index
                    for index, character in enumerate(governed)
                    if character == opening_quote
                    and not (
                        opening_quote == "'"
                        and index > 0
                        and index + 1 < len(governed)
                        and governed[index - 1].isalnum()
                        and governed[index + 1].isalnum()
                    )
                ]
                if len(positions) % 2:
                    return None
                protected.extend(zip(positions[::2], positions[1::2]))
                continue
            openings = [index for index, character in enumerate(governed) if character == opening_quote]
            closings = [
                index
                for index, character in enumerate(governed)
                if character == closing_quote
                and not (
                    closing_quote == "’"
                    and index > 0
                    and index + 1 < len(governed)
                    and governed[index - 1].isalnum()
                    and governed[index + 1].isalnum()
                )
            ]
            if len(openings) != len(closings) or any(
                opening >= closing for opening, closing in zip(openings, closings)
            ):
                return None
            protected.extend(zip(openings, closings))

        stack: list[tuple[str, int]] = []
        closing = {")": "(", "]": "[", "}": "{"}
        for index, character in enumerate(governed):
            if character in "([{":
                stack.append((character, index))
            elif character in closing:
                if not stack or stack[-1][0] != closing[character]:
                    return None
                _, start = stack.pop()
                protected.append((start, index))
        if stack:
            return None

        def is_protected(index: int) -> bool:
            return any(start < index < end for start, end in protected)

        governing_start = governing_negation_start.match(governed)
        if governing_start is None:
            return None
        leading = governed[governing_start.end():]
        if leading.lstrip().startswith(","):
            opening = governing_start.end() + leading.index(",")
            closing_matches = list(
                re.finditer(r",\s*(?=that\b)", governed[opening + 1:], re.I)
            )
            if not closing_matches:
                return None
            protected.append(
                (opening, opening + 1 + closing_matches[-1].start())
            )

        that_matches = [
            match
            for match in re.finditer(r"\bthat\b", governed, re.I)
            if not is_protected(match.start())
        ]
        if not that_matches:
            return None
        that_match = that_matches[0]
        for later_that in that_matches[1:]:
            intervening_boundaries = [
                match
                for match in independent_clause_boundary.finditer(
                    governed[that_match.end():later_that.start()]
                )
                if not is_protected(that_match.end() + match.start())
            ]
            if not intervening_boundaries:
                return None
            last_boundary = intervening_boundaries[-1]
            segment_start = that_match.end() + last_boundary.end()
            if governing_negation_start.search(
                governed[segment_start:later_that.start()]
            ) is None:
                return None

        after_that = governed[that_match.end():]
        if after_that.lstrip().startswith(","):
            opening = that_match.end() + after_that.index(",")
            closing_match = re.search(
                r",\s*(?=(?:the\s+)?(?:intraocular\s+)?(?:lens|intervention|"
                r"participants?|(?:study|research)\s+protocol)\b)",
                governed[opening + 1:],
                re.I,
            )
            if closing_match is None:
                return None
            protected.append((opening, opening + 1 + closing_match.start()))

        boundary_match = next(
            (
                match
                for match in independent_clause_boundary.finditer(governed)
                if match.start() > that_match.end() and not is_protected(match.start())
            ),
            None,
        )
        boundary = boundary_match.start() if boundary_match else len(governed)
        for nested_start in governing_negation_start.finditer(governed[:boundary]):
            if nested_start.start() == 0 or is_protected(nested_start.start()):
                continue
            nested_tail = governed[nested_start.end():boundary]
            if re.match(
                r"\s*(?:that\b|—[^—]*—\s*that\b|\([^)]*\)\s*that\b|"
                r"\[[^]]*\]\s*that\b|\{[^}]*\}\s*that\b|,.*?,\s*that\b)",
                nested_tail,
                re.I,
            ) is None:
                return None
        return boundary_match.span() if boundary_match else (boundary, boundary)

    clauses: list[str] = []

    def append_sentence_clauses(sentence: str) -> bool:
        sentence = sentence.strip()
        if not sentence:
            return True
        governing_start = governing_negation_start.search(sentence)
        if governing_start is None:
            clauses.extend(
                item.strip()
                for item in independent_clause_boundary.split(sentence)
                if item.strip()
            )
            return True
        prefix = sentence[:governing_start.start()].strip(" ;")
        if prefix:
            clauses.extend(
                item.strip()
                for item in independent_clause_boundary.split(prefix)
                if item.strip()
            )
        governed = sentence[governing_start.start():].strip()
        scope_boundary = governing_scope_boundary(governed)
        if scope_boundary is None:
            return False
        boundary_start, boundary_end = scope_boundary
        clauses.append(governed[:boundary_start].strip())
        if boundary_start == len(governed):
            return True
        return append_sentence_clauses(governed[boundary_end:])

    for sentence in assignment.split("."):
        if not append_sentence_clauses(sentence):
            return None
    negation = re.compile(
        r"\b(?:not|never|no|nor|neither|without|cannot|can['’]?t|won['’]?t)\b|"
        r"\b(?:does|did|do|was|were|is|are|has|have|had|can|could|would|should|will|must)"
        r"(?:\s+not|n['’]?t)\b",
        re.I,
    )

    def affirmed(clause: str, patterns: Iterable[str]) -> bool:
        """Return true only when a complete assertion clause is affirmative."""
        return not negation.search(clause) and any(
            re.search(pattern, clause, re.I) for pattern in patterns
        )

    routine_care_patterns = (
        r"\b(?:lens|intervention)(?:\s+selection)?\b.{0,100}\b(?:routine|ordinary)[- ](?:clinical[- ]?)?care\b",
        r"\b(?:routine|ordinary)[- ](?:clinical[- ]?)?care\b.{0,100}\b(?:lens|intervention)(?:\s+selection)?\b",
    )
    independence_patterns = (
        r"\b(?:lens|intervention)\s+select(?:ion|ions)?\b.{0,35}\b(?:independent|independently)\b",
        r"\b(?:lens|intervention)\b.{0,20}\bselected\s+independently\b",
        r"\b(?:investigator|doctor|surgeon)\b.{0,25}\bindependently\s+selects?\b.{0,20}\b(?:lens|intervention)\b",
        r"\b(?:lens|intervention)\s+select(?:ion|ions|ed)?\b.{0,100}\bbefore\s+(?:study\s+)?(?:enrollment|participation)\b",
    )
    research_patterns = (
        r"\bparticipants?\b.{0,40}\bassigned\b.{0,50}\b(?:to\s+receive|lens|intervention|treatment)\b.{0,60}\bby\s+(?:the\s+)?(?:study|research)\s+protocol\b",
        r"\b(?:lens|intervention)\s+(?:select(?:ion|ions)|assignments?)\b.{0,100}\b(?:determined|assigned)\b.{0,100}\bby\s+(?:the\s+)?(?:study|research)\s+protocol\b",
        r"\b(?:lens|intervention)\b.{0,20}\bassigned\b.{0,60}\bby\s+(?:the\s+)?(?:study|research)\s+protocol\b",
        r"\b(?:study|research)\s+protocol\b.{0,50}\b(?:assigns?|determines?|dictates?)\b.{0,50}\b(?:lens|intervention|treatment)\b",
        r"\bparticipants?\b.{0,40}\brandomi[sz]ed\b.{0,40}\b(?:to\s+receive|lens|intervention|treatment)\b",
    )
    for clause in clauses:
        routine_care = affirmed(clause, routine_care_patterns)
        independent = affirmed(clause, independence_patterns)
        if routine_care and independent:
            assertions.add("Observational")
        if affirmed(clause, research_patterns):
            assertions.add("Interventional")
    if len(assertions) != 1:
        return None
    return next(iter(assertions))


def _is_lens_assignment_study(reference: Mapping[str, Any]) -> bool:
    evidence = " ".join(
        _normalized_words(get_path(reference, path))
        for path in (
            "design.intervention_name",
            "design.intervention_type",
            "design.intervention_description",
            "procedures.assessments",
            "procedures.visit_schedule",
        )
    )
    return any(marker in evidence for marker in ("intraocular lens", " lens ", "lens implantation")) and any(
        marker in evidence for marker in ("implant", "operative", "cataract surgery")
    )


def normalized_study_classification(reference: Mapping[str, Any]) -> str | None:
    """Return one source-supported document classification, or None on ambiguity."""
    declared = get_path(reference, "regulatory.prs.study_type")
    declared = str(declared) if declared in PRS_STUDY_TYPES.values() else None
    design = _prs_study_type_from_design(reference)
    lens_study = _is_lens_assignment_study(reference)
    assignment = _lens_assignment_classification(reference) if lens_study else None
    if lens_study and assignment is None:
        return None
    supported = assignment or design or declared
    if not supported:
        return None
    assertions = {item for item in (declared, design, assignment) if item}
    return supported if len(assertions) == 1 else None


def _has_all_groups(text: str, groups: Iterable[Iterable[str]]) -> bool:
    return all(any(marker in text for marker in group) for group in groups)


def _contains_unresolved_policy(text: str) -> bool:
    return any(marker in text for marker in (
        "unknown", "unresolved", "not specified", "not established",
        "to be determined", "not yet determined", "will explain", "explain later",
        "will be explained", "depends on information not provided",
    ))


def _cost_allocation_complete(value: Any) -> bool:
    text = _normalized_words(value)
    if not text or _contains_unresolved_policy(text):
        return False
    study_allocation = any(re.search(pattern, text) for pattern in (
        r"\b(?:sponsor|study)\b.{0,45}\b(?:pays?|will\s+pay|will\s+not\s+pay|covers?|will\s+cover|provided\s+at\s+no\s+cost|study-only)\b",
        r"\bstudy-only\b.{0,35}\b(?:paid|covered|testing|procedure|visit|device)\b",
    ))
    participant_allocation = any(re.search(pattern, text) for pattern in (
        r"\b(?:participant|you|insurer|insurance)\b.{0,55}\b(?:responsible|billed|will\s+pay|pays?|no\s+cost)\b",
        r"\b(?:billed|charged)\s+to\b.{0,35}\b(?:participant|you|insurer|insurance)\b",
        r"\b(?:ordinary|usual)\s+care\b.{0,55}\b(?:participant|you|insurer|insurance|billed|covered)\b",
    ))
    return study_allocation and participant_allocation


def _injury_policy_complete(value: Any) -> bool:
    text = _normalized_words(value)
    if not text or _contains_unresolved_policy(text):
        return False
    care = any(re.search(pattern, text) for pattern in (
        r"\b(?:study\s+doctor|investigator|sponsor|study)\s+(?:will\s+)?(?:arrange|provide)s?\b.{0,30}\b(?:care|treatment)\b",
        r"\bparticipant\b.{0,30}\bmust\s+(?:obtain|seek)\b.{0,25}\b(?:care|treatment)\b",
        r"\b(?:care|treatment)\b.{0,35}\b(?:will\s+be\s+)?(?:arranged|provided)\s+by\b",
    ))
    compensation = any(re.search(pattern, text) for pattern in (
        r"\bno\s+(?:additional\s+)?compensation\b",
        r"\bcompensation\b.{0,30}\b(?:is|will\s+be)\s+(?:available|provided|unavailable|not\s+available)\b",
        r"\bpayment\b.{0,30}\b(?:is|will\s+be)\s+(?:available|provided|unavailable|not\s+available)\b",
    ))
    responsibility = any(re.search(pattern, text) for pattern in (
        r"\b(?:participant|you|insurer|insurance|sponsor|study)\b.{0,45}(?<!not\s)\b(?:is|are)\s+(?:financially\s+)?responsible\b",
        r"\b(?:participant|you|insurer|insurance|sponsor|study)\b.{0,45}\bwill\s+pay\b",
        r"\b(?:costs?|expenses?)\b.{0,35}\b(?:covered|paid)\s+by\b",
    ))
    return care and compensation and responsibility


def _sample_size_rationale_complete(value: Any) -> bool:
    text = _normalized_words(value)
    if not text:
        return False
    statistical = any(marker in text for marker in ("power", "precision", "confidence interval", "standard error")) and any(
        marker in text for marker in ("assumption", "effect size", "variance", "alpha", "%", "estimate")
    )
    feasibility = "feasibility" in text and any(
        marker in text for marker in ("site", "recruit", "eligible", "volume", "capacity", "enrollment")
    )
    pilot = any(marker in text for marker in ("pilot", "exploratory")) and any(
        marker in text for marker in ("characterize", "estimate", "variability", "planning", "feasibility")
    )
    evaluable = "evaluable" in text and any(
        marker in text for marker in ("source-supported", "historical", "power", "precision", "feasibility", "pilot")
    )
    basis = statistical or feasibility or pilot or evaluable
    attrition_claim = any(marker in text for marker in ("dropout", "attrition", "withdrawn", "nonevaluable"))
    attrition_supported = any(marker in text for marker in (
        "source-supported", "historical", "prior retention", "observed retention", "retention data",
    ))
    return basis and (not attrition_claim or attrition_supported)


def evidence_claim_citation(reference: Mapping[str, Any], claim: str) -> str | None:
    """Return the citation explicitly bound to this approved evidence claim."""
    normalized_claim = _normalized_words(claim).rstrip(".")
    records: list[Mapping[str, Any]] = []
    for path in ("study.background_evidence", "study.background_citations", "references"):
        value = get_path(reference, path)
        if isinstance(value, list):
            records.extend(item for item in value if isinstance(item, Mapping))
        elif isinstance(value, Mapping):
            records.append(value)
    for record in records:
        supported_claim = _normalized_words(
            record.get("claim") or record.get("source_passage") or record.get("conclusion")
        ).rstrip(".")
        citation = record.get("citation") or record.get("reference") or record.get("source")
        if meaningful(citation) and supported_claim and (
            supported_claim in normalized_claim or normalized_claim in supported_claim
        ):
            return " ".join(str(citation).split())
    return None


def evidence_claim_supported(reference: Mapping[str, Any], claim: str) -> bool:
    """Require an approved record that binds this exact evidence claim to its citation."""
    return evidence_claim_citation(reference, claim) is not None


def linked_evidence_citations(reference: Mapping[str, Any]) -> list[str]:
    """Return unique citations from claim-linked approved evidence records."""
    citations: list[str] = []
    for path in ("study.background_evidence", "study.background_citations"):
        value = get_path(reference, path)
        records = value if isinstance(value, list) else [value]
        for record in records:
            if not isinstance(record, Mapping) or not meaningful(
                record.get("claim") or record.get("source_passage") or record.get("conclusion")
            ):
                continue
            citation = record.get("citation") or record.get("reference") or record.get("source")
            if meaningful(citation):
                citations.append(" ".join(str(citation).split()))
    return list(dict.fromkeys(citations))


def normalize_privacy_modules(
    section: Mapping[str, Any],
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Deduplicate identical privacy modules and reject conflicting same-ID payloads."""
    records: list[tuple[str, dict[str, Any], str]] = []
    for kind, key in (("paragraph", "paragraphs"), ("list", "lists")):
        values = section.get(key) if isinstance(section.get(key), list) else []
        for value in values:
            if not isinstance(value, Mapping):
                continue
            item = copy.deepcopy(dict(value))
            module_id = str(item.get("module_id") or "").strip()
            if kind == "paragraph":
                canonical_content: Any = " ".join(str(item.get("text") or "").split())
            else:
                canonical_content = [
                    " ".join(str(entry).split())
                    for entry in item.get("items", [])
                    if str(entry).strip()
                ]
            canonical = json.dumps(
                {"kind": kind, "content": canonical_content},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
            if module_id:
                item["module_id"] = module_id
                if kind == "paragraph":
                    item["text"] = canonical_content
                else:
                    item["items"] = canonical_content
            records.append((kind, item, canonical))

    payloads: dict[str, set[str]] = {}
    for _kind, item, canonical in records:
        module_id = str(item.get("module_id") or "")
        if module_id:
            payloads.setdefault(module_id, set()).add(canonical)
    conflicts = {
        module_id: sorted(values)
        for module_id, values in payloads.items()
        if len(values) > 1
    }
    findings = [
        {
            "code": f"conflicting_privacy_module:{module_id}",
            "category": "source-evidence",
            "field": "icf.privacy",
            "module_id": module_id,
            "target_ids": ["icf.privacy"],
            "issue": f"Approved privacy payloads disagree for module_id {module_id}.",
            "required": "Provide one approved payload for this privacy module identity.",
            "payload_sha256s": sorted(
                hashlib.sha256(value.encode("utf-8")).hexdigest()
                for value in values
            ),
            "publication_disposition": "blocking",
        }
        for module_id, values in sorted(conflicts.items())
    ]

    normalized: dict[str, list[dict[str, Any]]] = {"paragraphs": [], "lists": []}
    seen: set[str] = set()
    for kind, item, _canonical in records:
        module_id = str(item.get("module_id") or "")
        if module_id in conflicts:
            continue
        if module_id and module_id in seen:
            continue
        if module_id:
            seen.add(module_id)
        normalized["paragraphs" if kind == "paragraph" else "lists"].append(item)
    return normalized, findings


def release_source_findings(reference: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return post-approval facts that must block document release when absent.

    These are deliberately separate from ``input_findings``: they do not expand
    the reviewer-intake checklist, but generic deferred prose cannot satisfy the
    Protocol or ICF release contract.
    """
    branch = canonical_study_type(get_path(reference, "meta.study_type"))
    if branch not in {"Prospective", "Ambispective"}:
        return []
    findings: list[dict[str, Any]] = []

    def add(field: str, issue: str, required: str, artifacts: Iterable[str]) -> None:
        findings.append({
            "category": "source-evidence",
            "field": field,
            "issue": issue,
            "required": required,
            "affected_artifacts": list(artifacts),
            "publication_disposition": "blocking",
            "safety_critical": field in {
                "study_specific_foreseeable_risks", "research_injury_responsibility",
                "study_design_classification",
            },
        })

    classification = normalized_study_classification(reference)
    if classification is None or (
        _is_lens_assignment_study(reference)
        and _lens_assignment_classification(reference) is None
    ):
        add(
            "study_design_classification",
            "The approved source does not resolve whether lens assignment is observational or interventional, or its classification facts conflict.",
            "Submit a separately approved source correction stating whether the studied lens assignments are determined by the research protocol or selected independently as routine clinical care before study participation.",
            ("protocol.docx", "icf.docx"),
        )

    risks = _normalized_words(get_path(reference, "risks_benefits.risks"))
    generic_risk_markers = (
        "study team will explain", "will be explained later", "risks will be discussed",
    )
    lens_risk_groups = (
        ("cataract surgery", "surgical risk", "surgery risk"),
        ("intraocular lens", "lens-related", "device-related"),
        ("postoperative", "after surgery", "post-operative"),
        ("visual symptom", "visual disturbance", "dysphotops"),
        ("study procedure", "study eye examination", "research procedure", "study examination"),
    )
    risks_complete = bool(risks) and not any(marker in risks for marker in generic_risk_markers)
    if _is_lens_assignment_study(reference):
        risks_complete = risks_complete and _has_all_groups(risks, lens_risk_groups)
    if not risks_complete:
        add(
            "study_specific_foreseeable_risks",
            "Study-specific foreseeable risks are missing or generic deferral language was supplied.",
            "Provide source-supported foreseeable risks for the study, including as applicable cataract-surgery, intraocular-lens/device, postoperative, visual-symptom, and additional study-procedure risks; do not invent a risk list.",
            ("protocol.docx", "icf.docx"),
        )

    if not _cost_allocation_complete(get_path(reference, "risks_benefits.costs")):
        add(
            "participant_cost_allocation",
            "The approved source does not allocate participant, insurer, sponsor, and study costs.",
            "State which study-related procedures, devices, visits, treatment, and ordinary-care items are paid by the sponsor or study, billed to the participant or insurer, or otherwise assigned.",
            ("protocol.docx", "icf.docx"),
        )

    if not _injury_policy_complete(get_path(reference, "risks_benefits.injury_handling")):
        add(
            "research_injury_responsibility",
            "Research-injury care, payment or compensation, and financial responsibility are not established by the approved source.",
            "State who provides or arranges care for a research-related injury, whether payment or compensation is available, and who is financially responsible.",
            ("protocol.docx", "icf.docx"),
        )

    justification = (
        get_path(reference, "population.sample_justification")
        or get_path(reference, "statistics.sample_size_justification")
    )
    if not _sample_size_rationale_complete(justification):
        add(
            "sample_size_justification",
            "The sample-size rationale or attrition allowance is asserted without an approved statistical or feasibility basis.",
            "Provide approved support for the evaluable sample-size rationale and any dropout or attrition assumption; do not infer an attrition rate from planned and evaluable counts alone.",
            ("protocol.docx",),
        )
    return findings


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


def sterling_clause_contract(repo_root: Path | None = None) -> dict[str, Any]:
    """Load and validate the governed, template-derived Sterling module contract."""
    root = (repo_root or Path(__file__).resolve().parents[1]).resolve()
    path = root / STERLING_CLAUSE_CONTRACT_RESOURCE
    payload = json.loads(path.read_text(encoding="utf-8"))
    modules = payload.get("modules") if isinstance(payload, Mapping) else None
    terminology_profiles = payload.get("terminology_profiles") if isinstance(payload, Mapping) else None
    if payload.get("schema_version") != STERLING_CLAUSE_CONTRACT_VERSION:
        raise ValueError("Sterling Clause Contract version is not supported.")
    if (
        payload.get("family") != "Sterling"
        or not isinstance(modules, list)
        or not isinstance(terminology_profiles, list)
    ):
        raise ValueError("Sterling ICF module contract is malformed.")
    identifiers = [str(item.get("module_id") or "") for item in modules if isinstance(item, Mapping)]
    required_fields = {
        "module_id", "classification", "applicability", "provenance", "placement",
        "section_id", "fidelity", "substitutions", "expected_structure", "validation",
        "severity", "repeatable",
    }
    if (
        len(identifiers) != len(modules)
        or not all(identifiers)
        or len(identifiers) != len(set(identifiers))
        or any(not required_fields <= set(item) for item in modules if isinstance(item, Mapping))
    ):
        raise ValueError("Sterling ICF module contract contains incomplete or duplicate modules.")
    allowed = {"core", "conditional", "source-bound"}
    if any(str(item.get("classification")) not in allowed for item in modules):
        raise ValueError("Sterling ICF module contract contains an unknown classification.")
    if any(
        not str(profile.get("profile_id") or "").strip()
        or not isinstance(profile.get("applicability"), Mapping)
        or not isinstance(profile.get("preferred"), Mapping)
        or not isinstance(profile.get("replacements"), Mapping)
        or not isinstance(profile.get("prohibited"), list)
        for profile in terminology_profiles
        if isinstance(profile, Mapping)
    ) or len(terminology_profiles) != len({
        str(profile.get("profile_id")) for profile in terminology_profiles if isinstance(profile, Mapping)
    }):
        raise ValueError("Sterling ICF terminology profiles are incomplete or duplicated.")
    allowed_triggers = {"always", "meaningful", "truthy"}
    required_severities = {"absent", "altered", "unsupported", "misplaced"}
    if any(
        str((item.get("applicability") or {}).get("rule")) not in allowed_triggers
        or set(item.get("severity") or {}) != required_severities
        or any(
            str((item.get("severity") or {}).get(key)) not in {"blocking", "warning"}
            for key in required_severities
        )
        or not isinstance(item.get("substitutions"), list)
        or not isinstance(item.get("repeatable"), bool)
        or not str((item.get("placement") or {}).get("section") or "").strip()
        or not isinstance((item.get("placement") or {}).get("order"), int)
        or not str(item.get("section_id") or "").strip()
        or not str(item.get("fidelity") or "").strip()
        or not isinstance(item.get("provenance"), Mapping)
        or not isinstance(item.get("expected_structure"), Mapping)
        or not isinstance(item.get("validation"), Mapping)
        for item in modules
    ):
        raise ValueError("Sterling ICF module contract contains an incomplete applicability, provenance, validation, placement, structure, substitution, repetition, fidelity, or severity rule.")
    return copy.deepcopy(dict(payload))


def sterling_clause_text(clause_id: str, repo_root: Path | None = None) -> str:
    """Return exact authorized boilerplate for a clause that has one."""
    root = (repo_root or Path(__file__).resolve().parents[1]).resolve()
    contract = sterling_clause_contract(root)
    clause = next(
        (item for item in contract["modules"] if item["module_id"] == clause_id),
        None,
    )
    if clause is None:
        raise KeyError(clause_id)
    source = clause.get("provenance") or {}
    boilerplate_id = source.get("boilerplate_id")
    if not boilerplate_id:
        exact_id = (clause.get("validation") or {}).get("exact_boilerplate_id")
        boilerplate_id = exact_id
    if not boilerplate_id:
        boilerplate_id = (clause.get("validation") or {}).get("placement_boilerplate_id")
    if not boilerplate_id:
        raise ValueError(f"Sterling clause has no one exact boilerplate text: {clause_id}")
    payload = json.loads((root / _BOILERPLATE_RESOURCE).read_text(encoding="utf-8"))
    text = (payload.get("sections") or {}).get(str(boilerplate_id))
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"Sterling clause boilerplate is unavailable: {clause_id}")
    return text


def facility_projection(facility: Mapping[str, Any]) -> dict[str, str]:
    """Project flat or nested facility aliases into one artifact-neutral model."""
    def text(value: Any) -> str:
        return "" if value is None else " ".join(str(value).split())

    address = facility.get("address")
    nested = address if isinstance(address, Mapping) else {}
    sources = (nested, facility)

    def first(*aliases: str) -> str:
        for source in sources:
            for alias in aliases:
                value = source.get(alias)
                if isinstance(value, (Mapping, list, tuple, set)):
                    continue
                if text(value):
                    return text(value)
        return ""

    def identity(value: str) -> str:
        return " ".join("".join(c.casefold() if c.isalnum() else " " for c in value).split())

    name = text(facility.get("name") or facility.get("facility_name"))
    city = first("city", "locality", "town")
    state = first("state", "region", "province")
    postal_code = first("zip", "postal_code", "postalCode", "postcode", "zip_code")
    country = first("country", "country_name")
    locality_parts = [city, state, postal_code, country]
    raw_segments: list[str] = []
    if nested:
        street_parts = [
            first("line1", "address_line1", "street", "address"),
            first("line2", "address_line2", "street2"),
        ]
    else:
        raw_segments = [part.strip() for part in re.split(r"[,;\n]", text(address)) if part.strip()]
        known_components = [name, *locality_parts]
        known_identities = {identity(part) for part in known_components if part}
        known_tokens = {token for part in known_components for token in identity(part).split()}
        street_parts = []
        for segment in raw_segments:
            marker = identity(segment)
            tokens = set(marker.split())
            if marker in known_identities or (tokens and known_tokens and tokens <= known_tokens):
                continue
            street_parts.append(segment)
    street = ", ".join(part for part in street_parts if part)
    seen = {identity(part) for part in re.split(r"[,;\n]", street) if part.strip()}
    locality = []
    for part in locality_parts:
        marker = identity(part)
        if part and marker not in seen:
            locality.append(part)
            seen.add(marker)
    locality_text = ", ".join(locality)
    display_locality = ", ".join(part for part in (city, state, country, postal_code) if part)
    display_address = ", ".join(filter(None, (street, display_locality)))
    if raw_segments:
        supplied_segments = list(raw_segments)
        if supplied_segments and identity(supplied_segments[0]) == identity(name):
            supplied_segments = supplied_segments[1:]
        supplied_tokens = set(identity(" ".join(supplied_segments)).split())
        required_tokens = {
            token
            for part in locality_parts
            if part
            for token in identity(part).split()
        }
        if supplied_segments and required_tokens and required_tokens <= supplied_tokens:
            display_address = ", ".join(supplied_segments)
    return {
        "name": name,
        "street": street,
        "city": city,
        "state": state,
        "postal_code": postal_code,
        "country": country,
        "locality": locality_text,
        "address": display_address,
    }


_UNRESOLVED_SOURCE_TEXT = {"tbd", "todo", "unknown", "not provided", "pending"}


def _valid_required_value(field: str, value: Any) -> bool:
    """Apply presence semantics for the required field, not generic truthiness."""
    if not meaningful(value) or isinstance(value, (bool, bytes)):
        return False
    if isinstance(value, str):
        text = value.strip()
        if text.casefold().rstrip(".:") in _UNRESOLVED_SOURCE_TEXT:
            return False
        if field == "risks_benefits.compensation_or_reimbursement":
            return bool(text)  # an explicit "None" is a complete source answer
        return bool(text)
    if field in {"population.inclusion_criteria", "population.exclusion_criteria"}:
        return isinstance(value, list) and bool(value) and all(
            isinstance(item, str) and _valid_required_value(field, item) for item in value
        )
    if field == "endpoints.primary":
        return isinstance(value, list) and bool(value)
    if isinstance(value, Mapping):
        return False
    return isinstance(value, (int, float, list, tuple))


def _canonicalize_declared_aliases(reference: dict[str, Any]) -> list[dict[str, Any]]:
    """Project declared intake aliases while retaining their exact provenance."""
    findings: list[dict[str, Any]] = []
    declared: dict[str, tuple[str, ...]] = {
        requirement.field: requirement.aliases
        for requirement in (*PROSPECTIVE_REQUIRED, *RETROSPECTIVE_REQUIRED)
        if requirement.aliases
    }
    provenance: dict[str, list[str]] = {}
    missing = object()
    for canonical, aliases in declared.items():
        canonical_value = get_path(reference, canonical, missing)
        supplied = [
            (path, get_path(reference, path, missing))
            for path in (canonical, *aliases)
            if get_path(reference, path, missing) is not missing
            and _valid_required_value(canonical, get_path(reference, path))
        ]
        if canonical == "procedures.assessments" and _valid_required_value(canonical, canonical_value):
            # A structured visit schedule may coexist with a higher-level
            # assessment list; it is a fallback source, not a competing scalar.
            continue
        signatures = {_candidate_signature(value) for _path, value in supplied}
        signatures.discard(None)
        if len(signatures) > 1:
            findings.append({
                "category": "source-evidence",
                "field": canonical,
                "issue": "Required Source Input has conflicting declared aliases.",
                "required": "Select one source-supported value.",
                "source_values": {path: copy.deepcopy(value) for path, value in supplied},
            })
            continue
        alias_values = [(path, value) for path, value in supplied if path != canonical]
        if (canonical_value is missing or not _valid_required_value(canonical, canonical_value)) and alias_values:
            set_path(reference, canonical, copy.deepcopy(alias_values[0][1]))
            provenance[canonical] = [path for path, _value in alias_values]
    if provenance:
        source = reference.setdefault("source", {})
        if not isinstance(source, dict):
            findings.append({"category": "technical", "field": "source", "issue": "Source metadata must be an object."})
        else:
            existing = source.get("alias_provenance")
            source["alias_provenance"] = {**(existing if isinstance(existing, dict) else {}), **provenance}
    return findings


def _ensure_administrative_identifier(reference: dict[str, Any]) -> None:
    """Close optional identifier gaps from stable source identity only."""
    protocol_number = get_path(reference, "meta.protocol_number")
    provider_id = get_path(reference, "regulatory.prs.provider_study_id")
    if meaningful(protocol_number) or meaningful(provider_id):
        identifier = str(protocol_number or provider_id).strip()
        if not meaningful(protocol_number):
            set_path(reference, "meta.protocol_number", identifier)
        if not meaningful(provider_id):
            set_path(reference, "regulatory.prs.provider_study_id", identifier)
        return
    identity = {
        "study_type": canonical_study_type(get_path(reference, "meta.study_type")),
        "title": get_path(reference, "study.title"),
        "sponsor": get_path(reference, "parties.sponsor.name"),
        "principal_investigator": get_path(reference, "parties.principal_investigator.name"),
    }
    digest = hashlib.sha256(json.dumps(
        identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str,
    ).encode("utf-8")).hexdigest()[:12].upper()
    identifier = f"ADM-{digest}"
    set_path(reference, "meta.protocol_number", identifier)
    set_path(reference, "regulatory.prs.provider_study_id", identifier)
    source = reference.setdefault("source", {})
    if isinstance(source, dict):
        source["administrative_identifier"] = {
            "authority": "deterministic_workflow",
            "value": identifier,
            "source_fields": sorted(identity),
        }


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


def normalize_visit_term(value: Any) -> str:
    """Normalize source visit labels/timing without changing their meaning."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = re.sub(
        r"\bPreoperative screening at the Preoperative time point\b",
        "Preoperative screening",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\bOne operative visit per eye\b",
        "One operative visit for each eye",
        text,
        flags=re.I,
    )
    return text


def normalized_visit_records(reference: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Combine the approved visit inventory and procedure relationships.

    The explicit schedule table owns row order; extra procedure-schedule visits
    follow it. Merge only unambiguous equal name/timing rows with compatible
    supplied IDs/fields. Never turn narrative assessments into numbered visits.
    """
    visits: list[dict[str, Any]] = []
    table_count = 0
    for path in ("procedures.visit_schedule_table", "procedures.visit_schedule"):
        raw = get_path(reference, path, [])
        source_rows = [row for row in raw if isinstance(row, Mapping)] if isinstance(raw, list) else []
        source_keys = [
            (normalize_visit_term(row.get("visit") or row.get("visitName")),
             normalize_visit_term(row.get("timing") or row.get("visitWindow")))
            for row in source_rows
        ]
        for row in source_rows:
            if not isinstance(row, Mapping) or not any(
                meaningful(row.get(key)) for key in ("visit", "visitName", "visitNumber", "timing", "visitWindow")
            ):
                continue
            record = copy.deepcopy(dict(row))
            record["visit"] = normalize_visit_term(row.get("visit") or row.get("visitName"))
            record["timing"] = normalize_visit_term(row.get("timing") or row.get("visitWindow"))
            raw_procedures = row.get("procedures", [])
            record["procedures"] = (
                [str(item).strip() for item in raw_procedures if meaningful(item)]
                if isinstance(raw_procedures, list) else
                [item.strip() for item in re.split(r"[;\n]", str(raw_procedures or "")) if item.strip()]
            )
            # Do not collapse separate rows within either approved source, or
            # guess that differently timed/named contacts are the same visit.
            matches = [candidate for candidate in visits[:table_count]
                       if record["visit"] and candidate["visit"] == record["visit"]
                       and candidate["timing"] == record["timing"]
                       and all(not meaningful(candidate.get(key)) or not meaningful(value)
                               or candidate[key] == value
                               for key, value in record.items()
                               if key not in {"procedures", "visitName", "visitWindow"})]
            # A unique table candidate is insufficient when multiple contacts
            # in the other source could match it. Retain ambiguous rows rather
            # than silently collapsing separate approved contacts.
            source_key = (record["visit"], record["timing"])
            if len(matches) == 1 and source_keys.count(source_key) == 1:
                candidate = matches[0]
                for key, value in record.items():
                    if not meaningful(candidate.get(key)):
                        candidate[key] = value
                candidate["procedures"] = list(dict.fromkeys(candidate["procedures"] + record["procedures"]))
            else:
                visits.append(record)
        if path.endswith("visit_schedule_table"):
            table_count = len(visits)
    used_numbers = {str(row["visitNumber"]) for row in visits if meaningful(row.get("visitNumber"))}
    for index, record in enumerate(visits, 1):
        if not meaningful(record.get("visitNumber")):
            while str(index) in used_numbers:
                index += 1
            record["visitNumber"] = str(index)
            used_numbers.add(str(index))
        if not record["visit"]:
            record["visit"] = f"Visit {record['visitNumber']}"
    return visits


def protocol_table_contracts(reference: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Return typed, source-derived Protocol table matrices for rendering and QA."""
    visits = normalized_visit_records(reference)
    assessment_rows: list[list[str]] = []
    if visits:
        normalized_visits = [{**visit, "name": visit["visit"]} for visit in visits]
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
                ["Activity", *[f"Visit {visit['visitNumber']}" for visit in normalized_visits]],
                *[
                    [activity, *["X" if activity in visit["procedures"] else "" for visit in normalized_visits]]
                    for activity in activities
                ],
            ]
    if not assessment_rows:
        # No procedure assignments does not make an approved contact disappear.
        # Both matrix and inventory forms use the same normalized visit set.
        entries = [[visit["visit"], visit["timing"]] for visit in visits]
        if entries:
            assessment_rows = [["Approved visit or assessment", "Approved timing"], *entries]
    # A structured matrix must not suppress supplied narrative assessments.
    # Preserve source clauses verbatim; no NLP guess assigns them to visits.
    inventory: list[dict[str, Any]] = []
    supplemental_notes: list[str] = []

    def inventory_items(value: Any, path: str) -> None:
        if isinstance(value, Mapping):
            inventory.append({"record": copy.deepcopy(dict(value)), "source_path": path})
        elif isinstance(value, list):
            for index, child in enumerate(value):
                inventory_items(child, f"{path}.{index}")
        elif meaningful(value):
            # An exact duplicate of the explicitly owned completion rule is not
            # an assessment. Its source remains untouched for Section 18.
            if value != get_path(reference, "procedures.completion"):
                inventory.append({"activity": str(value), "source_path": path})

    for path in ("procedures.assessments", "procedures.evaluation"):
        inventory_items(get_path(reference, path), path)
    matrix = bool(assessment_rows and assessment_rows[0][0] == "Activity")
    represented = {re.sub(r"\s+", " ", row[0]).strip().casefold().rstrip(".") for row in assessment_rows}
    represented.update(visit["visit"].casefold() for visit in visits)
    unallocated = []
    for item in inventory:
        if "record" in item:
            unallocated.append(item)
            supplemental_notes.append("; ".join(
                f"{key}: {json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value}"
                for key, value in item["record"].items()))
            continue
        key = re.sub(r"\s+", " ", item["activity"]).strip().casefold().rstrip(".")
        if key in represented:
            continue
        represented.add(key)
        unallocated.append(item)
        supplemental_notes.append(item["activity"])

    # Only an explicit positive each-contact relationship authorizes X marks.
    # Historical abstraction and pre-consent contacts are not research AE visits.
    safety_inventory: list[dict[str, str]] = []
    for path in ("safety.monitoring", "safety.adverse_events"):
        value = get_path(reference, path)
        leaves = []
        def safety_leaves(value: Any) -> None:
            if isinstance(value, Mapping):
                for child in value.values(): safety_leaves(child)
            elif isinstance(value, list):
                for child in value: safety_leaves(child)
            elif meaningful(value): leaves.append(str(value))
        safety_leaves(value)
        for leaf in leaves:
            if leaf not in supplemental_notes:
                supplemental_notes.append(leaf)
            for clause in re.split(r"[;!?]\s*|\.(?!\d)\s*|,\s*|\b(?:while|whereas|but|and)\b", leaf, flags=re.I):
                # Contrasts/restrictions are not positive each-contact evidence.
                # Leave them intact as notes rather than guessing their scope.
                if (re.search(r"\b(?:adverse events?|AEs?)\b", clause, re.I)
                        and re.search(r"\b(?:each|every)\s+(?:study\s+)?contact\b", clause, re.I)
                        and not re.search(r"\b(?:not|no|never|without|only|rather\s+than|instead\s+of)\b", clause, re.I)):
                    safety_inventory.append({"activity": clause, "source_path": path})
    if safety_inventory:
        safety_label = "Adverse event review at each contact (study-specific review after consent)"
        if matrix and canonical_study_type(get_path(reference, "meta.study_type")) in {"Prospective", "Ambispective"}:
            contacts = [not re.search(r"historical|abstraction|record review|chart review|pre[- ]consent|before consent", visit["visit"] + " " + visit["timing"], re.I) for visit in visits]
            assessment_rows.append([safety_label, *["X" if contact else "" for contact in contacts]])

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
            "supplemental_notes": supplemental_notes,
            "assessment_inventory": inventory,
            "unallocated_assessments": unallocated,
            "each_contact_safety_evidence": safety_inventory,
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
        if _valid_required_value(requirement.field, value):
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


def timeline_findings(reference: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Report source contradictions using comparable anchors, never repair source.

    Enrollment is a recruitment horizon, not a participant follow-up duration.
    An explicit baseline-relative duration is compared with a baseline-relative
    scheduled final contact, or the difference of points on one schedule origin.
    """
    timeline = get_path(reference, "study.timeline")
    text = str(timeline or "")
    relative_pattern = re.compile(r"\b((?:\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s*[- ]?\s*(?:days?|weeks?|months?))\s+(?:after|from|following)\s+(?:the\s+)?baseline\b", re.I)
    visits = normalized_visit_records(reference)
    relatives = []
    for clause in re.split(r"[;!?]\s*|\.(?!\d)\s*", text):
        previous_end = 0
        for match in relative_pattern.finditer(clause):
            # A directly trailing parenthetical labels this duration, not the
            # next one. Consume it so compound schedules cannot inherit it.
            trailing = re.match(r"\s*\([^()]*\)", clause[match.end():])
            event_phrase = clause[previous_end:match.start()]
            if trailing:
                event_phrase += trailing.group(0)
            relatives.append((event_phrase, match))
            previous_end = match.end() + (trailing.end() if trailing else 0)
    for event_phrase, relative in relatives:
        stated = _duration_days(relative.group(1))
        points = []
        for visit in visits:
            timing = visit["timing"] or visit["visit"]
            point = re.search(r"\b(?:day|week|month)\s+(\d+(?:\.\d+)?)\b", timing, re.I)
            if not point:
                continue
            days = _duration_days(point.group(0))
            explicit_origin = re.search(r"\b(?:after|from|following)\s+(.+)", timing, re.I)
            anchor = ("postoperative" if re.search(r"post[- ]?operativ|post[- ]?op|(?:after|from|following) surgery", timing, re.I)
                      else re.sub(r"\s+", " ", explicit_origin.group(1)).strip().casefold().rstrip(".") if explicit_origin
                      else "schedule")
            points.append((visit, days, anchor))
        events = re.findall(r"\b(interim|final)\b", event_phrase, re.I)
        # Optional visit lists need not include the named endpoint. Multiple
        # event names or scheduled matches leave the relationship ambiguous.
        if len(events) > 1:
            continue
        event_name = events[0] if events else (
            "final" if re.search(r"follow[- ]?up|followed|participa(?:nt|tion)", event_phrase, re.I) else None)
        targets = [point for point in points if event_name and re.search(
            rf"\b{event_name}\b", point[0]["visit"], re.I)]
        if len(targets) != 1:
            continue
        baselines = [(days, anchor) for visit, days, anchor in points if re.search(r"\bbaseline\b", visit["visit"], re.I)]
        durations = [days for visit, days, anchor in targets if anchor == "baseline" and not re.search(r"\bbaseline\b", visit["visit"], re.I)]
        for baseline, origin in baselines:
            durations.extend(days - baseline for visit, days, anchor in targets
                             if anchor == origin and days >= baseline and not re.search(r"\bbaseline\b", visit["visit"], re.I))
        # An unanchored final point beside an explicitly anchored baseline is
        # not comparable. A conditional subtraction is not a source conflict
        # and must not turn an unspecified origin into an obligatory input.
        # Preserve both supplied values; compare only established durations.
        if durations and stated is not None:
            scheduled = max(durations)
            tolerance = max(1.0, stated * 0.02)
            if abs(stated - scheduled) > tolerance:
                return [{"category": "source-evidence", "field": "study.timeline",
                         "issue": f"The baseline-relative timeline ({relative.group(0)}) conflicts with the nominal scheduled interval of {scheduled / 7:g} weeks after baseline.",
                         "required": "Reconcile the conflicting approved temporal anchors; do not silently rewrite either source statement.",
                         "source_values": {"study.timeline": copy.deepcopy(timeline),
                                           "procedures.visit_schedule": copy.deepcopy(get_path(reference, "procedures.visit_schedule")),
                                           "procedures.visit_schedule_table": copy.deepcopy(get_path(reference, "procedures.visit_schedule_table"))}}]
    if relatives:
        return []
    participant_clauses = [clause for clause in re.split(r"[;.!?]|,(?=\s*(?:follow|participant|final))", text, flags=re.I)
                           if not re.search(r"\benroll(?:ment|ing)?\b|\brecruit(?:ment|ing)?\b", clause, re.I)]
    timeline_days = _duration_days("; ".join(participant_clauses))
    scheduled_days = _scheduled_duration_days(reference)
    tolerance = max(1.0, timeline_days * 0.02) if timeline_days is not None else 0.0
    if timeline_days is not None and scheduled_days is not None and scheduled_days > timeline_days + tolerance:
        return [{"category": "source-evidence", "field": "study.timeline", "issue": "The approved visit/outcome schedule extends beyond the stated study timeline.", "required": "A timeline at least as long as the latest approved visit or outcome time point.", "source_values": {"study.timeline": copy.deepcopy(timeline)}}]
    return []


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
        if not _valid_required_value(requirement.field, required_input_value(reference, requirement)):
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
    for path in ("procedures.visit_schedule", "procedures.visit_schedule_table"):
        raw_visits = get_path(reference, path, [])
        seen_ids: set[str] = set()
        for index, visit in enumerate(raw_visits if isinstance(raw_visits, list) else []):
            if not isinstance(visit, Mapping) or not meaningful(visit.get("visitNumber")):
                continue
            identifier = str(visit["visitNumber"])
            if identifier in seen_ids:
                findings.append({"category": "source-evidence", "field": f"{path}.{index}.visitNumber",
                                 "issue": f"Duplicate supplied visitNumber: {identifier}.",
                                 "required": "Reconcile duplicate approved visit identifiers; do not silently renumber.",
                                 "source_values": {path: copy.deepcopy(raw_visits)}})
            seen_ids.add(identifier)
    findings.extend(timeline_findings(reference))
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
    alias_findings = _canonicalize_declared_aliases(normalized)
    branch = canonical_study_type(get_path(normalized, "meta.study_type"))
    if branch:
        normalized.setdefault("meta", {})["study_type"] = branch
        normalized["meta"]["document_set"] = [name.replace(".docx", "_docx").replace("study.xml", "xml") for name in DOCUMENT_SETS[branch]]
    if branch in {"Prospective", "Ambispective"}:
        _ensure_administrative_identifier(normalized)
    raw_prs_study_type = get_path(normalized, "regulatory.prs.study_type")
    if derive_prs_study_type and branch != "Retrospective" and not meaningful(raw_prs_study_type):
        if prs_study_type := _prs_study_type_from_design(normalized):
            set_path(normalized, "regulatory.prs.study_type", prs_study_type)
    findings = [*alias_findings, *input_findings(normalized)]
    if require_approval:
        if str(get_path(normalized, "approval.status", "")).casefold() != "approved":
            findings.append({"category": "approval", "field": "approval.status", "issue": "The current Source-of-Truth Markdown has not been explicitly approved.", "required": "Explicit approval of the current file."})
        review_file = get_path(normalized, "approval.review_file")
        if not review_file or (run_dir is not None and not (run_dir / str(review_file)).is_file()):
            findings.append({"category": "approval", "field": "approval.review_file", "issue": "The approved Source-of-Truth Markdown file is unavailable.", "required": "An existing reviewer-facing Markdown file."})
    source_gap_issues = {
        "Required Source Input is missing.",
        "Required Source Input has conflicting source candidates.",
        "Required Source Input has conflicting declared aliases.",
    }
    source_gaps = [
        finding for finding in findings
        if finding.get("category") != "approval"
        and (
            finding.get("issue") in source_gap_issues
            or finding.get("field") == "meta.icf_template"
            and "unresolved" in str(finding.get("issue", "")).casefold()
        )
    ]
    technical_findings = [
        finding for finding in findings
        if finding.get("category") != "approval" and finding not in source_gaps
    ]
    return {
        "status": "passed" if not findings else "blocked",
        "study_type": branch,
        "blocking_findings": findings,
        "source_gaps": source_gaps,
        "technical_findings": technical_findings,
        "normalized_reference": normalized,
    }


def evidence_available(reference: Mapping[str, Any], paths: Iterable[str]) -> list[str]:
    return [path for path in paths if meaningful(get_path(reference, path))]


def source_evidence_coverage_map(reference: Mapping[str, Any]) -> dict[str, Any]:
    """Build the deterministic map from approved facts to required artifacts.

    The map is deliberately derived from the Document Section Contracts rather
    than from drafted prose.  That makes it useful before drafting and keeps a
    later model response from changing which artifact owns a required fact.
    Empty optional fields are retained as contract destinations, while the
    ``approved`` flag tells callers whether there is an approved value to
    preserve for this particular run.
    """
    branch = canonical_study_type(get_path(reference, "meta.study_type")) or ""
    icf_template = str(get_path(reference, "meta.icf_template", "Advarra"))
    destinations: dict[str, list[dict[str, Any]]] = {}

    def add_sections(artifact: str, sections: Iterable[SectionSpec]) -> None:
        for section in sections:
            if not section_applies(reference, section):
                continue
            for source_path in section.evidence:
                destinations.setdefault(source_path, []).append({
                    "artifact": artifact,
                    "section_id": section.section_id,
                    "required": section.required,
                    "approved": meaningful(get_path(reference, source_path)),
                })

    add_sections("protocol.docx", protocol_contract(branch))
    if branch in {"Prospective", "Ambispective"}:
        add_sections("icf.docx", icf_contract(branch, icf_template))
        # PRS structured fields are deterministic destinations even when the
        # narrative wording is supplied by a drafting request.
        for source_path in (
            "meta.study_title", "meta.protocol_number", "population.study_population",
            "population.inclusion_criteria", "population.exclusion_criteria",
            "endpoints.primary", "endpoints.secondary", "endpoints.other",
            "procedures.assessments", "procedures.visit_schedule",
            "design.study_design", "risks_benefits.risks",
        ):
            if meaningful(get_path(reference, source_path)):
                destinations.setdefault(source_path, []).append({
                    "artifact": "study.xml",
                    "section_id": "prs.structured",
                    "required": True,
                    "approved": True,
                })

    entries = [
        {
            "source_path": source_path,
            "approved_value_sha256": hashlib.sha256(
                json.dumps(get_path(reference, source_path), sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest(),
            "destinations": sorted(items, key=lambda item: (item["artifact"], item["section_id"])),
        }
        for source_path, items in sorted(destinations.items())
    ]
    return {
        "schema_version": "source-evidence-coverage-map/v1",
        "study_type": branch,
        "icf_template": icf_template if branch in {"Prospective", "Ambispective"} else None,
        "entries": entries,
    }


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
    sterling_clauses = (
        resource(STERLING_CLAUSE_CONTRACT_RESOURCE)
        if icf_family == "Sterling"
        else None
    )
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
    if sterling_clauses is not None and sterling_clauses["sha256"]:
        try:
            sterling_clause_contract(root)
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            problems.append(f"Sterling Clause Contract is unreadable: {exc}")

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
        "sterling_clause_contract": sterling_clauses,
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
    "APPROVED_FONT_PLAN_VERSION", "APPROVED_PACKAGED_FONT_FALLBACKS", "BOILERPLATE_VERSION", "BUNDLED_FONT_FILES", "STERLING_CLAUSE_CONTRACT_VERSION", "STERLING_CLAUSE_CONTRACT_RESOURCE",
    "CONTRACT_VERSION", "CONTRACTED_TEMPLATE_BUNDLE_SCHEMA", "DOCUMENT_SETS", "FORBIDDEN_DRAFT_LANGUAGE", "LAYOUT_FAMILY_ARTIFACTS", "LAYOUT_REPAIR_RULES", "PACKAGED_FONT_ASSETS", "RECOVERY_POLICIES", "SAFETY_ROLE_RESPONSIBILITY_CONCEPTS", "VISUAL_CHECK_DISPOSITIONS",
    "BatchSpec", "ContractedTemplateBundleError", "ICF_RETAINED_SHELL_SECTIONS", "ICF_STUDY_SECTIONS", "PROTOCOL_1_TO_19", "RETROSPECTIVE_1_TO_13", "SectionSpec",
    "batch_plan", "canonical_study_type", "contract_hash", "contract_payload", "contracted_template_bundle", "document_set",
    "evidence_available", "facility_projection", "get_path", "icf_summary_obligations", "input_findings", "meaningful", "parse_source_truth", "protocol_concept_ownership", "source_evidence_coverage_map",
    "icf_contract", "icf_retained_sections", "protocol_contract", "protocol_table_contracts", "recovery_finding", "repair_report", "section_applies", "set_path", "source_contract", "source_truth_markdown", "sterling_clause_contract", "sterling_clause_text",
]
