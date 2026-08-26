from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from hermes_e2e import (
    EXPECTED_OUTPUTS,
    DiagnosticOutcome,
    _run_handoff_wave,
    _wait_for_processes,
    _workflow,
    input_provenance,
    inspect_run,
    subprocess_environment,
    OperationBudget,
    sandbox_command,
)


def test_diagnostic_reports_invalid_hermes_response_for_a_missing_response(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    revision_id = "r-test"
    revision = run_dir / "revisions" / revision_id
    requests = revision / "hermes/requests"
    requests.mkdir(parents=True)
    (run_dir / "reference").mkdir(parents=True)
    (run_dir / "reference/study.reference.json").write_text(
        json.dumps({"approval": {"revision_id": revision_id}, "generation": {"attempts": {}}}),
        encoding="utf-8",
    )
    (requests / "draft.json").write_text(
        json.dumps(
            {
                "request_id": "draft-1",
                "task": "section_drafting",
                "batch_id": "protocol-foundations",
                "attempts": {"protocol.synopsis": 1},
                "response_path": "hermes/responses/draft-1.json",
            }
        ),
        encoding="utf-8",
    )

    report = inspect_run(
        run_dir,
        final_result={"status": "awaiting_hermes", "stage": "drafting"},
        elapsed_seconds=1.25,
        timed_out=False,
        child_returncode=0,
    )

    assert report["outcome"] == DiagnosticOutcome.INVALID_HERMES_RESPONSE.value
    assert report["missing_response_paths"] == ["hermes/responses/draft-1.json"]
    assert report["drafting_request_count"] == 1
    assert report["stable_target_attempts"] == {"protocol.synopsis": [1]}
    assert report["candidate_created"] is False
    assert report["output_published"] is False
    assert report["required_outputs"] == sorted(EXPECTED_OUTPUTS)


def test_subprocess_environment_exposes_hermes_managed_native_tools(tmp_path: Path, monkeypatch) -> None:
    hermes_bin = tmp_path / ".hermes/bin"
    hermes_bin.mkdir(parents=True)
    monkeypatch.setenv("PATH", "/usr/bin")

    environment = subprocess_environment(home=tmp_path)

    assert environment["PATH"].split(":", 1) == [str(hermes_bin), "/usr/bin"]


def test_process_completion_timestamps_are_captured_when_each_process_exits() -> None:
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", f"import time; time.sleep({delay})"],
            start_new_session=True,
        )
        for delay in (0.05, 0.2)
    ]

    timed_out, completions = _wait_for_processes(processes, timeout_seconds=2.0)

    assert timed_out is False
    assert completions[id(processes[0])][1] < completions[id(processes[1])][1]


def test_timeout_cleanup_tolerates_a_process_exiting_before_signal(monkeypatch) -> None:
    class ExitsAtDeadline:
        pid = 12345
        returncode = 0
        polls = iter((None, 0))

        def poll(self):
            return next(self.polls)

    process = ExitsAtDeadline()
    monkeypatch.setattr("hermes_e2e.os.killpg", lambda *_: (_ for _ in ()).throw(AssertionError("must not signal exited process")))

    timed_out, completions = _wait_for_processes([process], timeout_seconds=0.0)

    assert timed_out is False
    assert completions[id(process)][0] == 0


def test_handoff_wave_closes_parent_log_handles(tmp_path: Path, monkeypatch) -> None:
    captured_handles = []

    class CompletedProcess:
        pid = 12345
        returncode = 0

        def poll(self):
            return 0

    def fake_popen(*args, **kwargs):
        captured_handles.extend((kwargs["stdout"], kwargs["stderr"]))
        return CompletedProcess()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    run_dir = tmp_path / "run"
    revision = run_dir / "revisions/r-test"
    revision.mkdir(parents=True)

    _run_handoff_wave(
        run_dir,
        revision,
        [{
            "request_path": "hermes/requests/draft-1.json",
            "response_path": "hermes/responses/draft-1.json",
            "task": "section_drafting",
            "batch_id": "protocol-foundations",
        }],
        timeout_seconds=1.0,
    )

    assert captured_handles
    assert all(handle.closed for handle in captured_handles)


