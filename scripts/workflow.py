#!/usr/bin/env python3
"""The single public lifecycle for the clinical-document skill."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from docx import Document

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path: sys.path.insert(0, str(SCRIPT_DIR))

from contracts import BUNDLED_FONT_FILES, RECOVERY_POLICIES, ContractedTemplateBundleError, LAYOUT_REPAIR_RULES, batch_plan, canonical_study_type, contracted_template_bundle, document_set, get_path, icf_contract, parse_source_truth, protocol_contract, recovery_finding, repair_report, set_path, source_contract, source_truth_markdown
from drafting import MAX_ATTEMPTS, accepted_cross_section_duplicate_findings, governing_resources, ingest_responses, invalidate_accepted_targets, merged_drafts, missing_drafts, pending_requests, recorded_acceptance_response, retry_attempts, schedule_requests, sha256_file, sha256_value
from prs_xml import generate as generate_xml
from quality import _approved_packaged_font_fallback, _template_fonts, create_verification_requests, page_renderers, pending_verifications, quality_report, render_assurance, renderer, renderers, sha256_file as quality_sha256, verification_response_is_complete
from rendering import render_documents


REFERENCE = Path("reference/study.reference.json")
MAX_VERIFICATION_ATTEMPTS = 3
DESKTOP_DELIVERY_RETRIES = 2
NORMAL_RUNTIME_TARGET_MIN_SECONDS = 600.0
NORMAL_RUNTIME_TARGET_MAX_SECONDS = 720.0
DESKTOP_OPERATION_BUDGET_SECONDS = 1800.0
DESKTOP_STAGE_SOFT_BUDGETS = {
    "drafting": 480.0,
    "candidate": 120.0,
    "render_assurance": 300.0,
    "independent_verification": 240.0,
    "delivery": 60.0,
    "desktop_delivery": 60.0,
}
RELEASE_MANIFEST = "RELEASE-MANIFEST.json"
INSTALLATION_ASSURANCE = "INSTALLATION-ASSURANCE.json"
MINIMUM_PYTHON_VERSION = (3, 10)
PDF_PAGE_RENDERER = {
    "kind": "pypdfium2",
    "version": "5.13.0",
    "wheel": "assets/runtime-wheels/pypdfium2-5.13.0-py3-none-macosx_13_0_arm64.whl",
    "wheel_sha256": "da5c7b74eebf40b5c1fbe1de01aa1edc8827a79fb1efd999616bc20dcaf77ba4",
    "platform": "macosx_13_0_arm64",
}


class OperationDeadlineExpired(RuntimeError):
    """Raised before an atomic publication would cross the operation deadline."""


def _runtime_version(value: Mapping[str, Any]) -> tuple[int, int, int]:
    raw = value.get("version_info")
    if isinstance(raw, list) and len(raw) >= 2:
        parts = [int(item) for item in raw[:3]]
    else:
        parts = [int(item) for item in str(value.get("version") or "").split(".")[:3]]
    return tuple((parts + [0, 0, 0])[:3])


def _current_python_runtime() -> dict[str, Any]:
    runtime = {
        "executable": str(Path(sys.executable).resolve()),
        "implementation": platform.python_implementation(),
        "version": platform.python_version(),
        "version_info": list(sys.version_info[:3]),
    }
    if _runtime_version(runtime) < (*MINIMUM_PYTHON_VERSION, 0):
        raise RuntimeError("The Desktop operation requires an explicitly resolved Python 3.10+ runtime.")
    return runtime


def resolve_python_runtime(
    *,
    candidates: list[Path] | None = None,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Resolve and identify an explicit Python 3.10+ executable for Desktop use."""
    runtime_environment = os.environ if environment is None else environment
    if candidates is None:
        requested = runtime_environment.get("HERMES_PYTHON")
        discovered = [Path(requested)] if requested else []
        discovered.append(Path(sys.executable))
        search_path = runtime_environment.get("PATH")
        for name in ("python3.13", "python3.12", "python3.11", "python3.10", "python3"):
            if executable := shutil.which(name, path=search_path):
                discovered.append(Path(executable))
        candidates = discovered
    probe = (
        "import json,platform,sys;"
        "print(json.dumps({'executable':str(__import__('pathlib').Path(sys.executable).resolve()),"
        "'implementation':platform.python_implementation(),'version':platform.python_version(),"
        "'version_info':list(sys.version_info[:3])}))"
    )
    seen: set[str] = set()
    failures: list[str] = []
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        try:
            completed = subprocess.run(
                [key, "-c", probe],
                capture_output=True,
                text=True,
                timeout=5.0,
                check=False,
                env=dict(runtime_environment),
            )
            runtime = json.loads(completed.stdout) if completed.returncode == 0 else {}
            if not isinstance(runtime, dict) or _runtime_version(runtime) < (*MINIMUM_PYTHON_VERSION, 0):
                failures.append(f"{key}: unsupported Python runtime")
                continue
            return {
                "executable": str(runtime["executable"]),
                "implementation": str(runtime["implementation"]),
                "version": str(runtime["version"]),
                "version_info": list(_runtime_version(runtime)),
            }
        except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
            failures.append(f"{key}: {exc}")
    detail = "; ".join(failures) or "no candidates were found"
    raise RuntimeError(f"No supported Python 3.10+ Desktop runtime is available: {detail}")


