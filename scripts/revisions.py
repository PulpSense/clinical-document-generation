"""Immutable approved-source revisions and change-boundary helpers."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REVISION_ROOT = "revisions"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def current_source_path(run_dir: Path, reference: dict[str, Any]) -> Path | None:
    source = reference.get("source") if isinstance(reference.get("source"), dict) else {}
    value = source.get("source_of_truth_file") or source.get("source_of_truth_md")
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else run_dir / path


def source_change(reference: dict[str, Any], run_dir: Path) -> dict[str, Any] | None:
    """Return a finding when the approved Markdown no longer matches approval."""
    approval = reference.get("approval") if isinstance(reference.get("approval"), dict) else {}
    approved_hash = approval.get("approved_source_sha256") or (
        reference.get("source", {}).get("approved_source_sha256")
        if isinstance(reference.get("source"), dict)
        else None
    )
    source_path = current_source_path(run_dir, reference)
    if not approved_hash or source_path is None:
        return None
    actual_hash = sha256_file(source_path) if source_path.is_file() else None
    if actual_hash == approved_hash:
        return None
    return {
        "field": "approval.approved_source_sha256",
        "issue": "The approved Source-of-Truth Markdown changed after approval; approval and generated material are invalid.",
        "evidence_required": "A newly reviewed and explicitly approved Source-of-Truth Markdown revision.",
        "severity": "blocking",
        "approved_sha256": approved_hash,
        "actual_sha256": actual_hash,
    }


def invalidate_changed_source(run_dir: Path, reference: dict[str, Any]) -> dict[str, Any] | None:
    """Record invalidation without deleting prior evidence or revisions."""
    finding = source_change(reference, run_dir)
    if finding is None:
        return None
    now = datetime.now(timezone.utc).isoformat()
    affected_material = _affected_material(run_dir)
    state = {
        "status": "invalidated",
        "reason": "approved_source_changed",
        "invalidated_at": now,
        "finding": finding,
        "affected_material": affected_material,
        "invalidated_material": [
            {"path": path, "status": "invalidated"}
            for path in affected_material
        ],
    }
    _write_json(run_dir / "state/source-invalidation.json", state)
    _write_json(run_dir / "state/client-facing-revision.json", {
        "status": "invalidated",
        "reason": "approved_source_changed",
        "invalidated_at": now,
        "client_outputs": [],
    })
    updated = dict(reference)
    approval = dict(updated.get("approval") or {})
    approval.update({"status": "changes_requested", "invalidated_at": now, "invalidated_reason": "approved_source_changed"})
    updated["approval"] = approval
    state_ref = run_dir / "reference/study.reference.json"
    _write_json(state_ref, updated)
    return finding


def _affected_material(run_dir: Path) -> list[str]:
    """List preserved material that must not be treated as current output."""
    paths: list[str] = []
    for root in ("drafts", "evidence", "output", "logs"):
        directory = run_dir / root
        if directory.is_dir():
            paths.extend(path.relative_to(run_dir).as_posix() for path in directory.rglob("*") if path.is_file())
    return sorted(paths)


def create_revision(run_dir: Path, reference_path: Path, source_path: Path) -> dict[str, Any]:
    """Snapshot one approved source and its generation-manifest foundation."""
    root = run_dir / REVISION_ROOT
    numbers = [int(path.name) for path in root.iterdir() if path.is_dir() and path.name.isdigit()] if root.is_dir() else []
    revision_id = f"{max(numbers, default=0) + 1:04d}"
    revision_dir = root / revision_id
    revision_dir.mkdir(parents=True)
    source_hash = sha256_file(source_path)
    reference_hash = sha256_file(reference_path)
    revision_source = revision_dir / "source-of-truth.md"
    revision_reference = revision_dir / "study.reference.json"
    revision_source.write_bytes(source_path.read_bytes())
    revision_reference.write_bytes(reference_path.read_bytes())
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    manifest = {
        "manifest_version": "2026-08-22",
        "revision_id": revision_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "approved",
        "study_type": (reference.get("meta") or {}).get("study_type"),
        "approved_source": {"path": "source-of-truth.md", "sha256": source_hash},
        "reference": {"path": "study.reference.json", "sha256": reference_hash},
        "contracts": {"source_contract": "quality_contract", "branch_contract": "study_type_branches"},
        "generation": {"drafts": [], "evidence": [], "artifacts": []},
    }
    _write_json(revision_dir / "generation-manifest.json", manifest)
    return {"revision_id": revision_id, "path": revision_dir.relative_to(run_dir).as_posix(), "source_sha256": source_hash, "manifest": manifest}


def publish_revision(run_dir: Path, revision_id: str, outputs: list[str]) -> dict[str, Any]:
    """Point the run's client-facing filter at the newest passing revision."""
    release = {
        "status": "passed",
        "revision_id": revision_id,
        "client_outputs": list(outputs),
        "published_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(run_dir / "state/client-facing-revision.json", release)
    return release


__all__ = ["create_revision", "invalidate_changed_source", "publish_revision", "source_change", "sha256_file"]
