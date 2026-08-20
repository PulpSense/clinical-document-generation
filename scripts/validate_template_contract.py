#!/usr/bin/env python3
"""Hold bundled templates to the structural contract their branch requires.

Placeholder resolution is not enough. A visit schedule whose row still consumes
the legacy scalar placeholders resolves cleanly and then renders every visit
newline-packed into one table cell. This module rejects that shape in the
bundled templates so the one-row regression cannot re-enter the package.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import zipfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
BUNDLED_DOCX_DIR = SKILL_DIR / "assets" / "client-templates" / "docx"

ROW_RE = re.compile(r"<w:tr\b[^>]*>.*?</w:tr>", re.DOTALL)
TABLE_RE = re.compile(r"<w:tbl>.*?</w:tbl>", re.DOTALL)
TEXT_RE = re.compile(r"<w:t\b[^>]*>(.*?)</w:t>", re.DOTALL)

#: Compatibility fields kept for older external templates. They may never carry
#: a visit schedule in a bundled template that requires real rows.
LEGACY_VISIT_PLACEHOLDERS = {
    "AI_visitNumber",
    "AI_visitName",
    "AI_visitWindow",
    "AI_CRFnumber",
}

#: The structured rows a compliant visit table repeats over.
VISIT_BLOCK_PATH = "visits"
#: Table 15.1 is inserted where this placeholder sits. A template that drops it
#: silently loses the section, exactly as the visit table was once lost.
STRUCTURAL_TABLE_PLACEHOLDER = "{visitsTable}"

#: Bundled templates whose visit schedule must be a Data-Driven Table.
PARAGRAPH_RE = re.compile(r"<w:p\b[^>]*>.*?</w:p>", re.DOTALL)

#: Every bundled protocol template, whose static TOC must describe its body.
PROTOCOL_TEMPLATES = (
    "prospective-protocol.template.docx",
    "ambispective-protocol.template.docx",
    "retrospective-protocol.template.docx",
)

VISIT_TABLE_TEMPLATES = (
    "prospective-protocol.template.docx",
    "ambispective-protocol.template.docx",
)


def visible_text(fragment: str) -> str:
    return "".join(html.unescape(match.group(1)) for match in TEXT_RE.finditer(fragment))


def document_parts(path: Path) -> dict[str, str]:
    parts: dict[str, str] = {}
    with zipfile.ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            if name.startswith("word/") and name.endswith(".xml"):
                parts[name] = archive.read(name).decode("utf-8", errors="ignore")
    return parts


def is_visit_table(rows: list[str]) -> bool:
    """A visit schedule table, identified by its header row."""
    if not rows:
        return False
    header = visible_text(rows[0]).replace(" ", "").replace(" ", "").lower()
    return "visitwindow" in header or ("visit" in header and "crf" in header)


def visit_table_findings(template_path: Path) -> list[dict]:
    """Contract violations in `template_path`'s visit schedule table."""
    findings: list[dict] = []
    template = Path(template_path)
    for part_name, xml in document_parts(template).items():
        for table in TABLE_RE.findall(xml):
            rows = ROW_RE.findall(table)
            if not is_visit_table(rows):
                continue
            body = rows[1:]
            table_text = visible_text(table)
            for placeholder in sorted(LEGACY_VISIT_PLACEHOLDERS):
                if "{" + placeholder + "}" in table_text:
                    findings.append(
                        {
                            "template": template.name,
                            "part": part_name,
                            "placeholder": placeholder,
                            "issue": (
                                "Legacy scalar visit placeholder in a visit schedule table. "
                                "Repeat a row over "
                                f"{{#{VISIT_BLOCK_PATH}}}...{{/{VISIT_BLOCK_PATH}}} instead."
                            ),
                        }
                    )
            if not any(
                "{#" + VISIT_BLOCK_PATH + "}" in visible_text(row) for row in body
            ):
                findings.append(
                    {
                        "template": template.name,
                        "part": part_name,
                        "placeholder": f"{{#{VISIT_BLOCK_PATH}}}",
                        "issue": (
                            "The visit schedule table has no repeated row block, so it cannot "
                            "render one real row per visit."
                        ),
                    }
                )
    return findings


