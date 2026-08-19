"""Branch-level acceptance tests for the deterministic generation workflow.

Each test starts from an approved structured study reference and invokes the
supported branch workflow once, then inspects the produced artifacts, the
Delivery Gate outcomes, and delivery eligibility. These tests deliberately avoid
private helpers so the seam stays replaceable.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import branch_fixtures
from branch_fixtures import build_run, write_reference


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from generate_branch_documents import generate_branch  # noqa: E402
from render_templates import unresolved_in_docx, visible_text_from_word_xml  # noqa: E402


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

            result = generate_branch(run_dir, renderer_available=False)

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

            result = generate_branch(run_dir, renderer_available=False)

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

            result = generate_branch(run_dir, renderer_available=False)

            self.assertEqual(gate(result, "required_inputs")["status"], "pass")
            self.assertTrue(result["delivery_ready"], result["gates"])

    def test_missing_retrospective_required_input_blocks_before_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            reference = build_run(run_dir, "retrospective")
            reference["study"]["hypothesis"] = None
            write_reference(run_dir, reference)

            result = generate_branch(run_dir, renderer_available=False)

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

            result = generate_branch(run_dir, renderer_available=False)

            self.assertEqual(gate(result, "required_inputs")["status"], "pass")
            self.assertTrue(result["delivery_ready"], result["gates"])

    def test_blank_branch_body_content_fails_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            reference = build_run(run_dir, "retrospective")
            reference["generated"]["protocol"]["methods"] = ""
            write_reference(run_dir, reference)

            result = generate_branch(run_dir, renderer_available=False)

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

            result = generate_branch(run_dir, renderer_available=False)

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


class ProspectiveBranchTests(unittest.TestCase):
    def test_approved_fixture_generates_the_complete_default_set(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            build_run(run_dir, "prospective")

            result = generate_branch(run_dir, renderer_available=False)

            self.assertEqual(result["branch"], "Prospective")
            self.assertEqual(result["document_set"], ["protocol_docx", "icf_docx", "xml"])
            self.assertEqual(
                result["artifacts"],
                {
                    "protocol_docx": "output/protocol.docx",
                    "icf_docx": "output/icf.docx",
                    "xml": "output/study.xml",
                },
            )
            self.assertTrue(result["delivery_ready"], result["gates"])
            for rel in result["artifacts"].values():
                self.assertTrue((run_dir / rel).is_file(), rel)

    def test_protocol_has_a_real_visit_table_and_branch_body_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            build_run(run_dir, "prospective")

            result = generate_branch(run_dir, renderer_available=False)

            self.assertEqual(gate(result, "visit_table")["status"], "pass")
            self.assertEqual(gate(result, "content_completeness")["status"], "pass")
            text = docx_text(run_dir / "output" / "protocol.docx")
            self.assertIn("Randomised, parallel-group, open-label, multicentre study.", text)
            self.assertIn("Screening", text)

    def test_icf_has_prose_visit_information_and_no_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            build_run(run_dir, "prospective")

            generate_branch(run_dir, renderer_available=False)

            icf = docx_text(run_dir / "output" / "icf.docx")
            self.assertIn("come to the clinic for seven visits", icf)
            self.assertIn("about one hour", icf)
            self.assertNotIn("{", icf)
            self.assertEqual(unresolved_in_docx(run_dir / "output" / "icf.docx"), [])

    def test_prs_xml_is_well_formed_and_passes_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            build_run(run_dir, "prospective")

            result = generate_branch(run_dir, renderer_available=False)

            self.assertEqual(gate(result, "prs_xml")["status"], "pass")
            xml_path = run_dir / "output" / "study.xml"
            root = ElementTree.parse(xml_path).getroot()
            self.assertTrue(root.tag)
            self.assertIn("Agent QX", xml_path.read_text(encoding="utf-8"))

    def test_missing_optional_prs_values_stay_nonblocking(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            reference = build_run(run_dir, "prospective")
            for optional in ("collaborator_agency", "enrollment_type", "start_date_type"):
                reference["regulatory"]["prs"].pop(optional, None)
            write_reference(run_dir, reference)

            result = generate_branch(run_dir, renderer_available=False)

            self.assertTrue(result["delivery_ready"], result["gates"])
            self.assertEqual(gate(result, "prs_xml")["status"], "pass")

    def test_unresolved_icf_template_choice_blocks_intake(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            reference = build_run(run_dir, "prospective")
            reference["meta"]["icf_template"] = None
            write_reference(run_dir, reference)

            result = generate_branch(run_dir, renderer_available=False)

            self.assertFalse(result["delivery_ready"])
            required = gate(result, "required_inputs")
            self.assertIn(
                "meta.icf_template", [item["field"] for item in required["findings"]]
            )
            self.assertEqual(result["artifacts"], {})

    def test_available_renderer_failures_prevent_delivery(self) -> None:
        def failing_exporter(docx_path: Path, pdf_path: Path) -> dict:
            return {"status": "error", "message": "renderer crashed"}

        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            build_run(run_dir, "prospective")

            result = generate_branch(
                run_dir, renderer_available=True, exporter=failing_exporter
            )

            visual = gate(result, "visual_qa")
            self.assertEqual(visual["status"], "fail")
            self.assertFalse(result["delivery_ready"])
            self.assertIn("renderer crashed", " ".join(item["issue"] for item in visual["findings"]))

    def test_static_toc_mismatches_prevent_delivery(self) -> None:
        def exporter(docx_path: Path, pdf_path: Path) -> dict:
            pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
            return {"status": "exported", "renderer": "stub"}

        def auditor(docx_path: Path, pdf_path: Path) -> dict:
            return {
                "entry_count": 12,
                "mismatch_count": 2,
                "alignment_mismatch_count": 1,
                "missing_count": 0,
            }

        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            build_run(run_dir, "prospective")

            result = generate_branch(
                run_dir, renderer_available=True, exporter=exporter, toc_auditor=auditor
            )

            visual = gate(result, "visual_qa")
            self.assertEqual(visual["status"], "fail")
            self.assertFalse(result["delivery_ready"])
            issues = " ".join(item["issue"] for item in visual["findings"])
            self.assertIn("2 page mismatches", issues)
            self.assertIn("1 alignment mismatches", issues)

    def test_installed_but_unusable_renderer_stays_nonblocking(self) -> None:
        """`pages_available()` only proves the app exists, not that it can export."""

        def unavailable_exporter(docx_path: Path, pdf_path: Path) -> dict:
            return {
                "status": "unavailable",
                "message": "No usable DOCX-to-PDF renderer was found.",
                "attempts": [{"renderer": "pages", "available": True, "success": False}],
            }

        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            build_run(run_dir, "prospective")

            result = generate_branch(
                run_dir, renderer_available=True, exporter=unavailable_exporter
            )

            visual = gate(result, "visual_qa")
            self.assertEqual(visual["status"], "skipped")
            self.assertFalse(visual["blocking"])
            self.assertTrue(result["delivery_ready"], result["gates"])
            evidence = json.loads((run_dir / "logs" / "visual-qa.json").read_text())
            self.assertEqual(evidence["status"], "unavailable")
            self.assertTrue(evidence["limitations"], "the skipped QA must be disclosed")

    def test_result_records_the_document_set_and_every_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            build_run(run_dir, "prospective")

            result = generate_branch(run_dir, renderer_available=False)

            recorded = [item["gate"] for item in result["gates"]]
            self.assertEqual(
                recorded,
                [
                    "approval",
                    "required_inputs",
                    "branch_mapping",
                    "placeholders",
                    "content_completeness",
                    "visit_table",
                    "prs_xml",
                    "stale_content",
                    "visual_qa",
                ],
            )
            saved = json.loads((run_dir / "logs" / "branch-generation.json").read_text())
            self.assertEqual(saved["document_set"], result["document_set"])
            self.assertEqual(saved["artifacts"], result["artifacts"])
            self.assertEqual(
                [item["gate"] for item in saved["gates"]], recorded
            )


class AmbispectiveBranchTests(unittest.TestCase):
    def test_approved_fixture_generates_the_complete_default_set(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            build_run(run_dir, "ambispective")

            result = generate_branch(run_dir, renderer_available=False)

            self.assertEqual(result["branch"], "Ambispective")
            self.assertEqual(
                sorted(result["artifacts"]), ["icf_docx", "protocol_docx", "xml"]
            )
            self.assertTrue(result["delivery_ready"], result["gates"])
            self.assertEqual(gate(result, "prs_xml")["status"], "pass")

    def test_protocol_separates_historical_from_prospective_activity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            build_run(run_dir, "ambispective")

            generate_branch(run_dir, renderer_available=False)

            text = docx_text(run_dir / "output" / "protocol.docx")
            self.assertIn("historical data collection phase", text)
            self.assertIn("Historical data are abstracted", text)
            self.assertIn("prospective phase enrolls participants", text)
            self.assertIn("Prospective visits, procedures, and follow-up", text)

    def test_endpoints_identify_how_evidence_is_collected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            build_run(run_dir, "ambispective")

            generate_branch(run_dir, renderer_available=False)

            xml = (run_dir / "output" / "study.xml").read_text(encoding="utf-8")
            self.assertIn("Historical baseline to prospective week 12", xml)
            self.assertIn("collected prospectively", xml)

    def test_icf_uses_prospective_language_without_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            build_run(run_dir, "ambispective")

            generate_branch(run_dir, renderer_available=False)

            icf_path = run_dir / "output" / "icf.docx"
            icf = docx_text(icf_path)
            self.assertIn("come to the clinic for seven visits", icf)
            self.assertEqual(unresolved_in_docx(icf_path), [])

    def test_shared_required_inputs_match_the_prospective_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            reference = build_run(run_dir, "ambispective")
            reference["design"]["intervention_name"] = None
            write_reference(run_dir, reference)

            result = generate_branch(run_dir, renderer_available=False)

            self.assertFalse(result["delivery_ready"])
            self.assertIn(
                "design.intervention_name",
                [item["field"] for item in gate(result, "required_inputs")["findings"]],
            )


if __name__ == "__main__":
    unittest.main()
