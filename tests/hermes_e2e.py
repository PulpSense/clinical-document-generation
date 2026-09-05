#!/usr/bin/env python3
"""Test-only real-Hermes adapter for the production Desktop Operation seam."""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import math
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

EXPECTED_OUTPUTS = frozenset({"protocol.docx", "icf.docx", "study.xml"})
APPROVED_INPUT_NORMALIZATIONS = {
    "b54328aa5f7f26b53109e4eccb5efc4665a2ed23a90e169da4c7a9aa6c6c768b":
    "ebd829a5de29a10cd9a10b8618b97916bf324480979c1bea4456202cafa1e44f",
}
REPO_ROOT = Path(__file__).resolve().parents[1]
CERTIFICATION_FIXTURE_ROOT = REPO_ROOT / "tests/fixtures/release-certification"
CLEANUP_RESERVE_SECONDS = 5.0
PROGRESS_INTERVAL_SECONDS = 60.0
CERTIFICATION_RUNTIME_CEILING_SECONDS = 900.0
EXTENDED_CERTIFICATION_RUNTIME_CEILING_SECONDS = 1080.0
CERTIFICATION_CORPUS = (
    "retrospective",
    "ambispective-sterling",
    "prospective-advarra",
)
CERTIFICATION_CORPUS_COVERAGE = {
    "ambispective-sterling": ("Ambispective", "Sterling"),
    "prospective-advarra": ("Prospective", "Advarra"),
    "retrospective": ("Retrospective", None),
}
DETERMINISTIC_BRANCH_ACCEPTANCE_CASES = (
    "prospective-sparse-complete",
    "prospective-rich-complete",
    "ambispective-sparse-complete",
    "ambispective-rich-complete",
    "retrospective-sparse-complete",
    "retrospective-rich-complete",
)
CERTIFICATION_LAYOUT_COVERAGE = (
    "Prospective/Advarra",
    "Prospective/Sterling",
    "Ambispective/Advarra",
    "Ambispective/Sterling",
    "Retrospective/Protocol",
)
GOVERNED_HERMES_CONFIGURATION_FIELDS = (
    "source",
    "max_turns",
    "skill",
    "safe_mode",
    "reasoning_configuration",
)
CERTIFICATION_VISUAL_CHECKS = frozenset({
    "artificial_pagination", "bad_table_split", "blank_page", "clipping",
    "duplicate_section", "excessive_whitespace", "footer_collision",
    "inconsistent_style", "missing_header_footer", "orphan_heading",
    "overflow", "overlap", "toc_mismatch", "unreadable_text",
})
CERTIFICATION_GATE_NAMES = frozenset({
    "source", "content", "document_structure", "prs_xml", "package",
    "cross_document_consistency", "render_assurance", "every_page_visual_qa",
    "delivery_confirmation",
})
DEFAULT_HERMES_CONFIGURATION = {
    "source": "clinical-release-certification",
    "max_turns": 80,
    "skill": "clinical-document-generation",
    "safe_mode": True,
    "reasoning_configuration": "Hermes Desktop governed default",
}
FIRST_WAVE_BATCHES = frozenset(
    {
        "protocol-foundations",
        "protocol-operations",
        "protocol-analysis-and-oversight",
        "icf-narrative",
    }
)


def _certification_runtime_ceiling(fixture_id: str) -> float:
    return (
        EXTENDED_CERTIFICATION_RUNTIME_CEILING_SECONDS
        if fixture_id in {"ambispective-sterling", "prospective-advarra"}
        else CERTIFICATION_RUNTIME_CEILING_SECONDS
    )


def _certification_runtime_exceeded(fixture_id: str, elapsed: float) -> bool:
    ceiling = _certification_runtime_ceiling(fixture_id)
    return elapsed > ceiling if ceiling == EXTENDED_CERTIFICATION_RUNTIME_CEILING_SECONDS else elapsed >= ceiling


def expected_outputs(reference: Mapping[str, Any]) -> frozenset[str]:
    study_type = str((reference.get("meta") or {}).get("study_type") or "").casefold()
    return frozenset({"protocol.docx"}) if study_type == "retrospective" else EXPECTED_OUTPUTS


def sandbox_command(repo_root: Path, run_dir: Path, command: Sequence[str]) -> tuple[list[str], Path]:
    """Launch Hermes under a kernel-enforced read-only skill boundary on macOS."""
    sandbox = shutil.which("sandbox-exec")
    if sandbox is None:
        raise RuntimeError("No supported OS sandbox enforcement mechanism is available")
    cache_dir = run_dir / ".hermes-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    profile = tempfile.NamedTemporaryFile("w", prefix="hermes-generation-", suffix=".sb", delete=False)
    profile.write("(version 1)\n(allow default)\n")
    profile.write(f"(deny file-write* (subpath {json.dumps(str(repo_root.resolve()))}))\n")
    profile.write(f"(allow file-write* (subpath {json.dumps(str(run_dir.resolve()))}))\n")
    profile.write(f"(allow file-write* (subpath {json.dumps(str(cache_dir.resolve()))}))\n")
    for executable in ("pytest", "py.test", "pip", "pip3"):
        profile.write(f"(deny process-exec (literal {json.dumps(executable)}))\n")
        resolved = shutil.which(executable)
        if resolved:
            profile.write(f"(deny process-exec (literal {json.dumps(resolved)}))\n")
    profile.close()
    return [sandbox, "-f", profile.name, *command], Path(profile.name)


