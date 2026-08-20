#!/usr/bin/env python3
"""Create a local clinical document generation run directory."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from icf_template_selection import (
    INTERNAL_PROVIDED_CHOICE,
    apply_bundled_icf_template,
    resolve_icf_template_choice,
)
from source_intake import build_packet, packet_text
from study_type_branches import canonical_study_type, default_document_set


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent

STANDARD_TEMPLATE_NAMES = {
    "protocol_template": "protocol.template.docx",
    "icf_template": "icf.template.docx",
    "main_template": "main.template.docx",
    "short_template": "short.template.docx",
    "xml_template": "study.template.xml",
}

DEFAULT_TEMPLATE_SOURCES = {
    "Prospective": {
        "protocol_template": SKILL_DIR / "assets" / "client-templates" / "docx" / "prospective-protocol.template.docx",
        "xml_template": SKILL_DIR / "assets" / "client-templates" / "prs" / "clinicaltrials_prs_full_placeholder_template.xml",
    },
    "Ambispective": {
        "protocol_template": SKILL_DIR / "assets" / "client-templates" / "docx" / "ambispective-protocol.template.docx",
        "xml_template": SKILL_DIR / "assets" / "client-templates" / "prs" / "clinicaltrials_prs_full_placeholder_template.xml",
    },
    "Retrospective": {
        "protocol_template": SKILL_DIR / "assets" / "client-templates" / "docx" / "retrospective-protocol.template.docx",
    },
}


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or datetime.now(timezone.utc).strftime("run-%Y%m%d-%H%M%S")


def copy_if_present(src: str | None, dest: Path) -> str | None:
    if not src:
        return None
    source = Path(src).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)
    return str(dest)


def copy_template(src: Path, dest: Path) -> str:
    if not src.exists():
        raise FileNotFoundError(src)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return str(dest)


def display_path(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.name


def skeleton_reference(created_at: str, study_type: str | None = None, icf_template: str | None = None) -> dict:
    canonical = canonical_study_type(study_type)
    return {
        "meta": {
            "created_at": created_at,
            "protocol_number": None,
            "version": None,
            "date": None,
            "study_type": canonical,
            "document_set": default_document_set(canonical),
            "icf_template": icf_template,
        },
        "source": {
            "channel": None,
            "raw_files": ["input/raw_context.md"],
            "transcript_files": [],
            "notes": None,
            "field_candidates": {},
            "source_of_truth_file": None,
            "source_of_truth_md": None,
            "source_of_truth_status": None,
        },
        "template_fields": {},
        "approval": {
            "status": "pending_review",
            "review_file": None,
            "approved_by": None,
            "approved_at": None,
            "notes": None,
        },
        "study": {
            "title": None,
            "short_title": None,
            "condition": None,
            "background": None,
            "unmet_need": None,
            "hypothesis": None,
            "timeline": None,
        },
        "parties": {},
        "sites": [],
        "population": {},
        "design": {},
        "objectives": {},
        "endpoints": {},
        "procedures": {},
        "statistics": {},
        "risks_benefits": {},
        "generated": {
            "protocol": {},
            "icf": {},
            "short": {},
            "xml": {},
        },
        "regulatory": {
            "jurisdiction": None,
            "xml_profile": None,
        },
        "needs_review": [
            {
                "field": "study.title",
                "issue": "Create the structured reference file from the raw source material.",
            }
        ],
    }


def study_type_from_reference(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        reference = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    meta = reference.get("meta") if isinstance(reference, dict) else {}
    if not isinstance(meta, dict):
        return None
    return canonical_study_type(meta.get("study_type"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="runs", help="Directory where runs are stored.")
    parser.add_argument("--slug", help="Run folder slug. Defaults to timestamp.")
    parser.add_argument(
        "--study-type",
        choices=["prospective", "ambispective", "ambipective", "retrospective"],
        help="Study branch used to set meta.study_type and meta.document_set in a new reference.",
    )
    parser.add_argument("--raw-context", help="Path to raw context text/markdown to copy.")
    parser.add_argument(
        "--evidence",
        action="append",
        default=[],
        metavar="PATH",
        help="An Evidence File in the Source Intake Packet. Repeat for every file the client sent.",
    )
    parser.add_argument("--reference", help="Existing study.reference.json to copy.")
    parser.add_argument("--protocol-template", help="DOCX template for the protocol document.")
    parser.add_argument("--icf-template", help="DOCX template for the informed consent form.")
    parser.add_argument(
        "--icf-template-choice",
        choices=["advarra", "sterling"],
        help="Bundled ICF template choice. Required before source-of-truth for Prospective/Ambispective runs unless detected from input.",
    )
    parser.add_argument("--main-template", help="DOCX template for the main document.")
    parser.add_argument("--short-template", help="DOCX template for the short document.")
    parser.add_argument("--xml-template", help="XML template for the study XML.")
    parser.add_argument(
        "--no-default-templates",
        action="store_true",
        help="Do not copy bundled client templates when branch templates are omitted.",
    )
    parser.add_argument("--allow-existing", action="store_true", help="Allow an existing run directory.")
    args = parser.parse_args()

    created_at = datetime.now(timezone.utc).isoformat()
    slug = slugify(args.slug or datetime.now(timezone.utc).strftime("run-%Y%m%d-%H%M%S"))
    run_dir = Path(args.root).expanduser().resolve() / slug

    if run_dir.exists() and not args.allow_existing:
        raise FileExistsError(f"Run directory already exists: {run_dir}")

    for rel in [
        "input/attachments",
        "reference",
        "templates",
        "output",
        "logs",
    ]:
        (run_dir / rel).mkdir(parents=True, exist_ok=True)

    raw_dest = run_dir / "input" / "raw_context.md"
    if args.raw_context:
        copy_if_present(args.raw_context, raw_dest)
    elif not raw_dest.exists():
        raw_dest.write_text("", encoding="utf-8")

    # One Markdown file is simply the smallest Source Intake Packet, so both
    # entry points build the same manifest.
    evidence_paths = [args.raw_context] if args.raw_context else []
    evidence_paths.extend(args.evidence)
    packet = build_packet(run_dir, evidence_paths) if evidence_paths else None

    reference_dest = run_dir / "reference" / "study.reference.json"
    if args.reference:
        copy_if_present(args.reference, reference_dest)
    elif not reference_dest.exists():
        reference_dest.write_text(
            json.dumps(skeleton_reference(created_at, args.study_type), indent=2) + "\n",
            encoding="utf-8",
        )

    canonical = canonical_study_type(args.study_type) or study_type_from_reference(reference_dest)
    copied_templates = {}
    for attr, dest_name in STANDARD_TEMPLATE_NAMES.items():
        copied = copy_if_present(getattr(args, attr), run_dir / "templates" / dest_name)
        if copied:
            copied_templates[attr] = {"path": f"templates/{dest_name}", "source": "provided"}

    if canonical and not args.no_default_templates:
        for attr, source in DEFAULT_TEMPLATE_SOURCES.get(canonical, {}).items():
            if getattr(args, attr):
                continue
            if attr in copied_templates:
                continue
            dest_name = STANDARD_TEMPLATE_NAMES[attr]
            copy_template(source, run_dir / "templates" / dest_name)
            copied_templates[attr] = {
                "path": f"templates/{dest_name}",
                "source": "bundled_client_template",
            }

    reference = json.loads(reference_dest.read_text(encoding="utf-8"))
    raw_text = packet_text(run_dir) or raw_dest.read_text(encoding="utf-8", errors="replace")
    if args.icf_template:
        meta = reference.get("meta") if isinstance(reference.get("meta"), dict) else {}
        meta["icf_template"] = INTERNAL_PROVIDED_CHOICE
        reference["meta"] = meta
        if "icf_template" in copied_templates:
            copied_templates["icf_template"]["selection"] = INTERNAL_PROVIDED_CHOICE
    elif canonical in {"Prospective", "Ambispective"} and not args.no_default_templates:
        selection = resolve_icf_template_choice(
            reference,
            raw_text=raw_text,
            requested_choice=args.icf_template_choice,
        )
        if selection.get("choice"):
            destination = apply_bundled_icf_template(run_dir, reference, selection["choice"])
            copied_templates["icf_template"] = {
                "path": display_path(destination, run_dir),
                "source": "bundled_client_template",
                "selection": selection["choice"],
            }
    reference_dest.write_text(json.dumps(reference, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    sources = [
        {
            "type": "raw_context",
            "path": "input/raw_context.md",
            "provided": bool(args.raw_context),
        }
    ]
    if packet:
        sources.extend(
            {
                "type": "evidence_file",
                "path": item["path"],
                "filename": item["filename"],
                "media_type": item["media_type"],
                "status": item["status"],
            }
            for item in packet["evidence"]
        )
    manifest = {
        "created_at": created_at,
        "run_dir": ".",
        "source_intake_packet": "input/source-intake-manifest.json" if packet else None,
        "evidence_counts": packet["counts"] if packet else None,
        "sources": sources,
        "templates": copied_templates,
    }
    (run_dir / "input" / "source_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )

    print(display_path(run_dir, Path.cwd()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