def test_workflow_subprocess_timeout_is_reported_explicitly(tmp_path: Path, monkeypatch) -> None:
    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", raise_timeout)

    result, returncode = _workflow(tmp_path, "generate", timeout_seconds=0.01)

    assert returncode == 124
    assert result == {"status": "timeout", "stage": "generate"}


def test_operation_budget_persists_deadline_across_resume_and_reserves_cleanup(tmp_path: Path) -> None:
    now = [100.0]
    budget = OperationBudget(tmp_path / "run", clock=lambda: now[0], budget_seconds=20.0, cleanup_reserve_seconds=3.0)
    first = budget.start_or_resume()
    now[0] = 112.0
    resumed = OperationBudget(tmp_path / "run", clock=lambda: now[0], budget_seconds=20.0, cleanup_reserve_seconds=3.0)

    assert resumed.start_or_resume()["deadline_monotonic"] == first["deadline_monotonic"]
    assert resumed.remaining() == 8.0
    assert resumed.child_timeout() == 5.0


def test_operation_budget_exhaustion_is_terminal_and_new_operation_is_explicit(tmp_path: Path) -> None:
    now = [0.0]
    run = tmp_path / "run"
    budget = OperationBudget(run, clock=lambda: now[0], budget_seconds=5.0, cleanup_reserve_seconds=1.0)
    budget.start_or_resume()
    now[0] = 5.0
    assert budget.expired()
    budget.terminal("timeout", reason="deadline_exhausted")

    resumed = OperationBudget(run, clock=lambda: now[0], operation_id="default", budget_seconds=99.0)
    assert resumed.start_or_resume()["status"] == "timeout"
    fresh = OperationBudget(run, clock=lambda: now[0], operation_id="new-approved-operation", budget_seconds=99.0)
    assert fresh.start_or_resume()["operation_id"] == "new-approved-operation"


def test_sandbox_launch_denies_repository_writes_but_allows_run_workspace(tmp_path: Path) -> None:
    command, profile = sandbox_command(Path(__file__).resolve().parents[1], tmp_path / "run", ["/bin/sh", "-c", "true"])
    try:
        text = profile.read_text(encoding="utf-8")
        assert command[0].endswith("sandbox-exec")
        assert "deny file-write*" in text
        assert str((tmp_path / "run").resolve()) in text
    finally:
        profile.unlink(missing_ok=True)


def test_input_provenance_requires_an_explicit_approved_normalization(tmp_path: Path) -> None:
    source_input = tmp_path / "required-input.md"
    approved_source = tmp_path / "source-of-truth.md"
    source_input.write_text("raw required input", encoding="utf-8")
    approved_source.write_text("approved normalized source", encoding="utf-8")
    approved = input_provenance(source_input, approved_source, approved_normalizations={
        "27ea2440fecf829c2937093323cf06fa78b222418927401f3e9d3c08fd6684ff":
        "bdfdbf1b0a285881f4660b5b86201908032fd81d0b3ad07ef0557eb2fafc0a35"
    })
    assert approved["status"] == "approved_normalization"

    approved_source.write_text("different source", encoding="utf-8")
    try:
        input_provenance(source_input, approved_source, approved_normalizations={
            "27ea2440fecf829c2937093323cf06fa78b222418927401f3e9d3c08fd6684ff":
            "bdfdbf1b0a285881f4660b5b86201908032fd81d0b3ad07ef0557eb2fafc0a35"
        })
    except ValueError as exc:
        assert "approved normalization" in str(exc)
    else:
        raise AssertionError("unbound normalized source was accepted")


