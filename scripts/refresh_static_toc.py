#!/usr/bin/env python3
"""Refresh and align static DOCX table-of-contents entries from a rendered PDF."""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from audit_static_toc import audit, normalize


PARAGRAPH_RE = re.compile(r"<w:p\b[^>]*>.*?</w:p>", re.DOTALL)
PARAGRAPH_PROPERTIES_RE = re.compile(r"<w:pPr\b[^>]*>.*?</w:pPr>", re.DOTALL)
RUN_PROPERTIES_RE = re.compile(r"<w:rPr\b[^>]*>.*?</w:rPr>", re.DOTALL)


def set_word_field_refresh_flags(path: Path) -> None:
    def add_dirty_flag(match: re.Match[str]) -> str:
        field_start = re.sub(r"\s*/\s*$", "", match.group(1))
        return field_start + ' w:dirty="true"/>'

    with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
        tmp_path = Path(tmp.name)
    try:
        with zipfile.ZipFile(path, "r") as zin, zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == "word/settings.xml":
                    xml = data.decode("utf-8")
                    if "<w:updateFields" not in xml:
                        xml = xml.replace("</w:settings>", '<w:updateFields w:val="true"/></w:settings>')
                    else:
                        xml = re.sub(r"<w:updateFields\b[^>]*/>", '<w:updateFields w:val="true"/>', xml)
                    data = xml.encode("utf-8")
                elif item.filename.startswith("word/header") and b"PAGE" in data:
                    xml = data.decode("utf-8")
                    xml = re.sub(
                        r'(<w:fldChar\b(?=[^>]*w:fldCharType="begin")(?:(?!w:dirty=)[^>])*)/?>',
                        add_dirty_flag,
                        xml,
                        count=1,
                    )
                    xml = re.sub(r'w:dirty="false"', 'w:dirty="true"', xml)
                    data = xml.encode("utf-8")
                zout.writestr(item, data)
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def toc_tab_position(document_xml: str) -> int:
    page_size = re.search(r"<w:pgSz\b[^>]*\bw:w=\"(?P<width>\d+)\"", document_xml)
    margins = re.search(
        r"<w:pgMar\b(?=[^>]*\bw:left=\"(?P<left>\d+)\")"
        r"(?=[^>]*\bw:right=\"(?P<right>\d+)\")[^>]*/?>",
        document_xml,
    )
    if not page_size or not margins:
        return 9360
    return max(
        0,
        int(page_size.group("width"))
        - int(margins.group("left"))
        - int(margins.group("right")),
    )


def normalized_paragraph_properties(paragraph: str, tab_position: int) -> str:
    match = PARAGRAPH_PROPERTIES_RE.search(paragraph)
    properties = match.group(0) if match else "<w:pPr></w:pPr>"
    properties = re.sub(r"<w:tabs\b[^>]*>.*?</w:tabs>", "", properties, flags=re.DOTALL)
    properties = re.sub(r"<w:tabs\b[^>]*/>", "", properties)
    properties = re.sub(r"<w:ind\b[^>]*/>", "", properties)
    tab = (
        f'<w:tabs><w:tab w:val="right" w:leader="dot" '
        f'w:pos="{tab_position}"/></w:tabs>'
    )
    return properties.replace("</w:pPr>", tab + "</w:pPr>")


def align_toc_paragraph(paragraph: str, title: str, page: int, tab_position: int) -> str:
    opening = re.match(r"<w:p\b[^>]*>", paragraph)
    if not opening:
        return paragraph
    properties = normalized_paragraph_properties(paragraph, tab_position)
    run_properties_match = RUN_PROPERTIES_RE.search(paragraph)
    run_properties = run_properties_match.group(0) if run_properties_match else ""
    escaped_title = html.escape(normalize(title), quote=False)
    run = (
        f"<w:r>{run_properties}<w:t xml:space=\"preserve\">{escaped_title}</w:t>"
        f"<w:tab/><w:t>{page}</w:t></w:r>"
    )
    return opening.group(0) + properties + run + "</w:p>"


def update_document_xml(path: Path, entries: list[dict[str, Any]]) -> None:
    with zipfile.ZipFile(path) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")
    by_index = {
        entry["paragraph_index"]: entry
        for entry in entries
        if entry.get("actual_page") is not None
    }
    tab_position = toc_tab_position(document_xml)
    paragraph_index = -1

    def replace_paragraph(match: re.Match[str]) -> str:
        nonlocal paragraph_index
        paragraph_index += 1
        entry = by_index.get(paragraph_index)
        if not entry:
            return match.group(0)
        return align_toc_paragraph(
            match.group(0), entry["title"], entry["actual_page"], tab_position
        )

    updated_xml = PARAGRAPH_RE.sub(replace_paragraph, document_xml).encode("utf-8")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".docx", dir=path.parent) as tmp:
        tmp_path = Path(tmp.name)
    try:
        with zipfile.ZipFile(path, "r") as source, zipfile.ZipFile(
            tmp_path, "w"
        ) as destination:
            for item in source.infolist():
                data = updated_xml if item.filename == "word/document.xml" else source.read(item.filename)
                destination.writestr(item, data)
        tmp_path.replace(path)
    finally:
        tmp_path.unlink(missing_ok=True)


def refresh_docx(docx_path: Path, pdf_path: Path, output_path: Path) -> dict[str, Any]:
    result = audit(docx_path, pdf_path)
    if result["missing_count"]:
        missing = ", ".join(item["title"] for item in result["missing"])
        raise SystemExit(f"Cannot refresh TOC because rendered headings were not found: {missing}")
    if result["entry_count"] == 0:
        raise SystemExit("Cannot refresh TOC because no static TOC entries were found.")

    if output_path.resolve() != docx_path.resolve():
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(docx_path, output_path)
    else:
        output_path = docx_path

    updated = []
    aligned_count = 0
    for entry in result["entries"]:
        actual_page = entry["actual_page"]
        if actual_page is None:
            continue
        if actual_page != entry["listed_page"]:
            updated.append(
                {
                    "title": entry["title"],
                    "old_page": entry["listed_page"],
                    "new_page": actual_page,
                }
            )
        if actual_page != entry["listed_page"] or not entry.get("alignment_ok"):
            aligned_count += 1

    update_document_xml(output_path, result["entries"])
    set_word_field_refresh_flags(output_path)
    return {
        **result,
        "output_docx": str(output_path),
        "updated_count": len(updated),
        "aligned_count": aligned_count,
        "alignment": "right_tab_with_dot_leader",
        "updates": updated,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docx", required=True, help="DOCX containing static TOC entries.")
    parser.add_argument("--pdf", required=True, help="Rendered PDF used as the page source of truth.")
    parser.add_argument("--output", help="Output DOCX path. Defaults to updating --docx in place.")
    parser.add_argument("--report", help="Optional JSON refresh report path.")
    args = parser.parse_args()

    docx_path = Path(args.docx).expanduser().resolve()
    pdf_path = Path(args.pdf).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve() if args.output else docx_path
    result = refresh_docx(docx_path, pdf_path, output_path)
    rendered = json.dumps(result, indent=2)
    if args.report:
        report_path = Path(args.report).expanduser().resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
