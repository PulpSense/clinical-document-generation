"""A static table of contents must describe the document it sits in.

The bundled retrospective protocol listed `8.1. Informed Consent / Subject
enrollment` in its TOC while its body jumped straight from section 8 to
section 9. Nothing caught it until the visual QA gate began auditing the TOC
against a rendered PDF, at which point the branch could no longer be packaged
on any host with a renderer installed.

These tests catch that class deterministically, with no renderer involved.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from validate_template_contract import (  # noqa: E402
    PROTOCOL_TEMPLATES,
    orphan_toc_findings,
)


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
BUNDLED_DOCX_DIR = REPO_ROOT / "assets" / "client-templates" / "docx"


def toc_paragraph(title: str, page: int) -> str:
    """A paragraph shaped like a real static TOC row."""
    return (
        "<w:p><w:pPr><w:tabs>"
        '<w:tab w:val="right" w:leader="dot" w:pos="9000"/>'
        "</w:tabs></w:pPr>"
        f'<w:r><w:t xml:space="preserve">{title}\t{page}</w:t></w:r></w:p>'
    )


def body_paragraph(text: str) -> str:
    return f'<w:p><w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>'


def write_docx(path: Path, body: str) -> None:
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{WORD_NS}"><w:body>{body}</w:body></w:document>'
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document)


class OrphanTocEntryTests(unittest.TestCase):
    def findings_for(self, body: str) -> list[dict]:
        with tempfile.TemporaryDirectory() as temporary:
            template = Path(temporary) / "protocol.template.docx"
            write_docx(template, body)
            return orphan_toc_findings(template)

    def test_a_toc_entry_with_no_body_heading_is_reported(self) -> None:
        findings = self.findings_for(
            toc_paragraph("8. STUDY PROCEDURE", 5)
            + toc_paragraph("8.1. Informed Consent / Subject enrollment", 5)
            + body_paragraph("8. STUDY PROCEDURE")
            + body_paragraph("{AI_studyProcedure}")
        )

        self.assertEqual(len(findings), 1)
        self.assertIn("Informed Consent", findings[0]["entry"])

    def test_a_heading_sharing_its_paragraph_with_content_still_counts(self) -> None:
        """`9.1. Analysis Data Sets {AI_analysisDataSets}` is a real heading."""
        findings = self.findings_for(
            toc_paragraph("9.1. Analysis Data Sets", 5)
            + body_paragraph("9.1. Analysis Data Sets {AI_analysisDataSets}")
        )

        self.assertEqual(findings, [])

    def test_a_document_with_no_toc_is_not_a_finding(self) -> None:
        self.assertEqual(self.findings_for(body_paragraph("1. TITLE PAGE")), [])

    def test_every_bundled_protocol_template_describes_its_own_body(self) -> None:
        for name in PROTOCOL_TEMPLATES:
            with self.subTest(template=name):
                findings = orphan_toc_findings(BUNDLED_DOCX_DIR / name)
                self.assertEqual(
                    findings,
                    [],
                    f"{name} lists sections its body does not contain: "
                    f"{[item['entry'] for item in findings]}",
                )


if __name__ == "__main__":
    unittest.main()
