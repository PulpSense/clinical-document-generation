from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from clinical_document_workflow import branch_contract  # noqa: E402
from drafting import plan_prospective_batches  # noqa: E402
from prospective import (  # noqa: E402
    SectionDraft,
    merge_prospective_drafts,
    prospective_contract,
    prospective_batch_plan,
    scoped_batch_input,
    verify_prospective_sections,
)


class ProspectiveReplacementTests(unittest.TestCase):
    def test_contract_has_corrected_1_to_19_hierarchy(self) -> None:
        contract = prospective_contract()
        top_level = [item.number for item in contract if "." not in item.section_id]
        self.assertEqual(top_level, [f"{index}." for index in range(1, 20)])
        self.assertEqual(len(prospective_batch_plan()), 3)
        self.assertEqual(plan_prospective_batches(), prospective_batch_plan())

    def test_batches_expose_only_relevant_approved_field_families(self) -> None:
        batches = prospective_batch_plan()
        self.assertEqual(
            [batch.batch_id for batch in batches],
            ["protocol-foundations", "protocol-operations", "protocol-analysis-and-oversight"],
        )
        self.assertNotIn("icf", " ".join(batches[0].approved_field_families).lower())
        self.assertIn("procedures", batches[1].approved_field_families)
        self.assertIn("statistics", batches[2].approved_field_families)

    def test_scoped_batch_input_excludes_unrelated_reference_families(self) -> None:
        reference = {"study": {"title": "Study"}, "objectives": {"primary": "Outcome"}, "procedures": {"assessments": "Visits"}, "statistics": {"analysis_plan": "Descriptive"}, "generated": {"protocol": {"internal": "not a drafting input"}}}
        scoped = scoped_batch_input(reference, "protocol-foundations")
        self.assertEqual(set(scoped), {"study", "objectives"})
        self.assertNotIn("generated", scoped)
        scoped["study"]["title"] = "changed"  # type: ignore[index]
        self.assertEqual(reference["study"]["title"], "Study")  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "Unknown"):
            scoped_batch_input(reference, "icf")

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
        self.assertEqual(len(workflow["drafting_batches"]), 3)
        self.assertEqual(workflow["candidate_visibility"], "internal_until_complete_branch_package")


if __name__ == "__main__":
    unittest.main()
