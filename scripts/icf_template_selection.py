#!/usr/bin/env python3
"""Resolve and apply the ICF template selected for a clinical study run."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from study_type_branches import canonical_study_type


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
STANDARD_REFERENCE = "reference/study.reference.json"
STANDARD_TEMPLATE = "templates/icf.template.docx"
STANDARD_MANIFEST = "input/source_manifest.json"

ICF_STUDY_TYPES = {"Prospective", "Ambispective"}
PUBLIC_CHOICES = ("Advarra", "Sterling")
INTERNAL_PROVIDED_CHOICE = "Provided"

BUNDLED_ICF_TEMPLATES = {
    "Prospective": {
        "Advarra": SKILL_DIR / "assets" / "client-templates" / "docx" / "prospective-icf.template.docx",
        "Sterling": SKILL_DIR / "assets" / "client-templates" / "docx" / "sterling-icf.template.docx",
    },
    "Ambispective": {
        "Advarra": SKILL_DIR / "assets" / "client-templates" / "docx" / "ambispective-icf.template.docx",
        "Sterling": SKILL_DIR / "assets" / "client-templates" / "docx" / "sterling-icf.template.docx",
    },
}

CHOICE_PATTERNS = {
    "Advarra": re.compile(r"\badvarra\b", re.IGNORECASE),
    "Sterling": re.compile(r"\bsterling\b", re.IGNORECASE),
}


def normalize_icf_template_choice(value: Any, allow_provided: bool = True) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).strip().lower().replace("-", " ").split())
    aliases = {
        "advarra": "Advarra",
        "advarra irb": "Advarra",
        "sterling": "Sterling",
        "sterling irb": "Sterling",
        "sterling institutional review board": "Sterling",
    }
    if allow_provided:
        aliases.update({"provided": INTERNAL_PROVIDED_CHOICE, "custom": INTERNAL_PROVIDED_CHOICE})
    return aliases.get(normalized)


def study_requires_icf_selection(reference: dict) -> bool:
    meta = reference.get("meta") if isinstance(reference.get("meta"), dict) else {}
    return canonical_study_type(meta.get("study_type")) in ICF_STUDY_TYPES


def irb_name(reference: dict) -> str:
    parties = reference.get("parties") if isinstance(reference.get("parties"), dict) else {}
    for key in ("irb", "ethics_committee"):
        party = parties.get(key)
        if isinstance(party, dict) and str(party.get("name") or "").strip():
            return str(party["name"]).strip()
    return ""


def mentioned_choices(*values: Any) -> list[str]:
    text = "\n".join(str(value) for value in values if value is not None)
    return [choice for choice, pattern in CHOICE_PATTERNS.items() if pattern.search(text)]


def selection_issue(reference: dict, reason: str = "missing") -> str:
    name = irb_name(reference)
    if reason == "ambiguous":
        return (
            "Both Advarra and Sterling are mentioned. Ask the reviewer which ICF template to use "
            "before creating the source-of-truth file."
        )
    if reason == "invalid":
        return (
            "The recorded ICF template is not supported. Only Advarra and Sterling are available; "
            "ask the reviewer which one to use before creating the source-of-truth file."
        )
    if name:
        return (
            f"The study names `{name}`, but only the Advarra and Sterling ICF templates are available. "
            "Ask the reviewer whether to use Advarra or Sterling before creating the source-of-truth file."
        )
    return (
        "No ICF template was specified. Ask the reviewer whether to use the Advarra or Sterling template "
        "before creating the source-of-truth file."
    )


def resolve_icf_template_choice(
    reference: dict,
    raw_text: str = "",
    requested_choice: Any = None,
) -> dict:
    if not study_requires_icf_selection(reference):
        return {"required": False, "choice": None, "reason": "not_applicable", "issue": None}

    if requested_choice is not None:
        choice = normalize_icf_template_choice(requested_choice, allow_provided=False)
        if choice:
            return {"required": True, "choice": choice, "reason": "requested", "issue": None}
        return {"required": True, "choice": None, "reason": "invalid", "issue": selection_issue(reference, "invalid")}

    meta = reference.get("meta") if isinstance(reference.get("meta"), dict) else {}
    recorded = meta.get("icf_template")
    if recorded is not None and str(recorded).strip():
        choice = normalize_icf_template_choice(recorded)
        if choice:
            return {"required": True, "choice": choice, "reason": "recorded", "issue": None}
        return {"required": True, "choice": None, "reason": "invalid", "issue": selection_issue(reference, "invalid")}

    mentions = mentioned_choices(raw_text, irb_name(reference))
    if len(mentions) == 1:
        return {"required": True, "choice": mentions[0], "reason": "detected", "issue": None}
    if len(mentions) > 1:
        return {
            "required": True,
            "choice": None,
            "reason": "ambiguous",
            "issue": selection_issue(reference, "ambiguous"),
        }
    return {"required": True, "choice": None, "reason": "missing", "issue": selection_issue(reference)}


def bundled_icf_template(study_type: Any, choice: Any) -> Path:
    canonical = canonical_study_type(study_type)
    normalized = normalize_icf_template_choice(choice, allow_provided=False)
    if canonical not in ICF_STUDY_TYPES or normalized not in PUBLIC_CHOICES:
        raise ValueError(f"Unsupported ICF template selection: study_type={study_type!r}, choice={choice!r}")
    return BUNDLED_ICF_TEMPLATES[canonical][normalized]


def update_manifest(run_dir: Path, choice: str, source_path: Path) -> None:
    manifest_path = run_dir / STANDARD_MANIFEST
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {}
    else:
        manifest = {}
    templates = manifest.get("templates") if isinstance(manifest.get("templates"), dict) else {}
    templates["icf_template"] = {
        "path": STANDARD_TEMPLATE,
        "source": "bundled_client_template",
        "selection": choice,
        "asset": source_path.name,
    }
    manifest["templates"] = templates
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def apply_bundled_icf_template(run_dir: Path, reference: dict, choice: str) -> Path:
    meta = reference.get("meta") if isinstance(reference.get("meta"), dict) else {}
    canonical = canonical_study_type(meta.get("study_type"))
    source = bundled_icf_template(canonical, choice)
    if not source.exists():
        raise FileNotFoundError(source)
    destination = run_dir / STANDARD_TEMPLATE
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    meta["icf_template"] = normalize_icf_template_choice(choice, allow_provided=False)
    reference["meta"] = meta
    update_manifest(run_dir, meta["icf_template"], source)
    return destination


def ensure_run_icf_template(run_dir: Path, reference: dict, requested_choice: Any = None) -> dict:
    raw_path = run_dir / "input" / "raw_context.md"
    raw_text = raw_path.read_text(encoding="utf-8", errors="replace") if raw_path.exists() else ""
    result = resolve_icf_template_choice(reference, raw_text=raw_text, requested_choice=requested_choice)
    choice = result.get("choice")
    if not result["required"] or not choice:
        return result
    if choice == INTERNAL_PROVIDED_CHOICE:
        destination = run_dir / STANDARD_TEMPLATE
        if not destination.exists():
            return {
                "required": True,
                "choice": None,
                "reason": "provided_missing",
                "issue": "The recorded provided ICF template is missing from `templates/icf.template.docx`.",
            }
        return result
    destination = apply_bundled_icf_template(run_dir, reference, choice)
    result["template"] = destination.as_posix()
    return result
