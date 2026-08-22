from __future__ import annotations

import copy
import sys
import unittest


from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from readiness_contract import (  # noqa: E402
    FINDING_CATEGORIES,
    REQUIRED_BLOCKING_SCENARIOS,
    classify_future_finding,
    readiness_evidence,
)
from study_type_branches import branch_for_study_type  # noqa: E402
from tests.test_clinical_document_workflow import ClinicalDocumentWorkflowTests  # noqa: E402


class ReadinessContractTests(unittest.TestCase):
    def ready_reference(self, study_type: str) -> dict:
        reference = copy.deepcopy(ClinicalDocumentWorkflowTests().reference(study_type))
        fields = reference.setdefault("template_fields", {})
        branch = branch_for_study_type(study_type)
        for item in branch["content_completeness"]:
            field = item["field"]
            if field.startswith("template_fields.") and "data_driven_tables" not in field:
                fields[field.removeprefix("template_fields.")] = "Approved generated content."
        if study_type != "Retrospective":
            fields.setdefault("data_driven_tables", {})["visit_schedule"] = {
                "columns": [
                    {"key": "visitNumber", "label": "Visit Number"},
                    {"key": "visitName", "label": "Visit Name"},
                    {"key": "visitWindow", "label": "Visit Window"},
                    {"key": "CRFnumber", "label": "CRF Number"},
                ],
                "rows": reference["procedures"]["visit_schedule_table"],
            }
            reference["generated"] = {"icf": {"study_purpose": "Approved purpose."}}
            reference["regulatory"] = {"xml_profile": "clinicaltrials-prs"}
            fields["data_driven_tables"]["prs_xml"] = {
                "primary_outcomes": {"rows": [{"outcomeMeasure": "Primary", "outcomeTimeFrame": "Month 3", "uid": "P1", "description": "Approved."}]}
            }
        return reference

    def test_readiness_evidence_declares_the_branch_document_matrix(self) -> None:
        for study_type in ("Prospective", "Ambispective", "Retrospective"):
            reference = self.ready_reference(study_type)
            evidence = readiness_evidence(reference)
            expected = ["protocol_docx"] if study_type == "Retrospective" else ["protocol_docx", "icf_docx", "xml"]
            self.assertEqual(evidence["required_document_set"], expected)
            self.assertEqual(evidence["status"], "passed")

    def test_readiness_evidence_records_pipeline_failure(self) -> None:
        reference = self.ready_reference("Retrospective")
        evidence = readiness_evidence(reference, pipeline={"status": "failed"})
        self.assertEqual(evidence["status"], "blocked")
        self.assertIn("failed_render_or_static_toc_gate", evidence["blocking_scenarios"])

    def test_future_finding_categories_are_explicit(self) -> None:
        self.assertEqual(set(FINDING_CATEGORIES), {"contract_bug", "reference_defect", "new_requirement"})
        self.assertEqual(classify_future_finding("new_requirement")["category"], "new_requirement")
        with self.assertRaises(ValueError):
            classify_future_finding("random_request")

    def test_readiness_contract_lists_required_blocking_scenarios(self) -> None:
        self.assertIn("unapproved_source_of_truth", REQUIRED_BLOCKING_SCENARIOS)
        self.assertIn("failed_docx_package_or_structure_gate", REQUIRED_BLOCKING_SCENARIOS)


if __name__ == "__main__":
    unittest.main()
