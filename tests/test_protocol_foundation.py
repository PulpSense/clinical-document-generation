from __future__ import annotations

import sys
import tempfile
import zipfile
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from protocol_document import (  # noqa: E402
    build_protocol_model,
    render_protocol_docx,
    validate_data_driven_table,
)
from complete_protocol import build_complete_protocol, protocol_completeness_missing  # noqa: E402
from delivery_gates import audit_docx_package, audit_protocol_structure  # noqa: E402


class ProtocolFoundationTests(unittest.TestCase):
    def reference(self) -> dict:
        return {
            "meta": {"protocol_number": "P-001", "version": "1.0", "date": "20 Aug 2026"},
            "study": {"title": "Structured Study", "short_title": "Structured Study"},
            "generated": {
                "protocol": {
                    "sections": [
                        {
                            "number": "1.",
                            "title": "Introduction",
                            "paragraphs": ["The approved protocol introduction."],
                            "lists": [["First criterion", "Second criterion"]],
                        }
                    ]
                }
            },
            "template_fields": {
                "data_driven_tables": {
                    "visit_schedule": {
                        "columns": [
                            {"key": "visitNumber", "label": "Visit Number"},
                            {"key": "visitName", "label": "Visit Name"},
                        ],
                        "rows": [
                            {"visitNumber": "1", "visitName": "Screening"},
                        ],
                    }
                }
            },
        }

    def test_model_keeps_structured_sections_and_validates_table_contract(self) -> None:
        model = build_protocol_model(self.reference())
        self.assertEqual(model["sections"][0]["title"], "Introduction")
        self.assertEqual(validate_data_driven_table(model["tables"][0]), [])
        self.assertEqual(model["tables"][0]["rows"][0]["visitName"], "Screening")

    def test_invalid_table_reports_schema_and_row_errors(self) -> None:
        table = {
            "columns": [{"key": "visitNumber", "label": "Visit Number"}],
            "rows": [{"visitName": "Screening"}],
        }
        errors = validate_data_driven_table(table)
        self.assertTrue(any("missing required key" in error for error in errors))

    def test_render_removes_embedded_fonts_and_inserts_real_constructs(self) -> None:
        template = REPO_ROOT / "assets/client-templates/docx/prospective-protocol.template.docx"
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "protocol.docx"
            report = render_protocol_docx(template, output, self.reference())
            self.assertEqual(report["unresolved_placeholders"], [])
            self.assertEqual(report["embedded_fonts"], [])
            self.assertTrue(report["legacy_body_removed"])
            with zipfile.ZipFile(output) as archive:
                names = set(archive.namelist())
                document = archive.read("word/document.xml").decode("utf-8")
                self.assertFalse(any(name.startswith("word/fonts/") for name in names))
                self.assertIn("Structured Study", document)
                self.assertIn("Screening", document)
                self.assertIn("w:tblLayout w:type=\"fixed\"", document)
                self.assertIn("w:tblHeader", document)
                self.assertIn("w:tblBorders", document)
                self.assertIn('w:val="single"', document)
                self.assertIn('w:keepNext', document)
                self.assertIn('w:gridCol w:w="1000"', document)
                self.assertIn("w:numPr", document)
                self.assertLess(document.index("Screening"), document.index("<w:sectPr"))

    def test_schedule_table_uses_readable_visit_geometry_and_preserves_all_rows(self) -> None:
        reference = self.complete_reference()
        reference["generated"]["protocol"]["sections"] = build_complete_protocol(reference)["sections"]
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "protocol.docx"
            render_protocol_docx(
                REPO_ROOT / "assets/client-templates/docx/prospective-protocol.template.docx",
                output,
                reference,
            )
            with zipfile.ZipFile(output) as archive:
                document = archive.read("word/document.xml").decode("utf-8")
            self.assertEqual(document.count("<w:tblBorders>"), 2)
            self.assertGreaterEqual(document.count('<w:tblHeader w:val="true"'), 2)
            self.assertGreaterEqual(document.count("<w:cantSplit/>"), 6)
            self.assertEqual(document.count("w:tcW w:w=\"1000\""), 3)
            self.assertIn("Screening", document)
            self.assertIn("Month 3", document)
            self.assertIn("Day 90 +/- 7", document)

    def test_structured_body_replaces_legacy_sections_once(self) -> None:
        reference = self.complete_reference()
        reference["generated"]["protocol"]["sections"] = build_complete_protocol(reference)["sections"]
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "protocol.docx"
            render_protocol_docx(
                REPO_ROOT / "assets/client-templates/docx/prospective-protocol.template.docx",
                output,
                reference,
            )
            with zipfile.ZipFile(output) as archive:
                document = archive.read("word/document.xml").decode("utf-8")
            self.assertEqual(document.count('<w:t xml:space="preserve">8. STUDY DESIGN</w:t>'), 1)
            self.assertEqual(document.count('<w:t xml:space="preserve">9. STUDY PROCEDURE</w:t>'), 1)
            self.assertEqual(document.count('<w:t xml:space="preserve">15. STANDARD EVALUATION PROCEDURES</w:t>'), 1)
            self.assertEqual(document.count('<w:t xml:space="preserve">19. SUMMARY OF RISKS AND BENEFITS</w:t>'), 1)
            self.assertIn("8. STUDY DESIGN ................................", document)
            self.assertNotIn("Table 9.2-1. Visit Schedule", document)
            self.assertIn("1. TITLE PAGE", document)
            self.assertIn("2. INVESTIGATOR AGREEMENT", document)
            self.assertIn("3. GENERAL INFORMATION", document)
            self.assertIn("4. TABLE OF CONTENTS", document)

    def complete_reference(self) -> dict:
        reference = self.reference()
        reference.update(
            {
                "study": {
                    "title": "Complete Approved Study",
                    "background": "The approved study background.",
                    "hypothesis": "The approved study hypothesis.",
                },
                "objectives": {"primary": "Evaluate the primary endpoint."},
                "population": {
                    "inclusion_criteria": ["Adults meeting the approved criteria."],
                    "exclusion_criteria": ["Participants with the approved exclusion."],
                    "sample_size": "80 participants",
                    "sample_justification": "The sample supports descriptive estimation and expected attrition.",
                },
                "design": {"study_design": "Prospective single-arm observational study."},
                "endpoints": {"primary": "Change in the approved primary outcome by Month 3."},
                "procedures": {
                    "assessments": "Screening, baseline, and Month 3 assessments.",
                    "visit_schedule_table": [
                        {"visitNumber": "1", "visitName": "Screening", "visitWindow": "Day -30 to Day 0", "CRFnumber": "SCR"},
                        {"visitNumber": "2", "visitName": "Month 3", "visitWindow": "Day 90 +/- 7", "CRFnumber": "M3"},
                    ],
                },
                "generated": {
                    "protocol": {
                        "introduction": "The approved introduction.",
                        "visitScheduleTable": [
                            {"visitNumber": "1", "visitName": "Screening", "visitWindow": "Day -30 to Day 0", "CRFnumber": "SCR"},
                            {"visitNumber": "2", "visitName": "Month 3", "visitWindow": "Day 90 +/- 7", "CRFnumber": "M3"},
                        ],
                        "sampleSizeJustification": "The sample supports descriptive estimation.",
                        "risks": "The approved safety language.",
                        "benefits": "The approved benefits language.",
                    }
                },
            }
        )
        return reference

    def test_complete_protocol_preserves_required_sections_and_tables(self) -> None:
        reference = self.complete_reference()
        self.assertEqual(protocol_completeness_missing(reference), [])
        protocol = build_complete_protocol(reference)
        titles = {section["title"] for section in protocol["sections"]}
        self.assertIn("STANDARD EVALUATION PROCEDURES", titles)
        self.assertIn("SAMPLE SIZE JUSTIFICATION", titles)
        schedule_section = next(section for section in protocol["sections"] if section["number"] == "15.")
        self.assertEqual(schedule_section["tables"][0]["caption"], "15.1 Proposed Visits and Study Assessments")
        self.assertEqual(len(schedule_section["tables"][0]["rows"]), 2)
        sample_section = next(section for section in protocol["sections"] if section["number"] == "11.")
        self.assertEqual(len(sample_section["tables"][0]["rows"]), 2)

        section18 = {
            section["number"]: section["paragraphs"]
            for section in protocol["sections"]
            if section["number"].startswith("18")
        }
        self.assertEqual(set(section18), {"18.", "18.1.", "18.2.", "18.3.", "18.4.", "18.5."})
        self.assertTrue(all(paragraphs and any(text.strip() for text in paragraphs) for paragraphs in section18.values()))

    def test_section18_blocks_when_final_follow_up_cannot_be_inferred(self) -> None:
        reference = self.complete_reference()
        del reference["generated"]["protocol"]["visitScheduleTable"]
        del reference["procedures"]["visit_schedule_table"]
        with self.assertRaisesRegex(ValueError, "final scheduled visit"):
            build_complete_protocol(reference)

    def test_primary_endpoint_dict_is_source_grounded(self) -> None:
        reference = self.complete_reference()
        reference["endpoints"]["primary"] = [{"label": "Change in pain score", "time_point": "Month 3"}]
        missing = protocol_completeness_missing(reference)
        self.assertFalse(any(item["field"] == "endpoints.primary" for item in missing))

    def test_complete_protocol_stops_when_source_detail_is_missing(self) -> None:
        reference = self.complete_reference()
        del reference["population"]["sample_justification"]
        missing = protocol_completeness_missing(reference)
        self.assertTrue(any(item["field"] == "population.sample_justification" for item in missing))
        with self.assertRaises(ValueError):
            build_complete_protocol(reference)

    def test_delivery_gate_accepts_complete_protocol_and_rejects_missing_table(self) -> None:
        reference = self.complete_reference()
        protocol = build_complete_protocol(reference)
        reference["generated"]["protocol"]["sections"] = protocol["sections"]
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "protocol.docx"
            render_protocol_docx(REPO_ROOT / "assets/client-templates/docx/prospective-protocol.template.docx", output, reference)
            self.assertEqual(audit_docx_package(output), [])
            self.assertEqual(audit_protocol_structure(output), [])

            broken = Path(temporary) / "broken.docx"
            with zipfile.ZipFile(output) as source, zipfile.ZipFile(broken, "w") as destination:
                for item in source.infolist():
                    data = source.read(item.filename)
                    if item.filename == "word/document.xml":
                        data = data.replace(b"15. STANDARD EVALUATION PROCEDURES", b"15. MISSING EVALUATION PROCEDURES")
                    destination.writestr(item, data)
            self.assertTrue(any("15. STANDARD EVALUATION PROCEDURES" in item["field"] for item in audit_protocol_structure(broken)))


if __name__ == "__main__":
    unittest.main()
