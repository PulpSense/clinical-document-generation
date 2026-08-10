#!/usr/bin/env python3
"""Select Advarra or Sterling for a Prospective/Ambispective run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from icf_template_selection import STANDARD_REFERENCE, ensure_run_icf_template


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, help="Clinical document generation run directory.")
    parser.add_argument("--choice", required=True, choices=["advarra", "sterling"], help="ICF template to use.")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser().resolve()
    reference_path = run_dir / STANDARD_REFERENCE
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    result = ensure_run_icf_template(run_dir, reference, requested_choice=args.choice)
    if result.get("issue"):
        print(json.dumps(result, indent=2))
        return 1
    reference_path.write_text(json.dumps(reference, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "run_dir": ".",
                "selection": result.get("choice"),
                "template": "templates/icf.template.docx",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
