"""Table 15.1 is a Data-Driven Table, not an empty caption.

`{visitsTable}` is a structural placeholder: the reference contract removes it
and inserts a real table in its place. Resolving it to an empty string leaves
section 15 as a caption followed by nothing, which every placeholder-based gate
happily accepts because the token did resolve. These tests pin the rendered
structure and the gate that refuses to deliver an empty structural section.
"""

from __future__ import annotations

import html
import json
import re
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from branch_fixtures import build_run


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from build_n8n_prospective_fields import build_fields  # noqa: E402
from generate_branch_documents import generate_branch  # noqa: E402
from render_templates import render_docx  # noqa: E402
from validate_template_contract import (  # noqa: E402
    STRUCTURAL_TABLE_PLACEHOLDER,
    bundled_template_findings,
    missing_structural_table_findings,
)


ROW_RE = re.compile(r"<w:tr\b[^>]*>.*?</w:tr>", re.DOTALL)
CELL_RE = re.compile(r"<w:tc>.*?</w:tc>", re.DOTALL)
TABLE_RE = re.compile(r"<w:tbl>.*?</w:tbl>", re.DOTALL)
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

ASSESSMENT_CAPTION = "Table 15.1. Proposed Visits and Study Assessments"


def visible(fragment: str) -> str:
    return "".join(
        html.unescape(match.group(1))
        for match in re.finditer(r"<w:t\b[^>]*>(.*?)</w:t>", fragment, re.DOTALL)
    )


def document_xml(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        return archive.read("word/document.xml").decode()


def write_docx(path: Path, body: str) -> None:
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{WORD_NS}"><w:body>{body}</w:body></w:document>'
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document)


def paragraph(text: str) -> str:
    return f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"


def matrix(columns: int, rows: int, cells: list[str]) -> dict:
    return {"cells": cells, "totalColumns": columns, "totalRows": rows}


def rendered_table(cells: list[str], *, columns: int, rows: int) -> str:
    """Render a lone `{visitsTable}` paragraph and return the document XML."""
    with tempfile.TemporaryDirectory() as temporary:
        template = Path(temporary) / "template.docx"
        output = Path(temporary) / "output.docx"
        write_docx(template, paragraph("{visitsTable}"))

        render_docx(template, output, {"visitsTable": matrix(columns, rows, cells)})

        return document_xml(output)


def table_after_caption(path: Path, caption: str) -> str | None:
    """The first table that follows `caption` in document order."""
    xml = document_xml(path)
    # The caption also appears in the table of contents, so take its last
    # occurrence: the one in the body, after the TOC.
    index = xml.rfind(caption)
    if index < 0:
        return None
    match = TABLE_RE.search(xml, index)
    return match.group(0) if match else None


class MatrixTableRenderingTests(unittest.TestCase):
    def test_a_matrix_placeholder_becomes_a_real_word_table(self) -> None:
        xml = rendered_table(
            ["Visit", "Assessments", "1", "Symptom score", "2", "Vital signs"],
            columns=2,
            rows=3,
        )

        tables = TABLE_RE.findall(xml)
        self.assertEqual(len(tables), 1, "the placeholder must become one table")
        rows = ROW_RE.findall(tables[0])
        self.assertEqual(len(rows), 3)
        self.assertEqual(
            [[visible(c).strip() for c in CELL_RE.findall(row)] for row in rows],
            [["Visit", "Assessments"], ["1", "Symptom score"], ["2", "Vital signs"]],
        )

    def test_the_placeholder_paragraph_does_not_survive(self) -> None:
        xml = rendered_table(["A", "B"], columns=2, rows=1)

        self.assertNotIn("{visitsTable}", visible(xml))
        self.assertNotIn("visitsTable", visible(xml))

    def test_header_row_repeats_and_body_rows_do_not(self) -> None:
        xml = rendered_table(["H1", "H2", "a", "b"], columns=2, rows=2)

        rows = ROW_RE.findall(TABLE_RE.findall(xml)[0])
        self.assertIn("<w:tblHeader", rows[0], "the header row must repeat across pages")
        self.assertNotIn("<w:tblHeader", rows[1], "body rows must not repeat as headers")

    def test_matrix_cells_are_escaped(self) -> None:
        xml = rendered_table(["Dose & route", "<not a tag>"], columns=2, rows=1)

        cells = [visible(c).strip() for c in CELL_RE.findall(TABLE_RE.findall(xml)[0])]
        self.assertEqual(cells, ["Dose & route", "<not a tag>"])
        self.assertIn("&amp;", xml)

    def test_a_short_final_row_is_padded_to_the_column_count(self) -> None:
        """A ragged matrix must still produce a rectangular table."""
        xml = rendered_table(["H1", "H2", "only one"], columns=2, rows=2)

        rows = ROW_RE.findall(TABLE_RE.findall(xml)[0])
        self.assertEqual([len(CELL_RE.findall(row)) for row in rows], [2, 2])