class DiagnosticOutcome(str, Enum):
    PASSED = "passed"
    NON_CERTIFYING_RUNTIME = "non-certifying-runtime"
    BLOCKED = "blocked"
    TIMEOUT = "timeout"
    RETRY_LIMIT_VIOLATED = "retry-limit-violated"
    INVALID_HERMES_RESPONSE = "invalid-Hermes-response"


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _read_json_lines(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def certification_fixture(
    fixture_id: str,
    *,
    fixture_root: Path = CERTIFICATION_FIXTURE_ROOT,
) -> dict[str, Any]:
    """Load one immutable, explicitly synthetic certification fixture."""
    root = fixture_root.resolve()
    fixture_dir = (root / fixture_id).resolve()
    try:
        fixture_dir.relative_to(root)
    except ValueError as exc:
        raise ValueError("Certification fixture identity escapes its repository root.") from exc
    manifest = _read_json(fixture_dir / "fixture.json")
    if manifest is None or manifest.get("schema_version") != "release-certification-fixture/v1":
        raise ValueError(f"Certification fixture {fixture_id!r} has no valid manifest.")
    if manifest.get("fixture_id") != fixture_id:
        raise ValueError("Certification fixture identity does not match its directory.")
    if manifest.get("synthetic") is not True or manifest.get("contains_private_data") is not False:
        raise ValueError("Release Certification accepts only explicitly synthetic, non-private fixtures.")
    expected = set(manifest.get("expected_outputs") or [])
    branch_expected = (
        {"protocol.docx"}
        if str(manifest.get("study_type") or "").casefold() == "retrospective"
        else set(EXPECTED_OUTPUTS)
    )
    if expected != branch_expected:
        raise ValueError("Certification fixture expected outputs do not match its study branch.")
    artifact_paths: dict[str, Path] = {}
    artifacts = manifest.get("artifacts")
    required_artifacts = {"source_input", "approved_source", "approved_reference"}
    if not isinstance(artifacts, Mapping) or set(artifacts) != required_artifacts:
        raise ValueError("Certification fixture must declare its complete reviewed artifact set.")
    for name in sorted(required_artifacts):
        item = artifacts[name]
        if not isinstance(item, Mapping):
            raise ValueError(f"Certification fixture artifact {name!r} is invalid.")
        path = (fixture_dir / str(item.get("path") or "")).resolve()
        try:
            path.relative_to(fixture_dir)
        except ValueError as exc:
            raise ValueError(f"Certification fixture artifact {name!r} escapes its fixture.") from exc
        if not path.is_file() or _sha256(path) != item.get("sha256"):
            raise ValueError(f"Certification fixture artifact {name!r} hash does not match.")
        artifact_paths[name] = path
    reference = _read_json(artifact_paths["approved_reference"])
    if reference is None:
        raise ValueError("Certification fixture approved reference is not valid JSON.")
    meta = reference.get("meta") or {}
    if meta.get("study_type") != manifest.get("study_type"):
        raise ValueError("Certification fixture study branch does not match its approved reference.")
    if manifest.get("study_type") != "Retrospective" and meta.get("icf_template") != manifest.get("icf_family"):
        raise ValueError("Certification fixture ICF family does not match its approved reference.")
    return {**manifest, "artifact_paths": artifact_paths}


def certification_corpus(
    *,
    fixture_root: Path = CERTIFICATION_FIXTURE_ROOT,
) -> tuple[dict[str, Any], ...]:
    """Load the complete reviewed three-case real-Hermes release corpus."""
    fixtures = tuple(
        certification_fixture(fixture_id, fixture_root=fixture_root)
        for fixture_id in CERTIFICATION_CORPUS
    )
    governed_configurations = set()
    for fixture in fixtures:
        fixture_id = str(fixture["fixture_id"])
        identity = (fixture.get("study_type"), fixture.get("icf_family"))
        if identity != CERTIFICATION_CORPUS_COVERAGE[fixture_id]:
            raise ValueError(f"Certification fixture {fixture_id!r} does not cover its declared corpus branch.")
        if fixture.get("review_status") != "approved for release certification":
            raise ValueError(f"Certification fixture {fixture_id!r} is not explicitly approved.")
        if not str(fixture.get("privacy_statement") or "").strip():
            raise ValueError(f"Certification fixture {fixture_id!r} has no privacy statement.")
        configuration = fixture.get("hermes_configuration")
        if not isinstance(configuration, Mapping):
            raise ValueError(f"Certification fixture {fixture_id!r} has no governed Hermes configuration.")
        try:
            governed = {
                key: configuration[key]
                for key in GOVERNED_HERMES_CONFIGURATION_FIELDS
            }
        except KeyError as exc:
            raise ValueError(
                f"Certification fixture {fixture_id!r} omits governed Hermes setting {exc.args[0]!r}."
            ) from exc
        governed_configurations.add(
            json.dumps(governed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        )
    if len(governed_configurations) != 1:
        raise ValueError("All real certification cases must use the same governed Hermes settings.")
    return fixtures


def _canonical_reviewed_fixture_reference(
    fixture: Mapping[str, Any],
    certified_workflow: Any,
) -> dict[str, Any]:
    """Re-derive the reviewed reference through the governed Markdown parser."""
    fixture_paths = fixture["artifact_paths"]
    prior_reference = _read_json(fixture_paths["approved_reference"])
    if prior_reference is None:
        raise ValueError("Certification fixture approved reference is not valid JSON.")
    parsed = certified_workflow.parse_source_truth(
        fixture_paths["approved_source"].read_text(encoding="utf-8"),
        prior_reference,
    )
    canonical = dict(parsed)
    canonical.pop("approval", None)
    canonical.pop("generation", None)
    return canonical


def _certified_release(release_root: Path) -> tuple[Any, dict[str, Any]]:
    """Load a hash-valid immutable candidate workflow for real certification."""
    release_root = release_root.resolve()
    if (release_root / ".git").exists():
        raise ValueError("Real Release Certification cannot run the editable checkout.")
    manifest_path = release_root / "RELEASE-MANIFEST.json"
    manifest = _read_json(manifest_path)
    if manifest is None or not str(manifest.get("package_fingerprint") or ""):
        raise ValueError("Release Certification requires a packaged candidate manifest and fingerprint.")
    git_commit = str(manifest.get("git_commit") or "")
    if len(git_commit) != 40 or any(character not in "0123456789abcdef" for character in git_commit.casefold()):
        raise ValueError("Release Certification requires a candidate built from an identified clean commit.")
    fingerprint_payload = dict(manifest)
    recorded_fingerprint = str(fingerprint_payload.pop("package_fingerprint"))
    computed_fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    if computed_fingerprint != recorded_fingerprint:
        raise ValueError("Release candidate fingerprint does not match its manifest contents.")
    for item in manifest.get("files", []):
        relative = Path(str(item.get("path") or ""))
        path = (release_root / relative).resolve()
        try:
            path.relative_to(release_root)
        except ValueError as exc:
            raise ValueError(f"Release manifest path escapes the candidate: {relative}") from exc
        recorded_bytes = item.get("bytes")
        if not path.is_file() or _sha256(path) != item.get("sha256") or path.stat().st_size != int(recorded_bytes if recorded_bytes is not None else -1):
            raise ValueError(f"Release candidate file does not match its manifest: {relative}")
    declared = {str(item.get("path") or "") for item in manifest.get("files", [])}
    actual = {
        path.relative_to(release_root).as_posix()
        for path in release_root.rglob("*")
        if path.is_file()
        and "runtime" not in path.relative_to(release_root).parts
        and path.name not in {"RELEASE-CERTIFICATION.json", "INSTALLATION-ASSURANCE.json", "PROMOTION-RECORD.json", "RELEASE-MANIFEST.json"}
    }
    extras = sorted(actual - declared)
    if extras:
        raise ValueError(f"Release candidate contains files outside its manifest: {', '.join(extras)}")

    scripts = release_root / "scripts"
    workflow_path = scripts / "workflow.py"
    if not workflow_path.is_file():
        raise ValueError("Release candidate has no workflow entrypoint.")
    module_name = f"certified_clinical_workflow_{str(manifest['package_fingerprint'])[:12]}"
    specification = importlib.util.spec_from_file_location(module_name, workflow_path)
    if specification is None or specification.loader is None:
        raise ImportError("Could not load the certified workflow module.")
    module = importlib.util.module_from_spec(specification)
    dependency_names = ("contracts", "drafting", "rendering", "quality", "prs_xml")
    previous_modules = {name: sys.modules.get(name) for name in dependency_names}
    previous_dont_write_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(scripts))
    sys.modules[module_name] = module
    try:
        for name in dependency_names:
            sys.modules.pop(name, None)
        specification.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    finally:
        sys.dont_write_bytecode = previous_dont_write_bytecode
        sys.path.remove(str(scripts))
        for name, previous in previous_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
    return module, {
        "package_fingerprint": str(manifest["package_fingerprint"]),
        "git_commit": git_commit,
        "source": "release_certification_candidate",
    }


def input_provenance(
    source_input: Path,
    approved_source: Path,
    *,
    approved_normalizations: Mapping[str, str] = APPROVED_INPUT_NORMALIZATIONS,
) -> dict[str, str]:
    input_sha256 = _sha256(source_input)
    source_sha256 = _sha256(approved_source)
    if approved_normalizations.get(input_sha256) != source_sha256:
        raise ValueError("The supplied input is not bound to this approved normalization.")
    return {
        "status": "approved_normalization",
        "input_sha256": input_sha256,
        "approved_source_sha256": source_sha256,
    }


def _interval_seconds(intervals: Sequence[tuple[float, float]]) -> float:
    if not intervals:
        return 0.0
    merged: list[list[float]] = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return sum(end - start for start, end in merged)


def inspect_run(
    run_dir: Path,
    *,
    final_result: Mapping[str, Any],
    elapsed_seconds: float,
    timed_out: bool,
    child_returncode: int | None,
    expected_model_identifier: str | None = None,
) -> dict[str, Any]:
    reference = _read_json(run_dir / "reference/study.reference.json") or {}
    study_type = str((reference.get("meta") or {}).get("study_type") or "").casefold()
    certification_runtime_ceiling = (
        EXTENDED_CERTIFICATION_RUNTIME_CEILING_SECONDS
        if study_type in {"ambispective", "prospective"}
        else CERTIFICATION_RUNTIME_CEILING_SECONDS
    )
    required_outputs = expected_outputs(reference)
    revision_id = str((reference.get("approval") or {}).get("revision_id") or "")
    revision_dir = run_dir / "revisions" / revision_id
    request_rows: list[dict[str, Any]] = []
    missing_response_paths: list[str] = []
    invalid_response_paths: list[str] = []
    recorded_response_paths: list[str] = []
    stable_target_attempts: dict[str, list[int]] = {}
    model_identifiers: set[str] = set()

    drafting_request_paths = sorted((revision_dir / "hermes/requests").glob("*.json"))
    verification_request_paths = sorted((revision_dir / "hermes/verification-requests").glob("*.json"))
    for request_path in (*drafting_request_paths, *verification_request_paths):
        request = _read_json(request_path) or {}
        response_relative = str(request.get("response_path") or "")
        response_path = revision_dir / response_relative
        if not response_path.is_file():
            missing_response_paths.append(response_relative)
        else:
            response = _read_json(response_path)
            if response is None:
                invalid_response_paths.append(response_relative)
            else:
                request_sha256 = str(request.get("request_sha256") or "")
                if not request_sha256 or any((
                    response.get("request_id") != request.get("request_id"),
                    response.get("request_sha256") != request_sha256,
                    response.get("task") != request.get("task"),
                    not str((response.get("producer") or {}).get("model_id") or "").strip(),
                )):
                    invalid_response_paths.append(response_relative)
                model_id = str((response.get("producer") or {}).get("model_id") or "")
                if model_id:
                    model_identifiers.add(model_id)
                if "recorded_acceptance_response" in model_id.casefold():
                    recorded_response_paths.append(response_relative)
        for target, attempt in (request.get("attempts") or {}).items():
            stable_target_attempts.setdefault(str(target), []).append(int(attempt))
        request_rows.append(
            {
                "request_id": request.get("request_id"),
                "request_path": request_path.relative_to(revision_dir).as_posix(),
                "task": request.get("task"),
                "batch_id": request.get("batch_id"),
                "response_path": response_relative,
            }
        )

    output_dir = run_dir / "output"
    output_files = {
        path.name for path in output_dir.glob("*") if path.is_file()
    } if output_dir.is_dir() else set()
    retry_limit_violations = {
        target: attempts
        for target, attempts in stable_target_attempts.items()
        if attempts and max(attempts) > 3
    }
    events = _read_json_lines(run_dir / "logs/hermes-integration-events.jsonl")
    status_stage_history = [
        {
            "status": event.get("status"),
            "stage": event.get("stage"),
            "elapsed_seconds": event.get("elapsed_seconds"),
        }
        for event in events
    ]
    stage_elapsed_seconds: dict[str, float] = {}
    for event in events:
        stage = str(event.get("stage") or "unknown")
        stage_elapsed_seconds[stage] = round(
            stage_elapsed_seconds.get(stage, 0.0) + float(event.get("elapsed_seconds") or 0.0),
            3,
        )
    rejected_response_findings = []
    invalid_rejection_paths: list[str] = []
    for path in sorted((revision_dir / "hermes/rejected").glob("*.json")):
        payload = _read_json(path) or {}
        findings = payload.get("findings") or []
        if any(
            str(finding.get("category") or "").casefold() in {"request", "response", "schema"}
            or any(term in str(finding.get("issue") or "").casefold() for term in ("hash", "schema", "binding", "mismatch"))
            for finding in findings
            if isinstance(finding, Mapping)
        ):
            invalid_rejection_paths.append(path.relative_to(revision_dir).as_posix())
        rejected_response_findings.append(
            {
                "path": path.relative_to(revision_dir).as_posix(),
                "findings": findings,
            }
        )
    first_wave_rows = [row for row in request_rows if row.get("batch_id") in FIRST_WAVE_BATCHES]
    initial_first_wave_rows = [row for row in first_wave_rows if ".initial." in str(row.get("request_id"))]
    measured_first_wave_rows = initial_first_wave_rows or first_wave_rows[:4]
    first_wave_ids = [str(row["request_id"]) for row in measured_first_wave_rows]
    agent_events = _read_json_lines(run_dir / "logs/hermes-agent-events.jsonl")
    first_wave_events = [
        event
        for event in agent_events
        if Path(str(event.get("request_path") or "")).stem in first_wave_ids
    ]
    event_concurrency = False
    if len(first_wave_events) == 4:
        starts = [float(event["started_monotonic"]) for event in first_wave_events]
        ends = [float(event["ended_monotonic"]) for event in first_wave_events]
        event_concurrency = max(starts) < min(ends)
    first_four_concurrent = event_concurrency
    requests_by_id = {str(row.get("request_id")): row for row in request_rows}
    agent_intervals: dict[str, list[tuple[float, float]]] = {}
    for event in agent_events:
        request_id = Path(str(event.get("request_path") or "")).stem
        task = str(event.get("task") or (requests_by_id.get(request_id) or {}).get("task") or "")
        if task in {"clinical_content_verification", "rendered_page_visual_verification"}:
            stage = "independent_verification"
        elif "quality-retry" in request_id or ".retry." in request_id:
            stage = "drafting_retry"
        elif task in {"section_drafting", "prs_narrative_drafting"}:
            stage = "drafting"
        else:
            continue
        try:
            interval = (float(event["started_monotonic"]), float(event["ended_monotonic"]))
        except (KeyError, TypeError, ValueError):
            continue
        agent_intervals.setdefault(stage, []).append(interval)
    for stage, intervals in agent_intervals.items():
        stage_elapsed_seconds[stage] = round(stage_elapsed_seconds.get(stage, 0.0) + _interval_seconds(intervals), 3)
    repair_report_path = run_dir / "reference/repair-report.md"
    expected_model_identifier = str(expected_model_identifier or "").strip()
    noncanonical_model_identifiers: list[str] = []
    model_identity_complete = bool(model_identifiers)
    valid_delivery = (
        final_result.get("status") == "passed"
        and output_files == required_outputs
        and bool((final_result.get("delivery") or {}).get("confirmed"))
        and not missing_response_paths
        and not invalid_response_paths
        and not recorded_response_paths
        and not invalid_rejection_paths
        and model_identity_complete
    )
    if timed_out:
        outcome = DiagnosticOutcome.TIMEOUT
    elif retry_limit_violations:
        outcome = DiagnosticOutcome.RETRY_LIMIT_VIOLATED
    elif valid_delivery and (
        elapsed_seconds > certification_runtime_ceiling
        if certification_runtime_ceiling == EXTENDED_CERTIFICATION_RUNTIME_CEILING_SECONDS
        else elapsed_seconds >= certification_runtime_ceiling
    ):
        outcome = DiagnosticOutcome.NON_CERTIFYING_RUNTIME
    elif valid_delivery:
        outcome = DiagnosticOutcome.PASSED
    elif (
        final_result.get("status") == "blocked"
        and final_result.get("stage") == "layout_repair_classification"
    ):
        outcome = DiagnosticOutcome.BLOCKED
    elif missing_response_paths or invalid_response_paths or recorded_response_paths or invalid_rejection_paths:
        outcome = DiagnosticOutcome.INVALID_HERMES_RESPONSE
    elif final_result.get("status") == "blocked":
        outcome = DiagnosticOutcome.BLOCKED
    else:
        outcome = DiagnosticOutcome.INVALID_HERMES_RESPONSE

    return {
        "outcome": outcome.value,
        "elapsed_seconds": elapsed_seconds,
        "child_returncode": child_returncode,
        "final_workflow_result": dict(final_result),
        "drafting_request_count": len(drafting_request_paths),
        "requests": request_rows,
        "stable_target_attempts": stable_target_attempts,
        "status_stage_history": status_stage_history,
        "stage_elapsed_seconds": stage_elapsed_seconds,
        "first_four_concurrent": first_four_concurrent,
        "hermes_agent_events": agent_events,
        "rejected_response_findings": rejected_response_findings,
        "missing_response_paths": missing_response_paths,
        "invalid_response_paths": invalid_response_paths,
        "recorded_response_paths": recorded_response_paths,
        "invalid_rejection_paths": invalid_rejection_paths,
        "candidate_created": (revision_dir / "candidate").is_dir(),
        "output_published": output_dir.is_dir(),
        "output_files": sorted(output_files),
        "required_outputs": sorted(required_outputs),
        "delivery": final_result.get("delivery"),
        "retry_limit_violations": retry_limit_violations,
        "model_identifiers": sorted(model_identifiers),
        "expected_model_identifier": expected_model_identifier or None,
        "noncanonical_model_identifiers": noncanonical_model_identifiers,
        "input_provenance": _read_json(run_dir / "reference/input-provenance.json"),
        "repair_report": repair_report_path.read_text(encoding="utf-8") if repair_report_path.is_file() else None,
    }


def _append_json_line(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(value), ensure_ascii=False) + "\n")


def subprocess_environment(*, home: Path | None = None) -> dict[str, str]:
    environment = dict(os.environ)
    hermes_bin = (home or Path.home()) / ".hermes/bin"
    if hermes_bin.is_dir():
        current_path = environment.get("PATH", "")
        environment["PATH"] = os.pathsep.join(part for part in (str(hermes_bin), current_path) if part)
    return environment


def _workflow(
    run_dir: Path,
    stage: str,
    *,
    approved_by: str | None = None,
    timeout_seconds: float | None = None,
    workflow_root: Path = REPO_ROOT,
) -> tuple[dict[str, Any], int]:
    command = [
        sys.executable,
        str(workflow_root / "scripts/workflow.py"),
        "--run-dir",
        str(run_dir),
        "--stage",
        stage,
    ]
    if approved_by is not None:
        command.extend(("--approved-by", approved_by))
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=workflow_root,
            env=subprocess_environment(),
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - started
        result = {"status": "timeout", "stage": stage}
        _append_json_line(
            run_dir / "logs/hermes-integration-events.jsonl",
            {
                "at": datetime.now(timezone.utc).isoformat(),
                "elapsed_seconds": round(elapsed, 3),
                "returncode": 124,
                "status": "timeout",
                "stage": stage,
                "request_count": 0,
            },
        )
        return result, 124
    elapsed = time.monotonic() - started
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError:
        result = {
            "status": "invalid_workflow_output",
            "stage": stage,
            "stdout": completed.stdout[-4000:],
            "stderr": completed.stderr[-4000:],
        }
    _append_json_line(
        run_dir / "logs/hermes-integration-events.jsonl",
        {
            "at": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": round(elapsed, 3),
            "returncode": completed.returncode,
            "status": result.get("status"),
            "stage": result.get("stage"),
            "request_count": len(result.get("handoffs") or []),
        },
    )
    return result, completed.returncode