def missing_visit_table_findings(template_path: Path) -> list[dict]:
    """Report a template that should carry a visit table but has none."""
    template = Path(template_path)
    for xml in document_parts(template).values():
        for table in TABLE_RE.findall(xml):
            if is_visit_table(ROW_RE.findall(table)):
                return []
    return [
        {
            "template": template.name,
            "part": "word/document.xml",
            "placeholder": f"{{#{VISIT_BLOCK_PATH}}}",
            "issue": "The branch requires a visit schedule table, but the template has none.",
        }
    ]


def missing_structural_table_findings(template_path: Path) -> list[dict]:
    """Report a template that no longer carries its structural table placeholder."""
    template = Path(template_path)
    for xml in document_parts(template).values():
        if STRUCTURAL_TABLE_PLACEHOLDER in visible_text(xml):
            return []
    return [
        {
            "template": template.name,
            "part": "word/document.xml",
            "placeholder": STRUCTURAL_TABLE_PLACEHOLDER,
            "issue": (
                "The branch requires a structural assessments table, but the "
                "template has no placeholder to insert one into."
            ),
        }
    ]


def orphan_toc_findings(template_path: Path) -> list[dict]:
    """Report static TOC entries that no heading in the body answers to.

    A heading may share its paragraph with the content that follows it, as
    `9.1. Analysis Data Sets {AI_analysisDataSets}` does, so an entry counts as
    answered when a body paragraph *starts with* its title.
    """
    from audit_static_toc import TOC_LINE_RE, toc_entries

    template = Path(template_path)
    entries = toc_entries(template)
    if not entries:
        return []

    with zipfile.ZipFile(template) as archive:
        xml = archive.read("word/document.xml").decode("utf-8", errors="ignore")
    # A TOC row carries its page number after a tab or a run of dots. Reusing
    # the reader's own test keeps this working whether the leader is literal
    # dots or a right-aligned dot-leader tab stop.
    body = []
    for match in PARAGRAPH_RE.finditer(xml):
        text = visible_text(match.group(0)).replace("\u00a0", " ").strip()
        if TOC_LINE_RE.match(text):
            continue
        body.append(" ".join(text.split()).lower())

    findings = []
    for entry in entries:
        title = " ".join(entry["title"].split()).lower()
        if any(paragraph.startswith(title) for paragraph in body):
            continue
        findings.append(
            {
                "template": template.name,
                "part": "word/document.xml",
                "entry": entry["title"],
                "issue": (
                    "The static table of contents lists a section the document "
                    "body does not contain."
                ),
            }
        )
    return findings


def bundled_template_findings() -> list[dict]:
    """Every contract violation across the bundled templates that require one."""
    findings: list[dict] = []
    for name in PROTOCOL_TEMPLATES:
        template = BUNDLED_DOCX_DIR / name
        if template.exists():
            findings.extend(orphan_toc_findings(template))
    for name in VISIT_TABLE_TEMPLATES:
        template = BUNDLED_DOCX_DIR / name
        if not template.exists():
            findings.append(
                {
                    "template": name,
                    "part": None,
                    "placeholder": None,
                    "issue": "Bundled template is missing.",
                }
            )
            continue
        findings.extend(missing_visit_table_findings(template))
        findings.extend(missing_structural_table_findings(template))
        findings.extend(visit_table_findings(template))
    return findings


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "templates",
        nargs="*",
        help="Template paths to check. Defaults to the bundled templates with a contract.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.templates:
        findings: list[dict] = []
        for raw in args.templates:
            path = Path(raw).expanduser().resolve()
            findings.extend(missing_visit_table_findings(path))
            findings.extend(visit_table_findings(path))
    else:
        findings = bundled_template_findings()
    print(json.dumps({"finding_count": len(findings), "findings": findings}, indent=2))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