def test_diagnostic_collects_stage_history_rejections_and_first_wave_concurrency(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    revision_id = "r-test"
    revision = run_dir / "revisions" / revision_id
    requests = revision / "hermes/requests"
    responses = revision / "hermes/responses"
    rejected = revision / "hermes/rejected"
    for path in (requests, responses, rejected, run_dir / "reference", run_dir / "logs"):
        path.mkdir(parents=True, exist_ok=True)
    (run_dir / "reference/study.reference.json").write_text(
        json.dumps({"approval": {"revision_id": revision_id}, "generation": {"attempts": {}}}),
        encoding="utf-8",
    )
    batches = (
        "protocol-foundations",
        "protocol-operations",
        "protocol-analysis-and-oversight",
        "icf-narrative",
    )
    request_ids = []
    for index, batch in enumerate(batches):
        request_id = f"draft-{index}"
        request_ids.append(request_id)
        response_path = f"hermes/responses/{request_id}.json"
        (requests / f"{request_id}.json").write_text(
            json.dumps(
                {
                    "request_id": request_id,
                    "request_sha256": str(index) * 64,
                    "task": "section_drafting",
                    "batch_id": batch,
                    "attempts": {f"section-{index}": 1},
                    "response_path": response_path,
                }
            ),
            encoding="utf-8",
        )
        (revision / response_path).write_text(json.dumps({
            "request_id": request_id,
            "request_sha256": str(index) * 64,
            "task": "section_drafting",
            "producer": {"model_id": "test-model"},
        }), encoding="utf-8")
    (rejected / "draft-2.json").write_text(
        json.dumps({"findings": [{"category": "evidence", "issue": "not authorized"}]}),
        encoding="utf-8",
    )
    (run_dir / "logs/hermes-integration-events.jsonl").write_text(
        json.dumps({"status": "awaiting_hermes", "stage": "drafting", "elapsed_seconds": 0.5}) + "\n"
        + json.dumps({"status": "blocked", "stage": "drafting_retry", "elapsed_seconds": 0.25}) + "\n",
        encoding="utf-8",
    )
    agent_events = [
        {
            "request_path": f"hermes/requests/{request_id}.json",
            "batch_id": batch,
            "started_monotonic": 10.0 + index / 100,
            "ended_monotonic": 20.0 + index,
        }
        for index, (request_id, batch) in enumerate(zip(request_ids, batches, strict=True))
    ]
    agent_events.append(
        {
            "request_path": "hermes/requests/draft-1.quality-retry.json",
            "batch_id": "protocol-operations",
            "started_monotonic": 30.0,
            "ended_monotonic": 31.0,
        }
    )
    (run_dir / "logs/hermes-agent-events.jsonl").write_text(
        "\n".join(json.dumps(event) for event in agent_events) + "\n",
        encoding="utf-8",
    )
    (run_dir / "reference/repair-report.md").write_text("# Repair report\n", encoding="utf-8")

    report = inspect_run(
        run_dir,
        final_result={"status": "blocked", "stage": "drafting_retry"},
        elapsed_seconds=2.0,
        timed_out=False,
        child_returncode=1,
    )

    assert report["outcome"] == DiagnosticOutcome.BLOCKED.value
    assert report["status_stage_history"] == [
        {"status": "awaiting_hermes", "stage": "drafting", "elapsed_seconds": 0.5},
        {"status": "blocked", "stage": "drafting_retry", "elapsed_seconds": 0.25},
    ]
    assert report["stage_elapsed_seconds"] == {"drafting": 13.5, "drafting_retry": 1.25}
    assert report["first_four_concurrent"] is True
    assert report["rejected_response_findings"] == [
        {"path": "hermes/rejected/draft-2.json", "findings": [{"category": "evidence", "issue": "not authorized"}]}
    ]
    assert report["repair_report"] == "# Repair report\n"


def test_diagnostic_measures_only_the_four_initial_agents_when_a_retry_exists(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    revision_id = "r-test"
    revision = run_dir / "revisions" / revision_id
    requests = revision / "hermes/requests"
    responses = revision / "hermes/responses"
    for path in (requests, responses, run_dir / "reference", run_dir / "logs"):
        path.mkdir(parents=True)
    (run_dir / "reference/study.reference.json").write_text(
        json.dumps({"approval": {"revision_id": revision_id}}),
        encoding="utf-8",
    )
    batches = (
        "protocol-foundations",
        "protocol-operations",
        "protocol-analysis-and-oversight",
        "icf-narrative",
    )
    events = []
    for index, batch in enumerate(batches):
        request_id = f"r-test.draft.{batch}.initial.a1.{index}"
        response_path = f"hermes/responses/{request_id}.json"
        (requests / f"{request_id}.json").write_text(
            json.dumps({"request_id": request_id, "request_sha256": str(index) * 64, "task": "section_drafting", "batch_id": batch, "attempts": {f"section-{index}": 1}, "response_path": response_path}),
            encoding="utf-8",
        )
        (revision / response_path).write_text(json.dumps({"request_id": request_id, "request_sha256": str(index) * 64, "task": "section_drafting", "producer": {"model_id": "test-model"}}), encoding="utf-8")
        events.append({"request_path": f"hermes/requests/{request_id}.json", "batch_id": batch, "started_monotonic": index * 0.1, "ended_monotonic": 2.0})
    retry_id = "r-test.draft.protocol-foundations.retry.a2.extra"
    retry_response = f"hermes/responses/{retry_id}.json"
    (requests / f"{retry_id}.json").write_text(
        json.dumps({"request_id": retry_id, "request_sha256": "f" * 64, "task": "section_drafting", "batch_id": "protocol-foundations", "attempts": {"section-0": 2}, "response_path": retry_response}),
        encoding="utf-8",
    )
    (revision / retry_response).write_text(json.dumps({"request_id": retry_id, "request_sha256": "f" * 64, "task": "section_drafting", "producer": {"model_id": "test-model"}}), encoding="utf-8")
    events.append({"request_path": f"hermes/requests/{retry_id}.json", "batch_id": "protocol-foundations", "started_monotonic": 3.0, "ended_monotonic": 4.0})
    (run_dir / "logs/hermes-agent-events.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )

    report = inspect_run(
        run_dir,
        final_result={"status": "blocked", "stage": "drafting"},
        elapsed_seconds=4.0,
        timed_out=False,
        child_returncode=1,
    )

    assert report["first_four_concurrent"] is True


def test_diagnostic_reports_malformed_drafting_and_missing_verification_responses(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    revision_id = "r-test"
    revision = run_dir / "revisions" / revision_id
    drafting_requests = revision / "hermes/requests"
    verification_requests = revision / "hermes/verification-requests"
    for path in (drafting_requests, verification_requests, run_dir / "reference"):
        path.mkdir(parents=True)
    (run_dir / "reference/study.reference.json").write_text(
        json.dumps({"approval": {"revision_id": revision_id}}),
        encoding="utf-8",
    )
    drafting_response = "hermes/responses/draft-1.json"
    (drafting_requests / "draft-1.json").write_text(
        json.dumps(
            {
                "request_id": "draft-1",
                "task": "section_drafting",
                "batch_id": "protocol-foundations",
                "attempts": {"introduction": 1},
                "response_path": drafting_response,
            }
        ),
        encoding="utf-8",
    )
    (revision / drafting_response).parent.mkdir(parents=True)
    (revision / drafting_response).write_text(json.dumps({
        "request_id": "draft-1",
        "task": "section_drafting",
        "producer": {"model_id": "test-model"},
    }), encoding="utf-8")
    verification_response = "hermes/verification-responses/visual.json"
    (verification_requests / "visual.json").write_text(
        json.dumps(
            {
                "request_id": "verify-visual",
                "task": "rendered_page_visual_verification",
                "response_path": verification_response,
            }
        ),
        encoding="utf-8",
    )

    report = inspect_run(
        run_dir,
        final_result={"status": "blocked", "stage": "quality"},
        elapsed_seconds=2.0,
        timed_out=False,
        child_returncode=1,
    )

    assert report["outcome"] == DiagnosticOutcome.INVALID_HERMES_RESPONSE.value
    assert report["drafting_request_count"] == 1
    assert report["invalid_response_paths"] == [drafting_response]
    assert report["missing_response_paths"] == [verification_response]


def test_diagnostic_does_not_pass_with_recorded_drafting_provenance(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    revision_id = "r-test"
    revision = run_dir / "revisions" / revision_id
    requests = revision / "hermes/requests"
    responses = revision / "hermes/responses"
    output = run_dir / "output"
    for path in (requests, responses, output, run_dir / "reference"):
        path.mkdir(parents=True)
    (run_dir / "reference/study.reference.json").write_text(
        json.dumps({"approval": {"revision_id": revision_id}}), encoding="utf-8"
    )
    request_id = "r-test.draft.protocol-foundations.initial.a1.test"
    request_sha = "a" * 64
    response_path = f"hermes/responses/{request_id}.json"
    (requests / f"{request_id}.json").write_text(json.dumps({
        "request_id": request_id,
        "request_sha256": request_sha,
        "task": "section_drafting",
        "batch_id": "protocol-foundations",
        "attempts": {"introduction": 1},
        "response_path": response_path,
    }), encoding="utf-8")
    (revision / response_path).write_text(json.dumps({
        "request_id": request_id,
        "request_sha256": request_sha,
        "task": "section_drafting",
        "producer": {"model_id": "recorded_acceptance_response"},
    }), encoding="utf-8")
    for filename in EXPECTED_OUTPUTS:
        (output / filename).write_bytes(b"published")

    report = inspect_run(
        run_dir,
        final_result={"status": "passed", "stage": "delivery"},
        elapsed_seconds=1.0,
        timed_out=False,
        child_returncode=0,
    )

    assert report["outcome"] == DiagnosticOutcome.INVALID_HERMES_RESPONSE.value
    assert report["recorded_response_paths"] == [response_path]


def test_diagnostic_does_not_pass_with_an_invalid_terminal_rejection(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    revision_id = "r-test"
    revision = run_dir / "revisions" / revision_id
    requests = revision / "hermes/requests"
    responses = revision / "hermes/responses"
    rejected = revision / "hermes/rejected"
    output = run_dir / "output"
    for path in (requests, responses, rejected, output, run_dir / "reference"):
        path.mkdir(parents=True)
    (run_dir / "reference/study.reference.json").write_text(
        json.dumps({"approval": {"revision_id": revision_id}}), encoding="utf-8"
    )
    request_id = "r-test.draft.protocol-foundations.initial.a1.test"
    request_sha = "a" * 64
    response_path = f"hermes/responses/{request_id}.json"
    (requests / f"{request_id}.json").write_text(json.dumps({
        "request_id": request_id,
        "request_sha256": request_sha,
        "task": "section_drafting",
        "batch_id": "protocol-foundations",
        "attempts": {"introduction": 1},
        "response_path": response_path,
    }), encoding="utf-8")
    (revision / response_path).write_text(json.dumps({
        "request_id": request_id,
        "request_sha256": request_sha,
        "task": "section_drafting",
        "producer": {"model_id": "live-hermes-model"},
    }), encoding="utf-8")
    (rejected / "terminal.json").write_text(json.dumps({
        "findings": [{"category": "schema", "issue": "terminal response schema mismatch"}],
    }), encoding="utf-8")
    for filename in EXPECTED_OUTPUTS:
        (output / filename).write_bytes(b"published")

    report = inspect_run(
        run_dir,
        final_result={"status": "passed", "stage": "delivery"},
        elapsed_seconds=1.0,
        timed_out=False,
        child_returncode=0,
    )

    assert report["outcome"] == DiagnosticOutcome.INVALID_HERMES_RESPONSE.value
    assert report["invalid_rejection_paths"] == ["hermes/rejected/terminal.json"]
