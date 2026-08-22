#!/usr/bin/env python3
"""Parse an edited Markdown source-of-truth file back into study.reference.json."""

from __future__ import annotations

import argparse
import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from study_type_branches import canonical_study_type, default_document_set, get_path


STANDARD_REFERENCE = "reference/study.reference.json"
STANDARD_REPORT = "reference/review-parse-report.md"
FIELD_RE = re.compile(
    r"<!--\s*field:\s*([A-Za-z_][A-Za-z0-9_.-]*)\s*-->\s*(.*?)\s*<!--\s*/field\s*-->",
    re.DOTALL,
)
STUDY_HEADER_RE = re.compile(r"^Study(?: preview, not editable)?:\s*(.+?)\s*$", re.MULTILINE)
RESET_ROOTS = [
    "study",
    "parties",
    "sites",
    "population",
    "design",
    "objectives",
    "endpoints",
    "procedures",
    "statistics",
    "risks_benefits",
    "generated",
    "regulatory",
    "references",
]


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def display_path(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.name


def extract_rows(markdown_path: Path) -> tuple[list[tuple[str, str]], list[str]]:
    text = markdown_path.read_text(encoding="utf-8")
    parsed = [(match.group(1).strip(), match.group(2).strip()) for match in FIELD_RE.finditer(text)]
    warnings = []
    if not parsed:
        warnings.append("No source-of-truth field markers were found.")
    return parsed, warnings


def extract_study_header(markdown_path: Path) -> str | None:
    text = markdown_path.read_text(encoding="utf-8")
    match = STUDY_HEADER_RE.search(text)
    return match.group(1).strip() if match else None


def scalar_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def get_row_value(rows: list[tuple[str, str]], field_id: str) -> str | None:
    for row_field, row_value in rows:
        if row_field == field_id:
            return row_value.strip()
    return None


def replace_row(rows: list[tuple[str, str]], field_id: str, value: str) -> list[tuple[str, str]]:
    replaced = False
    updated: list[tuple[str, str]] = []
    for row_field, row_value in rows:
        if row_field == field_id:
            updated.append((row_field, value))
            replaced = True
        else:
            updated.append((row_field, row_value))
    if not replaced:
        updated.append((field_id, value))
    return updated


def reconcile_study_header(original: dict, rows: list[tuple[str, str]], header_title: str | None) -> tuple[list[tuple[str, str]], list[str]]:
    if not header_title:
        return rows, []

    field_title = get_row_value(rows, "study.title")
    if not field_title or field_title == header_title:
        return rows, []

    original_title = scalar_text(get_path(original, "study.title"))
    if field_title == original_title and header_title != original_title:
        return replace_row(rows, "study.title", header_title), []

    if header_title == original_title and field_title != original_title:
        return rows, []

    return rows, [
        "The visible `Study:` header differs from the mapped `study.title` field. "
        "The mapped field value was used; edit the `study.title` field block if the title should change."
    ]


def parse_list(value: str) -> list[str]:
    items = []
    for raw_line in value.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^[•*\-]\s*", "", line).strip()
        if line:
            items.append(line)
    return items


def coerce_value(value: str, original_value: Any) -> Any:
    if value == "":
        return None
    if isinstance(original_value, bool):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "y", "1"}:
            return True
        if normalized in {"false", "no", "n", "0"}:
            return False
    if isinstance(original_value, int) and not isinstance(original_value, bool):
        try:
            return int(value)
        except ValueError:
            return value
    if isinstance(original_value, float):
        try:
            return float(value)
        except ValueError:
            return value
    if isinstance(original_value, list):
        if all(not isinstance(item, (dict, list)) for item in original_value):
            return parse_list(value)
    return value


def ensure_list_length(values: list, index: int) -> None:
    while len(values) <= index:
        values.append(None)


def set_path(data: dict, dotted_path: str, value: Any) -> None:
    parts = dotted_path.split(".")
    current: Any = data
    for index, part in enumerate(parts[:-1]):
        next_part = parts[index + 1]
        next_is_list = next_part.isdigit()
        if part.isdigit():
            list_index = int(part)
            if not isinstance(current, list):
                raise ValueError(f"List index `{part}` cannot be applied at `{dotted_path}`.")
            ensure_list_length(current, list_index)
            if current[list_index] is None or not isinstance(current[list_index], (dict, list)):
                current[list_index] = [] if next_is_list else {}
            current = current[list_index]
            continue
        if isinstance(current, list):
            raise ValueError(f"Object key `{part}` cannot be applied to a list at `{dotted_path}`.")
        if part not in current or current[part] is None or not isinstance(current[part], (dict, list)):
            current[part] = [] if next_is_list else {}
        current = current[part]

    final = parts[-1]
    if final.isdigit():
        if not isinstance(current, list):
            raise ValueError(f"Final list index `{final}` cannot be applied at `{dotted_path}`.")
        list_index = int(final)
        ensure_list_length(current, list_index)
        current[list_index] = value
    else:
        if isinstance(current, list):
            raise ValueError(f"Final object key `{final}` cannot be applied to a list at `{dotted_path}`.")
        current[final] = value