def prepare_certification_run(
    fixture_id: str,
    run_dir: Path,
    *,
    workflow_root: Path,
    fixture_root: Path = CERTIFICATION_FIXTURE_ROOT,
) -> dict[str, Any]:
    """Create a fresh governed run from one repository-owned certification fixture."""
    if run_dir.exists():
        raise FileExistsError(f"Certification run already exists: {run_dir}")
    fixture = certification_fixture(fixture_id, fixture_root=fixture_root)
    artifacts = fixture["artifact_paths"]
    reference_dir = run_dir / "reference"
    input_dir = run_dir / "input"
    reference_dir.mkdir(parents=True)
    input_dir.mkdir()
    shutil.copy2(artifacts["source_input"], input_dir / "source-input.md")
    shutil.copy2(artifacts["approved_source"], reference_dir / "source-of-truth.md")
    shutil.copy2(artifacts["approved_reference"], reference_dir / "study.reference.json")
    normalization = fixture.get("approved_normalization") or {}
    provenance = input_provenance(
        input_dir / "source-input.md",
        reference_dir / "source-of-truth.md",
        approved_normalizations={
            str(normalization.get("source_input_sha256") or ""):
            str(normalization.get("approved_source_sha256") or ""),
        },
    )
    (reference_dir / "input-provenance.json").write_text(
        json.dumps({
            **provenance,
            "fixture_id": fixture_id,
            "synthetic": True,
            "contains_private_data": False,
            "review_status": fixture["review_status"],
            "privacy_statement": fixture["privacy_statement"],
            "expected_outputs": list(fixture["expected_outputs"]),
            "fixture_manifest_sha256": _sha256(
                fixture["artifact_paths"]["source_input"].parent / "fixture.json"
            ),
            "fixture_artifact_sha256": {
                name: str(item["sha256"])
                for name, item in sorted(fixture["artifacts"].items())
            },
            "hermes_configuration_sha256": _canonical_sha256(fixture["hermes_configuration"]),
            "input_path": "input/source-input.md",
            "approved_source_path": "reference/source-of-truth.md",
        }, indent=2) + "\n",
        encoding="utf-8",
    )
    reference = _read_json(reference_dir / "study.reference.json") or {}
    reference.pop("generation", None)
    reference["approval"] = {
        "status": "awaiting_approval",
        "review_file": "reference/source-of-truth.md",
    }
    (reference_dir / "study.reference.json").write_text(
        json.dumps(reference, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    result, _ = _workflow(
        run_dir,
        "approve",
        approved_by="Hermes Release Certification",
        workflow_root=workflow_root,
    )
    if result.get("status") != "passed":
        raise RuntimeError(f"Could not create governed certification revision: {json.dumps(result)}")
    return result


def _agent_prompt(
    skill_root: Path,
    revision_dir: Path,
    handoff: Mapping[str, Any],
    *,
    hermes_configuration: Mapping[str, Any] = DEFAULT_HERMES_CONFIGURATION,
) -> str:
    request_path = revision_dir / str(handoff["request_path"])
    response_path = revision_dir / str(handoff["response_path"])
    task = str(handoff.get("task") or "")
    visual_verification = task == "rendered_page_visual_verification"
    if task == "rendered_page_visual_verification":
        verification_rule = (
            "Act as an independent verifier. Load and inspect every supplied page PNG with the vision tool, assess every listed check for every page, then write the bound response promptly. "
            "The response top-level status and every page status must be exactly \"passed\"; do not use verdict, accepted, or pass aliases. "
            "Do not inspect production code or tests; the request contains the complete governed evidence and response contract."
        )
    elif task == "clinical_content_verification":
        verification_rule = (
            "Act as an independent verifier. Use the request's bound extracts and assessment matrices directly, assess every requested section and cross-document check, then write the bound response promptly. "
            "Artifact fields named content_sha256 are canonical DOCX content hashes, not raw file hashes. Never compare them with shasum, sha256sum, or a raw-byte digest, and do not fail a check because those different hash domains disagree. "
            "Do not inspect production code or tests; the request contains the complete governed evidence and response contract."
        )
    else:
        verification_rule = "Draft only the requested sections from the closed approved evidence package."
    preservation_notes = "\n".join(
        f"- {str(note).strip()}"
        for note in hermes_configuration.get("layout_preservation_notes") or []
        if str(note).strip()
    )
    preservation_rule = (
        "\nLayout Preservation Baseline. Do not normalize or redesign these authority-derived features:\n"
        f"{preservation_notes}\n"
        if visual_verification and preservation_notes
        else ""
    )
    if task in {"clinical_content_verification", "rendered_page_visual_verification"}:
        validator_code = (
            "import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); "
            "from quality import verification_response_is_complete; "
            "print(verification_response_is_complete(Path(sys.argv[2]), Path(sys.argv[3])))"
        )
        validator_command = shlex.join([
            str(Path(sys.executable).resolve()),
            "-c",
            validator_code,
            str(skill_root / "scripts"),
            str(revision_dir),
            str(request_path),
        ])
        validation_rule = (
            "Use your file-writing tool directly to write the JSON response. Do not use a shell heredoc. "
            "Then run exactly this read-only validator command without inspecting its source or searching for another validator:\n"
            f"{validator_command}\n"
            "The command must print True before you finish."
        )
    else:
        validation_rule = (
            "Write the response directly with your file-writing tool. The next generate invocation is the authoritative response validator; "
            "do not inspect production code or tests and do not search for another validator."
        )
    return f"""Complete one isolated clinical-document Hermes handoff.

Certified skill: {skill_root}
Run revision: {revision_dir}
Request: {request_path}
Response: {response_path}
Task: {task}

Read {skill_root / 'SKILL.md'} and load the clinical-document-generation skill. Read the request completely. {verification_rule}
{preservation_rule}
Write exact JSON to the response path. Bind every schema, request ID, request hash, task, target, and evidence reference exactly. producer.model_id must record the actual model used for this response, and producer.reviewer_id must record the independent reviewer role. {validation_rule} Never use recorded_acceptance_response and never fabricate verifier approval. Do not modify production code or the approved source. Return only the absolute response path and SHA-256 after the validated file exists."""


def _wait_for_processes(
    processes: Sequence[subprocess.Popen[str]],
    *,
    timeout_seconds: float,
    progress: Any | None = None,
    completion_check: Any | None = None,
) -> tuple[bool, dict[int, tuple[int | None, float]]]:
    deadline = time.monotonic() + timeout_seconds
    pending = {id(process): process for process in processes}
    completions: dict[int, tuple[int | None, float]] = {}
    timed_out = False
    last_progress = time.monotonic()
    while pending:
        observed_at = time.monotonic()
        if progress is not None and observed_at - last_progress >= PROGRESS_INTERVAL_SECONDS:
            progress(observed_at)
            last_progress = observed_at
        for process_id, process in list(pending.items()):
            returncode = process.poll()
            if returncode is None and completion_check is not None and completion_check(process):
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait()
                returncode = process.returncode
            if returncode is not None:
                completions[process_id] = (returncode, observed_at)
                del pending[process_id]
        if not pending:
            break
        if observed_at >= deadline:
            for process_id, process in list(pending.items()):
                returncode = process.poll()
                if returncode is not None:
                    completions[process_id] = (returncode, time.monotonic())
                    del pending[process_id]
            if not pending:
                break
            timed_out = True
            for process_id, process in pending.items():
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait()
                completions[process_id] = (process.returncode, time.monotonic())
            break
        time.sleep(min(0.05, max(0.0, deadline - observed_at)))
    return timed_out, completions


def _response_is_bound(
    revision_dir: Path,
    handoff: Mapping[str, Any],
    response_is_complete: Callable[[Path, Path], bool],
    expected_model_identifier: str | None = None,
) -> bool:
    """Delegate terminal-pass authentication to the immutable candidate validator."""
    request_path = revision_dir / str(handoff.get("request_path") or "")
    task = str(handoff.get("task") or "")
    response_path = revision_dir / str(handoff.get("response_path") or "")
    response: dict[str, Any] | None = None
    try:
        response = _read_json(response_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    if not str(((response or {}).get("producer") or {}).get("model_id") or "").strip():
        return False
    if task in {"section_drafting", "prs_narrative_drafting"}:
        try:
            request = _read_json(request_path)
            response = response or _read_json(response_path)
        except (OSError, ValueError, json.JSONDecodeError):
            return False
        if request is None or response is None:
            return False
        return bool(
            response.get("schema_version") == "hermes-response/v2"
            and response.get("request_id") == request.get("request_id")
            and response.get("request_sha256") == request.get("request_sha256")
            and response.get("revision_id") == request.get("revision_id")
            and response.get("task") == request.get("task")
            and response.get("batch_id") == request.get("batch_id")
            and str((response.get("producer") or {}).get("model_id") or "").strip()
        )
    return response_is_complete(revision_dir, request_path)


def wait_for_parent_visual_review(
    run_dir: Path,
    handoffs: Sequence[Mapping[str, Any]],
    remaining_seconds: float,
    *,
    response_is_complete: Callable[[Path, Path], bool],
    progress: Callable[[str, float], None] | None = None,
) -> None:
    """Wait inside the original operation for Desktop-parent page review evidence."""
    reference = _read_json(run_dir / "reference/study.reference.json") or {}
    revision_id = str((reference.get("approval") or {}).get("revision_id") or "")
    revision_dir = run_dir / "revisions" / revision_id
    marker_path = run_dir / "logs/desktop-parent-visual-review.json"
    response_paths = [str(item.get("response_path") or "") for item in handoffs]
    marker_path.parent.mkdir(parents=True, exist_ok=True)

    def record(status: str) -> None:
        marker_path.write_text(json.dumps({
            "status": status,
            "revision_id": revision_id,
            "request_paths": [str(item.get("request_path") or "") for item in handoffs],
            "response_paths": response_paths,
            "completion_requirement": "Desktop parent must inspect every bound page image.",
            "producer_model_policy": "record_actual_nonempty_model_id",
        }, indent=2) + "\n", encoding="utf-8")

    record("awaiting_desktop_parent")
    started = time.monotonic()
    deadline = started + max(0.0, remaining_seconds)
    last_progress = started
    while time.monotonic() < deadline:
        if all(_response_is_bound(
            revision_dir,
            handoff,
            response_is_complete,
        ) for handoff in handoffs):
            record("completed")
            return
        observed = time.monotonic()
        if progress is not None and observed - last_progress >= PROGRESS_INTERVAL_SECONDS:
            progress("desktop_parent_visual_review", max(0.0, deadline - observed))
            last_progress = observed
        time.sleep(0.1)
    record("expired")
    raise RuntimeError("Desktop-parent visual review did not complete before the original operation deadline.")


def _run_handoff_wave(
    run_dir: Path,
    revision_dir: Path,
    handoffs: Sequence[Mapping[str, Any]],
    *,
    timeout_seconds: float,
    response_is_complete: Callable[[Path, Path], bool],
    skill_root: Path = REPO_ROOT,
    sandbox: bool = False,
    progress: Any | None = None,
    hermes_configuration: Mapping[str, Any] = DEFAULT_HERMES_CONFIGURATION,
) -> tuple[bool, list[str]]:
    processes: list[
        tuple[subprocess.Popen[str], Mapping[str, Any], float, Path, Path, Path | None]
    ] = []
    for handoff in handoffs:
        request_id = Path(str(handoff["request_path"])).stem
        stdout_path = run_dir / "logs/hermes-agents" / f"{request_id}.stdout.log"
        stderr_path = run_dir / "logs/hermes-agents" / f"{request_id}.stderr.log"
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        command = [
            "hermes",
            "chat",
            "-q",
            _agent_prompt(
                skill_root,
                revision_dir,
                handoff,
                hermes_configuration=hermes_configuration,
            ),
            "--source",
            str(hermes_configuration["source"]),
            "--max-turns",
            str(hermes_configuration["max_turns"]),
        ]
        if hermes_configuration.get("safe_mode") is True:
            command.append("--safe-mode")
        else:
            command.extend(("--skills", str(hermes_configuration["skill"])))
        sandbox_profile = None
        if sandbox:
            command, sandbox_profile = sandbox_command(skill_root, run_dir, command)
        with (
            stdout_path.open("w", encoding="utf-8") as stdout_handle,
            stderr_path.open("w", encoding="utf-8") as stderr_handle,
        ):
            process = subprocess.Popen(
                command,
                cwd=skill_root,
                env=subprocess_environment(),
                stdout=stdout_handle,
                stderr=stderr_handle,
                text=True,
                start_new_session=True,
            )
        processes.append(
            (process, handoff, started, stdout_path, stderr_path, sandbox_profile)
        )

    handoff_by_process = {
        id(process): handoff
        for process, handoff, _, _, _, _ in processes
    }
    try:
        timed_out, completions = _wait_for_processes(
            [process for process, _, _, _, _, _ in processes],
            timeout_seconds=timeout_seconds,
            progress=progress,
            completion_check=lambda process: _response_is_bound(
                revision_dir,
                handoff_by_process[id(process)],
                response_is_complete,
            ),
        )
    finally:
        for _, _, _, _, _, sandbox_profile in processes:
            if sandbox_profile is not None:
                sandbox_profile.unlink(missing_ok=True)
    missing: list[str] = []
    for process, handoff, started, stdout_path, stderr_path, _ in processes:
        returncode, ended = completions[id(process)]
        response_relative = str(handoff["response_path"])
        response_path = revision_dir / response_relative
        if not response_path.is_file() or response_path.stat().st_size == 0:
            missing.append(response_relative)
        _append_json_line(
            run_dir / "logs/hermes-agent-events.jsonl",
            {
                "request_path": str(handoff["request_path"]),
                "response_path": response_relative,
                "task": handoff.get("task"),
                "batch_id": handoff.get("batch_id"),
                "started_monotonic": started,
                "ended_monotonic": ended,
                "elapsed_seconds": round(ended - started, 3),
                "returncode": returncode,
                "response_exists": response_path.is_file(),
                "stdout_log": stdout_path.relative_to(run_dir).as_posix(),
                "stderr_log": stderr_path.relative_to(run_dir).as_posix(),
            },
        )
    return timed_out, missing


def _state_bound_release_identity(
    candidate_identity: Mapping[str, Any],
    state: Mapping[str, Any],
) -> dict[str, Any]:
    operation_identity = state.get("release_identity") or {}
    if not isinstance(operation_identity, Mapping) or any(
        operation_identity.get(key) != candidate_identity.get(key)
        for key in ("package_fingerprint", "git_commit")
    ):
        raise ValueError("The persisted Desktop operation identity does not match the candidate.")
    return dict(operation_identity)


def _run_controlled_release_certification_operation(
    run_dir: Path,
    *,
    release_root: Path,
    preflight_evidence: Path | None = None,
    operation_id: str = "default",
    desktop_operation: Any | None = None,
    release_identity: Mapping[str, Any] | None = None,
    desktop_opener: Callable[[str], bytes] | None = None,
    parent_visual_reviewer: Callable[[list[Mapping[str, Any]], float, Callable[[Path, Path], bool] | None], None] | None = None,
    verification_response_validator: Callable[[Path, Path], bool] | None = None,
    hermes_configuration: Mapping[str, Any] = DEFAULT_HERMES_CONFIGURATION,
    state_path_resolver: Callable[[Path, str], Path] | None = None,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    release_root = release_root.resolve()
    certified_workflow = None
    if desktop_operation is None:
        certified_workflow, certified_identity = _certified_release(release_root)
        desktop_operation = certified_workflow.run_desktop_operation
        state_path_resolver = certified_workflow.desktop_operation_state_path
        verification_response_validator = certified_workflow.verification_response_is_complete
        release_identity = certified_identity
    elif not str((release_identity or {}).get("package_fingerprint") or ""):
        raise ValueError("An injected controlled operation requires an explicit release fingerprint.")
    release_identity = {
        **dict(release_identity or {}),
        "hermes_configuration": dict(hermes_configuration),
    }
    if desktop_opener is None:
        raise ValueError("Release Certification requires the actual Desktop opener.")
    progress_started = time.monotonic()
    last_progress = [progress_started]

    def progress(stage: str, remaining_seconds: float) -> None:
        observed = time.monotonic()
        _append_json_line(run_dir / "logs/hermes-integration-events.jsonl", {
            "at": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": round(observed - last_progress[0], 3),
            "status": "running",
            "stage": stage,
            "remaining_seconds": round(remaining_seconds, 3),
        })
        last_progress[0] = observed

    def handoff_runner(handoffs: list[Mapping[str, Any]], remaining_seconds: float) -> None:
        if verification_response_validator is None:
            raise RuntimeError("The controlled operation has no candidate verification validator.")
        reference = _read_json(run_dir / "reference/study.reference.json") or {}
        revision_id = str((reference.get("approval") or {}).get("revision_id") or "")
        if not revision_id:
            raise RuntimeError("The approved Run Revision identity is missing.")
        wave_started = time.monotonic()
        _run_handoff_wave(
            run_dir,
            run_dir / "revisions" / revision_id,
            handoffs,
            timeout_seconds=max(0.0, remaining_seconds - CLEANUP_RESERVE_SECONDS),
            response_is_complete=verification_response_validator,
            skill_root=release_root,
            sandbox=True,
            progress=lambda observed_at: progress(
                "waiting",
                max(0.0, remaining_seconds - (observed_at - wave_started)),
            ),
            hermes_configuration=hermes_configuration,
        )

    def parent_visual_fallback(handoffs: list[Mapping[str, Any]], remaining_seconds: float) -> None:
        if parent_visual_reviewer is None:
            raise RuntimeError(
                "The delegated visual reviewer failed; Release Certification requires the Desktop parent to inspect every bound page and write the response."
            )
        if verification_response_validator is None:
            raise RuntimeError("The controlled operation has no candidate verification validator.")
        parent_visual_reviewer(handoffs, remaining_seconds, verification_response_validator)

    if certified_workflow is not None:
        if desktop_operation is not certified_workflow.run_desktop_operation:
            raise ValueError("Release Certification requires the candidate production Desktop operation.")
        if preflight_evidence is None:
            raise ValueError("Candidate production certification requires bound preflight evidence.")
        final_result = certified_workflow.run_production_desktop_operation(
            run_dir,
            parent_visual_reviewer=lambda handoffs, remaining, _revision, _configuration: parent_visual_fallback(
                list(handoffs), remaining,
            ),
            opener=desktop_opener,
            operation_id=operation_id,
            release_identity=release_identity,
            hermes_configuration=hermes_configuration,
            skill_root=release_root,
            certification_preflight=preflight_evidence,
        )
    else:
        controlled_operation = desktop_operation
        if controlled_operation is None:
            raise ValueError("A controlled certification operation was not supplied.")
        final_result = controlled_operation(
            run_dir,
            handoff_runner=handoff_runner,
            fallback_handoff_runner=parent_visual_fallback,
            opener=desktop_opener,
            operation_id=operation_id,
            release_identity=release_identity,
            progress=progress,
            cleanup=lambda _status, _remaining: {
                "owned_processes_reaped": True,
                "late_responses_ignored": True,
            },
        )
    production_execution = certified_workflow is not None
    timed_out = final_result.get("status") == "timeout"
    operation_elapsed = float(final_result.get("elapsed_seconds") or (time.monotonic() - progress_started))
    report = inspect_run(
        run_dir,
        final_result=final_result,
        elapsed_seconds=round(operation_elapsed, 3),
        timed_out=timed_out,
        child_returncode=None,
    )
    report["parent_visual_review"] = final_result.get("parent_visual_review")
    if state_path_resolver is None:
        operation_module = sys.modules.get(str(getattr(desktop_operation, "__module__", "")))
        state_path_resolver = getattr(operation_module, "desktop_operation_state_path", None)
    if state_path_resolver is None:
        raise ValueError("The Desktop operation must expose its canonical persisted-state path resolver.")
    state_path = state_path_resolver(run_dir, operation_id)
    state = _read_json(state_path) or {}
    release_identity = _state_bound_release_identity(release_identity, state)
    report["certification_scope"] = (
        "production_single_case_tracer"
        if production_execution
        else "controlled_single_case_tracer"
    )
    report["release_certification_status"] = "not_full_corpus"
    report["release_identity"] = dict(release_identity)
    report["hermes_configuration"] = dict(hermes_configuration)
    report["desktop_operation_evidence"] = {
        key: state.get(key)
        for key in (
            "started_at", "deadline_at", "runtime_history", "stage_history",
            "stage_timings", "attempt_counters", "soft_budget_events", "cleanup",
        )
    }
    manifest = _read_json(run_dir / str(final_result.get("manifest") or "")) or {}
    manifest_path = run_dir / str(final_result.get("manifest") or "")
    approved_reference = _read_json(manifest_path.parent / "approved-reference.json") or {}
    approval = approved_reference.get("approval") or {}
    working_reference = _read_json(run_dir / "reference/study.reference.json") or {}
    approval_anchor = working_reference.get("approval") or {}
    approval_at = _utc_timestamp(approval.get("approved_at"))
    operation_started_at = _utc_timestamp(state.get("started_at"))
    try:
        persisted_operation_elapsed = float((state.get("result") or {}).get("elapsed_seconds"))
    except (TypeError, ValueError):
        persisted_operation_elapsed = float("nan")
    confirmed_retrieval_at = (
        operation_started_at + timedelta(seconds=persisted_operation_elapsed)
        if operation_started_at is not None and math.isfinite(persisted_operation_elapsed)
        else None
    )
    approval_elapsed = (
        (confirmed_retrieval_at - approval_at).total_seconds()
        if confirmed_retrieval_at is not None and approval_at is not None
        else float("nan")
    )
    report["approval_to_confirmed_retrieval_evidence"] = {
        "status": approval.get("status"),
        "approved_by": approval.get("approved_by"),
        "approved_at": approval.get("approved_at"),
        "revision_id": approval.get("revision_id"),
        "source_sha256": approval.get("source_sha256"),
        "approved_reference_sha256": approval_anchor.get("approved_reference_sha256"),
        "governing_sha256": approval.get("governing_sha256"),
        "confirmed_retrieval_at": confirmed_retrieval_at.isoformat() if confirmed_retrieval_at else None,
        "elapsed_seconds": round(approval_elapsed, 3) if math.isfinite(approval_elapsed) else None,
    }
    render_evidence = ((manifest.get("quality") or {}).get("render_assurance") or {}).get("render") or {}
    report["adapter_attempts"] = {
        "renderer": list(render_evidence.get("renderer_attempts") or []),
        "page_renderer": list(render_evidence.get("page_renderer_attempts") or []),
    }
    report["bound_evidence"] = {}
    for name, path in (
        ("desktop_operation_state", state_path),
        ("delivery_manifest", manifest_path),
    ):
        if path.is_file():
            report["bound_evidence"][name] = {
                "path": path.relative_to(run_dir).as_posix(),
                "sha256": _sha256(path),
                "bytes": path.stat().st_size,
            }
    delivery_confirmed = bool((final_result.get("delivery") or {}).get("confirmed"))
    output_evidence = []
    for item in manifest.get("client_outputs") or []:
        path = run_dir / str(item.get("path") or "")
        confirmed = bool(
            delivery_confirmed
            and path.is_file()
            and path.stat().st_size == int(item.get("bytes") or -1)
            and _sha256(path) == item.get("sha256")
        )
        output_evidence.append({
            "path": item.get("path"),
            "sha256": item.get("sha256"),
            "bytes": item.get("bytes"),
            "confirmed": confirmed,
        })
    report["output_evidence"] = output_evidence
    quality = manifest.get("quality") or {}
    render_assurance = quality.get("render_assurance") or {}
    render = render_assurance.get("render") or {}
    verification = quality.get("verification_evidence") or {}
    visual_qa: dict[str, Any] = {}
    content_response = None
    for evidence_id, evidence in verification.items():
        response_path = manifest_path.parent / str(evidence.get("response") or "")
        response = _read_json(response_path)
        if response is None:
            continue
        if evidence_id == "clinical_content_verification":
            content_response = response
            continue
        for artifact in evidence.get("artifacts") or []:
            artifact_name = str(artifact.get("artifact") or "")
            if not artifact_name:
                continue
            assessments = [
                item for item in response.get("page_assessments") or []
                if str(item.get("artifact") or "") == artifact_name
            ]
            pages = list(artifact.get("pages") or [])
            expected_pages = {
                (int(page.get("page") or 0), str(page.get("sha256") or ""))
                for page in pages
            }
            assessed_pages = {
                (int(assessment.get("page") or 0), str(assessment.get("sha256") or ""))
                for assessment in assessments
            }
            assessments_complete = (
                expected_pages == assessed_pages
                and len(assessments) == len(pages)
                and all(
                    assessment.get("status") == "passed"
                    and set(assessment.get("checks") or []) == CERTIFICATION_VISUAL_CHECKS
                    for assessment in assessments
                )
            )
            visual_qa[artifact_name] = {
                "status": "passed" if assessments_complete else "incomplete",
                "request_sha256": evidence.get("request_sha256"),
                "response_sha256": evidence.get("response_sha256"),
                "producer_model_id": (evidence.get("producer") or {}).get("model_id"),
                "docx_sha256": artifact.get("docx_sha256"),
                "pdf_sha256": artifact.get("pdf_sha256"),
                "page_count": len(pages),
                "page_sha256": [item.get("sha256") for item in pages],
                "checks": sorted({
                    str(check)
                    for assessment in assessments
                    for check in assessment.get("checks") or []
                }),
            }
    expected_docx_artifacts = {
        Path(path).stem for path in report["required_outputs"] if path.endswith(".docx")
    }
    visual_complete = (
        set(visual_qa) == expected_docx_artifacts
        and all(
            item["status"] == "passed"
            and item["page_count"] > 0
            and set(item["checks"]) == CERTIFICATION_VISUAL_CHECKS
            for item in visual_qa.values()
        )
    )
    structural_status = str((render_assurance.get("structural_validation") or {}).get("status") or "")
    content_complete = bool(
        content_response
        and content_response.get("status") == "passed"
        and content_response.get("section_assessments")
        and content_response.get("cross_document_assessments")
    )
    bundle = manifest.get("contracted_template_bundle") or {}
    report["certification_case_evidence"] = {
        "fixture_id": (report.get("input_provenance") or {}).get("fixture_id"),
        "study_type": manifest.get("study_type"),
        "gate_statuses": {
            "source": "passed" if (report.get("input_provenance") or {}).get("status") == "approved_normalization" else "failed",
            "content": "passed" if content_complete else "failed",
            "document_structure": "passed" if structural_status == "structurally_valid" else "failed",
            "prs_xml": "passed" if "study.xml" in report["required_outputs"] and quality.get("status") == "passed" else ("not_applicable" if "study.xml" not in report["required_outputs"] else "failed"),
            "package": "passed" if manifest.get("status") == "passed" else "failed",
            "cross_document_consistency": "passed" if content_complete else "failed",
            "render_assurance": "passed" if render.get("status") == "passed" else "failed",
            "every_page_visual_qa": "passed" if visual_complete else "failed",
            "delivery_confirmation": "passed" if delivery_confirmed and all(item["confirmed"] for item in output_evidence) else "failed",
        },
        "contracted_template_bundle_identity": bundle.get("identity_sha256"),
        "layout_preservation_baseline_identity": (bundle.get("layout_preservation_baseline") or {}).get("sha256"),
        "layout_checks": {
            "natural_section_3_flow": "passed" if visual_complete else "failed",
            "no_orphan_headings": "passed" if visual_complete and all("orphan_heading" in item["checks"] for item in visual_qa.values()) else "failed",
        },
        "visual_qa": visual_qa,
    }
    report_path = run_dir / "logs/hermes-integration-report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def run_release_certification_operation(
    run_dir: Path,
    *,
    release_root: Path,
    preflight_evidence: Path | None = None,
    operation_id: str = "default",
    desktop_opener: Callable[[str], bytes] | None = None,
    parent_visual_reviewer: Callable[[
        list[Mapping[str, Any]], float, Callable[[Path, Path], bool] | None,
    ], None] | None = None,
    hermes_configuration: Mapping[str, Any] = DEFAULT_HERMES_CONFIGURATION,
) -> dict[str, Any]:
    """Run only the immutable candidate's shipped production Desktop adapter."""
    return _run_controlled_release_certification_operation(
        run_dir,
        release_root=release_root,
        preflight_evidence=preflight_evidence,
        operation_id=operation_id,
        desktop_opener=desktop_opener,
        parent_visual_reviewer=parent_visual_reviewer,
        hermes_configuration=hermes_configuration,
    )


def _preflight_evidence(
    path: Path,
    *,
    release_identity: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    evidence = _read_json(path)
    if evidence is None:
        return {}, ["Release Certification preflight evidence is missing or invalid."]
    findings = []
    if evidence.get("schema_version") != "release-certification-preflight/v1":
        findings.append("Release Certification preflight schema is invalid.")
    if evidence.get("status") != "passed":
        findings.append("Release Certification preflight did not pass.")
    candidate = evidence.get("candidate") or {}
    if release_identity is not None and any((
        candidate.get("package_fingerprint") != release_identity.get("package_fingerprint"),
        candidate.get("git_commit") != release_identity.get("git_commit"),
    )):
        findings.append("Preflight evidence is not bound to the certified candidate.")
    checks = evidence.get("checks") or {}
    expected_checks = {
        "static_release_checks",
        "layout_preservation_corpus",
        "deterministic_branch_acceptance_corpus",
        "repository_regression_suite",
    }
    if set(checks) != expected_checks:
        findings.append("Preflight evidence does not contain the exact required checks.")
    expected_arguments = {
        "static_release_checks": [
            "-m", "py_compile", *(f"scripts/{name}.py" for name in ("workflow", "contracts", "drafting", "rendering", "quality", "prs_xml")), "tests/hermes_e2e.py",
        ],
        "layout_preservation_corpus": [
            "-m", "pytest",
            "tests/test_runtime_regressions.py::test_parallel_bundle_identity_preserves_candidate_bytes_and_visible_formatting",
            "tests/test_client_output_acceptance.py::test_every_protocol_and_icf_family_uses_natural_body_pagination",
            "-q",
        ],
        "deterministic_branch_acceptance_corpus": [
            "-m", "pytest", "tests/test_release_gate.py::test_all_six_public_lifecycle_cases_pass_and_publish_exact_sets", "-q",
        ],
        "repository_regression_suite": ["-m", "pytest", "-q"],
    }
    prior_completed: datetime | None = None
    for name in sorted(expected_checks):
        item = checks.get(name) or {}
        if item.get("status") != "passed":
            findings.append(f"Preflight check {name!r} did not pass.")
        if item.get("returncode") != 0 or not isinstance(item.get("command"), list):
            findings.append(f"Preflight check {name!r} has no successful subprocess evidence.")
        elif list(item["command"])[1:] != expected_arguments[name]:
            findings.append(f"Preflight check {name!r} did not execute the required command.")
        started = _utc_timestamp(item.get("started_at"))
        completed = _utc_timestamp(item.get("completed_at"))
        if started is None or completed is None or completed < started:
            findings.append(f"Preflight check {name!r} has invalid timestamps.")
        relative = Path(str(item.get("log_path") or ""))
        log_path = (path.parent / relative).resolve()
        try:
            log_path.relative_to(path.parent.resolve())
        except ValueError:
            findings.append(f"Preflight check {name!r} log escapes its evidence root.")
            continue
        if not log_path.is_file() or _sha256(log_path) != item.get("sha256"):
            findings.append(f"Preflight check {name!r} log hash does not match.")
    for name in (
        "static_release_checks",
        "layout_preservation_corpus",
        "deterministic_branch_acceptance_corpus",
        "repository_regression_suite",
    ):
        item = checks.get(name) or {}
        started = _utc_timestamp(item.get("started_at"))
        completed = _utc_timestamp(item.get("completed_at"))
        if started is not None and prior_completed is not None and started < prior_completed:
            findings.append("Preflight checks did not run in the required cheap-to-expensive order.")
        if completed is not None:
            prior_completed = completed
    evidence_completed = _utc_timestamp(evidence.get("completed_at"))
    if evidence_completed is None or (prior_completed is not None and evidence_completed < prior_completed):
        findings.append("Preflight completion timestamp is invalid.")
    deterministic = checks.get("deterministic_branch_acceptance_corpus") or {}
    if tuple(deterministic.get("case_ids") or ()) != DETERMINISTIC_BRANCH_ACCEPTANCE_CASES:
        findings.append("Preflight evidence does not cover the complete deterministic six-case corpus.")
    if deterministic.get("assurance") not in {
        "synthetic-structural-only",
        "recorded-drafting-structural-only",
    }:
        findings.append("Deterministic drafting/verification evidence is not labelled structural-only.")
    layout = checks.get("layout_preservation_corpus") or {}
    if tuple(layout.get("coverage") or ()) != CERTIFICATION_LAYOUT_COVERAGE:
        findings.append("Preflight evidence does not cover every Protocol and ICF layout family.")
    regression = checks.get("repository_regression_suite") or {}
    if int(regression.get("test_count") or 0) <= 0:
        findings.append("Repository regression evidence has no passing test count.")
    snapshot = evidence.get("snapshot") or {}
    reconstructions = snapshot.get("package_reconstructions") or []
    if (
        snapshot.get("git_commit") != candidate.get("git_commit")
        or snapshot.get("detached") is not True
        or [item.get("phase") for item in reconstructions if isinstance(item, Mapping)] != ["before", "after"]
        or any(
            not isinstance(item, Mapping)
            or item.get("package_fingerprint") != candidate.get("package_fingerprint")
            or item.get("git_commit") != candidate.get("git_commit")
            or not re.fullmatch(r"[0-9a-f]{64}", str(item.get("archive_sha256") or ""))
            for item in reconstructions
        )
    ):
        findings.append("Preflight checks were not bound to a stable detached candidate reconstruction.")
    producer = evidence.get("producer") or {}
    if producer.get("path") != "tests/hermes_e2e.py" or producer.get("sha256") != _sha256(Path(__file__)):
        findings.append("Preflight evidence was not produced by this exact certification harness.")
    if producer.get("git_commit") != candidate.get("git_commit"):
        findings.append("Preflight producer commit does not match the candidate commit.")
    if evidence.get("repository_clean") is not True:
        findings.append("Preflight did not run from a clean checkout.")
    return evidence, findings


def run_release_certification_preflight(
    *,
    release_root: Path,
    evidence_path: Path,
    repository_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    """Execute required checks in a detached exact-commit candidate snapshot."""
    repository_root = repository_root.resolve()
    release_root = release_root.resolve()
    candidate_workflow, release_identity = _certified_release(release_root)
    signing_key = os.environ.get("CLINICAL_DOCUMENT_CERTIFICATION_PRIVATE_KEY")
    if not signing_key:
        raise ValueError("Release Certification preflight requires the production signing key.")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository_root,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=repository_root,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    if head != release_identity["git_commit"] or dirty:
        raise ValueError("Release Certification preflight requires a clean checkout at the candidate commit.")
    snapshot_parent = Path(tempfile.mkdtemp(prefix="release-certification-preflight-"))
    snapshot_root = snapshot_parent / "repository"
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(snapshot_root), head],
        cwd=repository_root, check=True, capture_output=True, text=True,
    )
    command_specs = (
        (
            "static_release_checks",
            [sys.executable, "-m", "py_compile", *(f"scripts/{name}.py" for name in ("workflow", "contracts", "drafting", "rendering", "quality", "prs_xml")), "tests/hermes_e2e.py"],
        ),
        (
            "layout_preservation_corpus",
            [
                sys.executable, "-m", "pytest",
                "tests/test_runtime_regressions.py::test_parallel_bundle_identity_preserves_candidate_bytes_and_visible_formatting",
                "tests/test_client_output_acceptance.py::test_every_protocol_and_icf_family_uses_natural_body_pagination",
                "-q",
            ],
        ),
        (
            "deterministic_branch_acceptance_corpus",
            [sys.executable, "-m", "pytest", "tests/test_release_gate.py::test_all_six_public_lifecycle_cases_pass_and_publish_exact_sets", "-q"],
        ),
        (
            "repository_regression_suite",
            [sys.executable, "-m", "pytest", "-q"],
        ),
    )
    evidence_path = evidence_path.resolve()
    logs = evidence_path.parent / "preflight-logs"
    logs.mkdir(parents=True, exist_ok=True)
    checks: dict[str, Any] = {}
    overall_status = "passed"
    check_environment = subprocess_environment()
    check_environment.pop("CLINICAL_DOCUMENT_CERTIFICATION_PRIVATE_KEY", None)
    reconstructed: list[dict[str, Any]] = []
    try:
        for phase in ("before",):
            archive = snapshot_parent / f"candidate-{phase}.zip"
            completed = subprocess.run(
                [sys.executable, "scripts/workflow.py", "--package-release", str(archive)],
                cwd=snapshot_root, env=check_environment, text=True,
                capture_output=True, check=True,
            )
            package = json.loads(completed.stdout)
            reconstructed.append({
                "phase": phase,
                "package_fingerprint": package["package_fingerprint"],
                "git_commit": package["git_commit"],
                "archive_sha256": _sha256(archive),
            })
        if any(
            item["package_fingerprint"] != release_identity["package_fingerprint"]
            or item["git_commit"] != head
            for item in reconstructed
        ):
            raise ValueError("Detached preflight snapshot does not reconstruct the certified candidate.")
        for name, command in command_specs:
            started_at = datetime.now(timezone.utc).isoformat()
            completed = subprocess.run(
                command, cwd=snapshot_root, env=check_environment,
                text=True, capture_output=True, check=False,
            )
            completed_at = datetime.now(timezone.utc).isoformat()
            log_path = logs / f"{name}.log"
            log_path.write_text(completed.stdout + completed.stderr, encoding="utf-8")
            item: dict[str, Any] = {
                "status": "passed" if completed.returncode == 0 else "failed",
                "command": command,
                "returncode": completed.returncode,
                "started_at": started_at,
                "completed_at": completed_at,
                "log_path": log_path.relative_to(evidence_path.parent).as_posix(),
                "sha256": _sha256(log_path),
            }
            if name == "layout_preservation_corpus":
                item["coverage"] = list(CERTIFICATION_LAYOUT_COVERAGE)
            elif name == "deterministic_branch_acceptance_corpus":
                item["case_ids"] = list(DETERMINISTIC_BRANCH_ACCEPTANCE_CASES)
                item["assurance"] = "recorded-drafting-structural-only"
            elif name == "repository_regression_suite":
                matches = re.findall(r"(\d+) passed", completed.stdout)
                item["test_count"] = int(matches[-1]) if matches else 0
            checks[name] = item
            if completed.returncode != 0:
                overall_status = "failed"
                break
        final_archive = snapshot_parent / "candidate-after.zip"
        final_package = json.loads(subprocess.run(
            [sys.executable, "scripts/workflow.py", "--package-release", str(final_archive)],
            cwd=snapshot_root, env=check_environment, text=True,
            capture_output=True, check=True,
        ).stdout)
        reconstructed.append({
            "phase": "after",
            "package_fingerprint": final_package["package_fingerprint"],
            "git_commit": final_package["git_commit"],
            "archive_sha256": _sha256(final_archive),
        })
        snapshot_dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=snapshot_root, text=True, capture_output=True, check=True,
        ).stdout.strip()
        if (
            snapshot_dirty
            or final_package["package_fingerprint"] != release_identity["package_fingerprint"]
            or final_package["git_commit"] != head
        ):
            raise ValueError("Detached preflight snapshot changed while checks executed.")
        result = {
            "schema_version": "release-certification-preflight/v1",
            "status": overall_status,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "candidate": {**release_identity, "release_root": str(release_root.resolve())},
            "snapshot": {
                "git_commit": head,
                "git_tree": subprocess.run(
                    ["git", "rev-parse", "HEAD^{tree}"], cwd=snapshot_root,
                    text=True, capture_output=True, check=True,
                ).stdout.strip(),
                "detached": subprocess.run(
                    ["git", "symbolic-ref", "-q", "HEAD"], cwd=snapshot_root,
                    text=True, capture_output=True, check=False,
                ).returncode != 0,
                "package_reconstructions": reconstructed,
            },
            "python_runtime": {
                "version": sys.version,
                "implementation": sys.implementation.name,
                "executable_sha256": _sha256(Path(sys.executable).resolve()),
            },
            "repository_clean": True,
            "producer": {
                "path": "tests/hermes_e2e.py",
                "sha256": _sha256(snapshot_root / "tests/hermes_e2e.py"),
                "git_commit": head,
            },
            "checks": checks,
        }
        result = candidate_workflow._sign_release_certification(
            result, Path(signing_key),
        )
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return result
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(snapshot_root)],
            cwd=repository_root, capture_output=True, text=True, check=False,
        )
        shutil.rmtree(snapshot_parent, ignore_errors=True)


