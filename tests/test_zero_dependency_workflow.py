from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from audit_static_toc import audit  # noqa: E402
from pdf_text import extract_pdf_pages  # noqa: E402
from refresh_static_toc import refresh_docx  # noqa: E402
from render_templates import (  # noqa: E402
    render_docx,
    render_xml,
    render_text_template,
    run_generation,
    unresolved_in_docx,
    visible_text_from_word_xml,
)
from scan_placeholders import scan_path  # noqa: E402


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def write_docx(path: Path, document_xml: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", document_xml)
        archive.writestr(
            "word/settings.xml",
            f'<w:settings xmlns:w="{WORD_NS}"></w:settings>',
        )


def write_pdf(path: Path, lines: list[str]) -> None:
    escaped_lines = [
        line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        for line in lines
    ]
    stream = "\n".join(
        f"BT /F1 12 Tf ({line}) Tj ET" for line in escaped_lines
    ).encode("cp1252")
    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Count 1 /Kids [3 0 R] >>\nendobj\n",
        (
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\nendobj\n"
        ),
        (
            b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            b"/Encoding /WinAnsiEncoding >>\nendobj\n"
        ),
        b"5 0 obj\n<< /Length "
        + str(len(stream)).encode()
        + b" >>\nstream\n"
        + stream
        + b"\nendstream\nendobj\n",
    ]
    path.write_bytes(b"%PDF-1.4\n" + b"".join(objects) + b"%%EOF\n")


class RendererTests(unittest.TestCase):
    def test_docx_renderer_handles_split_tokens_and_line_breaks(self) -> None:
        document = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{WORD_NS}"><w:body>
<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>{{study.</w:t></w:r><w:r><w:t>title}}</w:t></w:r></w:p>
<w:p><w:r><w:t>{{generated.summary}}</w:t></w:r></w:p>
<w:sectPr><w:pgSz w:w="12240"/><w:pgMar w:left="1440" w:right="1440"/></w:sectPr>
</w:body></w:document>'''
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            template = root / "template.docx"
            output = root / "output.docx"
            write_docx(template, document)
            unresolved = render_docx(
                template,
                output,
                {"study": {"title": "A & B"}, "generated": {"summary": "First\nSecond"}},
            )
            self.assertEqual(unresolved, [])
            with zipfile.ZipFile(output) as archive:
                xml = archive.read("word/document.xml").decode()
            self.assertIn("A &amp; B", xml)
            self.assertIn("<w:br/>", xml)
            self.assertIn("First\nSecond", visible_text_from_word_xml(xml))

    def test_all_bundled_docx_templates_render_without_placeholders(self) -> None:
        templates = sorted((REPO_ROOT / "assets/client-templates/docx").glob("*.docx"))
        self.assertTrue(templates)
        with tempfile.TemporaryDirectory() as temporary:
            output_root = Path(temporary)
            for template in templates:
                fields = {
                    token["name"]: "Line one\nLine two" if token["name"].startswith("AI_") else f"VALUE_{token['name']}"
                    for token in scan_path(template)
                    if token["kind"] == "variable"
                }
                output = output_root / template.name
                render_docx(template, output, fields)
                self.assertEqual(unresolved_in_docx(output), [], template.name)
                with zipfile.ZipFile(output) as archive:
                    self.assertIsNone(archive.testzip(), template.name)

    def test_text_renderer_supports_blocks_and_xml_escaping(self) -> None:
        template = "{#items}<x>{name}</x>{/items}{^missing}<empty/>{/missing}"
        rendered = render_text_template(
            template,
            {"items": [{"name": "A & B"}, {"name": "C"}], "missing": False},
        )
        self.assertEqual(rendered, "<x>A &amp; B</x><x>C</x><empty/>")

    def test_docx_renderer_repeats_table_rows(self) -> None:
        document = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{WORD_NS}"><w:body><w:tbl>
<w:tr><w:tc><w:p><w:r><w:t>{{#sites}}{{name}}{{/sites}}</w:t></w:r></w:p></w:tc></w:tr>
</w:tbl></w:body></w:document>'''
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            template = root / "template.docx"
            output = root / "output.docx"
            write_docx(template, document)
            render_docx(template, output, {"sites": [{"name": "Alpha"}, {"name": "Beta"}]})
            with zipfile.ZipFile(output) as archive:
                xml = archive.read("word/document.xml").decode()
            self.assertEqual(xml.count("<w:tr>"), 2)
            self.assertIn("Alpha", xml)
            self.assertIn("Beta", xml)

    def test_bundled_prs_xml_renders_with_repeated_blocks(self) -> None:
        template = REPO_ROOT / "assets/client-templates/prs/clinicaltrials_prs_full_placeholder_template.xml"
        fields = {
            token["name"]: True if token["kind"] == "block_start" else f"VALUE_{token['name']}"
            for token in scan_path(template)
            if token["kind"] in {"variable", "block_start"}
        }
        fields["__xml_profile"] = "clinicaltrials-prs"
        fields["__prs_counts"] = {
            "intervention": 3,
            "arm_group": 1,
            "primary_outcome": 1,
            "secondary_outcome": 2,
            "other_outcome": 2,
        }
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "study.xml"
            unresolved = render_xml(template, output, fields)
            rendered = output.read_text(encoding="utf-8")
            self.assertEqual(unresolved, [])
            self.assertEqual(rendered.count("<intervention>"), 3)
            self.assertEqual(rendered.count("<arm_group>"), 1)
            self.assertEqual(rendered.count("<secondary_outcome>"), 2)
            self.assertEqual(rendered.count("<other_outcome>"), 2)

    def test_generation_requires_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            reference = run_dir / "reference/study.reference.json"
            reference.parent.mkdir(parents=True)
            reference.write_text(
                json.dumps({"approval": {"status": "pending_review"}}), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "requires approval"):
                run_generation(run_dir, reference, require_approval=True)


class TocTests(unittest.TestCase):
    def test_pdf_extractor_and_toc_refresh_use_standard_library(self) -> None:
        document = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{WORD_NS}"><w:body>
<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Section One ........ 1</w:t></w:r></w:p>
<w:p><w:r><w:t>Section One</w:t></w:r></w:p>
<w:sectPr><w:pgSz w:w="12240"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr>
</w:body></w:document>'''
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            docx = root / "document.docx"
            pdf = root / "document.pdf"
            write_docx(docx, document)
            write_pdf(pdf, ["Section One"])
            self.assertEqual(extract_pdf_pages(pdf), ["Section One\n"])

            before = audit(docx, pdf)
            self.assertEqual(before["entry_count"], 1)
            self.assertEqual(before["alignment_mismatch_count"], 1)
            refreshed = refresh_docx(docx, pdf, docx)
            self.assertEqual(refreshed["aligned_count"], 1)

            after = audit(docx, pdf)
            self.assertEqual(after["mismatch_count"], 0)
            self.assertEqual(after["missing_count"], 0)
            self.assertEqual(after["alignment_mismatch_count"], 0)


class RepositoryContractTests(unittest.TestCase):
    def test_scripts_directory_contains_python_only(self) -> None:
        forbidden = {".js", ".mjs", ".cjs", ".applescript"}
        offenders = [path.name for path in SCRIPTS_DIR.iterdir() if path.suffix in forbidden]
        self.assertEqual(offenders, [])
        self.assertFalse((SCRIPTS_DIR / "package.json").exists())
        self.assertFalse((SCRIPTS_DIR / "package-lock.json").exists())


if __name__ == "__main__":
    unittest.main()
