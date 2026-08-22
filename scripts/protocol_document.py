#!/usr/bin/env python3
"""Structured protocol model and deterministic DOCX foundation.

The existing client templates still accept their legacy placeholders.  This
module adds the structured insertion seam used by rebuilt protocol templates:
sections, real list paragraphs, captions, and explicit Word table geometry.
It deliberately uses only the standard library so the skill remains portable.
"""

from __future__ import annotations

import html
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS_DECL = f'xmlns:w="{W}"'
PAGE_WIDTH = 9360
DEFAULT_COLUMN_WIDTHS = {
    "visitNumber": 1000,
    "visitName": 2200,
    "visitWindow": 3200,
    "CRFnumber": 2240,
    "evidence": 1800,
    "value": 4200,
    "source": 2640,
}
PARAGRAPH_RE = re.compile(r"<w:p\b[^>]*>.*?</w:p>", re.DOTALL)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return ""


def _table_contract(name: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"name": name, "columns": [], "rows": []}
    return {
        "name": name,
        "caption": value.get("caption") or name.replace("_", " ").title(),
        "columns": value.get("columns") if isinstance(value.get("columns"), list) else [],
        "rows": value.get("rows") if isinstance(value.get("rows"), list) else [],
        "validation": value.get("validation") if isinstance(value.get("validation"), dict) else {},
    }


def validate_data_driven_table(table: dict[str, Any]) -> list[str]:
    """Return contract errors without mutating a Data-Driven Table."""
    errors: list[str] = []
    columns = table.get("columns")
    rows = table.get("rows")
    if not isinstance(columns, list) or not columns:
        return ["table must declare at least one column"]
    keys: list[str] = []
    for index, column in enumerate(columns, start=1):
        if not isinstance(column, dict):
            errors.append(f"column {index} must be an object")
            continue
        key = _text(column.get("key")).strip()
        label = _text(column.get("label")).strip()
        if not key:
            errors.append(f"column {index} is missing required key")
        elif key in keys:
            errors.append(f"duplicate column key: {key}")
        else:
            keys.append(key)
        if not label:
            errors.append(f"column {index} is missing required label")
    if not isinstance(rows, list):
        errors.append("rows must be a list")
        return errors
    if not rows:
        errors.append("rows must contain at least one source row")
    for row_index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            errors.append(f"row {row_index} must be an object")
            continue
        missing = [key for key in keys if key not in row]
        if missing:
            errors.append(f"row {row_index} missing required key(s): {', '.join(missing)}")
    expected_columns = table.get("validation", {}).get("column_count")
    if expected_columns is not None and expected_columns != len(columns):
        errors.append(f"expected {expected_columns} columns, found {len(columns)}")
    return errors


def build_protocol_model(reference: dict[str, Any]) -> dict[str, Any]:
    """Build the renderer-facing structured protocol model.

    The model is additive: the legacy ``template_fields`` map remains in the
    reference and is still rendered by the compatibility adapter.
    """
    generated = reference.get("generated") if isinstance(reference.get("generated"), dict) else {}
    protocol = generated.get("protocol") if isinstance(generated.get("protocol"), dict) else {}
    retrospective = str((reference.get("meta") or {}).get("study_type") or "").casefold() == "retrospective"
    sections = protocol.get("sections") if isinstance(protocol.get("sections"), list) else []
    tables_root = reference.get("template_fields")
    tables_root = tables_root.get("data_driven_tables") if isinstance(tables_root, dict) else {}
    tables = []
    section_table_names = {
        table.get("name")
        for section in sections
        if isinstance(section, dict)
        for table in section.get("tables", [])
        if isinstance(table, dict)
    }
    if isinstance(tables_root, dict):
        for name, value in tables_root.items():
            if name == "prs_xml" or not isinstance(value, dict):
                continue
            if retrospective and name in {"visit_schedule", "schedule_of_assessments"}:
                continue
            table = _table_contract(str(name), value)
            # The complete protocol already owns the schedule and evidence
            # tables at their numbered sections.  Do not append a second
            # legacy compatibility copy after Section 19.
            if table["name"] in section_table_names or (
                table["name"] == "visit_schedule" and "schedule_of_assessments" in section_table_names
            ):
                continue
            errors = validate_data_driven_table(table)
            if errors:
                raise ValueError(f"Invalid Data-Driven Table {name}: {'; '.join(errors)}")
            tables.append(table)
    for section in sections:
        if not isinstance(section, dict):
            continue
        for table_value in section.get("tables", []):
            if not isinstance(table_value, dict):
                raise ValueError("Invalid Data-Driven Table in protocol section: table must be an object")
            table = _table_contract(str(table_value.get("name") or "section_table"), table_value)
            errors = validate_data_driven_table(table)
            if errors:
                raise ValueError(
                    f"Invalid Data-Driven Table {table['name']}: {'; '.join(errors)}"
                )
    return {
        "title": _text(reference.get("study", {}).get("title") if isinstance(reference.get("study"), dict) else ""),
        "sections": [section for section in sections if isinstance(section, dict)],
        "tables": tables,
    }


