#!/usr/bin/env python3
"""Test-only diagnostics for the real Hermes workflow seam."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence

EXPECTED_OUTPUTS = frozenset({"protocol.docx", "icf.docx", "study.xml"})
APPROVED_INPUT_NORMALIZATIONS = {
    "b54328aa5f7f26b53109e4eccb5efc4665a2ed23a90e169da4c7a9aa6c6c768b":
    "ebd829a5de29a10cd9a10b8618b97916bf324480979c1bea4456202cafa1e44f",
}
REPO_ROOT = Path(__file__).resolve().parents[1]
OPERATION_BUDGET_SECONDS = 900.0
CLEANUP_RESERVE_SECONDS = 5.0
PROGRESS_INTERVAL_SECONDS = 60.0
DEFAULT_INPUT = Path.home() / "Downloads/clinical-document-generation-required-inputs/ambispective-required-only.md"
DEFAULT_BASELINE = REPO_ROOT / "runs/AS-SP-001-9-sterling"
FIRST_WAVE_BATCHES = frozenset(
    {
        "protocol-foundations",
        "protocol-operations",
        "protocol-analysis-and-oversight",
        "icf-narrative",
    }
)


@dataclass
class OperationBudget:
    """Persistent wall-clock budget shared by every post-approval action."""

    run_dir: Path
    clock: Any = time.monotonic
    wall_clock: Any = lambda: datetime.now(timezone.utc).isoformat()
    operation_id: str = "default"
    budget_seconds: float = OPERATION_BUDGET_SECONDS
    cleanup_reserve_seconds: float = CLEANUP_RESERVE_SECONDS

    @property
    def path(self) -> Path:
        return self.run_dir / "logs/hermes-operation.json"

    def _save(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def start_or_resume(self) -> dict[str, Any]:
        if self.path.is_file():
            state = json.loads(self.path.read_text(encoding="utf-8"))
            if state.get("operation_id") == self.operation_id:
                return state
        started = self.clock()
        state = {
            "operation_id": self.operation_id,
            "started_at": self.wall_clock(),
            "started_monotonic": started,
            "deadline_monotonic": started + self.budget_seconds,
            "deadline_seconds": self.budget_seconds,
            "status": "running",
            "stage": "approved",
            "events": [],
        }
        self._save(state)
        return state

    def state(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def remaining(self) -> float:
        return max(0.0, float(self.state()["deadline_monotonic"]) - self.clock())

    def child_timeout(self, requested: float | None = None) -> float:
        available = max(0.0, self.remaining() - self.cleanup_reserve_seconds)
        return max(0.0, min(available, requested) if requested is not None else available)

    def event(self, stage: str, *, status: str = "running", **details: Any) -> None:
        state = self.state()
        state["stage"] = stage
        state["status"] = status
        state["events"].append({"at": self.wall_clock(), "stage": stage, "status": status, **details})
        self._save(state)

    def terminal(self, status: str, *, reason: str, cleanup: dict[str, Any] | None = None) -> None:
        state = self.state()
        state.update({"status": status, "ended_at": self.wall_clock(), "stop_reason": reason})
        if cleanup is not None:
            state["cleanup"] = cleanup
        self._save(state)

    def expired(self) -> bool:
        return self.remaining() <= 0.0


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
    revision_id = str((reference.get("approval") or {}).get("revision_id") or "")
    revision_dir = run_dir / "revisions" / revision_id
    request_rows: list[dict[str, Any]] = []
    missing_response_paths: list[str] = []
    invalid_response_paths: list[str] = []
    recorded_response_paths: list[str] = []
    stable_target_attempts: dict[str, list[int]] = {}

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
    if timed_out:
        outcome = DiagnosticOutcome.TIMEOUT
    elif retry_limit_violations:
        outcome = DiagnosticOutcome.RETRY_LIMIT_VIOLATED
    elif (
        final_result.get("status") == "passed"
        and output_files == EXPECTED_OUTPUTS
        and not missing_response_paths
        and not invalid_response_paths
        and not recorded_response_paths
        and not invalid_rejection_paths
    ):
        outcome = DiagnosticOutcome.PASSED
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
        "required_outputs": sorted(EXPECTED_OUTPUTS),
        "retry_limit_violations": retry_limit_violations,
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
) -> tuple[dict[str, Any], int]:
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts/workflow.py"),
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
            cwd=REPO_ROOT,
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


def prepare_disposable_run(baseline: Path, source_input: Path, run_dir: Path) -> dict[str, Any]:
    if run_dir.exists():
        raise FileExistsError(f"Diagnostic run already exists: {run_dir}")
    reference_dir = run_dir / "reference"
    input_dir = run_dir / "input"
    reference_dir.mkdir(parents=True)
    input_dir.mkdir()
    provenance = input_provenance(source_input, baseline / "reference/source-of-truth.md")
    shutil.copy2(baseline / "reference/study.reference.json", reference_dir / "study.reference.json")
    shutil.copy2(baseline / "reference/source-of-truth.md", reference_dir / "source-of-truth.md")
    shutil.copy2(source_input, input_dir / source_input.name)
    (reference_dir / "input-provenance.json").write_text(
        json.dumps(
            {
                **provenance,
                "input_path": f"input/{source_input.name}",
                "approved_source_path": "reference/source-of-truth.md",
            },
            indent=2,
        ) + "\n",
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
    result, _ = _workflow(run_dir, "approve", approved_by="Hermes real-E2E diagnostic")
    if result.get("status") != "passed":
        raise RuntimeError(f"Could not create governed diagnostic revision: {json.dumps(result)}")
    return result


def _agent_prompt(run_dir: Path, revision_dir: Path, handoff: Mapping[str, Any]) -> str:
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
    return f"""Complete one isolated clinical-document Hermes handoff.

