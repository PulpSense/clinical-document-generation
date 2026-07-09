#!/usr/bin/env python3
"""Audit static DOCX table-of-contents page numbers and alignment."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


TOC_LINE_RE = re.compile(r"^(?P<title>.+?)(?:\t|\s*\.{3,}\s*)(?P<page>\d+)\s*$")
LEADING_NUMBER_RE = re.compile(r"^(?P<number>\d+)(?:\.(?=\s)|\s+\.)")
ROOT_SECTION_RE = re.compile(r"^(?P<number>\d+)(?:\.|\s)")


def require_imports():
    try:
        from docx import Document
        from docx.enum.text import WD_TAB_ALIGNMENT, WD_TAB_LEADER
    except ImportError as exc:
        raise SystemExit("python-docx is required to audit DOCX TOC entries.") from exc
    try:
        import pdfplumber
    except ImportError as exc:
        raise SystemExit("pdfplumber is required to audit rendered PDF pages.") from exc
    return Document, WD_TAB_ALIGNMENT, WD_TAB_LEADER, pdfplumber


def normalize(value: str) -> str:
    value = value.replace("\u00a0", " ")
    value = re.sub(r"\s+", " ", value).strip()
    value = LEADING_NUMBER_RE.sub(lambda match: f"{match.group('number')}.", value)
    return value


def has_right_dot_leader_tab(paragraph: Any, alignment: Any, leader: Any) -> bool:
    text = paragraph.text.replace("\u00a0", " ")
    if "\t" not in text:
        return False
    for tab in paragraph.paragraph_format.tab_stops:
        if tab.alignment == alignment.RIGHT and tab.leader == leader.DOTS:
            return True
    return False


def toc_entries(docx_path: Path) -> list[dict[str, Any]]:
    Document, WD_TAB_ALIGNMENT, WD_TAB_LEADER, _ = require_imports()
    document = Document(str(docx_path))
    entries: list[dict[str, Any]] = []
    for index, paragraph in enumerate(document.paragraphs):
        text = paragraph.text.replace("\u00a0", " ").strip()
        match = TOC_LINE_RE.match(text)
        if not match:
            continue
        title = normalize(match.group("title"))
        entries.append(
            {
                "paragraph_index": index,
                "title": title,
                "listed_page": int(match.group("page")),
                "alignment_ok": has_right_dot_leader_tab(paragraph, WD_TAB_ALIGNMENT, WD_TAB_LEADER),
            }
        )
    return entries


def rendered_pages(pdf_path: Path) -> list[str]:
    _, _, _, pdfplumber = require_imports()
    with pdfplumber.open(str(pdf_path)) as pdf:
        return [page.extract_text() or "" for page in pdf.pages]


def is_toc_or_index_title(title: str) -> bool:
    normalized = normalize(title).upper()
    return "TABLE OF CONTENTS" in normalized or normalized == "INDEX" or normalized.endswith(" INDEX")


def toc_like_line_count(text: str) -> int:
    return sum(1 for line in text.splitlines() if TOC_LINE_RE.match(normalize(line)))


def page_has_toc_or_index_heading(text: str) -> bool:
    normalized = normalize(text).upper()
    if "TABLE OF CONTENTS" in normalized:
        return True
    return any(normalize(line).upper() == "INDEX" for line in text.splitlines())


def root_section_number(title: str) -> int | None:
    match = ROOT_SECTION_RE.match(normalize(title))
    return int(match.group("number")) if match else None


def search_after_toc_flags(entries: list[dict[str, Any]]) -> list[bool]:
    """Mark TOC entries whose real headings must be found after the TOC/index.

    Static TOC pages contain every later heading title as entry text. If the audit
    searches those pages for post-TOC sections, it can accept the TOC entry itself
    as the rendered heading and write a stale page number back into the index.
    """

    toc_entry_index = None
    for index, entry in enumerate(entries):
        if is_toc_or_index_title(entry["title"]):
            toc_entry_index = index
            break
    if toc_entry_index is None:
        previous_root = None
        inferred_post_toc_index = None
        for index, entry in enumerate(entries):
            root = root_section_number(entry["title"])
            if root is None:
                continue
            if previous_root is not None and root > previous_root + 1:
                inferred_post_toc_index = index
                break
            previous_root = max(previous_root or root, root)
        if inferred_post_toc_index is None:
            return [False for _ in entries]
        return [index >= inferred_post_toc_index for index, _entry in enumerate(entries)]
    return [index > toc_entry_index for index, _entry in enumerate(entries)]


def min_search_page(title: str, toc_end_page: int, search_after_toc: bool = False) -> int:
    if search_after_toc or title.startswith("Table "):
        return toc_end_page + 1
    return 1


def page_contains_heading(title: str, text: str, allow_substring: bool = False) -> bool:
    title_norm = normalize(title)
    if not title_norm:
        return False
    page_norm = normalize(text)
    lines = [normalize(line) for line in text.splitlines()]
    if any(line == title_norm for line in lines):
        return True
    # Some PDF extractors join wrapped heading text with nearby body text. Only
    # use substring matching after the rendered TOC/index pages have been
    # excluded, otherwise a TOC row can masquerade as the section heading.
    return allow_substring and title_norm in page_norm


def toc_end_page(pages: list[str]) -> int:
    toc_pages = [
        index
        for index, text in enumerate(pages, start=1)
        if page_has_toc_or_index_heading(text)
    ]
    if not toc_pages:
        toc_pages = [
            index
            for index, text in enumerate(pages, start=1)
            if toc_like_line_count(text) >= 3
        ]
        if not toc_pages:
            return 0
    end = max(toc_pages)
    for page_number in range(end + 1, len(pages) + 1):
        if toc_like_line_count(pages[page_number - 1]) < 3:
            break
        end = page_number
    return end


def find_actual_page(title: str, pages: list[str], toc_end: int, search_after_toc: bool = False) -> int | None:
    title_norm = normalize(title)
    start = min_search_page(title_norm, toc_end, search_after_toc)
    for page_number, text in enumerate(pages, start=1):
        if page_number < start:
            continue
        if page_contains_heading(title_norm, text, allow_substring=search_after_toc):
            return page_number
    return None


def resolved_search_after_toc_flags(
    entries: list[dict[str, Any]],
    pages: list[str],
    toc_end: int,
) -> list[bool]:
    """Prefer post-TOC lookup whenever the rendered heading exists there.

    Some client templates do not include an explicit `TABLE OF CONTENTS` or
    `INDEX` row in the static index. The heuristic in `search_after_toc_flags`
    handles common numbering jumps, but this PDF-backed pass is the durable
    guard: if an entry's real heading is present after the rendered TOC/index
    pages, the audit must use that occurrence instead of any front-matter TOC
    row containing the same title.
    """

    flags = search_after_toc_flags(entries)
    resolved = []
    for entry, inferred in zip(entries, flags):
        if inferred or is_toc_or_index_title(entry["title"]):
            resolved.append(inferred)
            continue
        actual_after_toc = find_actual_page(entry["title"], pages, toc_end, search_after_toc=True)
        resolved.append(actual_after_toc is not None)
    return resolved


def audit(docx_path: Path, pdf_path: Path) -> dict[str, Any]:
    pages = rendered_pages(pdf_path)
    toc_end = toc_end_page(pages)
    entries = toc_entries(docx_path)
    post_toc_flags = resolved_search_after_toc_flags(entries, pages, toc_end)
    results = []
    for entry, search_after_toc in zip(entries, post_toc_flags):
        actual = find_actual_page(entry["title"], pages, toc_end, search_after_toc)
        ok = actual == entry["listed_page"] and entry.get("alignment_ok") is True
        results.append({**entry, "actual_page": actual, "searched_after_toc": search_after_toc, "ok": ok})
    page_mismatches = [item for item in results if item["actual_page"] != item["listed_page"]]
    alignment_mismatches = [item for item in results if item.get("alignment_ok") is not True]
    missing = [item for item in results if item["actual_page"] is None]
    return {
        "docx": str(docx_path),
        "pdf": str(pdf_path),
        "page_count": len(pages),
        "toc_end_page": toc_end,
        "entry_count": len(entries),
        "mismatch_count": len(page_mismatches),
        "alignment_mismatch_count": len(alignment_mismatches),
        "missing_count": len(missing),
        "entries": results,
        "mismatches": page_mismatches,
        "alignment_mismatches": alignment_mismatches,
        "missing": missing,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docx", required=True, help="DOCX containing static TOC entries.")
    parser.add_argument("--pdf", required=True, help="Rendered PDF for actual page lookup.")
    parser.add_argument("--output", help="Optional JSON report path.")
    args = parser.parse_args()

    result = audit(Path(args.docx).expanduser().resolve(), Path(args.pdf).expanduser().resolve())
    rendered = json.dumps(result, indent=2)
    if args.output:
        output_path = Path(args.output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 1 if result["mismatch_count"] or result["missing_count"] or result["alignment_mismatch_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
