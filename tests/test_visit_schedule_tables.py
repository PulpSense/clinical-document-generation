"""Prospective and ambispective visit schedules are Data-Driven Tables.

A visit schedule must become one real Word row per visit. Newline-packing every
visit into a single body row renders as one unreadable cell and is the defect
these tests exist to prevent from returning.
"""

from __future__ import annotations

import html
import re
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from branch_fixtures import BUNDLED_DOCX, build_run


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from generate_branch_documents import generate_branch  # noqa: E402
from validate_template_contract import (  # noqa: E402
    LEGACY_VISIT_PLACEHOLDERS,
    bundled_template_findings,
    visit_table_findings,
)


ROW_RE = re.compile(r"<w:tr\b[^>]*>.*?</w:tr>", re.DOTALL)
TABLE_RE = re.compile(r"<w:tbl>.*?</w:tbl>", re.DOTALL)
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def visible(fragment: str) -> str:
    return "".join(
        html.unescape(match.group(1))
        for match in re.finditer(r"<w:t\b[^>]*>(.*?)</w:t>", fragment, re.DOTALL)
    )


def document_xml(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        return archive.read("word/document.xml").decode()


def visit_table_rows(path: Path) -> list[str]:
    """Rows of the table that carries the visit schedule."""
    xml = document_xml(path)
    for table in TABLE_RE.findall(xml):
        rows = ROW_RE.findall(table)
        if not rows:
            continue
        header = visible(rows[0]).replace(" ", "").lower()
        if "visitwindow" in header and "crf" in header:
            return rows
    raise AssertionError("No visit schedule table was found in the document.")


class RenderedVisitTableTests(unittest.TestCase):
    def assert_seven_real_rows(self, branch: str) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            build_run(run_dir, branch, visit_count=7)

            result = generate_branch(run_dir, renderer_available=False)
            self.assertTrue(result["delivery_ready"], result["gates"])

            rows = visit_table_rows(run_dir / "output" / "protocol.docx")
            self.assertEqual(len(rows), 8, "one header row plus seven visit rows")

            body = [visible(row) for row in rows[1:]]
            self.assertIn("Screening", body[0])
            self.assertIn("End of Study", body[6])
            for index, text in enumerate(body, start=1):
                self.assertIn(str(index), text)

    def test_seven_visit_prospective_fixture_renders_seven_rows(self) -> None:
        self.assert_seven_real_rows("prospective")

    def test_seven_visit_ambispective_fixture_renders_seven_rows(self) -> None:
        self.assert_seven_real_rows("ambispective")

    def test_visit_values_are_not_newline_packed_into_one_row(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            build_run(run_dir, "prospective", visit_count=7)
            generate_branch(run_dir, renderer_available=False)

            for row in visit_table_rows(run_dir / "output" / "protocol.docx"):
                text = visible(row)
                packed = [name for name in ("Screening", "End of Study") if name in text]
                self.assertLessEqual(
                    len(packed), 1, f"visits were packed into one row: {text!r}"
                )

    def test_visit_count_drives_the_row_count(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            build_run(run_dir, "prospective", visit_count=3)
            generate_branch(run_dir, renderer_available=False)

            rows = visit_table_rows(run_dir / "output" / "protocol.docx")
            self.assertEqual(len(rows), 4)

    def test_generated_rows_keep_usable_table_geometry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            build_run(run_dir, "prospective", visit_count=7)
            generate_branch(run_dir, renderer_available=False)

            rows = visit_table_rows(run_dir / "output" / "protocol.docx")
            header, body = rows[0], rows[1:]

            self.assertIn("<w:tblHeader", header, "the header row must repeat on each page")
            for row in body:
                self.assertNotIn(
                    "<w:tblHeader", row, "a visit row must not repeat as a page header"
                )
                self.assertIn("<w:cantSplit", row, "a visit row must not split across pages")
                self.assertEqual(
                    len(re.findall(r"<w:tcW\b", row)),
                    len(re.findall(r"<w:tcW\b", header)),
                    "every visit row keeps the header's column widths",
                )


class BundledTemplateContractTests(unittest.TestCase):
    def test_bundled_protocol_templates_use_repeated_row_visit_blocks(self) -> None:
        for name in ("prospective-protocol.template.docx", "ambispective-protocol.template.docx"):
            with self.subTest(template=name):
                template = BUNDLED_DOCX / name
                self.assertEqual(visit_table_findings(template), [])
                xml = document_xml(template)
                self.assertIn("{#visits}", xml)
                self.assertIn("{/visits}", xml)

    def test_every_bundled_template_passes_the_contract(self) -> None:
        self.assertEqual(bundled_template_findings(), [])

    def test_legacy_scalar_visit_placeholders_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            template = Path(temporary) / "legacy-protocol.template.docx"
            write_legacy_visit_template(template)

            findings = visit_table_findings(template)

            self.assertTrue(findings)
            reported = {item["placeholder"] for item in findings}
            self.assertTrue(reported & LEGACY_VISIT_PLACEHOLDERS, reported)


def write_legacy_visit_template(path: Path) -> None:
    """A protocol template still packing visits into one scalar row."""
    header = (
        "<w:tr><w:tc><w:p><w:r><w:t>Visit Number</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>Visit Name</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>Visit Window</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>CRF Number</w:t></w:r></w:p></w:tc></w:tr>"
    )
    body = (
        "<w:tr><w:tc><w:p><w:r><w:t>{AI_visitNumber}</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>{AI_visitName}</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>{AI_visitWindow}</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>{AI_CRFnumber}</w:t></w:r></w:p></w:tc></w:tr>"
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{WORD_NS}"><w:body><w:tbl>{header}{body}</w:tbl>'
        "<w:p><w:r><w:t>{AI_introduction}</w:t></w:r></w:p>"
        "</w:body></w:document>"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", document)


class LegacyFallbackDeliveryGateTests(unittest.TestCase):
    def test_legacy_string_fallback_fails_the_delivery_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            build_run(run_dir, "prospective", visit_count=7)
            # Swap in a template that still consumes the scalar compatibility fields.
            write_legacy_visit_template(run_dir / "templates" / "protocol.template.docx")

            result = generate_branch(run_dir, renderer_available=False)

            self.assertFalse(result["delivery_ready"])
            visit_gate = [g for g in result["gates"] if g["gate"] == "visit_table"][0]
            self.assertEqual(visit_gate["status"], "fail")
            self.assertTrue(visit_gate["findings"])
            report = (run_dir / result["repair_report"]).read_text(encoding="utf-8")
            self.assertIn("visit_table", report)

    def test_retrospective_branch_has_no_visit_table_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            build_run(run_dir, "retrospective")

            result = generate_branch(run_dir, renderer_available=False)

            visit_gate = [g for g in result["gates"] if g["gate"] == "visit_table"][0]
            self.assertEqual(visit_gate["status"], "skipped")
            self.assertTrue(result["delivery_ready"], result["gates"])


if __name__ == "__main__":
    unittest.main()