Repository: {REPO_ROOT}
Run revision: {revision_dir}
Request: {request_path}
Response: {response_path}
Task: {task}

Read {REPO_ROOT / 'SKILL.md'} and load the clinical-document-drafting skill. Read the request completely. {verification_rule}
Write exact JSON to the response path. Bind every schema, request ID, request hash, task, target, and evidence reference exactly. Use a truthful nonempty producer.model_id. Run the repository's real validator before finishing. Never use recorded_acceptance_response and never fabricate verifier approval. Do not modify production code or the approved source. Return only the absolute response path and SHA-256 after the validated file exists."""


def _wait_for_processes(
    processes: Sequence[subprocess.Popen[str]],
    *,
    timeout_seconds: float,
    progress: Any | None = None,
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


def _run_handoff_wave(
    run_dir: Path,
    revision_dir: Path,
    handoffs: Sequence[Mapping[str, Any]],
    *,
    timeout_seconds: float,
    budget: OperationBudget | None = None,
) -> tuple[bool, list[str]]:
    processes: list[tuple[subprocess.Popen[str], Mapping[str, Any], float, Path, Path]] = []
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
            _agent_prompt(run_dir, revision_dir, handoff),
            "--source",
            "clinical-real-e2e",
            "--max-turns",
            "80",
            "--skills",
            "clinical-document-drafting",
            "--safe-mode",
        ]
        sandbox_profile = None
        if budget is not None:
            command, sandbox_profile = sandbox_command(REPO_ROOT, run_dir, command)
        with (
            stdout_path.open("w", encoding="utf-8") as stdout_handle,
            stderr_path.open("w", encoding="utf-8") as stderr_handle,
        ):
            process = subprocess.Popen(
                command,
                cwd=REPO_ROOT,
                env=subprocess_environment(),
                stdout=stdout_handle,
                stderr=stderr_handle,
                text=True,
                start_new_session=True,
            )
        processes.append((process, handoff, started, stdout_path, stderr_path))
        if sandbox_profile is not None:
            sandbox_profile.unlink(missing_ok=True)

    timed_out, completions = _wait_for_processes(
        [process for process, _, _, _, _ in processes],
        timeout_seconds=timeout_seconds,
        progress=(lambda observed_at: budget.event(
            "waiting", elapsed_seconds=round(observed_at - budget.state()["started_monotonic"], 3)
        )) if budget is not None else None,
    )
    missing: list[str] = []
    for process, handoff, started, stdout_path, stderr_path in processes:
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


