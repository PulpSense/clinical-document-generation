from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from workflow import approve_source, generate_approved_run, prepare_run, validate_run  # noqa: E402
from tests.test_quality_contract import QualityContractTests  # noqa: E402


class ClinicalDocumentWorkflowTests(unittest.TestCase):
    def reference(self, study_type: str = "Prospective") -> dict:
        reference = copy.deepcopy(QualityContractTests().complete_reference(study_type))
        reference["study"].update(
            {
                "background": "Background and significance.",
                "hypothesis": "The primary outcome will improve.",
            }
        )
        reference["objectives"] = {"primary": ["Evaluate the primary outcome."]}
        reference["design"].update(
            {
                "intervention_name": "Study Device",
                "intervention_type": "Device",
            }
        )
        reference["procedures"]["minimum_days_before_screening_without_participation"] = 30
        reference["statistics"] = {"analysis_plan": "Descriptive analysis."}
        reference["parties"].update(
            {
                "irb": {
                    "name": "Example IRB",
                    "affiliation": "Independent",
                    "phone": "555-0200",
                    "email": "irb@example.org",
                    "address": "2 Review Avenue",
                },
                "study_coordinator": {
                    "name": "Jordan Lee",
                    "title": "CRC",
                    "business_phone": "555-0100",
                    "office_phone": "555-0101",
                    "email": "jordan@example.org",
                },
            }
        )
        reference["sites"] = [
            {
                "facility": {"name": "Site One"},
                "contact": {"name": "Jordan Lee", "email": "jordan@example.org"},
                "investigators": [{"name": "A. Investigator", "degrees": "MD"}],
            }
        ]
        return reference

    def write_run(self, root: Path, reference: dict) -> Path:
        run_dir = root / "run"
        (run_dir / "input").mkdir(parents=True)
        (run_dir / "reference").mkdir(parents=True)
        (run_dir / "input/raw_context.md").write_text("Generate the clinical documents.", encoding="utf-8")
        (run_dir / "reference/study.reference.json").write_text(json.dumps(reference), encoding="utf-8")
        return run_dir

    def test_prepare_run_creates_source_truth_and_waits_for_client_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            reference = self.reference()
            reference["approval"]["status"] = "pending_review"
            run_dir = self.write_run(Path(temporary), reference)
            (run_dir / "reference/missing-inputs.md").write_text("stale blocker", encoding="utf-8")

            result = prepare_run(run_dir)

            self.assertEqual(result["status"], "awaiting_approval")
            self.assertTrue((run_dir / result["source_of_truth"]).is_file())
            self.assertFalse((run_dir / "output/protocol.docx").exists())
            stored = json.loads((run_dir / "reference/study.reference.json").read_text(encoding="utf-8"))
            self.assertEqual(stored["approval"]["status"], "pending_review")
            self.assertFalse((run_dir / "reference/missing-inputs.md").exists())
            source_text = (run_dir / result["source_of_truth"]).read_text(encoding="utf-8")
            self.assertIn("<!-- field: procedures.retention -->", source_text)
            self.assertIn("<!-- field: safety.roles -->", source_text)
            self.assertIn("<!-- field: risks_benefits.privacy -->", source_text)

    def test_prepare_run_consolidates_missing_facts_and_template_choice(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            reference = self.reference()
            reference["meta"].pop("icf_template")
            reference["design"].pop("arms")
            run_dir = self.write_run(Path(temporary), reference)

            result = prepare_run(run_dir)

            self.assertEqual(result["status"], "blocked")
            report = (run_dir / "reference/missing-inputs.md").read_text(encoding="utf-8")
            self.assertIn("meta.icf_template", report)
            self.assertNotIn("design.arms", report)
            self.assertFalse(list((run_dir / "output").glob("*")) if (run_dir / "output").exists() else [])

    def test_prepare_run_uses_the_original_n8n_starred_input_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            reference = self.reference()
            for field in ("version", "date"):
                reference["meta"].pop(field)
            reference["population"].pop("study_population")
            reference["design"].pop("masking")
            for field in ("retention", "discontinuation", "replacement"):
                reference["procedures"].pop(field)
            reference["risks_benefits"].pop("injury_handling")
            reference["risks_benefits"].pop("privacy")
            reference.pop("safety", None)
            run_dir = self.write_run(Path(temporary), reference)

            result = prepare_run(run_dir)

            self.assertEqual(result["status"], "awaiting_approval")

    def test_generate_approved_run_requires_the_approved_markdown_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            reference = self.reference()
            reference["approval"] = {"status": "approved", "approved_by": "Client"}
            reference["source"]["source_of_truth_file"] = "reference/approved.md"
            run_dir = self.write_run(Path(temporary), reference)

            result = generate_approved_run(run_dir)

            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["client_outputs"], [])
            self.assertTrue((run_dir / "reference/repair-report.md").is_file())
            self.assertIn("does not exist", (run_dir / "reference/repair-report.md").read_text(encoding="utf-8"))

    def test_validate_run_returns_one_consolidated_readiness_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            reference = self.reference()
            reference["approval"]["status"] = "pending_review"
            run_dir = self.write_run(Path(temporary), reference)

            result = validate_run(run_dir)

            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["stage"], "readiness")
            self.assertIn("readiness_report", result)
            fields = {item["field"] for item in result["readiness_report"]["findings"]}
            self.assertIn("approval.status", fields)
            self.assertEqual(result["client_outputs"], [])

    def test_approve_source_parses_the_current_markdown_before_release(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = self.write_run(Path(temporary), self.reference())
            prepared = prepare_run(run_dir)

            result = approve_source(run_dir, approved_by="Client Reviewer")

            self.assertEqual(result["approval_status"], "approved")
            stored = json.loads((run_dir / "reference/study.reference.json").read_text(encoding="utf-8"))
            self.assertEqual(stored["approval"]["approved_by"], "Client Reviewer")
            self.assertEqual(stored["source"]["source_of_truth_file"], prepared["source_of_truth"])

    def test_approve_source_accepts_a_client_edited_markdown_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = self.write_run(Path(temporary), self.reference())
            prepared = prepare_run(run_dir)
            edited = run_dir / "input/attachments/client-edited-source.md"
            edited.parent.mkdir(parents=True, exist_ok=True)
            edited.write_text((run_dir / prepared["source_of_truth"]).read_text(encoding="utf-8"), encoding="utf-8")

            result = approve_source(run_dir, approved_by="Client Reviewer", source_md=edited)

            self.assertEqual(result["approval_status"], "approved")
            stored = json.loads((run_dir / "reference/study.reference.json").read_text(encoding="utf-8"))
            self.assertEqual(stored["approval"]["review_file"], "input/attachments/client-edited-source.md")

    def test_approval_records_hash_and_immutable_revision_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = self.write_run(Path(temporary), self.reference())
            prepared = prepare_run(run_dir)
            result = approve_source(run_dir, approved_by="Client Reviewer")

            stored = json.loads((run_dir / "reference/study.reference.json").read_text(encoding="utf-8"))
            revision_id = stored["approval"]["run_revision"]
            revision_dir = run_dir / "revisions" / revision_id
            self.assertEqual(stored["approval"]["approved_source_sha256"], result["source_sha256"])
            self.assertTrue((revision_dir / "source-of-truth.md").is_file())
            manifest = json.loads((revision_dir / "generation-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["approved_source"]["sha256"], result["source_sha256"])
            self.assertEqual(prepared["source_of_truth"], stored["approval"]["review_file"])

    def test_changed_approved_source_invalidates_approval_and_client_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = self.write_run(Path(temporary), self.reference())
            prepared = prepare_run(run_dir)
            approve_source(run_dir, approved_by="Client Reviewer")
            source_path = run_dir / prepared["source_of_truth"]
            for relative in (
                "drafts/section.json",
                "output/protocol.docx",
                "evidence/readiness.json",
            ):
                path = run_dir / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("preserved evidence", encoding="utf-8")
            source_path.write_text(source_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

            result = validate_run(run_dir)

            self.assertEqual(result["source_invalidation"]["field"], "approval.approved_source_sha256")
            self.assertEqual(result["readiness_report"]["status"], "blocked")
            stored = json.loads((run_dir / "reference/study.reference.json").read_text(encoding="utf-8"))
            self.assertEqual(stored["approval"]["status"], "changes_requested")
            invalidation = json.loads((run_dir / "state/source-invalidation.json").read_text(encoding="utf-8"))
            self.assertEqual(
                invalidation["invalidated_material"],
                [
                    {"path": "drafts/section.json", "status": "invalidated"},
                    {"path": "evidence/readiness.json", "status": "invalidated"},
                    {"path": "output/protocol.docx", "status": "invalidated"},
                ],
            )

    def test_deleted_approved_source_invalidates_approval_before_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = self.write_run(Path(temporary), self.reference())
            prepared = prepare_run(run_dir)
            approve_source(run_dir, approved_by="Client Reviewer")
            (run_dir / prepared["source_of_truth"]).unlink()

            result = generate_approved_run(run_dir)

            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["stage"], "approval_gate")
            self.assertEqual(result["findings"][0]["actual_sha256"], None)
            stored = json.loads((run_dir / "reference/study.reference.json").read_text(encoding="utf-8"))
            self.assertEqual(stored["approval"]["status"], "changes_requested")


if __name__ == "__main__":
    unittest.main()
