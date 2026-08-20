#!/usr/bin/env python3
"""Package the skill, but only behind passing branch smoke evidence.

A package is refused unless every supported branch generated its complete
default document set and passed every applicable Delivery Gate. The evidence
that authorised the release travels inside the archive.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
from typing import Callable

from run_branch_smoke import run_smoke


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent

#: Everything Hermes needs to run the skill. `SKILL.md` alone is not a skill.
PACKAGED_FILES = ("SKILL.md", "README.md")
PACKAGED_DIRECTORIES = ("agents", "assets", "references", "scripts")
EVIDENCE_MEMBER = "smoke-evidence.json"

EXCLUDED_SUFFIXES = {".pyc", ".bak", ".tmp"}
EXCLUDED_DIRECTORY_NAMES = {"__pycache__"}


class PackagingRefused(RuntimeError):
    """Raised when smoke evidence does not authorise a release."""


def refusal_message(evidence: dict) -> str:
    parts = []
    if evidence.get("missing_branches"):
        parts.append("no smoke result for " + ", ".join(evidence["missing_branches"]))
    if evidence.get("failed_branches"):
        parts.append("failed Delivery Gates for " + ", ".join(evidence["failed_branches"]))
    detail = "; ".join(parts) or "the smoke run did not report package eligibility"
    return f"Refusing to package the skill: {detail}."


def packaged_members(skill_dir: Path) -> list[tuple[Path, str]]:
    """Every file that belongs in the archive, with its archive name."""
    members: list[tuple[Path, str]] = []
    for name in PACKAGED_FILES:
        path = skill_dir / name
        if path.is_file():
            members.append((path, name))
    for directory in PACKAGED_DIRECTORIES:
        root = skill_dir / directory
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix in EXCLUDED_SUFFIXES:
                continue
            if EXCLUDED_DIRECTORY_NAMES & set(path.relative_to(skill_dir).parts):
                continue
            members.append((path, path.relative_to(skill_dir).as_posix()))
    return members


def package_skill(
    archive_path: Path,
    *,
    skill_dir: Path = SKILL_DIR,
    smoke_root: Path | None = None,
    evidence: dict | None = None,
    fixtures: dict[str, dict] | None = None,
    renderer_available: bool | None = None,
    exporter: Callable[[Path, Path], dict] | None = None,
    toc_auditor: Callable[[Path, Path], dict] | None = None,
) -> dict:
    """Build the skill archive when branch smoke evidence authorises it."""
    archive_path = Path(archive_path)
    if evidence is None:
        if smoke_root is None:
            raise ValueError("Packaging needs either smoke evidence or a smoke root.")
        evidence = run_smoke(
            Path(smoke_root),
            fixtures=fixtures,
            renderer_available=renderer_available,
            exporter=exporter,
            toc_auditor=toc_auditor,
        )

    if not evidence.get("package_eligible"):
        raise PackagingRefused(refusal_message(evidence))

    members = packaged_members(Path(skill_dir))
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, name in members:
            archive.write(path, name)
        archive.writestr(
            EVIDENCE_MEMBER, json.dumps(evidence, indent=2, ensure_ascii=False) + "\n"
        )

    return {
        "archive": str(archive_path),
        "member_count": len(members) + 1,
        "package_eligible": True,
        "smoke": evidence,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="Archive path to write.")
    parser.add_argument(
        "--smoke-root",
        required=True,
        help="Directory that receives the branch smoke runs and their evidence.",
    )
    parser.add_argument(
        "--no-renderer",
        action="store_true",
        help=(
            "Skip renderer-backed PDF and static-TOC QA while smoking. Every "
            "other Delivery Gate still runs. Use this when no renderer should "
            "be launched."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = package_skill(
            Path(args.output).expanduser().resolve(),
            smoke_root=Path(args.smoke_root).expanduser().resolve(),
            renderer_available=False if args.no_renderer else None,
        )
    except PackagingRefused as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps({k: v for k, v in result.items() if k != "smoke"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
