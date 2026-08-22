"""Metadata for the embedded client Protocol reference.

The reference is an internal layout authority. It is never copied into a
client output directory and its study-specific values are never used as
generation inputs.
"""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
EMBEDDED_PROTOCOL_REFERENCE = SKILL_DIR / "assets" / "client-templates" / "reference" / "protocol-reference.docx"
EMBEDDED_PROTOCOL_REFERENCE_RELATIVE = "assets/client-templates/reference/protocol-reference.docx"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def embedded_protocol_reference() -> dict[str, Any]:
    """Return auditable, stable metadata for the bundled client example."""
    if not EMBEDDED_PROTOCOL_REFERENCE.is_file():
        raise FileNotFoundError(EMBEDDED_PROTOCOL_REFERENCE)
    with zipfile.ZipFile(EMBEDDED_PROTOCOL_REFERENCE) as archive:
        if archive.testzip() is not None:
            raise ValueError("Embedded client Protocol reference is a corrupt DOCX package.")
        required = {"[Content_Types].xml", "word/document.xml", "word/header1.xml"}
        missing = sorted(required - set(archive.namelist()))
        if missing:
            raise ValueError("Embedded client Protocol reference is missing DOCX parts: " + ", ".join(missing))
    return {
        "path": EMBEDDED_PROTOCOL_REFERENCE_RELATIVE,
        "source": "embedded_client_reference",
        "sha256": _sha256(EMBEDDED_PROTOCOL_REFERENCE),
        "package_size_bytes": EMBEDDED_PROTOCOL_REFERENCE.stat().st_size,
        "page_system": {
            "page_size": "Letter",
            "orientation": "portrait",
            "margins_inches": {"left": 1.25, "right": 1.25, "top": 1.0, "bottom": 1.0},
            "section_count": 1,
            "source_rendered_page_count": 19,
        },
        "layout_contract": [
            "title_page",
            "investigator_agreement",
            "general_information",
            "static_table_of_contents",
            "study_sections",
            "visit_schedule",
            "safety_and_adverse_events",
            "study_related_injuries",
            "study_endpoint_criteria",
            "summary_of_risks_and_benefits",
        ],
        "known_presentation_defects": [
            "manually maintained TOC values",
            "inconsistent heading constructs",
            "source-specific clinical values",
        ],
    }


def add_reference_to_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    updated = dict(manifest)
    references = dict(updated.get("references") or {})
    references["protocol"] = embedded_protocol_reference()
    updated["references"] = references
    return updated
