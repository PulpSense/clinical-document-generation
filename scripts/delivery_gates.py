"""Delivery gates for generated study documents."""

from __future__ import annotations

import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from render_templates import unresolved_in_docx

WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = "{" + WORD_NS + "}"
MAX_DOCX_BYTES = 5 * 1024 * 1024
NORMAL_MAX_DOCX_BYTES = 250 * 1024
INTERNAL_LANGUAGE = re.compile(r"\b(?:draft|todo|tbd|needs review|internal only)\b", re.I)
STALE_TEMPLATE_LANGUAGE = re.compile(
    r"(?i)(?:cataract|handpiece|prior[- ]to[- ]surgery|the approved source identifies|should be finalized|replace(?:d)? before delivery)"
)


def _text(root: ET.Element) -> str:
    return " ".join(item.text or "" for item in root.iter(W + "t")).strip()


def audit_docx_package(path: Path) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if path.stat().st_size > MAX_DOCX_BYTES:
        errors.append({"field": str(path), "issue": f"DOCX package is {path.stat().st_size} bytes; limit is {MAX_DOCX_BYTES} bytes."})
    elif path.stat().st_size > NORMAL_MAX_DOCX_BYTES:
        errors.append({"field": str(path), "issue": f"DOCX package is {path.stat().st_size} bytes; normal production limit is {NORMAL_MAX_DOCX_BYTES} bytes."})
    try:
        with zipfile.ZipFile(path) as archive:
            bad = archive.testzip()
            if bad:
                errors.append({"field": str(path), "issue": f"DOCX package contains a corrupt member: {bad}."})
            names = set(archive.namelist())
            required_members = {"[Content_Types].xml", "word/document.xml", "word/_rels/document.xml.rels"}
            for member in sorted(required_members - names):
                errors.append({"field": str(path), "issue": f"DOCX package is missing required member `{member}`."})
            if any(name.startswith("word/fonts/") for name in names) or "word/fontTable.xml" in names:
                errors.append({"field": str(path), "issue": "DOCX package contains embedded fonts or font-table assets."})
    except (OSError, zipfile.BadZipFile) as exc:
        errors.append({"field": str(path), "issue": f"DOCX package cannot be opened: {exc}."})
    return errors


def repair_docx_package(path: Path) -> dict[str, Any]:
    """Apply the one controlled package repair allowed before revalidation."""
    from protocol_document import _strip_embedded_fonts

    with zipfile.ZipFile(path) as source:
        members = {item.filename: source.read(item.filename) for item in source.infolist()}
    clean = _strip_embedded_fonts(members)
    removed = sorted(set(members) - set(clean))
    if not removed:
        return {"path": str(path), "changed": False, "removed_members": []}
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".docx", delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with zipfile.ZipFile(temporary_path, "w", zipfile.ZIP_DEFLATED) as destination:
            for name, data in clean.items():
                destination.writestr(name, data)
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return {"path": str(path), "changed": True, "removed_members": removed}


