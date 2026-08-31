"""Fail-closed content, XML, renderer, and page-visual quality gates."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import importlib
import importlib.util
import json
import math
import os
import platform
import re
import signal
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import zipfile
import zlib
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader
from lxml import etree as ET

from contracts import APPROVED_PACKAGED_FONT_FALLBACKS, BOILERPLATE_VERSION, BUNDLED_FONT_FILES, ICF_RETAINED_SHELL_SECTIONS, RECOVERY_POLICIES, batch_plan, canonical_study_type, contracted_template_bundle, get_path, icf_contract, icf_retained_sections, protocol_contract, recovery_finding
from rendering import audit_docx, refresh_toc_from_pdf, template_paths


VERIFY_SCHEMA = "hermes-verification/v1"
RESPONSE_SCHEMA = "hermes-verification-response/v1"
CONTENT_CHECKS = ("substantive", "source_supported", "no_invention", "no_internal_language", "cross_document_consistent")
CROSS_DOCUMENT_CHECKS = ("protocol_number", "study_title", "study_type", "population", "procedures", "risks_benefits")
VISUAL_CHECKS = (
    "clipping", "overlap", "overflow", "orphan_heading", "bad_table_split",
    "blank_page", "footer_collision", "unreadable_text", "duplicate_section",
    "inconsistent_style", "missing_header_footer", "toc_mismatch",
    "excessive_whitespace", "artificial_pagination",
)
TRANSIENT_REVIEW_STATUSES = {"retryable_error", "transient_error", "unavailable", "temporarily_unavailable"}
_MAC_FONT_NAMES: set[str] | None = None
_WINDOWS_FONT_NAMES: set[str] | None = None
PDFIUM_WORKER_TIMEOUT_SECONDS = 120.0
PDFIUM_MAX_PAGES = 400
PDFIUM_MAX_DIMENSION_PIXELS = 20_000
PDFIUM_MAX_TOTAL_PIXELS = 1_000_000_000
PDFIUM_MAX_OUTPUT_BYTES = 1_000_000_000
PDFIUM_WORKER_MEMORY_BYTES = 2 * 1024 * 1024 * 1024
PDFIUM_WORKER_FILE_BYTES = PDFIUM_MAX_OUTPUT_BYTES + 64 * 1024 * 1024
RELEASE_CERTIFICATION_PUBLIC_KEY = "references/release-certification-public-key.json"
RELEASE_CERTIFICATION_SIGNATURE_ALGORITHM = "rsa-pkcs1-v1_5-sha256"
RELEASE_CERTIFICATION_TRUSTED_KEY_ID = "50aa8bde2e3f31c7c24984078dbe1d236f118e0744c43a84d0e4c77ffcc1107c"
_SHA256_DIGEST_INFO_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")
CERTIFICATION_EVIDENCE_MAX_FILES = 512
CERTIFICATION_EVIDENCE_MAX_ITEM_BYTES = 32 * 1024 * 1024
CERTIFICATION_EVIDENCE_MAX_TOTAL_BYTES = 128 * 1024 * 1024
CERTIFICATION_CASE_ORDER = (
    "retrospective", "ambispective-sterling", "prospective-advarra",
)
DETERMINISTIC_BRANCH_ACCEPTANCE_CASES = (
    "prospective-sparse-complete", "prospective-rich-complete",
    "ambispective-sparse-complete", "ambispective-rich-complete",
    "retrospective-sparse-complete", "retrospective-rich-complete",
)
GOVERNED_GATE_SEQUENCE = (
    "clinical_fidelity",
    "content_completeness_consistency",
    "docx_prs_structure",
    "exact_artifact_rendering",
    "every_page_visual_qa",
    "exact_byte_atomic_delivery",
)
FORMAT_CONFORMANCE_MATRIX = "references/format-conformance-matrix.json"
CERTIFICATION_VISUAL_CHECKS = {
    "artificial_pagination", "bad_table_split", "blank_page", "clipping",
    "duplicate_section", "excessive_whitespace", "footer_collision",
    "inconsistent_style", "missing_header_footer", "orphan_heading",
    "overflow", "overlap", "toc_mismatch", "unreadable_text",
}

SYMBOL_FONT_FALLBACKS = (
    "Apple Symbols",
    "Segoe UI Symbol",
    "Arial Unicode MS",
    "Arial Unicode",
    "Symbol",
    "DejaVu Sans",
    "Noto Sans",
    "Arial",
    "Helvetica",
    "Liberation Sans",
)
SANS_FONT_FALLBACKS = (
    "Arial",
    "Helvetica",
    "Aptos",
    "Calibri",
    "Liberation Sans",
    "DejaVu Sans",
    "Noto Sans",
    "Verdana",
)
SERIF_FONT_FALLBACKS = (
    "Times New Roman",
    "Times",
    "Liberation Serif",
    "DejaVu Serif",
    "Georgia",
    "Cambria",
    "Noto Serif",
)
MONOSPACE_FONT_FALLBACKS = (
    "Courier New",
    "Menlo",
    "Consolas",
    "Liberation Mono",
    "DejaVu Sans Mono",
    "Noto Sans Mono",
)


def verification_request_sha256(request: Mapping[str, Any]) -> str:
    unsigned = dict(request)
    unsigned.pop("request_sha256", None)
    return hashlib.sha256(json.dumps(unsigned, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def verification_request_hash_valid(request: Mapping[str, Any]) -> bool:
    supplied = str(request.get("request_sha256") or "")
    return bool(supplied) and supplied == verification_request_sha256(request)

PAGE_RENDERER_BACKENDS = ("pypdfium2",)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict): raise ValueError(f"Expected JSON object: {path}")
    return value


def _write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""): digest.update(chunk)
    return digest.hexdigest()


def canonical_evidence_sha256(value: Any) -> str:
    """Hash a machine-readable evidence value using one canonical encoding."""
    return hashlib.sha256(json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")).hexdigest()


def _normalized_ooxml_hash(element: ET._Element, *, redact_text: bool = True) -> str:
    clone = ET.fromstring(ET.tostring(element))
    for node in clone.iter():
        for attribute in list(node.attrib):
            if ET.QName(attribute).localname.startswith("rsid"):
                del node.attrib[attribute]
        if redact_text and ET.QName(node).localname in {"t", "delText"}:
            node.text = "#TEXT" if node.text else ""
    return hashlib.sha256(ET.tostring(clone, method="c14n")).hexdigest()


def normalized_docx_format_signature(path: Path) -> dict[str, Any]:
    """Return semantic, text-normalized OOXML format evidence for one DOCX."""
    with zipfile.ZipFile(path) as archive:
        document_xml = ET.fromstring(archive.read("word/document.xml"))
        styles_xml = ET.fromstring(archive.read("word/styles.xml"))
        numbering_xml = ET.fromstring(archive.read("word/numbering.xml"))
        settings_xml = ET.fromstring(archive.read("word/settings.xml"))
        headers_footers = []
        for name in sorted(
            item for item in archive.namelist()
            if re.fullmatch(r"word/(?:header|footer)\d+\.xml", item)
        ):
            root = ET.fromstring(archive.read(name))
            fields = [" ".join(str(node.text or "").split()) for node in root.xpath(".//*[local-name()='instrText']")]
            headers_footers.append({
                "part": name,
                "semantic_sha256": _normalized_ooxml_hash(root),
                "fields": fields,
                "table_count": len(root.xpath(".//*[local-name()='tbl']")),
            })

    section_geometry = []
    for section in document_xml.xpath(".//*[local-name()='sectPr']"):
        item: dict[str, Any] = {}
        for child_name in ("pgSz", "pgMar", "cols", "type"):
            matches = section.xpath(f"./*[local-name()='{child_name}']")
            child = matches[0] if matches else None
            item[child_name] = (
                {ET.QName(key).localname: value for key, value in sorted(child.attrib.items())}
                if child is not None else None
            )
        section_geometry.append(item)

    table_geometry = []
    for table in document_xml.xpath(".//*[local-name()='tbl']"):
        rows = table.xpath("./*[local-name()='tr']")
        table_geometry.append({
            "grid_widths": [node.get(qn("w:w"), "") for node in table.xpath("./*[local-name()='tblGrid']/*[local-name()='gridCol']")],
            "row_count": len(rows),
            "repeating_header_rows": sum(bool(row.xpath("./*[local-name()='trPr']/*[local-name()='tblHeader']")) for row in rows),
            "non_splitting_rows": sum(bool(row.xpath("./*[local-name()='trPr']/*[local-name()='cantSplit']")) for row in rows),
            "semantic_sha256": _normalized_ooxml_hash(table),
        })

    paragraphs = document_xml.xpath(".//*[local-name()='body']//*[local-name()='p']")
    paragraph_records = []
    visible_paragraphs = []
    for index, paragraph in enumerate(paragraphs):
        text = " ".join("".join(str(node.text or "") for node in paragraph.xpath(".//*[local-name()='t']")).split())
        style_nodes = paragraph.xpath("./*[local-name()='pPr']/*[local-name()='pStyle']")
        style = style_nodes[0].get(qn("w:val"), "") if style_nodes else ""
        ppr = paragraph.xpath("./*[local-name()='pPr']")
        paragraph_records.append({
            "style": style,
            "ppr_sha256": _normalized_ooxml_hash(ppr[0]) if ppr else None,
            "run_property_sha256": [_normalized_ooxml_hash(node) for node in paragraph.xpath("./*[local-name()='r']/*[local-name()='rPr']")],
        })
        if text:
            visible_paragraphs.append((index, text, style, paragraph))

    signature_pattern = re.compile(r"\b(?:signature|signed|participant name|investigator name)\b", re.I)
    legal_pattern = re.compile(r"\b(?:consent|authorization|privacy|confidential|injury|compensation|withdraw|voluntary)\b", re.I)
    signature_blocks = [
        {"paragraph": index, "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "style": style}
        for index, text, style, _ in visible_paragraphs if signature_pattern.search(text)
    ]
    legal_terms = ("consent", "authorization", "privacy", "confidential", "injury", "compensation", "withdraw", "voluntary")
    consent_legal_placement = [
        {
            "paragraph": index,
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "style": style,
            "categories": [term for term in legal_terms if re.search(rf"\b{term}\w*\b", text, re.I)],
        }
        for index, text, style, _ in visible_paragraphs if legal_pattern.search(text)
    ]
    headings = []
    protocol_document = path.name == "protocol.docx"
    style_page_breaks = {
        str(style_node.get(qn("w:styleId"), ""))
        for style_node in styles_xml.xpath(".//*[local-name()='style']")
        if style_node.xpath("./*[local-name()='pPr']/*[local-name()='pageBreakBefore']")
    }
    for index, text, style, paragraph in visible_paragraphs:
        if not style.casefold().startswith("heading"):
            continue
        ppr_matches = paragraph.xpath("./*[local-name()='pPr']")
        ppr = ppr_matches[0] if ppr_matches else None
        direct_page_break = bool(ppr is not None and ppr.xpath("./*[local-name()='pageBreakBefore']"))
        effective_page_boundary = direct_page_break or style in style_page_breaks
        if protocol_document and not effective_page_boundary:
            previous = paragraph.getprevious()
            while previous is not None and ET.QName(previous).localname == "p":
                if previous.xpath('.//*[local-name()="br" and @*[local-name()="type"]="page"]'):
                    effective_page_boundary = True
                    break
                section = previous.xpath("./*[local-name()='pPr']/*[local-name()='sectPr']")
                if section and not section[0].xpath(
                    "./*[local-name()='type' and @*[local-name()='val']='continuous']"
                ):
                    effective_page_boundary = True
                    break
                if previous.xpath('.//*[local-name()="t" and normalize-space(text())]'):
                    break
                previous = previous.getprevious()
        headings.append({
            "paragraph": index,
            "text": text,
            "style": style,
            "page_break_before": direct_page_break,
            **({"effective_page_boundary": effective_page_boundary} if protocol_document else {}),
            "keep_with_next": bool(ppr is not None and ppr.xpath("./*[local-name()='keepNext']")),
        })
    field_codes = [" ".join(str(node.text or "").split()) for node in document_xml.xpath(".//*[local-name()='instrText']")]
    page_fields = sum("PAGE" in value.upper() for value in field_codes) + sum(
        "PAGE" in value.upper() for part in headers_footers for value in part["fields"]
    )
    update_fields = bool(settings_xml.xpath(".//*[local-name()='updateFields' and (@*[local-name()='val']='true' or @*[local-name()='val']='1')]"))
    numbered_headings = [
        item for item in headings if re.match(r"^\d+(?:\.|\s)", item["text"])
    ]
    toc_index = next((
        index for index, item in enumerate(headings)
        if "table of contents" in re.sub(r"[^a-z0-9]+", " ", item["text"].casefold())
    ), None)
    body_headings = (
        [
            item for item in headings[toc_index + 1:]
            if re.match(r"^\d+(?:\.|\s)", item["text"])
        ]
        if toc_index is not None
        else numbered_headings
    )
    first_numbered = body_headings[0]["paragraph"] if body_headings else None
    later_body_headings = body_headings[1:] if toc_index is not None else body_headings
    return {
        "section_geometry": section_geometry,
        "styles": {"count": len(styles_xml.xpath(".//*[local-name()='style']")), "semantic_sha256": _normalized_ooxml_hash(styles_xml, redact_text=False)},
        "numbering": {
            "abstract_count": len(numbering_xml.xpath(".//*[local-name()='abstractNum']")),
            "number_count": len(numbering_xml.xpath(".//*[local-name()='num']")),
            "semantic_sha256": _normalized_ooxml_hash(numbering_xml, redact_text=False),
        },
        "headers_footers": headers_footers,
        "fields_toc": {"codes": field_codes, "update_fields": update_fields},
        "page_furniture": {
            "header_count": sum(item["part"].startswith("word/header") for item in headers_footers),
            "footer_count": sum(item["part"].startswith("word/footer") for item in headers_footers),
            "page_field_count": page_fields,
        },
        "table_geometry": table_geometry,
        "signature_blocks": signature_blocks,
        "consent_legal_placement": consent_legal_placement,
        "paragraph_rhythm": {"paragraph_count": len(paragraph_records), "semantic_sha256": canonical_evidence_sha256(paragraph_records)},
        "pagination_relations": {
            "headings": headings,
            "first_numbered_body_paragraph": first_numbered,
            "numbered_body_has_no_artificial_starts": all(
                not item["page_break_before"] for item in later_body_headings
            ),
            "all_headings_keep_with_next": all(item["keep_with_next"] for item in headings),
        },
    }


def _rendered_pagination_relations(docx_path: Path, pdf_path: Path) -> dict[str, Any]:
    document = Document(docx_path)
    pages = [
        re.sub(r"[^a-z0-9]+", " ", (page.extract_text() or "").casefold()).strip()
        for page in PdfReader(pdf_path).pages
    ]
    body = list(document.element.body)
    protocol = docx_path.name == "protocol.docx"
    headings = [
        paragraph for paragraph in document.paragraphs
        if paragraph.style.name.casefold().startswith("heading")
        and (not protocol or re.match(r"^\d+(?:\.\d+)*\.?\s+", paragraph.text.strip()))
        and (protocol or paragraph.style.name == "Heading ICF Section")
        and paragraph.text.strip()
        and "TITLE PAGE" not in paragraph.text.upper()
        and "TABLE OF CONTENTS" not in paragraph.text.upper()
    ]
    cohesion = []
    for heading in headings:
        heading_index = body.index(heading._p)
        first_content = ""
        for element in body[heading_index + 1:]:
            if element.tag == qn("w:tbl"):
                table = Table(element, document)
                first_content = " ".join(cell.text for cell in table.rows[0].cells) if table.rows else ""
                break
            if element.tag != qn("w:p"):
                continue
            paragraph = Paragraph(element, document)
            if paragraph.style.name.casefold().startswith("heading"):
                first_content = paragraph.text
                break
            if paragraph.text.strip():
                first_content = paragraph.text
                break
        heading_tokens = re.findall(r"[a-z0-9]+", heading.text.casefold())
        content_marker = " ".join(re.findall(r"[a-z0-9]+", first_content.casefold())[:4])
        together = False
        if first_content and heading_tokens and content_marker:
            for page in pages:
                if protocol:
                    heading_marker = " ".join(heading_tokens)
                    if heading_marker not in page:
                        continue
                    heading_end = page.index(heading_marker) + len(heading_marker)
                else:
                    first = page.find(heading_tokens[0])
                    if first < 0:
                        continue
                    heading_end = first + len(heading_tokens[0])
                    if len(heading_tokens) > 1:
                        second = page.find(heading_tokens[1], heading_end)
                        if second < 0:
                            continue
                        heading_end = second + len(heading_tokens[1])
                remainder = page[heading_end:]
                if protocol and content_marker in remainder:
                    together = True
                    break
                if not protocol:
                    content_tokens = [
                        token for token in re.findall(r"[a-z0-9]+", first_content.casefold())
                        if token not in {"a", "an", "the", "this"}
                    ][:3]
                    cursor = 0
                    for token in content_tokens:
                        position = remainder.find(token, cursor)
                        if position < 0:
                            break
                        cursor = position + len(token)
                    else:
                        if content_tokens:
                            together = True
                            break
        cohesion.append({
            "heading": heading.text.strip(),
            "first_content_sha256": hashlib.sha256(first_content.encode("utf-8")).hexdigest() if first_content else None,
            "same_page": together,
        })
    section_three = next((paragraph.text.strip() for paragraph in headings if "GENERAL INFORMATION" in paragraph.text.upper()), None)
    section_three_flow = True
    if section_three:
        marker = " ".join(re.findall(r"[a-z0-9]+", section_three.casefold()))
        section_three_page = next((page for page in pages if marker in page and "table of contents" not in page), "")
        section_three_flow = "2 investigator agreement" in section_three_page
    return {
        "pdf_sha256": sha256_file(pdf_path),
        "heading_cohesion": cohesion,
        "all_headings_with_first_content": bool(cohesion) and all(item["same_page"] for item in cohesion),
        "natural_section_3_flow": section_three_flow,
    }


def audit_format_conformance_outputs(
    repo_root: Path,
    matrix: Mapping[str, Any],
    release_gate_report: Mapping[str, Any],
    evidence_root: Path,
) -> dict[str, Any]:
    """Compare generated deterministic DOCX semantics with approved baselines."""
    selected_cases = {
        "retrospective-protocol": "retrospective-sparse-complete",
        "prospective-advarra": "prospective-sparse-complete",
        "prospective-sterling": "prospective-rich-complete",
        "ambispective-advarra": "ambispective-sparse-complete",
        "ambispective-sterling": "ambispective-rich-complete",
    }
    reported = {str(item.get("case")): item for item in release_gate_report.get("cases", []) if isinstance(item, Mapping)}
    results = []
    for case in matrix.get("cases", []):
        case_id = str(case.get("case_id") or "")
        lifecycle_case = selected_cases.get(case_id, "")
        gate_case = reported.get(lifecycle_case, {})
        findings = []
        baseline_record = case.get("approved_output_baseline", {})
        baseline_path = repo_root / str(baseline_record.get("path") or "")
        if not baseline_path.is_file() or sha256_file(baseline_path) != baseline_record.get("sha256"):
            findings.append({"code": "FORMAT_BASELINE_IDENTITY_MISMATCH", "target": case_id})
            baseline = {"artifacts": {}}
        else:
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        revision_id = str((gate_case.get("result") or {}).get("revision_id") or "")
        revision_dir = evidence_root / lifecycle_case / "revisions" / revision_id
        candidate_dir = revision_dir / "candidate"
        actual_artifacts = {}
        for artifact, expected_signature in baseline.get("artifacts", {}).items():
            artifact_path = candidate_dir / artifact
            if not artifact_path.is_file():
                findings.append({"code": "FORMAT_CANDIDATE_MISSING", "target": f"{case_id}:{artifact}"})
                continue
            actual_signature = normalized_docx_format_signature(artifact_path)
            actual_artifacts[artifact] = {"sha256": sha256_file(artifact_path), "signature_sha256": canonical_evidence_sha256(actual_signature)}
            pdf_path = revision_dir / "rendered" / f"{artifact_path.stem}.pdf"
            if not pdf_path.is_file():
                findings.append({"code": "FORMAT_RENDERED_PDF_MISSING", "target": f"{case_id}:{artifact}"})
            else:
                relations = _rendered_pagination_relations(artifact_path, pdf_path)
                actual_artifacts[artifact]["rendered_pagination"] = relations
                if not relations["all_headings_with_first_content"]:
                    findings.append({"code": "FORMAT_ORPHAN_HEADING", "target": f"{case_id}:{artifact}"})
                if artifact == "protocol.docx" and not relations["natural_section_3_flow"]:
                    findings.append({"code": "FORMAT_SECTION_3_FLOW_BROKEN", "target": f"{case_id}:{artifact}#section=3"})
            if actual_signature != expected_signature:
                findings.append({
                    "code": "FORMAT_BASELINE_MISMATCH",
                    "target": f"{case_id}:{artifact}",
                    "expected_signature_sha256": canonical_evidence_sha256(expected_signature),
                    "actual_signature_sha256": canonical_evidence_sha256(actual_signature),
                })
        results.append({
            "case_id": case_id,
            "status": "passed" if not findings else "blocked",
            "baseline_sha256": baseline_record.get("sha256"),
            "artifacts": actual_artifacts,
            "findings": findings,
        })
    return {
        "status": "passed" if results and all(item["status"] == "passed" for item in results) else "blocked",
        "cases": results,
        "evidence_sha256": canonical_evidence_sha256(results),
    }


def load_format_conformance_matrix(repo_root: Path) -> dict[str, Any]:
    """Load and independently rehash the deterministic format matrix."""
    root = repo_root.resolve()
    matrix = _json(root / FORMAT_CONFORMANCE_MATRIX)
    if matrix.get("schema_version") != "clinical-format-conformance/v1":
        raise ValueError("Format conformance matrix schema is invalid.")
    unsigned = dict(matrix)
    declared_sha256 = str(unsigned.pop("matrix_sha256", ""))
    if not declared_sha256 or declared_sha256 != canonical_evidence_sha256(unsigned):
        raise ValueError("Format conformance matrix identity is invalid.")
    gates = matrix.get("gate_sequence")
    if not isinstance(gates, list) or tuple(
        item.get("gate_id") for item in gates if isinstance(item, Mapping)
    ) != GOVERNED_GATE_SEQUENCE:
        raise ValueError("Format conformance gate order is invalid.")
    cases = matrix.get("cases")
    expected_cases = (
        "retrospective-protocol", "prospective-advarra", "prospective-sterling",
        "ambispective-advarra", "ambispective-sterling",
    )
    if not isinstance(cases, list) or tuple(
        item.get("case_id") for item in cases if isinstance(item, Mapping)
    ) != expected_cases:
        raise ValueError("Format conformance case inventory is invalid.")
    for case in cases:
        resources = [
            case.get("fixture"),
            case.get("approved_output_baseline"),
            *list(case.get("baselines") or []),
        ]
        for resource in resources:
            if not isinstance(resource, Mapping):
                raise ValueError("Format conformance resource declaration is invalid.")
            path_text = str(resource.get("path") or "")
            relative = PurePosixPath(path_text)
            if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != path_text:
                raise ValueError("Format conformance resource path is invalid.")
            target = root / relative
            if not target.is_file() or sha256_file(target) != resource.get("sha256"):
                raise ValueError(f"Format conformance resource identity is invalid: {relative}")
    return matrix


def validate_gate_ledger(repo_root: Path, ledger: Mapping[str, Any]) -> dict[str, Any]:
    """Reject reordered, stale, incomplete, or non-monotonic delivery gates."""
    matrix = load_format_conformance_matrix(repo_root)
    value = dict(ledger)
    if value.get("schema_version") != "clinical-gate-ledger/v1":
        raise ValueError("Gate ledger schema is invalid.")
    if value.get("matrix_sha256") != matrix.get("matrix_sha256"):
        raise ValueError("Gate ledger is not bound to the current conformance matrix.")
    attempt_id = str(value.get("attempt_id") or "")
    if not attempt_id:
        raise ValueError("Gate ledger attempt identity is missing.")
    unsigned = dict(value)
    declared_sha256 = str(unsigned.pop("ledger_sha256", ""))
    if not declared_sha256 or declared_sha256 != canonical_evidence_sha256(unsigned):
        raise ValueError("Gate ledger identity is invalid.")
    records = value.get("records")
    if not isinstance(records, list) or tuple(
        record.get("gate_id") for record in records if isinstance(record, Mapping)
    ) != GOVERNED_GATE_SEQUENCE:
        raise ValueError("Gate ledger sequence is invalid.")
    unresolved = False
    finding_fields = set(matrix["finding_contract"]["required"])
    predecessors = value.get("predecessors")
    if not isinstance(predecessors, list):
        raise ValueError("Gate ledger predecessor history is invalid.")
    predecessor_hashes = []
    gate_retry_owners = {
        str(item["gate_id"]): str(item["retry_owner"])
        for item in matrix["gate_sequence"]
    }
    for predecessor in predecessors:
        if not isinstance(predecessor, Mapping):
            raise ValueError("Gate ledger predecessor entry is invalid.")
        ledger_sha256 = str(predecessor.get("ledger_sha256") or "")
        blocked_findings = predecessor.get("blocked_findings")
        predecessor_code = f"{str(predecessor.get('terminal_gate')).upper()}_FAILED"
        if (
            predecessor.get("attempt_id") != attempt_id
            or not re.fullmatch(r"[0-9a-f]{64}", ledger_sha256)
            or predecessor.get("terminal_gate") not in GOVERNED_GATE_SEQUENCE
            or not isinstance(blocked_findings, list)
            or not blocked_findings
            or any(
                not isinstance(finding, Mapping)
                or not finding_fields <= set(finding)
                or not re.fullmatch(r"[A-Z][A-Z0-9_]+", str(finding.get("code") or ""))
                or finding.get("code") != predecessor_code
                or not str(finding.get("target") or "").strip()
                or not re.fullmatch(r"[0-9a-f]{64}", str(finding.get("evidence_sha256") or ""))
                or finding.get("retry_owner") != gate_retry_owners.get(str(predecessor.get("terminal_gate")))
                or finding.get("terminal_status") != "blocked"
                for finding in blocked_findings
            )
        ):
            raise ValueError("Gate ledger predecessor evidence is invalid.")
        predecessor_hashes.append(ledger_sha256)
    if len(predecessor_hashes) != len(set(predecessor_hashes)):
        raise ValueError("Gate ledger predecessor history contains duplicates.")
    for order, record in enumerate(records, start=1):
        if not isinstance(record, Mapping) or record.get("order") != order:
            raise ValueError("Gate ledger order is invalid.")
        status = str(record.get("terminal_status") or "")
        if status not in {"passed", "pending", "blocked"}:
            raise ValueError("Gate ledger terminal status is invalid.")
        if unresolved and status == "passed":
            raise ValueError(f"Gate {record.get('gate_id')} cannot pass after an unresolved earlier gate.")
        unresolved = unresolved or status != "passed"
        evidence_sha256 = str(record.get("evidence_sha256") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", evidence_sha256):
            raise ValueError("Gate evidence identity is invalid.")
        expected_retry_owner = gate_retry_owners.get(str(record.get("gate_id")))
        if record.get("retry_owner") != expected_retry_owner:
            raise ValueError("Gate retry ownership does not match the governed matrix.")
        findings = record.get("findings")
        governed_finding_code = f"{str(record.get('gate_id')).upper()}_FAILED"
        if not isinstance(findings, list) or any(
            not isinstance(finding, Mapping)
            or not finding_fields <= set(finding)
            or not re.fullmatch(r"[A-Z][A-Z0-9_]+", str(finding.get("code") or ""))
            or finding.get("code") != governed_finding_code
            or not str(finding.get("target") or "").strip()
            or not re.fullmatch(r"[0-9a-f]{64}", str(finding.get("evidence_sha256") or ""))
            or not str(finding.get("retry_owner") or "").strip()
            or finding.get("retry_owner") != record.get("retry_owner")
            or finding.get("terminal_status") != "blocked"
            for finding in findings
        ):
            raise ValueError("Gate finding contract is invalid.")
        if (status == "blocked") != bool(findings):
            raise ValueError("Only blocked gates may carry findings, and blocked gates require them.")
    return value


def build_gate_ledger(
    repo_root: Path,
    evidence_by_gate: Mapping[str, Any],
    *,
    attempt_id: str,
    predecessors: Iterable[Mapping[str, Any]] = (),
    statuses: Mapping[str, str] | None = None,
    findings_by_gate: Mapping[str, Iterable[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Build a canonical monotonic ledger from exact evidence values."""
    matrix = load_format_conformance_matrix(repo_root)
    if not str(attempt_id).strip():
        raise ValueError("Gate ledger attempt identity is required.")
    gates = {str(item["gate_id"]): item for item in matrix["gate_sequence"]}
    if set(evidence_by_gate) != set(GOVERNED_GATE_SEQUENCE):
        raise ValueError("Evidence must cover the complete governed gate sequence.")
    records = []
    for order, gate_id in enumerate(GOVERNED_GATE_SEQUENCE, start=1):
        status = str((statuses or {}).get(gate_id, "passed"))
        records.append({
            "order": order,
            "gate_id": gate_id,
            "terminal_status": status,
            "evidence_sha256": canonical_evidence_sha256(evidence_by_gate[gate_id]),
            "retry_owner": str(gates[gate_id]["retry_owner"]),
            "findings": [dict(item) for item in (findings_by_gate or {}).get(gate_id, [])],
        })
    if all(record["terminal_status"] == "passed" for record in records):
        raise ValueError("A complete passed ledger must advance from its final pending delivery gate.")
    ledger = {
        "schema_version": "clinical-gate-ledger/v1",
        "matrix_sha256": matrix["matrix_sha256"],
        "attempt_id": str(attempt_id),
        "predecessors": [dict(item) for item in predecessors],
        "records": records,
    }
    ledger["ledger_sha256"] = canonical_evidence_sha256(ledger)
    return validate_gate_ledger(repo_root, ledger)


