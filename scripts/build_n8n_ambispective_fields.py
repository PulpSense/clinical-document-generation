#!/usr/bin/env python3
"""Build n8n-compatible ambispective protocol, ICF, and XML fields.

The existing workflow's ambispective branch uses the same output schema and
placeholder catalog as the prospective branch, with node names suffixed by `1`
(`Introduction1`, `Population Variables1`, etc.). Keep this wrapper separate so
future client templates can diverge without changing the prospective command.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from build_n8n_prospective_fields import REQUIRED_AI_FIELDS, STANDARD_REFERENCE, build_fields, load_json


def display_path(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.name


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, help="Run directory containing reference/study.reference.json.")
    parser.add_argument("--reference", help="Reference JSON path. Defaults to reference/study.reference.json.")
    parser.add_argument("--check", action="store_true", help="Do not write the reference; report blank required fields.")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser().resolve()
    reference_path = Path(args.reference).expanduser().resolve() if args.reference else run_dir / STANDARD_REFERENCE
    reference = load_json(reference_path)
    fields = build_fields(reference)
    blank_required = sorted(key for key in REQUIRED_AI_FIELDS if not str(fields.get(key, "")).strip())

    if args.check:
        print(json.dumps({"branch": "Ambispective", "blank_required_fields": blank_required, "template_fields": fields}, indent=2, ensure_ascii=False))
        return 1 if blank_required else 0

    merged = reference.get("template_fields")
    if not isinstance(merged, dict):
        merged = {}
    merged.update(fields)
    reference["template_fields"] = merged
    reference_path.write_text(json.dumps(reference, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "updated": display_path(reference_path, run_dir),
                "branch": "Ambispective",
                "field_count": len(fields),
                "blank_required_fields": blank_required,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
