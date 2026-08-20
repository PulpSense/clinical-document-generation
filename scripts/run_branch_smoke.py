#!/usr/bin/env python3
"""Run the deterministic branch smoke fixtures and record their evidence.

One invocation generates the complete default document set for every supported
study branch from an approved structured study reference, runs every applicable
Delivery Gate, and reports whether the skill is eligible for packaging.

The evidence is written next to the runs so a released skill version can be
audited afterwards: which branch, which active outputs, which artifacts, which
gate outcomes, and which QA limitations applied.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from generate_branch_documents import generate_branch
from smoke_fixtures import build_run, write_reference


STANDARD_EVIDENCE = "skill-smoke.json"

#: Every branch a released skill must prove, in reporting order.
SMOKE_BRANCHES = ("Prospective", "Ambispective", "Retrospective")


def smoke_branch(
    root: Path,
    branch: str,
    *,
    reference: dict | None = None,
    renderer_available: bool | None = None,
    exporter: Callable[[Path, Path], dict] | None = None,
    refresher: Callable[[Path, Path], dict] | None = None,
    toc_auditor: Callable[[Path, Path], dict] | None = None,
) -> dict:
    """Generate and gate one branch, returning its smoke record."""
    run_dir = root / branch.lower()
    run_dir.mkdir(parents=True, exist_ok=True)
    build_run(run_dir, branch)
    if reference is not None:
        write_reference(run_dir, reference)

    result = generate_branch(
        run_dir,
        renderer_available=renderer_available,
        exporter=exporter,
        refresher=refresher,
        toc_auditor=toc_auditor,
    )
    return {
        "branch": result["branch"],
        "run_dir": run_dir.name,
        "document_set": result["document_set"],
        "artifacts": result["artifacts"],
        "gates": result["gates"],
        "qa": result["qa"],
        "delivery_ready": result["delivery_ready"],
        "repair_report": result["repair_report"],
    }


def run_smoke(
    root: Path,
    *,
    branches: tuple[str, ...] = SMOKE_BRANCHES,
    fixtures: dict[str, dict] | None = None,
    renderer_available: bool | None = None,
    exporter: Callable[[Path, Path], dict] | None = None,
    refresher: Callable[[Path, Path], dict] | None = None,
    toc_auditor: Callable[[Path, Path], dict] | None = None,
) -> dict:
    """Smoke every supported branch and decide package eligibility."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    fixtures = fixtures or {}

    records = [
        smoke_branch(
            root,
            branch,
            reference=fixtures.get(branch),
            renderer_available=renderer_available,
            exporter=exporter,
            refresher=refresher,
            toc_auditor=toc_auditor,
        )
        for branch in branches
    ]

    covered = {record["branch"] for record in records}
    missing = [branch for branch in SMOKE_BRANCHES if branch not in covered]
    failed = [record["branch"] for record in records if not record["delivery_ready"]]

    evidence: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "branches": records,
        "missing_branches": missing,
        "failed_branches": failed,
        # A branch that was never smoked is as disqualifying as one that failed.
        "package_eligible": not missing and not failed,
    }
    (root / STANDARD_EVIDENCE).write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return evidence


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        required=True,
        help="Directory that receives the smoke runs and their evidence.",
    )
    parser.add_argument(
        "--no-renderer",
        action="store_true",
        help=(
            "Skip renderer-backed PDF and static-TOC QA. Every other Delivery "
            "Gate still runs. Use this when no renderer should be launched."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    evidence = run_smoke(
        Path(args.root).expanduser().resolve(),
        renderer_available=False if args.no_renderer else None,
    )
    print(json.dumps(evidence, indent=2, ensure_ascii=False))
    return 0 if evidence["package_eligible"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