def run_real_hermes(
    run_dir: Path,
    *,
    timeout_seconds: float,
    operation_id: str = "default",
    budget: OperationBudget | None = None,
) -> dict[str, Any]:
    budget = budget or OperationBudget(run_dir, operation_id=operation_id, budget_seconds=min(timeout_seconds, OPERATION_BUDGET_SECONDS))
    prior_state = budget.start_or_resume()
    started = time.monotonic()
    final_result: dict[str, Any] = {"status": "invalid_workflow_output", "stage": "generate"}
    child_returncode: int | None = None
    terminal_state = prior_state.get("status") not in {"running", None}
    timed_out = prior_state.get("status") == "timeout"
    if terminal_state:
        final_result = {"status": prior_state["status"], "stage": prior_state.get("stage", "generate")}
    last_progress = -PROGRESS_INTERVAL_SECONDS
    while not terminal_state and not budget.expired() and budget.remaining() > budget.cleanup_reserve_seconds:
        remaining = budget.child_timeout(timeout_seconds - (time.monotonic() - started))
        if remaining <= 0:
            break
        stage = str(final_result.get("stage") or "generate")
        if stage != budget.state().get("stage") or time.monotonic() - started - last_progress >= PROGRESS_INTERVAL_SECONDS:
            budget.event(stage, elapsed_seconds=round(time.monotonic() - started, 3))
            last_progress = time.monotonic() - started
        final_result, child_returncode = _workflow(
            run_dir,
            "generate",
            timeout_seconds=max(0.001, remaining),
        )
        if final_result.get("status") == "timeout":
            timed_out = True
            break
        if final_result.get("status") != "awaiting_hermes":
            break
        revision_id = str(final_result.get("revision_id") or "")
        handoffs = final_result.get("handoffs") or []
        if not revision_id or not handoffs:
            break
        remaining = timeout_seconds - (time.monotonic() - started)
        wave_timed_out, missing = _run_handoff_wave(
            run_dir,
            run_dir / "revisions" / revision_id,
            handoffs,
            timeout_seconds=remaining,
            budget=budget,
        )
        if wave_timed_out:
            timed_out = True
            break
        if missing:
            break
    if budget.expired() or budget.remaining() <= budget.cleanup_reserve_seconds:
        timed_out = True
        final_result = {"status": "timeout", "stage": final_result.get("stage", "generate")}

    report = inspect_run(
        run_dir,
        final_result=final_result,
        elapsed_seconds=round(time.monotonic() - started, 3),
        timed_out=timed_out,
        child_returncode=child_returncode,
    )
    report_path = run_dir / "logs/hermes-integration-report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    budget.terminal(
        "timeout" if timed_out else str(report["outcome"]),
        reason="deadline_exhausted" if timed_out else str(report["outcome"]),
        cleanup={"owned_processes_reaped": True, "late_responses_ignored": timed_out},
    )
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--baseline-run", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--run-root", type=Path, default=Path("/tmp/clinical-hermes-real-e2e"))
    parser.add_argument("--timeout", type=float, default=1800.0)
    parser.add_argument("--operation-id", default="default")
    args = parser.parse_args(argv)
    run_dir = args.run_root / datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ")
    prepare_disposable_run(args.baseline_run.resolve(), args.input.resolve(), run_dir)
    report = run_real_hermes(run_dir, timeout_seconds=args.timeout, operation_id=args.operation_id)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["outcome"] == DiagnosticOutcome.PASSED.value else 1


if __name__ == "__main__":
    raise SystemExit(main())
