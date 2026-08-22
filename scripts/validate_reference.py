#!/usr/bin/env python3
"""Validate a study reference file against templates in a run directory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scan_placeholders import scan_path
from quality_contract import repair_report_markdown as quality_repair_report_markdown
from quality_contract import validate_source_contract
from study_type_branches import (
    DOC_TEMPLATES,
    branch_for_study_type,
    content_completeness_missing,
    repair_report_markdown,
    starred_review_item_is_blocking,
    validate_branch,
)


STANDARD_TEMPLATES = list(dict.fromkeys(DOC_TEMPLATES.values()))


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def rel_to_run(path: Path, run_dir: Path) -> str:
    try:
        return path.relative_to(run_dir).as_posix()
    except ValueError:
        return path.name


def flatten(value, prefix: str = "") -> set[str]:
    paths: set[str] = set()
    if prefix:
        paths.add(prefix)
    if isinstance(value, dict):
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            paths.update(flatten(child, child_prefix))
    elif isinstance(value, list):
        if prefix:
            paths.add(prefix)
            item_prefix = f"{prefix}[]"
            paths.add(item_prefix)
            for index, child in enumerate(value):
                paths.update(flatten(child, f"{prefix}.{index}"))
                paths.update(flatten(child, item_prefix))
    return paths


def path_exists(paths: set[str], candidate: str) -> bool:
    if candidate in paths:
        return True
    # Allow array item checks such as sites[].facility.name.
    parts = candidate.split(".")
    for i in range(1, len(parts)):
        array_candidate = ".".join(parts[:i]) + "[]." + ".".join(parts[i:])
        if array_candidate in paths:
            return True
    return False


def validate_tokens(tokens: list[dict], reference: dict) -> tuple[list[dict], list[dict]]:
    paths = flatten(reference)
    template_fields = reference.get("template_fields")
    if isinstance(template_fields, dict):
        paths.update(flatten(template_fields))
    missing = []
    warnings = []
    stack: list[str] = []

    for token in tokens:
        kind = token["kind"]
        name = token["name"]
        if kind == "error":
            missing.append({"placeholder": name, "issue": token["raw"], "template": token["template"]})
            continue
        if kind in {"block_start", "inverted_block_start"}:
            if not path_exists(paths, name):
                missing.append(
                    {
                        "placeholder": token["raw"],
                        "field": name,
                        "issue": "Block path is not present in reference file.",
                        "template": token["template"],
                    }
                )
            stack.append(name)
            continue
        if kind == "block_end":
            if stack and stack[-1] == name:
                stack.pop()
            elif name in stack:
                stack.remove(name)
                warnings.append(
                    {
                        "placeholder": token["raw"],
                        "issue": "Block nesting is irregular.",
                        "template": token["template"],
                    }
                )
            else:
                missing.append(
                    {
                        "placeholder": token["raw"],
                        "field": name,
                        "issue": "Closing block has no matching opening block.",
                        "template": token["template"],
                    }
                )
            continue

        candidates = [name]
        if stack and "." not in name:
            candidates.append(f"{stack[-1]}[].{name}")
            candidates.append(f"{stack[-1]}.{name}")
        elif stack:
            candidates.append(f"{stack[-1]}[].{name}")
            candidates.append(f"{stack[-1]}.{name}")

        if stack and path_exists(paths, f"{stack[-1]}[]"):
            # Empty arrays expose the block path but not item-level fields. The
            # renderer will skip the block, so relative item placeholders are valid.
            item_candidate = f"{stack[-1]}[].{name}"
            if item_candidate in candidates and not any(path_exists(paths, candidate) for candidate in candidates):
                continue

        if not any(path_exists(paths, candidate) for candidate in candidates):
            missing.append(
                {
                    "placeholder": token["raw"],
                    "field": name,
                    "issue": "Placeholder path is not present in reference file.",
                    "template": token["template"],
                }
            )

    for unclosed in stack:
        missing.append(
            {
                "placeholder": "{#" + unclosed + "}",
                "field": unclosed,
                "issue": "Opening block was not closed.",
            }
        )

    return missing, warnings


def write_missing_fields(path: Path, missing: list[dict], warnings: list[dict], needs_review: list) -> None:
    lines = ["# Missing Fields", ""]
    if not missing and not warnings and not needs_review:
        lines.append("No missing template fields or reference review items were detected.")
    if missing:
        lines.extend(["## Missing Template Fields", ""])
        for item in missing:
            lines.append(f"- `{item.get('field') or item.get('placeholder')}`: {item['issue']}")
    if warnings:
        lines.extend(["", "## Warnings", ""])
        for item in warnings:
            lines.append(f"- `{item.get('placeholder')}`: {item['issue']}")
    if needs_review:
        lines.extend(["", "## Reference Items Needing Review", ""])
        for item in needs_review:
            field = item.get("field", "unknown")
            issue = item.get("issue", "Review required.")
            lines.append(f"- `{field}`: {issue}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_repair_report(path: Path, missing: list[dict], *, enabled: bool) -> str | None:
    if not enabled:
        path.unlink(missing_ok=True)
        return None
    if not missing:
        path.unlink(missing_ok=True)
        return None
    path.write_text(repair_report_markdown(missing), encoding="utf-8")
    return path.name


def normalized_status(reference: dict) -> str:
    approval = reference.get("approval")
    if not isinstance(approval, dict):
        return ""
    return str(approval.get("status") or "").strip().lower()


def blocking_review_items(reference: dict, needs_review: list) -> list:
    meta = reference.get("meta") if isinstance(reference.get("meta"), dict) else {}
    branch = branch_for_study_type(meta.get("study_type"))
    if not branch or not branch.get("source_required_fields"):
        return needs_review
    blocking = []
    for item in needs_review:
        if starred_review_item_is_blocking(item, branch["source_required_fields"]):
            blocking.append(item)
    return blocking


def validate_approval(reference: dict, needs_review: list) -> list[dict]:
    missing = []
    if normalized_status(reference) != "approved":
        missing.append(
            {
                "field": "approval.status",
                "issue": "Final generation requires approval.status to be 'approved'.",
            }
        )
    if needs_review:
        missing.append(
            {
                "field": "needs_review",
                "issue": "Final generation requires all branch-blocking needs_review items to be resolved.",
            }
        )
    source = reference.get("source")
    source_truth = None
    if isinstance(source, dict):
        source_truth = (
            source.get("source_of_truth_file")
            or source.get("source_of_truth_md")
        )
    if not source_truth:
        missing.append(
            {
                "field": "source.source_of_truth_file",
                "issue": "Final generation requires an approved or confirmed source-of-truth file.",
            }
        )
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, help="Run directory to validate.")
    parser.add_argument(
        "--require-approval",
        action="store_true",
        help="Fail unless approval is recorded and no branch-blocking review items remain.",
    )
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser().resolve()
    reference_path = run_dir / "reference" / "study.reference.json"
    report_path = run_dir / "logs" / "generation-report.json"
    missing_path = run_dir / "reference" / "missing_fields.md"

    reference = load_json(reference_path)
    tokens = []
    templates = []
    for rel in STANDARD_TEMPLATES:
        path = run_dir / rel
        if path.exists():
            templates.append(rel)

    branch_missing, branch_warnings, active_templates = validate_branch(reference, templates)

    scan_templates = active_templates or templates
    for rel in scan_templates:
        path = run_dir / rel
        if path.exists():
            for token in scan_path(path):
                token["template"] = rel_to_run(path, run_dir)
                tokens.append(token)

    missing, warnings = validate_tokens(tokens, reference)
    missing = branch_missing + missing
    warnings = branch_warnings + warnings
    needs_review = reference.get("needs_review") or []
    blocking_needs_review = blocking_review_items(reference, needs_review)
    content_missing = content_completeness_missing(reference) if args.require_approval else []
    quality_contract = validate_source_contract(reference, require_approval=args.require_approval, require_tables=args.require_approval)
    contract_missing = quality_contract["blocking_findings"] if args.require_approval else []
    if args.require_approval:
        missing = (
            validate_approval(reference, blocking_needs_review)
            + content_missing
            + contract_missing
            + missing
        )
    write_missing_fields(missing_path, missing, warnings, needs_review)
    repair_path = run_dir / "reference" / "repair-report.md"
    if args.require_approval and contract_missing:
        legacy_report = repair_report_markdown(missing)
        detailed_report = quality_repair_report_markdown(contract_missing)
        repair_path.write_text(legacy_report + "\n## Detailed Source Contract Findings\n\n" + detailed_report, encoding="utf-8")
        repair_report = repair_path.name
    else:
        repair_report = write_repair_report(repair_path, missing, enabled=bool(args.require_approval))

    report = {
        "run_dir": ".",
        "run_id": run_dir.name,
        "reference": rel_to_run(reference_path, run_dir),
        "templates": templates,
        "placeholder_count": len(tokens),
        "missing_count": len(missing),
        "warning_count": len(warnings),
        "needs_review_count": len(needs_review),
        "blocking_needs_review_count": len(blocking_needs_review),
        "content_completeness_missing_count": len(content_missing),
        "quality_contract": quality_contract,
        "approval_status": normalized_status(reference) or None,
        "approval_required": bool(args.require_approval),
        "repair_report": f"reference/{repair_report}" if repair_report else None,
        "missing": missing,
        "warnings": warnings,
        "needs_review": needs_review,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(report, indent=2))
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