def audit_protocol_structure(path: Path, *, require_substantive: bool = False) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    try:
        with zipfile.ZipFile(path) as archive:
            root = ET.fromstring(archive.read("word/document.xml"))
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError) as exc:
        return [{"field": str(path), "issue": f"Protocol document structure cannot be parsed: {exc}."}]
    body_text = _text(root)
    body = root.find(".//" + W + "body")
    if body is None:
        return [{"field": str(path), "issue": "Protocol document has no Word body."}]
    section_properties = body.findall("./" + W + "sectPr")
    if len(section_properties) != 1:
        errors.append({"field": "word/document.xml", "issue": f"Protocol must contain exactly one final section-properties element; found {len(section_properties)}."})
    elif section_properties[0].find("./" + W + "pgSz") is None or section_properties[0].find("./" + W + "pgMar") is None:
        errors.append({"field": "word/document.xml", "issue": "Layout contract requires explicit page size and margins."})
    required = (
        "5. INTRODUCTION",
        "6. OBJECTIVE(S)",
        "7. SUBJECTS",
        "8. STUDY DESIGN",
        "9. STUDY PROCEDURE",
        "10. ANALYSIS PLAN",
        "11. SAMPLE SIZE JUSTIFICATION",
        "15. STANDARD EVALUATION PROCEDURES",
        "18. STUDY ENDPOINT CRITERIA",
        "18.1. Patient Completion of Study",
        "18.2. Patient Discontinuation",
        "18.3. Patient Termination",
        "18.4. Study Termination",
        "18.5. Study Completion",
        "19. SUMMARY OF RISKS AND BENEFITS",
    )
    for heading in required:
        if heading not in body_text:
            errors.append({"field": heading, "issue": "Required protocol section is missing."})

    heading_paragraphs = [
        paragraph for paragraph in body.findall("./" + W + "p")
        if paragraph.find("./" + W + "pPr/" + W + "pStyle") is not None
        and paragraph.find("./" + W + "pPr/" + W + "pStyle").get(W + "val", "").lower().startswith("heading")
    ]
    for heading in required:
        matches = [paragraph for paragraph in heading_paragraphs if re.sub(r"\s+", " ", _text(paragraph)).strip() == heading]
        if len(matches) > 1:
            errors.append({"field": heading, "issue": f"Required section appears {len(matches)} times; expected exactly once."})

    if require_substantive:
        children = list(body)
        heading_positions = {
            index: re.sub(r"\s+", " ", _text(child)).strip()
            for index, child in enumerate(children)
            if child.tag == W + "p"
            and child.find("./" + W + "pPr/" + W + "pStyle") is not None
            and child.find("./" + W + "pPr/" + W + "pStyle").get(W + "val", "").lower().startswith("heading")
        }
        for position, title in heading_positions.items():
            if title not in required:
                continue
            has_body = False
            for following in children[position + 1 :]:
                if following.tag == W + "p":
                    following_text = re.sub(r"\s+", " ", _text(following)).strip()
                    following_style = following.find("./" + W + "pPr/" + W + "pStyle")
                    if following_style is not None and following_style.get(W + "val", "").lower().startswith("heading"):
                        break
                    if following_text and not following_text.startswith("Table of Contents"):
                        has_body = True
                        break
                elif following.tag == W + "tbl":
                    has_body = True
                    break
            if not has_body:
                errors.append({"field": title, "issue": "Required section heading has no substantive body content."})

    for paragraph in body.findall("./" + W + "p"):
        paragraph_text = re.sub(r"\s+", " ", _text(paragraph)).strip()
        has_tab = paragraph.find(".//" + W + "tab") is not None
        if paragraph_text.startswith("Table ") and not re.search(r"\.{3,}\s*\d+\s*$", paragraph_text) and not (has_tab and re.search(r"\d+\s*$", paragraph_text)):
            ppr = paragraph.find("./" + W + "pPr")
            if ppr is None or ppr.find("./" + W + "keepNext") is None:
                errors.append({"field": paragraph_text, "issue": "Table caption must be a real paragraph kept with its following table."})
        if paragraph.find("./" + W + "pPr/" + W + "numPr") is not None:
            num_pr = paragraph.find("./" + W + "pPr/" + W + "numPr")
            if num_pr.find("./" + W + "numId") is None or num_pr.find("./" + W + "ilvl") is None:
                errors.append({"field": paragraph_text, "issue": "List item is missing explicit numbering level or numbering definition."})

    # A heading is not a complete section. Check the structured Word
    # paragraphs so an empty or heading-only Section 18 cannot pass delivery.
    paragraphs = root.findall(".//" + W + "p")
    section18_titles = {
        "18. STUDY ENDPOINT CRITERIA",
        "18.1. Patient Completion of Study",
        "18.2. Patient Discontinuation",
        "18.3. Patient Termination",
        "18.4. Study Termination",
        "18.5. Study Completion",
    }
    for index, paragraph in enumerate(paragraphs):
        title = re.sub(r"\s+", " ", _text(paragraph)).strip()
        if title not in section18_titles:
            continue
        next_text = ""
        for following in paragraphs[index + 1 :]:
            candidate = re.sub(r"\s+", " ", _text(following)).strip()
            if candidate in section18_titles or candidate.startswith("19."):
                break
            if candidate:
                next_text = candidate
                break
        if not next_text:
            errors.append({"field": title, "issue": "Required Section 18 heading has no substantive body text."})
    tables = root.findall(".//" + W + "tbl")
    captions = ("Table 11.1 Sample Size Evidence", "Table 15.1 Proposed Visits and Study Assessments")
    present_captions = [caption for caption in captions if caption in body_text]
    if len(tables) < len(present_captions):
        for caption in present_captions[len(tables):]:
            errors.append({"field": caption, "issue": "Table caption is present without a corresponding Word table."})
    if "Table 15.1 Proposed Visits and Study Assessments" not in body_text:
        errors.append({"field": "Table 15.1 Proposed Visits and Study Assessments", "issue": "Complete Schedule of Assessments table is missing."})
    for index, table in enumerate(tables, start=1):
        grid = table.find("./" + W + "tblGrid")
        rows = table.findall("./" + W + "tr")
        if grid is None or not grid.findall("./" + W + "gridCol"):
            errors.append({"field": f"table[{index}]", "issue": "Table has no explicit Word grid geometry."})
        grid_columns = grid.findall("./" + W + "gridCol") if grid is not None else []
        table_properties = table.find("./" + W + "tblPr")
        if table_properties is None or table_properties.find("./" + W + "tblLayout") is None:
            errors.append({"field": f"table[{index}]", "issue": "Table must use explicit fixed layout geometry."})
        header_marker = rows[0].find("./" + W + "trPr/" + W + "tblHeader") if rows else None
        structured_table = bool(header_marker is not None and header_marker.get(W + "val", "true").lower() in {"true", "1", "on"})
        for row_index, row in enumerate(rows, start=1):
            cells = row.findall("./" + W + "tc")
            if not cells:
                errors.append({"field": f"table[{index}].row[{row_index}]", "issue": "Table row has no cells."})
                continue
            if structured_table and grid_columns and len(cells) != len(grid_columns):
                errors.append({"field": f"table[{index}].row[{row_index}]", "issue": "Table row cell count does not match its explicit grid."})
            if structured_table:
                for cell_index, cell in enumerate(cells, start=1):
                    tcpr = cell.find("./" + W + "tcPr")
                    if tcpr is None or tcpr.find("./" + W + "tcW") is None or tcpr.find("./" + W + "vAlign") is None:
                        errors.append({"field": f"table[{index}].row[{row_index}].cell[{cell_index}]", "issue": "Table cell lacks explicit width or vertical alignment."})
        if rows and structured_table:
            header_properties = rows[0].find("./" + W + "trPr")
            if header_properties is None or header_properties.find("./" + W + "tblHeader") is None:
                errors.append({"field": f"table[{index}]", "issue": "Data-driven table must repeat its header row across pages."})
    if INTERNAL_LANGUAGE.search(body_text):
        errors.append({"field": "word/document.xml", "issue": "Internal drafting language is present in the client-facing protocol."})
    return errors