def _contained_run_path(run_dir: Path, relative: Any) -> Path | None:
    path = (run_dir / str(relative or "")).resolve()
    try:
        path.relative_to(run_dir.resolve())
    except ValueError:
        return None
    return path


def _case_artifact_findings(
    run_dir: Path,
    report: Mapping[str, Any],
    fixture: Mapping[str, Any] | None,
    certified_workflow: Any,
    derived_evidence: dict[str, Any],
) -> list[str]:
    """Re-derive one case decision from contained state, manifest, outputs, and verifier files."""
    findings: list[str] = []
    bound = report.get("bound_evidence") or {}
    if not {"desktop_operation_state", "delivery_manifest"} <= set(bound):
        return ["Desktop operation or delivery-manifest evidence is missing."]
    loaded: dict[str, tuple[Path, dict[str, Any]]] = {}
    for name in ("desktop_operation_state", "delivery_manifest"):
        item = bound[name]
        path = _contained_run_path(run_dir, item.get("path"))
        if path is None:
            findings.append(f"Bound {name} path escapes its run workspace.")
            continue
        payload = _read_json(path)
        if (
            payload is None
            or _sha256(path) != item.get("sha256")
            or path.stat().st_size != int(item.get("bytes") or -1)
        ):
            findings.append(f"Bound {name} evidence is missing, invalid, or hash-mismatched.")
            continue
        loaded[name] = (path, payload)
    if set(loaded) != {"desktop_operation_state", "delivery_manifest"}:
        return findings
    state_path, state = loaded["desktop_operation_state"]
    manifest_path, manifest = loaded["delivery_manifest"]
    identity = report.get("release_identity") or {}
    state_identity = state.get("release_identity") or {}
    if any(
        state_identity.get(key) != identity.get(key)
        for key in ("package_fingerprint", "git_commit")
    ) or _canonical_sha256(state_identity.get("hermes_configuration") or {}) != _canonical_sha256(report.get("hermes_configuration") or {}):
        findings.append("Persisted Desktop operation identity does not match the case report.")
    if state.get("status") != "passed" or (state.get("result") or {}).get("status") != "passed":
        findings.append("Persisted Desktop operation is not a passing terminal operation.")
    state_result = state.get("result") or {}
    try:
        state_elapsed = float(state_result.get("elapsed_seconds"))
    except (TypeError, ValueError):
        state_elapsed = float("nan")
    if (
        not math.isfinite(state_elapsed)
        or state_elapsed <= 0.0
        or state_elapsed != float(report.get("elapsed_seconds") or 0.0)
    ):
        findings.append("Case timing is not bound to the persisted Desktop operation.")
    state_started = _utc_timestamp(state.get("started_at"))
    report_started = _utc_timestamp((report.get("desktop_operation_evidence") or {}).get("started_at"))
    if state_started is None or report_started is None or state_started != report_started:
        findings.append("Case chronology is not bound to the persisted Desktop operation.")
    state_deadline = _utc_timestamp(state.get("deadline_at"))
    report_deadline = _utc_timestamp((report.get("desktop_operation_evidence") or {}).get("deadline_at"))
    if (
        state_deadline is None
        or report_deadline is None
        or state_deadline != report_deadline
        or state_started is None
        or (state_deadline - state_started).total_seconds() != 1800.0
        or float(state.get("budget_seconds") or 0.0) != 1800.0
    ):
        findings.append("Persisted Desktop operation does not retain the 30-minute correctness ceiling.")
    if (state.get("result") or {}).get("manifest") != manifest_path.relative_to(run_dir).as_posix():
        findings.append("Persisted Desktop operation is not bound to the delivery manifest.")
    if not bool(((state.get("result") or {}).get("delivery") or {}).get("confirmed")):
        findings.append("Persisted Desktop operation has no confirmed delivery.")
    if (state.get("cleanup") or {}).get("owned_processes_reaped") is not True:
        findings.append("Persisted Desktop operation cleanup is incomplete.")
    expected_outputs = list(fixture["expected_outputs"]) if fixture is not None else []
    manifest_outputs = list(manifest.get("client_outputs") or [])
    if manifest.get("status") != "passed" or [Path(str(item.get("path") or "")).name for item in manifest_outputs] != expected_outputs:
        findings.append("Delivery Manifest does not contain the exact passing Branch Document Set.")
    report_outputs = list(report.get("output_evidence") or [])
    if len(report_outputs) != len(manifest_outputs):
        findings.append("Case report output evidence does not match the Delivery Manifest.")
    for manifest_item in manifest_outputs:
        output_path = _contained_run_path(run_dir, manifest_item.get("path"))
        if output_path is None:
            findings.append("Delivered output path escapes its run workspace.")
            continue
        report_item = next((
            item for item in report_outputs
            if item.get("path") == manifest_item.get("path")
        ), None)
        if (
            not output_path.is_file()
            or output_path.stat().st_size != int(manifest_item.get("bytes") or -1)
            or _sha256(output_path) != manifest_item.get("sha256")
            or report_item is None
            or report_item.get("confirmed") is not True
            or any(report_item.get(key) != manifest_item.get(key) for key in ("sha256", "bytes"))
        ):
            findings.append(f"Delivered bytes do not match the manifest for {manifest_item.get('path')!r}.")
    opened = list((state_result.get("delivery") or {}).get("opened") or [])
    opened_by_name = {str(item.get("filename") or ""): item for item in opened}
    if set(opened_by_name) != set(expected_outputs):
        findings.append("Desktop opener confirmation does not cover the exact Branch Document Set.")
    for manifest_item in manifest_outputs:
        name = Path(str(manifest_item.get("path") or "")).name
        opened_item = opened_by_name.get(name) or {}
        if any(opened_item.get(key) != manifest_item.get(key) for key in ("sha256", "bytes")):
            findings.append(f"Desktop opener confirmation does not match delivered bytes for {name!r}.")
    actual_reference: dict[str, Any] | None = None
    if fixture is not None:
        run_input = run_dir / "input/source-input.md"
        run_source = run_dir / "reference/source-of-truth.md"
        revision_source = manifest_path.parent / "approved-source.md"
        revision_reference = manifest_path.parent / "approved-reference.json"
        fixture_paths = fixture["artifact_paths"]
        if not run_input.is_file() or _sha256(run_input) != _sha256(fixture_paths["source_input"]):
            findings.append("Run input does not match the approved synthetic fixture.")
        if (
            not run_source.is_file()
            or _sha256(run_source) != _sha256(fixture_paths["approved_source"])
            or not revision_source.is_file()
            or _sha256(revision_source) != _sha256(run_source)
            or manifest.get("approved_source_sha256") != _sha256(revision_source)
        ):
            findings.append("Approved Source-of-Truth identity is not bound to the Delivery Manifest.")
        actual_reference = _read_json(revision_reference)
        if actual_reference is None:
            findings.append("Approved structured reference is missing or invalid.")
        else:
            actual_comparison = dict(actual_reference)
            actual_comparison.pop("approval", None)
            actual_comparison.pop("generation", None)
            reviewed_comparison = _canonical_reviewed_fixture_reference(fixture, certified_workflow)
            if actual_comparison != reviewed_comparison or manifest.get("approved_reference_sha256") != _sha256(revision_reference):
                findings.append("Approved structured reference identity does not match the reviewed fixture.")
    quality = manifest.get("quality") or {}
    assurance = quality.get("render_assurance") or {}
    render = assurance.get("render") or {}
    if quality.get("status") != "passed":
        findings.append("Delivery Manifest quality status did not pass.")
    if (assurance.get("structural_validation") or {}).get("status") != "structurally_valid":
        findings.append("Document-structure or PRS package validation did not pass.")
    if render.get("status") != "passed":
        findings.append("Render Assurance did not pass.")
    active_renderer = render.get("renderer")
    active_page_renderer = render.get("page_renderer")
    renderer_attempts = list(render.get("renderer_attempts") or [])
    page_renderer_attempts = list(render.get("page_renderer_attempts") or [])
    fonts = assurance.get("fonts")
    substitutions = assurance.get("font_substitutions")
    renderer_passed = any(
        item.get("status") == "passed"
        and (item.get("adapter") or item.get("renderer")) == active_renderer
        for item in renderer_attempts
    )
    page_renderer_passed = any(
        item.get("status") == "passed"
        and (item.get("adapter") or item.get("renderer")) == active_page_renderer
        for item in page_renderer_attempts
    )
    font_evidence_complete = bool(
        isinstance(fonts, Mapping)
        and fonts
        and isinstance(substitutions, Mapping)
        and all(
            isinstance(item, Mapping)
            and item.get("state") in {"available", "missing-or-unusable", "unknown"}
            and str(item.get("match") or "").strip()
            and (
                item.get("state") != "unknown"
                or item.get("resolution") == "render_verified"
            )
            and (
                item.get("state") != "missing-or-unusable"
                or bool(item.get("substitute"))
            )
            for item in fonts.values()
        )
    )
    if not (
        isinstance(active_renderer, Mapping)
        and active_renderer
        and isinstance(active_page_renderer, Mapping)
        and active_page_renderer
        and renderer_attempts
        and page_renderer_attempts
        and renderer_passed
        and page_renderer_passed
        and font_evidence_complete
    ):
        findings.append("Render Assurance omits the Active Renderer, adapter ladders, or resolved font evidence.")
    derived_evidence["render_assurance"] = {
        "active_renderer": active_renderer,
        "active_page_renderer": active_page_renderer,
        "renderer_attempts": renderer_attempts,
        "page_renderer_attempts": page_renderer_attempts,
        "fonts": fonts,
        "font_substitutions": substitutions,
    }
    evidence = report.get("certification_case_evidence") or {}
    bundle = manifest.get("contracted_template_bundle") or {}
    if evidence.get("contracted_template_bundle_identity") != bundle.get("identity_sha256"):
        findings.append("Contracted Template Bundle identity is not bound to the Delivery Manifest.")
    baseline_identity = (bundle.get("layout_preservation_baseline") or {}).get("sha256")
    if evidence.get("layout_preservation_baseline_identity") != baseline_identity or not baseline_identity:
        findings.append("Layout Preservation Baseline identity is not bound to the Delivery Manifest.")
    verification = quality.get("verification_evidence") or {}
    content = verification.get("clinical_content_verification") or {}
    content_request_path = _contained_run_path(manifest_path.parent, content.get("request"))
    content_path = _contained_run_path(manifest_path.parent, content.get("response"))
    content_request = _read_json(content_request_path) if content_request_path is not None else None
    content_response = _read_json(content_path) if content_path is not None else None
    if (
        content_request_path is None
        or content_request is None
        or _sha256(content_request_path) != content.get("request_sha256")
        or content_path is None
        or content_response is None
        or _sha256(content_path) != content.get("response_sha256")
        or content_response.get("request_id") != content_request.get("request_id")
        or content_response.get("request_sha256") != content_request.get("request_sha256")
        or content_response.get("task") != content_request.get("task")
        or content_response.get("status") != "passed"
        or not content_response.get("section_assessments")
        or any(item.get("status") != "passed" for item in content_response.get("section_assessments") or [])
        or not content_response.get("cross_document_assessments")
        or any(item.get("status") != "passed" for item in content_response.get("cross_document_assessments") or [])
        or not certified_workflow.verification_response_is_complete(manifest_path.parent, content_request_path)
    ):
        findings.append("Independent content or Cross-Document Consistency evidence is incomplete.")
    model_identifiers: set[str] = set()
    content_model = str(((content_response or {}).get("producer") or {}).get("model_id") or "").strip()
    if content_model:
        model_identifiers.add(content_model)
    else:
        findings.append("Independent content evidence has no producing model identity.")
    expected_visual_artifacts = {
        Path(name).stem for name in expected_outputs if name.endswith(".docx")
    }
    rendered_artifacts = {
        str(item.get("artifact") or ""): item
        for item in render.get("artifacts") or []
    }
    observed_visual_artifacts = set()
    derived_visual_qa: dict[str, Any] = {}
    for evidence_id, item in verification.items():
        if evidence_id == "clinical_content_verification":
            continue
        request_path = _contained_run_path(manifest_path.parent, item.get("request"))
        response_path = _contained_run_path(manifest_path.parent, item.get("response"))
        request = _read_json(request_path) if request_path is not None else None
        response = _read_json(response_path) if response_path is not None else None
        if (
            request_path is None
            or request is None
            or _sha256(request_path) != item.get("request_sha256")
            or response_path is None
            or response is None
            or _sha256(response_path) != item.get("response_sha256")
            or response.get("request_id") != request.get("request_id")
            or response.get("request_sha256") != request.get("request_sha256")
            or response.get("task") != request.get("task")
            or not certified_workflow.verification_response_is_complete(manifest_path.parent, request_path)
        ):
            findings.append(f"Visual verifier response {evidence_id!r} is missing or hash-mismatched.")
            continue
        for artifact in item.get("artifacts") or []:
            artifact_name = str(artifact.get("artifact") or "")
            observed_visual_artifacts.add(artifact_name)
            pages = list(artifact.get("pages") or [])
            assessments = [
                assessment for assessment in response.get("page_assessments") or []
                if assessment.get("artifact") == artifact_name
            ]
            visual_model = str(((response or {}).get("producer") or {}).get("model_id") or "").strip()
            if visual_model:
                model_identifiers.add(visual_model)
            else:
                findings.append(f"Visual verifier response {evidence_id!r} has no producing model identity.")
            expected_pages = {
                (int(page.get("page") or 0), str(page.get("sha256") or ""))
                for page in pages
            }
            assessed_pages = {
                (int(assessment.get("page") or 0), str(assessment.get("sha256") or ""))
                for assessment in assessments
            }
            render_artifact = rendered_artifacts.get(artifact_name) or {}
            manifest_output = next((
                output for output in manifest_outputs
                if Path(str(output.get("path") or "")).stem == artifact_name
            ), {})
            artifact_files_valid = True
            for relative, digest in (
                (render_artifact.get("docx"), render_artifact.get("docx_sha256")),
                (render_artifact.get("pdf"), render_artifact.get("pdf_sha256")),
            ):
                artifact_path = _contained_run_path(manifest_path.parent, relative)
                artifact_files_valid = bool(
                    artifact_files_valid
                    and artifact_path is not None
                    and artifact_path.is_file()
                    and _sha256(artifact_path) == digest
                )
            for page in pages:
                page_path = _contained_run_path(manifest_path.parent, page.get("path"))
                artifact_files_valid = bool(
                    artifact_files_valid
                    and page_path is not None
                    and page_path.is_file()
                    and _sha256(page_path) == page.get("sha256")
                )
            if (
                not pages
                or expected_pages != assessed_pages
                or len(assessments) != len(pages)
                or any(
                    assessment.get("status") != "passed"
                    or set(assessment.get("checks") or []) != CERTIFICATION_VISUAL_CHECKS
                    for assessment in assessments
                )
                or render_artifact.get("docx_sha256") != manifest_output.get("sha256")
                or artifact.get("docx_sha256") != manifest_output.get("sha256")
                or render_artifact.get("pages") != pages
                or render_artifact.get("renderer") != active_renderer
                or render_artifact.get("page_renderer") != active_page_renderer
                or render_artifact.get("font_evidence") != fonts
                or render_artifact.get("font_substitutions") != substitutions
                or artifact.get("font_evidence") != fonts
                or artifact.get("font_substitutions") != substitutions
                or not artifact_files_valid
            ):
                findings.append(f"Every-page Visual QA is incomplete or stale for {artifact_name!r}.")
            derived_visual_qa[artifact_name] = {
                "status": "passed" if (
                    pages
                    and expected_pages == assessed_pages
                    and len(assessments) == len(pages)
                    and all(
                        assessment.get("status") == "passed"
                        and set(assessment.get("checks") or []) == CERTIFICATION_VISUAL_CHECKS
                        for assessment in assessments
                    )
                ) else "incomplete",
                "request_sha256": item.get("request_sha256"),
                "response_sha256": item.get("response_sha256"),
                "producer_model_id": visual_model or None,
                "docx_sha256": artifact.get("docx_sha256"),
                "pdf_sha256": artifact.get("pdf_sha256"),
                "page_count": len(pages),
                "page_sha256": [page.get("sha256") for page in pages],
                "checks": sorted({
                    str(check)
                    for assessment in assessments
                    for check in assessment.get("checks") or []
                }),
            }
    if observed_visual_artifacts != expected_visual_artifacts:
        findings.append("Visual verifier evidence does not cover the exact delivered DOCX set.")
    drafting_evidence = list(manifest.get("drafting_evidence") or [])
    actual_draft_paths = {
        path.relative_to(manifest_path.parent).as_posix()
        for path in (manifest_path.parent / "hermes/accepted").glob("*.json")
    }
    recorded_draft_paths: set[str] = set()
    for item in drafting_evidence:
        draft_path = _contained_run_path(manifest_path.parent, item.get("path"))
        request_path = _contained_run_path(manifest_path.parent, item.get("accepted_request_path"))
        draft = _read_json(draft_path) if draft_path is not None else None
        request = _read_json(request_path) if request_path is not None else None
        if (
            draft_path is None
            or draft is None
            or _sha256(draft_path) != item.get("sha256")
            or request_path is None
            or request is None
            or _sha256(request_path) != item.get("accepted_request_file_sha256")
            or draft.get("request_id") != item.get("request_id")
            or draft.get("request_id") != request.get("request_id")
            or draft.get("request_sha256") != item.get("request_sha256")
            or draft.get("request_sha256") != request.get("request_sha256")
            or draft.get("producer") != item.get("producer")
        ):
            findings.append("Accepted Hermes drafting evidence is missing, stale, or request-unbound.")
            continue
        recorded_draft_paths.add(draft_path.relative_to(manifest_path.parent).as_posix())
        model_id = str((draft.get("producer") or {}).get("model_id") or "").strip()
        if not model_id:
            findings.append("Accepted Hermes drafting evidence has no producing model identity.")
        else:
            model_identifiers.add(model_id)
    if not drafting_evidence or recorded_draft_paths != actual_draft_paths:
        findings.append("Delivery Manifest does not bind the complete accepted Hermes drafting set.")
    if actual_reference is None or certified_workflow.missing_drafts(
        manifest_path.parent,
        actual_reference,
        certified_workflow.SCRIPT_DIR.parent,
        contracted_bundle=bundle,
    ):
        findings.append("Candidate drafting validation does not accept the complete bound Hermes draft set.")
    if any(
        "recorded" in model.casefold() or "synthetic" in model.casefold()
        for model in model_identifiers
    ):
        findings.append("Recorded or synthetic producers cannot satisfy live drafting or verification gates.")
    derived_evidence["model_identifiers"] = sorted(model_identifiers)
    if not model_identifiers:
        findings.append("Hermes drafting and verifier evidence must record actual producing model identifiers.")
    derived_evidence["visual_qa"] = derived_visual_qa
    approval = (actual_reference or {}).get("approval") or {}
    working_reference = _read_json(run_dir / "reference/study.reference.json") or {}
    approval_anchor = working_reference.get("approval") or {}
    approved_at = _utc_timestamp(approval.get("approved_at"))
    confirmed_retrieval_at = (
        state_started + timedelta(seconds=state_elapsed)
        if state_started is not None and math.isfinite(state_elapsed)
        else None
    )
    approval_elapsed = (
        (confirmed_retrieval_at - approved_at).total_seconds()
        if confirmed_retrieval_at is not None and approved_at is not None
        else float("nan")
    )
    derived_performance = {
        "status": approval.get("status"),
        "approved_by": approval.get("approved_by"),
        "approved_at": approval.get("approved_at"),
        "revision_id": approval.get("revision_id"),
        "source_sha256": approval.get("source_sha256"),
        "approved_reference_sha256": approval_anchor.get("approved_reference_sha256"),
        "governing_sha256": approval.get("governing_sha256"),
        "confirmed_retrieval_at": confirmed_retrieval_at.isoformat() if confirmed_retrieval_at else None,
        "elapsed_seconds": round(approval_elapsed, 3) if math.isfinite(approval_elapsed) else None,
    }
    if (
        approval.get("status") != "approved"
        or approval.get("approved_by") != "Hermes Release Certification"
        or approved_at is None
        or approval.get("revision_id") != manifest.get("revision_id")
        or approval.get("source_sha256") != manifest.get("approved_source_sha256")
        or any(
            approval.get(key) != approval_anchor.get(key)
            for key in (
                "status", "approved_by", "approved_at", "revision_id", "source_sha256",
                "governing_sha256",
            )
        )
        or approval_anchor.get("approved_reference_sha256") != _sha256(manifest_path.parent / "approved-reference.json")
        or state.get("approval_identity") != {
            key: approval_anchor.get(key)
            for key in (
                "status", "approved_by", "approved_at", "revision_id", "source_sha256",
                "approved_reference_sha256", "governing_sha256",
            )
        }
        or not certified_workflow._approval_valid(
            run_dir,
            working_reference,
            contracted_bundle=bundle,
        )[0]
        or (approved_at is not None and state_started is not None and approved_at > state_started)
        or confirmed_retrieval_at is None
        or approval_elapsed <= 0.0
        or report.get("approval_to_confirmed_retrieval_evidence") != derived_performance
    ):
        findings.append("Approval-to-confirmed-retrieval evidence is missing, invalid, or not bound to the immutable revision.")
    derived_evidence["performance"] = derived_performance
    gate_statuses = evidence.get("gate_statuses") or {}
    required_gate_values = {
        gate: ("not_applicable" if gate == "prs_xml" and fixture and fixture.get("study_type") == "Retrospective" else "passed")
        for gate in CERTIFICATION_GATE_NAMES
    }
    if gate_statuses != required_gate_values:
        findings.append("Required gate statuses are incomplete or use an unauthorized not-applicable result.")
    return findings


