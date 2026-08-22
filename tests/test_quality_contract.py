from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from quality_contract import (  # noqa: E402
    repair_report_markdown,
    validate_data_driven_tables,
    validate_source_contract,
)
from complete_protocol import operational_detail_missing  # noqa: E402
from render_templates import normalize_title_page_fields  # noqa: E402
from build_n8n_prospective_fields import visit_schedule_table  # noqa: E402
from build_prs_xml_fields import infer_masking  # noqa: E402
from protocol_document import build_protocol_model  # noqa: E402
from delivery_pipeline import run_delivery_pipeline  # noqa: E402
from readiness_contract import readiness_report  # noqa: E402


class QualityContractTests(unittest.TestCase):
    def complete_reference(self, study_type: str = "Prospective") -> dict:
        return {
            "meta": {
                "study_type": study_type,
                "document_set": ["protocol_docx", "icf_docx", "xml"] if study_type != "Retrospective" else ["protocol_docx"],
                "protocol_number": "P-001",
                "version": "1.0",
                "date": "21 Aug 2026",
                "icf_template": "Advarra" if study_type != "Retrospective" else None,
            },
            "approval": {"status": "approved", "approved_by": "Reviewer"},
            "source": {"source_of_truth_file": "reference/source.md", "field_candidates": {}},
            "study": {"title": "Source Grounded Study", "timeline": "3 months"},
            "population": {
                "study_population": "Adults with the target condition.",
                "sample_size": "40 participants",
                "sample_justification": "Descriptive estimates with expected attrition.",
                "minimum_age": "18 Years",
                "maximum_age": "80 Years",
                "inclusion_criteria": ["Adults with the target condition."],
                "exclusion_criteria": ["Unable to complete follow-up."],
            },
            "parties": {
                "sponsor": {"name": "Sponsor", "address": "1 Main Street"},
                "principal_investigator": {"name": "A. Investigator", "title": "MD"},
                "sub_investigators": "None",
            },
            "sites": [{"facility": {"name": "Site One"}}],
            "design": {
                "study_design": "Prospective observational study.",
                "number_of_sites": 1,
                "masking": "None",
                "arms": [{"name": "Study arm", "qualification": "Eligible adults."}],
            },
            "endpoints": {
                "primary": [{"label": "Primary outcome", "time_point": "Month 3"}],
                "secondary": [{"label": "Safety outcome", "time_point": "Month 3"}],
            },
            "procedures": {
                "assessments": "Baseline and Month 3 assessments.",
                "retention": "Reminder calls support follow-up.",
                "discontinuation": "Participants may withdraw at any time.",
                "replacement": "No replacement after enrollment.",
                "visit_schedule_table": [
                    {"visitNumber": "1", "visitName": "Baseline", "visitWindow": "Day 0", "CRFnumber": "BL"},
                    {"visitNumber": "2", "visitName": "Month 3", "visitWindow": "Day 90 +/- 7", "CRFnumber": "M3"},
                ],
            },
            "safety": {"roles": "The investigator assesses and reports safety events."},
            "risks_benefits": {
                "compensation_or_reimbursement": "Participants receive approved reimbursement.",
                "injury_handling": "Study-related injury receives appropriate care.",
                "privacy": "Participant information is handled under the approved privacy procedures.",
            },
            "template_fields": {
                "data_driven_tables": {
                    "sample_size_evidence": {
                        "columns": [
                            {"key": "evidence", "label": "Evidence"},
                            {"key": "value", "label": "Value"},
                            {"key": "source", "label": "Source"},
                        ],
                        "rows": [{"evidence": "Planned sample", "value": "40", "source": "Approved source"}],
                    }
                }
            },
        }

    def test_complete_approved_reference_passes_branch_contract(self) -> None:
        result = validate_source_contract(self.complete_reference())
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["blocking_findings"], [])

    def test_sample_size_evidence_is_accepted_from_structured_source_sections(self) -> None:
        reference = self.complete_reference()
        reference["template_fields"].pop("data_driven_tables")
        reference["statistics"] = {
            "sample_size_evidence": [
                {"evidence": "COMET-2", "value": "16 subjects", "source": "Approved analysis"}
            ]
        }
        result = validate_source_contract(reference)
        self.assertEqual(result["status"], "passed")

    def test_approved_source_markdown_must_exist_in_the_run(self) -> None:
        import tempfile

        reference = self.complete_reference()
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            reference["source"]["source_of_truth_file"] = "reference/source.md"
            result = validate_source_contract(reference, run_dir=run_dir)
            self.assertTrue(any(item["field"] == "source.source_of_truth_file" for item in result["blocking_findings"]))
            source_path = run_dir / "reference/source.md"
            source_path.parent.mkdir(parents=True)
            source_path.write_text("# Approved Source", encoding="utf-8")
            result = validate_source_contract(reference, run_dir=run_dir)
            self.assertFalse(any(item["field"] == "source.source_of_truth_file" for item in result["blocking_findings"]))

    def test_unapproved_reference_blocks_before_delivery(self) -> None:
        reference = self.complete_reference()
        reference["approval"]["status"] = "pending_review"
        result = validate_source_contract(reference)
        self.assertTrue(any(item["field"] == "approval.status" for item in result["blocking_findings"]))

    def test_prospective_source_contract_requires_an_icf_template_choice(self) -> None:
        reference = self.complete_reference()
        reference["meta"].pop("icf_template")
        result = validate_source_contract(reference, require_approval=False)
        self.assertTrue(any(item["field"] == "meta.icf_template" for item in result["blocking_findings"]))

    def test_unmasked_study_omits_prs_masking_instead_of_emitting_forbidden_none(self) -> None:
        self.assertEqual(infer_masking({"design": {"masking": "None"}}), "")

    def test_legacy_alias_is_normalized_and_audited(self) -> None:
        reference = self.complete_reference()
        reference["meta"].pop("protocol_number")
        reference["template_fields"]["protocolNumber"] = "P-001"
        result = validate_source_contract(reference)
        self.assertEqual(result["status"], "passed")
        self.assertIn("protocol_number", result["normalized_reference"]["meta"])
        self.assertTrue(any(item["from"] == "template_fields.protocolNumber" for item in result["normalizations"]))

    def test_conflicting_aliases_are_blocking_and_report_evidence(self) -> None:
        reference = self.complete_reference()
        reference["parties"]["sub_investigator"] = "Dr. Conflicting Investigator"
        result = validate_source_contract(reference)
        conflict = next(item for item in result["blocking_findings"] if item["field"] == "parties.sub_investigators")
        self.assertEqual(conflict["severity"], "blocking")
        self.assertIn("reviewer decision", conflict["evidence_required"])

    def test_legacy_template_projection_is_audited_without_overriding_canonical_source(self) -> None:
        reference = self.complete_reference()
        reference["template_fields"]["protocolNumber"] = "P-999"
        result = validate_source_contract(reference)
        self.assertEqual(result["status"], "passed")
        self.assertTrue(any(item["from"] == "template_fields.protocolNumber" for item in result["normalizations"]))

    def test_table_contract_rejects_missing_rows_and_bad_order(self) -> None:
        reference = self.complete_reference()
        reference["procedures"]["visit_schedule_table"] = [
            {"visitNumber": "2", "visitName": "Month 3", "visitWindow": "Day 90 +/- 7", "CRFnumber": "M3"},
            {"visitNumber": "1", "visitName": "Baseline", "visitWindow": "Day 0", "CRFnumber": "BL"},
        ]
        errors = validate_data_driven_tables(reference)
        self.assertTrue(any("visit order" in item["issue"] for item in errors))

    def test_repair_report_names_blocker_and_required_evidence(self) -> None:
        reference = self.complete_reference()
        reference["risks_benefits"].pop("injury_handling")
        result = validate_source_contract(reference)
        report = repair_report_markdown(result["blocking_findings"])
        self.assertIn("risks_benefits.injury_handling", report)
        self.assertIn("evidence required", report.lower())

    def test_operational_detail_is_blocking_when_an_approved_value_is_removed(self) -> None:
        reference = self.complete_reference()
        reference["risks_benefits"].pop("injury_handling")
        missing = operational_detail_missing(reference)
        self.assertTrue(any(item["field"] == "risks_benefits.injury_handling" for item in missing))

    def test_canonical_metadata_overrides_substituted_legacy_projection(self) -> None:
        reference = self.complete_reference()
        reference["template_fields"].update(
            {"protocolNumber": "WRONG", "title": "Wrong title", "sponsortName": "Wrong sponsor"}
        )
        reference["template_fields"]["title"] = reference["study"]["title"]
        reference["parties"]["principal_investigator"]["name"] = "Canonical Investigator"
        reference["parties"]["sponsor"]["name"] = "Canonical Sponsor"
        data = normalize_title_page_fields(reference)
        fields = data["template_fields"]
        self.assertEqual(fields["protocolNumber"], "P-001")
        self.assertEqual(fields["sponsortName"], "Canonical Sponsor")
        self.assertTrue(any(item["field"] == "template_fields.protocolNumber" for item in data["metadata_normalizations"]))

    def test_ambiguous_legacy_schedule_is_reported_as_blocking(self) -> None:
        reference = self.complete_reference()
        reference["procedures"]["visit_schedule_table"] = []
        reference["procedures"]["visit_schedule"] = "Screening and follow-up as clinically indicated"
        table = visit_schedule_table(reference)
        self.assertEqual(table["rows"], [])
        self.assertTrue(table["legacy_string_fallback"]["blocking"])

    def test_section_caption_without_rows_cannot_enter_protocol_model(self) -> None:
        reference = self.complete_reference()
        reference["generated"] = {
            "protocol": {
                "sections": [
                    {
                        "number": "15.",
                        "title": "STANDARD EVALUATION PROCEDURES",
                        "tables": [{
                            "name": "schedule_of_assessments",
                            "caption": "15.1 Proposed Visits and Study Assessments",
                            "columns": [{"key": "visitName", "label": "Visit Name"}],
                            "rows": [],
                        }],
                    }
                ]
            }
        }
        with self.assertRaisesRegex(ValueError, "rows must contain at least one source row"):
            build_protocol_model(reference)

    def test_internal_process_language_blocks_source_contract(self) -> None:
        reference = self.complete_reference()
        reference["generated"] = {"protocol": {"introduction": "TODO: finalize later."}}
        result = validate_source_contract(reference)
        self.assertTrue(any(item["field"] == "generated" for item in result["blocking_findings"]))

    def test_delivery_pipeline_fails_closed_without_a_real_output(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            reference_path = run_dir / "reference/study.reference.json"
            reference_path.parent.mkdir(parents=True)
            reference_path.write_text("{}", encoding="utf-8")
            result = run_delivery_pipeline(run_dir, [])
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["client_outputs"], [])
            self.assertTrue((run_dir / "reference/repair-report.md").exists())

    def test_branch_readiness_passes_all_three_approved_branches(self) -> None:
        for study_type in ("Prospective", "Ambispective", "Retrospective"):
            reference = self.complete_reference(study_type)
            reference["generated"] = {
                "protocol": {"introduction": "Approved protocol.", "visitScheduleTable": reference["procedures"]["visit_schedule_table"]}
            }
            reference["template_fields"].update({
                "AI_populationShort": "Approved population.",
                "AI_introduction": "Approved introduction.",
                "AI_populationLong": "Approved population section.",
                "AI_inclusionCriteria": "Approved inclusion criteria.",
                "AI_exclusionCriteria": "Approved exclusion criteria.",
                "AI_studyDesignLong": "Approved design.",
                "AI_methods": "Approved methods.",
                "AI_visitSchedule": "Approved schedule.",
                "AI_visitScheduleDetails": "Approved schedule details.",
                "AI_measurements": "Approved measurements.",
                "AI_measurementsDetails": "Approved measurement details.",
                "AI_analysisDataSets": "Approved analysis sets.",
                "AI_statisticalMethodology": "Approved methodology.",
                "AI_statisticalConsiderations": "Approved considerations.",
                "AI_risks": "Approved risks.",
                "AI_objectivesIntro": "Approved objectives.",
                "AI_primaryOutcome": "Approved outcome.",
                "AI_analysisDataSetsBullets": "Approved analysis bullets.",
                "AI_studyProcedure": "Approved procedure.",
            })
            if study_type != "Retrospective":
                reference["generated"]["icf"] = {"study_purpose": "Approved purpose."}
                reference["regulatory"] = {"xml_profile": "clinicaltrials-prs"}
                reference["template_fields"].update({
                    "AI_studyPurpose": "Approved purpose.",
                    "AI_icfVisitsOverview": "Approved visits.",
                    "AI_visitsDetails": "Approved details.",
                    "AI_visitsAndLength": "Approved length.",
                    "AI_interventionPossibleSideEffects": "Approved side effects.",
                })
                reference["template_fields"]["data_driven_tables"]["visit_schedule"] = {
                    "columns": [
                        {"key": "visitNumber", "label": "Visit Number"},
                        {"key": "visitName", "label": "Visit Name"},
                        {"key": "visitWindow", "label": "Visit Window"},
                        {"key": "CRFnumber", "label": "CRF Number"},
                    ],
                    "rows": reference["procedures"]["visit_schedule_table"],
                }
                reference["template_fields"]["data_driven_tables"]["prs_xml"] = {
                    "primary_outcomes": {"rows": [{"outcomeMeasure": "Primary", "outcomeTimeFrame": "Month 3", "uid": "P1", "description": "Approved."}]}
                }
            report = readiness_report(reference)
            self.assertEqual(report["status"], "passed", study_type)

    def test_branch_readiness_blocks_unapproved_and_contaminated_runs(self) -> None:
        reference = self.complete_reference("Retrospective")
        reference["approval"]["status"] = "pending_review"
        reference["generated"] = {"protocol": {"introduction": "TODO: finalize later."}}
        report = readiness_report(reference)
        fields = {item["field"] for item in report["findings"]}
        self.assertIn("approval.status", fields)
        self.assertIn("generated", fields)


if __name__ == "__main__":
    unittest.main()