def audit_gp26_visual_acceptance(path: Path) -> list[dict[str, str]]:
    """Audit user-visible GP-26 protocol defects not covered by XML validity."""
    errors: list[dict[str, str]] = []
    try:
        with zipfile.ZipFile(path) as archive:
            root = ET.fromstring(archive.read("word/document.xml"))
            body_text = _text(root)
            paragraphs = root.findall(".//" + W + "p")
            headings = [
                _text(paragraph)
                for paragraph in paragraphs
                if paragraph.find("./" + W + "pPr/" + W + "pStyle") is not None
                and paragraph.find("./" + W + "pPr/" + W + "pStyle").get(W + "val", "").lower().startswith("heading")
            ]
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError) as exc:
        return [{"field": str(path), "issue": f"Visual acceptance could not parse DOCX: {exc}."}]

    for title in (
        "5. INTRODUCTION", "6. OBJECTIVE(S)", "7. SUBJECTS", "8. STUDY DESIGN",
        "9. STUDY PROCEDURE", "10. ANALYSIS PLAN", "11. SAMPLE SIZE JUSTIFICATION",
        "15. STANDARD EVALUATION PROCEDURES", "17. FINANCIAL AND INSURANCE INFORMATION/STUDY RELATED INJURIES",
        "19. SUMMARY OF RISKS AND BENEFITS",
    ):
        count = sum(1 for heading in headings if re.sub(r"\s+", " ", heading).strip() == title)
        if count != 1:
            errors.append({"field": title, "issue": f"Required section appears {count} times; expected exactly once."})

    if body_text.count("Table 15.1 Proposed Visits and Study Assessments") != 1:
        errors.append({"field": "Table 15.1 Proposed Visits and Study Assessments", "issue": "Schedule caption is duplicated or missing."})
    if len(root.findall(".//" + W + "tbl")) < 2:
        errors.append({"field": "required_tables", "issue": "Required sample-size and Schedule of Assessments tables are not both present."})
    if STALE_TEMPLATE_LANGUAGE.search(body_text):
        errors.append({"field": "word/document.xml", "issue": "Stale study-specific template or internal drafting language is present."})
    return errors


