#!/usr/bin/env python3
"""Preserve a client submission as one auditable Source Intake Packet.

A Source Intake Packet is the unit of client input. It holds one or more
Evidence Files, whatever form the client had them in, and is represented by a
manifest that records identity, order, media type, processing status, and any
extraction error.

This module is deliberately deterministic: it preserves evidence, extracts text
where it can, and reports what it could not read. Interpreting that text into
study facts is the model-owned Extraction Pass and does not belong here.
"""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from pdf_text import extract_pdf_pages
from render_templates import visible_text_from_word_xml


EVIDENCE_DIR = "input/evidence"
STANDARD_MANIFEST = "input/source-intake-manifest.json"

DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)

#: Extensions this skill can turn into text, with their reported media type.
SUPPORTED_MEDIA_TYPES = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".text": "text/plain",
    ".json": "application/json",
    ".csv": "text/csv",
    ".pdf": "application/pdf",
    ".docx": DOCX_MEDIA_TYPE,
}

STATUS_ACCEPTED = "accepted"
STATUS_UNSUPPORTED = "unsupported"
STATUS_UNREADABLE = "unreadable"


def slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return slug or "evidence"


def media_type_for(path: Path) -> str | None:
    return SUPPORTED_MEDIA_TYPES.get(path.suffix.lower())


def _text_from_plain(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _text_from_pdf(path: Path) -> str:
    return "\n".join(extract_pdf_pages(path))


def _text_from_docx(path: Path) -> str:
    pieces: list[str] = []
    with zipfile.ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            if not name.startswith("word/") or not name.endswith(".xml"):
                continue
            pieces.append(
                visible_text_from_word_xml(archive.read(name).decode("utf-8", errors="ignore"))
            )
    return "\n".join(pieces)


EXTRACTORS: dict[str, Callable[[Path], str]] = {
    ".md": _text_from_plain,
    ".markdown": _text_from_plain,
    ".txt": _text_from_plain,
    ".text": _text_from_plain,
    ".json": _text_from_plain,
    ".csv": _text_from_plain,
    ".pdf": _text_from_pdf,
    ".docx": _text_from_docx,
}


def _extract_text(path: Path) -> str:
    return EXTRACTORS[path.suffix.lower()](path)


def read_manifest(run_dir: Path) -> dict:
    path = Path(run_dir) / STANDARD_MANIFEST
    if not path.exists():
        return {"created_at": None, "run_dir": ".", "evidence": [], "counts": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def evidence_entries(run_dir: Path) -> list[dict]:
    return read_manifest(run_dir).get("evidence") or []


def packet_text(run_dir: Path, *, separator: str = "\n\n") -> str:
    """Every readable Evidence File as one text corpus, in submission order.

    Template selection and any other source inspection reads this rather than a
    single raw-context file, so a fact stated only in the third attachment is
    still seen.
    """
    run_dir = Path(run_dir)
    pieces: list[str] = []
    for item in evidence_entries(run_dir):
        text_rel = item.get("text_path")
        if item.get("status") != STATUS_ACCEPTED or not text_rel:
            continue
        text_path = run_dir / text_rel
        if text_path.exists():
            pieces.append(text_path.read_text(encoding="utf-8", errors="replace"))
    return separator.join(pieces)


def build_packet(
    run_dir: Path,
    evidence_paths: list[Path] | list[str],
    *,
    channel: str | None = None,
) -> dict:
    """Copy every Evidence File into the run and write the packet manifest.

    Unsupported and unreadable evidence is preserved and reported rather than
    dropped: a reviewer must be able to see that a file arrived and why the
    workflow could not read it.
    """
    run_dir = Path(run_dir)
    evidence_root = run_dir / EVIDENCE_DIR
    evidence_root.mkdir(parents=True, exist_ok=True)
    (run_dir / "input" / "extracted").mkdir(parents=True, exist_ok=True)

    entries: list[dict] = []
    for order, raw_path in enumerate(evidence_paths, start=1):
        source = Path(raw_path).expanduser()
        identity = f"{order:03d}-{slugify(source.name)}"
        stored = evidence_root / identity
        stored.write_bytes(source.read_bytes())

        entry: dict[str, Any] = {
            "id": identity,
            "order": order,
            "filename": source.name,
            "path": f"{EVIDENCE_DIR}/{identity}",
            "provenance": str(source),
            "media_type": media_type_for(source) or "application/octet-stream",
            "bytes": stored.stat().st_size,
            "status": STATUS_ACCEPTED,
            "error": "",
            "text_path": None,
        }

        if media_type_for(source) is None:
            entry["status"] = STATUS_UNSUPPORTED
            entry["error"] = (
                f"{source.name}: `{source.suffix or 'no extension'}` is not a supported "
                "Evidence File type, so no text was extracted from it."
            )
            entries.append(entry)
            continue

        try:
            text = _extract_text(stored)
        except Exception as exc:  # noqa: BLE001 - every failure names its file
            entry["status"] = STATUS_UNREADABLE
            entry["error"] = f"{source.name}: could not extract text ({exc.__class__.__name__}: {exc})."
            entries.append(entry)
            continue

        text_rel = f"input/extracted/{identity}.txt"
        (run_dir / text_rel).write_text(text, encoding="utf-8")
        entry["text_path"] = text_rel
        entry["characters"] = len(text)
        entries.append(entry)

    counts = {
        STATUS_ACCEPTED: sum(1 for item in entries if item["status"] == STATUS_ACCEPTED),
        STATUS_UNSUPPORTED: sum(1 for item in entries if item["status"] == STATUS_UNSUPPORTED),
        STATUS_UNREADABLE: sum(1 for item in entries if item["status"] == STATUS_UNREADABLE),
        "total": len(entries),
    }
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run_dir": ".",
        "channel": channel,
        "evidence": entries,
        "counts": counts,
    }
    manifest_path = run_dir / STANDARD_MANIFEST
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest


def unreadable_report(run_dir: Path) -> list[dict]:
    """Evidence the workflow accepted but could not read, for the reviewer."""
    return [
        {"filename": item["filename"], "status": item["status"], "error": item["error"]}
        for item in evidence_entries(run_dir)
        if item.get("status") != STATUS_ACCEPTED
    ]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, help="Run directory receiving the packet.")
    parser.add_argument(
        "--evidence",
        action="append",
        default=[],
        metavar="PATH",
        help="An Evidence File. Repeat for every file in the Source Intake Packet.",
    )
    parser.add_argument("--channel", help="How the packet arrived, for the manifest.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    manifest = build_packet(
        Path(args.run_dir).expanduser().resolve(), args.evidence, channel=args.channel
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0 if manifest["counts"]["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
