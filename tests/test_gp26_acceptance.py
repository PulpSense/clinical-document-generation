from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from audit_static_toc import audit  # noqa: E402
from complete_protocol import protocol_completeness_missing  # noqa: E402
from delivery_gates import audit_docx_package, audit_gp26_visual_acceptance, audit_protocol_structure  # noqa: E402
from export_docx_to_pdf import export_docx  # noqa: E402
from refresh_static_toc import refresh_docx  # noqa: E402
from render_templates import run_generation, visible_text_from_word_xml  # noqa: E402


FIXTURE = REPO_ROOT / "tests/fixtures/gp-26-01-approved.json"
PROTOCOL_TEMPLATE = REPO_ROOT / "assets/client-templates/docx/prospective-protocol.template.docx"


class GP26AcceptanceTest(unittest.TestCase):
    def _prepare_run(self, run_dir: Path, reference: dict) -> Path:
        shutil.copyfile(PROTOCOL_TEMPLATE, run_dir / "templates/protocol.template.docx")
        reference_path = run_dir / "reference/study.reference.json"
        reference_path.parent.mkdir(parents=True, exist_ok=True)
        reference_path.write_text(json.dumps(reference), encoding="utf-8")
        return reference_path

    def test_incomplete_approved_reference_cannot_be_delivered(self) -> None:
        reference = json.loads(FIXTURE.read_text(encoding="utf-8"))
        del reference["population"]["sample_justification"]

        with tempfile.TemporaryDirectory(prefix="gp-26-01-incomplete-") as temporary:
            run_dir = Path(temporary)
            (run_dir / "templates").mkdir()
            reference_path = self._prepare_run(run_dir, reference)

            with self.assertRaisesRegex(ValueError, "Content Completeness Gate"):
                run_generation(run_dir, reference_path, require_approval=True)
            self.assertFalse((run_dir / "output/protocol.docx").exists())
            self.assertTrue((run_dir / "reference/repair-report.md").is_file())

    def test_approved_reference_runs_through_final_protocol_qa(self) -> None:
        reference = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(reference["meta"]["protocol_number"], "GP-26-01")
        self.assertEqual(reference["approval"]["status"], "approved")
        self.assertEqual(protocol_completeness_missing(reference), [])

        with tempfile.TemporaryDirectory(prefix="gp-26-01-acceptance-") as temporary:
            run_dir = Path(temporary)
            (run_dir / "templates").mkdir()
            reference_path = self._prepare_run(run_dir, reference)

            report = run_generation(run_dir, reference_path, require_approval=True)
            protocol_path = run_dir / "output/protocol.docx"
            self.assertEqual(report["approval_status"], "approved")
            self.assertEqual(report["delivery_gates"]["status"], "passed")
            self.assertEqual(report["unresolved_output_placeholders"]["output/protocol.docx"], [])
            self.assertFalse((run_dir / "reference/repair-report.md").exists())
            self.assertTrue(protocol_path.is_file())

            persisted = json.loads(reference_path.read_text(encoding="utf-8"))
            section18 = {
                section["number"]: section["paragraphs"]
                for section in persisted["generated"]["protocol"]["sections"]
                if section["number"].startswith("18")
            }
            self.assertEqual(set(section18), {"18.", "18.1.", "18.2.", "18.3.", "18.4.", "18.5."})
            self.assertTrue(all(paragraphs and any(text.strip() for text in paragraphs) for paragraphs in section18.values()))

            package_errors = audit_docx_package(protocol_path)
            structure_errors = audit_protocol_structure(protocol_path)
            self.assertEqual(package_errors, [])
            self.assertEqual(structure_errors, [])
            self.assertEqual(audit_gp26_visual_acceptance(protocol_path), [])
            self.assertLess(protocol_path.stat().st_size, 5 * 1024 * 1024)

            with zipfile.ZipFile(protocol_path) as archive:
                self.assertFalse(any(name.startswith("word/fonts/") for name in archive.namelist()))
                document_xml = archive.read("word/document.xml").decode("utf-8")
                package_text = "\n".join(
                    visible_text_from_word_xml(archive.read(name).decode("utf-8", errors="ignore"))
                    for name in archive.namelist()
                    if name.startswith("word/") and name.endswith(".xml")
                )
            visible_text = visible_text_from_word_xml(document_xml)

            for required in (
                "GP-26-01",
                "21 Aug 2026",
                "5. INTRODUCTION",
                "6. OBJECTIVE(S)",
                "8. STUDY DESIGN",
                "11. SAMPLE SIZE JUSTIFICATION",
                "15. STANDARD EVALUATION PROCEDURES",
                "17. FINANCIAL AND INSURANCE INFORMATION/STUDY RELATED INJURIES",
                "19. SUMMARY OF RISKS AND BENEFITS",
                "Table 15.1 Proposed Visits and Study Assessments",
                "Month 1 Telephone Follow-up",
                "Month 3 Clinic Follow-up",
                "Day 90 +/- 7",
                "CRF Number",
                "SCR/BL",
            ):
                self.assertIn(required, package_text, required)
            self.assertNotRegex(visible_text, r"(?i)\b(?:draft|todo|tbd|needs review|internal only)\b")
            title_page = visible_text.split("2. INVESTIGATOR AGREEMENT", 1)[0]
            self.assertEqual(title_page.count("PulpSense Clinical Research"), 1)
            self.assertEqual(title_page.count("Example City"), 2)  # IRB and sponsor addresses
            self.assertEqual(title_page.count("Example Institutional Review Board"), 1)

            pdf_path = run_dir / "logs/docx-render/protocol.pdf"
            renderer_report, renderer_code = export_docx(protocol_path, pdf_path)
            if renderer_report["status"] == "unavailable":
                self.assertEqual(renderer_code, 0)
                self.assertEqual(renderer_report["status"], "unavailable")
                return

            self.assertEqual(renderer_code, 0)
            refreshed = refresh_docx(protocol_path, pdf_path, protocol_path)
            self.assertIn(refreshed["alignment"], {"right_tab_with_dot_leader"})
            second_report, second_code = export_docx(protocol_path, pdf_path)
            self.assertEqual(second_code, 0)
            self.assertEqual(second_report["status"], "exported")
            toc_report = audit(protocol_path, pdf_path)
            self.assertEqual(toc_report["mismatch_count"], 0, toc_report)
            self.assertEqual(toc_report["missing_count"], 0, toc_report)
            self.assertEqual(toc_report["alignment_mismatch_count"], 0, toc_report)


if __name__ == "__main__":
    unittest.main()