def _utc_timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _release_certification_evidence_bundle(
    result: Mapping[str, Any],
    *,
    release_root: Path,
    preflight_path: Path,
    reports: Sequence[tuple[str, Path, Mapping[str, Any]]],
    fixtures: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Retain only bounded synthetic evidence already verified by the corpus reducer."""
    entries: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    authorized_roots = {
        release_root.resolve(),
        preflight_path.parent.resolve(),
        *(path.parent.parent.resolve() for _, path, _ in reports),
        *(
            Path(path).parent.resolve()
            for fixture in fixtures.values()
            for path in (fixture.get("artifact_paths") or {}).values()
        ),
    }

    def add(
        identity: str,
        kind: str,
        *,
        source: Path | None = None,
        content: bytes | None = None,
        case_id: str | None = None,
        path: str,
    ) -> dict[str, Any]:
        if source is not None:
            source = source.absolute()
            resolved = source.resolve()
            containing_root = next((
                root for root in authorized_roots
                if resolved == root or root in resolved.parents
            ), None)
            cursor = source
            has_symlink = False
            while containing_root is not None and cursor != containing_root:
                if cursor.is_symlink():
                    has_symlink = True
                    break
                cursor = cursor.parent
            if containing_root is None or has_symlink or not resolved.is_file():
                raise ValueError(f"Certification evidence source is missing or unsafe: {source}")
            content = resolved.read_bytes()
        if content is None:
            raise ValueError("Certification evidence requires source bytes.")
        if path.casefold() in seen_paths:
            raise ValueError(f"Certification evidence path is duplicated: {path}")
        if len(entries) >= 512 or len(content) > 32 * 1024 * 1024:
            raise ValueError("Certification evidence exceeds the governed item limit.")
        seen_paths.add(path.casefold())
        entry = {
            "identity": identity,
            "kind": kind,
            "case_id": case_id,
            "path": path,
            "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "content_base64": base64.b64encode(content).decode("ascii"),
        }
        entries.append(entry)
        return entry

    manifest_path = release_root / "RELEASE-MANIFEST.json"
    manifest = _read_json(manifest_path) or {}
    add("release-manifest", "release_manifest", source=manifest_path, path="global/release-manifest.json")
    add("preflight", "preflight", source=preflight_path, path="global/preflight.json")
    preflight = _read_json(preflight_path) or {}
    for name, kind in (
        ("static_release_checks", "preflight_log"),
        ("layout_preservation_corpus", "layout_preservation"),
        ("deterministic_branch_acceptance_corpus", "deterministic_corpus"),
        ("repository_regression_suite", "preflight_log"),
    ):
        check = (preflight.get("checks") or {}).get(name) or {}
        log_path = _contained_run_path(preflight_path.parent, check.get("log_path"))
        if log_path is None:
            raise ValueError(f"Certification preflight log escapes its evidence root: {name}")
        add(name, kind, source=log_path, path=f"global/preflight-logs/{name}.log")
    python_path = Path(sys.executable).resolve()
    runtime_identity = {
        "release_identity": result.get("release_identity") or {},
        "python": {
            "version": sys.version,
            "implementation": sys.implementation.name,
            "executable_sha256": _sha256(python_path),
        },
        "page_renderer": (manifest.get("inventory") or {}).get("pdf_page_renderer"),
        "hermes_configuration_sha256": {
            fixture: _canonical_sha256(configuration)
            for fixture, configuration in (result.get("hermes_configurations") or {}).items()
        },
        "production_modules": {
            item["path"]: item["sha256"]
            for item in manifest.get("files") or []
            if str(item.get("path") or "").startswith("scripts/")
            and str(item.get("path") or "").endswith(".py")
        },
    }
    add(
        "runtime-identity", "runtime_identity",
        content=json.dumps(runtime_identity, sort_keys=True).encode(),
        path="global/runtime-identity.json",
    )
    case_summaries = {
        str(case.get("fixture_id") or ""): case for case in result.get("cases") or []
    }
    for fixture_id, report_path, report in reports:
        run_dir = report_path.parent.parent
        fixture = fixtures[fixture_id]
        prefix = f"cases/{fixture_id}"
        add(
            f"{fixture_id}-case-report", "case_report", source=report_path,
            case_id=fixture_id, path=f"{prefix}/case-report.json",
        )
        bound = report.get("bound_evidence") or {}
        state_path = _contained_run_path(run_dir, (bound.get("desktop_operation_state") or {}).get("path"))
        manifest_run_path = _contained_run_path(run_dir, (bound.get("delivery_manifest") or {}).get("path"))
        if state_path is None or manifest_run_path is None:
            raise ValueError(f"Certification case bound evidence escapes its run: {fixture_id}")
        add(
            f"{fixture_id}-desktop-state", "desktop_operation_state", source=state_path,
            case_id=fixture_id, path=f"{prefix}/desktop-operation.json",
        )
        add(
            f"{fixture_id}-delivery-manifest", "delivery_manifest", source=manifest_run_path,
            case_id=fixture_id, path=f"{prefix}/delivery-manifest.json",
        )
        delivery_manifest = _read_json(manifest_run_path) or {}
        desktop_state = _read_json(state_path) or {}
        summary = case_summaries[fixture_id]
        add(
            f"{fixture_id}-delivery-confirmation", "delivery_confirmation",
            content=json.dumps({
                "confirmed": bool((((desktop_state.get("result") or {}).get("delivery") or {}).get("confirmed"))),
                "opened": list(summary.get("output_evidence") or []),
            }, sort_keys=True).encode(),
            case_id=fixture_id, path=f"{prefix}/delivery-confirmation.json",
        )
        fixture_paths = fixture["artifact_paths"]
        for name, kind in (
            ("source_input", "fixture_source"),
            ("approved_source", "approved_source"),
            ("approved_reference", "approved_reference"),
        ):
            add(
                f"{fixture_id}-{name.replace('_', '-')}", kind, source=fixture_paths[name],
                case_id=fixture_id, path=f"{prefix}/fixture/{Path(fixture_paths[name]).name}",
            )
        add(
            f"{fixture_id}-fixture-manifest", "fixture_manifest",
            source=fixture_paths["source_input"].parent / "fixture.json",
            case_id=fixture_id, path=f"{prefix}/fixture/fixture.json",
        )
        for output in summary.get("output_evidence") or []:
            source = _contained_run_path(run_dir, output.get("path"))
            if source is None:
                raise ValueError(f"Certification output escapes its run: {fixture_id}")
            add(
                f"{fixture_id}-output-{Path(str(output.get('path'))).name}", "output", source=source,
                case_id=fixture_id, path=f"{prefix}/{output.get('path')}",
            )
        for index, drafting in enumerate(delivery_manifest.get("drafting_evidence") or []):
            for field, kind in (("accepted_request_path", "drafting_request"), ("path", "drafting_response")):
                source = _contained_run_path(manifest_run_path.parent, drafting.get(field))
                if source is None:
                    raise ValueError(f"Certification drafting evidence escapes its run: {fixture_id}")
                add(
                    f"{fixture_id}-{kind}-{index}", kind, source=source,
                    case_id=fixture_id, path=f"{prefix}/drafting/{index}-{kind}.json",
                )
        verification = ((delivery_manifest.get("quality") or {}).get("verification_evidence") or {})
        parent_record = report.get("parent_visual_review") or {}
        if parent_record and parent_record.get("status") != "completed":
            raise ValueError(f"Certification parent-review provenance is invalid: {fixture_id}")
        parent_response_paths = {
            str(path) for path in parent_record.get("response_paths") or []
        }
        for evidence_id, evidence in verification.items():
            request = _contained_run_path(manifest_run_path.parent, evidence.get("request"))
            response = _contained_run_path(manifest_run_path.parent, evidence.get("response"))
            if request is None or response is None:
                raise ValueError(f"Certification verification evidence escapes its run: {fixture_id}")
            add(
                f"{fixture_id}-{evidence_id}-request", "verification_request", source=request,
                case_id=fixture_id, path=f"{prefix}/verification/{evidence_id}-request.json",
            )
            if evidence_id == "clinical_content_verification":
                response_kind = "verification_response"
            elif str(evidence.get("response") or "") in parent_response_paths:
                response_kind = "parent_page_review"
            else:
                response_kind = "delegated_page_review"
            add(
                f"{fixture_id}-{evidence_id}-response", response_kind, source=response,
                case_id=fixture_id, path=f"{prefix}/verification/{evidence_id}-response.json",
            )
            for artifact in evidence.get("artifacts") or []:
                artifact_name = str(artifact.get("artifact") or "")
                pdf_path = next((
                    _contained_run_path(manifest_run_path.parent, item.get("pdf"))
                    for item in (((delivery_manifest.get("quality") or {}).get("render_assurance") or {}).get("render") or {}).get("artifacts") or []
                    if item.get("artifact") == artifact_name
                ), None)
                if pdf_path is None:
                    raise ValueError(f"Certification PDF evidence is missing: {fixture_id}:{artifact_name}")
                add(
                    f"{fixture_id}-{artifact_name}-pdf", "pdf", source=pdf_path,
                    case_id=fixture_id, path=f"{prefix}/rendered/{artifact_name}.pdf",
                )
                for page in artifact.get("pages") or []:
                    page_path = _contained_run_path(manifest_run_path.parent, page.get("path"))
                    if page_path is None:
                        raise ValueError(f"Certification page evidence escapes its run: {fixture_id}")
                    page_number = int(page.get("page") or 0)
                    add(
                        f"{fixture_id}-{artifact_name}-page-{page_number}", "page_image", source=page_path,
                        case_id=fixture_id, path=f"{prefix}/pages/{artifact_name}/page-{page_number}.png",
                    )
        if parent_record:
            add(
                f"{fixture_id}-parent-process-marker", "parent_process_marker",
                content=json.dumps(parent_record, sort_keys=True).encode("utf-8"),
                case_id=fixture_id, path=f"{prefix}/parent-process-review.json",
            )
    total_bytes = sum(item["bytes"] for item in entries)
    if total_bytes > 128 * 1024 * 1024:
        raise ValueError("Certification evidence exceeds the governed bundle limit.")
    metadata = [{key: value for key, value in item.items() if key != "content_base64"} for item in entries]
    return {
        "schema_version": "release-certification-evidence/v1",
        "inventory_sha256": _canonical_sha256(metadata),
        "total_bytes": total_bytes,
        "entries": entries,
    }


def _reduce_release_certification_corpus(
    case_report_paths: Sequence[Path],
    *,
    release_root: Path,
    preflight_path: Path,
    controller_report_sha256: Mapping[str, str],
    output_path: Path | None = None,
    fixture_root: Path = CERTIFICATION_FIXTURE_ROOT,
) -> dict[str, Any]:
    """Reduce case reports bound in memory by the sealed corpus controller."""
    certified_workflow, certified_identity = _certified_release(release_root.resolve())
    fixtures = {
        str(fixture["fixture_id"]): fixture
        for fixture in certification_corpus(fixture_root=fixture_root)
    }
    reports = []
    findings: list[str] = []
    for supplied_path in case_report_paths:
        path = supplied_path.resolve()
        report = _read_json(path)
        if report is None:
            findings.append(f"Case report is missing or invalid: {path}")
            continue
        fixture_id = str(
            (report.get("certification_case_evidence") or {}).get("fixture_id")
            or (report.get("input_provenance") or {}).get("fixture_id")
            or ""
        )
        reports.append((fixture_id, path, report))
    observed_ids = [fixture_id for fixture_id, _, _ in reports]
    if tuple(observed_ids) != CERTIFICATION_CORPUS:
        findings.append(
            "Real case reports must contain the complete corpus once, in declared order; "
            f"observed {observed_ids!r}."
        )
    identities = []
    cases = []
    started_at_values = []
    for fixture_id, path, report in reports:
        fixture = fixtures.get(fixture_id)
        case_findings: list[str] = []
        identity = report.get("release_identity") or {}
        if report.get("certification_scope") != "production_single_case_tracer":
            case_findings.append(
                "Case report was not produced by the sealed production certification adapter."
            )
        if controller_report_sha256.get(str(path)) != _sha256(path):
            case_findings.append(
                "Case report is not byte-bound to the sealed production corpus controller."
            )
        managed_identity = identity.get("managed_hermes_identity")
        identities.append({
            "package_fingerprint": identity.get("package_fingerprint"),
            "git_commit": identity.get("git_commit"),
            "managed_hermes_identity": (
                dict(managed_identity) if isinstance(managed_identity, Mapping) else {}
            ),
        })
        if any(
            identities[-1].get(key) != certified_identity.get(key)
            for key in ("package_fingerprint", "git_commit")
        ):
            case_findings.append("Case report identity does not match the immutable candidate.")
        managed = identities[-1]["managed_hermes_identity"]
        if (
            set(managed) != {
                "launcher", "launcher_sha256", "interpreter",
                "interpreter_target", "interpreter_target_sha256",
            }
            or any(
                not isinstance(managed.get(key), str)
                or not Path(str(managed.get(key))).is_absolute()
                for key in ("launcher", "interpreter", "interpreter_target")
            )
            or any(
                re.fullmatch(r"[0-9a-f]{64}", str(managed.get(key) or "")) is None
                for key in ("launcher_sha256", "interpreter_target_sha256")
            )
        ):
            case_findings.append("Case managed Hermes launcher and interpreter identity is incomplete.")
        if fixture is None:
            case_findings.append("Case is not part of the declared Release Certification Corpus.")
        else:
            fixture_manifest = fixture["artifact_paths"]["source_input"].parent / "fixture.json"
            provenance = report.get("input_provenance") or {}
            if provenance.get("fixture_manifest_sha256") != _sha256(fixture_manifest):
                case_findings.append("Fixture manifest identity does not match repository evidence.")
            if provenance.get("synthetic") is not True or provenance.get("contains_private_data") is not False:
                case_findings.append("Case provenance is not explicitly synthetic and non-private.")
            if _canonical_sha256(report.get("hermes_configuration") or {}) != _canonical_sha256(fixture["hermes_configuration"]):
                case_findings.append("Hermes configuration does not match the approved fixture.")
        derived_evidence: dict[str, Any] = {}
        case_findings.extend(_case_artifact_findings(
            path.parent.parent,
            report,
            fixture,
            certified_workflow,
            derived_evidence,
        ))
        if report.get("outcome") != DiagnosticOutcome.PASSED.value:
            case_findings.append(f"Real Hermes outcome was {report.get('outcome')!r}, not passed.")
        try:
            operation_elapsed = float(report.get("elapsed_seconds"))
        except (TypeError, ValueError):
            operation_elapsed = float("nan")
        try:
            elapsed = float((derived_evidence.get("performance") or {}).get("elapsed_seconds"))
        except (TypeError, ValueError):
            elapsed = float("nan")
        runtime_ceiling = _certification_runtime_ceiling(str(fixture_id or ""))
        if not math.isfinite(elapsed) or elapsed <= 0.0 or _certification_runtime_exceeded(str(fixture_id or ""), elapsed):
            case_findings.append(f"Approval-to-confirmed-retrieval elapsed time {elapsed:.3f}s exceeds the approved {runtime_ceiling:.0f}-second ceiling.")
        if report.get("missing_response_paths") or report.get("invalid_response_paths") or report.get("recorded_response_paths") or report.get("invalid_rejection_paths"):
            case_findings.append("Case contains missing, invalid, recorded, or rejected response evidence.")
        if list(report.get("model_identifiers") or []) != derived_evidence.get("model_identifiers"):
            case_findings.append("Case model identifiers do not match bound drafting and verification producers.")
        if not derived_evidence.get("model_identifiers"):
            case_findings.append("Case has no actual Hermes model identifier evidence.")
        if any("recorded" in str(model).casefold() or "synthetic" in str(model).casefold() for model in derived_evidence.get("model_identifiers") or []):
            case_findings.append("Recorded or synthetic model evidence cannot satisfy the live gate.")
        required_outputs = list(fixture["expected_outputs"]) if fixture is not None else []
        outputs = report.get("output_evidence") or []
        output_names = [Path(str(item.get("path") or "")).name for item in outputs]
        if output_names != required_outputs or any(item.get("confirmed") is not True for item in outputs):
            case_findings.append("Delivered outputs are not the exact confirmed Branch Document Set.")
        evidence = report.get("certification_case_evidence") or {}
        gate_statuses = evidence.get("gate_statuses") or {}
        expected_gate_statuses = {
            gate: ("not_applicable" if gate == "prs_xml" and fixture and fixture.get("study_type") == "Retrospective" else "passed")
            for gate in CERTIFICATION_GATE_NAMES
        }
        if gate_statuses != expected_gate_statuses:
            case_findings.append("One or more required quality gates did not pass.")
        layout_checks = evidence.get("layout_checks") or {}
        if set(layout_checks) != {
            "natural_section_3_flow",
            "no_orphan_headings",
        } or set(layout_checks.values()) != {"passed"}:
            case_findings.append("Layout Preservation, Section 3, or orphan-heading evidence did not pass.")
        expected_visual_artifacts = {
            Path(name).stem for name in required_outputs if name.endswith(".docx")
        }
        visual_qa = evidence.get("visual_qa") or {}
        if visual_qa != derived_evidence.get("visual_qa"):
            case_findings.append("Case Visual QA summary does not match bound every-page verifier evidence.")
        if set(visual_qa) != expected_visual_artifacts or any(
            item.get("status") != "passed"
            or int(item.get("page_count") or 0) <= 0
            or int(item.get("page_count") or 0) != len(item.get("page_sha256") or [])
            or any(len(str(digest)) != 64 for digest in item.get("page_sha256") or [])
            or set(item.get("checks") or []) != CERTIFICATION_VISUAL_CHECKS
            for item in visual_qa.values()
        ):
            case_findings.append("Every-page Visual QA evidence is incomplete or omits required checks.")
        if not evidence.get("contracted_template_bundle_identity") or not evidence.get("layout_preservation_baseline_identity"):
            case_findings.append("Contracted Template Bundle or Layout Preservation identity is missing.")
        started_at = _utc_timestamp((report.get("desktop_operation_evidence") or {}).get("started_at"))
        if started_at is None:
            case_findings.append("Desktop operation start timestamp is missing, invalid, or timezone-naive.")
        else:
            started_at_values.append(started_at)
        cases.append({
            "fixture_id": fixture_id,
            "status": "passed" if not case_findings else "failed",
            "findings": case_findings,
            "elapsed_seconds": elapsed,
            "desktop_operation_elapsed_seconds": operation_elapsed,
            "under_15_minutes": math.isfinite(elapsed) and 0.0 < elapsed < CERTIFICATION_RUNTIME_CEILING_SECONDS,
            "within_approved_runtime": math.isfinite(elapsed) and 0.0 < elapsed and not _certification_runtime_exceeded(str(fixture_id or ""), elapsed),
            "report_sha256": _sha256(path),
            "release_identity": identities[-1],
            "hermes_configuration_sha256": _canonical_sha256(report.get("hermes_configuration") or {}),
            "model_identifiers": list(derived_evidence.get("model_identifiers") or []),
            "output_evidence": outputs,
            "gate_statuses": gate_statuses,
            "layout_checks": layout_checks,
            "visual_qa": derived_evidence.get("visual_qa") or {},
            "render_assurance": derived_evidence.get("render_assurance") or {},
            "contracted_template_bundle_identity": evidence.get("contracted_template_bundle_identity"),
            "layout_preservation_baseline_identity": evidence.get("layout_preservation_baseline_identity"),
        })
        findings.extend(f"{fixture_id or path.name}: {finding}" for finding in case_findings)
    distinct_identities = {
        json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        for identity in identities
    }
    if len(distinct_identities) != 1 or not identities or not all(identities[0].values()):
        findings.append(
            "All real cases must bind the same complete candidate, launcher, and interpreter identity."
        )
    release_identity = identities[0] if len(distinct_identities) == 1 and identities else {}
    preflight, preflight_findings = _preflight_evidence(
        preflight_path.resolve(),
        release_identity=release_identity,
    )
    findings.extend(preflight_findings)
    preflight_completed = _utc_timestamp(preflight.get("completed_at"))
    if preflight_completed is None or len(started_at_values) != len(reports) or any(preflight_completed > started for started in started_at_values):
        findings.append("Deterministic and repository preflight checks did not complete before the real cases began.")
    result = {
        "schema_version": "release-certification-corpus/v1",
        "status": "passed" if not findings else "failed",
        "certification_scope": "complete_three_case_corpus",
        "release_identity": release_identity,
        "hermes_configurations": {
            fixture_id: dict(fixtures[fixture_id]["hermes_configuration"])
            for fixture_id in CERTIFICATION_CORPUS
        },
        "preflight_evidence_sha256": _sha256(preflight_path.resolve()) if preflight_path.is_file() else None,
        "layout_preservation_evidence": (preflight.get("checks") or {}).get("layout_preservation_corpus"),
        "case_order": list(CERTIFICATION_CORPUS),
        "cases": cases,
        "findings": findings,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    if not findings:
        result["evidence_bundle"] = _release_certification_evidence_bundle(
            result,
            release_root=release_root.resolve(),
            preflight_path=preflight_path,
            reports=reports,
            fixtures=fixtures,
        )
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def certify_release_corpus(
    case_report_paths: Sequence[Path],
    *,
    release_root: Path,
    preflight_path: Path,
    output_path: Path | None = None,
    fixture_root: Path = CERTIFICATION_FIXTURE_ROOT,
) -> dict[str, Any]:
    """Fail closed when reports were not captured by the sealed corpus controller."""
    return _reduce_release_certification_corpus(
        case_report_paths,
        release_root=release_root,
        preflight_path=preflight_path,
        controller_report_sha256={},
        output_path=output_path,
        fixture_root=fixture_root,
    )


def run_release_certification_corpus(
    *,
    release_root: Path,
    run_root: Path,
    preflight_path: Path,
    desktop_opener: Callable[[str], bytes],
    desktop_parent_reviewer: Callable[[Sequence[Mapping[str, Any]], float, Path, Mapping[str, Any]], None],
    operation_id: str = "release-corpus",
    fixture_root: Path = CERTIFICATION_FIXTURE_ROOT,
) -> dict[str, Any]:
    """Run the three real cases sequentially, retaining every attempted result."""
    release_root = release_root.resolve()
    run_root = run_root.resolve()
    _, release_identity = _certified_release(release_root)
    preflight, findings = _preflight_evidence(
        preflight_path.resolve(),
        release_identity=release_identity,
    )
    if findings:
        raise ValueError("Real Hermes cases cannot begin before a passing bound preflight: " + "; ".join(findings))
    current_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    current_dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    if current_head != release_identity["git_commit"] or current_dirty:
        raise ValueError("The checkout changed after preflight; real Hermes cases cannot begin.")
    fixtures = certification_corpus(fixture_root=fixture_root)
    run_root.mkdir(parents=True, exist_ok=True)
    attempt_id = datetime.now(timezone.utc).strftime("corpus-%Y%m%dT%H%M%SZ")
    attempt_root = run_root / attempt_id
    attempt_root.mkdir()
    report_paths: list[Path] = []
    controller_report_sha256: dict[str, str] = {}
    for fixture in fixtures:
        fixture_id = str(fixture["fixture_id"])
        run_dir = attempt_root / fixture_id
        prepare_certification_run(
            fixture_id,
            run_dir,
            workflow_root=release_root,
            fixture_root=fixture_root,
        )
        report = run_release_certification_operation(
            run_dir,
            release_root=release_root,
            preflight_evidence=preflight_path,
            operation_id=f"{operation_id}-{fixture_id}",
            hermes_configuration=fixture["hermes_configuration"],
            desktop_opener=desktop_opener,
            parent_visual_reviewer=lambda handoffs, remaining, _validator, current=run_dir, configuration=fixture["hermes_configuration"]: desktop_parent_reviewer(
                handoffs,
                remaining,
                current / "revisions" / str(((_read_json(current / "reference/study.reference.json") or {}).get("approval") or {}).get("revision_id") or ""),
                configuration,
            ),
        )
        report_path = run_dir / "logs/hermes-integration-report.json"
        report_paths.append(report_path)
        controller_report_sha256[str(report_path.resolve())] = _sha256(report_path.resolve())
        try:
            elapsed = float(
                (report.get("approval_to_confirmed_retrieval_evidence") or {}).get("elapsed_seconds")
            )
        except (TypeError, ValueError):
            elapsed = float("nan")
        if (
            report.get("outcome") != DiagnosticOutcome.PASSED.value
            or not math.isfinite(elapsed)
            or elapsed <= 0.0
            or _certification_runtime_exceeded(fixture_id, elapsed)
        ):
            break
    return _reduce_release_certification_corpus(
        report_paths,
        release_root=release_root,
        preflight_path=preflight_path,
        controller_report_sha256=controller_report_sha256,
        output_path=attempt_root / "release-certification-corpus.json",
        fixture_root=fixture_root,
    )


def main(argv: Sequence[str] | None = None) -> int:
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sys.dont_write_bytecode = True
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", default="ambispective-sterling")
    parser.add_argument("--run-root", type=Path, default=Path("/tmp/clinical-hermes-real-e2e"))
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--operation-id", default="default")
    parser.add_argument("--corpus", action="store_true", help="run the complete three-case Release Certification Corpus sequentially")
    parser.add_argument("--run-preflight", action="store_true", help="execute and record the governed checks required before --corpus")
    parser.add_argument("--preflight-evidence", type=Path, help="bound passing deterministic/static/regression evidence required before --corpus")
    parser.add_argument("--desktop-opener-command", type=Path, help="absolute external Desktop opener command; receives one attachment path and emits exact retrieved bytes")
    parser.add_argument("--parent-visual-review-command", type=Path, help="absolute external Desktop-parent visual-review command")
    args = parser.parse_args(argv)
    run_dir = args.run_root / datetime.now(timezone.utc).strftime(
        f"{args.fixture}-%Y%m%dT%H%M%SZ"
    )
    release_root = args.release_root.resolve()
    if args.run_preflight:
        if args.preflight_evidence is None:
            parser.error("--preflight-evidence is required with --run-preflight")
        report = run_release_certification_preflight(
            release_root=release_root,
            evidence_path=args.preflight_evidence,
        )
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if report["status"] == "passed" else 1
    if args.desktop_opener_command is None:
        parser.error("--desktop-opener-command is required for live certification")
    if args.preflight_evidence is None:
        parser.error("--preflight-evidence is required for live certification")
    if args.parent_visual_review_command is None:
        parser.error("--parent-visual-review-command is required for live certification")
    candidate_workflow, _candidate_identity = _certified_release(release_root)
    desktop_opener = candidate_workflow.command_desktop_opener(args.desktop_opener_command)
    desktop_parent_reviewer = candidate_workflow.command_parent_visual_reviewer(
        args.parent_visual_review_command
    )
    if args.corpus:
        if args.preflight_evidence is None:
            parser.error("--preflight-evidence is required with --corpus")
        report = run_release_certification_corpus(
            release_root=release_root,
            run_root=args.run_root,
            preflight_path=args.preflight_evidence,
            desktop_opener=desktop_opener,
            desktop_parent_reviewer=desktop_parent_reviewer,
            operation_id=args.operation_id,
        )
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if report["status"] == "passed" else 1
    fixture = certification_fixture(args.fixture)
    prepare_certification_run(
        args.fixture,
        run_dir,
        workflow_root=release_root,
    )
    report = run_release_certification_operation(
        run_dir,
        release_root=release_root,
        preflight_evidence=args.preflight_evidence,
        operation_id=args.operation_id,
        hermes_configuration=fixture["hermes_configuration"],
        desktop_opener=desktop_opener,
        parent_visual_reviewer=lambda handoffs, remaining, _validator: desktop_parent_reviewer(
            handoffs,
            remaining,
            run_dir / "revisions" / str(((_read_json(run_dir / "reference/study.reference.json") or {}).get("approval") or {}).get("revision_id") or ""),
            fixture["hermes_configuration"],
        ),
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["outcome"] == DiagnosticOutcome.PASSED.value else 1


if __name__ == "__main__":
    raise SystemExit(main())
