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

#: Bundled templates whose visit schedule must be a Data-Driven Table.
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


def bundled_template_findings() -> list[dict]:
    """Every contract violation across the bundled templates that require one."""
    findings: list[dict] = []
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