def _escape(value: Any) -> str:
    return html.escape(_text(value), quote=False)


def _run(value: Any, *, bold: bool = False) -> str:
    prop = "<w:rPr><w:b/></w:rPr>" if bold else ""
    return f'<w:r>{prop}<w:t xml:space="preserve">{_escape(value)}</w:t></w:r>'


def _paragraph(
    value: Any,
    style: str | None = None,
    *,
    list_item: bool = False,
    keep_next: bool = False,
) -> str:
    properties = []
    if style:
        properties.append(f'<w:pStyle w:val="{style}"/>')
    if list_item:
        properties.append('<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>')
    if keep_next:
        properties.append('<w:keepNext/>')
    ppr = f"<w:pPr>{''.join(properties)}</w:pPr>" if properties else ""
    return f"<w:p>{ppr}{_run(value)}</w:p>"


def _column_widths(columns: list[dict[str, Any]], table_width: int) -> list[int]:
    """Choose stable widths, honoring schema hints and preserving the table width."""
    requested = [column.get("width") for column in columns]
    if all(isinstance(width, int) and width > 0 for width in requested):
        widths = [int(width) for width in requested]
    else:
        widths = [DEFAULT_COLUMN_WIDTHS.get(column.get("key"), 0) for column in columns]
        missing = [index for index, width in enumerate(widths) if not width]
        used = sum(widths)
        remaining = max(len(missing), table_width - used)
        for index in missing:
            widths[index] = remaining // len(missing)
        if not missing and used != table_width:
            widths[-1] += table_width - used
    if sum(widths) != table_width:
        widths[-1] += table_width - sum(widths)
    return widths


def _table(table: dict[str, Any], table_width: int = PAGE_WIDTH) -> str:
    columns = table["columns"]
    widths = _column_widths(columns, table_width)
    grid = "".join(f'<w:gridCol w:w="{item}"/>' for item in widths)
    cell_margins = '<w:tcMar><w:top w:w="80" w:type="dxa"/><w:left w:w="90" w:type="dxa"/><w:bottom w:w="80" w:type="dxa"/><w:right w:w="90" w:type="dxa"/></w:tcMar>'
    borders = (
        '<w:tblBorders>'
        '<w:top w:val="single" w:sz="6" w:space="0" w:color="808080"/>'
        '<w:left w:val="single" w:sz="6" w:space="0" w:color="808080"/>'
        '<w:bottom w:val="single" w:sz="6" w:space="0" w:color="808080"/>'
        '<w:right w:val="single" w:sz="6" w:space="0" w:color="808080"/>'
        '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="B7B7B7"/>'
        '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="B7B7B7"/>'
        '</w:tblBorders>'
    )

    def row(values: dict[str, Any], header: bool = False) -> str:
        cells = []
        for column, cell_width in zip(columns, widths):
            value = values.get(column["key"], "")
            shading = '<w:shd w:fill="E7E6E6"/><w:tcBorders>' if header else ""
            cell_borders = (
                '<w:top w:val="single" w:sz="4" w:color="B7B7B7"/>'
                '<w:left w:val="single" w:sz="4" w:color="B7B7B7"/>'
                '<w:bottom w:val="single" w:sz="4" w:color="B7B7B7"/>'
                '<w:right w:val="single" w:sz="4" w:color="B7B7B7"/>'
                '</w:tcBorders>'
                if header
                else ""
            )
            tcpr = f'<w:tcPr><w:tcW w:w="{cell_width}" w:type="dxa"/><w:vAlign w:val="top"/>{shading}{cell_borders}{cell_margins}</w:tcPr>'
            cells.append(f"<w:tc>{tcpr}{_paragraph(value)}</w:tc>")
        trpr = '<w:trPr><w:tblHeader w:val="true"/><w:cantSplit/></w:trPr>' if header else '<w:trPr><w:cantSplit/></w:trPr>'
        return f"<w:tr>{trpr}{''.join(cells)}</w:tr>"

    header = {column["key"]: column["label"] for column in columns}
    rows = "".join(row(item) for item in table["rows"])
    caption = _paragraph(f"Table {table['caption']}", "Caption", keep_next=True)
    props = f'<w:tblPr><w:tblW w:w="{table_width}" w:type="dxa"/><w:tblLayout w:type="fixed"/><w:tblInd w:w="0" w:type="dxa"/>{borders}{cell_margins}</w:tblPr>'
    return f"{caption}<w:tbl>{props}<w:tblGrid>{grid}</w:tblGrid>{row(header, True)}{rows}</w:tbl>"


