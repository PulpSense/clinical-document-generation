#!/usr/bin/env python3
"""Check whether a draft reference has enough input to create the source document."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from icf_template_selection import ensure_run_icf_template, selection_issue
from study_type_branches import (
    branch_for_study_type,
    has_meaningful_value,
    is_meaningful_value,
    starred_distinct_candidate_count,
    starred_requirement_for_field,
    starred_requirement_value,
    starred_review_item_is_blocking,
)


STANDARD_REFERENCE = "reference/study.reference.json"
STANDARD_OUTPUT = "reference/missing-inputs.md"


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def display_path(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.name


def review_item_text(item: Any) -> tuple[str, str]:
    if isinstance(item, dict):
        return str(item.get("field") or "needs_review"), str(item.get("issue") or "Review required.")
    return "needs_review", str(item)


def missing_inputs(reference: dict) -> list[dict]:
    meta = reference.get("meta") if isinstance(reference.get("meta"), dict) else {}
    study_type = meta.get("study_type")
    branch = branch_for_study_type(study_type)
    missing: list[dict] = []
    seen_fields: set[str] = set()

    def append_missing(field: str, issue: str) -> None:
        if field in seen_fields:
            return
        seen_fields.add(field)
        missing.append({"field": field, "issue": issue})

    if branch is None:
        append_missing(
            "meta.study_type",
            "Study type must be Prospective, Ambispective, or Retrospective before creating the structured source document.",
        )
        return missing

    canonical = branch["canonical_study_type"]
    if canonical in {"Prospective", "Ambispective"}:
        choice = meta.get("icf_template")
        if not choice or str(choice).strip().lower() not in {"advarra", "sterling", "provided", "custom"}:
            append_missing("meta.icf_template", selection_issue(reference, "invalid" if choice else "missing"))

    if branch.get("source_required_fields"):
        requirements = branch["source_required_fields"]

        for requirement in requirements:
            count = starred_distinct_candidate_count(reference, requirement)
            if count > 1:
                append_missing(
                    requirement["field"],
                    f"Starred {canonical.lower()} field `{requirement['label']}` has {count} distinct source inputs. Resolve the conflict before continuing.",
                )

        for item in reference.get("needs_review") or []:
            if not starred_review_item_is_blocking(item, requirements):
                continue
            field, issue = review_item_text(item)
            requirement = starred_requirement_for_field(field, requirements)
            if requirement:
                append_missing(requirement["field"], issue)

        for requirement in requirements:
            if not is_meaningful_value(starred_requirement_value(reference, requirement)):
                append_missing(
                    requirement["field"],
                    f"Missing starred {canonical.lower()} input: {requirement['label']}.",
                )
    else:
        for field in branch.get("source_required_paths", branch["required_paths"]):
            if not has_meaningful_value(reference, field):
                append_missing(
                    field,
                    f"Required client/source input for {canonical} source-of-truth review.",
                )

        for item in reference.get("needs_review") or []:
            field, issue = review_item_text(item)
            append_missing(field, issue)

    return missing


def write_report(path: Path, run_dir: Path, missing: list[dict]) -> None:
    lines = ["# Missing Inputs", ""]
    if not missing:
        lines.append("No missing required inputs were detected. The structured source document may be created.")
    else:
        lines.append(
            "Do not create the structured source document yet. Resolve the missing or conflicting client/source inputs below, update "
            "`reference/study.reference.json`, and rerun the preflight."
        )
        lines.append("")
        for item in missing:
            lines.append(f"- `{item['field']}`: {item['issue']}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, help="Run directory containing reference/study.reference.json.")
    parser.add_argument("--reference", help="Reference JSON path. Defaults to reference/study.reference.json.")
    parser.add_argument("--output", help="Report path. Defaults to reference/missing-inputs.md.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable output.")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser().resolve()
    reference_path = Path(args.reference).expanduser().resolve() if args.reference else run_dir / STANDARD_REFERENCE
    output_path = Path(args.output).expanduser().resolve() if args.output else run_dir / STANDARD_OUTPUT
    reference = load_json(reference_path)
    selection = ensure_run_icf_template(run_dir, reference)
    if selection.get("choice"):
        reference_path.write_text(json.dumps(reference, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    missing = missing_inputs(reference)
    write_report(output_path, run_dir, missing)

    result = {
        "run_dir": ".",
        "reference": display_path(reference_path, run_dir),
        "report": display_path(output_path, run_dir),
        "missing_count": len(missing),
        "missing": missing,
    }
    print(json.dumps(result, indent=2) if args.json else f"{result['report']} ({len(missing)} missing)")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