def retry_gate_ledger(
    repo_root: Path,
    blocked_ledger: Mapping[str, Any],
    evidence_by_gate: Mapping[str, Any],
    *,
    statuses: Mapping[str, str],
    findings_by_gate: Mapping[str, Iterable[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Create one linked retry while retaining the exact terminal blocked ledger."""
    prior = validate_gate_ledger(repo_root, blocked_ledger)
    blocked_records = [
        record for record in prior["records"]
        if record["terminal_status"] == "blocked"
    ]
    if len(blocked_records) != 1:
        raise ValueError("A retry requires exactly one terminal blocked predecessor gate.")
    blocked = blocked_records[0]
    predecessor = {
        "attempt_id": prior["attempt_id"],
        "ledger_sha256": prior["ledger_sha256"],
        "terminal_gate": blocked["gate_id"],
        "blocked_findings": [dict(item) for item in blocked["findings"]],
    }
    return build_gate_ledger(
        repo_root,
        evidence_by_gate,
        attempt_id=str(prior["attempt_id"]),
        predecessors=[*list(prior["predecessors"]), predecessor],
        statuses=statuses,
        findings_by_gate=findings_by_gate,
    )


def advance_gate_ledger(
    repo_root: Path,
    ledger: Mapping[str, Any],
    *,
    gate_id: str,
    terminal_status: str,
    evidence: Any,
    findings: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Advance only the first unresolved gate and bind its replacement evidence."""
    current = validate_gate_ledger(repo_root, ledger)
    records = [dict(record) for record in current["records"]]
    unresolved = next(
        (record for record in records if record["terminal_status"] != "passed"),
        None,
    )
    if unresolved is None or unresolved["gate_id"] != gate_id:
        raise ValueError(f"Only the first unresolved gate may advance; requested {gate_id}.")
    if unresolved["terminal_status"] == "blocked":
        raise ValueError(f"A terminal blocked gate cannot advance; start a new retained attempt for {gate_id}.")
    unresolved["terminal_status"] = terminal_status
    unresolved["evidence_sha256"] = canonical_evidence_sha256(evidence)
    unresolved["findings"] = [dict(item) for item in findings]
    advanced = {
        "schema_version": current["schema_version"],
        "matrix_sha256": current["matrix_sha256"],
        "attempt_id": current["attempt_id"],
        "predecessors": list(current["predecessors"]),
        "records": records,
    }
    advanced["ledger_sha256"] = canonical_evidence_sha256(advanced)
    return validate_gate_ledger(repo_root, advanced)


def release_certification_payload(report: Mapping[str, Any]) -> bytes:
    """Canonical bytes covered by the detached release-certification signature."""
    unsigned = dict(report)
    unsigned.pop("evidence_attestation", None)
    return json.dumps(
        unsigned,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _canonical_sha256_value(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")).hexdigest()


def release_certification_key_id(key: Mapping[str, Any]) -> str:
    """Return the canonical identity shared by certification signers and verifiers."""
    identity = {
        "algorithm": str(key.get("algorithm") or ""),
        "exponent": int(str(key.get("exponent") or "")),
        "modulus": format(int(str(key.get("modulus") or ""), 16), "x"),
    }
    return _canonical_sha256_value(identity)


def _validated_certification_evidence(bundle: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Decode one bounded canonical evidence inventory and rehash every byte."""
    if bundle.get("schema_version") != "release-certification-evidence/v1":
        raise ValueError("Certification evidence bundle schema is invalid.")
    entries = bundle.get("entries")
    if not isinstance(entries, list) or not entries or len(entries) > CERTIFICATION_EVIDENCE_MAX_FILES:
        raise ValueError("Certification evidence bundle has an invalid file count.")
    identities: set[str] = set()
    paths: set[str] = set()
    total_bytes = 0
    decoded: list[dict[str, Any]] = []
    for raw_item in entries:
        if not isinstance(raw_item, Mapping):
            raise ValueError("Certification evidence inventory item is invalid.")
        item = dict(raw_item)
        identity = str(item.get("identity") or "")
        identity_key = identity.casefold()
        if not identity or identity_key in identities:
            raise ValueError("Certification evidence contains a duplicate evidence identity.")
        identities.add(identity_key)
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", identity):
            raise ValueError("Certification evidence identity is noncanonical.")
        path_text = str(item.get("path") or "")
        relative = PurePosixPath(path_text)
        if (
            not path_text
            or "\\" in path_text
            or any(part in {"", ".", ".."} for part in path_text.split("/"))
            or relative.is_absolute()
            or relative.as_posix() != path_text
            or relative.parts[0] not in {"global", "cases"}
        ):
            raise ValueError(f"Certification evidence has a noncanonical evidence path: {path_text}")
        path_key = path_text.casefold()
        if path_key in paths:
            raise ValueError("Certification evidence contains a duplicate evidence path.")
        paths.add(path_key)
        declared_bytes = item.get("bytes")
        if isinstance(declared_bytes, bool) or not isinstance(declared_bytes, int):
            raise ValueError("Certification evidence byte length is invalid.")
        if declared_bytes < 0 or declared_bytes > CERTIFICATION_EVIDENCE_MAX_ITEM_BYTES:
            raise ValueError("Certification evidence item exceeds the governed byte limit.")
        try:
            content = base64.b64decode(
                str(item.get("content_base64") or ""), validate=True
            )
        except (binascii.Error, ValueError) as exc:
            raise ValueError("Certification evidence content is not strict base64.") from exc
        if (
            len(content) != declared_bytes
            or hashlib.sha256(content).hexdigest() != item.get("sha256")
        ):
            raise ValueError("Certification evidence bytes do not match the inventory.")
        total_bytes += declared_bytes
        if total_bytes > CERTIFICATION_EVIDENCE_MAX_TOTAL_BYTES:
            raise ValueError("Certification evidence bundle exceeds the governed byte limit.")
        decoded.append({**item, "content": content})
    return decoded


def _certification_evidence_findings(
    report: Mapping[str, Any],
    manifest: Mapping[str, Any],
    manifest_bytes: bytes,
) -> list[str]:
    """Independently derive certification claims from retained evidence bytes."""
    bundle = report.get("evidence_bundle") or {}
    try:
        entries = _validated_certification_evidence(bundle)
    except ValueError as exc:
        return [str(exc)]
    metadata = [
        {key: value for key, value in item.items() if key not in {"content", "content_base64"}}
        for item in entries
    ]
    if (
        bundle.get("inventory_sha256") != _canonical_sha256_value(metadata)
        or bundle.get("total_bytes") != sum(item["bytes"] for item in entries)
    ):
        return ["Certification evidence inventory identity or total byte count is invalid."]
    allowed_kinds = {
        "release_manifest", "preflight", "preflight_log", "layout_preservation", "deterministic_corpus",
        "runtime_identity", "case_report", "desktop_operation_state", "delivery_manifest",
        "output", "delivery_confirmation", "drafting_request", "drafting_response",
        "verification_request", "verification_response", "delegated_page_review",
        "parent_page_review", "parent_process_marker",
        "fixture_manifest", "fixture_source", "approved_source", "approved_reference", "pdf", "page_image",
    }
    findings: list[str] = []
    indexed: dict[tuple[str | None, str], list[dict[str, Any]]] = {}
    parsed: dict[str, dict[str, Any] | None] = {}
    consumed_identities: set[str] = set()
    for item in entries:
        identity_key = str(item["identity"])
        kind = str(item.get("kind") or "")
        case_id = item.get("case_id")
        path = str(item.get("path") or "")
        if kind not in allowed_kinds:
            findings.append(f"Evidence kind is not release-authorized: {kind!r}.")
            continue
        if case_id is None:
            if not path.startswith("global/"):
                findings.append(f"Global evidence has a case path: {path}.")
        elif case_id not in CERTIFICATION_CASE_ORDER or not path.startswith(f"cases/{case_id}/"):
            findings.append(f"Case evidence is mis-scoped: {path}.")
        indexed.setdefault((case_id, kind), []).append(item)
        if kind not in {"output", "pdf", "page_image", "release_manifest"}:
            try:
                value = json.loads(item["content"])
                parsed[identity_key] = value if isinstance(value, dict) else None
            except (UnicodeDecodeError, json.JSONDecodeError):
                parsed[identity_key] = None

    def items(case_id: str | None, kind: str) -> list[dict[str, Any]]:
        return indexed.get((case_id, kind), [])

    def consume(evidence: Iterable[Mapping[str, Any]]) -> None:
        consumed_identities.update(str(item.get("identity") or "") for item in evidence)

    def one(case_id: str | None, kind: str) -> dict[str, Any] | None:
        matches = items(case_id, kind)
        if len(matches) != 1:
            findings.append(f"Exactly one {kind!r} item is required for {case_id or 'global'}.")
            return None
        consume(matches)
        return matches[0]

    def payload(item: Mapping[str, Any] | None) -> dict[str, Any]:
        return parsed.get(str((item or {}).get("identity") or "")) or {}

    manifest_item = one(None, "release_manifest")
    if manifest_item is not None and manifest_item["content"] != manifest_bytes:
        findings.append("Retained release-manifest bytes do not match the installed manifest.")
    identity = report.get("release_identity") or {}
    preflight_item = one(None, "preflight")
    preflight = payload(preflight_item)
    required_checks = {
        "layout_preservation_corpus", "deterministic_branch_acceptance_corpus",
        "repository_regression_suite", "static_release_checks",
    }
    check_values = preflight.get("checks") or {}
    if (
        preflight_item is None
        or preflight_item.get("sha256") != report.get("preflight_evidence_sha256")
        or preflight.get("status") != "passed"
        or any(
            (preflight.get("candidate") or {}).get(key) != identity.get(key)
            for key in ("package_fingerprint", "git_commit")
        )
        or set(check_values) != required_checks
        or any(
            not isinstance(value, Mapping)
            or value.get("status") != "passed"
            or value.get("returncode") != 0
            for value in check_values.values()
        )
    ):
        findings.append("Preflight evidence does not independently pass every required check.")
    layout_item = one(None, "layout_preservation")
    layout = payload(layout_item)
    layout_summary = report.get("layout_preservation_evidence") or {}
    layout_check = check_values.get("layout_preservation_corpus") or {}
    if (
        layout_item is None
        or layout_item.get("sha256") != layout_summary.get("sha256")
        or not (
            layout.get("status") == "passed" and layout.get("returncode") == 0
            or isinstance(layout_check, Mapping)
            and layout_check.get("status") == "passed"
            and layout_check.get("returncode") == 0
            and layout_check.get("sha256") == layout_item.get("sha256")
        )
        or set((layout or layout_check).get("coverage") or []) != set(layout_summary.get("coverage") or [])
    ):
        findings.append("Layout-preservation evidence is incomplete or stale.")
    deterministic_item = one(None, "deterministic_corpus")
    deterministic = payload(deterministic_item)
    deterministic_check = check_values.get("deterministic_branch_acceptance_corpus") or {}
    if (
        not (
            deterministic.get("status") == "passed"
            and set(deterministic.get("case_ids") or []) == set(DETERMINISTIC_BRANCH_ACCEPTANCE_CASES)
            or isinstance(deterministic_check, Mapping)
            and deterministic_check.get("status") == "passed"
            and deterministic_check.get("returncode") == 0
            and deterministic_item is not None
            and deterministic_check.get("sha256") == deterministic_item.get("sha256")
            and set(deterministic_check.get("case_ids") or []) == set(DETERMINISTIC_BRANCH_ACCEPTANCE_CASES)
        )
    ):
        findings.append("Deterministic branch-acceptance evidence is incomplete.")
    preflight_logs = {
        str(item.get("identity") or ""): item
        for item in items(None, "preflight_log")
    }
    consume(preflight_logs.values())
    required_preflight_logs = {
        "static_release_checks", "repository_regression_suite",
    }
    if (
        set(preflight_logs) != required_preflight_logs
        or any(
            not isinstance(check_values.get(name), Mapping)
            or check_values[name].get("sha256") != preflight_logs[name].get("sha256")
            for name in required_preflight_logs
        )
    ):
        findings.append("Static and repository-regression preflight logs are incomplete.")
    runtime = payload(one(None, "runtime_identity"))
    configurations = report.get("hermes_configurations") or {}
    expected_modules = {
        item["path"]: item["sha256"]
        for item in manifest.get("files") or []
        if str(item.get("path") or "").startswith("scripts/")
        and str(item.get("path") or "").endswith(".py")
    }
    if (
        runtime.get("release_identity") != identity
        or runtime.get("python") != preflight.get("python_runtime")
        or runtime.get("page_renderer") != (manifest.get("inventory") or {}).get("pdf_page_renderer")
        or runtime.get("production_modules") != expected_modules
        or not str((runtime.get("python") or {}).get("version") or "")
        or not re.fullmatch(r"[0-9a-f]{64}", str((runtime.get("python") or {}).get("executable_sha256") or ""))
        or runtime.get("hermes_configuration_sha256") != {
            fixture: _canonical_sha256_value(configuration) for fixture, configuration in configurations.items()
        }
    ):
        findings.append("Python, worker, skill, renderer, or Hermes configuration identity is invalid.")

    cases = {str(item.get("fixture_id") or ""): item for item in report.get("cases") or []}
    for fixture in CERTIFICATION_CASE_ORDER:
        case = cases.get(fixture) or {}
        models = set(case.get("model_identifiers") or [])
        case_item = one(fixture, "case_report")
        case_payload = payload(case_item)
        state = payload(one(fixture, "desktop_operation_state"))
        delivery_manifest = payload(one(fixture, "delivery_manifest"))
        delivery = payload(one(fixture, "delivery_confirmation"))
        raw_case_identity = case_payload.get("release_identity") or {}
        if (
            case_item is None or case_item.get("sha256") != case.get("report_sha256")
            or case_payload.get("status", case_payload.get("outcome")) != "passed"
            or {key: raw_case_identity.get(key) for key in identity} != identity
            or case_payload.get("hermes_configuration") != configurations.get(fixture)
            or set(case_payload.get("model_identifiers") or []) != models
        ):
            findings.append(f"Case report is incomplete or stale for {fixture}.")
        state_identity = state.get("release_identity") or {}
        if (
            state.get("status") != "passed"
            or (state.get("result") or {}).get("status") != "passed"
            or not ((state.get("result") or {}).get("delivery") or {}).get("confirmed")
            or not (state.get("cleanup") or {}).get("owned_processes_reaped")
            or {key: state_identity.get(key) for key in identity} != identity
            or state_identity.get("hermes_configuration") != configurations.get(fixture)
        ):
            findings.append(f"Desktop operation evidence does not pass for {fixture}.")
        expected_outputs = {str(item.get("path") or ""): item for item in case.get("output_evidence") or []}
        actual_outputs = {
            str(item["path"])[len(f"cases/{fixture}/"):]: item for item in items(fixture, "output")
        }
        consume(actual_outputs.values())
        if set(actual_outputs) != set(expected_outputs):
            findings.append(f"Output evidence does not cover the delivered set for {fixture}.")
        for path, expected in expected_outputs.items():
            actual = actual_outputs.get(path) or {}
            if actual.get("sha256") != expected.get("sha256") or actual.get("bytes") != expected.get("bytes") or expected.get("confirmed") is not True:
                findings.append(f"Output bytes do not match {fixture}:{path}.")
        manifest_outputs = {
            str(item.get("path") or ""): {
                key: item.get(key) for key in ("path", "sha256", "bytes")
            }
            for item in delivery_manifest.get("client_outputs") or []
        }
        expected_manifest_outputs = {
            path: {key: item.get(key) for key in ("path", "sha256", "bytes")}
            for path, item in expected_outputs.items()
        }
        opened_outputs = {str(item.get("path") or ""): item for item in delivery.get("opened") or []}
        if (
            delivery_manifest.get("status") != "passed"
            or (delivery_manifest.get("quality") or {}).get("status") != "passed"
            or manifest_outputs != expected_manifest_outputs
            or delivery.get("confirmed") is not True
            or opened_outputs != expected_outputs
        ):
            findings.append(f"Delivery evidence is invalid for {fixture}.")
        draft_request_items = items(fixture, "drafting_request")
        draft_response_items = items(fixture, "drafting_response")
        consume(draft_request_items)
        consume(draft_response_items)
        draft_requests = {payload(item).get("request_id"): payload(item) for item in draft_request_items}
        draft_responses = [payload(item) for item in draft_response_items]
        if (
            not draft_requests
            or len(draft_requests) != len(draft_responses)
            or any(
                not (request := draft_requests.get(response.get("request_id")))
                or response.get("request_sha256") != request.get("request_sha256")
                or response.get("status") not in {None, "passed"}
                or (response.get("producer") or {}).get("model_id") not in models
                for response in draft_responses
            )
        ):
            findings.append(f"Drafting worker evidence is incomplete for {fixture}.")
        fixture_manifest = payload(one(fixture, "fixture_manifest"))
        fixture_source = one(fixture, "fixture_source")
        approved_source = one(fixture, "approved_source")
        approved_reference = one(fixture, "approved_reference")
        provenance = fixture_manifest.get("provenance") or fixture_manifest
        if provenance.get("synthetic") is not True or provenance.get("contains_private_data") is not False:
            findings.append(f"Fixture evidence is not explicitly synthetic and non-private for {fixture}.")
        artifact_entries = {
            "source_input": fixture_source,
            "approved_source": approved_source,
            "approved_reference": approved_reference,
        }
        manifest_artifacts = fixture_manifest.get("artifacts") or {}
        if any(
            entry is None
            or (manifest_artifacts.get(name) or {}).get("sha256") != entry.get("sha256")
            for name, entry in artifact_entries.items()
        ):
            findings.append(f"Retained fixture source bytes do not match the governed fixture manifest for {fixture}.")
        normalization = fixture_manifest.get("approved_normalization") or {}
        if (
            normalization.get("source_input_sha256") != (fixture_source or {}).get("sha256")
            or normalization.get("approved_source_sha256") != (approved_source or {}).get("sha256")
        ):
            findings.append(f"Retained approved source normalization is invalid for {fixture}.")
        request_items = items(fixture, "verification_request")
        response_items = items(fixture, "verification_response")
        consume(request_items)
        consume(response_items)
        requests = [(item, payload(item)) for item in request_items]
        content_requests = [(item, value) for item, value in requests if value.get("task") == "clinical_content_verification"]
        content_responses = [(item, payload(item)) for item in response_items]
        if len(content_requests) != 1 or len(content_responses) != 1:
            findings.append(f"Content verification evidence is incomplete for {fixture}.")
        else:
            request = content_requests[0][1]
            response = content_responses[0][1]
            if (
                response.get("request_id") != request.get("request_id")
                or response.get("request_sha256") != request.get("request_sha256")
                or response.get("task") != request.get("task")
                or response.get("status") != "passed"
                or (response.get("producer") or {}).get("model_id") not in models
                or not response.get("section_assessments")
                or any(item.get("status") != "passed" for item in response.get("section_assessments") or [])
                or not response.get("cross_document_assessments")
                or any(item.get("status") != "passed" for item in response.get("cross_document_assessments") or [])
            ):
                findings.append(f"Content verification does not pass for {fixture}.")
        visual_requests = [(item, value) for item, value in requests if value.get("task") == "rendered_page_visual_verification"]
        parent_review_items = items(fixture, "parent_page_review")
        delegated_review_items = items(fixture, "delegated_page_review")
        consume(parent_review_items)
        consume(delegated_review_items)
        visual_reviews = [
            (item, payload(item))
            for item in [*parent_review_items, *delegated_review_items]
        ]
        parent_marker_items = items(fixture, "parent_process_marker")
        consume(parent_marker_items)
        parent_marker = payload(parent_marker_items[0]) if len(parent_marker_items) == 1 else {}
        visual_summary = case.get("visual_qa") or {}
        if len(visual_requests) != len(visual_summary) or len(visual_reviews) != len(visual_summary):
            findings.append(f"Every-page review set is incomplete for {fixture}.")
        if parent_review_items and (
            len(parent_marker_items) != 1
            or parent_marker.get("status") != "completed"
            or parent_marker.get("completion_requirement")
            != "Desktop parent must inspect every bound page image."
            or parent_marker.get("required_producer_model_id") not in models
        ):
            findings.append(f"Desktop-parent review completion evidence is invalid for {fixture}.")
        if not parent_review_items and parent_marker_items:
            findings.append(f"Unexpected Desktop-parent marker exists without fallback review evidence for {fixture}.")
        for artifact, visual in visual_summary.items():
            request_pair = next((pair for pair in visual_requests if pair[0].get("sha256") == visual.get("request_sha256")), None)
            review_pair = next((
                pair for pair in visual_reviews
                if any(part.get("artifact") == artifact for part in pair[1].get("page_assessments") or [])
            ), None)
            pdf = next((item for item in items(fixture, "pdf") if str(item["path"]).endswith(f"/{artifact}.pdf")), None)
            page_items = [item for item in items(fixture, "page_image") if f"/pages/{artifact}/" in str(item["path"])]
            consume([pdf] if pdf is not None else [])
            consume(page_items)
            expected_pages = list(visual.get("page_sha256") or [])
            request_item, request = request_pair or ({}, {})
            review_item, review = review_pair or ({}, {})
            assessments = review.get("page_assessments") or []
            docx = actual_outputs.get(f"output/{artifact}.docx") or {}
            retained_page_sha256 = [item.get("sha256") for item in page_items]
            request_artifacts = [
                item for item in request.get("artifacts") or []
                if item.get("artifact") == artifact
            ]
            request_artifact = request_artifacts[0] if len(request_artifacts) == 1 else {}
            if (
                request_item.get("sha256") != visual.get("request_sha256")
                or review_item.get("sha256") != visual.get("response_sha256")
                or review.get("request_id") != request.get("request_id")
                or review.get("request_sha256") != request.get("request_sha256")
                or request_artifact.get("docx_sha256") != docx.get("sha256")
                or request_artifact.get("pdf_sha256") != (pdf or {}).get("sha256")
                or [item.get("sha256") for item in request_artifact.get("pages") or []]
                != retained_page_sha256
                or review.get("status") != "passed"
                or (review.get("producer") or {}).get("model_id") not in models
                or (pdf or {}).get("sha256") != visual.get("pdf_sha256")
                or retained_page_sha256 != expected_pages
                or [item.get("sha256") for item in assessments] != expected_pages
                or any(item.get("status") != "passed" or set(item.get("checks") or []) != CERTIFICATION_VISUAL_CHECKS for item in assessments)
            ):
                findings.append(f"PDF or every-page review is invalid for {fixture}:{artifact}.")
    unconsumed = sorted(
        str(item.get("path") or item.get("identity") or "")
        for item in entries
        if str(item.get("identity") or "") not in consumed_identities
    )
    if unconsumed:
        findings.append(
            "Certification evidence contains unrelated or semantically unbound items: "
            + ", ".join(unconsumed)
            + "."
        )
    return findings


def release_certification_attestation_findings(
    report: Mapping[str, Any],
    manifest: Mapping[str, Any],
    skill_root: Path,
    *,
    trusted_key_id: str = RELEASE_CERTIFICATION_TRUSTED_KEY_ID,
) -> list[str]:
    """Verify report provenance against the manifest-bound release public key."""
    findings: list[str] = []
    key_path = skill_root / RELEASE_CERTIFICATION_PUBLIC_KEY
    try:
        key_bytes = key_path.read_bytes()
        key = json.loads(key_bytes)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"Release certification public key is unavailable or invalid: {exc}"]
    manifest_entry = next(
        (
            item for item in manifest.get("files") or []
            if item.get("path") == RELEASE_CERTIFICATION_PUBLIC_KEY
        ),
        None,
    )
    if (
        manifest_entry is None
        or manifest_entry.get("bytes") != len(key_bytes)
        or manifest_entry.get("sha256") != hashlib.sha256(key_bytes).hexdigest()
    ):
        findings.append("Release certification public key is not bound to the immutable manifest.")
    try:
        modulus = int(str(key.get("modulus") or ""), 16)
        exponent = int(key.get("exponent"))
    except (TypeError, ValueError):
        return findings + ["Release certification public key parameters are invalid."]
    try:
        key_identity = release_certification_key_id(key)
    except (TypeError, ValueError):
        return findings + ["Release certification public key identity is invalid."]
    if (
        key.get("schema_version") != "release-certification-public-key/v1"
        or key.get("algorithm") != RELEASE_CERTIFICATION_SIGNATURE_ALGORITHM
        or key.get("key_id") != key_identity
        or key_identity != trusted_key_id
        or exponent < 3
        or exponent % 2 == 0
        or modulus.bit_length() < 2048
    ):
        findings.append("Release certification public key identity or strength is invalid.")
    attestation = report.get("evidence_attestation") or {}
    payload_digest = hashlib.sha256(release_certification_payload(report)).digest()
    if (
        attestation.get("schema_version") != "release-certification-attestation/v1"
        or attestation.get("algorithm") != RELEASE_CERTIFICATION_SIGNATURE_ALGORITHM
        or attestation.get("key_id") != key_identity
        or attestation.get("payload_sha256") != payload_digest.hex()
    ):
        findings.append("Release certification evidence attestation metadata is missing or invalid.")
        return findings
    try:
        signature = base64.b64decode(
            str(attestation.get("signature_base64") or ""),
            validate=True,
        )
    except (binascii.Error, ValueError):
        return findings + ["Release certification evidence signature is not strict base64."]
    encoded_bytes = (modulus.bit_length() + 7) // 8
    digest_info = _SHA256_DIGEST_INFO_PREFIX + payload_digest
    expected = b"\x00\x01" + b"\xff" * (encoded_bytes - len(digest_info) - 3) + b"\x00" + digest_info
    if len(signature) != encoded_bytes:
        findings.append("Release certification evidence signature has an invalid length.")
    else:
        recovered = pow(int.from_bytes(signature, "big"), exponent, modulus).to_bytes(encoded_bytes, "big")
        if not hmac.compare_digest(recovered, expected):
            findings.append("Release certification evidence signature does not verify.")
    return findings


def _manifest_package_fingerprint(manifest: Mapping[str, Any]) -> tuple[str, str]:
    """Return the recorded and canonical fingerprints for one release manifest."""
    payload = dict(manifest)
    recorded = str(payload.pop("package_fingerprint", ""))
    computed = hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
    return recorded, computed


def _content_sha256(path: Path) -> str:
    """Hash visible DOCX text independently from its presentation properties."""
    if path.suffix.casefold() != ".docx":
        return sha256_file(path)
    try:
        stories: list[tuple[str, list[str]]] = []
        with zipfile.ZipFile(path) as package:
            for name in sorted(package.namelist()):
                if not name.startswith("word/") or not name.endswith(".xml"):
                    continue
                root = ET.fromstring(package.read(name))
                values = [
                    str(element.text or "")
                    for element in root.iter()
                    if ET.QName(element).localname in {"t", "instrText"}
                ]
                if values:
                    stories.append((name, values))
        payload = json.dumps(stories, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()
    except (OSError, ET.XMLSyntaxError, zipfile.BadZipFile):
        return sha256_file(path)


def _executable_candidates(
    names: Iterable[str],
    *,
    environment: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Iterable[tuple[Path, str]]:
    """Yield PATH and common installation candidates without changing the host."""
    search_path = (environment or {}).get("PATH") if environment is not None else None
    yielded: set[str] = set()
    for name in names:
        if path := shutil.which(name, path=search_path):
            resolved = str(Path(path).resolve())
            yielded.add(resolved.casefold())
            yield Path(resolved), "PATH"

    user_home = (home or Path.home()).expanduser()
    directories = [
        user_home / ".hermes/bin",
        Path(sys.executable).resolve().parent,
        Path("/opt/homebrew/bin"),
        Path("/usr/local/bin"),
        Path("/usr/bin"),
        Path("/bin"),
    ]
    sources = {
        str(user_home / ".hermes/bin"): "Hermes bundled tools",
        str(Path(sys.executable).resolve().parent): "Python environment",
    }
    bundled_tools_root = user_home / ".cache/codex-runtimes"
    if bundled_tools_root.is_dir():
        for pattern in ("*/dependencies/bin/override", "*/dependencies/bin/fallback"):
            for directory in sorted(bundled_tools_root.glob(pattern)):
                directories.append(directory)
                sources[str(directory)] = "bundled workspace tools"
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "ProgramData"):
        if value := (environment or os.environ).get(variable):
            base = Path(value)
            directories.extend((base / "LibreOffice/program", base / "chocolatey/bin"))

    for directory in directories:
        for name in names:
            candidates = (directory / name, directory / f"{name}.exe")
            for candidate in candidates:
                if not candidate.is_file() or not os.access(candidate, os.X_OK):
                    continue
                resolved = str(candidate.resolve())
                key = resolved.casefold()
                if key in yielded:
                    continue
                yielded.add(key)
                yield Path(resolved), sources.get(str(directory), "common installation path")


def _pdfium_integrity_failure(code: str, path: str, issue: str) -> dict[str, Any]:
    return {"status": "blocked", "finding": {
        "category": "renderer",
        "field": "page_renderer",
        "code": code,
        "path": path,
        "issue": issue,
    }}


def _pdfium_runtime_integrity(
    skill_root: Path,
    *,
    require_promoted_runtime: bool = True,
) -> dict[str, Any]:
    """Verify one installed runtime and explain the first exact mismatch."""
    resolved_root = Path(skill_root).resolve()
    active_lifecycle_evidence = any(
        path.exists() or path.is_symlink()
        for path in (
            resolved_root / "PROMOTION-RECORD.json",
            resolved_root / "INSTALLATION-ASSURANCE.json",
            resolved_root.parent / ".clinical-document-generation.previous",
            resolved_root.parent / ".clinical-document-generation.activation.json",
        )
    )
    require_promoted_runtime = require_promoted_runtime or active_lifecycle_evidence
    runtime_root = resolved_root / "runtime"
    runtime_python = runtime_root / "python"
    identity_path = runtime_root / "PDF-RENDERER.json"
    if runtime_root.is_symlink():
        return _pdfium_integrity_failure(
            "renderer.pdfium_runtime_directory_symlink",
            "runtime",
            "The PDFium runtime directory must not be a symlink.",
        )
    if runtime_python.is_symlink():
        return _pdfium_integrity_failure(
            "renderer.pdfium_runtime_root_symlink",
            "runtime/python",
            "The PDFium runtime root must not be a symlink.",
        )
    if not runtime_python.is_dir():
        return _pdfium_integrity_failure(
            "renderer.pdfium_runtime_missing",
            "runtime/python",
            "The manifest-bound PDFium runtime directory is missing.",
        )
    if identity_path.is_symlink() or not identity_path.is_file():
        return _pdfium_integrity_failure(
            "renderer.pdfium_metadata_missing",
            "runtime/PDF-RENDERER.json",
            "The PDFium operational metadata is missing or symlinked.",
        )
    try:
        recorded = _json(identity_path)
        manifest = _json(resolved_root / "RELEASE-MANIFEST.json")
        recorded_fingerprint, computed_fingerprint = _manifest_package_fingerprint(manifest)
        if not recorded_fingerprint or computed_fingerprint != recorded_fingerprint:
            return _pdfium_integrity_failure(
                "renderer.pdfium_manifest_fingerprint_invalid",
                "RELEASE-MANIFEST.json",
                "The PDFium inventory is not bound to a valid release package fingerprint.",
            )
        promotion_path = resolved_root / "PROMOTION-RECORD.json"
        if require_promoted_runtime and not (
            promotion_path.exists() or promotion_path.is_symlink()
        ):
            return _pdfium_integrity_failure(
                "renderer.pdfium_promotion_record_invalid",
                "PROMOTION-RECORD.json",
                "The promoted release record is missing, malformed, or symlinked.",
            )
        if promotion_path.exists() or promotion_path.is_symlink():
            if promotion_path.is_symlink() or not promotion_path.is_file():
                return _pdfium_integrity_failure(
                    "renderer.pdfium_promotion_record_invalid",
                    "PROMOTION-RECORD.json",
                    "The promoted release record is missing, malformed, or symlinked.",
                )
            try:
                promotion = _json(promotion_path)
            except (OSError, ValueError, json.JSONDecodeError, TypeError):
                return _pdfium_integrity_failure(
                    "renderer.pdfium_promotion_record_invalid",
                    "PROMOTION-RECORD.json",
                    "The promoted release record is missing, malformed, or symlinked.",
                )
            if (
                promotion.get("schema_version") != "promoted-release/v1"
                or promotion.get("status") != "active"
                or promotion.get("package_fingerprint") != recorded_fingerprint
            ):
                return _pdfium_integrity_failure(
                    "renderer.pdfium_promotion_fingerprint_mismatch",
                    "PROMOTION-RECORD.json",
                    "The runtime manifest does not match the promoted release fingerprint.",
                )
            assurance_path = resolved_root / "INSTALLATION-ASSURANCE.json"
            expected_assurance_sha256 = promotion.get("runtime_assurance_sha256")
            if (
                not isinstance(expected_assurance_sha256, str)
                or re.fullmatch(r"[0-9a-f]{64}", expected_assurance_sha256) is None
                or assurance_path.is_symlink()
                or not assurance_path.is_file()
            ):
                return _pdfium_integrity_failure(
                    "renderer.pdfium_installation_assurance_mismatch",
                    "INSTALLATION-ASSURANCE.json",
                    "The promoted release does not match its bound installation assurance.",
                )
            try:
                actual_assurance_sha256 = sha256_file(assurance_path)
            except OSError:
                actual_assurance_sha256 = ""
            if actual_assurance_sha256 != expected_assurance_sha256:
                return _pdfium_integrity_failure(
                    "renderer.pdfium_installation_assurance_mismatch",
                    "INSTALLATION-ASSURANCE.json",
                    "The promoted release does not match its bound installation assurance.",
                )
        manifest_identity = manifest["inventory"]["pdf_page_renderer"]
    except (OSError, ValueError, json.JSONDecodeError, KeyError, TypeError):
        return _pdfium_integrity_failure(
            "renderer.pdfium_manifest_invalid",
            "RELEASE-MANIFEST.json",
            "The release manifest does not contain a valid PDFium identity.",
        )
    identity_fields = ("kind", "version", "wheel", "wheel_sha256", "platform")
    if (
        recorded.get("kind") != "pypdfium2"
        or any(recorded.get(field) != manifest_identity.get(field) for field in identity_fields)
    ):
        return _pdfium_integrity_failure(
            "renderer.pdfium_metadata_mismatch",
            "runtime/PDF-RENDERER.json",
            "The PDFium operational identity does not match the release manifest.",
        )
    wheel_relative = Path(str(recorded.get("wheel") or ""))
    wheel_candidate = resolved_root / wheel_relative
    if wheel_candidate.is_symlink():
        return _pdfium_integrity_failure(
            "renderer.pdfium_wheel_symlink", wheel_relative.as_posix(),
            "The packaged PDFium wheel must not be a symlink.",
        )
    wheel = wheel_candidate.resolve()
    try:
        wheel.relative_to(resolved_root)
    except ValueError:
        return _pdfium_integrity_failure(
            "renderer.pdfium_wheel_escaping",
            wheel_relative.as_posix(),
            "The PDFium wheel path escapes the release root.",
        )
    if not wheel.is_file() or sha256_file(wheel) != recorded.get("wheel_sha256"):
        return _pdfium_integrity_failure(
            "renderer.pdfium_wheel_changed",
            wheel_relative.as_posix(),
            "The packaged PDFium wheel is missing, symlinked, or changed.",
        )
    expected_inventory = manifest_identity.get("runtime_inventory")
    if not isinstance(expected_inventory, list) or not expected_inventory:
        return _pdfium_integrity_failure(
            "renderer.pdfium_inventory_invalid",
            "RELEASE-MANIFEST.json",
            "The release manifest has no valid PDFium runtime inventory.",
        )
    expected_by_path: dict[str, dict[str, Any]] = {}
    for item in expected_inventory:
        if not isinstance(item, Mapping) or set(item) != {"path", "bytes", "sha256"}:
            return _pdfium_integrity_failure(
                "renderer.pdfium_inventory_invalid", "RELEASE-MANIFEST.json",
                "A PDFium inventory entry has an invalid shape.",
            )
        relative = Path(str(item.get("path") or ""))
        normalized = relative.as_posix()
        if (
            not normalized
            or relative.is_absolute()
            or ".." in relative.parts
            or normalized in expected_by_path
            or not isinstance(item.get("bytes"), int)
            or int(item["bytes"]) < 0
            or not re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256") or ""))
        ):
            return _pdfium_integrity_failure(
                "renderer.pdfium_inventory_escaping",
                normalized or "RELEASE-MANIFEST.json",
                "A PDFium inventory path is unsafe, duplicated, or malformed.",
            )
        expected_by_path[normalized] = {
            "bytes": int(item["bytes"]), "sha256": str(item["sha256"]),
        }
    if list(expected_by_path) != sorted(expected_by_path):
        return _pdfium_integrity_failure(
            "renderer.pdfium_inventory_invalid", "RELEASE-MANIFEST.json",
            "The PDFium runtime inventory is not deterministically ordered.",
        )
    actual_paths: dict[str, Path] = {}
    for path in runtime_python.rglob("*"):
        normalized = path.relative_to(runtime_python).as_posix()
        if path.is_symlink():
            return _pdfium_integrity_failure(
                "renderer.pdfium_runtime_symlink", normalized,
                f"The installed PDFium path is symlinked: {normalized}.",
            )
        if path.is_file():
            actual_paths[normalized] = path
    for normalized in expected_by_path:
        if normalized not in actual_paths:
            return _pdfium_integrity_failure(
                "renderer.pdfium_runtime_file_missing", normalized,
                f"The installed PDFium file is missing: {normalized}.",
            )
    for normalized in sorted(actual_paths):
        if normalized not in expected_by_path:
            return _pdfium_integrity_failure(
                "renderer.pdfium_runtime_file_extra", normalized,
                f"The installed PDFium runtime has an extra file: {normalized}.",
            )
        expected = expected_by_path[normalized]
        path = actual_paths[normalized]
        if path.stat().st_size != expected["bytes"] or sha256_file(path) != expected["sha256"]:
            return _pdfium_integrity_failure(
                "renderer.pdfium_runtime_file_changed", normalized,
                f"The installed PDFium file changed: {normalized}.",
            )
    return {"status": "passed", "identity": {
        "kind": "pypdfium2",
        "path": "python:pypdfium2",
        "module": "pypdfium2",
        "python_path": str(runtime_python),
        "version": str(recorded.get("version") or ""),
        "source": "release-owned runtime",
        "wheel": str(recorded.get("wheel") or ""),
        "wheel_sha256": str(recorded.get("wheel_sha256") or ""),
    }}


def page_renderers(
    *,
    environment: Mapping[str, str] | None = None,
    home: Path | None = None,
    skill_root: Path | None = None,
    require_promoted_runtime: bool = True,
) -> list[dict[str, Any]]:
    """Return the one release-owned PDFium page renderer, if verified."""
    del environment, home
    if skill_root is None:
        return []
    verification = _pdfium_runtime_integrity(
        Path(skill_root), require_promoted_runtime=require_promoted_runtime
    )
    return [verification["identity"]] if verification["status"] == "passed" else []


def _write_pdfium_png(bitmap: Any, output: Path) -> None:
    """Write PDFium's reverse-byte-order RGB buffer with only the standard library."""
    width = int(bitmap.width)
    height = int(bitmap.height)
    stride = int(bitmap.stride)
    raw = bytes(bitmap.buffer)
    scanlines = b"".join(
        b"\x00" + raw[offset:offset + width * 3]
        for offset in range(0, stride * height, stride)
    )

    def chunk(kind: bytes, data: bytes) -> bytes:
        payload = kind + data
        return struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    output.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(scanlines))
        + chunk(b"IEND", b"")
    )


def page_renderer(
    *,
    environment: Mapping[str, str] | None = None,
    home: Path | None = None,
    skill_root: Path | None = None,
) -> dict[str, Any] | None:
    """Return the preferred installed PDF page renderer."""
    identities = page_renderers(environment=environment, home=home, skill_root=skill_root)
    return identities[0] if identities else None


def _is_release_owned_pdfium_identity(identity: Mapping[str, Any]) -> bool:
    """Return whether an identity names the installed release-owned runtime."""
    python_path = Path(str(identity.get("python_path") or "")).expanduser()
    return (
        identity.get("kind") == "pypdfium2"
        and identity.get("path") == "python:pypdfium2"
        and identity.get("module") == "pypdfium2"
        and identity.get("source") == "release-owned runtime"
        and python_path.is_absolute()
        and python_path.name == "python"
        and python_path.parent.name == "runtime"
    )


def _one_pdfium_renderer(
    identities: Iterable[Mapping[str, Any]],
    *,
    skill_root: Path | None = None,
    require_promoted_runtime: bool = True,
) -> list[dict[str, Any]]:
    """Keep one identity verified against this release's manifest and runtime."""
    candidates = [dict(identity) for identity in identities if _is_release_owned_pdfium_identity(identity)]
    if skill_root is None:
        return candidates[:1]
    verified = page_renderers(
        skill_root=skill_root,
        require_promoted_runtime=require_promoted_runtime,
    )
    identity_fields = (
        "kind", "path", "module", "python_path", "version", "source", "wheel", "wheel_sha256",
    )
    for identity in candidates:
        if any(all(identity.get(field) == known.get(field) for field in identity_fields) for known in verified):
            return [identity]
    return []


def _ordered_page_images(output_dir: Path) -> list[Path]:
    def key(path: Path) -> tuple[int, str]:
        match = re.search(r"(\d+)(?=\.png$)", path.name)
        return (int(match.group(1)) if match else -1, path.name)
    return sorted(output_dir.glob("page*.png"), key=key)


def _rasterize_pdfium_worker_render(
    pdf: Path,
    output_dir: Path,
    identity: Mapping[str, Any],
    *,
    first_page_only: bool = False,
    dpi: int = 130,
    require_promoted_runtime: bool = True,
) -> list[Path]:
    """Render inside the isolated worker after re-verifying its release."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for stale in output_dir.glob("page*.png"):
        stale.unlink()
    kind = str(identity["kind"])
    if kind != "pypdfium2":
        raise RuntimeError(f"Unsupported page renderer: {kind}")

    release_root = Path(__file__).resolve().parents[1]
    governed = _one_pdfium_renderer(
        [identity],
        skill_root=release_root,
        require_promoted_runtime=require_promoted_runtime,
    )
    if not governed:
        raise RuntimeError(
            "PDF page rendering requires the manifest-verified release-owned runtime."
        )
    identity = governed[0]
    module_name = str(identity["module"])
    python_path = str(identity["python_path"])
    inserted = False
    previous_modules: dict[str, Any] = {}
    if python_path not in sys.path:
        sys.path.insert(0, python_path)
        inserted = True
    module_roots = ("pypdfium2", "pypdfium2_raw", "pypdfium2_cfg")
    for name in list(sys.modules):
        if any(name == root or name.startswith(root + ".") for root in module_roots):
            previous_modules[name] = sys.modules.pop(name)
    document = None
    previous_dont_write_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        pdfium = importlib.import_module(module_name)
        module_file = Path(str(getattr(pdfium, "__file__", ""))).resolve()
        try:
            module_file.relative_to(Path(python_path).resolve())
        except ValueError as exc:
            raise RuntimeError(f"pypdfium2 resolved outside the release-owned runtime: {module_file}") from exc
        document = pdfium.PdfDocument(str(pdf))
        document_pages = len(document)
        if document_pages > PDFIUM_MAX_PAGES:
            raise RuntimeError(
                f"renderer.pdfium_page_limit_exceeded: PDF has {document_pages} pages; "
                f"the governed maximum is {PDFIUM_MAX_PAGES}."
            )
        count = min(document_pages, 1) if first_page_only else document_pages
        total_pixels = 0
        total_output_bytes = 0
        for index in range(count):
            page = document[index]
            width = max(1, int(math.ceil(float(page.get_width()) * dpi / 72.0)))
            height = max(1, int(math.ceil(float(page.get_height()) * dpi / 72.0)))
            if width > PDFIUM_MAX_DIMENSION_PIXELS or height > PDFIUM_MAX_DIMENSION_PIXELS:
                page.close()
                raise RuntimeError(
                    "renderer.pdfium_dimension_limit_exceeded: "
                    f"page {index + 1} would render at {width}x{height} pixels."
                )
            total_pixels += width * height
            if total_pixels > PDFIUM_MAX_TOTAL_PIXELS:
                page.close()
                raise RuntimeError(
                    "renderer.pdfium_pixel_limit_exceeded: "
                    f"rendering exceeded {PDFIUM_MAX_TOTAL_PIXELS} total pixels."
                )
            bitmap = page.render(scale=dpi / 72.0, rev_byteorder=True)
            try:
                if int(bitmap.format) != 2:
                    raise RuntimeError(f"PDFium returned unsupported bitmap format {bitmap.format}.")
                page_path = output_dir / f"page-{index + 1}.png"
                _write_pdfium_png(bitmap, page_path)
                total_output_bytes += page_path.stat().st_size
                if total_output_bytes > PDFIUM_MAX_OUTPUT_BYTES:
                    raise RuntimeError(
                        "renderer.pdfium_output_limit_exceeded: "
                        f"page images exceeded {PDFIUM_MAX_OUTPUT_BYTES} bytes."
                    )
            finally:
                bitmap.close()
                page.close()
    except ImportError as exc:
        raise RuntimeError(f"The release-owned pypdfium2 page renderer is unavailable: {exc}") from exc
    finally:
        sys.dont_write_bytecode = previous_dont_write_bytecode
        if document is not None:
            document.close()
        for name in list(sys.modules):
            if any(name == root or name.startswith(root + ".") for root in module_roots):
                sys.modules.pop(name, None)
        sys.modules.update(previous_modules)
        if inserted:
            sys.path.remove(python_path)

    pages = _ordered_page_images(output_dir)
    if not pages:
        raise RuntimeError(f"{kind} page-image export produced no PNG pages.")
    temporary = []
    for index, page in enumerate(pages, 1):
        target = output_dir / f".normalized-{index}.png"
        page.replace(target)
        temporary.append(target)
    normalized = []
    for index, page in enumerate(temporary, 1):
        target = output_dir / ("page.png" if first_page_only else f"page-{index}.png")
        page.replace(target)
        normalized.append(target)
    return normalized


def _required_pdfium_worker_resource_limits() -> list[str]:
    system = platform.system()
    if system == "Windows":
        return []
    names = ["RLIMIT_CPU", "RLIMIT_FSIZE", "RLIMIT_NOFILE"]
    if system == "Linux":
        names.insert(1, "RLIMIT_AS")
    return names


def _supported_pdfium_worker_resource_limits() -> list[str]:
    try:
        import resource
    except ImportError:
        return []
    return [
        name for name in _required_pdfium_worker_resource_limits()
        if getattr(resource, name, None) is not None
    ]


def _apply_pdfium_worker_resource_limits() -> list[str]:
    """Apply every supported hard process limit before loading PDFium."""
    required = _required_pdfium_worker_resource_limits()
    try:
        import resource
    except ImportError as exc:
        if not required:
            return []
        raise RuntimeError(
            "renderer.pdfium_resource_limits_unavailable: "
            "The worker host does not expose required process limits."
        ) from exc
    applied = []
    limits = (
        ("RLIMIT_CPU", max(1, int(PDFIUM_WORKER_TIMEOUT_SECONDS))),
        ("RLIMIT_AS", PDFIUM_WORKER_MEMORY_BYTES),
        ("RLIMIT_FSIZE", PDFIUM_WORKER_FILE_BYTES),
        ("RLIMIT_NOFILE", 128),
    )
    supported = set(_supported_pdfium_worker_resource_limits())
    missing = [name for name in required if name not in supported]
    if missing:
        raise RuntimeError(
            "renderer.pdfium_resource_limits_unavailable: "
            f"The worker host does not expose required process limits: {', '.join(missing)}."
        )
    for name, requested in limits:
        if name not in supported:
            continue
        kind = getattr(resource, name, None)
        if kind is None:
            continue
        try:
            _soft, hard = resource.getrlimit(kind)
            finite_hard = requested if hard == resource.RLIM_INFINITY else min(requested, hard)
            resource.setrlimit(kind, (finite_hard, finite_hard))
            applied.append(name)
        except (OSError, ValueError) as exc:
            raise RuntimeError(
                "renderer.pdfium_resource_limit_failed: "
                f"The worker could not apply supported process limit {name}."
            ) from exc
    return applied


def run_pdfium_worker(request_path: Path) -> dict[str, Any]:
    """Internal workflow action for one isolated, bounded PDFium render."""
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
        pdf = Path(str(request["pdf"])).resolve()
        output_dir = Path(str(request["output_dir"])).resolve()
        require_promoted_runtime = request.get("require_promoted_runtime", True)
        if type(require_promoted_runtime) is not bool:
            raise RuntimeError(
                "renderer.pdfium_worker_protocol_invalid: Promotion mode must be boolean."
            )
        if not pdf.is_file() or sha256_file(pdf) != request.get("pdf_sha256"):
            raise RuntimeError(
                "renderer.pdfium_input_changed: The PDF bytes changed before worker rendering."
            )
        output_dir.mkdir(parents=True, exist_ok=True)
        if output_dir.is_symlink() or any(output_dir.iterdir()):
            raise RuntimeError(
                "renderer.pdfium_worker_output_invalid: Worker output staging was not empty."
            )
        applied_limits = _apply_pdfium_worker_resource_limits()
        pages = _rasterize_pdfium_worker_render(
            pdf,
            output_dir,
            request["identity"],
            first_page_only=bool(request.get("first_page_only")),
            dpi=int(request.get("dpi", 130)),
            require_promoted_runtime=require_promoted_runtime,
        )
        evidence = [
            {"name": page.name, "bytes": page.stat().st_size, "sha256": sha256_file(page)}
            for page in pages
        ]
        return {"status": "passed", "pages": evidence, "resource_limits": applied_limits}
    except Exception as exc:
        message = str(exc)
        code, separator, issue = message.partition(": ")
        if not separator or not code.startswith("renderer.pdfium_"):
            code = "renderer.pdfium_worker_crashed"
            issue = message or type(exc).__name__
        return {"status": "blocked", "findings": [{
            "category": "renderer",
            "field": "page_renderer",
            "code": code,
            "issue": issue,
        }]}


def _pdfium_worker_command(request_path: Path) -> list[str]:
    release_root = Path(__file__).resolve().parents[1]
    return [
        sys.executable,
        str(release_root / "scripts/workflow.py"),
        "--internal-pdfium-worker",
        str(request_path),
    ]


def _clear_page_output(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for path in output_dir.iterdir():
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)


def _terminate_pdfium_worker_group(process: subprocess.Popen[str]) -> None:
    """Terminate and reap the worker's complete process group after any exit."""
    if platform.system() != "Windows":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    elif process.poll() is None:
        process.kill()
    process.communicate()


def rasterize_pdf(
    pdf: Path,
    output_dir: Path,
    identity: Mapping[str, Any],
    *,
    first_page_only: bool = False,
    dpi: int = 130,
    timeout_seconds: float = PDFIUM_WORKER_TIMEOUT_SECONDS,
    require_promoted_runtime: bool = True,
) -> list[Path]:
    """Render through one killable worker bound to the current immutable release."""
    output_dir = output_dir.resolve()
    _clear_page_output(output_dir)
    release_root = Path(__file__).resolve().parents[1]
    governed = _one_pdfium_renderer(
        [identity],
        skill_root=release_root,
        require_promoted_runtime=require_promoted_runtime,
    )
    if not governed:
        raise RuntimeError(
            "PDF page rendering requires the manifest-verified release-owned runtime."
        )
    timeout = min(PDFIUM_WORKER_TIMEOUT_SECONDS, float(timeout_seconds))
    if timeout <= 0:
        raise RuntimeError("renderer.pdfium_worker_timeout: No worker time remained.")
    with tempfile.TemporaryDirectory(prefix=".pdfium-worker-", dir=output_dir.parent) as temporary:
        temporary_root = Path(temporary)
        worker_output = temporary_root / "pages"
        worker_output.mkdir()
        request_path = temporary_root / "request.json"
        request_path.write_text(json.dumps({
            "pdf": str(pdf.resolve()),
            "pdf_sha256": sha256_file(pdf),
            "output_dir": str(worker_output),
            "identity": governed[0],
            "first_page_only": first_page_only,
            "dpi": dpi,
            "require_promoted_runtime": require_promoted_runtime,
        }), encoding="utf-8")
        process = subprocess.Popen(
            _pdfium_worker_command(request_path),
            cwd=release_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=platform.system() != "Windows",
        )
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            _terminate_pdfium_worker_group(process)
            _clear_page_output(output_dir)
            raise RuntimeError(
                f"renderer.pdfium_worker_timeout: PDFium exceeded {timeout:g} seconds."
            ) from exc
        _terminate_pdfium_worker_group(process)
        try:
            result = json.loads(stdout)
        except json.JSONDecodeError as exc:
            _clear_page_output(output_dir)
            raise RuntimeError(
                "renderer.pdfium_worker_crashed: "
                f"PDFium worker exited {process.returncode}: {stderr.strip() or stdout.strip()}"
            ) from exc
        if process.returncode or result.get("status") != "passed":
            _clear_page_output(output_dir)
            finding = next(iter(result.get("findings") or []), {})
            code = str(finding.get("code") or "renderer.pdfium_worker_crashed")
            issue = str(finding.get("issue") or stderr.strip() or "PDFium worker failed.")
            raise RuntimeError(f"{code}: {issue}")
        required_limits = set(_required_pdfium_worker_resource_limits())
        if not required_limits.issubset(set(result.get("resource_limits") or [])):
            _clear_page_output(output_dir)
            raise RuntimeError(
                "renderer.pdfium_resource_limits_unavailable: "
                "The worker could not apply required host process limits."
            )
        evidence = result.get("pages")
        actual = [
            {"name": page.name, "bytes": page.stat().st_size, "sha256": sha256_file(page)}
            for page in _ordered_page_images(worker_output)
            if page.is_file() and not page.is_symlink()
        ]
        if not isinstance(evidence, list) or actual != evidence or not actual:
            _clear_page_output(output_dir)
            raise RuntimeError(
                "renderer.pdfium_worker_output_invalid: Worker page evidence did not match output bytes."
            )
        pages = []
        for item in actual:
            source = worker_output / item["name"]
            target = output_dir / item["name"]
            os.replace(source, target)
            pages.append(target)
        return pages


def renderers(
    *,
    environment: Mapping[str, str] | None = None,
    skill_root: Path | None = None,
    deadline_monotonic: float | None = None,
    clock: Any = time.monotonic,
) -> list[dict[str, Any]]:
    """List supported host DOCX renderers in governed fidelity order."""
    del skill_root
    search_path = (environment or {}).get("PATH") if environment is not None else None
    system = platform.system()
    identities: list[dict[str, Any]] = []
    yielded: set[str] = set()

    def append(identity: dict[str, Any]) -> None:
        key = str(identity.get("path", "")).casefold()
        if key and key not in yielded:
            yielded.add(key)
            identities.append(identity)

    def probe_timeout(cap: float = 20.0) -> float | None:
        if deadline_monotonic is None:
            return cap
        remaining = deadline_monotonic - clock()
        return min(cap, remaining) if remaining > 0 else None

    if system == "Windows":
        try:
            if importlib.util.find_spec("win32com.client") is not None:
                append({"kind": "Microsoft Word", "path": "COM:Word.Application", "version": "installed COM application", "platform": "Windows", "source": "host application"})
        except (ImportError, ValueError):
            pass
    if system == "Darwin" and Path("/Applications/Microsoft Word.app").exists():
        append({"kind": "Microsoft Word", "path": "/Applications/Microsoft Word.app", "version": "installed macOS application", "platform": "Darwin", "source": "host application"})
    office_candidates = list(_executable_candidates(("libreoffice", "soffice"), environment=environment))
    if system == "Darwin":
        office_candidates.append((Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"), "macOS application"))
    for candidate, source in office_candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            path = str(candidate)
            timeout = probe_timeout()
            if timeout is None:
                break
            try:
                result = subprocess.run([path, "--version"], text=True, capture_output=True, timeout=timeout, env=dict(environment) if environment else None)
            except (OSError, subprocess.TimeoutExpired):
                continue
            if result.returncode == 0:
                append({"kind": "LibreOffice", "path": path, "version": result.stdout.strip(), "platform": system, "source": source})
    return identities


def renderer(
    *,
    environment: Mapping[str, str] | None = None,
    skill_root: Path | None = None,
) -> dict[str, Any] | None:
    """Return the preferred supported host office renderer."""
    identities = renderers(environment=environment, skill_root=skill_root)
    return identities[0] if identities else None


def _template_fonts(path: Path) -> set[str]:
    """Return font families that can render visible text in the DOCX stories.

    Word stores fonts for dormant styles and alternate writing systems alongside
    the fonts used by visible runs.  Requiring every declaration makes renderer
    preflight depend on fonts that cannot affect an English document.  Resolve
    each visible run through its run, character-style, paragraph-style, and
    document-default hierarchy instead.
    """
    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    ns = {"w": namespace}
    attr = lambda name: f"{{{namespace}}}{name}"
    fonts: set[str] = set()

    def font_values(element: ET._Element | None) -> dict[str, str]:
        if element is None:
            return {}
        node = element.find("w:rPr/w:rFonts", ns) if element.tag != attr("rPr") else element.find("w:rFonts", ns)
        if node is None:
            return {}
        return {
            key: value.strip()
            for key in ("ascii", "hAnsi", "eastAsia", "cs")
            if (value := node.get(attr(key))) and value.strip()
        }

    def scripts(text: str) -> set[str]:
        required: set[str] = set()
        for character in text:
            codepoint = ord(character)
            if character.isspace() or character.isascii():
                required.add("ascii")
            elif (
                0x3040 <= codepoint <= 0x30FF
                or 0x3400 <= codepoint <= 0x9FFF
                or 0xAC00 <= codepoint <= 0xD7AF
                or 0xF900 <= codepoint <= 0xFAFF
            ):
                required.add("eastAsia")
            elif (
                0x0590 <= codepoint <= 0x08FF
                or 0x0900 <= codepoint <= 0x0DFF
                or 0xFB1D <= codepoint <= 0xFEFC
            ):
                required.add("cs")
            else:
                required.add("hAnsi")
        return required or {"ascii"}

    with zipfile.ZipFile(path) as package:
        styles: dict[str, tuple[str | None, dict[str, str]]] = {}
        defaults: dict[str, str] = {}
        if "word/styles.xml" in package.namelist():
            styles_root = ET.fromstring(package.read("word/styles.xml"))
            defaults = font_values(styles_root.find("w:docDefaults/w:rPrDefault/w:rPr", ns))
            for style in styles_root.findall("w:style", ns):
                style_id = style.get(attr("styleId"))
                if not style_id:
                    continue
                based_on = style.find("w:basedOn", ns)
                styles[style_id] = (
                    based_on.get(attr("val")) if based_on is not None else None,
                    font_values(style),
                )

        def style_fonts(style_id: str | None) -> dict[str, str]:
            resolved: dict[str, str] = {}
            seen: set[str] = set()
            while style_id and style_id not in seen:
                seen.add(style_id)
                based_on, declared = styles.get(style_id, (None, {}))
                for key, value in declared.items():
                    resolved.setdefault(key, value)
                style_id = based_on
            return resolved

        story_names = [
            name for name in package.namelist()
            if name == "word/document.xml"
            or re.fullmatch(r"word/(?:header|footer)\d+\.xml", name)
            or name in {"word/footnotes.xml", "word/endnotes.xml", "word/comments.xml"}
        ]
        for name in story_names:
            root = ET.fromstring(package.read(name))
            for run in root.iter(attr("r")):
                text = "".join(node.text or "" for node in run.findall("w:t", ns))
                symbols = run.findall("w:sym", ns)
                if not text.strip() and not symbols:
                    continue
                for symbol in symbols:
                    if value := symbol.get(attr("font")):
                        fonts.add(value.strip())

                direct = font_values(run.find("w:rPr", ns))
                run_style = run.find("w:rPr/w:rStyle", ns)
                character = style_fonts(run_style.get(attr("val")) if run_style is not None else None)
                paragraph = run.getparent()
                while paragraph is not None and paragraph.tag != attr("p"):
                    paragraph = paragraph.getparent()
                paragraph_style = paragraph.find("w:pPr/w:pStyle", ns) if paragraph is not None else None
                inherited = style_fonts(paragraph_style.get(attr("val")) if paragraph_style is not None else None)
                sources = (direct, character, inherited, defaults)
                for script in scripts(text):
                    fallbacks = {
                        "ascii": ("ascii", "hAnsi"),
                        "hAnsi": ("hAnsi", "ascii"),
                        "eastAsia": ("eastAsia", "hAnsi", "ascii"),
                        "cs": ("cs", "hAnsi", "ascii"),
                    }[script]
                    selected = next(
                        (source[key] for source in sources for key in fallbacks if key in source),
                        None,
                    )
                    if selected:
                        fonts.add(selected)
    return fonts


def _font_probe(
    font: str,
    *,
    environment: Mapping[str, str] | None = None,
    timeout_seconds: float = 10.0,
) -> tuple[bool | None, str]:
    global _MAC_FONT_NAMES, _WINDOWS_FONT_NAMES
    executable = shutil.which("fc-match", path=(environment or {}).get("PATH"))
    if not executable and platform.system() == "Darwin":
        try:
            if _MAC_FONT_NAMES is None:
                result = subprocess.run(["/usr/sbin/system_profiler", "SPFontsDataType", "-json"], text=True, capture_output=True, timeout=max(0.001, min(10.0, timeout_seconds)))
                if result.returncode != 0:
                    raise RuntimeError(result.stderr.strip() or "system_profiler failed")
                entries = json.loads(result.stdout).get("SPFontsDataType", [])
                _MAC_FONT_NAMES = set()
                for item in entries:
                    if not isinstance(item, Mapping):
                        continue
                    _MAC_FONT_NAMES.add(str(item.get("_name", "")).casefold())
                    for face in item.get("typefaces", []):
                        if not isinstance(face, Mapping):
                            continue
                        for key in ("_name", "family", "fullname"):
                            if value := str(face.get(key, "")).strip():
                                _MAC_FONT_NAMES.add(value.casefold())
            normalized_font = font.casefold()
            available = any(
                name.removesuffix(".ttf").removesuffix(".otf").removesuffix(".ttc").removesuffix(" bold").removesuffix(" italic").strip() == normalized_font
                for name in _MAC_FONT_NAMES
            )
            return available, "macOS system font inventory"
        except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError, json.JSONDecodeError):
            pass
    if not executable and platform.system() == "Windows":
        try:
            if _WINDOWS_FONT_NAMES is None:
                import winreg
                _WINDOWS_FONT_NAMES = set()
                key_path = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"
                for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                    try:
                        with winreg.OpenKey(hive, key_path) as key:
                            for index in range(winreg.QueryInfoKey(key)[1]):
                                name, filename, _kind = winreg.EnumValue(key, index)
                                _WINDOWS_FONT_NAMES.add(re.sub(r"\s*\([^)]*\)\s*$", "", str(name)).casefold())
                                _WINDOWS_FONT_NAMES.add(Path(str(filename)).stem.casefold())
                    except OSError:
                        continue
            normalized_font = font.casefold()
            return normalized_font in _WINDOWS_FONT_NAMES, "Windows system font inventory"
        except (ImportError, OSError):
            pass
    if not executable:
        return None, "font inventory is unavailable; availability will be decided by render evidence."
    try:
        result = subprocess.run(
            [executable, "-f", "%{family}", font],
            text=True,
            capture_output=True,
            timeout=max(0.001, min(5.0, timeout_seconds)),
            env=dict(environment) if environment else None,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"font probe unavailable: {exc}"
    families = {part.strip().casefold() for part in result.stdout.split(",") if part.strip()}
    return result.returncode == 0 and font.casefold() in families, result.stdout.strip()


def _bundled_font_path(
    repo_root: Path,
    font: str,
    approved_font_plan: Mapping[str, Any] | None = None,
) -> Path | None:
    families = (
        approved_font_plan.get("packaged_families", {})
        if isinstance(approved_font_plan, Mapping)
        else BUNDLED_FONT_FILES
    )
    filename = families.get(font)
    if not filename:
        return None
    assets = (
        approved_font_plan.get("packaged_font_assets", {})
        if isinstance(approved_font_plan, Mapping)
        else {}
    )
    relative = next(
        (str(path) for path in assets if Path(str(path)).name == filename),
        f"assets/fallback-fonts/{filename}",
    )
    path = repo_root / relative
    return path if path.is_file() else None


def _runtime_environment(
    repo_root: Path,
    environment: Mapping[str, str] | None,
    contracted_bundle: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    runtime = dict(environment or os.environ)
    approved_font_plan = contracted_bundle.get("approved_font_plan", {}) if isinstance(contracted_bundle, Mapping) else {}
    asset_paths = approved_font_plan.get("packaged_font_assets", {}) if isinstance(approved_font_plan, Mapping) else {}
    font_dirs = sorted({(repo_root / str(relative)).parent for relative in asset_paths})
    if not font_dirs:
        font_dirs = [repo_root / "assets/fallback-fonts"]
    available_dirs = [path for path in font_dirs if path.is_dir()]
    if available_dirs:
        existing = runtime.get("SAL_FONTPATH", "")
        runtime["SAL_FONTPATH"] = os.pathsep.join([
            *(str(path) for path in available_dirs),
            *([existing] if existing else []),
        ])
    return runtime


def _font_fallback_candidates(font: str) -> tuple[str, ...]:
    """Return visually compatible cross-platform fallbacks in preference order."""
    normalized = font.casefold()
    if "symbol" in normalized or "dingbat" in normalized or "wingding" in normalized:
        candidates = SYMBOL_FONT_FALLBACKS
    elif any(marker in normalized for marker in ("mono", "courier", "consolas", "menlo", "code")):
        candidates = MONOSPACE_FONT_FALLBACKS
    elif any(marker in normalized for marker in ("serif", "times", "georgia", "cambria", "garamond", "minion")):
        candidates = SERIF_FONT_FALLBACKS
    else:
        candidates = SANS_FONT_FALLBACKS
    seen = {normalized}
    ordered = []
    for candidate in candidates:
        key = candidate.casefold()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(candidate)
    return tuple(ordered)


def _approved_packaged_font_fallback(
    font: str,
    approved_font_plan: Mapping[str, Any] | None = None,
) -> str:
    """Map a missing template font to one audited release-owned substitute."""
    normalized = font.casefold().strip()
    approved = (
        approved_font_plan.get("approved_fallbacks", {})
        if isinstance(approved_font_plan, Mapping)
        else APPROVED_PACKAGED_FONT_FALLBACKS
    )
    families = (
        approved_font_plan.get("packaged_families", {})
        if isinstance(approved_font_plan, Mapping)
        else BUNDLED_FONT_FILES
    )
    if normalized in approved:
        return str(approved[normalized])
    if any(marker in normalized for marker in ("mono", "courier", "consolas", "menlo", "code")):
        return "Liberation Mono" if "Liberation Mono" in families else next(iter(families))
    if any(marker in normalized for marker in ("serif", "times", "georgia", "cambria", "garamond", "minion")):
        return "Liberation Serif" if "Liberation Serif" in families else next(iter(families))
    return "Liberation Sans" if "Liberation Sans" in families else next(iter(families))


def preflight(
    repo_root: Path,
    reference: Mapping[str, Any],
    *,
    contracted_bundle: Mapping[str, Any] | None = None,
    deadline_seconds: float = 30.0,
    environment: Mapping[str, str] | None = None,
    renderer_identities: Iterable[Mapping[str, Any]] | None = None,
    page_renderer_identities: Iterable[Mapping[str, Any]] | None = None,
    clock: Any = time.monotonic,
) -> dict[str, Any]:
    """Resolve and smoke-test Render Assurance capabilities.

    Inventory uncertainty is evidence to test, not evidence of absence. The
    function only blocks after every local renderer/page-renderer combination
    has failed its disposable render.
    """
    started = clock()
    deadline = started + max(0.0, deadline_seconds)

    def remaining() -> float:
        return max(0.0, deadline - clock())

    bundle = contracted_bundle or contracted_template_bundle(repo_root, reference)
    approved_font_plan = bundle["approved_font_plan"]
    runtime_environment = _runtime_environment(repo_root, environment, bundle)
    renderer_candidates = (
        [dict(item) for item in renderer_identities]
        if renderer_identities is not None
        else renderers(
            environment=runtime_environment,
            skill_root=repo_root,
            deadline_monotonic=deadline,
            clock=clock,
        )
    )
    page_candidates = _one_pdfium_renderer(
        [dict(item) for item in page_renderer_identities]
        if page_renderer_identities is not None
        else page_renderers(environment=runtime_environment, skill_root=repo_root) if remaining() > 0 else [],
        skill_root=repo_root,
    )
    identity = None
    page_identity = None
    renderer_attempts: list[dict[str, Any]] = []
    page_attempts: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    protocol_template, icf_template = template_paths(repo_root, reference, contracted_bundle=bundle)
    templates = [path for path in (protocol_template, icf_template) if path is not None]
    required_fonts = sorted({font for path in templates for font in _template_fonts(path)})
    font_results: dict[str, Any] = {}
    font_substitutions: dict[str, str] = {}
    bundled_substitution = False
    for font in required_fonts:
        probe_remaining = remaining()
        if probe_remaining <= 0:
            font_results[font] = {"available": None, "match": "Render Assurance deadline expired before font inventory."}
            continue
        available, detail = _font_probe(font, environment=runtime_environment, timeout_seconds=probe_remaining)
        font_results[font] = {"available": available, "match": detail}
        if available is not False:
            continue
        candidate = _approved_packaged_font_fallback(font, approved_font_plan)
        bundled = _bundled_font_path(repo_root, candidate, approved_font_plan)
        if bundled is not None:
            font_substitutions[font] = candidate
            font_results[font].update({
                "substitute": candidate,
                "substitute_match": f"bundled approved compatible font: {bundled.relative_to(repo_root)}",
            })
            bundled_substitution = True
        else:
            font_results[font]["attempted_fallbacks"] = [candidate]
    smoke: dict[str, Any] = {"status": "not_run"}
    if renderer_candidates and page_candidates and remaining() > 0:
        with tempfile.TemporaryDirectory(prefix="hermes-renderer-preflight-") as directory:
            root = Path(directory)
            source = root / "preflight.docx"
            document = Document()
            document.add_paragraph("Hermes renderer preflight")
            for font in required_fonts:
                selected = font_substitutions.get(font, font)
                run = document.add_paragraph().add_run(f"{selected}: Aa 123 •")
                run.font.name = selected
                fonts = run._element.get_or_add_rPr().get_or_add_rFonts()
                for attribute in ("ascii", "hAnsi", "eastAsia", "cs"):
                    fonts.set(qn(f"w:{attribute}"), selected)
            document.save(source)
            page_renderer_failed = False
            for candidate_renderer in renderer_candidates:
                attempt_remaining = remaining()
                if attempt_remaining <= 0:
                    break
                if bundled_substitution and candidate_renderer.get("kind") != "LibreOffice":
                    renderer_attempts.append({
                        "renderer": candidate_renderer,
                        "status": "skipped",
                        "issue": "Bundled fallback fonts are isolated to the verified LibreOffice runtime.",
                    })
                    continue
                try:
                    pdf = _render_pdf(
                        source,
                        root,
                        candidate_renderer,
                        environment=runtime_environment,
                        timeout_seconds=max(0.001, attempt_remaining),
                    )
                except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                    renderer_attempts.append({"renderer": candidate_renderer, "status": "failed", "issue": str(exc)})
                    continue
                page_dir = root / "pages"
                for candidate_page_renderer in page_candidates:
                    attempt_remaining = remaining()
                    if attempt_remaining <= 0:
                        break
                    try:
                        rasterize_pdf(
                            pdf,
                            page_dir,
                            candidate_page_renderer,
                            first_page_only=True,
                        )
                    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                        page_attempts.append({"renderer": candidate_page_renderer, "status": "failed", "issue": str(exc)})
                        page_renderer_failed = True
                        break
                    identity = candidate_renderer
                    page_identity = candidate_page_renderer
                    renderer_attempts.append({"renderer": candidate_renderer, "status": "passed"})
                    page_attempts.append({"renderer": candidate_page_renderer, "status": "passed"})
                    smoke = {"status": "passed", "pdf": "disposable/preflight.pdf", "page_image": "disposable/preflight.png", "pages": len(PdfReader(pdf).pages)}
                    break
                if identity is not None:
                    break
                if page_renderer_failed:
                    renderer_attempts.append({
                        "renderer": candidate_renderer,
                        "status": "failed",
                        "issue": "The release-owned pypdfium2 page renderer failed; no office renderer retry is permitted.",
                    })
                    break
                renderer_attempts.append({
                    "renderer": candidate_renderer,
                    "status": "failed",
                    "issue": "Every available page renderer failed for this renderer.",
                })
    if identity is None:
        if not renderer_candidates:
            issue = "No supported Microsoft Word or LibreOffice renderer is available."
            field = "renderer"
        elif not page_candidates:
            issue = "The release-owned pypdfium2 page renderer is unavailable."
            field = "page_renderer"
        else:
            issue = (
                "The release-owned pypdfium2 page renderer failed; Render Assurance stopped exactly."
                if page_attempts else
                "Every supported office renderer failed its smoke render."
            )
            field = "preflight"
        findings.append({"category": "renderer", "field": field, "issue": issue})
        smoke = {"status": "blocked", "issue": issue}
    else:
        for font, result in font_results.items():
            if result.get("available") is None:
                result["resolution"] = "render_verified"
    elapsed = clock() - started
    if elapsed > deadline_seconds and identity is None:
        findings.append({"category": "renderer", "field": "preflight", "issue": f"Renderer preflight exceeded its {deadline_seconds:.1f}s deadline ({elapsed:.3f}s)."})
    ordered_renderers = ([identity] if identity else []) + [candidate for candidate in renderer_candidates if candidate != identity]
    ordered_page_renderers = ([page_identity] if page_identity else []) + [candidate for candidate in page_candidates if candidate != page_identity]
    return {
        "status": "passed" if not findings else "blocked",
        "contracted_template_bundle": dict(bundle),
        "renderer": identity,
        "renderer_candidates": ordered_renderers,
        "renderer_attempts": renderer_attempts,
        "page_renderer": page_identity,
        "page_renderer_candidates": ordered_page_renderers,
        "page_renderer_attempts": page_attempts,
        "required_fonts": required_fonts,
        "fonts": font_results,
        "font_substitutions": font_substitutions,
        "smoke": smoke,
        "deadline_seconds": deadline_seconds,
        "elapsed_seconds": round(elapsed, 3),
        "findings": findings,
    }


def _render_pdf(docx: Path, output_dir: Path, identity: Mapping[str, Any], *, environment: Mapping[str, str] | None = None, timeout_seconds: float = 180.0) -> Path:
    if identity["kind"] == "LibreOffice":
        result = subprocess.run([str(identity["path"]), "--headless", "--convert-to", "pdf", "--outdir", str(output_dir), str(docx)], text=True, capture_output=True, timeout=timeout_seconds, env=dict(environment) if environment else None)
        path = output_dir / f"{docx.stem}.pdf"
        if result.returncode or not path.is_file():
            raise RuntimeError(f"LibreOffice PDF export failed: {result.stderr or result.stdout}")
        return path
    if identity.get("platform") == "Windows":
        return _windows_word_pdf(docx, output_dir, timeout_seconds=timeout_seconds)
    return _mac_pdf(docx, output_dir, identity, timeout_seconds=timeout_seconds)


def _mac_pdf(docx: Path, output_dir: Path, identity: Mapping[str, Any], *, timeout_seconds: float = 180.0) -> Path:
    if identity.get("kind") != "Microsoft Word":
        raise RuntimeError("Only Microsoft Word or LibreOffice may convert DOCX to PDF.")
    app = "Microsoft Word"
    output = output_dir / f"{docx.stem}.pdf"
    script = 'on run argv\nset src to POSIX file (item 1 of argv)\nset dst to POSIX file (item 2 of argv)\ntell application "Microsoft Word"\nset d to open src\nsave as d file name dst file format format PDF\nclose d saving no\nend tell\nend run'
    result = subprocess.run(["osascript", "-e", script, str(docx), str(output)], text=True, capture_output=True, timeout=timeout_seconds)
    if result.returncode or not output.is_file(): raise RuntimeError(f"{app} PDF export failed: {result.stderr or result.stdout}")
    return output


def _windows_word_pdf(docx: Path, output_dir: Path, *, timeout_seconds: float = 180.0) -> Path:
    output = output_dir / f"{docx.stem}.pdf"
    script = (
        "import sys\nimport win32com.client\n"
        "word=win32com.client.DispatchEx('Word.Application'); word.Visible=False; document=None\n"
        "try:\n document=word.Documents.Open(sys.argv[1], ReadOnly=True); document.ExportAsFixedFormat(sys.argv[2], 17)\n"
        "finally:\n document.Close(False) if document is not None else None; word.Quit()\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(docx.resolve()), str(output.resolve())],
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
    )
    if result.returncode:
        raise RuntimeError(f"Microsoft Word PDF export failed: {result.stderr or result.stdout}")
    if not output.is_file(): raise RuntimeError("Microsoft Word PDF export did not produce a file.")
    return output


def _blank_pdf_pages(path: Path) -> list[int]:
    blank: list[int] = []
    for index, page in enumerate(PdfReader(path).pages, 1):
        lines = []
        for line in (page.extract_text() or "").splitlines():
            normalized = line.strip()
            if re.search(r"\bpage\s+\d+\s+of\s+\d+\b", normalized, flags=re.I):
                continue
            if re.fullmatch(r"(?:v(?:ersion)?\s*)?\S*\s*\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}", normalized, flags=re.I):
                continue
            lines.append(normalized)
        if len(re.findall(r"\b\w+\b", "\n".join(lines))) < 3:
            blank.append(index)
    return blank


def render_pages(
    revision_dir: Path,
    *,
    artifact_names: Iterable[str] | None = None,
    contracted_bundle: Mapping[str, Any] | None = None,
    renderer_identity: Mapping[str, Any] | None = None,
    page_renderer_identity: Mapping[str, Any] | None = None,
    renderer_identities: Iterable[Mapping[str, Any]] | None = None,
    page_renderer_identities: Iterable[Mapping[str, Any]] | None = None,
    deadline_monotonic: float | None = None,
    clock: Any = time.monotonic,
    font_evidence: Mapping[str, Any] | None = None,
    font_substitutions: Mapping[str, str] | None = None,
    office_exporter: Any = None,
    page_exporter: Any = None,
    blank_page_detector: Any = None,
    require_promoted_runtime: bool = True,
) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[1]
    runtime_environment = _runtime_environment(repo_root, None, contracted_bundle)
    export_docx = office_exporter or _render_pdf
    export_pages = page_exporter or rasterize_pdf
    find_blank_pages = blank_page_detector or _blank_pdf_pages
    render_root = revision_dir / "rendered"
    selected_artifacts = set(artifact_names or ())
    docx_paths = [
        path
        for path in sorted((revision_dir / "candidate").glob("*.docx"))
        if not selected_artifacts or path.stem in selected_artifacts
    ]
    if selected_artifacts:
        for docx in docx_paths:
            (render_root / f"{docx.stem}.pdf").unlink(missing_ok=True)
            shutil.rmtree(render_root / docx.stem, ignore_errors=True)
    elif render_root.exists():
        shutil.rmtree(render_root)
    renderer_candidates = [dict(item) for item in (renderer_identities or [])]
    if renderer_identity is not None:
        renderer_candidates = [dict(renderer_identity), *[item for item in renderer_candidates if dict(item) != dict(renderer_identity)]]
    if not renderer_candidates and renderer_identities is None and renderer_identity is None:
        renderer_candidates = renderers(environment=runtime_environment, skill_root=repo_root)
    page_candidates = [dict(item) for item in (page_renderer_identities or [])]
    if page_renderer_identity is not None:
        page_candidates = [dict(page_renderer_identity), *[item for item in page_candidates if dict(item) != dict(page_renderer_identity)]]
    if not page_candidates and page_renderer_identities is None and page_renderer_identity is None:
        page_candidates = page_renderers(
            environment=runtime_environment,
            skill_root=repo_root,
            require_promoted_runtime=require_promoted_runtime,
        )
    page_candidates = _one_pdfium_renderer(
        page_candidates,
        skill_root=repo_root,
        require_promoted_runtime=require_promoted_runtime,
    )
    if not renderer_candidates:
        return {"status": "blocked", "findings": [{"category": "renderer", "field": "renderer", "issue": "No supported Microsoft Word or LibreOffice renderer is available."}]}
    if not page_candidates:
        if page_renderer_identities is None and page_renderer_identity is None:
            integrity = _pdfium_runtime_integrity(
                repo_root, require_promoted_runtime=require_promoted_runtime
            )
            if integrity["status"] == "blocked":
                return {
                    "status": "blocked",
                    "renderer": renderer_candidates[0],
                    "findings": [integrity["finding"]],
                }
        return {"status": "blocked", "renderer": renderer_candidates[0], "findings": [{"category": "renderer", "field": "page_renderer", "issue": "No supported PDF page renderer is available."}]}

    renderer_attempts: list[dict[str, Any]] = []
    page_attempts: list[dict[str, Any]] = []
    for renderer_index, identity in enumerate(renderer_candidates, 1):
        remaining = 180.0 if deadline_monotonic is None else deadline_monotonic - clock()
        if remaining <= 0:
            break
        attempt_root = revision_dir / ".render-attempts" / f"renderer-{renderer_index}"
        if attempt_root.exists():
            shutil.rmtree(attempt_root)
        attempt_root.mkdir(parents=True)
        pdfs: dict[Path, Path] = {}
        try:
            for docx in docx_paths:
                remaining = 180.0 if deadline_monotonic is None else deadline_monotonic - clock()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired("DOCX rendering", 0)
                pdf = export_docx(docx, attempt_root, identity, environment=runtime_environment, timeout_seconds=min(180.0, remaining))
                for _ in range(3):
                    if not refresh_toc_from_pdf(docx, pdf):
                        break
                    pdf.unlink(missing_ok=True)
                    remaining = 180.0 if deadline_monotonic is None else deadline_monotonic - clock()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired("DOCX rendering", 0)
                    pdf = export_docx(docx, attempt_root, identity, environment=runtime_environment, timeout_seconds=min(180.0, remaining))
                pdfs[docx] = pdf
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            renderer_attempts.append({"renderer": identity, "status": "failed", "issue": str(exc)})
            continue

        selected_page_renderer = None
        selected_pages: dict[Path, list[Path]] = {}
        for candidate in page_candidates:
            current_pages: dict[Path, list[Path]] = {}
            try:
                for docx, pdf in pdfs.items():
                    remaining = 180.0 if deadline_monotonic is None else deadline_monotonic - clock()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired("PDF page rendering", 0)
                    page_dir = attempt_root / docx.stem / str(candidate["kind"])
                    page_kwargs = {
                        "dpi": 130,
                        "timeout_seconds": min(PDFIUM_WORKER_TIMEOUT_SECONDS, remaining),
                    }
                    if page_exporter is None:
                        page_kwargs["require_promoted_runtime"] = require_promoted_runtime
                    pages = export_pages(pdf, page_dir, candidate, **page_kwargs)
                    expected = len(PdfReader(pdf).pages)
                    if len(pages) != expected or expected == 0:
                        raise RuntimeError(f"Page rendering failed for {docx.name}: expected {expected}, got {len(pages)}.")
                    current_pages[docx] = pages
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                page_attempts.append({"renderer": candidate, "status": "failed", "issue": str(exc)})
                continue
            selected_page_renderer = candidate
            selected_pages = current_pages
            page_attempts.append({"renderer": candidate, "status": "passed"})
            break
        if selected_page_renderer is None:
            terminal_issue = str(
                (page_attempts[-1] if page_attempts else {}).get("issue")
                or "The release-owned pypdfium2 page renderer failed."
            )
            terminal_code = terminal_issue.partition(": ")[0]
            if not terminal_code.startswith("renderer.pdfium_"):
                terminal_code = "renderer.pdfium_worker_failed"
            return {
                "status": "blocked",
                "renderer_attempts": renderer_attempts,
                "page_renderer_attempts": page_attempts,
                "findings": [{
                    "category": "renderer",
                    "field": "rendering",
                    "code": terminal_code,
                    "issue": terminal_issue,
                    "recovery_class": "adapter_fault",
                    "action": "stop",
                }],
            }

        findings: list[dict[str, Any]] = []
        artifacts = []
        if not selected_artifacts and render_root.exists():
            shutil.rmtree(render_root)
        render_root.mkdir(parents=True, exist_ok=True)
        for docx, source_pdf in pdfs.items():
            pdf = render_root / source_pdf.name
            pdf.unlink(missing_ok=True)
            shutil.copy2(source_pdf, pdf)
            page_dir = render_root / docx.stem
            shutil.rmtree(page_dir, ignore_errors=True)
            page_dir.mkdir()
            pages = []
            for index, source_page in enumerate(selected_pages[docx], 1):
                page = page_dir / f"page-{index}.png"
                shutil.copy2(source_page, page)
                pages.append(page)
            for page_number in find_blank_pages(pdf):
                findings.append({
                    "category": "visual",
                    "field": docx.stem,
                    "artifact": docx.stem,
                    "page": page_number,
                    "target_ids": [f"layout:{docx.stem}"],
                    "issue": f"Rendered {docx.stem} contains a textless page at page {page_number}.",
                })
            artifacts.append({
                "artifact": docx.stem,
                "status": "passed",
                "renderer": identity,
                "page_renderer": selected_page_renderer,
                "font_evidence": dict(font_evidence or {}),
                "font_substitutions": dict(font_substitutions or {}),
                "docx": docx.relative_to(revision_dir).as_posix(),
                "docx_sha256": sha256_file(docx),
                "pdf": pdf.relative_to(revision_dir).as_posix(),
                "pdf_sha256": sha256_file(pdf),
                "page_count": len(pages),
                "pages": [{"page": i, "path": page.relative_to(revision_dir).as_posix(), "sha256": sha256_file(page)} for i, page in enumerate(pages, 1)],
            })
        renderer_attempts.append({"renderer": identity, "status": "passed"})
        return {
            "status": "passed" if not findings else "blocked",
            "renderer": identity,
            "renderer_attempts": renderer_attempts,
            "page_renderer": selected_page_renderer,
            "page_renderer_attempts": page_attempts,
            "artifacts": artifacts,
            "findings": findings,
        }
    return {
        "status": "blocked",
        "renderer_attempts": renderer_attempts,
        "page_renderer_attempts": page_attempts,
        "findings": [{"category": "renderer", "field": "rendering", "issue": "Every local renderer/page-renderer combination failed."}],
    }


def render_assurance(
    repo_root: Path,
    revision_dir: Path,
    reference: Mapping[str, Any],
    *,
    contracted_bundle: Mapping[str, Any] | None = None,
    structural_validation: Mapping[str, Any],
    candidate_font_substitutions: Mapping[str, str] | None = None,
    rebuild_candidate: Any = None,
    artifact_names: Iterable[str] | None = None,
    renderer_identities: Iterable[Mapping[str, Any]] | None = None,
    page_renderer_identities: Iterable[Mapping[str, Any]] | None = None,
    deadline_seconds: float = 180.0,
    deadline_monotonic: float | None = None,
    clock: Any = time.monotonic,
    font_probe: Any = None,
    office_exporter: Any = None,
    page_exporter: Any = None,
    blank_page_detector: Any = None,
    require_promoted_runtime: bool = True,
) -> dict[str, Any]:
    """Resolve fonts and render one complete candidate through one assurance seam."""
    started = clock()
    deadline = deadline_monotonic if deadline_monotonic is not None else started + max(0.0, deadline_seconds)
    bundle = contracted_bundle or contracted_template_bundle(repo_root, reference)
    approved_font_plan = bundle["approved_font_plan"]
    runtime_environment = _runtime_environment(repo_root, None, bundle)
    selected_artifacts = set(artifact_names or ())
    all_candidate_paths = [path for path in sorted((revision_dir / "candidate").glob("*")) if path.is_file()]
    structural_evidence, structural_finding = _validated_candidate_structure(
        revision_dir,
        structural_validation,
        all_candidate_paths,
    )
    candidate_paths = [
        path
        for path in all_candidate_paths
        if path.suffix.casefold() == ".docx"
        if not selected_artifacts or path.stem in selected_artifacts
    ]
    if structural_finding is not None or not candidate_paths:
        finding = structural_finding or recovery_finding({
                "category": "document-structure",
                "field": "candidate",
                "issue": "Render Assurance requires a complete structurally validated DOCX candidate.",
            }, "document_structure_defect")
        return {
            "schema_version": "render-assurance/v1",
            "status": "blocked",
            "fonts": {},
            "font_substitutions": {},
            "candidate": {"files": []},
            "structural_validation": structural_evidence,
            "render": {"status": "not_run", "findings": [finding]},
            "findings": [finding],
        }

    required_fonts = sorted({font for path in candidate_paths for font in _template_fonts(path)})
    probe = font_probe or _font_probe
    fonts: dict[str, dict[str, Any]] = {}
    substitutions: dict[str, str] = {}
    for font in required_fonts:
        remaining = max(0.0, deadline - clock())
        if remaining <= 0:
            available, detail = None, "Render Assurance deadline expired before font inventory."
        else:
            available, detail = probe(font, environment=runtime_environment, timeout_seconds=remaining)
        state = "available" if available is True else "missing-or-unusable" if available is False else "unknown"
        evidence = {"state": state, "match": detail}
        if state == "unknown":
            evidence.update({
                "recovery_class": "font_capability_uncertainty",
                "action": RECOVERY_POLICIES["font_capability_uncertainty"],
            })
        if state == "missing-or-unusable":
            substitute = _approved_packaged_font_fallback(font, approved_font_plan)
            bundled = _bundled_font_path(repo_root, substitute, approved_font_plan)
            if bundled is not None:
                if substitute.casefold() != font.casefold():
                    substitutions[font] = substitute
                evidence.update({
                    "substitute": substitute,
                    "substitute_match": f"bundled approved compatible font: {bundled.relative_to(repo_root)}",
                })
            else:
                evidence["attempted_fallbacks"] = [substitute]
        fonts[font] = evidence

    prior_substitutions = dict(candidate_font_substitutions or {})
    for source, target in prior_substitutions.items():
        if source not in required_fonts and target in required_fonts:
            substitutions[source] = target
            fonts[source] = {
                "state": "missing-or-unusable",
                "match": "Persisted candidate substitution.",
                "substitute": target,
                "resolution": "candidate_substitution_preserved",
            }
    if substitutions != prior_substitutions:
        if rebuild_candidate is None:
            finding = recovery_finding({
                "category": "document-structure",
                "field": "font_substitutions",
                "issue": "The candidate must be rebuilt with the selected approved font substitutions before rendering.",
            }, "document_structure_defect")
            return {
                "schema_version": "render-assurance/v1",
                "status": "blocked",
                "fonts": fonts,
                "font_substitutions": substitutions,
                "candidate": {"files": _artifact_hashes(revision_dir, all_candidate_paths)},
                "render": {"status": "not_run", "findings": [finding]},
                "findings": [finding],
            }
        rebuild_report = rebuild_candidate(substitutions)
        if rebuild_report.get("status") != "passed":
            findings = [recovery_finding(finding, "document_structure_defect") for finding in (rebuild_report.get("findings") or [{
                "category": "document-structure",
                "field": "font_substitutions",
                "issue": "The candidate could not be rebuilt with approved font substitutions.",
            }])]
            return {
                "schema_version": "render-assurance/v1",
                "status": "blocked",
                "fonts": fonts,
                "font_substitutions": substitutions,
                "candidate": {"files": _artifact_hashes(revision_dir, all_candidate_paths)},
                "render": {"status": "not_run", "findings": findings},
                "findings": findings,
            }
        candidate_paths = [
            path
            for path in sorted((revision_dir / "candidate").glob("*.docx"))
            if not selected_artifacts or path.stem in selected_artifacts
        ]
        all_candidate_paths = [path for path in sorted((revision_dir / "candidate").glob("*")) if path.is_file()]
        post_rebuild_validation = {
            **dict(structural_validation),
            "candidate_files": _artifact_hashes(revision_dir, all_candidate_paths),
        }
        structural_evidence, structural_finding = _validated_candidate_structure(
            revision_dir,
            post_rebuild_validation,
            all_candidate_paths,
        )
        structural_evidence["revalidated_after_substitution"] = structural_finding is None
        if structural_finding is not None or not candidate_paths:
            finding = structural_finding or recovery_finding({
                "category": "document-structure",
                "field": "candidate",
                "issue": "The rebuilt candidate does not contain the selected DOCX artifacts.",
            }, "document_structure_defect")
            return {
                "schema_version": "render-assurance/v1",
                "status": "blocked",
                "fonts": fonts,
                "font_substitutions": substitutions,
                "candidate": {"files": _artifact_hashes(revision_dir, all_candidate_paths)},
                "structural_validation": structural_evidence,
                "render": {"status": "not_run", "findings": [finding]},
                "findings": [finding],
            }

    office_candidates = (
        [dict(item) for item in renderer_identities]
        if renderer_identities is not None
        else renderers(environment=runtime_environment, skill_root=repo_root, deadline_monotonic=deadline, clock=clock)
    )
    page_candidates = _one_pdfium_renderer(
        [dict(item) for item in page_renderer_identities]
        if page_renderer_identities is not None
        else page_renderers(
            environment=runtime_environment,
            skill_root=repo_root,
            require_promoted_runtime=require_promoted_runtime,
        ),
        skill_root=repo_root,
        require_promoted_runtime=require_promoted_runtime,
    )
    render_report = render_pages(
        revision_dir,
        artifact_names=artifact_names,
        contracted_bundle=bundle,
        renderer_identities=office_candidates,
        page_renderer_identities=(
            page_candidates
            if page_renderer_identities is not None or page_candidates
            else None
        ),
        deadline_monotonic=deadline,
        clock=clock,
        font_evidence=fonts,
        font_substitutions=substitutions,
        office_exporter=office_exporter,
        page_exporter=page_exporter,
        blank_page_detector=blank_page_detector,
        require_promoted_runtime=require_promoted_runtime,
    )
    render_report["renderer_attempts"] = _governed_adapter_attempts(render_report.get("renderer_attempts", []))
    render_report["page_renderer_attempts"] = _governed_adapter_attempts(
        render_report.get("page_renderer_attempts", []),
        failure_action="stop",
    )
    governed_findings = []
    for raw in render_report.get("findings", []):
        finding = dict(raw)
        if finding.get("category") == "visual":
            finding.update({
                "recovery_class": "visual_defect",
                "action": RECOVERY_POLICIES["visual_defect"],
            })
        elif finding.get("category") == "renderer" and not finding.get("recovery_class"):
            finding = recovery_finding(finding, "adapter_fault")
        governed_findings.append(finding)
    render_report["findings"] = governed_findings
    if render_report.get("status") == "passed":
        for evidence in fonts.values():
            if evidence["state"] == "unknown":
                evidence["resolution"] = "render_verified"
        for artifact in render_report.get("artifacts", []):
            artifact["font_evidence"] = fonts
    report = {
        "schema_version": "render-assurance/v1",
        "status": render_report.get("status", "blocked"),
        "fonts": fonts,
        "font_substitutions": substitutions,
        "candidate": {
            "files": _artifact_hashes(revision_dir, all_candidate_paths),
            "font_evidence": fonts,
            "font_substitutions": substitutions,
        },
        "structural_validation": structural_evidence,
        "render": render_report,
        "findings": governed_findings,
        "elapsed_seconds": round(clock() - started, 3),
    }
    if report["status"] != "passed" and governed_findings and all(
        finding.get("recovery_class") == "adapter_fault" for finding in governed_findings
    ):
        report["diagnostic"] = {
            "recovery_class": "adapter_fault",
            "action": RECOVERY_POLICIES["adapter_fault"],
            "outcome": "adapters_exhausted",
            "candidate_disposition": "preserved",
            "publication": "blocked",
            "office_attempts": render_report["renderer_attempts"],
            "page_attempts": render_report["page_renderer_attempts"],
            "font_evidence": fonts,
            "font_substitutions": substitutions,
            "candidate_files": report["candidate"]["files"],
        }
    return report


def _validated_candidate_structure(
    revision_dir: Path,
    validation: Mapping[str, Any],
    candidate_paths: Iterable[Path],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    paths = list(candidate_paths)
    current = _artifact_hashes(revision_dir, paths)
    expected = {str(name) for name in validation.get("expected_files", []) if str(name)}
    actual = {path.name for path in paths}
    recorded = {
        str(item.get("path")): item
        for item in validation.get("candidate_files", [])
        if isinstance(item, Mapping) and item.get("path")
    }
    evidence = {
        "status": validation.get("status"),
        "expected_files": sorted(expected),
        "candidate_files": current,
    }
    complete = (
        validation.get("status") == "structurally_valid"
        and bool(expected)
        and actual == expected
        and all(
            (row := recorded.get(item["path"])) is not None
            and row.get("sha256") == item["sha256"]
            and int(row.get("bytes") or 0) == item["bytes"]
            for item in current
        )
    )
    if complete:
        return evidence, None
    return evidence, recovery_finding({
        "category": "document-structure",
        "field": "candidate",
        "issue": "Render Assurance requires the complete structurally validated Branch Document Set with matching hashes.",
    }, "document_structure_defect")


def _governed_adapter_attempts(
    attempts: Iterable[Mapping[str, Any]],
    *,
    failure_action: str | None = None,
) -> list[dict[str, Any]]:
    governed = []
    for raw in attempts:
        attempt = {"adapter": dict(raw.get("renderer") or raw.get("adapter") or {}), "status": raw.get("status")}
        if raw.get("status") in {"failed", "skipped"}:
            attempt.update({
                "recovery_class": "adapter_fault",
                "action": failure_action or RECOVERY_POLICIES["adapter_fault"],
                "issue": str(raw.get("issue") or "Adapter did not complete."),
            })
        governed.append(attempt)
    return governed


def _artifact_hashes(revision_dir: Path, paths: Iterable[Path]) -> list[dict[str, Any]]:
    return [
        {
            "path": path.relative_to(revision_dir).as_posix(),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
        for path in paths
    ]


def deterministic_content_check(revision_dir: Path, reference: Mapping[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    branch = canonical_study_type(get_path(reference, "meta.study_type")) or ""
    icf_template = str(get_path(reference, "meta.icf_template", "Advarra"))
    draftable_sections = {
        section_id
        for batch in batch_plan(branch, icf_template)
        for section_id in batch.section_ids
    }
    protocol = revision_dir / "candidate/protocol.docx"
    findings.extend(audit_docx(protocol, required_phrases=[str(get_path(reference, "study.title", ""))]))
    document = Document(protocol)
    visible = "\n".join(p.text for p in document.paragraphs)
    normalized_visible = re.sub(r"\s+", " ", visible).casefold()
    source_visible = json.dumps(reference, ensure_ascii=False).casefold()
    def heading_key(value: str) -> str:
        first_line = next((line for line in value.splitlines() if line.strip()), "")
        normalized = re.sub(r"(?<=\d)\.(?=\s|$)", "", first_line)
        return re.sub(r"\s+", " ", normalized).strip().casefold()

    headings = [heading_key(p.text) for p in document.paragraphs if p.style.name.casefold().startswith("heading") and p.text.strip()]
    sections = protocol_contract(branch)
    for section in sections:
        expected = heading_key(f"{section.number} {section.title}")
        count = headings.count(expected)
        if count != 1:
            findings.append({"category": "content", "field": section.section_id, "target_ids": [section.section_id], "issue": f"Protocol section heading must appear exactly once; found {count}: {section.number} {section.title}"})
    stale_protocol_claims = {
        "an investigator-initiated clinical trial": "title-page",
        "all subjects will be monitored for adverse events": "quality-safety",
        "included on each case report form": "quality-safety",
        "1996 version of the declaration of helsinki": "ethics",
        "approval prior to initiating the study": "ethics",
    }
    for phrase, target in stale_protocol_claims.items():
        if phrase in normalized_visible and phrase not in source_visible:
            findings.append({"category": "content", "field": target, "target_ids": [target], "issue": f"Protocol contains unsupported client-template study language: {phrase}"})

    blocks: list[Paragraph | Table] = []
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            blocks.append(Paragraph(child, document))
        elif child.tag == qn("w:tbl"):
            blocks.append(Table(child, document))

    def heading_level(paragraph: Paragraph) -> int | None:
        if not paragraph.style.name.casefold().startswith("heading"):
            return None
        match = re.search(r"(\d+)$", paragraph.style.name)
        return int(match.group(1)) if match else 1

    def has_section_content(section: Any) -> bool | None:
        expected = heading_key(f"{section.number} {section.title}")
        target_index = next((
            index for index, block in enumerate(blocks)
            if isinstance(block, Paragraph) and heading_level(block) is not None and heading_key(block.text) == expected
        ), None)
        if target_index is None:
            return None
        target = blocks[target_index]
        assert isinstance(target, Paragraph)
        target_level = heading_level(target) or 1
        for block in blocks[target_index + 1:]:
            if isinstance(block, Paragraph):
                level = heading_level(block)
                if level is not None:
                    if level <= target_level:
                        break
                    continue
                if len(re.findall(r"\b\w+\b", block.text)) >= 3:
                    return True
            elif any(cell.text.strip() for row in block.rows for cell in row.cells):
                return True
        return False

    for section in sections:
        if section.role == "container":
            continue
        populated = has_section_content(section)
        if populated is False:
            findings.append({
                "category": "content",
                "field": section.section_id,
                "target_ids": [section.section_id],
                "issue": f"Protocol section has no substantive content after its heading: {section.number} {section.title}",
            })
    seen: dict[str, str] = {}
    current_section = ""
    heading_to_id = {heading_key(f"{section.number} {section.title}"): section.section_id for section in sections}
    for paragraph in document.paragraphs:
        text = re.sub(r"\s+", " ", paragraph.text).strip()
        if paragraph.style.name.casefold().startswith("heading"):
            current_section = heading_to_id.get(heading_key(paragraph.text), current_section)
            continue
        key = text.casefold()
        if len(text.split()) >= 8 and key in seen:
            if seen[key] == current_section:
                findings.append({"category": "content", "field": current_section or "protocol", "target_ids": [current_section or "protocol"], "issue": f"Exact paragraph is duplicated in protocol section {current_section or 'protocol'}."})
            else:
                findings.append({"category": "content", "field": current_section or "protocol", "target_ids": sorted({seen[key], current_section}), "issue": f"Exact paragraph is duplicated across protocol sections {seen[key]} and {current_section}."})
        elif len(text.split()) >= 8:
            seen[key] = current_section
    if branch == "Retrospective":
        if "approved visit schedule table is" in normalized_visible:
            findings.append({
                "category": "content",
                "field": "study-procedure.enrollment",
                "target_ids": ["study-procedure.enrollment"],
                "issue": "Retrospective study procedure contains flattened visit-schedule serialization instead of readable client-facing content.",
            })
        for field in ("population.inclusion_criteria", "population.exclusion_criteria"):
            value = get_path(reference, field, [])
            items = value if isinstance(value, list) else [value]
            for item in items:
                expected = re.sub(r"\s+", " ", _text(item)).strip().casefold().rstrip(".")
                if expected and expected not in normalized_visible:
                    findings.append({"category": "content", "field": "subjects.eligibility", "target_ids": ["subjects.eligibility"], "issue": f"Retrospective eligibility omits approved source content from {field}."})
        timeline = re.sub(r"\s+", " ", _text(get_path(reference, "study.timeline"))).strip().casefold().rstrip(".")
        if timeline and timeline not in normalized_visible:
            findings.append({"category": "content", "field": "study-procedure.enrollment", "target_ids": ["study-procedure.enrollment"], "issue": "Retrospective study procedure omits the approved study timeline."})
        schedule = get_path(reference, "procedures.visit_schedule_table", []) or []
        visit_names = [item.get("visitName") or item.get("visit") for item in schedule if isinstance(item, Mapping)]
        for visit_name in visit_names:
            expected = re.sub(r"\s+", " ", _text(visit_name)).strip().casefold()
            if expected and expected not in normalized_visible:
                findings.append({"category": "content", "field": "study-procedure.enrollment", "target_ids": ["study-procedure.enrollment"], "issue": f"Retrospective study procedure omits approved visit {visit_name}."})
    if branch != "Retrospective":
        icf = revision_dir / "candidate/icf.docx"
        findings.extend(audit_docx(icf, required_phrases=[str(get_path(reference, "study.title", ""))]))
        icf_document = Document(icf)
        icf_visible = re.sub(r"\s+", " ", " ".join(paragraph.text for paragraph in icf_document.paragraphs)).casefold()
        for section_id, title in icf_retained_sections(branch, icf_template):
            if title.casefold() not in icf_visible:
                findings.append(recovery_finding({
                    "category": "content",
                    "field": section_id,
                    "target_ids": ["layout:icf"],
                    "issue": f"Required retained ICF section is missing from the client shell: {title}",
                }, "document_structure_defect"))
        signature_marker = "signature of participant"
        if signature_marker not in icf_visible:
            findings.append(recovery_finding({
                "category": "content",
                "field": "icf.signature-block",
                "target_ids": ["layout:icf"],
                "issue": "Required participant signature block is missing from the ICF.",
            }, "document_structure_defect"))
        injury_or_costs = (
            "icf.injury" if "icf.injury" in draftable_sections
            else "icf.costs" if "icf.costs" in draftable_sections
            else "icf"
        )
        stale_icf_claims = {
            "eye tests and procedures": "icf.procedures",
            "routine cataract surgery": "icf.study-purpose",
            "company that makes the handpiece": "icf.study-purpose",
            "no additional side effects or risks expected": "icf.risks",
            "not to be used for participant enrollment": "icf.study-purpose",
            "advarra institutional review board": "icf.privacy",
            "all charges for medical care": injury_or_costs,
            "insurance company": injury_or_costs,
        }
        for phrase, target in stale_icf_claims.items():
            if phrase in icf_visible and phrase not in source_visible:
                findings.append({
                    "category": "content",
                    "field": target,
                    "target_ids": [target],
                    "issue": f"ICF contains example-study prose that is not supported by the approved source: {phrase}",
                })
        if _text(get_path(reference, "regulatory.prs.study_type")).casefold() == "observational" and "clinical trial" in icf_visible and "clinical trial" not in source_visible:
            findings.append({"category": "content", "field": "icf.study-purpose", "target_ids": ["icf.study-purpose"], "issue": "Observational ICF retains interventional clinical-trial language."})
        minimum_days = _text(get_path(reference, "procedures.minimum_days_before_screening_without_participation"))
        if minimum_days:
            day_pattern = re.compile(rf"\b{re.escape(minimum_days)}\s*[- ]?\s*days?\b", re.I)
            if not day_pattern.search(visible):
                findings.append({"category": "content", "field": "subjects.inclusion", "target_ids": ["subjects.inclusion"], "issue": "Protocol omits the approved minimum interval without participation in another study before screening."})
            if not day_pattern.search(icf_visible):
                findings.append({"category": "content", "field": "icf.procedures", "target_ids": ["icf.procedures"], "issue": "ICF omits the approved minimum interval without participation in another study before screening."})
            xml_path = revision_dir / "candidate/study.xml"
            if xml_path.is_file() and not day_pattern.search(xml_path.read_text(encoding="utf-8")):
                findings.append(recovery_finding({"category": "content", "field": "prs.eligibility", "target_ids": ["layout:xml"], "issue": "PRS XML omits the approved minimum interval without participation in another study before screening."}, "document_structure_defect"))
        consent_to_sign = any(phrase in icf_visible for phrase in (
            "should not sign",
            "if you would like to participate, you will be asked to sign",
            "if you agree to participate, you will be asked to sign",
        ))
        if not consent_to_sign:
            findings.append(recovery_finding({"category": "content", "field": "icf.consent", "target_ids": ["layout:icf"], "issue": "ICF lacks an explicit instruction not to sign when the participant does not agree."}, "document_structure_defect"))
    governed = []
    for item in findings:
        if item.get("recovery_class") in RECOVERY_POLICIES:
            governed.append(item)
            continue
        targets = item.get("target_ids") if isinstance(item.get("target_ids"), list) else []
        unlocalized = not targets or any(
            str(target).strip().casefold() in {"", "protocol", "icf"}
            or str(target) not in draftable_sections
            for target in targets
        )
        governed.append(recovery_finding(
            item,
            "document_structure_defect" if unlocalized else "drafting_defect",
        ))
    return governed


def create_verification_requests(
    revision_dir: Path,
    reference: Mapping[str, Any],
    render_report: Mapping[str, Any],
    *,
    contracted_bundle: Mapping[str, Any] | None = None,
) -> list[Path]:
    requests = revision_dir / "hermes/verification-requests"; responses = revision_dir / "hermes/verification-responses"
    responses.mkdir(parents=True, exist_ok=True)
    content_files = []
    for path in sorted((revision_dir / "candidate").glob("*")):
        if not path.is_file():
            continue
        artifact = {"path": path.relative_to(revision_dir).as_posix()}
        if path.suffix.casefold() == ".docx":
            artifact["content_sha256"] = _content_sha256(path)
        else:
            artifact["sha256"] = sha256_file(path)
        content_files.append(artifact)
    branch = canonical_study_type(get_path(reference, "meta.study_type")) or ""
    sections = [{"artifact": "protocol", "section_id": section.section_id, "number": section.number, "title": section.title} for section in protocol_contract(branch)]
    if branch != "Retrospective":
        choice = str(get_path(reference, "meta.icf_template", "Advarra"))
        sections.extend({"artifact": "icf", "section_id": section.section_id, "number": section.number, "title": section.title} for section in icf_contract(branch, choice))
        sections.extend({"artifact": "icf", "section_id": section_id, "number": "", "title": title} for section_id, title in icf_retained_sections(branch, choice))
    repo_root = Path(__file__).resolve().parents[1]
    bundle = dict(contracted_bundle or contracted_template_bundle(repo_root, reference))
    boilerplate_path = repo_root / str(bundle["fixed_clinical_boilerplate"]["path"])
    authorized_boilerplate = _json(boilerplate_path)
    if authorized_boilerplate.get("version") != BOILERPLATE_VERSION:
        raise ValueError("Verification boilerplate does not match the content contract.")
    cross_document_checks = [] if branch == "Retrospective" else list(CROSS_DOCUMENT_CHECKS)
    content_instructions = "Assess every listed section against every content check."
    if cross_document_checks:
        content_instructions += " Assess every cross-document check."
    content_instructions += (
        " Findings must include target_ids for affected section IDs. Treat exact authorized Fixed Clinical "
        "Boilerplate as approved non-study-specific content, not invention. Do not fail optional fields, dates, "
        "instruments, scoring rules, denominators, or policies that are absent from the approved source; instead "
        "fail only an unsupported affirmative claim or an omission of supplied material evidence. A document-control "
        "date may default from approval, while an unknown version must remain blank and must not be failed merely for "
        "being unknown."
    )
    payloads = [{
        "schema_version": VERIFY_SCHEMA,
        "request_id": f"{revision_dir.name}.verify.content",
        "task": "clinical_content_verification",
        "revision_id": revision_dir.name,
        "artifacts": content_files,
        "approved_source": reference,
        "authorized_boilerplate": authorized_boilerplate,
        "sections": sections,
        "checks": list(CONTENT_CHECKS),
        "cross_document_checks": cross_document_checks,
        "instructions": content_instructions,
        "response_path": f"hermes/verification-responses/{revision_dir.name}.verify.content.json",
    }]
    visual_artifacts = list(render_report.get("artifacts", []))
    visual_batches = [[artifact] for artifact in visual_artifacts] or [[]]
    for index, artifacts in enumerate(visual_batches, start=1):
        artifact_name = str(artifacts[0].get("artifact", "documents")) if artifacts else "documents"
        artifact_id = re.sub(r"[^a-z0-9]+", "-", artifact_name.casefold()).strip("-") or f"document-{index}"
        request_id = f"{revision_dir.name}.verify.visual.{artifact_id}"
        request_artifacts = [
            {key: value for key, value in artifact.items() if key not in {"renderer", "page_renderer"}}
            for artifact in artifacts
        ]
        payloads.append({
            "schema_version": VERIFY_SCHEMA,
            "request_id": request_id,
            "task": "rendered_page_visual_verification",
            "revision_id": revision_dir.name,
            "renderer": artifacts[0].get("renderer", render_report.get("renderer")) if artifacts else render_report.get("renderer"),
            "page_renderer": artifacts[0].get("page_renderer", render_report.get("page_renderer")) if artifacts else render_report.get("page_renderer"),
            "artifacts": request_artifacts,
            "checks": list(VISUAL_CHECKS),
            "instructions": "Inspect every supplied page image for this document. Do not infer pass from file existence or document text. Every repairable failure must identify artifact, check, and the exact element text of the affected heading or table caption so the repair remains local.",
            "reviewer_policy": {
                "image_inspection_required": True,
                "delegated_failure_fallback": "parent_reviews_the_same_bound_page_images",
                "deterministic_checks_alone_can_pass": False,
            },
            "response_path": f"hermes/verification-responses/{request_id}.json",
        })
    for payload in payloads:
        payload["contracted_template_bundle"] = bundle
        payload["request_sha256"] = verification_request_sha256(payload)
    expected = {payload["request_id"]: payload for payload in payloads}
    existing_paths = sorted(requests.glob("*.json"))
    existing = {}
    for path in existing_paths:
        try:
            item = _json(path); existing[item.get("request_id")] = (path, item)
        except (OSError, ValueError, json.JSONDecodeError):
            existing[path.name] = (path, {})
    for request_id, (path, request) in existing.items():
        replacement = expected.get(request_id)
        if (
            replacement is not None
            and verification_request_hash_valid(request)
            and request.get("request_sha256") == replacement["request_sha256"]
        ):
            continue
        response_path = request.get("response_path")
        if response_path:
            (revision_dir / str(response_path)).unlink(missing_ok=True)
        path.unlink(missing_ok=True)
    result = []
    for payload in payloads:
        path = requests / f"{payload['request_id']}.json"; _write(path, payload); result.append(path)
    return result


def pending_verifications(revision_dir: Path) -> list[Path]:
    pending = []
    for path in sorted((revision_dir / "hermes/verification-requests").glob("*.json")):
        request = _json(path)
        if not (revision_dir / request["response_path"]).is_file(): pending.append(path)
    return pending


def verification_response_is_complete(revision_dir: Path, request_path: Path) -> bool:
    """Return whether one current, bound verifier response satisfies its full pass contract."""
    try:
        request = _json(request_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    if not verification_request_hash_valid(request):
        return False
    findings, _ = validate_verifications(revision_dir, request_paths=[request_path])
    return not findings


def verification_response_is_terminal(revision_dir: Path, request_path: Path) -> bool:
    """Return whether a verifier produced a bound response the workflow can consume."""
    try:
        request = _json(request_path)
        if not isinstance(request, Mapping):
            return False
        response = _json(revision_dir / str(request.get("response_path") or ""))
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(response, Mapping):
        return False
    if not verification_request_hash_valid(request):
        return False
    if any(
        response.get(key) != expected
        for key, expected in (
            ("schema_version", RESPONSE_SCHEMA),
            ("request_id", request.get("request_id")),
            ("request_sha256", request.get("request_sha256")),
            ("task", request.get("task")),
        )
    ):
        return False
    producer = response.get("producer") if isinstance(response.get("producer"), Mapping) else {}
    if not _text(producer.get("model_id")):
        return False
    status = str(response.get("status") or "").casefold()
    if status == "passed":
        return verification_response_is_complete(revision_dir, request_path)
    findings = response.get("findings") if isinstance(response.get("findings"), list) else []
    if status == "blocked":
        return bool(findings) and all(
            isinstance(item, Mapping) and bool(_text(item.get("issue")))
            for item in findings
        )
    return False


def validate_verifications(
    revision_dir: Path,
    *,
    request_paths: Iterable[Path] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    findings: list[dict[str, Any]] = []; evidence: dict[str, Any] = {}
    request_records = [
        (request_path, _json(request_path))
        for request_path in sorted(
            request_paths
            if request_paths is not None
            else (revision_dir / "hermes/verification-requests").glob("*.json")
        )
    ]
    task_counts: dict[str, int] = {}
    for _, request in request_records:
        task = str(request.get("task"))
        task_counts[task] = task_counts.get(task, 0) + 1
    for request_path, request in request_records:
        response_path = revision_dir / request["response_path"]
        evidence_key = request["task"] if task_counts[str(request.get("task"))] == 1 else request["request_id"]
        verification_target = "verification:visual" if request["task"] == "rendered_page_visual_verification" else "verification:content"
        if not verification_request_hash_valid(request):
            findings.append(recovery_finding({
                "category": "verification",
                "field": "request_sha256",
                "target_ids": [verification_target],
                "issue": "Verification request body does not match its declared request hash.",
            }, "document_structure_defect"))
            continue
        if not response_path.is_file():
            findings.append(recovery_finding({"category": "verification", "field": request["task"], "target_ids": [verification_target], "issue": "Independent Hermes verification response is missing."}, "verifier_transient")); continue
        try: response = _json(response_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            findings.append(recovery_finding({"category": "verification", "field": request["task"], "target_ids": [verification_target], "issue": f"Invalid verification response: {exc}"}, "verifier_transient")); continue
        for key, expected in (("schema_version", RESPONSE_SCHEMA), ("request_id", request["request_id"]), ("request_sha256", request["request_sha256"]), ("task", request["task"])):
            if response.get(key) != expected: findings.append(recovery_finding({"category": "verification", "field": key, "issue": f"Verification response binding mismatch for {key}."}, "document_structure_defect"))
        producer = response.get("producer") if isinstance(response.get("producer"), Mapping) else {}
        if not _text(producer.get("model_id")): findings.append(recovery_finding({"category": "verification", "field": "producer.model_id", "target_ids": [verification_target], "issue": "Verifier identity is missing."}, "verifier_transient"))
        error = response.get("error") if isinstance(response.get("error"), Mapping) else {}
        error_type = _text(error.get("type")).casefold()
        transient = str(response.get("status") or "").casefold() in TRANSIENT_REVIEW_STATUSES or error_type in {
            "api_unavailable", "connection_error", "rate_limit", "timeout", "service_unavailable"
        }
        if transient:
            findings.append(recovery_finding({
                "category": "reviewer-transient",
                "field": request["task"],
                "target_ids": [verification_target],
                "issue": _text(error.get("message")) or "Independent Hermes verifier reported a transient API failure.",
            }, "verifier_transient"))
            evidence[evidence_key] = {"request": request_path.relative_to(revision_dir).as_posix(), "request_sha256": sha256_file(request_path), "response": response_path.relative_to(revision_dir).as_posix(), "response_sha256": sha256_file(response_path), "producer": producer, "status": "transient", "contracted_template_bundle": request.get("contracted_template_bundle")}
            continue
        issues = response.get("findings") if isinstance(response.get("findings"), list) else []
        if response.get("status") != "passed" or issues:
            for item in issues or [{"issue": "Verifier did not pass the artifact."}]:
                source = item if isinstance(item, Mapping) else {"issue": item}
                category = "visual" if request["task"] == "rendered_page_visual_verification" else "verification"
                finding = {"category": category, "field": request["task"], "issue": _text(source.get("issue"))}
                for key in ("target_ids", "artifact", "page", "check", "element"):
                    if key in source: finding[key] = source[key]
                if category == "visual":
                    finding["target_ids"] = [f"layout:{source.get('artifact') or 'documents'}"]
                elif not finding.get("target_ids"):
                    finding["target_ids"] = ["verification:content"]
                findings.append(recovery_finding(
                    finding,
                    "visual_defect" if category == "visual" else "drafting_defect",
                ))
        for artifact in request.get("artifacts", []):
            if request["task"] == "clinical_content_verification":
                path = revision_dir / str(artifact.get("path"))
                expected = artifact.get("content_sha256") or artifact.get("sha256")
                actual = None
                if path.is_file():
                    actual = _content_sha256(path) if artifact.get("content_sha256") else sha256_file(path)
                if not path.is_file() or actual != expected:
                    findings.append(recovery_finding({"category": "verification", "field": request["task"], "issue": f"Verification request is stale for {artifact.get('path')}."}, "document_structure_defect"))
            else:
                for key in ("docx", "pdf"):
                    path = revision_dir / str(artifact.get(key))
                    if not path.is_file() or sha256_file(path) != artifact.get(f"{key}_sha256"):
                        findings.append(recovery_finding({"category": "verification", "field": artifact.get("artifact", key), "issue": f"Visual verification request is stale for {artifact.get(key)}."}, "document_structure_defect"))
                for page in artifact.get("pages", []):
                    path = revision_dir / str(page.get("path"))
                    if not path.is_file() or sha256_file(path) != page.get("sha256"):
                        findings.append(recovery_finding({"category": "verification", "field": artifact.get("artifact", "page"), "issue": f"Visual verification request is stale for {page.get('path')}."}, "document_structure_defect"))
        if request["task"] == "clinical_content_verification":
            expected_sections = {(item["artifact"], item["section_id"]) for item in request.get("sections", [])}
            valid_section_rows = [item for item in response.get("section_assessments", []) if isinstance(item, Mapping) and item.get("status") == "passed" and set(item.get("checks", [])) == set(CONTENT_CHECKS)]
            assessed_sections = {(item.get("artifact"), item.get("section_id")) for item in valid_section_rows}
            if expected_sections != assessed_sections or len(valid_section_rows) != len(expected_sections):
                findings.append(recovery_finding({"category": "verification", "field": request["task"], "target_ids": [verification_target], "issue": f"Every contracted section and content check must be explicitly assessed; expected {len(expected_sections)}, accepted {len(assessed_sections)}."}, "verifier_transient"))
            expected_cross = set(request.get("cross_document_checks", []))
            valid_cross_rows = [item for item in response.get("cross_document_assessments", []) if isinstance(item, Mapping) and item.get("status") == "passed"]
            assessed_cross = {item.get("check") for item in valid_cross_rows}
            if expected_cross != assessed_cross or len(valid_cross_rows) != len(expected_cross):
                findings.append(recovery_finding({"category": "verification", "field": request["task"], "target_ids": [verification_target], "issue": f"Every cross-document check must be explicitly assessed; expected {len(expected_cross)}, accepted {len(assessed_cross)}."}, "verifier_transient"))
        if request["task"] == "rendered_page_visual_verification":
            expected_pages = {(a["artifact"], p["page"], p["sha256"]) for a in request.get("artifacts", []) for p in a.get("pages", [])}
            valid_page_rows = [p for p in response.get("page_assessments", []) if isinstance(p, Mapping) and p.get("status") == "passed" and set(p.get("checks", [])) == set(VISUAL_CHECKS)]
            assessed = {(p.get("artifact"), p.get("page"), p.get("sha256")) for p in valid_page_rows}
            if expected_pages != assessed or len(valid_page_rows) != len(expected_pages): findings.append(recovery_finding({"category": "verification", "field": "page_assessments", "target_ids": [verification_target], "issue": f"Every rendered page and every visual check must be explicitly assessed; expected {len(expected_pages)}, accepted {len(assessed)}."}, "verifier_transient"))
        evidence[evidence_key] = {
            "request": request_path.relative_to(revision_dir).as_posix(),
            "request_sha256": sha256_file(request_path),
            "response": response_path.relative_to(revision_dir).as_posix(),
            "response_sha256": sha256_file(response_path),
            "producer": producer,
            "artifacts": request.get("artifacts", []),
            "contracted_template_bundle": request.get("contracted_template_bundle"),
        }
    return findings, evidence


def quality_report(revision_dir: Path, reference: Mapping[str, Any], render_report: Mapping[str, Any], xml_report: Mapping[str, Any] | None) -> dict[str, Any]:
    findings = deterministic_content_check(revision_dir, reference)
    findings.extend(dict(item) for item in render_report.get("findings", []))
    if xml_report:
        findings.extend(recovery_finding(item, "document_structure_defect") for item in xml_report.get("findings", []))
    verification_findings, evidence = validate_verifications(revision_dir)
    findings.extend(verification_findings)
    return {"status": "passed" if not findings else "blocked", "findings": findings, "renderer": render_report.get("renderer"), "verification_evidence": evidence}


__all__ = ["CONTENT_CHECKS", "CROSS_DOCUMENT_CHECKS", "FORMAT_CONFORMANCE_MATRIX", "GOVERNED_GATE_SEQUENCE", "ICF_RETAINED_SHELL_SECTIONS", "PAGE_RENDERER_BACKENDS", "RECOVERY_POLICIES", "RESPONSE_SCHEMA", "VISUAL_CHECKS", "advance_gate_ledger", "audit_format_conformance_outputs", "build_gate_ledger", "canonical_evidence_sha256", "create_verification_requests", "deterministic_content_check", "load_format_conformance_matrix", "normalized_docx_format_signature", "page_renderer", "page_renderers", "pending_verifications", "preflight", "quality_report", "rasterize_pdf", "recovery_finding", "render_assurance", "render_pages", "renderer", "renderers", "retry_gate_ledger", "sha256_file", "validate_gate_ledger", "verification_request_hash_valid", "verification_request_sha256", "verification_response_is_complete", "verification_response_is_terminal"]