def structured_body(model: dict[str, Any], table_width: int = PAGE_WIDTH) -> str:
    blocks: list[str] = []
    if model.get("title"):
        blocks.append(_paragraph(model["title"], "Title"))
    for section in model.get("sections", []):
        title = _text(section.get("title"))
        if title:
            blocks.append(_paragraph(f"{section.get('number', '')} {title}".strip(), "Heading1"))
        for paragraph in section.get("paragraphs", []):
            blocks.append(_paragraph(paragraph))
        for items in section.get("lists", []):
            if isinstance(items, list):
                blocks.extend(_paragraph(item, list_item=True) for item in items)
        blocks.extend(_table(table, table_width) for table in section.get("tables", []) if isinstance(table, dict))
    blocks.extend(_table(table, table_width) for table in model.get("tables", []))
    return "".join(blocks)


def _inject_body(document_xml: str, body: str) -> str:
    # sectPr is required to be the final child of w:body.  Inserting after it
    # produces XML that parses but is not a valid Word document structure.
    section = re.search(r"<w:sectPr\b", document_xml)
    if section:
        return document_xml[: section.start()] + body + document_xml[section.start() :]
    marker = "</w:body>"
    if marker not in document_xml:
        raise ValueError("Protocol template has no Word document body")
    return document_xml.replace(marker, body + marker, 1)


def _document_content_width(document_xml: str) -> int:
    page = re.search(r'<w:pgSz\b[^>]*\bw:w="(\d+)"', document_xml)
    margins = re.search(
        r'<w:pgMar\b(?=[^>]*\bw:left="(\d+)")(?=[^>]*\bw:right="(\d+)")',
        document_xml,
    )
    if not page or not margins:
        return PAGE_WIDTH
    return max(1, int(page.group(1)) - int(margins.group(1)) - int(margins.group(2)))


def _paragraph_text(paragraph: str) -> str:
    """Return visible paragraph text for template-shell boundary checks."""
    text = "".join(re.findall(r"<w:t\b[^>]*>(.*?)</w:t>", paragraph, re.DOTALL))
    return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def _retain_template_shell(document_xml: str, *, retrospective: bool = False) -> tuple[str, bool]:
    """Keep template-owned pages and remove its legacy generated body."""
    paragraphs = list(PARAGRAPH_RE.finditer(document_xml))
    boundary = "4. INTRODUCTION" if retrospective else "5. INTRODUCTION"
    generated_starts = [
        match.start()
        for match in paragraphs
        if _paragraph_text(match.group()).startswith(boundary)
    ]
    # The TOC contains the same label; the final occurrence is the legacy
    # generated-body boundary in the bundled templates.
    generated_start = generated_starts[-1] if generated_starts else None
    if generated_start is None:
        return document_xml, False
    section = re.search(r"<w:sectPr\b", document_xml[generated_start:])
    if section is None:
        raise ValueError("Protocol template has no final section properties")
    section_start = generated_start + section.start()
    return document_xml[:generated_start] + document_xml[section_start:], True


