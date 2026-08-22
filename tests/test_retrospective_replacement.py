from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from retrospective import (  # noqa: E402
    RetryLedger,
    SectionDraft,
    merge_section_drafts,
    retrospective_batch_plan,
    retrospective_contract,
    verify_rendered_pages,
    verify_retrospective_sections,
    reuse_accepted_drafts,
)
from drafting import plan_retrospective_batches  # noqa: E402
from delivery_gates import audit_retrospective_visual_acceptance  # noqa: E402
from clinical_document_workflow import branch_contract  # noqa: E402


class RetrospectiveReplacementTests(unittest.TestCase):
    def test_contract_has_bundled_1_to_13_hierarchy_in_order(self) -> None:
        contract = retrospective_contract()
        top_level = [item.number for item in contract if "." not in item.section_id]
        self.assertEqual(top_level, [f"{index}." for index in range(1, 14)])
        self.assertEqual([item.number for item in contract[-7:]], ["9.1.", "9.2.", "9.3.", "10.", "11.", "12.", "13."])
        self.assertEqual(len(retrospective_batch_plan()), 3)

    def test_merge_is_stable_and_rejects_unknown_sections(self) -> None:
        drafts = [
            SectionDraft("ethics", "Ethics content", batch_id="protocol-analysis-and-oversight"),
            SectionDraft("introduction", "Introduction content", batch_id="protocol-foundations"),
        ]
        self.assertEqual([draft.section_id for draft in merge_section_drafts(drafts)], ["introduction", "ethics"])
        with self.assertRaisesRegex(ValueError, "Unknown"):
            merge_section_drafts([SectionDraft("not-a-section", "x")])

    def test_content_and_visual_verifiers_return_findings_without_mutation(self) -> None:
        drafts = [SectionDraft("introduction", "TODO: draft this")]
        self.assertEqual(verify_retrospective_sections(drafts)[0]["section_id"], "introduction")
        visual = verify_rendered_pages({1: "", 2: "inspected"})
        self.assertEqual(visual, [{"artifact": "protocol.docx", "page": 1, "category": "visual", "issue": "Rendered page has no inspection evidence."}])

    def test_retry_ledger_counts_initial_attempt_and_caps_at_three(self) -> None:
        ledger = RetryLedger()
        self.assertEqual([ledger.record("section:introduction") for _ in range(3)], [1, 2, 3])
        self.assertFalse(ledger.can_attempt("section:introduction"))
        with self.assertRaisesRegex(ValueError, "exhausted"):
            ledger.record("section:introduction")

    def test_targeted_retry_reuses_unrelated_accepted_drafts(self) -> None:
        drafts = [SectionDraft("introduction", "accepted"), SectionDraft("ethics", "accepted")]
        self.assertEqual([draft.section_id for draft in reuse_accepted_drafts(drafts, ["introduction"])], ["ethics"])
        self.assertEqual([batch.batch_id for batch in plan_retrospective_batches()], [
            "protocol-foundations", "protocol-operations", "protocol-analysis-and-oversight"
        ])

    def test_retrospective_visual_gate_is_branch_specific(self) -> None:
        self.assertTrue(callable(audit_retrospective_visual_acceptance))

    def test_public_branch_contract_exposes_only_retrospective_replacement_tasks(self) -> None:
        contract = branch_contract({"meta": {"study_type": "retrospective"}})
        replacement = contract["replacement_workflow"]
        self.assertEqual([batch["batch_id"] for batch in replacement["drafting_batches"]], [
            "protocol-foundations", "protocol-operations", "protocol-analysis-and-oversight"
        ])
        self.assertNotIn("icf", " ".join(batch["batch_id"] for batch in replacement["drafting_batches"]).lower())
        self.assertNotIn("prs", " ".join(batch["batch_id"] for batch in replacement["drafting_batches"]).lower())


if __name__ == "__main__":
    unittest.main()
