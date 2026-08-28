#!/usr/bin/env python3
"""Test-only real-Hermes adapter for the production Desktop Operation seam."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
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
DEFAULT_HERMES_CONFIGURATION = {
    "source": "clinical-release-certification",
    "max_turns": 80,
    "skill": "clinical-document-drafting",
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
) -> dict[str, Any]:
    reference = _read_json(run_dir / "reference/study.reference.json") or {}
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
    valid_delivery = (
        final_result.get("status") == "passed"
        and output_files == required_outputs
        and bool((final_result.get("delivery") or {}).get("confirmed"))
        and not missing_response_paths
        and not invalid_response_paths
        and not recorded_response_paths
        and not invalid_rejection_paths
    )
    if timed_out:
        outcome = DiagnosticOutcome.TIMEOUT
    elif retry_limit_violations:
        outcome = DiagnosticOutcome.RETRY_LIMIT_VIOLATED
    elif valid_delivery and elapsed_seconds >= CERTIFICATION_RUNTIME_CEILING_SECONDS:
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
    verification = task in {
        "clinical_content_verification",
        "rendered_page_visual_verification",
    }
    verification_rule = (
        "Act as an independent verifier. Inspect every requested item; for visual verification, load and inspect every page PNG with the vision tool."
        if verification
        else "Draft only the requested sections from the closed approved evidence package."
    )
    preservation_notes = "\n".join(
        f"- {str(note).strip()}"
        for note in hermes_configuration.get("layout_preservation_notes") or []
        if str(note).strip()
    )
    preservation_rule = (
        "\nLayout Preservation Baseline. Do not normalize or redesign these authority-derived features:\n"
        f"{preservation_notes}\n"
        if verification and preservation_notes
        else ""
    )
    return f"""Complete one isolated clinical-document Hermes handoff.

Certified skill: {skill_root}
Run revision: {revision_dir}
Request: {request_path}
Response: {response_path}
Task: {task}

Read {skill_root / 'SKILL.md'} and load the clinical-document-drafting skill. Read the request completely. {verification_rule}
{preservation_rule}
Write exact JSON to the response path. Bind every schema, request ID, request hash, task, target, and evidence reference exactly. Use a truthful nonempty producer.model_id. Run the repository's real validator before finishing. Never use recorded_acceptance_response and never fabricate verifier approval. Do not modify production code or the approved source. Return only the absolute response path and SHA-256 after the validated file exists."""


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
) -> bool:
    request = _read_json(revision_dir / str(handoff.get("request_path") or ""))
    response = _read_json(revision_dir / str(handoff.get("response_path") or ""))
    if request is None or response is None:
        return False
    return not any((
        response.get("request_id") != request.get("request_id"),
        response.get("request_sha256") != request.get("request_sha256"),
        response.get("task") != request.get("task"),
        not str((response.get("producer") or {}).get("model_id") or "").strip(),
    ))


def wait_for_parent_visual_review(
    run_dir: Path,
    handoffs: Sequence[Mapping[str, Any]],
    remaining_seconds: float,
    *,
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
        }, indent=2) + "\n", encoding="utf-8")

    record("awaiting_desktop_parent")
    started = time.monotonic()
    deadline = started + max(0.0, remaining_seconds)
    last_progress = started
    while time.monotonic() < deadline:
        if all(_response_is_bound(revision_dir, handoff) for handoff in handoffs):
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
            "--skills",
            str(hermes_configuration["skill"]),
        ]
        if hermes_configuration.get("safe_mode") is True:
            command.append("--safe-mode")
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


def run_release_certification_operation(
    run_dir: Path,
    *,
    release_root: Path,
    operation_id: str = "default",
    desktop_operation: Any | None = None,
    release_identity: Mapping[str, Any] | None = None,
    parent_visual_reviewer: Callable[[list[Mapping[str, Any]], float], None] | None = None,
    hermes_configuration: Mapping[str, Any] = DEFAULT_HERMES_CONFIGURATION,
    state_path_resolver: Callable[[Path, str], Path] | None = None,
) -> dict[str, Any]:
    release_root = release_root.resolve()
    if desktop_operation is None:
        certified_workflow, certified_identity = _certified_release(release_root)
        desktop_operation = certified_workflow.run_desktop_operation
        state_path_resolver = certified_workflow.desktop_operation_state_path
        release_identity = certified_identity
    elif not str((release_identity or {}).get("package_fingerprint") or ""):
        raise ValueError("An injected controlled operation requires an explicit release fingerprint.")
    release_identity = {
        **dict(release_identity or {}),
        "hermes_configuration": dict(hermes_configuration),
    }
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
        parent_visual_reviewer(handoffs, remaining_seconds)

    final_result = desktop_operation(
        run_dir,
        handoff_runner=handoff_runner,
        fallback_handoff_runner=parent_visual_fallback,
        opener=lambda path: Path(path).read_bytes(),
        operation_id=operation_id,
        release_identity=release_identity,
        progress=progress,
        cleanup=lambda _status, _remaining: {
            "owned_processes_reaped": True,
            "late_responses_ignored": True,
        },
    )
    timed_out = final_result.get("status") == "timeout"
    operation_elapsed = float(final_result.get("elapsed_seconds") or (time.monotonic() - progress_started))
    report = inspect_run(
        run_dir,
        final_result=final_result,
        elapsed_seconds=round(operation_elapsed, 3),
        timed_out=timed_out,
        child_returncode=None,
    )
    if state_path_resolver is None:
        operation_module = sys.modules.get(str(getattr(desktop_operation, "__module__", "")))
        state_path_resolver = getattr(operation_module, "desktop_operation_state_path", None)
    if state_path_resolver is None:
        raise ValueError("The Desktop operation must expose its canonical persisted-state path resolver.")
    state_path = state_path_resolver(run_dir, operation_id)
    state = _read_json(state_path) or {}
    report["certification_scope"] = "single_case_tracer"
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
    report_path = run_dir / "logs/hermes-integration-report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", default="ambispective-sterling")
    parser.add_argument("--run-root", type=Path, default=Path("/tmp/clinical-hermes-real-e2e"))
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--operation-id", default="default")
    args = parser.parse_args(argv)
    run_dir = args.run_root / datetime.now(timezone.utc).strftime(
        f"{args.fixture}-%Y%m%dT%H%M%SZ"
    )
    release_root = args.release_root.resolve()
    _certified_release(release_root)
    fixture = certification_fixture(args.fixture)
    prepare_certification_run(
        args.fixture,
        run_dir,
        workflow_root=release_root,
    )
    report = run_release_certification_operation(
        run_dir,
        release_root=release_root,
        operation_id=args.operation_id,
        hermes_configuration=fixture["hermes_configuration"],
        parent_visual_reviewer=lambda handoffs, remaining: wait_for_parent_visual_review(
            run_dir,
            handoffs,
            remaining,
            progress=lambda stage, available: _append_json_line(
                run_dir / "logs/hermes-integration-events.jsonl",
                {
                    "at": datetime.now(timezone.utc).isoformat(),
                    "status": "running",
                    "stage": stage,
                    "remaining_seconds": round(available, 3),
                },
            ),
        ),
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["outcome"] == DiagnosticOutcome.PASSED.value else 1


if __name__ == "__main__":
    raise SystemExit(main())