def _ensure_section4_toc_entry(document_xml: str, *, retrospective: bool = False) -> str:
    """Add omitted Section 4 and sample-size table rows to the static TOC."""
    def row(title: str, page: int) -> str:
        return (
            '<w:p><w:pPr><w:tabs><w:tab w:val="right" w:leader="dot" w:pos="9360"/></w:tabs></w:pPr>'
            f'<w:r><w:t xml:space="preserve">{html.escape(title)}</w:t><w:tab/><w:t>{page}</w:t></w:r></w:p>'
        )

    rows = list(PARAGRAPH_RE.finditer(document_xml))
    if not re.search(r"4\.?\s+TABLE OF CONTENTS\s+\.{3,}\s+\d+", document_xml, re.I):
        for match in rows:
            text = _paragraph_text(match.group())
            if not re.match(r"5\.?\s+INTRODUCTION\s+\.{3,}\s+\d+", text, re.I):
                continue
            document_xml = document_xml[: match.start()] + row("4. TABLE OF CONTENTS", 4) + document_xml[match.start() :]
            break
    table_number = "10.1" if retrospective else "11.1"
    if not re.search(rf"Table\s+{re.escape(table_number)}\.?\s+Sample Size Evidence\s+\.{3,}\s+\d+", document_xml, re.I):
        rows = list(PARAGRAPH_RE.finditer(document_xml))
        target = r"11\.?\s+CONFIDENTIALITY" if retrospective else r"12\.?\s+CONFIDENTIALITY"
        for match in rows:
            text = _paragraph_text(match.group())
            if not re.match(target, text, re.I):
                continue
            document_xml = document_xml[: match.start()] + row(f"Table {table_number} Sample Size Evidence", 8) + document_xml[match.start() :]
            break
    return document_xml


def _remove_retrospective_orphan_toc_entries(document_xml: str) -> str:
    """Remove legacy prospective table rows from the retrospective TOC."""
    return PARAGRAPH_RE.sub(
        lambda match: ""
        if _paragraph_text(match.group()).casefold().startswith("table visit schedule")
        else match.group(),
        document_xml,
    )


def _toc_field() -> str:
    """Add an updateable Word TOC field beside the cached static TOC.

    The static rows remain the portable cached display used by renderers that
    do not update fields.  Word can update the real field on open, and the
    delivery pipeline audits the cached rows after final pagination.
    """
    return (
        '<w:p><w:pPr><w:rPr><w:vanish/></w:rPr></w:pPr>'
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r><w:instrText xml:space="preserve"> TOC \\o "1-3" \\h \\z \\u </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
    )


def _ensure_real_toc_field(document_xml: str) -> str:
    """Store a locked, updateable TOC field beside the cached TOC."""
    field = _toc_field()
    if re.search(r"<w:instrText[^>]*>\s*TOC\b", document_xml, re.I):
        return document_xml
    matches = list(PARAGRAPH_RE.finditer(document_xml))
    for match in matches:
        if "TABLE OF CONTENTS" in _paragraph_text(match.group()).upper():
            end = match.end()
            return document_xml[:end] + field + document_xml[end:]
    return document_xml


def _ensure_update_fields(members: dict[str, bytes]) -> dict[str, bytes]:
    """Tell Word to refresh fields when the document is opened."""
    name = "word/settings.xml"
    settings = members.get(name)
    if not settings:
        return members
    text = settings.decode("utf-8")
    if "updateFields" not in text:
        text = text.replace("</w:settings>", '<w:updateFields w:val="true"/></w:settings>')
    members[name] = text.encode("utf-8")
    return members


def _strip_embedded_fonts(members: dict[str, bytes]) -> dict[str, bytes]:
    clean = {
        name: data
        for name, data in members.items()
        if not (name.startswith("word/fonts/") or name in {"word/fontTable.xml", "word/_rels/fontTable.xml.rels"})
    }
    content_types = clean.get("[Content_Types].xml")
    if content_types:
        text = content_types.decode("utf-8")
        text = re.sub(r'<Override[^>]+PartName="/word/fontTable\.xml"[^>]*/>', "", text)
        clean["[Content_Types].xml"] = text.encode("utf-8")
    rels_name = "word/_rels/document.xml.rels"
    if rels_name in clean:
        text = clean[rels_name].decode("utf-8")
        text = re.sub(r'<Relationship[^>]+Target="fontTable\.xml"[^>]*/>', "", text)
        clean[rels_name] = text.encode("utf-8")
    return clean