def _desktop_deadline_state(
    persisted: Mapping[str, Any],
    *,
    budget_seconds: float,
    epoch_now: float,
) -> tuple[float, float, float, list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate portable deadline state, failing closed when it is unsafe."""
    if not persisted:
        return epoch_now, epoch_now + budget_seconds, budget_seconds, [], []
    fail_closed = (epoch_now - budget_seconds, epoch_now, budget_seconds, [], [])
    if "started_at_epoch" not in persisted or "deadline_at_epoch" not in persisted:
        return fail_closed
    try:
        started_at_epoch = float(persisted["started_at_epoch"])
        deadline_at_epoch = float(persisted["deadline_at_epoch"])
        persisted_budget = float(
            persisted.get("budget_seconds", deadline_at_epoch - started_at_epoch)
        )
        if not all(math.isfinite(value) for value in (
            started_at_epoch, deadline_at_epoch, persisted_budget,
        )):
            raise ValueError("Desktop deadline state contains a non-finite value.")
        if deadline_at_epoch < started_at_epoch or persisted_budget <= 0:
            raise ValueError("Desktop deadline state has an invalid interval.")
        raw_runtime_history = persisted.get("runtime_history", [])
        if not isinstance(raw_runtime_history, list) or any(
            not isinstance(item, Mapping) for item in raw_runtime_history
        ):
            raise ValueError("Desktop runtime history must be a list of objects.")
        runtime_history = [dict(item) for item in raw_runtime_history]
        raw_stage_history = persisted.get("stage_history", [])
        if not isinstance(raw_stage_history, list) or any(
            not isinstance(item, Mapping) for item in raw_stage_history
        ):
            raise ValueError("Desktop stage history must be a list of objects.")
        stage_history = [dict(item) for item in raw_stage_history]
        for field in ("attempt_counters", "stage_timings", "soft_budgets", "cleanup"):
            if field in persisted and not isinstance(persisted[field], Mapping):
                raise ValueError(f"Desktop operation {field} must be an object.")
        for field in ("soft_budget_events", "pending_handoffs"):
            if field in persisted and not isinstance(persisted[field], list):
                raise ValueError(f"Desktop operation {field} must be a list.")
    except (TypeError, ValueError, OverflowError):
        return fail_closed
    return (
        started_at_epoch,
        deadline_at_epoch,
        persisted_budget,
        runtime_history,
        stage_history,
    )


def performance_classification(elapsed_seconds: float) -> str:
    """Classify measured runtime without turning the target into a timeout."""
    if elapsed_seconds > DESKTOP_OPERATION_BUDGET_SECONDS:
        return "deadline_exceeded"
    if elapsed_seconds < NORMAL_RUNTIME_TARGET_MIN_SECONDS:
        return "below_target_window"
    if elapsed_seconds <= NORMAL_RUNTIME_TARGET_MAX_SECONDS:
        return "target_window"
    return "above_target_within_deadline"


def _active_release_identity(skill_root: Path) -> dict[str, Any]:
    """Identify the immutable release that owns a Desktop operation."""
    manifest_path = skill_root / RELEASE_MANIFEST
    if manifest_path.is_file():
        manifest = _read(manifest_path)
        fingerprint = str(manifest.get("package_fingerprint") or "")
        if not fingerprint:
            raise RuntimeError("The active release manifest has no package fingerprint.")
        return {
            "package_fingerprint": fingerprint,
            "git_commit": manifest.get("git_commit"),
            "source": "promoted_release",
        }
    implementation = [
        {
            "path": path.relative_to(skill_root).as_posix(),
            "sha256": sha256_file(path),
        }
        for path in sorted((skill_root / "scripts").glob("*.py"))
    ]
    return {
        "package_fingerprint": sha256_value(implementation),
        "git_commit": None,
        "source": "controlled_checkout",
    }


def _release_excluded(path: Path) -> bool:
    """Return whether a path belongs to development-only or sensitive data."""
    parts = set(path.parts)
    if parts & {".git", ".scratch", "runs", ".hermes", ".test-venv", ".venv", "venv", "runtime", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "tests", "input", "inputs", "source-data", "patient-data", "evidence", "output"}:
        return True
    name = path.name.casefold()
    if name in {".env", ".env.local", "artifact.md", ".coverage", INSTALLATION_ASSURANCE.casefold()} or name.endswith((".pem", ".key", ".p12", ".pfx", ".sqlite", ".sqlite3")):
        return True
    return False


def _package_release_tree(
    repo_root: Path,
    output_path: Path,
    *,
    git_commit: str,
) -> dict[str, Any]:
    """Create a deterministic, installable Hermes skill archive.

    The archive contains only the skill runtime and its governed resources. The
    manifest is written into the archive and hashes every other member, making
    the installed candidate auditable without including source inputs or runs.
    """
    repo_root = repo_root.resolve()
    output_path = output_path.expanduser().resolve()
    if output_path == repo_root or repo_root in output_path.parents:
        raise ValueError("Release archive must be outside the skill repository.")
    files = [
        path for path in sorted(repo_root.rglob("*"))
        if path.is_file() and not _release_excluded(path.relative_to(repo_root))
    ]
    if not files:
        raise ValueError("No release files were found.")
    entries = []
    for path in files:
        relative = path.relative_to(repo_root).as_posix()
        entries.append({"path": relative, "sha256": sha256_file(path), "bytes": path.stat().st_size})
    bundle_references = (
        {"meta": {"study_type": "Prospective", "icf_template": "Advarra"}},
        {"meta": {"study_type": "Prospective", "icf_template": "Sterling"}},
        {"meta": {"study_type": "Ambispective", "icf_template": "Advarra"}},
        {"meta": {"study_type": "Ambispective", "icf_template": "Sterling"}},
        {"meta": {"study_type": "Retrospective"}},
    )
    bundles = [contracted_template_bundle(repo_root, reference) for reference in bundle_references]
    governed_resources = sorted({
        relative
        for bundle in bundles
        for relative in bundle["resource_hashes"]
    })
    templates = [repo_root / relative for relative in governed_resources if Path(relative).suffix.casefold() == ".docx"]
    font_inventory = {}
    for path in templates:
        if path.suffix.casefold() == ".docx":
            font_inventory[path.relative_to(repo_root).as_posix()] = sorted(_template_fonts(path))
    required_font_names = sorted({font for fonts in font_inventory.values() for font in fonts})
    approved_font_plan = bundles[0]["approved_font_plan"]
    pdf_renderer = dict(PDF_PAGE_RENDERER)
    pdf_renderer_wheel = repo_root / pdf_renderer["wheel"]
    if (
        not pdf_renderer_wheel.is_file()
        or sha256_file(pdf_renderer_wheel) != pdf_renderer["wheel_sha256"]
    ):
        raise ValueError(
            "The pinned pypdfium2 wheel is missing or does not match its governed hash."
        )
    implementation_files = [item["path"] for item in entries if item["path"].startswith("scripts/")]
    manifest = {
        "schema_version": "hermes-release-manifest/v2",
        "git_commit": git_commit,
        "package_root": "clinical-document-generation",
        "package_purpose": "Installable runtime for the reviewed clinical document workflow.",
        "installation": {
            "entrypoint": "SKILL.md",
            "runtime": "Python 3.10+",
            "dependencies": "requirements.txt",
            "install_as_direct_child_of": "Hermes skills directory",
            "activation": "atomic after end-to-end Render Assurance smoke; previous verified release retained",
            "required_external_tools": ["Microsoft Word or LibreOffice"],
        },
        "inventory": {
            "implementation": implementation_files,
            "contracted_template_bundles": bundles,
            "governed_resources": governed_resources,
            "font_identities": font_inventory,
            "font_fallbacks": {font: [_approved_packaged_font_fallback(font, approved_font_plan)] for font in required_font_names},
            "renderer_at_packaging": renderer(environment=os.environ),
            "pdf_page_renderer": pdf_renderer,
            "harness": {"python": platform.python_version(), "platform": platform.platform()},
            "model": "Hermes Desktop runtime; model identity is recorded per generation evidence.",
        },
        "excluded_classes": ["git metadata", "development virtual environments", "credentials", "patient/source data", "old run outputs", "development tests", "installed runtime and assurance evidence"],
        "files": entries,
    }
    manifest_payload = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    manifest["package_fingerprint"] = hashlib.sha256(manifest_payload).hexdigest()
    manifest_text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.tmp")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in files:
                relative = path.relative_to(repo_root).as_posix()
                info = zipfile.ZipInfo(f"clinical-document-generation/{relative}", date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, path.read_bytes())
            info = zipfile.ZipInfo(f"clinical-document-generation/{RELEASE_MANIFEST}", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, manifest_text.encode("utf-8"))
        os.replace(temporary, output_path)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "status": "passed",
        "package": output_path.as_posix(),
        "package_fingerprint": manifest["package_fingerprint"],
        "git_commit": git_commit,
        "file_count": len(entries),
        "archive_bytes": output_path.stat().st_size,
        "manifest": f"clinical-document-generation/{RELEASE_MANIFEST}",
    }


def package_release(repo_root: Path, output_path: Path) -> dict[str, Any]:
    """Package the exact committed tree, never mutable checkout bytes."""
    repo_root = repo_root.resolve()
    output_path = output_path.expanduser().resolve()
    if output_path == repo_root or repo_root in output_path.parents:
        raise ValueError("Release archive must be outside the skill repository.")
    try:
        git_root = Path(subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()).resolve()
        commit = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--verify", "HEAD^{commit}"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("A release must be built from a committed Git tree.") from exc
    if git_root != repo_root:
        raise ValueError("Release packaging must target the Git repository root.")
    with tempfile.TemporaryDirectory(prefix="clinical-release-commit-") as temporary_dir:
        snapshot_root = Path(temporary_dir) / "snapshot"
        snapshot_root.mkdir()
        snapshot_root = snapshot_root.resolve()
        archive_path = Path(temporary_dir) / "commit.tar"
        try:
            with archive_path.open("wb") as archive_handle:
                subprocess.run(
                    ["git", "-C", str(repo_root), "archive", "--format=tar", commit],
                    check=True,
                    stdout=archive_handle,
                    stderr=subprocess.PIPE,
                )
            with tarfile.open(archive_path, "r") as archive:
                for member in archive.getmembers():
                    target = (snapshot_root / member.name).resolve()
                    try:
                        target.relative_to(snapshot_root)
                    except ValueError as exc:
                        raise ValueError("The committed release archive contains an escaping path.") from exc
                    if member.issym() or member.islnk():
                        raise ValueError("The committed release archive contains an unsupported link.")
                archive.extractall(snapshot_root)
        except (OSError, subprocess.CalledProcessError, tarfile.TarError, ValueError) as exc:
            raise ValueError("The committed release tree could not be materialized.") from exc
        return _package_release_tree(snapshot_root, output_path, git_commit=commit)


def _manifest_integrity(skill_root: Path) -> list[dict[str, Any]]:
    manifest_path = skill_root / RELEASE_MANIFEST
    if not manifest_path.is_file():
        return [{"category": "installation", "field": RELEASE_MANIFEST, "issue": "Release manifest is missing."}]
    try:
        manifest = _read(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [{"category": "installation", "field": RELEASE_MANIFEST, "issue": str(exc)}]
    findings = []
    for item in manifest.get("files", []):
        path = skill_root / str(item.get("path") or "")
        try:
            path.resolve().relative_to(skill_root.resolve())
        except ValueError:
            findings.append({"category": "installation", "field": str(path), "issue": "Manifest path escapes the skill root."})
            continue
        if not path.is_file():
            findings.append({"category": "installation", "field": str(item.get("path")), "issue": "Packaged file is missing."})
        elif sha256_file(path) != item.get("sha256"):
            findings.append({"category": "installation", "field": str(item.get("path")), "issue": "Packaged file hash does not match the release manifest."})
    return findings


def verify_installation(skill_root: Path, *, deadline_seconds: float = 120.0) -> dict[str, Any]:
    """Prove that an extracted release owns a complete local assurance path."""
    skill_root = skill_root.resolve()
    findings = _manifest_integrity(skill_root)
    fallback_fonts = skill_root / "assets/fallback-fonts"
    if not any(fallback_fonts.glob("*.ttf")):
        findings.append({"category": "installation", "field": "fallback_fonts", "issue": "No packaged compatible fonts are present."})
    reference = {"meta": {"study_type": "Prospective", "icf_template": "Advarra"}}
    fallback_renderers = [
        item for item in renderers(skill_root=skill_root)
        if item.get("source") == "verified fallback stack"
    ]
    fallback_pages = [
        item for item in page_renderers(skill_root=skill_root)
        if item.get("kind") == "pypdfium2" and item.get("source") == "release-owned runtime"
    ]
    with tempfile.TemporaryDirectory(prefix="clinical-installation-assurance-") as directory:
        revision_dir = Path(directory)
        candidate_dir = revision_dir / "candidate"
        candidate_dir.mkdir()
        document = Document()
        for font in BUNDLED_FONT_FILES:
            run = document.add_paragraph().add_run(f"{font}: Clinical document installation smoke")
            run.font.name = font
        document.save(candidate_dir / "installation-smoke.docx")
        smoke_path = candidate_dir / "installation-smoke.docx"
        assurance = render_assurance(
            skill_root,
            revision_dir,
            reference,
            structural_validation={
                "status": "structurally_valid",
                "expected_files": [smoke_path.name],
                "candidate_files": [{
                    "path": smoke_path.relative_to(revision_dir).as_posix(),
                    "sha256": sha256_file(smoke_path),
                    "bytes": smoke_path.stat().st_size,
                }],
            },
            deadline_seconds=deadline_seconds,
            renderer_identities=fallback_renderers,
            page_renderer_identities=fallback_pages,
            rebuild_candidate=lambda _substitutions: {"status": "passed"},
        )
    if assurance.get("status") != "passed":
        findings.extend(assurance.get("findings", []))
    render_evidence = assurance.get("render", {})
    candidates = [attempt.get("adapter") for attempt in render_evidence.get("renderer_attempts", []) if attempt.get("adapter")]
    if not fallback_renderers:
        findings.append({"category": "installation", "field": "fallback_renderer", "issue": "The versioned local LibreOffice fallback was not discovered."})
    if not fallback_pages:
        findings.append({"category": "installation", "field": "pdf_page_renderer", "issue": "The release-owned pypdfium2 page renderer was not discovered."})
    return {
        "status": "passed" if not findings else "blocked",
        "renderer": render_evidence.get("renderer"),
        "renderer_candidates": candidates,
        "page_renderer": render_evidence.get("page_renderer"),
        "fonts": assurance.get("fonts", {}),
        "smoke": {
            "status": assurance.get("status"),
            "pages": sum(len(item.get("pages", [])) for item in render_evidence.get("artifacts", [])),
        },
        "render_assurance": assurance,
        "findings": findings,
    }


def _provisionable_libreoffice() -> tuple[Path, Path] | None:
    """Return (tree root, relative executable) for a locally reusable runtime."""
    system = platform.system()
    if system == "Darwin":
        roots = [Path("/Applications/LibreOffice.app")]
        cache = Path.home() / ".cache/codex-runtimes"
        roots.extend(sorted(cache.glob("*/dependencies/native/libreoffice-headless/libreoffice/*.app")))
        for root in roots:
            executable = root / "Contents/MacOS/soffice"
            if executable.is_file() and os.access(executable, os.X_OK):
                return root, executable.relative_to(root)
    for identity in renderers():
        if identity.get("kind") != "LibreOffice":
            continue
        executable = Path(str(identity["path"])).resolve()
        if executable.is_file() and os.access(executable, os.X_OK):
            root = executable.parent.parent if executable.parent.name == "program" else executable.parent
            return root, executable.relative_to(root)
    return None


def _provision_page_renderer(skill_root: Path) -> dict[str, Any]:
    """Install the manifest-bound pypdfium2 wheel without host discovery."""
    skill_root = skill_root.resolve()
    runtime_root = skill_root / "runtime"
    runtime_python = runtime_root / "python"
    existing = page_renderers(skill_root=skill_root)
    if existing:
        return {"status": "passed", "page_renderer": existing[0], "provisioned": False}
    try:
        manifest = _read(skill_root / RELEASE_MANIFEST)
        identity = dict(manifest["inventory"]["pdf_page_renderer"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return {"status": "blocked", "findings": [{
            "category": "installation",
            "field": "pdf_page_renderer",
            "issue": "The release manifest does not identify its one packaged pypdfium2 renderer.",
        }]}
    if identity.get("kind") != "pypdfium2":
        return {"status": "blocked", "findings": [{
            "category": "installation",
            "field": "pdf_page_renderer",
            "issue": "The release manifest must identify pypdfium2 as its only PDF page renderer.",
        }]}
    wheel_relative = Path(str(identity.get("wheel") or ""))
    wheel = (skill_root / wheel_relative).resolve()
    try:
        wheel.relative_to(skill_root)
    except ValueError:
        wheel = Path()
    expected_hash = str(identity.get("wheel_sha256") or "")
    if not wheel.is_file() or not expected_hash or sha256_file(wheel) != expected_hash:
        return {"status": "blocked", "findings": [{
            "category": "installation",
            "field": "pdf_page_renderer",
            "issue": "The packaged pypdfium2 wheel is missing or does not match its release-manifest hash.",
        }]}
    platform_tag = str(identity.get("platform") or "")
    host = f"{platform.system()} {platform.machine()}"
    compatible = (
        platform.system() == "Darwin"
        and "macosx" in platform_tag
        and platform.machine().casefold() in platform_tag.casefold()
    )
    if not compatible:
        return {"status": "blocked", "findings": [{
            "category": "installation",
            "field": "pdf_page_renderer",
            "issue": f"Packaged pypdfium2 targets {platform_tag}; this host is {host}.",
        }]}
    staged_python = runtime_root / ".pypdfium2-install"
    shutil.rmtree(staged_python, ignore_errors=True)
    staged_python.mkdir(parents=True)
    try:
        with zipfile.ZipFile(wheel) as archive:
            for member in archive.infolist():
                target = (staged_python / member.filename).resolve()
                try:
                    target.relative_to(staged_python.resolve())
                except ValueError as exc:
                    raise ValueError("The packaged pypdfium2 wheel contains an escaping path.") from exc
                if (member.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("The packaged pypdfium2 wheel contains an unsupported symbolic link.")
            archive.extractall(staged_python)
        shutil.rmtree(runtime_python, ignore_errors=True)
        os.replace(staged_python, runtime_python)
        _write(runtime_root / "PDF-RENDERER.json", {
            "kind": "pypdfium2",
            "version": str(identity.get("version") or ""),
            "wheel": wheel_relative.as_posix(),
            "wheel_sha256": expected_hash,
        })
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        shutil.rmtree(staged_python, ignore_errors=True)
        return {"status": "blocked", "findings": [{
            "category": "installation",
            "field": "pdf_page_renderer",
            "issue": f"The packaged pypdfium2 wheel could not be installed: {exc}",
        }]}
    installed = page_renderers(skill_root=skill_root)
    if len(installed) != 1:
        return {"status": "blocked", "findings": [{
            "category": "installation",
            "field": "pdf_page_renderer",
            "issue": "The release-owned pypdfium2 runtime could not be discovered after installation.",
        }]}
    identity = installed[0]
    return {"status": "passed", "page_renderer": identity, "provisioned": True}


def provision_fallback_stack(skill_root: Path) -> dict[str, Any]:
    """Provision version-local DOCX and page renderers without changing the host."""
    skill_root = skill_root.resolve()
    runtime_root = skill_root / "runtime"
    existing = renderers(skill_root=skill_root)
    page_provision = _provision_page_renderer(skill_root)
    if page_provision.get("status") != "passed":
        return page_provision
    if any(item.get("source") == "verified fallback stack" for item in existing):
        return {
            "status": "passed",
            "renderer": next(item for item in existing if item.get("source") == "verified fallback stack"),
            "page_renderer": page_provision["page_renderer"],
            "provisioned": {"renderer": False, "page_renderer": page_provision["provisioned"]},
        }
    source = _provisionable_libreoffice()
    if source is None:
        return {"status": "blocked", "findings": [{"category": "installation", "field": "fallback_renderer", "issue": "No local LibreOffice runtime is available to provision."}]}
    source_root, relative_executable = source
    destination = runtime_root / source_root.name
    runtime_root.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(source_root, destination, copy_function=os.link)
    except OSError:
        shutil.rmtree(destination, ignore_errors=True)
        shutil.copytree(source_root, destination)
    executable = destination / relative_executable
    return {
        "status": "passed",
        "renderer": {"kind": "LibreOffice", "path": str(executable), "source": "verified fallback stack", "platform": platform.system()},
        "page_renderer": page_provision["page_renderer"],
        "provisioned": {"renderer": True, "page_renderer": page_provision["provisioned"]},
    }


def _relocate_paths(value: Any, source_root: Path, destination_root: Path) -> Any:
    """Rewrite staged absolute paths to their post-activation location."""
    if isinstance(value, Mapping):
        return {str(key): _relocate_paths(item, source_root, destination_root) for key, item in value.items()}
    if isinstance(value, list):
        return [_relocate_paths(item, source_root, destination_root) for item in value]
    if isinstance(value, str):
        source = str(source_root)
        if value == source or value.startswith(source + os.sep):
            return str(destination_root) + value[len(source):]
    return value


def install_release(
    archive_path: Path,
    skills_dir: Path,
    *,
    verifier: Callable[[Path], Mapping[str, Any]] | None = None,
    provisioner: Callable[[Path], Mapping[str, Any]] = provision_fallback_stack,
) -> dict[str, Any]:
    """Smoke, then atomically activate an installable skill archive."""
    archive_path = archive_path.expanduser().resolve()
    skills_dir = skills_dir.expanduser().resolve()
    skills_dir.mkdir(parents=True, exist_ok=True)
    staging_root = Path(tempfile.mkdtemp(prefix=".clinical-document-generation.install-", dir=skills_dir))
    active = skills_dir / "clinical-document-generation"
    previous = skills_dir / ".clinical-document-generation.previous"
    candidate = staging_root / "clinical-document-generation"
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for info in archive.infolist():
                target = (staging_root / info.filename).resolve()
                try:
                    target.relative_to(staging_root)
                except ValueError as exc:
                    raise ValueError(f"Release archive path escapes the staging root: {info.filename}") from exc
            archive.extractall(staging_root)
        provision = dict(provisioner(candidate))
        if provision.get("status") != "passed":
            return {"status": "blocked", "stage": "provision", "findings": list(provision.get("findings", [])), "active_release_retained": active.is_dir()}
        if verifier is None:
            completed = subprocess.run(
                [sys.executable, str(candidate / "scripts/workflow.py"), "--verify-installation"],
                cwd=candidate,
                text=True,
                capture_output=True,
                timeout=180,
            )
            try:
                assurance = json.loads(completed.stdout)
            except json.JSONDecodeError:
                assurance = {
                    "status": "blocked",
                    "findings": [{"category": "installation", "field": "smoke", "issue": completed.stderr or completed.stdout or "Installation smoke returned no JSON."}],
                }
            if completed.returncode and assurance.get("status") == "passed":
                assurance = {"status": "blocked", "findings": [{"category": "installation", "field": "smoke", "issue": completed.stderr or "Installation smoke process failed."}]}
        else:
            assurance = dict(verifier(candidate))
        if assurance.get("status") != "passed":
            return {"status": "blocked", "stage": "installation_smoke", "findings": list(assurance.get("findings", [])), "active_release_retained": active.is_dir()}
        recorded_provision = _relocate_paths(provision, candidate, active)
        recorded_assurance = _relocate_paths(assurance, candidate, active)
        _write(candidate / INSTALLATION_ASSURANCE, {
            "status": "passed",
            "verified_at": datetime.now(timezone.utc).isoformat(),
            "provision": recorded_provision,
            "assurance": recorded_assurance,
        })
        displaced_previous = None
        if previous.exists():
            displaced_previous = skills_dir / f".clinical-document-generation.previous-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
            os.replace(previous, displaced_previous)
        if active.exists():
            os.replace(active, previous)
        try:
            os.replace(candidate, active)
        except Exception:
            if previous.exists() and not active.exists():
                os.replace(previous, active)
            raise
        return {
            "status": "passed",
            "stage": "activated",
            "active": str(active),
            "previous": str(previous) if previous.exists() else None,
            "displaced_previous": str(displaced_previous) if displaced_previous else None,
            "assurance": recorded_assurance,
        }
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)


@dataclass(frozen=True)
class RetryTarget:
    category: str
    value: str

    @classmethod
    def parse(cls, target_id: str) -> "RetryTarget":
        category, separator, value = target_id.partition(":")
        return cls(category, value) if separator else cls("section", target_id)

    @property
    def target_id(self) -> str:
        return self.value if self.category == "section" else f"{self.category}:{self.value}"


VERIFICATION_TASK_BY_TARGET = {
    "content": "clinical_content_verification",
    "visual": "rendered_page_visual_verification",
}

LAYOUT_RULE_BY_VISUAL_CHECK = {
    "orphan_heading": "heading_cohesion",
    "artificial_pagination": "body_pagination",
    "bad_table_split": "table_pagination",
}
def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict): raise ValueError(f"Expected JSON object: {path}")
    return value


def _read_corpus(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"Expected a JSON list of objects: {path}")
    return value


def _write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _reference(run_dir: Path) -> tuple[Path, dict[str, Any]]:
    path = run_dir / REFERENCE
    if not path.is_file(): raise FileNotFoundError(f"Create {path} from the study inputs before running prepare.")
    return path, _read(path)


def _slug(value: Any) -> str:
    text = "".join(character.lower() if character.isalnum() else "-" for character in str(value or "study"))
    return "-".join(part for part in text.split("-") if part)[:60] or "study"


def desktop_operation_state_path(run_dir: Path, operation_id: str = "default") -> Path:
    """Return the canonical persisted-state path for one Desktop operation."""
    operation_key = _slug(operation_id)
    name = "desktop-operation.json" if operation_key == "default" else f"desktop-operation-{operation_key}.json"
    return Path(run_dir).resolve() / "logs" / name


def _source_path(run_dir: Path, reference: Mapping[str, Any]) -> Path:
    recorded = reference.get("source", {}).get("source_of_truth_file") if isinstance(reference.get("source"), Mapping) else None
    if recorded:
        path = Path(str(recorded)); return path if path.is_absolute() else run_dir / path
    protocol = reference.get("meta", {}).get("protocol_number") if isinstance(reference.get("meta"), Mapping) else "study"
    title = reference.get("study", {}).get("title") if isinstance(reference.get("study"), Mapping) else "study"
    return run_dir / "reference" / f"source-of-truth--{_slug(protocol)}--{_slug(title)}.md"


def _approved_payload(reference: Mapping[str, Any]) -> dict[str, Any]:
    """Return only reviewer-controlled and approval-bound data."""
    payload = copy.deepcopy(dict(reference))
    payload.pop("generation", None)
    payload.pop("approval", None)
    return payload


def _approval_valid(
    run_dir: Path,
    reference: Mapping[str, Any],
    *,
    contracted_bundle: Mapping[str, Any] | None = None,
) -> tuple[bool, str]:
    approval = reference.get("approval") if isinstance(reference.get("approval"), Mapping) else {}
    source = _source_path(run_dir, reference)
    if str(approval.get("status", "")).casefold() != "approved": return False, "The Source-of-Truth Markdown has not been explicitly approved."
    if not source.is_file(): return False, "The approved Source-of-Truth Markdown is missing."
    if approval.get("source_sha256") != sha256_file(source): return False, "The Source-of-Truth Markdown changed after approval; approve the current file again."
    revision_id = str(approval.get("revision_id") or "")
    snapshot_path = run_dir / "revisions" / revision_id / "approved-reference.json"
    approved_source = run_dir / "revisions" / revision_id / "approved-source.md"
    if not revision_id or not snapshot_path.is_file() or not approved_source.is_file():
        return False, "The write-once approved revision snapshot is missing."
    if sha256_file(approved_source) != approval.get("source_sha256"):
        return False, "The approved revision copy of the Source-of-Truth is not hash-identical."
    if approval.get("approved_reference_sha256") != sha256_file(snapshot_path):
        return False, "The approved reference snapshot changed after approval."
    snapshot = _read(snapshot_path)
    if _approved_payload(reference) != _approved_payload(snapshot):
        return False, "Study inputs changed after approval; prepare and approve a new Source-of-Truth revision."
    expected_governing = sha256_value(governing_resources(
        SCRIPT_DIR.parent,
        snapshot,
        contracted_bundle=contracted_bundle,
    ))
    if approval.get("governing_sha256") != expected_governing:
        return False, "Generation contracts, templates, or implementation changed after approval; approve the unchanged Source-of-Truth again to create a new immutable revision."
    return True, ""


_OPTIONAL_REVIEW_FIELDS = (
    "study.condition",
    "procedures.methods",
    "procedures.unscheduled_visits",
    "procedures.discontinuation",
    "procedures.termination",
    "procedures.study_termination",
    "statistics.methodology",
    "statistics.analysis_populations",
    "statistics.missing_data_handling",
    "safety.general_information",
    "safety.monitoring",
    "safety.adverse_events",
    "safety.follow_up",
    "confidentiality.data_handling",
    "confidentiality.publication",
    "risks_benefits.risks",
    "risks_benefits.benefits",
    "risks_benefits.costs",
    "risks_benefits.alternatives",
    "risks_benefits.privacy",
    "risks_benefits.injury_handling",
)
_OPTIONAL_PRS_REVIEW_FIELDS = (
    "regulatory.prs.observational_study_design",
    "regulatory.prs.time_perspective",
    "regulatory.prs.verification_date",
    "regulatory.prs.start_date",
    "regulatory.prs.start_date_type",
    "regulatory.prs.primary_completion_date",
    "regulatory.prs.primary_completion_date_type",
    "regulatory.prs.study_completion_date",
    "regulatory.prs.study_completion_date_type",
    "regulatory.prs.patient_registry",
    "regulatory.prs.target_duration_quantity",
    "regulatory.prs.target_duration_units",
)


def _ensure_optional_review_fields(reference: dict[str, Any], branch: str | None) -> None:
    missing = object()
    paths = _OPTIONAL_REVIEW_FIELDS + (_OPTIONAL_PRS_REVIEW_FIELDS if branch != "Retrospective" else ())
    for path in paths:
        if get_path(reference, path, missing) is missing:
            set_path(reference, path, None)
    for outcome_kind in ("primary", "secondary", "other"):
        outcomes = get_path(reference, f"endpoints.{outcome_kind}")
        if not isinstance(outcomes, list):
            continue
        for outcome in outcomes:
            if isinstance(outcome, dict):
                outcome.setdefault("description", "")
                outcome.setdefault("analysis_method", "")


def prepare(run_dir: Path, *, today: date | None = None, **_: Any) -> dict[str, Any]:
    """Validate mandatory inputs and create the reviewer-editable source file."""
    run_dir = run_dir.resolve(); reference_path, reference = _reference(run_dir)
    contract = source_contract(reference, derive_prs_study_type=True)
    if contract["status"] != "passed":
        path = run_dir / "reference/missing-inputs.md"; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(repair_report(contract["blocking_findings"]), encoding="utf-8")
        return {"status": "blocked", "stage": "input_collection", "study_type": contract.get("study_type"), "missing": contract["blocking_findings"], "missing_inputs": path.relative_to(run_dir).as_posix(), "client_outputs": []}
    reference = contract["normalized_reference"]
    _ensure_optional_review_fields(reference, contract.get("study_type"))
    meta = reference.setdefault("meta", {})
    if not str(meta.get("date") or "").strip():
        meta["date"] = (today or date.today()).strftime("%d %b %Y")
    if meta.get("version") is None:
        meta["version"] = ""
    source = _source_path(run_dir, reference); source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(source_truth_markdown(reference), encoding="utf-8")
    reference.setdefault("source", {})["source_of_truth_file"] = source.relative_to(run_dir).as_posix()
    reference["approval"] = {"status": "awaiting_approval", "review_file": source.relative_to(run_dir).as_posix()}
    _write(reference_path, reference)
    (run_dir / "reference/missing-inputs.md").unlink(missing_ok=True)
    relative_source = source.relative_to(run_dir).as_posix()
    review_delivery = {
        "mode": "file",
        "role": "editable_source_of_truth",
        "path": relative_source,
        "absolute_path": source.resolve().as_posix(),
        "filename": source.name,
        "mime_type": "text/markdown",
        "editable": True,
        "inline_chat": False,
        "must_attach": True,
    }
    return {"status": "awaiting_approval", "stage": "source_review", "study_type": contract.get("study_type"), "source_of_truth": relative_source, "review_delivery": review_delivery, "client_outputs": []}


def approve(run_dir: Path, *, approved_by: str = "client", source_md: Path | None = None, **_: Any) -> dict[str, Any]:
    """Parse the current reviewer file exactly and bind explicit approval."""
    run_dir = run_dir.resolve(); reference_path, prior = _reference(run_dir)
    source = source_md.resolve() if source_md else _source_path(run_dir, prior)
    if not source.is_file(): raise FileNotFoundError(source)
    reference_dir = (run_dir / "reference").resolve()
    try: source.relative_to(reference_dir)
    except ValueError:
        canonical = reference_dir / "approved-source-of-truth.md"; shutil.copy2(source, canonical); source = canonical
    parsed = parse_source_truth(source.read_text(encoding="utf-8"), prior)
    contract = source_contract(parsed)
    report_path = run_dir / "reference/review-parse-report.md"
    report_path.write_text(repair_report(contract["blocking_findings"]), encoding="utf-8")
    if contract["status"] != "passed":
        return {"status": "blocked", "stage": "approval", "findings": contract["blocking_findings"], "client_outputs": []}
    reference = contract["normalized_reference"]
    reference.pop("generation", None)
    reference.setdefault("source", {})["source_of_truth_file"] = source.relative_to(run_dir).as_posix()
    digest = sha256_file(source)
    approval = {"status": "approved", "approved_by": approved_by, "approved_at": datetime.now(timezone.utc).isoformat(), "review_file": source.relative_to(run_dir).as_posix(), "source_sha256": digest}
    reference["approval"] = approval
    bundle = contracted_template_bundle(SCRIPT_DIR.parent, reference)
    governing = governing_resources(SCRIPT_DIR.parent, reference, contracted_bundle=bundle)
    governing_sha256 = sha256_value(governing)
    revision_identity = sha256_value({
        "approved_source_sha256": digest,
        "approved_reference": _approved_payload(reference),
        "governing_resources": governing,
    })
    revision_id = f"r-{revision_identity[:12]}"
    approval["revision_id"] = revision_id
    approval["governing_sha256"] = governing_sha256
    revision_dir = run_dir / "revisions" / revision_id
    snapshot_path = revision_dir / "approved-reference.json"
    approved_source_path = revision_dir / "approved-source.md"
    if revision_dir.exists():
        if not snapshot_path.is_file() or not approved_source_path.is_file():
            return {"status": "blocked", "stage": "approval", "findings": [{"category": "revision", "field": revision_id, "issue": "An incomplete revision already occupies the approved source hash."}], "client_outputs": []}
        existing = _read(snapshot_path)
        if _approved_payload(existing) != _approved_payload(reference) or sha256_file(approved_source_path) != digest:
            return {"status": "blocked", "stage": "approval", "findings": [{"category": "revision", "field": revision_id, "issue": "A different write-once revision already occupies the approved source hash."}], "client_outputs": []}
        reference["approval"] = dict(existing.get("approval", approval))
    else:
        revision_dir.mkdir(parents=True)
        _write(snapshot_path, reference)
        approved_source_path.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    reference["approval"]["approved_reference_sha256"] = sha256_file(snapshot_path)
    _write(reference_path, reference)
    return {"status": "passed", "stage": "approval", "revision_id": revision_id, "source_sha256": digest, "client_outputs": []}


def validate(run_dir: Path, **_: Any) -> dict[str, Any]:
    run_dir = run_dir.resolve(); _, reference = _reference(run_dir)
    contract = source_contract(reference); approved, approval_issue = _approval_valid(run_dir, reference)
    findings = list(contract["blocking_findings"])
    if not approved: findings.append({"category": "approval", "field": "approval", "issue": approval_issue})
    return {"status": "passed" if not findings else "blocked", "stage": "readiness", "study_type": contract.get("study_type"), "findings": findings, "client_outputs": []}


def _awaiting(revision_dir: Path, *, stage: str, paths: list[Path], findings: list[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    handoffs = []
    for path in paths:
        request = _read(path)
        handoff = {
            "request_path": path.relative_to(revision_dir).as_posix(),
            "response_path": str(request["response_path"]),
            "task": str(request["task"]),
            "batch_id": request.get("batch_id"),
        }
        if request.get("task") == "rendered_page_visual_verification":
            handoff["request_id"] = str(request["request_id"])
            handoff["request_sha256"] = str(request["request_sha256"])
            handoff["fallback_owner"] = "parent"
            handoff["completion_requirement"] = "inspect_every_bound_page_image"
        handoffs.append(handoff)
    return {
        "status": "awaiting_hermes",
        "stage": stage,
        "revision_id": revision_dir.name,
        "requests": [item["request_path"] for item in handoffs],
        "handoffs": handoffs,
        "findings": list(findings or []),
        "client_outputs": [],
    }


def _repair_block(
    run_dir: Path,
    stage: str,
    findings: list[Mapping[str, Any]],
    *,
    candidate_outputs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    path = run_dir / "reference/repair-report.md"
    path.write_text(repair_report(findings), encoding="utf-8")
    result: dict[str, Any] = {
        "status": "blocked",
        "stage": stage,
        "findings": [dict(finding) for finding in findings],
        "repair_report": path.relative_to(run_dir).as_posix(),
        "client_outputs": [],
    }
    if candidate_outputs is not None:
        result["candidate_outputs"] = candidate_outputs
    return result


def _document_report_failure(
    run_dir: Path,
    revision_dir: Path,
    document_report: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Interpret one blocked DOCX report identically on every render path."""
    findings = []
    for item in document_report.get("artifacts", []):
        for raw in item.get("findings", []):
            finding = dict(raw)
            governed = (
                finding.get("recovery_class") in RECOVERY_POLICIES
                and finding.get("action") == RECOVERY_POLICIES.get(str(finding.get("recovery_class")))
            )
            findings.append(
                finding if governed
                else recovery_finding({**finding, "target_ids": [f"layout:{item['artifact']}"]}, "document_structure_defect")
            )
    classification = [
        finding for finding in findings
        if finding.get("category") == "layout-repair-classification"
    ]
    if not classification:
        return findings, None
    return findings, _repair_block(
        run_dir,
        "layout_repair_classification",
        classification,
        candidate_outputs=_candidate_outputs(revision_dir),
    )


def _candidate_fingerprint(
    repo_root: Path,
    revision_dir: Path,
    reference: Mapping[str, Any],
    model: Mapping[str, Any],
    *,
    contracted_bundle: Mapping[str, Any],
    font_substitutions: Mapping[str, str] | None = None,
    layout_repairs: Mapping[str, Iterable[Mapping[str, str]]] | None = None,
) -> tuple[str, dict[str, Any]]:
    implementation_files = [repo_root / "scripts" / name for name in ("workflow.py", "contracts.py", "drafting.py", "rendering.py", "quality.py", "prs_xml.py")]
    accepted_files = sorted((revision_dir / "hermes/accepted").glob("*.json"))
    payload = {
        "approved_reference_sha256": sha256_file(revision_dir / "approved-reference.json"),
        "approved_source_sha256": get_path(reference, "approval.source_sha256"),
        "contracted_template_bundle": dict(contracted_bundle),
        "implementation": {path.name: sha256_file(path) for path in implementation_files},
        "accepted_drafts": {path.relative_to(revision_dir).as_posix(): sha256_file(path) for path in accepted_files},
        "merged_model_sha256": sha256_value(model),
        "font_substitutions": dict(sorted((font_substitutions or {}).items())),
        "layout_repairs": {
            str(artifact): _normalized_layout_repair_records(repairs)
            for artifact, repairs in sorted(dict(layout_repairs or {}).items())
        },
    }
    return sha256_value(payload), payload


def _cached_build(revision_dir: Path, fingerprint: str) -> dict[str, Any] | None:
    path = revision_dir / "candidate-build.json"
    if not path.is_file():
        return None
    try:
        build = _read(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if build.get("fingerprint") != fingerprint:
        return None
    for artifact in build.get("candidate_files", []):
        target = revision_dir / str(artifact.get("path"))
        if not target.is_file() or sha256_file(target) != artifact.get("sha256"):
            return None
    render_report = build.get("render_report", {})
    for artifact in render_report.get("artifacts", []):
        for key in ("docx", "pdf"):
            target = revision_dir / str(artifact.get(key))
            if not target.is_file() or sha256_file(target) != artifact.get(f"{key}_sha256"):
                return None
        for page in artifact.get("pages", []):
            target = revision_dir / str(page.get("path"))
            if not target.is_file() or sha256_file(target) != page.get("sha256"):
                return None
    return build


def _record_build(revision_dir: Path, fingerprint: str, governing: Mapping[str, Any], contracted_bundle: Mapping[str, Any], document_report: Mapping[str, Any], xml_report: Mapping[str, Any] | None, render_report: Mapping[str, Any]) -> dict[str, Any]:
    candidate_files = _candidate_file_records(revision_dir)
    build = {"fingerprint": fingerprint, "governing_resources": dict(governing), "contracted_template_bundle": dict(contracted_bundle), "candidate_files": candidate_files, "document_report": dict(document_report), "xml_report": dict(xml_report) if xml_report else None, "render_report": dict(render_report)}
    _write(revision_dir / "candidate-build.json", build)
    return build


def _candidate_file_records(revision_dir: Path) -> list[dict[str, Any]]:
    return [
        {
            "path": path.relative_to(revision_dir).as_posix(),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
        for path in sorted((revision_dir / "candidate").glob("*"))
        if path.is_file()
    ]


def _cached_candidate_structure(revision_dir: Path, fingerprint: str) -> dict[str, Any] | None:
    path = revision_dir / "candidate-structure.json"
    if not path.is_file():
        return None
    try:
        snapshot = _read(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if snapshot.get("fingerprint") != fingerprint:
        return None
    for artifact in snapshot.get("candidate_files", []):
        target = revision_dir / str(artifact.get("path"))
        if not target.is_file() or sha256_file(target) != artifact.get("sha256"):
            return None
    return snapshot


def _record_candidate_structure(
    revision_dir: Path,
    fingerprint: str,
    governing: Mapping[str, Any],
    contracted_bundle: Mapping[str, Any],
    document_report: Mapping[str, Any],
    xml_report: Mapping[str, Any] | None,
    expected_files: Iterable[str],
) -> dict[str, Any]:
    snapshot = {
        "fingerprint": fingerprint,
        "governing_resources": dict(governing),
        "contracted_template_bundle": dict(contracted_bundle),
        "candidate_files": _candidate_file_records(revision_dir),
        "document_report": dict(document_report),
        "xml_report": dict(xml_report) if xml_report else None,
        "font_substitutions": dict(governing.get("font_substitutions") or {}),
        "expected_files": sorted(str(name) for name in expected_files),
        "status": "structurally_valid",
    }
    _write(revision_dir / "candidate-structure.json", snapshot)
    return snapshot


def _merge_artifact_reports(prior: Mapping[str, Any], current: Mapping[str, Any]) -> dict[str, Any]:
    """Replace only newly generated artifact rows in a complete prior report."""
    def rows(report: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for item in report.get("artifacts", []):
            if not isinstance(item, Mapping) or not item.get("artifact"):
                continue
            row = dict(item)
            row.setdefault("renderer", report.get("renderer"))
            row.setdefault("page_renderer", report.get("page_renderer"))
            result[str(item["artifact"])] = row
        return result

    artifacts = rows(prior)
    artifacts.update(rows(current))
    merged = {**dict(prior), **dict(current), "artifacts": [artifacts[key] for key in sorted(artifacts)]}
    merged["status"] = "passed" if artifacts and all(item.get("status", "passed") == "passed" for item in artifacts.values()) else "blocked"
    return merged


def _merge_partial_assurance(
    prior_build: Mapping[str, Any],
    assurance: Mapping[str, Any],
    repaired_artifacts: set[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the complete exact-artifact evidence persisted after a local repair."""
    complete = dict(assurance)
    render_report = dict(complete.get("render") or {})
    if repaired_artifacts and render_report.get("status") == "passed":
        render_report = _merge_artifact_reports(prior_build.get("render_report", {}), render_report)
        complete["render"] = render_report
    return complete, render_report


def _unaffected_build_is_valid(
    revision_dir: Path,
    build: Mapping[str, Any],
    repaired_artifacts: set[str],
) -> bool:
    """Prove every retained artifact still matches the build being merged."""
    for item in build.get("candidate_files", []):
        path = revision_dir / str(item.get("path"))
        if path.suffix.casefold() == ".docx" and path.stem in repaired_artifacts:
            continue
        if not path.is_file() or sha256_file(path) != item.get("sha256"):
            return False
    for artifact in build.get("render_report", {}).get("artifacts", []):
        if str(artifact.get("artifact")) in repaired_artifacts:
            continue
        for key in ("docx", "pdf"):
            path = revision_dir / str(artifact.get(key))
            if not path.is_file() or sha256_file(path) != artifact.get(f"{key}_sha256"):
                return False
        for page in artifact.get("pages", []):
            path = revision_dir / str(page.get("path"))
            if not path.is_file() or sha256_file(path) != page.get("sha256"):
                return False
    return True


def _candidate_outputs(revision_dir: Path) -> list[dict[str, Any]]:
    """Describe retained artifacts that have not passed the Delivery Gate."""
    return [
        {
            "path": path.relative_to(revision_dir).as_posix(),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
            "delivery_status": "internal_candidate",
        }
        for path in sorted((revision_dir / "candidate").glob("*"))
        if path.is_file()
    ]


def desktop_attachment_reply(manifest: Mapping[str, Any], *, run_dir: Path | None = None) -> dict[str, Any]:
    """Build the supported file-link payload for the final Desktop reply.

    The manifest is the only source for attachments.  In particular, this
    deliberately does not scan the run directory, which could expose drafts,
    QA evidence, or rendered previews.
    """
    outputs = manifest.get("client_outputs")
    if not isinstance(outputs, list) or not outputs:
        raise ValueError("A passing Generation Manifest must contain client outputs.")
    attachments = []
    for item in outputs:
        if not isinstance(item, Mapping):
            raise ValueError("Generation Manifest contains an invalid client output.")
        path = str(item.get("path") or "")
        filename = Path(path).name
        path_parts = Path(path).parts
        digest = str(item.get("sha256") or "")
        if (
            not path
            or Path(path).is_absolute()
            or ".." in path_parts
            or not filename
            or filename != path.rsplit("/", 1)[-1]
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest.lower())
            or int(item.get("bytes") or 0) < 1
        ):
            raise ValueError("Generation Manifest contains an invalid client output path.")
        absolute_path = (run_dir / path).resolve().as_posix() if run_dir is not None else path
        attachments.append({
            "filename": filename,
            "path": path,
            "absolute_path": absolute_path,
            "sha256": digest,
            "bytes": int(item.get("bytes") or 0),
            "mime_type": "application/xml" if filename.lower().endswith(".xml") else "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "link": f"[{filename}](<{absolute_path}>)",
        })
    return {
        "type": "desktop_file_attachments",
        "attachments": attachments,
        "client_outputs_only": True,
    }


def confirm_desktop_delivery(
    manifest: Mapping[str, Any],
    reply: Mapping[str, Any],
    opener: Callable[[str], bytes],
    *,
    deadline: float | None = None,
    retries: int = DESKTOP_DELIVERY_RETRIES,
    clock: Callable[[], float] | None = None,
) -> dict[str, Any]:
    """Retrieve and open every attachment, preserving the manifest bytes.

    ``opener`` is the actual Desktop media boundary: it must return the bytes
    obtained by opening the link, rather than merely echoing a path. Retries
    reuse the same validated attachment and never invoke generation again.
    """
    clock = clock or time.monotonic
    expected = desktop_attachment_reply(manifest)["attachments"]
    actual = reply.get("attachments") if isinstance(reply, Mapping) else None
    findings = []
    def identity(item: Mapping[str, Any]) -> tuple[Any, ...]:
        return tuple(item.get(key) for key in ("filename", "path", "sha256", "bytes"))

    if not isinstance(actual, list) or [identity(item) for item in actual if isinstance(item, Mapping)] != [identity(item) for item in expected]:
        findings.append(recovery_finding({"category": "delivery", "field": "attachments", "issue": "Desktop reply attachments do not match the immutable Generation Manifest."}, "transport_fault"))
    if findings:
        return {"status": "blocked", "confirmed": False, "findings": findings, "attempts": 0}
    opened = []
    total_attempts = 0
    for item, delivered in zip(expected, actual, strict=True):
        attempts = 0
        last_issue = ""
        opened_current = False
        while attempts <= retries:
            attempts += 1
            total_attempts += 1
            if deadline is not None and clock() >= deadline:
                last_issue = "Desktop delivery deadline expired."
                break
            try:
                payload = opener(str(delivered.get("absolute_path") or delivered["path"]))
                if not isinstance(payload, bytes):
                    raise TypeError("Desktop opener did not return bytes.")
                if deadline is not None and clock() >= deadline:
                    raise TimeoutError("Desktop delivery deadline expired before retrieval was confirmed.")
                digest = hashlib.sha256(payload).hexdigest()
                if len(payload) != int(item["bytes"]) or digest != item["sha256"]:
                    raise ValueError("Retrieved file bytes do not match the immutable Generation Manifest.")
                opened.append({"filename": item["filename"], "sha256": digest, "bytes": len(payload), "attempts": attempts})
                opened_current = True
                break
            except Exception as exc:  # transport failures are reported, never certified
                last_issue = str(exc)
        else:
            last_issue = last_issue or "Desktop file transfer failed."
        if not opened_current:
            findings.append(recovery_finding({"category": "delivery", "field": item["filename"], "issue": last_issue or "Desktop file transfer failed."}, "transport_fault"))
            break
    return {
        "status": "confirmed" if not findings else "blocked",
        "confirmed": not findings,
        "opened": opened,
        "attempts": total_attempts,
        "findings": findings,
    }


def _desktop_delivery_set_finding(
    run_dir: Path,
    manifest: Mapping[str, Any],
) -> dict[str, Any] | None:
    try:
        _, delivery_reference = _reference(run_dir)
    except FileNotFoundError:
        return None
    expected_outputs = set(document_set(get_path(delivery_reference, "meta.study_type")))
    actual_outputs = {
        Path(str(item.get("path") or "")).name
        for item in manifest.get("client_outputs", [])
        if isinstance(item, Mapping)
    }
    if manifest.get("status") == "passed" and actual_outputs == expected_outputs:
        return None
    return {
        "category": "delivery",
        "field": "client_outputs",
        "issue": f"Desktop delivery requires the exact Branch Document Set; expected={sorted(expected_outputs)}, actual={sorted(actual_outputs)}.",
    }


def _handoff_response_is_bound(
    run_dir: Path,
    revision_id: str,
    handoff: Mapping[str, Any],
) -> bool:
    revision_dir = run_dir / "revisions" / revision_id
    request_path = revision_dir / str(handoff.get("request_path") or "")
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        isinstance(request, Mapping)
        and request.get("request_id") == handoff.get("request_id")
        and request.get("request_sha256") == handoff.get("request_sha256")
        and request.get("response_path") == handoff.get("response_path")
        and request.get("task") == handoff.get("task")
        and verification_response_is_complete(revision_dir, request_path)
    )


def run_desktop_operation(
    run_dir: Path,
    *,
    handoff_runner: Callable[[list[Mapping[str, Any]], float], Any],
    fallback_handoff_runner: Callable[[list[Mapping[str, Any]], float], Any] | None = None,
    opener: Callable[[str], bytes],
    operation_id: str = "default",
    budget_seconds: float = DESKTOP_OPERATION_BUDGET_SECONDS,
    clock: Callable[[], float] | None = None,
    wall_clock: Callable[[], float] | None = None,
    runtime_identity: Mapping[str, Any] | None = None,
    release_identity: Mapping[str, Any] | None = None,
    progress: Callable[[str, float], Any] | None = None,
    cleanup: Callable[[str, float], Mapping[str, Any] | None] | None = None,
    stage_soft_budgets: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Run the post-approval lifecycle and confirm its Desktop file delivery.

    Hermes owns the ``handoff_runner`` boundary and Desktop owns ``opener``;
    this function only routes path metadata, advances the public workflow, and
    validates the immutable delivery manifest. The persisted deadline uses a
    UTC epoch so another process or compatible runtime cannot reset it.
    Monotonic time is converted to that epoch only within this process.
    """
    run_dir = run_dir.resolve()
    clock = clock or time.monotonic
    wall_clock = wall_clock or time.time
    if budget_seconds <= 0:
        raise ValueError("Desktop operation budget must be positive.")
    current_runtime = dict(runtime_identity or _current_python_runtime())
    if _runtime_version(current_runtime) < (*MINIMUM_PYTHON_VERSION, 0):
        raise RuntimeError("The Desktop operation requires an explicitly resolved Python 3.10+ runtime.")
    current_release_identity = dict(release_identity or _active_release_identity(SCRIPT_DIR.parent))
    if not str(current_release_identity.get("package_fingerprint") or ""):
        raise ValueError("Desktop operation release identity requires a package fingerprint.")
    try:
        _, operation_reference = _reference(run_dir)
    except FileNotFoundError:
        operation_reference = {}
    operation_approval = operation_reference.get("approval") or {}
    current_approval_identity = (
        {
            key: operation_approval.get(key)
            for key in (
                "status", "approved_by", "approved_at", "revision_id", "source_sha256",
                "approved_reference_sha256", "governing_sha256",
            )
        }
        if operation_approval
        else None
    )
    soft_budgets = {
        str(stage): float(seconds)
        for stage, seconds in (DESKTOP_STAGE_SOFT_BUDGETS if stage_soft_budgets is None else stage_soft_budgets).items()
        if float(seconds) > 0
    }
    process_monotonic_anchor = clock()
    process_epoch_anchor = wall_clock()

    def epoch_now() -> float:
        return process_epoch_anchor + max(0.0, clock() - process_monotonic_anchor)

    state_path = desktop_operation_state_path(run_dir, operation_id)
    try:
        persisted = _read(state_path) if state_path.is_file() else {}
    except (OSError, ValueError, json.JSONDecodeError):
        persisted = {
            "operation_id": operation_id,
            "budget_seconds": budget_seconds,
            "status": "unreadable",
        }
    if persisted.get("operation_id") not in {None, operation_id}:
        raise ValueError("Desktop operation state belongs to a different operation.")
    recorded_release_identity = persisted.get("release_identity")
    if isinstance(recorded_release_identity, Mapping) and dict(recorded_release_identity) != current_release_identity:
        return {
            "status": "blocked",
            "stage": "release_identity",
            "findings": [{
                "category": "release",
                "field": "release_identity",
                "issue": "Desktop operation evidence belongs to a different Promoted Release or governed configuration identity.",
            }],
            "client_outputs": [],
        }
    recorded_approval_identity = persisted.get("approval_identity")
    if isinstance(recorded_approval_identity, Mapping) and dict(recorded_approval_identity) != current_approval_identity:
        return {
            "status": "blocked",
            "stage": "approval_identity",
            "findings": [{
                "category": "approval",
                "field": "approval_identity",
                "issue": "Desktop operation evidence belongs to a different approved immutable revision.",
            }],
            "client_outputs": [],
        }

    terminal = persisted.get("status") in {"passed", "blocked", "timeout"}
    if terminal and isinstance(persisted.get("result"), Mapping):
        prior_result = dict(persisted["result"])
        recorded_bundle = prior_result.get("contracted_template_bundle")
        requires_bundle_validation = prior_result.get("status") == "passed"
        if requires_bundle_validation and not (
            isinstance(recorded_bundle, Mapping)
            and recorded_bundle.get("identity_sha256")
        ):
            return {
                "status": "blocked",
                "stage": "contracted_template_bundle",
                "findings": [{"category": "contract", "field": "contracted_template_bundle", "issue": "Persisted passing Desktop evidence lacks a complete Contracted Template Bundle identity."}],
                "client_outputs": [],
            }
        if requires_bundle_validation:
            try:
                _, current_reference = _reference(run_dir)
                current_bundle = contracted_template_bundle(SCRIPT_DIR.parent, current_reference)
            except (ContractedTemplateBundleError, OSError, ValueError, json.JSONDecodeError) as exc:
                return {
                    "status": "blocked",
                    "stage": "contracted_template_bundle",
                    "findings": [{"category": "contract", "field": "contracted_template_bundle", "issue": f"Persisted Desktop evidence cannot be validated against the current governed bundle: {exc}"}],
                    "client_outputs": [],
                }
            if current_bundle.get("identity_sha256") != recorded_bundle.get("identity_sha256"):
                return {
                    "status": "blocked",
                    "stage": "contracted_template_bundle",
                    "findings": [{"category": "contract", "field": "contracted_template_bundle", "issue": "Persisted Desktop delivery evidence belongs to a stale Contracted Template Bundle."}],
                    "client_outputs": [],
                }
        if requires_bundle_validation and not (
            isinstance(recorded_release_identity, Mapping)
            and recorded_release_identity.get("package_fingerprint")
        ):
            return {
                "status": "blocked",
                "stage": "release_identity",
                "findings": [{
                    "category": "release",
                    "field": "package_fingerprint",
                    "issue": "Persisted passing Desktop evidence lacks a Promoted Release fingerprint.",
                }],
                "client_outputs": [],
            }
        if requires_bundle_validation:
            manifest_name = str(prior_result.get("manifest") or "")
            manifest_path = (run_dir / manifest_name).resolve()
            try:
                manifest_path.relative_to(run_dir)
                manifest = _read(manifest_path)
                set_finding = _desktop_delivery_set_finding(run_dir, manifest)
                if set_finding is not None:
                    raise ValueError(set_finding["issue"])
                reply = prior_result.get("desktop_reply") or desktop_attachment_reply(manifest, run_dir=run_dir)
                delivery = confirm_desktop_delivery(manifest, reply, opener)
                if not delivery.get("confirmed"):
                    issue = str((delivery.get("findings") or [{}])[0].get("issue") or "Terminal delivery could not be reconfirmed.")
                    raise ValueError(issue)
            except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
                return {
                    "status": "blocked",
                    "stage": "terminal_delivery_validation",
                    "findings": [{
                        "category": "delivery",
                        "field": "terminal_result",
                        "issue": f"Persisted Desktop success no longer has accessible hash-matching outputs: {exc}",
                    }],
                    "client_outputs": [],
                }
        return prior_result
    started_at_epoch, deadline_at_epoch, persisted_budget, runtime_history, stage_history = (
        _desktop_deadline_state(
            persisted,
            budget_seconds=budget_seconds,
            epoch_now=epoch_now(),
        )
    )
    if isinstance(persisted.get("soft_budgets"), Mapping):
        soft_budgets = {
            str(stage): float(seconds)
            for stage, seconds in persisted["soft_budgets"].items()
            if float(seconds) > 0
        }
    current_stage = str(persisted.get("stage") or "approved")
    raw_attempt_counters = persisted.get("attempt_counters")
    if not isinstance(raw_attempt_counters, Mapping):
        raw_attempt_counters = {}
    attempt_counters = {
        "drafting": dict(raw_attempt_counters.get("drafting") or {}),
        "verification": dict(raw_attempt_counters.get("verification") or {}),
        "generation": dict(raw_attempt_counters.get("generation") or {}),
        "handoff_dispatches": dict(raw_attempt_counters.get("handoff_dispatches") or {}),
        "delivery": int(raw_attempt_counters.get("delivery") or 0),
    }
    raw_stage_timings = persisted.get("stage_timings")
    if not isinstance(raw_stage_timings, Mapping):
        raw_stage_timings = {}
    stage_timings = {
        str(stage): dict(timing)
        for stage, timing in raw_stage_timings.items()
        if isinstance(timing, Mapping)
    }
    raw_soft_budget_events = persisted.get("soft_budget_events")
    if not isinstance(raw_soft_budget_events, list):
        raw_soft_budget_events = []
    soft_budget_events = [
        dict(item)
        for item in raw_soft_budget_events
        if isinstance(item, Mapping)
    ]
    raw_cleanup = persisted.get("cleanup")
    cleanup_evidence = dict(raw_cleanup) if isinstance(raw_cleanup, Mapping) else {}
    raw_pending_handoffs = persisted.get("pending_handoffs")
    if not isinstance(raw_pending_handoffs, list):
        raw_pending_handoffs = []
    pending_handoffs = [
        dict(item)
        for item in raw_pending_handoffs
        if isinstance(item, Mapping)
    ]
    last_result: dict[str, Any] = {}
    process_deadline_monotonic = process_monotonic_anchor + max(0.0, deadline_at_epoch - process_epoch_anchor)

    def runtime_key(item: Mapping[str, Any]) -> tuple[Any, ...]:
        return tuple(item.get(key) for key in ("executable", "implementation", "version"))

    if not runtime_history or runtime_key(runtime_history[-1]) != runtime_key(current_runtime):
        runtime_history.append(current_runtime)

    def remaining_seconds() -> float:
        return deadline_at_epoch - epoch_now()

    def save(status: str, result: Mapping[str, Any] | None = None) -> dict[str, Any]:
        payload = {
            "operation_id": operation_id,
            "started_at_epoch": started_at_epoch,
            "deadline_at_epoch": deadline_at_epoch,
            "started_at": datetime.fromtimestamp(started_at_epoch, timezone.utc).isoformat(),
            "deadline_at": datetime.fromtimestamp(deadline_at_epoch, timezone.utc).isoformat(),
            "budget_seconds": persisted_budget,
            "runtime": current_runtime,
            "runtime_history": runtime_history,
            "release_identity": current_release_identity,
            "approval_identity": current_approval_identity,
            "status": status,
            "stage": current_stage,
            "stage_history": stage_history,
            "stage_timings": stage_timings,
            "attempt_counters": attempt_counters,
            "pending_handoffs": pending_handoffs,
            "soft_budgets": soft_budgets,
            "soft_budget_events": soft_budget_events,
        }
        if cleanup_evidence:
            payload["cleanup"] = cleanup_evidence
        if result is not None:
            payload["result"] = dict(result)
        _write(state_path, payload)
        return dict(result or payload)

    def finish(result: Mapping[str, Any]) -> dict[str, Any]:
        nonlocal current_stage, cleanup_evidence
        current_stage = str(result.get("pending_stage") or result.get("stage") or current_stage)
        elapsed = max(0.0, epoch_now() - started_at_epoch)
        measured = {
            **result,
            "elapsed_seconds": round(elapsed, 3),
            "performance_classification": performance_classification(elapsed),
            "target_window_seconds": [
                NORMAL_RUNTIME_TARGET_MIN_SECONDS,
                NORMAL_RUNTIME_TARGET_MAX_SECONDS,
            ],
            "operation_deadline_seconds": DESKTOP_OPERATION_BUDGET_SECONDS,
            "started_at_epoch": started_at_epoch,
            "deadline_at_epoch": deadline_at_epoch,
            "runtime": current_runtime,
            "release_identity": current_release_identity,
        }
        if cleanup is not None and not cleanup_evidence:
            cleanup_evidence = dict(cleanup(str(measured.get("status", "blocked")), max(0.0, remaining_seconds())) or {})
        return save(str(measured.get("status", "blocked")), measured)

    def record_timing(stage: str, elapsed: float) -> None:
        timing = stage_timings.setdefault(stage, {"elapsed_seconds": 0.0, "invocations": 0})
        timing["elapsed_seconds"] = round(float(timing.get("elapsed_seconds") or 0.0) + max(0.0, elapsed), 3)
        timing["invocations"] = int(timing.get("invocations") or 0) + 1

    def record_soft_budget_event(stage: str) -> None:
        elapsed = float(stage_timings.get(stage, {}).get("elapsed_seconds") or 0.0)
        if (
            stage in soft_budgets
            and elapsed >= soft_budgets[stage]
            and not any(item.get("stage") == stage for item in soft_budget_events)
        ):
            soft_budget_events.append({
                "stage": stage,
                "budget_seconds": soft_budgets[stage],
                "elapsed_seconds": round(elapsed, 3),
                "action": "early_parent_fallback" if stage == "independent_verification" else "record_diagnostic",
            })

    def refresh_generation_attempts() -> None:
        try:
            _, operation_reference = _reference(run_dir)
        except (OSError, ValueError, json.JSONDecodeError):
            return
        generation = operation_reference.get("generation")
        if not isinstance(generation, Mapping):
            return
        attempt_counters["generation"] = {
            str(target): int(attempt)
            for target, attempt in dict(generation.get("attempts") or {}).items()
        }
        attempt_counters["verification"].update({
            str(target): int(attempt)
            for target, attempt in dict(generation.get("verification_attempts") or {}).items()
        })

    # Persist before any operation work can be interrupted; otherwise a restart
    # could create a fresh correctness budget.
    save("running")
    while True:
        remaining = remaining_seconds()
        if remaining <= 0:
            retained = [
                dict(item)
                for item in last_result.get("candidate_outputs", [])
                if isinstance(item, Mapping)
            ]
            try:
                _, current_reference = _reference(run_dir)
                current_revision = str(current_reference.get("approval", {}).get("revision_id") or "")
                if current_revision and not retained:
                    retained = _candidate_outputs(run_dir / "revisions" / current_revision)
            except (OSError, ValueError, json.JSONDecodeError):
                pass
            return finish({
                "status": "timeout",
                "stage": "desktop_operation",
                "pending_stage": current_stage if current_stage != "approved" else "generate",
                "deadline_at_epoch": deadline_at_epoch,
                "findings": [{"category": "timeout", "field": "operation", "issue": "The post-approval Desktop operation deadline expired."}],
                "candidate_outputs": retained,
                "pending_result": last_result,
                "client_outputs": [],
            })
        generate_started = clock()
        observed_stages: set[str] = set()

        def observe_generate_stage(stage: str, elapsed: float) -> None:
            observed_stages.add(stage)
            record_timing(stage, elapsed)
            record_soft_budget_event(stage)

        try:
            result = generate(
                run_dir,
                operation_deadline=process_deadline_monotonic,
                clock=clock,
                stage_observer=observe_generate_stage,
            )
        finally:
            generate_elapsed = clock() - generate_started
            record_timing("generate", generate_elapsed)
            refresh_generation_attempts()
            save("running")
        last_result = dict(result)
        stage = str(result.get("stage") or "generate")
        current_stage = stage
        if stage not in observed_stages:
            # An awaiting result names the next stage; no time has been spent
            # waiting on that handoff yet. Upstream generation is tracked by
            # its observer callbacks and must not consume the next soft budget.
            stage_elapsed = 0.0 if result.get("status") == "awaiting_hermes" else generate_elapsed
            record_timing(stage, stage_elapsed)
            record_soft_budget_event(stage)
        if remaining_seconds() <= 0:
            continue
        stage_history.append({"stage": stage, "status": result.get("status"), "remaining_seconds": round(remaining, 3)})
        save("running")
        if progress is not None:
            progress(stage, max(0.0, remaining_seconds()))
        if result.get("status") == "awaiting_hermes":
            handoffs = result.get("handoffs")
            if not isinstance(handoffs, list) or not handoffs:
                return finish({**result, "status": "blocked", "stage": "hermes_handoff", "client_outputs": []})
            current_handoffs = [dict(item) for item in handoffs if isinstance(item, Mapping)]
            prior_by_response = {
                str(item.get("response_path") or ""): item
                for item in pending_handoffs
            }
            def handoff_identity(item: Mapping[str, Any]) -> tuple[Any, ...]:
                return tuple(item.get(key) for key in (
                    "request_id", "request_sha256", "request_path", "response_path", "task", "attempts",
                ))

            for handoff in current_handoffs:
                prior = prior_by_response.get(str(handoff.get("response_path") or ""))
                if prior is not None and handoff_identity(prior) != handoff_identity(handoff):
                    return finish({
                        "status": "blocked",
                        "stage": "hermes_handoff_integrity",
                        "findings": [{
                            "category": "hermes",
                            "field": str(handoff.get("request_path") or "handoff"),
                            "issue": "A missing worker response was replaced by a changed request instead of redispatching the exact original request.",
                        }],
                        "client_outputs": [],
                    })
            handoffs = [
                prior_by_response.get(str(item.get("response_path") or ""), item)
                for item in current_handoffs
            ]
            pending_handoffs = [dict(item) for item in handoffs]
            save("running")
            remaining = remaining_seconds()
            if remaining <= 0:
                continue
            try:
                for handoff in handoffs:
                    if not isinstance(handoff, Mapping):
                        continue
                    counter_name = "verification" if str(handoff.get("task") or "").endswith("verification") else "drafting"
                    for target, attempt in dict(handoff.get("attempts") or {}).items():
                        attempt_counters[counter_name][str(target)] = max(
                            int(attempt_counters[counter_name].get(str(target)) or 0),
                            int(attempt),
                        )
                    dispatch_key = str(handoff.get("request_sha256") or handoff.get("request_id") or handoff.get("request_path") or "")
                    if dispatch_key:
                        attempt_counters["handoff_dispatches"][dispatch_key] = int(
                            attempt_counters["handoff_dispatches"].get(dispatch_key) or 0
                        ) + 1
                handoff_started = clock()
                stage_elapsed = float(stage_timings.get(stage, {}).get("elapsed_seconds") or 0.0)
                soft_remaining = max(0.0, soft_budgets.get(stage, remaining) - stage_elapsed)
                supports_parent_fallback = (
                    stage == "independent_verification"
                    and any(item.get("fallback_owner") == "parent" for item in handoffs)
                )
                runner_timeout = min(remaining, soft_remaining) if supports_parent_fallback else remaining
                save("running")
                try:
                    handoff_runner(handoffs, runner_timeout)
                finally:
                    record_timing(stage, clock() - handoff_started)
                    record_soft_budget_event(stage)
                    save("running")
                revision_id = str(result.get("revision_id") or "")
                fallback_handoffs = [
                    item for item in handoffs
                    if item.get("fallback_owner") == "parent"
                    and revision_id
                    and not _handoff_response_is_bound(run_dir, revision_id, item)
                ]
                if fallback_handoffs:
                    remaining = remaining_seconds()
                    if remaining > 0:
                        if fallback_handoff_runner is not None:
                            fallback_handoff_runner(fallback_handoffs, remaining)
                        else:
                            parent_handoffs = [{**item, "reviewer_owner": "parent"} for item in fallback_handoffs]
                            handoff_runner(parent_handoffs, remaining)
            except Exception as exc:
                revision_id = str(result.get("revision_id") or "")
                fallback_handoffs = [
                    item for item in handoffs
                    if item.get("fallback_owner") == "parent"
                    and revision_id
                    and not _handoff_response_is_bound(run_dir, revision_id, item)
                ]
                if fallback_handoffs:
                    remaining = remaining_seconds()
                    if remaining > 0:
                        try:
                            if fallback_handoff_runner is not None:
                                fallback_handoff_runner(fallback_handoffs, remaining)
                            else:
                                parent_handoffs = [{**item, "reviewer_owner": "parent"} for item in fallback_handoffs]
                                handoff_runner(parent_handoffs, remaining)
                        except Exception as fallback_exc:
                            exc = RuntimeError(f"Delegated reviewer failed ({exc}); parent reviewer fallback failed ({fallback_exc})")
                        else:
                            continue
                return finish({
                    "status": "blocked",
                    "stage": "hermes_handoff",
                    "findings": [{"category": "hermes", "field": "handoff", "issue": str(exc)}],
                    "client_outputs": [],
                })
            continue
        pending_handoffs = []
        if result.get("status") != "passed":
            return finish(result)
        if remaining_seconds() <= 0:
            continue
        manifest_name = str(result.get("manifest") or "")
        manifest_path = (run_dir / manifest_name).resolve()
        try:
            manifest_path.relative_to(run_dir)
            manifest = _read(manifest_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return finish({
                "status": "blocked",
                "stage": "desktop_delivery",
                "findings": [{"category": "delivery", "field": "manifest", "issue": str(exc)}],
                "client_outputs": [],
            })
        if set_finding := _desktop_delivery_set_finding(run_dir, manifest):
            return finish({
                "status": "blocked",
                "stage": "desktop_delivery_set",
                "findings": [set_finding],
                "client_outputs": [],
            })
        reply = result.get("desktop_reply") or desktop_attachment_reply(manifest, run_dir=run_dir)
        delivery = confirm_desktop_delivery(
            manifest,
            reply,
            opener,
            deadline=process_deadline_monotonic,
            clock=clock,
        )
        attempt_counters["delivery"] = int(delivery.get("attempts") or 0)
        if remaining_seconds() <= 0:
            current_stage = "desktop_delivery"
            last_result = {
                **result,
                "stage": "desktop_delivery",
                "delivery": delivery,
                "candidate_outputs": _candidate_outputs(
                    run_dir / "revisions" / str(result.get("revision_id") or "")
                ) if result.get("revision_id") else [],
                "client_outputs": [],
            }
            continue
        final = {
            **result,
            "status": "passed" if delivery["confirmed"] else "blocked",
            "stage": "desktop_delivery",
            "delivery": delivery,
            "deadline_at_epoch": deadline_at_epoch,
        }
        if not delivery["confirmed"]:
            final["client_outputs"] = []
        return finish(final)


def _drafting_evidence(revision_dir: Path) -> list[dict[str, Any]]:
    evidence = []
    for path in sorted((revision_dir / "hermes/accepted").glob("*.json")):
        item = _read(path)
        request_id = str(item.get("request_id") or "")
        accepted_request = revision_dir / "hermes/accepted-requests" / f"{request_id}.json"
        evidence.append({
            "path": path.relative_to(revision_dir).as_posix(),
            "sha256": sha256_file(path),
            "request_id": request_id,
            "request_sha256": item.get("request_sha256"),
            "accepted_request_path": accepted_request.relative_to(revision_dir).as_posix() if accepted_request.is_file() else None,
            "accepted_request_file_sha256": sha256_file(accepted_request) if accepted_request.is_file() else None,
            "producer": item.get("producer"),
        })
    return evidence


def _publish(
    run_dir: Path,
    revision_dir: Path,
    reference: Mapping[str, Any],
    quality: Mapping[str, Any],
    *,
    operation_deadline: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    sources = sorted((revision_dir / "candidate").glob("*.docx")) + sorted((revision_dir / "candidate").glob("*.xml"))
    expected = set(document_set(get_path(reference, "meta.study_type")))
    actual = {source.name for source in sources}
    if actual != expected:
        raise RuntimeError(f"Atomic publication requires the exact branch document set; expected={sorted(expected)}, actual={sorted(actual)}")
    output = run_dir / "output"
    staging = Path(tempfile.mkdtemp(prefix=".output-staging-", dir=run_dir))
    backup: Path | None = None
    try:
        if operation_deadline is not None and clock() >= operation_deadline:
            raise OperationDeadlineExpired("The Desktop operation expired before publication.")
        for source in sources:
            shutil.copy2(source, staging / source.name)
        # The only client-visible mutation is the atomic swap below. Recheck
        # after staging so slow copies cannot publish after the hard ceiling.
        if operation_deadline is not None and clock() >= operation_deadline:
            raise OperationDeadlineExpired("The Desktop operation expired while staging publication.")
        if output.exists():
            backup = Path(tempfile.mkdtemp(prefix=".output-backup-", dir=run_dir))
            backup.rmdir()
            os.replace(output, backup)
        try:
            os.replace(staging, output)
        except Exception:
            if backup is not None and backup.exists() and not output.exists():
                os.replace(backup, output)
            raise
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    if backup is not None and backup.exists():
        shutil.rmtree(backup)
    published = [
        {"path": (output / source.name).relative_to(run_dir).as_posix(), "sha256": quality_sha256(output / source.name), "bytes": (output / source.name).stat().st_size}
        for source in sources
    ]
    build_path = revision_dir / "candidate-build.json"
    build = _read(build_path) if build_path.is_file() else {}
    manifest = {"status": "passed", "revision_id": revision_dir.name, "study_type": canonical_study_type(reference.get("meta", {}).get("study_type")), "approved_source_sha256": reference.get("approval", {}).get("source_sha256"), "approved_reference_sha256": sha256_file(revision_dir / "approved-reference.json"), "candidate_build_sha256": sha256_file(build_path) if build_path.is_file() else None, "contracted_template_bundle": build.get("contracted_template_bundle", {}), "governing_resources": build.get("governing_resources", {}), "drafting_evidence": _drafting_evidence(revision_dir), "quality": quality, "client_outputs": published}
    manifest["desktop_reply"] = desktop_attachment_reply(manifest, run_dir=run_dir)
    _write(revision_dir / "delivery-manifest.json", manifest); _write(run_dir / "logs/generation-report.json", manifest)
    return {"status": "passed", "stage": "delivery", "revision_id": revision_dir.name, "contracted_template_bundle": manifest["contracted_template_bundle"], "client_outputs": [item["path"] for item in published], "desktop_reply": manifest["desktop_reply"], "delivery_status": "prepared_unconfirmed", "manifest": (revision_dir / "delivery-manifest.json").relative_to(run_dir).as_posix()}


def _clear_verification_responses(revision_dir: Path, tasks: set[str] | None = None) -> None:
    for request_path in (revision_dir / "hermes/verification-requests").glob("*.json"):
        try:
            request = _read(request_path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if tasks is None or str(request.get("task")) in tasks:
            (revision_dir / str(request.get("response_path", ""))).unlink(missing_ok=True)


def _normalized_layout_repair_records(repairs: Iterable[Mapping[str, Any]]) -> list[dict[str, str]]:
    normalized: dict[tuple[str, str], dict[str, str]] = {}
    for repair in repairs:
        if not isinstance(repair, Mapping):
            continue
        rule = str(repair.get("rule") or "").strip()
        target = " ".join(str(repair.get("target") or "").split())
        if rule and target:
            normalized[(rule, target)] = {"rule": rule, "target": target}
    return [normalized[key] for key in sorted(normalized)]


def _layout_repair_plan(findings: Iterable[Mapping[str, Any]]) -> tuple[dict[str, list[dict[str, str]]], list[dict[str, Any]]]:
    plan: dict[str, list[dict[str, str]]] = {}
    unsupported: list[dict[str, Any]] = []
    for raw in findings:
        finding = dict(raw)
        parsed_targets = [RetryTarget.parse(str(target)) for target in finding.get("target_ids", [])]
        layout_targets = [target.value for target in parsed_targets if target.category == "layout"]
        if not layout_targets:
            continue
        artifact = str(finding.get("artifact") or layout_targets[0]).removesuffix(".docx")
        check = str(finding.get("check") or "")
        target = " ".join(str(finding.get("element") or "").split())
        rule = LAYOUT_RULE_BY_VISUAL_CHECK.get(check)
        if rule not in LAYOUT_REPAIR_RULES.get(artifact, ()) or not target:
            unsupported.append({
                **finding,
                "required": "Classify the visual defect with one supported artifact, Layout Contract check, and exact heading or table-caption element before deterministic repair.",
            })
            continue
        plan.setdefault(artifact, []).append({"rule": rule, "target": target})
    plan = {
        artifact: _normalized_layout_repair_records(repairs)
        for artifact, repairs in plan.items()
    }
    return plan, unsupported


def _invalidate_layout_artifact(revision_dir: Path, artifact: str) -> None:
    """Invalidate only one DOCX and its exact rendered-page review evidence."""
    (revision_dir / "candidate" / f"{artifact}.docx").unlink(missing_ok=True)
    (revision_dir / "rendered" / f"{artifact}.pdf").unlink(missing_ok=True)
    shutil.rmtree(revision_dir / "rendered" / artifact, ignore_errors=True)
    for request_path in (revision_dir / "hermes/verification-requests").glob("*.json"):
        try:
            request = _read(request_path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if request.get("task") != "rendered_page_visual_verification":
            continue
        artifacts = request.get("artifacts") if isinstance(request.get("artifacts"), list) else []
        if not any(str(item.get("artifact")) == artifact for item in artifacts if isinstance(item, Mapping)):
            continue
        (revision_dir / str(request.get("response_path", ""))).unlink(missing_ok=True)
        request_path.unlink(missing_ok=True)


def _archive_failed_attempt(revision_dir: Path, stage: str, findings: list[Mapping[str, Any]]) -> Path:
    """Preserve the complete failed candidate and QA evidence before any retry mutation."""
    archive_root = revision_dir / "attempts"
    archive_root.mkdir(parents=True, exist_ok=True)
    safe_stage = _slug(stage)
    sequence = 1
    while (archive_root / f"{safe_stage}-a{sequence:02d}").exists():
        sequence += 1
    destination = archive_root / f"{safe_stage}-a{sequence:02d}"
    destination.mkdir()
    retained = (
        Path("candidate"),
        Path("rendered"),
        Path("candidate-build.json"),
        Path("hermes/accepted"),
        Path("hermes/accepted-requests"),
        Path("hermes/verification-requests"),
        Path("hermes/verification-responses"),
    )
    for relative in retained:
        source = revision_dir / relative
        target = destination / relative
        if source.is_dir():
            shutil.copytree(source, target)
        elif source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    files = {
        path.relative_to(destination).as_posix(): sha256_file(path)
        for path in sorted(destination.rglob("*"))
        if path.is_file()
    }
    _write(destination / "attempt-manifest.json", {
        "revision_id": revision_dir.name,
        "stage": stage,
        "attempt": sequence,
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "findings": [dict(item) for item in findings],
        "files": files,
    })
    return destination


def _quality_retry(
    run_dir: Path,
    reference_path: Path,
    working_reference: dict[str, Any],
    approved_reference: Mapping[str, Any],
    revision_dir: Path,
    prior_attempts: Mapping[str, int],
    findings: list[Mapping[str, Any]],
    stage: str,
    *,
    contracted_bundle: Mapping[str, Any] | None = None,
    operation_deadline: float | None = None,
    clock: Callable[[], float] = time.monotonic,
    stage_observer: Callable[[str, float], Any] | None = None,
) -> dict[str, Any]:
    """Retry draftable targets; deterministic layout defects require an actual repair."""
    invalid_recovery = [
        {
            "category": "recovery-classification",
            "field": "recovery_class",
            "issue": "Every recoverable finding must carry one governed Recovery Class and its lawful action.",
            "finding": dict(item),
        }
        for item in findings
        if item.get("recovery_class") not in RECOVERY_POLICIES
        or item.get("action") != RECOVERY_POLICIES.get(str(item.get("recovery_class")))
    ]
    if invalid_recovery:
        return _repair_block(
            run_dir,
            "recovery_classification",
            invalid_recovery,
            candidate_outputs=_candidate_outputs(revision_dir),
        )
    structural = [item for item in findings if item.get("recovery_class") == "document_structure_defect"]
    if structural:
        return _repair_block(
            run_dir,
            "document_structure",
            structural,
            candidate_outputs=_candidate_outputs(revision_dir),
        )
    expected_target_category = {
        "visual_defect": "layout",
        "drafting_defect": "section",
        "verifier_transient": "verification",
    }
    explicit_route_errors = [
        {
            "category": "recovery-classification",
            "field": "target_ids",
            "issue": f"Recovery Class {item.get('recovery_class')} requires {expected} targets.",
            "finding": dict(item),
        }
        for item in findings
        if (expected := expected_target_category.get(str(item.get("recovery_class")))) is not None
        and isinstance(item.get("target_ids"), list)
        and item.get("target_ids")
        and any(RetryTarget.parse(str(target)).category != expected for target in item["target_ids"])
    ]
    if explicit_route_errors:
        return _repair_block(
            run_dir,
            "recovery_classification",
            explicit_route_errors,
            candidate_outputs=_candidate_outputs(revision_dir),
        )
    _archive_failed_attempt(revision_dir, stage, findings)
    transient = [item for item in findings if item.get("recovery_class") == "verifier_transient"]
    if transient:
        verification_attempts = working_reference.setdefault("generation", {}).setdefault("verification_attempts", {})
        exhausted = []
        tasks = set()
        for item in transient:
            target = str((item.get("target_ids") or [item.get("field")])[0])
            next_attempt = int(verification_attempts.get(target, 0)) + 1
            verification_attempts[target] = next_attempt
            retry_target = RetryTarget.parse(target)
            task = VERIFICATION_TASK_BY_TARGET.get(retry_target.value) if retry_target.category == "verification" else None
            if task:
                tasks.add(task)
            if next_attempt > MAX_VERIFICATION_ATTEMPTS:
                exhausted.append({
                    **dict(item),
                    "field": target,
                    "issue": f"Reviewer retry limit reached after {MAX_VERIFICATION_ATTEMPTS} attempts. {item.get('issue', '')}".strip(),
                })
        _write(reference_path, working_reference)
        if exhausted:
            path = run_dir / "reference/repair-report.md"
            path.write_text(repair_report(exhausted), encoding="utf-8")
            return {"status": "blocked", "stage": "reviewer_retry_limit", "findings": exhausted, "repair_report": path.relative_to(run_dir).as_posix(), "client_outputs": []}
        _clear_verification_responses(revision_dir, tasks)
        remaining = [item for item in findings if item.get("recovery_class") != "verifier_transient"]
        if not remaining:
            return _awaiting(
                revision_dir,
                stage="independent_verification_retry",
                paths=sorted((revision_dir / "hermes/verification-requests").glob("*.json")),
                findings=transient,
            )
        findings = remaining
    known_sections = {section.section_id for section in protocol_contract(str(get_path(approved_reference, "meta.study_type", "")))}
    if canonical_study_type(get_path(approved_reference, "meta.study_type")) != "Retrospective":
        known_sections.update(section.section_id for section in icf_contract(
            str(get_path(approved_reference, "meta.study_type", "")),
            str(get_path(approved_reference, "meta.icf_template", "Advarra")),
        ))
        known_sections.update(("prs.brief-summary", "prs.detailed-description"))
    draftable_sections = {
        section_id
        for batch in batch_plan(
            str(get_path(approved_reference, "meta.study_type", "")),
            str(get_path(approved_reference, "meta.icf_template", "Advarra")),
        )
        for section_id in batch.section_ids
    }
    normalized: list[dict[str, Any]] = []
    for raw in findings:
        finding = dict(raw)
        targets = [str(item) for item in finding.get("target_ids", []) if item] if isinstance(finding.get("target_ids"), list) else []
        if not targets:
            field = str(finding.get("field") or "")
            if field in known_sections:
                targets = [field]
            elif finding.get("recovery_class") == "visual_defect":
                targets = [f"layout:{finding.get('artifact') or 'documents'}"]
            elif finding.get("recovery_class") == "verifier_transient":
                targets = ["verification:content"]
            else:
                targets = ["layout:documents"]
        finding["target_ids"] = targets
        normalized.append(finding)
    targets = {RetryTarget.parse(target) for finding in normalized for target in finding["target_ids"]}
    route_errors = [
        {
            "category": "recovery-classification",
            "field": "target_ids",
            "issue": f"Recovery Class {finding.get('recovery_class')} requires {expected} targets.",
            "finding": finding,
        }
        for finding in normalized
        if (expected := expected_target_category.get(str(finding.get("recovery_class")))) is not None
        and any(RetryTarget.parse(str(target)).category != expected for target in finding["target_ids"])
    ]
    if route_errors:
        return _repair_block(
            run_dir,
            "recovery_classification",
            route_errors,
            candidate_outputs=_candidate_outputs(revision_dir),
        )
    section_targets = {
        target.target_id
        for target in targets
        if target.category == "section" and target.target_id in draftable_sections
    }
    deterministic_targets = {
        target.target_id
        for target in targets
        if target.category == "section"
        and target.target_id in known_sections
        and target.target_id not in draftable_sections
    }
    has_layout_target = any(target.category == "layout" for target in targets)
    if deterministic_targets and not section_targets:
        path = run_dir / "reference/repair-report.md"
        path.write_text(repair_report(normalized), encoding="utf-8")
        return {
            "status": "blocked",
            "stage": "deterministic_repair",
            "findings": normalized,
            "repair_report": path.relative_to(run_dir).as_posix(),
            "client_outputs": [],
        }
    attempts, exhausted = retry_attempts(normalized, prior_attempts)
    working_reference.setdefault("generation", {})["attempts"] = attempts
    _write(reference_path, working_reference)
    if exhausted:
        path = run_dir / "reference/repair-report.md"; path.write_text(repair_report(exhausted), encoding="utf-8")
        return {"status": "blocked", "stage": stage, "findings": exhausted, "repair_report": path.relative_to(run_dir).as_posix(), "client_outputs": []}
    if section_targets:
        invalidate_accepted_targets(revision_dir, section_targets)
        (revision_dir / "candidate-build.json").unlink(missing_ok=True)
        _clear_verification_responses(revision_dir)
        created = schedule_requests(repo_root=SCRIPT_DIR.parent, revision_dir=revision_dir, revision_id=revision_dir.name, reference=approved_reference, attempts=attempts, wave="quality-retry", findings=normalized, contracted_bundle=contracted_bundle)
        if created:
            return _awaiting(revision_dir, stage="drafting_retry", paths=created, findings=normalized)
    if has_layout_target:
        generation = working_reference.setdefault("generation", {})
        repair_plan, unsupported = _layout_repair_plan(normalized)
        if unsupported:
            return _repair_block(
                run_dir,
                "layout_repair_classification",
                unsupported,
                candidate_outputs=_candidate_outputs(revision_dir),
            )
        persisted_repairs = generation.setdefault("layout_repairs", {})
        for artifact, repairs in repair_plan.items():
            existing = persisted_repairs.get(artifact, ())
            persisted_repairs[artifact] = _normalized_layout_repair_records([*existing, *repairs])
            _invalidate_layout_artifact(revision_dir, artifact)
        generation["pending_layout_artifacts"] = sorted(repair_plan)
        _write(reference_path, working_reference)
    else:
        tasks = {
            task
            for target in targets
            if target.category == "verification"
            for task in [VERIFICATION_TASK_BY_TARGET.get(target.value)]
            if task is not None
        }
        _clear_verification_responses(revision_dir, tasks or None)
    retry_options: dict[str, Any] = {
        "operation_deadline": operation_deadline,
        "clock": clock,
    }
    if stage_observer is not None:
        retry_options["stage_observer"] = stage_observer
    return generate(run_dir, **retry_options)


def generate(
    run_dir: Path,
    *,
    operation_deadline: float | None = None,
    clock: Callable[[], float] = time.monotonic,
    stage_observer: Callable[[str, float], Any] | None = None,
    **_: Any,
) -> dict[str, Any]:
    """Advance one approved revision until it needs Hermes work or passes."""
    observed_at = clock()

    def observe_stage(stage: str) -> None:
        nonlocal observed_at
        now = clock()
        if stage_observer is not None:
            stage_observer(stage, max(0.0, now - observed_at))
        observed_at = now

    run_dir = run_dir.resolve(); reference_path, working_reference = _reference(run_dir)
    try:
        bundle = contracted_template_bundle(SCRIPT_DIR.parent, working_reference)
    except ContractedTemplateBundleError as exc:
        return _repair_block(run_dir, "contracted_template_bundle", [exc.finding])
    approved, approval_issue = _approval_valid(run_dir, working_reference, contracted_bundle=bundle)
    revision_id = str(working_reference.get("approval", {}).get("revision_id") or "")
    revision_dir = run_dir / "revisions" / revision_id
    reference = _read(revision_dir / "approved-reference.json") if approved else working_reference
    contract = source_contract(reference)
    if contract["status"] != "passed" or not approved:
        findings = list(contract["blocking_findings"])
        if not approved: findings.append({"category": "approval", "field": "approval", "issue": approval_issue})
        if approved:
            return _repair_block(run_dir, "approval_gate", findings)
        return {"status": "blocked", "stage": "approval_gate", "findings": findings, "client_outputs": []}
    if not revision_id or not revision_dir.is_dir(): return {"status": "blocked", "stage": "revision", "findings": [{"category": "revision", "field": "revision_id", "issue": "Approved immutable revision is missing."}], "client_outputs": []}
    state = working_reference.setdefault("generation", {})
    expected_governing = governing_resources(SCRIPT_DIR.parent, reference, contracted_bundle=bundle)
    governing_sha256 = sha256_value(expected_governing)
    prior_governing_sha256 = state.get("governing_sha256")
    if prior_governing_sha256 is not None and prior_governing_sha256 != governing_sha256:
        return {
            "status": "blocked",
            "stage": "revision",
            "findings": [{
                "category": "revision",
                "field": revision_id,
                "issue": "Generation resources changed inside an immutable revision.",
                "required": "Approve the unchanged Source-of-Truth again to create a new revision.",
            }],
            "client_outputs": [],
        }
    elif prior_governing_sha256 is None:
        state["governing_sha256"] = governing_sha256
        _write(reference_path, working_reference)
    attempts = state.setdefault("attempts", {})
    persisted_exhaustion = [
        {"category": "retry", "field": str(target), "issue": f"Retry limit reached after {MAX_ATTEMPTS} attempts.", "required": "Reviewer intervention before a new approved revision."}
        for target, count in attempts.items() if int(count) > MAX_ATTEMPTS
    ]
    if persisted_exhaustion:
        path = run_dir / "reference/repair-report.md"; path.write_text(repair_report(persisted_exhaustion), encoding="utf-8")
        return {"status": "blocked", "stage": "retry_limit", "findings": persisted_exhaustion, "repair_report": path.relative_to(run_dir).as_posix(), "client_outputs": []}
    drafting_findings = [
        finding if finding.get("category") in {"source-evidence", "request-integrity"}
        else recovery_finding(finding, "drafting_defect")
        for finding in ingest_responses(revision_dir, expected_governing)
    ]
    if drafting_findings:
        attempts, exhausted = retry_attempts(drafting_findings, attempts); state["attempts"] = attempts; _write(reference_path, working_reference)
        source_gaps = [item for item in drafting_findings if item.get("category") in {"source-evidence", "request-integrity"}]
        if source_gaps or exhausted:
            path = run_dir / "reference/repair-report.md"; path.write_text(repair_report([*source_gaps, *exhausted]), encoding="utf-8")
            return {"status": "blocked", "stage": "drafting", "findings": [*source_gaps, *exhausted], "repair_report": path.relative_to(run_dir).as_posix(), "client_outputs": []}
        created = schedule_requests(repo_root=SCRIPT_DIR.parent, revision_dir=revision_dir, revision_id=revision_id, reference=reference, attempts=attempts, wave="retry", findings=drafting_findings, contracted_bundle=bundle)
        if created: return _awaiting(revision_dir, stage="drafting_retry", paths=created, findings=drafting_findings)
    created = schedule_requests(repo_root=SCRIPT_DIR.parent, revision_dir=revision_dir, revision_id=revision_id, reference=reference, attempts=attempts, wave="initial", contracted_bundle=bundle)
    pending = pending_requests(revision_dir, expected_governing)
    if created or pending: return _awaiting(revision_dir, stage="drafting", paths=pending or created)
    missing = missing_drafts(revision_dir, reference, SCRIPT_DIR.parent, contracted_bundle=bundle)
    if missing: return {"status": "blocked", "stage": "drafting", "findings": [{"category": "drafting", "field": item, "issue": "Required section has no accepted draft after all requests were processed."} for item in missing], "client_outputs": []}
    duplicate_findings = accepted_cross_section_duplicate_findings(
        revision_dir,
        reference,
        expected_governing,
    )
    if duplicate_findings:
        return _quality_retry(
            run_dir,
            reference_path,
            working_reference,
            reference,
            revision_dir,
            attempts,
            duplicate_findings,
            "pre_render_content",
            contracted_bundle=bundle,
            operation_deadline=operation_deadline,
            clock=clock,
            stage_observer=stage_observer,
        )

    observe_stage("drafting")
    model = merged_drafts(revision_dir, reference, expected_governing)
    font_substitutions = {
        str(source): str(target)
        for source, target in dict(state.get("font_substitutions") or {}).items()
    }
    layout_repairs = {
        str(artifact): tuple(_normalized_layout_repair_records(rules))
        for artifact, rules in dict(state.get("layout_repairs") or {}).items()
        if isinstance(rules, list)
    }
    fingerprint, governing = _candidate_fingerprint(
        SCRIPT_DIR.parent,
        revision_dir,
        reference,
        model,
        contracted_bundle=bundle,
        font_substitutions=font_substitutions,
        layout_repairs=layout_repairs,
    )
    try:
        prior_build = _read(revision_dir / "candidate-build.json")
    except (OSError, ValueError, json.JSONDecodeError):
        prior_build = None
    repair_artifacts = {
        str(artifact)
        for artifact in state.get("pending_layout_artifacts", [])
        if str(artifact) in layout_repairs
    }
    partial_repair = (
        repair_artifacts
        if prior_build and repair_artifacts and _unaffected_build_is_valid(revision_dir, prior_build, repair_artifacts)
        else set()
    )
    build = _cached_build(revision_dir, fingerprint)
    structure = _cached_candidate_structure(revision_dir, fingerprint)
    assurance_report: dict[str, Any] | None = None
    if build is None:
        if structure is not None:
            document_report = structure["document_report"]
            xml_report = structure.get("xml_report")
        else:
            document_report = render_documents(
                SCRIPT_DIR.parent,
                revision_dir,
                reference,
                model,
                contracted_bundle=bundle,
                font_substitutions=font_substitutions,
                artifact_names=partial_repair or None,
                layout_repairs=layout_repairs,
            )
            if partial_repair:
                document_report = _merge_artifact_reports(prior_build.get("document_report", {}), document_report)
            if document_report["status"] != "passed":
                findings, classification_block = _document_report_failure(run_dir, revision_dir, document_report)
                if classification_block is not None:
                    return classification_block
                return _quality_retry(run_dir, reference_path, working_reference, reference, revision_dir, attempts, findings, "rendering", contracted_bundle=bundle, operation_deadline=operation_deadline, clock=clock, stage_observer=stage_observer)
            xml_report = prior_build.get("xml_report") if partial_repair else None
            if canonical_study_type(reference.get("meta", {}).get("study_type")) != "Retrospective":
                if xml_report is None or not (revision_dir / "candidate/study.xml").is_file():
                    prs_authority = bundle["prs_authority"]
                    template = SCRIPT_DIR.parent / str(prs_authority["generation_template"]["path"])
                    xml_report = generate_xml(
                        template,
                        revision_dir / "candidate/study.xml",
                        reference,
                        model.get("prs", {}),
                        structural_template=SCRIPT_DIR.parent / str(prs_authority["structural_reference"]["path"]),
                    )
                if xml_report["status"] != "passed":
                    findings = [
                        {**finding, "category": "document-structure", "recovery_class": "document_structure_defect", "action": "preserve_and_stop"}
                        for finding in xml_report["findings"]
                    ]
                    return _repair_block(run_dir, "xml", findings, candidate_outputs=_candidate_outputs(revision_dir))
            structure = _record_candidate_structure(revision_dir, fingerprint, governing, bundle, document_report, xml_report, document_set(get_path(reference, "meta.study_type")))

        observe_stage("candidate")
        remaining = 180.0 if operation_deadline is None else operation_deadline - clock()
        if remaining <= 0:
            return {
                "status": "timeout",
                "stage": "render_assurance",
                "findings": [{"category": "timeout", "field": "operation", "issue": "The persisted Desktop operation deadline expired before Render Assurance."}],
                "candidate_outputs": _candidate_outputs(revision_dir),
                "client_outputs": [],
            }

        def rebuild_with_substitutions(resolved: Mapping[str, str]) -> dict[str, Any]:
            nonlocal document_report
            document_report = render_documents(
                SCRIPT_DIR.parent,
                revision_dir,
                reference,
                model,
                contracted_bundle=bundle,
                font_substitutions=resolved,
                artifact_names=partial_repair or None,
                layout_repairs=layout_repairs,
            )
            if partial_repair:
                document_report = _merge_artifact_reports(prior_build.get("document_report", {}), document_report)
            return document_report

        assurance_report = render_assurance(
            SCRIPT_DIR.parent,
            revision_dir,
            reference,
            contracted_bundle=bundle,
            structural_validation=structure,
            candidate_font_substitutions=font_substitutions,
            rebuild_candidate=rebuild_with_substitutions,
            artifact_names=partial_repair or None,
            deadline_seconds=min(180.0, remaining),
            deadline_monotonic=operation_deadline,
            clock=clock,
        )
        resolved_substitutions = {
            str(source): str(target)
            for source, target in dict(assurance_report.get("font_substitutions") or {}).items()
        }
        if resolved_substitutions != font_substitutions:
            font_substitutions = resolved_substitutions
            state["font_substitutions"] = font_substitutions
            fingerprint, governing = _candidate_fingerprint(
                SCRIPT_DIR.parent,
                revision_dir,
                reference,
                model,
                contracted_bundle=bundle,
                font_substitutions=font_substitutions,
                layout_repairs=layout_repairs,
            )
            structure = _record_candidate_structure(revision_dir, fingerprint, governing, bundle, document_report, xml_report, document_set(get_path(reference, "meta.study_type")))
        assurance_report, render_report = _merge_partial_assurance(prior_build or {}, assurance_report, partial_repair)
        state["render_assurance"] = assurance_report
        state.pop("renderer_preflight", None)
        structure = _record_candidate_structure(revision_dir, fingerprint, governing, bundle, document_report, xml_report, document_set(get_path(reference, "meta.study_type")))
        _write(reference_path, working_reference)
        if assurance_report.get("status") != "passed":
            findings = [
                {**finding, "target_ids": finding.get("target_ids") or [f"layout:{finding.get('artifact') or 'documents'}"]}
                for finding in assurance_report.get("findings", [])
            ]
            if findings and all(finding.get("recovery_class") == "adapter_fault" for finding in findings):
                diagnostic_path = run_dir / "reference/render-assurance-diagnostic.md"
                diagnostic_path.write_text(repair_report(findings), encoding="utf-8")
                return {
                    "status": "blocked",
                    "stage": "render_assurance",
                    "findings": findings,
                    "render_assurance": assurance_report,
                    "repair_report": diagnostic_path.relative_to(run_dir).as_posix(),
                    "candidate_outputs": _candidate_outputs(revision_dir),
                    "client_outputs": [],
                }
            return _quality_retry(run_dir, reference_path, working_reference, reference, revision_dir, attempts, findings, "rendered_document_qa", contracted_bundle=bundle, operation_deadline=operation_deadline, clock=clock, stage_observer=stage_observer)
        build = _record_build(revision_dir, fingerprint, governing, bundle, document_report, xml_report, render_report)
    else:
        observe_stage("candidate")
        document_report = build["document_report"]
        xml_report = build.get("xml_report")
        render_report = build["render_report"]
        recorded_assurance = state.get("render_assurance")
        assurance_report = dict(recorded_assurance) if isinstance(recorded_assurance, Mapping) else {
            "schema_version": "render-assurance/v1",
            "status": "passed",
            "font_substitutions": font_substitutions,
            "render": render_report,
            "findings": [],
        }
    observe_stage("render_assurance")
    if state.pop("pending_layout_artifacts", None) is not None:
        _write(reference_path, working_reference)
    create_verification_requests(revision_dir, reference, render_report, contracted_bundle=bundle)
    pending_checks = pending_verifications(revision_dir)
    if pending_checks: return _awaiting(revision_dir, stage="independent_verification", paths=pending_checks)
    final_quality = quality_report(revision_dir, reference, render_report, xml_report)
    final_quality["render_assurance"] = assurance_report
    if final_quality["status"] != "passed":
        return _quality_retry(run_dir, reference_path, working_reference, reference, revision_dir, attempts, final_quality["findings"], "quality", contracted_bundle=bundle, operation_deadline=operation_deadline, clock=clock, stage_observer=stage_observer)
    observe_stage("independent_verification")
    try:
        published = _publish(
            run_dir,
            revision_dir,
            reference,
            final_quality,
            operation_deadline=operation_deadline,
            clock=clock,
        )
    except OperationDeadlineExpired as exc:
        return {
            "status": "timeout",
            "stage": "delivery",
            "findings": [{"category": "timeout", "field": "operation", "issue": str(exc)}],
            "candidate_outputs": _candidate_outputs(revision_dir),
            "client_outputs": [],
        }
    observe_stage("delivery")
    return published


def _save_recorded_handoff(revision_dir: Path, request_path: Path) -> None:
    request = _read(request_path)
    response = recorded_acceptance_response(request)
    _write(revision_dir / request["response_path"], response)


def _save_verification_response(revision_dir: Path, request_path: Path, responder: Callable[[Mapping[str, Any]], Mapping[str, Any]]) -> None:
    request = _read(request_path)
    _write(revision_dir / request["response_path"], responder(request))


def run_release_gate(
    repo_root: Path,
    *,
    verification_responder: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
    evidence_root: Path | None = None,
) -> dict[str, Any]:
    """Exercise all six lifecycle cases; genuine verifier responses remain external."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if evidence_root is not None:
        root = evidence_root.resolve()
    else:
        base = (repo_root / ".scratch/release-gate" / timestamp).resolve()
        root = base
        suffix = 1
        while root.exists():
            root = base.with_name(f"{base.name}-{suffix}")
            suffix += 1
    root.mkdir(parents=True, exist_ok=True)
    results = []
    corpus = _read_corpus(repo_root / "tests/fixtures/branch-acceptance-corpus.json")
    for case in [item for item in corpus if str(item.get("profile", "")).endswith("complete")]:
            branch = str(case["study_type"]); richness = str(case["profile"]).split("-", 1)[0]
            run_dir = root / str(case["fixture_id"])
            if not (run_dir / REFERENCE).is_file():
                reference = _read(repo_root / str(case["source_fixture"]))
                reference["meta"]["protocol_number"] = f"{branch[:3].upper()}-{richness}-26"; reference["study"]["title"] = f"{branch} {richness} acceptance study"; reference["study"]["short_title"] = f"{branch} {richness} acceptance"
                if richness == "rich" and branch != "Retrospective":
                    reference["meta"]["icf_template"] = "Sterling"
                if richness == "rich":
                    reference["study"]["background"] = f"{reference['study']['background'].rstrip('.')} with extended follow-up."
                    reference["study"]["timeline"] = "6 months"
                    reference["procedures"]["assessments"] = list(reference["procedures"].get("assessments", [])) + ["Extended follow-up assessment"]
                    reference["procedures"]["visit_schedule_table"] = list(reference["procedures"].get("visit_schedule_table", [])) + [{"visitNumber": "4", "visitName": "Month 6", "visitWindow": "±14 days", "CRFnumber": "CRF-04"}]
                    reference["population"]["sample_size"] = "80 participants"
                    for item in reference["population"].get("sample_size_evidence", []):
                        if isinstance(item, dict): item["value"] = "80 participants"
                    for item in reference.get("statistics", {}).get("sample_size_evidence", []):
                        if isinstance(item, dict): item["value"] = "80 participants"
                    if branch != "Retrospective":
                        reference["endpoints"].setdefault("other", []).extend([{"label": "Extended follow-up outcome", "time_point": "Month 6"}, {"label": "Participant experience outcome", "time_point": "Month 6"}])
                        reference["design"]["interventions"] = [{"name": "Sentinel Patch", "type": "Device", "description": "Primary monitoring configuration.", "arm_group_label": "Primary cohort"}, {"name": "Sentinel Patch Extended", "type": "Device", "description": "Extended monitoring configuration.", "arm_group_label": "Extended cohort"}]
                        reference["design"]["arms"] = [{"name": "Primary cohort", "description": "Primary observational cohort."}, {"name": "Extended cohort", "description": "Extended observational cohort."}]
                    if reference.get("sites"):
                        second_site = copy.deepcopy(reference["sites"][0]); second_site["facility"]["name"] = "Site Two"; second_site["contact"]["name"] = "Taylor Coordinator"; second_site["contact"]["email"] = "taylor@example.org"; second_site["investigators"][0]["name"] = "Morgan Investigator"
                        reference["sites"].append(second_site); reference["design"]["number_of_sites"] = 2
                        reference["design"]["study_design"] = str(reference["design"]["study_design"]).replace("single-center", "multicenter")
                reference["approval"] = {"status": "draft"}; _write(run_dir / REFERENCE, reference)
                first = prepare(run_dir)
                if first.get("status") != "awaiting_approval": results.append({"case": run_dir.name, "status": "failed", "result": first}); continue
                approval = approve(run_dir, approved_by="Recorded Acceptance")
                if approval.get("status") != "passed": results.append({"case": run_dir.name, "status": "failed", "result": approval}); continue
            reference = _read(run_dir / REFERENCE)
            case_bundle = contracted_template_bundle(repo_root, reference)
            result: dict[str, Any] = {}
            for _attempt in range(12):
                result = generate(run_dir)
                if result.get("status") != "awaiting_hermes": break
                revision_dir = run_dir / "revisions" / str(result["revision_id"])
                for relative in result.get("requests", []):
                    request_path = revision_dir / relative
                    if "verification-requests" in relative:
                        if verification_responder is not None:
                            _save_verification_response(revision_dir, request_path, verification_responder)
                    else:
                        _save_recorded_handoff(revision_dir, request_path)
                if result.get("stage") == "independent_verification" and verification_responder is None:
                    break
            results.append({"case": run_dir.name, "corpus": case, "icf_template": get_path(reference, "meta.icf_template"), "source_sha256": sha256_value(_approved_payload(reference)), "contracted_template_bundle": case_bundle, "status": "passed" if result.get("status") == "passed" else "failed", "result": result})
    passed = all(item["status"] == "passed" for item in results)
    awaiting = any(item.get("result", {}).get("status") == "awaiting_hermes" for item in results)
    synthetic_verification = bool(verification_responder is not None and getattr(verification_responder, "synthetic", False))
    recorded_drafting = True
    status = "structural_passed" if passed and recorded_drafting else "passed" if passed else "awaiting_hermes" if awaiting else "blocked"
    assurance = "synthetic-structural-only" if synthetic_verification else "recorded-drafting-structural-only"
    unique_bundles = {
        bundle["identity_sha256"]: bundle
        for item in results
        if isinstance((bundle := item.get("contracted_template_bundle")), Mapping)
    }
    report = {"status": status, "assurance": assurance, "recorded_drafting": recorded_drafting, "cases": results, "contracted_template_bundles": list(unique_bundles.values()), "distinct_source_count": len({item.get("source_sha256") for item in results}), "visual_evidence": "external image inspection required; no automated visual approval is fabricated", "evidence_root": root.as_posix()}
    _write(root / "release-gate-report.json", report); return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--run-dir"); parser.add_argument("--stage", choices=("prepare", "approve", "validate", "generate")); parser.add_argument("--approved-by", default="client"); parser.add_argument("--source-md"); parser.add_argument("--release-gate", action="store_true"); parser.add_argument("--release-gate-root"); parser.add_argument("--package-release", metavar="ARCHIVE", help="create an installable release archive"); parser.add_argument("--verify-installation", action="store_true", help="smoke-test this installed release"); parser.add_argument("--install-release", metavar="ARCHIVE", help="atomically install and activate a release archive"); parser.add_argument("--skills-dir", help="Hermes skills directory for --install-release")
    args = parser.parse_args(argv)
    if args.package_release: result = package_release(SCRIPT_DIR.parent, Path(args.package_release))
    elif args.verify_installation: result = verify_installation(SCRIPT_DIR.parent)
    elif args.install_release:
        if not args.skills_dir: parser.error("--skills-dir is required with --install-release")
        result = install_release(Path(args.install_release), Path(args.skills_dir))
    elif args.release_gate: result = run_release_gate(SCRIPT_DIR.parent, evidence_root=Path(args.release_gate_root) if args.release_gate_root else None)
    else:
        if not args.run_dir or not args.stage: parser.error("--run-dir and --stage are required unless --release-gate is used")
        run_dir = Path(args.run_dir).expanduser().resolve()
        result = {"prepare": prepare, "approve": approve, "validate": validate, "generate": generate}[args.stage](run_dir, approved_by=args.approved_by, source_md=Path(args.source_md).expanduser() if args.source_md else None)
    print(json.dumps(result, indent=2, ensure_ascii=False)); return 0 if result.get("status") in {"passed", "awaiting_approval", "awaiting_hermes"} else 1


__all__ = ["approve", "confirm_desktop_delivery", "desktop_attachment_reply", "desktop_operation_state_path", "generate", "install_release", "package_release", "performance_classification", "prepare", "provision_fallback_stack", "resolve_python_runtime", "run_desktop_operation", "run_release_gate", "validate", "verify_installation"]


if __name__ == "__main__": raise SystemExit(main())
