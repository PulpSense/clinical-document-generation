#!/usr/bin/env python3
"""Update approval metadata in study.reference.json."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


STANDARD_REFERENCE = "reference/study.reference.json"
def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, help="Run directory containing the reference file.")
    parser.add_argument(
        "--status",
        required=True,
        choices=["pending_review", "changes_requested", "approved"],
        help="Approval status to write.",
    )
    parser.add_argument("--approved-by", help="Reviewer name or identifier.")
    parser.add_argument("--notes", help="Optional approval or change-request notes.")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser().resolve()
    reference_path = run_dir / STANDARD_REFERENCE
    reference = load_json(reference_path)

    approval = reference.get("approval")
    if not isinstance(approval, dict):
        approval = {}

    approval["status"] = args.status
    source = reference.get("source")
    source_review_file = None
    if isinstance(source, dict):
        source_review_file = source.get("source_of_truth_file") or source.get("source_of_truth_md")
    if not approval.get("review_file"):
        approval["review_file"] = source_review_file
    approval["notes"] = args.notes

    if args.status == "approved":
        approval["approved_by"] = args.approved_by or approval.get("approved_by") or "reviewer"
        approval["approved_at"] = datetime.now(timezone.utc).isoformat()
    else:
        approval["approved_by"] = None
        approval["approved_at"] = None

    reference["approval"] = approval
    reference_path.write_text(json.dumps(reference, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(approval, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