def _ensure_footer(members: dict[str, bytes]) -> dict[str, bytes]:
    """Keep the template header and guarantee a real default footer part."""
    if any(name.startswith("word/footer") for name in members):
        return members
    footer_name = "word/footer1.xml"
    rels_name = "word/_rels/document.xml.rels"
    content_types_name = "[Content_Types].xml"
    rels = members.get(rels_name, b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"></Relationships>').decode("utf-8")
    ids = [int(item) for item in re.findall(r'Id="rId(\d+)"', rels)]
    relationship_id = f"rId{max(ids, default=0) + 1}"
    relationship = (
        f'<Relationship Id="{relationship_id}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" '
        'Target="footer1.xml"/>'
    )
    rels = rels.replace("</Relationships>", relationship + "</Relationships>")
    members[rels_name] = rels.encode("utf-8")
    content_types = members.get(content_types_name, b"").decode("utf-8")
    override = (
        '<Override PartName="/word/footer1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>'
    )
    if content_types and "PartName=\"/word/footer1.xml\"" not in content_types:
        content_types = content_types.replace("</Types>", override + "</Types>")
        members[content_types_name] = content_types.encode("utf-8")
    document = members["word/document.xml"].decode("utf-8")
    reference = f'<w:footerReference w:type="default" r:id="{relationship_id}"/>'
    document = re.sub(r"(<w:sectPr\b[^>]*>)", r"\1" + reference, document, count=1)
    members["word/document.xml"] = document.encode("utf-8")
    members[footer_name] = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:ftr {NS_DECL}><w:p><w:pPr><w:jc w:val="center"/></w:pPr>'
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p></w:ftr>'
    ).encode("utf-8")
    return members


def render_protocol_docx(template_path: Path, output_path: Path, reference: dict[str, Any]) -> dict[str, Any]:
    """Render the template shell plus one structured, editable protocol body."""
    from render_templates import build_render_data, render_docx, unresolved_in_docx

    model = build_protocol_model(reference)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output_path.parent) as temporary:
        legacy = Path(temporary) / "legacy.docx"
        render_docx(template_path, legacy, build_render_data(reference))
        with zipfile.ZipFile(legacy) as archive:
            members = {item.filename: archive.read(item.filename) for item in archive.infolist()}
        document = members["word/document.xml"].decode("utf-8")
        retrospective = str((reference.get("meta") or {}).get("study_type") or "").casefold() == "retrospective"
        document = _ensure_section4_toc_entry(document, retrospective=retrospective)
        if retrospective:
            document = _remove_retrospective_orphan_toc_entries(document)
        document = _ensure_real_toc_field(document)
        document, legacy_body_removed = _retain_template_shell(document, retrospective=retrospective)
        members["word/document.xml"] = _inject_body(
            document, structured_body(model, _document_content_width(document))
        ).encode("utf-8")
        members = _strip_embedded_fonts(members)
        members = _ensure_footer(members)
        members = _ensure_update_fields(members)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in members.items():
                archive.writestr(name, data)
    section_table_count = sum(
        len(section.get("tables", []))
        for section in model["sections"]
        if isinstance(section, dict) and isinstance(section.get("tables", []), list)
    )
    return {
        "unresolved_placeholders": unresolved_in_docx(output_path),
        "embedded_fonts": sorted(name for name in members if name.startswith("word/fonts/") or name == "word/fontTable.xml"),
        "structured_sections": len(model["sections"]),
        "structured_tables": len(model["tables"]) + section_table_count,
        "legacy_body_removed": legacy_body_removed,
        "package_size_bytes": output_path.stat().st_size,
        "has_header": any(name.startswith("word/header") for name in members),
        "has_footer": any(name.startswith("word/footer") for name in members),
        "toc_field": True,
    }
