"""Branch-level acceptance tests for the deterministic generation workflow.

Each test starts from an approved structured study reference and invokes the
supported branch workflow once, then inspects the produced artifacts, the
Delivery Gate outcomes, and delivery eligibility. These tests deliberately avoid
private helpers so the seam stays replaceable.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import branch_fixtures
from branch_fixtures import build_run, write_reference


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from generate_branch_documents import generate_branch  # noqa: E402
from render_templates import visible_text_from_word_xml  # noqa: E402


def docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        return visible_text_from_word_xml(archive.read("word/document.xml").decode())


def gate(result: dict, name: str) -> dict:
    for item in result["gates"]:
        if item["gate"] == name:
            return item
    raise AssertionError(f"Gate {name!r} not in {[g['gate'] for g in result['gates']]}")


class RetrospectiveBranchTests(unittest.TestCase):
    def test_approved_fixture_generates_only_the_protocol(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            build_run(run_dir, "retrospective")

            result = generate_branch(run_dir)

            self.assertEqual(result["branch"], "Retrospective")
            self.assertEqual(result["document_set"], ["protocol_docx"])
            self.assertEqual(result["artifacts"], {"protocol_docx": "output/protocol.docx"})
            self.assertTrue(result["delivery_ready"], result["gates"])

            protocol = run_dir / "output" / "protocol.docx"
            self.assertTrue(protocol.is_file())
            with zipfile.ZipFile(protocol) as archive:
                self.assertIsNone(archive.testzip())
            self.assertFalse((run_dir / "output" / "icf.docx").exists())
            self.assertFalse((run_dir / "output" / "study.xml").exists())

    def test_protocol_carries_branch_body_content_and_no_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            build_run(run_dir, "retrospective")

            result = generate_branch(run_dir)

            self.assertEqual(gate(result, "placeholders")["status"], "pass")
            self.assertEqual(gate(result, "content_completeness")["status"], "pass")
            text = docx_text(run_dir / "output" / "protocol.docx")
            self.assertIn("retrospective chart review", text)
            self.assertIn("Single-centre retrospective observational chart review.", text)
            self.assertNotIn("{", text)

    def test_optional_values_and_generic_notes_do_not_block(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            reference = build_run(run_dir, "retrospective")
            reference["generated"]["protocol"]["secondaryOutcomes"] = []
            reference["generated"]["protocol"]["exploratoryOutcomes"] = []
            reference["needs_review"] = [
                {"field": "study.title", "issue": "Confirm the title casing with the sponsor."},
                {"field": "meta.version", "issue": "Optional note about versioning."},
            ]
            write_reference(run_dir, reference)

            result = generate_branch(run_dir)

            self.assertEqual(gate(result, "required_inputs")["status"], "pass")
            self.assertTrue(result["delivery_ready"], result["gates"])

    def test_missing_retrospective_required_input_blocks_before_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            reference = build_run(run_dir, "retrospective")
            reference["study"]["hypothesis"] = None
            write_reference(run_dir, reference)

            result = generate_branch(run_dir)

            self.assertFalse(result["delivery_ready"])
            required = gate(result, "required_inputs")
            self.assertEqual(required["status"], "fail")
            self.assertIn(
                "study.hypothesis", [item["field"] for item in required["findings"]]
            )
            self.assertFalse((run_dir / "output" / "protocol.docx").exists())
            self.assertTrue((run_dir / result["repair_report"]).is_file())

    def test_prospective_only_input_is_not_required_by_retrospective(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            reference = build_run(run_dir, "retrospective")
            # `procedures.visit_schedule_table` and the ICF choice are prospective-only.
            reference["meta"]["icf_template"] = None
            reference["procedures"].pop("assessment_details", None)
            write_reference(run_dir, reference)

            result = generate_branch(run_dir)

            self.assertEqual(gate(result, "required_inputs")["status"], "pass")
            self.assertTrue(result["delivery_ready"], result["gates"])

    def test_blank_branch_body_content_fails_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            reference = build_run(run_dir, "retrospective")
            reference["generated"]["protocol"]["methods"] = ""
            write_reference(run_dir, reference)

            result = generate_branch(run_dir)

            self.assertFalse(result["delivery_ready"])
            completeness = gate(result, "content_completeness")
            self.assertEqual(completeness["status"], "fail")
            self.assertIn(
                "AI_methods", [item["field"] for item in completeness["findings"]]
            )
            self.assertTrue((run_dir / result["repair_report"]).is_file())

    def test_stale_template_language_fails_delivery_with_a_repair_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            reference = build_run(run_dir, "retrospective")
            reference["generated"]["protocol"]["methods"] = (
                "Investigators abstract data using the Sunrise Cardiology Registry protocol template."
            )
            reference["meta"]["stale_content_markers"] = ["Sunrise Cardiology Registry"]
            write_reference(run_dir, reference)

            result = generate_branch(run_dir)

            self.assertFalse(result["delivery_ready"])
            stale = gate(result, "stale_content")
            self.assertEqual(stale["status"], "fail")
            self.assertIn(
                "Sunrise Cardiology Registry",
                " ".join(item["marker"] for item in stale["findings"]),
            )
            report = (run_dir / result["repair_report"]).read_text(encoding="utf-8")
            self.assertIn("Sunrise Cardiology Registry", report)
            self.assertIn("output/protocol.docx", report)

    def test_renderer_unavailability_is_recorded_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            build_run(run_dir, "retrospective")

            result = generate_branch(run_dir, renderer_available=False)

            visual = gate(result, "visual_qa")
            self.assertEqual(visual["status"], "skipped")
            self.assertTrue(result["delivery_ready"], result["gates"])
            self.assertIn("renderer", result["qa"])
            self.assertEqual(result["qa"]["renderer"], "unavailable")
            self.assertTrue((run_dir / "logs" / "visual-qa.json").is_file())


if __name__ == "__main__":
    unittest.main()
