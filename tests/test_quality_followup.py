"""Adversarial regressions for exact-PDF quality evidence."""
import pytest
from docx import Document
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

import quality
from test_quality_gate_corrections import toc_docx, write_pdf


def test_visible_toc_contradiction_overrides_matching_cache_and_body(tmp_path):
    docx, pdf = tmp_path / "protocol.docx", tmp_path / "protocol.pdf"
    toc_docx(docx)
    write_pdf(pdf, [[("TABLE OF CONTENTS", 72, 700), ("1. PURPOSE 9", 72, 670)],
                    [("1. PURPOSE", 72, 700)]])
    before = docx.read_bytes(), pdf.read_bytes()
    report = quality.audit_final_toc_destinations(docx, pdf)
    assert report["status"] == "mismatch"
    row = next(row for row in report["destinations"] if row["heading"] == "1. PURPOSE")
    assert row["cached_page"] == row["rendered_page"] == 2
    assert row["rendered_toc_page"] == 9
    assert row["status"] == "mismatch"
    assert report["findings"][0]["check"] == "toc_mismatch"
    assert (docx.read_bytes(), pdf.read_bytes()) == before


@pytest.mark.parametrize("entry", [None, "1. PURPOSE ?", "1. PURPOSE 2\n1. PURPOSE 2"])
def test_unverified_or_ambiguous_visible_toc_remains_unknown(tmp_path, entry):
    docx, pdf = tmp_path / "protocol.docx", tmp_path / "protocol.pdf"
    toc_docx(docx)
    lines = [("TABLE OF CONTENTS", 72, 700)]
    if entry:
        lines.extend((line, 72, 670 - i * 20) for i, line in enumerate(entry.splitlines()))
    write_pdf(pdf, [lines, [("1. PURPOSE", 72, 700)]])
    report = quality.audit_final_toc_destinations(docx, pdf)
    assert report["status"] == "unknown"
    assert report["findings"] == []


@pytest.mark.parametrize("cached,visible,body,status", [
    (2, 9, False, "mismatch"),  # contradiction does not require a body match
    (None, 2, True, "unknown"),  # absent cache is not a contradiction
    (2, 2, True, "passed"),
])
def test_toc_requires_evidence_not_assumptions(tmp_path, cached, visible, body, status):
    docx, pdf = tmp_path / "protocol.docx", tmp_path / "protocol.pdf"
    toc_docx(docx, cached_page=cached)
    write_pdf(pdf, [[("TABLE OF CONTENTS", 72, 700), (f"1. PURPOSE {visible}", 72, 670)],
                    [("1. PURPOSE" if body else "Unextractable destination", 72, 700)]])
    report = quality.audit_final_toc_destinations(docx, pdf)
    assert report["status"] == status
    assert bool(report["findings"]) == (status == "mismatch")


def test_inline_body_image_is_not_a_blank_page(tmp_path):
    docx, pdf = tmp_path / "body.docx", tmp_path / "body.pdf"
    Document().save(docx)
    writer = PdfWriter()
    # Header-only imagery remains furniture; body and boundary-crossing
    # imagery must survive even when there is no extractable text.
    for matrix in ("20 0 0 20 100 750", "200 0 0 200 100 300", "20 0 0 100 100 700"):
        page = writer.add_blank_page(width=612, height=792)
        stream = DecodedStreamObject()
        stream.set_data(b"q " + matrix.encode() + b" cm BI /W 1 /H 1 /CS /RGB /BPC 8 ID \xff\x00\x00 EI Q")
        page[NameObject("/Contents")] = writer._add_object(stream)
    writer.write(pdf)
    before = docx.read_bytes(), pdf.read_bytes()
    assert quality._blank_pdf_pages(pdf, docx_path=docx) == [1]
    rows = quality._pdf_body_pages(pdf, docx_path=docx)
    assert not rows[1]["body_empty"] and not rows[2]["body_empty"]
    assert (docx.read_bytes(), pdf.read_bytes()) == before