def reset_reference(original: dict) -> dict:
    reference = deepcopy(original)
    for root in RESET_ROOTS:
        if root == "sites" or isinstance(reference.get(root), list):
            reference[root] = []
        elif root in reference:
            reference[root] = {}
    reference["template_fields"] = {}
    reference["needs_review"] = []
    return reference


def apply_rows(original: dict, parsed_rows: list[tuple[str, str]]) -> tuple[dict, list[str]]:
    reference = reset_reference(original)
    warnings: list[str] = []
    for field_id, raw_value in parsed_rows:
        if field_id.startswith(("generated.", "template_fields.", "source.", "approval.", "needs_review.")):
            warnings.append(f"Skipped non-source field id `{field_id}`.")
            continue
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_.-]*$", field_id):
            warnings.append(f"Skipped invalid field id `{field_id}`.")
            continue
        original_value = get_path(original, field_id)
        try:
            set_path(reference, field_id, coerce_value(raw_value, original_value))
        except ValueError as exc:
            warnings.append(str(exc))

    meta = reference.get("meta")
    if not isinstance(meta, dict):
        meta = {}
        reference["meta"] = meta
    canonical = canonical_study_type(meta.get("study_type"))
    if canonical:
        meta["study_type"] = canonical
        if not meta.get("document_set"):
            meta["document_set"] = default_document_set(canonical)
    return reference, warnings


def write_report(path: Path, parsed_count: int, warnings: list[str], markdown_rel: str, output_rel: str) -> None:
    lines = [
        "# Source Of Truth Parse Report",
        "",
        f"- Parsed Markdown: `{markdown_rel}`",
        f"- Updated reference: `{output_rel}`",
        f"- Parsed fields: {parsed_count}",
        "",
    ]
    if warnings:
        lines.extend(["## Warnings", ""])
        for warning in warnings:
            lines.append(f"- {warning}")
    else:
        lines.append("No parser warnings were detected.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_source_truth(
    run_dir: Path,
    source_md: Path,
    *,
    approval_status: str = "pending_review",
    approved_by: str | None = None,
    reference_path: Path | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Parse the current Markdown and update approval metadata atomically."""
    run_dir = run_dir.expanduser().resolve()
    source_md = source_md.expanduser().resolve()
    reference_path = reference_path or run_dir / STANDARD_REFERENCE
    output_path = output_path or reference_path
    report_path = run_dir / STANDARD_REPORT

    original = load_json(reference_path)
    rows, warnings = extract_rows(source_md)
    rows, header_warnings = reconcile_study_header(original, rows, extract_study_header(source_md))
    warnings.extend(header_warnings)
    reference, apply_warnings = apply_rows(original, rows)
    warnings.extend(apply_warnings)

    source = reference.get("source")
    if not isinstance(source, dict):
        source = {}
    rel_source = display_path(source_md, run_dir)
    source["source_of_truth_file"] = rel_source
    source["source_of_truth_md"] = rel_source
    source["source_of_truth_status"] = "uploaded_reviewed"
    source["source_of_truth_parsed_at"] = datetime.now(timezone.utc).isoformat()
    reference["source"] = source

    approval = reference.get("approval")
    if not isinstance(approval, dict):
        approval = {}
    approval["status"] = approval_status
    approval["review_file"] = rel_source
    if approval_status == "approved":
        approval["approved_by"] = approved_by or approval.get("approved_by") or "reviewer"
        approval["approved_at"] = datetime.now(timezone.utc).isoformat()
    else:
        approval["approved_by"] = None
        approval["approved_at"] = None
    reference["approval"] = approval

    output_path.write_text(json.dumps(reference, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_report(report_path, len(rows), warnings, rel_source, display_path(output_path, run_dir))
    return {
        "updated": display_path(output_path, run_dir),
        "parsed_fields": len(rows),
        "warning_count": len(warnings),
        "warnings": warnings,
        "report": display_path(report_path, run_dir),
        "approval_status": approval_status,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, help="Run directory containing reference/study.reference.json.")
    parser.add_argument("--source-md", required=True, help="Edited source-of-truth Markdown uploaded by the reviewer.")
    parser.add_argument("--reference", help="Existing reference JSON path. Defaults to reference/study.reference.json.")
    parser.add_argument("--output-reference", help="Output reference JSON path. Defaults to reference/study.reference.json.")
    parser.add_argument("--approval-status", choices=["pending_review", "changes_requested", "approved"], default="pending_review")
    parser.add_argument("--approved-by", help="Reviewer name when approval-status is approved.")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser().resolve()
    result = parse_source_truth(
        run_dir,
        Path(args.source_md),
        approval_status=args.approval_status,
        approved_by=args.approved_by,
        reference_path=Path(args.reference).expanduser().resolve() if args.reference else None,
        output_path=Path(args.output_reference).expanduser().resolve() if args.output_reference else None,
    )
    print(json.dumps(result, indent=2))
    return 1 if result["warnings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
