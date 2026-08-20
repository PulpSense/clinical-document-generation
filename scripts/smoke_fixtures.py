"""Approved structured study references used by the branch acceptance tests.

Every fixture represents the state the workflow reaches *after* the reviewer has
approved Source-of-Truth Markdown: the starred source inputs are complete, the
generated narrative modules are populated, and `approval.status` is `approved`.
The branch generation seam starts here.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BUNDLED_DOCX = REPO_ROOT / "assets" / "client-templates" / "docx"
BUNDLED_PRS = (
    REPO_ROOT
    / "assets"
    / "client-templates"
    / "prs"
    / "clinicaltrials_prs_full_placeholder_template.xml"
)


def _address(city: str = "Boston") -> dict:
    return {
        "line1": "100 Research Way",
        "city": city,
        "state": "MA",
        "postal_code": "02115",
        "country": "United States",
    }


def _shared_source_facts() -> dict:
    """Starred source inputs shared by every branch contract."""
    return {
        "study": {
            "title": "A Study of Agent QX in Adults With Chronic Condition Y",
            "short_title": "QX-CCY",
            "condition": "Chronic Condition Y",
            "background": "Chronic Condition Y affects a large adult population and current care is limited.",
            "unmet_need": "No approved therapy addresses the residual symptom burden.",
            "hypothesis": "Agent QX reduces the symptom score compared with standard care.",
            "timeline": "12 months",
        },
        "objectives": {
            "primary": "Evaluate the effect of Agent QX on the symptom score at 12 weeks.",
            "secondary": "Characterise the safety profile of Agent QX.",
        },
        "design": {
            "study_design": "Randomised, parallel-group, open-label study",
            "number_of_sites": 1,
            "intervention_name": "Agent QX",
            "intervention_type": "Drug",
            "study_arm": "Two arm",
            "test_articles": ["Agent QX"],
        },
        "endpoints": {
            "primary": [
                {
                    "measure": "Change in symptom score",
                    "time_frame": "Baseline to week 12",
                    "description": "Mean change in the validated symptom score.",
                }
            ],
            "secondary": [
                {
                    "measure": "Incidence of treatment-emergent adverse events",
                    "time_frame": "Baseline to week 52",
                    "description": "Safety and tolerability of Agent QX.",
                }
            ],
        },
        "population": {
            "inclusion_criteria": [
                "Adults aged 18 years or older",
                "Documented diagnosis of Chronic Condition Y",
            ],
            "exclusion_criteria": [
                "Participation in another interventional study within 30 days",
                "Any condition that would compromise participant safety",
            ],
            "sample_size": 120,
            "sample_justification": "120 participants provide 90% power to detect the target effect size.",
        },
        "statistics": {
            "analysis_plan": "Primary analysis uses an ANCOVA model adjusted for baseline score.",
            "methodology": "Analyses are performed with a two-sided alpha of 0.05.",
            "software": "All analyses are produced in a validated statistical environment.",
        },
        "procedures": {
            "assessments": "Symptom score, vital signs, and laboratory panel at each visit.",
            "assessment_details": "Assessments follow the schedule defined in the visit table.",
            "minimum_days_before_screening_without_participation": 30,
        },
        "risks_benefits": {
            "risks": "Risks include injection-site reaction and transient headache.",
            "benefits": "Participants may experience a reduction in symptom burden.",
            "compensation_or_reimbursement": "Participants receive travel reimbursement per visit.",
        },
        "parties": {
            "principal_investigator": {
                "name": "Dr Alex Rivera",
                "title": "MD",
                "email": "alex.rivera@example.org",
            },
            "sub_investigator": {"name": "Dr Sam Okafor"},
            "sponsor": {"name": "Northwind Therapeutics", "address": _address()},
            "funding_source": {"name": "Northwind Therapeutics", "address": _address()},
            "irb": {
                "name": "Advarra IRB",
                "affiliation": "Independent central institutional review board",
                "address": "6100 Merriweather Drive, Columbia, MD 21044",
                "phone": "+1-555-0100",
                "email": "irb@example.org",
            },
            "study_coordinator": {
                "name": "Jordan Lee",
                "title": "RN, CCRC",
                "business_phone": "+1-555-0111",
                "office_phone": "+1-555-0112",
                "email": "jordan.lee@example.org",
            },
        },
        "sites": [
            {
                "facility": {
                    "name": "Northwind Clinical Research Center",
                    "address": _address(),
                },
                "contact": {
                    "name": "Jordan Lee",
                    "title": "RN, CCRC",
                    "phone": "+1-555-0111",
                    "email": "jordan.lee@example.org",
                },
                "investigator": {
                    "name": "Dr Alex Rivera",
                    "title": "MD",
                    "role": "Principal Investigator",
                },
            }
        ],
        "regulatory": {
            "jurisdiction": "United States",
            "xml_profile": "clinicaltrials-prs",
            "prs": {
                "provider_study_id": "NWT-QX-001",
                "provider_name": "Northwind Therapeutics",
                "org_name": "Northwind Therapeutics",
                "overall_status": "Recruiting",
                "irb_approval_status": "Approved",
                "study_uid": "U0000-QX-0001",
                "responsible_party_type": "Sponsor",
                "lead_sponsor_agency": "Northwind Therapeutics",
            },
        },
    }


def _retrospective_generated() -> dict:
    return {
        "protocol": {
            "shortTitle": "QX-CCY",
            "introduction": "This retrospective chart review examines outcomes in adults with Chronic Condition Y.",
            "objectivesIntro": "The objectives of this retrospective review are described below.",
            "primaryOutcomes": ["Change in symptom score abstracted from the medical record"],
            "secondaryOutcomes": ["Rate of documented treatment-emergent adverse events"],
            "exploratoryOutcomes": ["Association between baseline severity and outcome"],
            "populationLong": "Adults aged 18 years or older treated at the participating facility.",
            "inclusionCriteria": [
                "Adults aged 18 years or older",
                "Documented diagnosis of Chronic Condition Y",
            ],
            "exclusionCriteria": [
                "Incomplete medical record for the review period",
                "Any condition that would compromise data quality",
            ],
            "studyDesignLong": "Single-centre retrospective observational chart review.",
            "methods": "Investigators abstract structured data from the electronic medical record.",
            "studyProcedure": "Records are identified, abstracted, and quality-checked by two reviewers.",
            "studyProcedureBullets": ["Identify eligible records", "Abstract structured data"],
            "analysisDataSets": "The analysis set includes all records meeting the eligibility criteria.",
            "analysisDataSetsBullets": ["Full analysis set", "Safety analysis set"],
            "statisticalMethodology": "Descriptive statistics summarise the abstracted outcomes.",
            "statisticalConsiderations": "No interim analysis is planned for this retrospective review.",
            "sampleSizeJustification": "All eligible records in the review window are included.",
        }
    }


def _prospective_generated(visit_count: int = 7) -> dict:
    visits = []
    for index in range(1, visit_count + 1):
        if index == 1:
            name, window = "Screening", "Day -28 to Day -1"
        elif index == visit_count:
            name, window = "End of Study", "Week 52 (+/- 7 days)"
        else:
            name, window = f"Treatment Visit {index - 1}", f"Week {(index - 1) * 8} (+/- 5 days)"
        visits.append(
            {
                "visitNumber": str(index),
                "visitName": name,
                "visitWindow": window,
                "CRFnumber": f"CRF-{index:02d}",
            }
        )
    return {
        "protocol": {
            "shortTitle": "QX-CCY",
            "introduction": "This prospective study evaluates Agent QX in adults with Chronic Condition Y.",
            "populationShort": "Adults with Chronic Condition Y",
            "populationLong": "Adults aged 18 years or older with a documented diagnosis of Chronic Condition Y.",
            "inclusionCriteria": [
                "Adults aged 18 years or older",
                "Documented diagnosis of Chronic Condition Y",
            ],
            "exclusionCriteria": [
                "Participation in another interventional study within 30 days",
                "Any condition that would compromise participant safety",
            ],
            "studyDesignLong": "Randomised, parallel-group, open-label, multicentre study.",
            "masked": "Open label; no masking is applied.",
            "variables": "Symptom score, adverse events, and laboratory values.",
            "duration": "Each participant is followed for 52 weeks.",
            "methods": "Participants are randomised and treated according to the visit schedule.",
            "visitSchedule": "Participants attend scheduled visits from screening through end of study.",
            "visitScheduleTable": visits,
            "visitScheduleDetails": "Visit windows are calculated from the randomisation date.",
            "measurements": "Symptom score, vital signs, and laboratory panel.",
            "measurementsDetails": "Assessments are collected at each scheduled visit.",
            "analysisDataSets": "The full analysis set includes all randomised participants.",
            "statisticalMethodology": "ANCOVA adjusted for baseline symptom score.",
            "statisticalConsiderations": "A two-sided alpha of 0.05 is applied throughout.",
            "sampleSizeJustification": "120 participants provide 90% power for the primary endpoint.",
            "risks": "Risks include injection-site reaction and transient headache.",
            "benefits": "Participants may experience a reduction in symptom burden.",
            "studyArm": "Two arm",
        },
        "icf": {
            "icfVisitOverview": (
                "If you join this study you will come to the clinic for seven visits over about 12 months. "
                "The first visit checks whether you can take part and the last visit completes your participation."
            ),
            "icfVisitDetails": (
                "At each visit the study team will ask about your symptoms, check your vital signs, "
                "and collect a small blood sample. Most visits last about one hour."
            ),
            "icfStudyLenght&Participants": (
                "About 120 people will take part in this study, and your participation will last about 12 months."
            ),
            "icfPurpose": "The purpose of this study is to find out whether Agent QX reduces symptoms of Chronic Condition Y.",
            "interventionPossibleSideEffects": "You may have soreness where the study drug is given, or a headache.",
            "benefits": "You may or may not benefit from taking part in this study.",
            "payment": "You will be reimbursed for travel costs for each visit you attend.",
            "alternatives": "You may choose not to take part and continue your usual care.",
            "costs": "There is no cost to you for the study drug or study visits.",
            "injuryCompensation": "Contact the study doctor immediately if you are injured during the study.",
            "privacy": "Your health information will be kept private and shared only as described here.",
            "authorizationDuration": "Your permission to use this information does not expire unless you cancel it.",
        },
    }


def _ambispective_generated() -> dict:
    generated = deepcopy(_prospective_generated())
    protocol = generated["protocol"]
    protocol["introduction"] = (
        "This ambispective study combines a retrospective review of historical medical records "
        "with a prospective follow-up phase in adults with Chronic Condition Y."
    )
    protocol["studyDesignLong"] = (
        "Ambispective design. The historical data collection phase abstracts records from the "
        "preceding 24 months. The prospective phase enrolls participants for scheduled study visits."
    )
    protocol["methods"] = (
        "Historical data are abstracted from the electronic medical record for the retrospective "
        "period. Prospective visits, procedures, and follow-up are performed according to the visit schedule."
    )
    protocol["measurements"] = (
        "Historical measurements are abstracted from the medical record. Prospective measurements "
        "are collected at each scheduled study visit."
    )
    protocol["variables"] = (
        "Historically collected symptom scores and prospectively collected symptom scores, "
        "adverse events, and laboratory values."
    )
    return generated


def _ambispective_endpoints() -> dict:
    return {
        "primary": [
            {
                "measure": "Change in symptom score",
                "time_frame": "Historical baseline to prospective week 12",
                "description": (
                    "Baseline values are collected historically from the medical record; "
                    "follow-up values are collected prospectively at study visits."
                ),
            }
        ],
        "secondary": [
            {
                "measure": "Incidence of treatment-emergent adverse events",
                "time_frame": "Prospective follow-up through week 52",
                "description": "Adverse events are collected prospectively during the follow-up phase.",
            }
        ],
    }


def generated_modules(branch: str, *, visit_count: int = 7) -> dict:
    """The narrative modules Hermes writes from approved facts.

    Parsing approved Source-of-Truth Markdown deliberately clears `generated`,
    because draft prose must be rewritten from the facts the reviewer approved.
    Tests that walk the review loop use this to replay that step.
    """
    normalized = branch.strip().lower()
    if normalized == "retrospective":
        return _retrospective_generated()
    if normalized == "prospective":
        return _prospective_generated(visit_count)
    if normalized == "ambispective":
        return _ambispective_generated()
    raise ValueError(f"Unknown branch: {branch}")


def approved_reference(branch: str, *, visit_count: int = 7) -> dict:
    """Return an approved structured study reference for `branch`."""
    normalized = branch.strip().lower()
    reference: dict[str, Any] = {
        "meta": {
            "created_at": "2026-01-05T09:00:00+00:00",
            "protocol_number": "NWT-QX-001",
            "version": "1.0",
            "date": "05 Jan 2026",
            "study_type": None,
            "document_set": [],
            "icf_template": None,
        },
        "source": {
            "channel": "fixture",
            "raw_files": ["input/raw_context.md"],
            "transcript_files": [],
            "notes": None,
            "field_candidates": {},
            "source_of_truth_file": "reference/source-of-truth.md",
            "source_of_truth_md": "reference/source-of-truth.md",
            "source_of_truth_status": "uploaded_reviewed",
        },
        "template_fields": {},
        "approval": {
            "status": "approved",
            "review_file": "reference/source-of-truth.md",
            "approved_by": "reviewer",
            "approved_at": "2026-01-06T10:00:00+00:00",
            "notes": None,
        },
        "needs_review": [],
    }
    reference.update(deepcopy(_shared_source_facts()))

    if normalized == "retrospective":
        reference["meta"]["study_type"] = "Retrospective"
        reference["meta"]["document_set"] = ["protocol_docx"]
        reference["generated"] = _retrospective_generated()
        reference["regulatory"] = {"jurisdiction": "United States", "xml_profile": None}
        reference["references"] = [
            "Smith J, et al. Outcomes in Chronic Condition Y. J Example Med. 2024."
        ]
    elif normalized == "prospective":
        reference["meta"]["study_type"] = "Prospective"
        reference["meta"]["document_set"] = ["protocol_docx", "icf_docx", "xml"]
        reference["meta"]["icf_template"] = "advarra"
        reference["generated"] = _prospective_generated(visit_count)
    elif normalized == "ambispective":
        reference["meta"]["study_type"] = "Ambispective"
        reference["meta"]["document_set"] = ["protocol_docx", "icf_docx", "xml"]
        reference["meta"]["icf_template"] = "advarra"
        reference["generated"] = _ambispective_generated()
        reference["endpoints"] = _ambispective_endpoints()
    else:
        raise ValueError(f"Unknown branch: {branch}")

    return reference


BRANCH_TEMPLATES = {
    "Retrospective": {"protocol.template.docx": "retrospective-protocol.template.docx"},
    "Prospective": {
        "protocol.template.docx": "prospective-protocol.template.docx",
        "icf.template.docx": "prospective-icf.template.docx",
    },
    "Ambispective": {
        "protocol.template.docx": "ambispective-protocol.template.docx",
        "icf.template.docx": "ambispective-icf.template.docx",
    },
}


def build_run(run_dir: Path, branch: str, *, visit_count: int = 7) -> dict:
    """Materialise an approved run directory for `branch` and return its reference."""
    reference = approved_reference(branch, visit_count=visit_count)
    canonical = reference["meta"]["study_type"]

    for rel in ("input", "reference", "templates", "output", "logs"):
        (run_dir / rel).mkdir(parents=True, exist_ok=True)

    for dest_name, asset_name in BRANCH_TEMPLATES[canonical].items():
        (run_dir / "templates" / dest_name).write_bytes(
            (BUNDLED_DOCX / asset_name).read_bytes()
        )
    if "xml" in reference["meta"]["document_set"]:
        (run_dir / "templates" / "study.template.xml").write_bytes(BUNDLED_PRS.read_bytes())

    write_reference(run_dir, reference)
    return reference


def write_reference(run_dir: Path, reference: dict) -> Path:
    path = run_dir / "reference" / "study.reference.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(reference, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path