class AssessmentMatrixMappingTests(unittest.TestCase):
    def reference(self) -> dict:
        with tempfile.TemporaryDirectory() as temporary:
            return build_run(Path(temporary), "prospective")

    def test_a_matrix_is_derived_from_the_visit_schedule(self) -> None:
        """No Required Source Input carries an assessments matrix, so the
        table is built from the visit schedule the branch already has."""
        fields = build_fields(self.reference())

        table = fields["visitsTable"]
        self.assertIsInstance(table, dict)
        self.assertEqual(table["totalRows"], 8, "one header row plus seven visits")
        self.assertEqual(len(table["cells"]), table["totalRows"] * table["totalColumns"])
        header = table["cells"][: table["totalColumns"]]
        self.assertIn("Assessments", header)
        self.assertIn("Screening", table["cells"])

    def test_a_generated_matrix_is_used_verbatim(self) -> None:
        reference = self.reference()
        reference["generated"]["protocol"]["visitsTable"] = matrix(
            2, 2, ["Visit", "Assessment", "1", "Fundus photography"]
        )

        table = build_fields(reference)["visitsTable"]

        self.assertEqual(table["totalColumns"], 2)
        self.assertEqual(table["totalRows"], 2)
        self.assertIn("Fundus photography", table["cells"])

    def test_a_study_without_assessment_detail_still_produces_a_table(self) -> None:
        reference = self.reference()
        reference["procedures"].pop("assessments", None)
        reference["generated"]["protocol"].pop("measurements", None)

        table = build_fields(reference)["visitsTable"]

        self.assertTrue(table["cells"], "the section must never render empty")
        self.assertEqual(table["totalRows"], 8)


class StructuralTableGateTests(unittest.TestCase):
    def test_an_empty_structural_table_prevents_delivery(self) -> None:
        """A generated matrix of blank cells still resolves the placeholder.

        Every Required Source Input is satisfied here, so nothing upstream
        objects; only a gate that looks at the table's contents can stop a
        protocol whose section 15 is a caption over an empty grid.
        """
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            reference = build_run(run_dir, "prospective")
            reference["generated"]["protocol"]["visitsTable"] = matrix(
                2, 2, ["", "   ", "", ""]
            )
            (run_dir / "reference" / "study.reference.json").write_text(
                json.dumps(reference), encoding="utf-8"
            )

            result = generate_branch(run_dir, renderer_available=False)

            self.assertFalse(result["delivery_ready"], result["gates"])
            structural = [g for g in result["gates"] if g["gate"] == "structural_tables"]
            self.assertTrue(structural, "the branch must run a structural table gate")
            self.assertEqual(structural[0]["status"], "fail")
            self.assertEqual(
                structural[0]["findings"][0]["section"], ASSESSMENT_CAPTION
            )
            report = (run_dir / "logs" / "repair-report.md").read_text(encoding="utf-8")
            self.assertIn(ASSESSMENT_CAPTION, report)

    def test_a_populated_structural_table_passes_the_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            build_run(run_dir, "prospective")

            result = generate_branch(run_dir, renderer_available=False)

            structural = [g for g in result["gates"] if g["gate"] == "structural_tables"]
            self.assertEqual(structural[0]["status"], "pass")

    def test_retrospective_declares_no_structural_tables(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            build_run(run_dir, "retrospective")

            result = generate_branch(run_dir, renderer_available=False)

            self.assertTrue(result["delivery_ready"], result["gates"])
            structural = [g for g in result["gates"] if g["gate"] == "structural_tables"]
            self.assertEqual(structural[0]["status"], "skipped")


class RenderedAssessmentTableTests(unittest.TestCase):
    def assert_section_15_carries_a_table(self, branch: str) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            build_run(run_dir, branch, visit_count=7)

            result = generate_branch(run_dir, renderer_available=False)
            self.assertTrue(result["delivery_ready"], result["gates"])

            protocol = run_dir / "output" / "protocol.docx"
            table = table_after_caption(protocol, ASSESSMENT_CAPTION)
            self.assertIsNotNone(table, "section 15 must carry a real table")
            rows = ROW_RE.findall(table)
            self.assertEqual(len(rows), 8, "one header row plus seven visits")
            self.assertIn("Assessments", visible(rows[0]))
            self.assertIn("Screening", visible(rows[1]))

    def test_prospective_section_15_carries_a_real_table(self) -> None:
        self.assert_section_15_carries_a_table("prospective")

    def test_ambispective_section_15_carries_a_real_table(self) -> None:
        self.assert_section_15_carries_a_table("ambispective")

    def test_the_visit_schedule_table_stays_distinct(self) -> None:
        """Table 9.2-1 keeps its own four-column shape; 15.1 is not a copy."""
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            build_run(run_dir, "prospective", visit_count=7)

            generate_branch(run_dir, renderer_available=False)

            xml = document_xml(run_dir / "output" / "protocol.docx")
            tables = TABLE_RE.findall(xml)
            schedule = [t for t in tables if "Visit Window" in visible(t)]
            self.assertTrue(schedule, "the visit schedule table must still exist")
            self.assertEqual(len(ROW_RE.findall(schedule[0])), 8)
            self.assertEqual(
                len(CELL_RE.findall(ROW_RE.findall(schedule[0])[1])),
                4,
                "the visit schedule keeps its four columns",
            )

    def test_retrospective_has_no_assessment_table(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            build_run(run_dir, "retrospective")

            generate_branch(run_dir, renderer_available=False)

            protocol = run_dir / "output" / "protocol.docx"
            self.assertIsNone(table_after_caption(protocol, ASSESSMENT_CAPTION))


class TemplateContractTests(unittest.TestCase):
    """The gate proves the data is right; this proves the template still uses it."""

    def test_bundled_templates_still_carry_the_structural_placeholder(self) -> None:
        self.assertEqual(bundled_template_findings(), [])

    def test_a_template_that_dropped_the_placeholder_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            template = Path(temporary) / "protocol.template.docx"
            write_docx(template, paragraph("15. STANDARD EVALUATION PROCEDURES"))

            findings = missing_structural_table_findings(template)

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0]["placeholder"], STRUCTURAL_TABLE_PLACEHOLDER)

    def test_a_template_that_keeps_the_placeholder_is_clean(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            template = Path(temporary) / "protocol.template.docx"
            write_docx(template, paragraph("{visitsTable}"))

            self.assertEqual(missing_structural_table_findings(template), [])


if __name__ == "__main__":
    unittest.main()
