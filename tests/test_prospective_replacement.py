from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from workflow import branch_contract  # noqa: E402
from drafting import draft_prs_narrative, draft_prospective_protocol  # noqa: E402
from drafting import plan_prospective_batches  # noqa: E402
from prospective import (  # noqa: E402
    SectionDraft,
    merge_prospective_drafts,
    prospective_contract,
    prospective_batch_plan,
    scoped_batch_input,
    validate_prs_narrative,
    verify_prospective_sections,
)


class ProspectiveReplacementTests(unittest.TestCase):
    def test_public_drafting_boundary_merges_three_scoped_protocol_batches(self) -> None:
        reference = json.loads((Path(__file__).parent / "fixtures/gp-26-01-approved.json").read_text(encoding="utf-8"))
        reference["meta"]["study_type"] = "Prospective"
        result = draft_prospective_protocol(reference)
        report = result["report"]
        self.assertEqual(report["status"], "passed")
        self.assertEqual([batch["batch_id"] for batch in report["batches"]], [
            "protocol-foundations", "protocol-operations", "protocol-analysis-and-oversight"
        ])
        self.assertEqual(len(result["drafts"]), len([section for section in prospective_contract() if section.number not in {"1.", "2.", "3.", "4."}]))
        self.assertEqual(report["verification"]["findings"], [])
        operations = next(batch for batch in report["batches"] if batch["batch_id"] == "protocol-operations")
        self.assertIn("procedures", operations["approved_field_families"])
        self.assertNotIn("template_fields", operations["approved_input"])
        sections = result["reference"]["generated"]["protocol"]["sections"]
        self.assertTrue(any(section.get("tables") for section in sections if section.get("number") == "15."))

    def test_prs_narrative_runs_after_protocol_and_merges_only_prose(self) -> None:
        reference = {
            "study": {"background": "Background."},
            "objectives": {"primary": "Primary.", "secondary": "Secondary."},
            "design": {"study_design": "Design."},
            "generated": {"protocol": {}},
        }
        result = draft_prs_narrative(
            reference,
            prerequisite_report={
                "status": "passed",
                "completed_batch_ids": ["protocol-foundations"],
                "verification": {"status": "passed"},
            },
        )
        self.assertEqual(result["report"]["batch_id"], "prs-narrative")
        self.assertFalse(result["report"]["verification"]["xml_markup_emitted"])
        self.assertEqual(result["reference"]["generated"]["xml"], {
            "brief_summary": "Design.",
            "detailed_description": "Background.\n\nPrimary.\n\nSecondary.",
        })
        with self.assertRaisesRegex(ValueError, "requires passed"):
            draft_prs_narrative(reference, prerequisite_report={"status": "passed", "completed_batch_ids": []})

    def test_contract_has_corrected_1_to_19_hierarchy(self) -> None:
        contract = prospective_contract()
        top_level = [item.number for item in contract if "." not in item.section_id]
        self.assertEqual(top_level, [f"{index}." for index in range(1, 20)])
        self.assertEqual(len(prospective_batch_plan()), 5)
        self.assertEqual(plan_prospective_batches(), prospective_batch_plan())

    def test_batches_expose_only_relevant_approved_field_families(self) -> None:
        batches = prospective_batch_plan()
        self.assertEqual(
            [batch.batch_id for batch in batches],
            ["protocol-foundations", "protocol-operations", "protocol-analysis-and-oversight", "prs-narrative", "icf-narrative"],
        )
        self.assertNotIn("icf", " ".join(batches[0].approved_field_families).lower())
        self.assertIn("procedures", batches[1].approved_field_families)
        self.assertIn("statistics", batches[2].approved_field_families)
        self.assertEqual(batches[3].prerequisite_ids, ("protocol-foundations",))
        self.assertEqual(batches[3].section_ids, ("prs-narrative",))
        self.assertIn("procedures", batches[4].approved_field_families)
        self.assertNotIn("protocol", batches[4].approved_field_families)

    def test_scoped_batch_input_excludes_unrelated_reference_families(self) -> None:
        reference = {"study": {"title": "Study"}, "objectives": {"primary": "Outcome"}, "procedures": {"assessments": "Visits"}, "statistics": {"analysis_plan": "Descriptive"}, "generated": {"protocol": {"internal": "not a drafting input"}}}
        scoped = scoped_batch_input(reference, "protocol-foundations")
        self.assertEqual(set(scoped), {"study", "objectives"})
        self.assertNotIn("generated", scoped)
        scoped["study"]["title"] = "changed"  # type: ignore[index]
        self.assertEqual(reference["study"]["title"], "Study")  # type: ignore[index]
        prs_scoped = scoped_batch_input({"study": {}, "generated": {"protocol": {"study_design": "accepted"}, "xml": "forbidden"}}, "prs-narrative")
        self.assertEqual(prs_scoped, {"study": {}, "generated": {"protocol": {"study_design": "accepted"}}})
        with self.assertRaisesRegex(ValueError, "Unknown"):
            scoped_batch_input(reference, "icf")
        self.assertEqual(validate_prs_narrative({"brief_summary": "Brief", "detailed_description": "Detailed", "xml": "ignored"}), {"brief_summary": "Brief", "detailed_description": "Detailed"})
        with self.assertRaisesRegex(ValueError, "XML"):
            validate_prs_narrative({"brief_summary": "<arm_group />"})

    def test_merge_and_verify_are_contract_ordered_and_fail_closed(self) -> None:
        drafts = [
            SectionDraft("risks-benefits", "Risks", batch_id="protocol-analysis-and-oversight"),
            SectionDraft("introduction", "Introduction", batch_id="protocol-foundations"),
        ]
        self.assertEqual([draft.section_id for draft in merge_prospective_drafts(drafts)], ["introduction", "risks-benefits"])
        findings = verify_prospective_sections(drafts)
        self.assertTrue(any(item["section_id"] == "objectives" for item in findings))
        with self.assertRaisesRegex(ValueError, "Unknown"):
            merge_prospective_drafts([SectionDraft("not-a-section", "x")])

    def test_public_branch_contract_records_internal_complete_candidate_workflow(self) -> None:
        contract = branch_contract({"meta": {"study_type": "Prospective"}})
        workflow = contract["replacement_workflow"]
        self.assertEqual(workflow["contract_version"], "prospective-1-19-v1")
        self.assertEqual(len(workflow["section_ids"]), len(prospective_contract()))
        self.assertEqual(len(workflow["drafting_batches"]), 5)
        self.assertEqual(workflow["candidate_visibility"], "internal_until_complete_branch_package")


if __name__ == "__main__":
    unittest.main()