def audit_generated_outputs(run_dir: Path, outputs: list[str], *, protocol_output: str = "output/protocol.docx") -> dict[str, Any]:
    """Run package, unresolved-placeholder, and protocol-structure gates."""
    failures: list[dict[str, str]] = []
    package_reports: list[dict[str, Any]] = []
    for relative in outputs:
        path = run_dir / relative
        if path.suffix.lower() != ".docx" or not path.exists():
            continue
        package_errors = audit_docx_package(path)
        unresolved = unresolved_in_docx(path)
        if unresolved:
            package_errors.append({"field": relative, "issue": "Unresolved placeholders: " + ", ".join(unresolved)})
        failures.extend(package_errors)
        package_reports.append({"output": relative, "package_error_count": len(package_errors), "package_size_bytes": path.stat().st_size})
    rendering: dict[str, Any] = {"status": "skipped", "reason": "No external PDF render evidence was supplied."}
    pdf_path = run_dir / "logs" / "docx-render" / "protocol.pdf"
    protocol_path = run_dir / protocol_output
    if protocol_path.exists():
        structure_errors = audit_protocol_structure(protocol_path, require_substantive=True)
        failures.extend(structure_errors)
        failures.extend(audit_gp26_visual_acceptance(protocol_path))
        if pdf_path.exists() and pdf_path.stat().st_mtime >= protocol_path.stat().st_mtime:
            try:
                from audit_static_toc import audit

                toc = audit(protocol_path, pdf_path)
                rendering = {"status": "passed" if not toc["mismatch_count"] and not toc["missing_count"] and not toc["alignment_mismatch_count"] else "failed", "toc": toc}
                if rendering["status"] == "failed":
                    failures.append({"field": "static_toc", "issue": "Static TOC does not match rendered page evidence."})
            except (OSError, ValueError, zipfile.BadZipFile) as exc:
                rendering = {"status": "failed", "issue": str(exc)}
                failures.append({"field": "rendering", "issue": f"Rendered protocol evidence could not be audited: {exc}."})
    return {
        "status": "failed" if failures else "passed",
        "failure_count": len(failures),
        "failures": failures,
        "packages": package_reports,
        "rendering": rendering,
    }
