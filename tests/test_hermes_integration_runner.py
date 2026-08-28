from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

from hermes_e2e import (
    EXPECTED_OUTPUTS,
    DiagnosticOutcome,
    _agent_prompt,
    _certified_release,
    _run_handoff_wave,
    _wait_for_processes,
    certification_fixture,
    _workflow,
    input_provenance,
    inspect_run,
    prepare_certification_run,
    run_release_certification_operation,
    subprocess_environment,
    sandbox_command,
    wait_for_parent_visual_review,
)
import workflow
import drafting


def test_certification_fixture_is_repository_owned_synthetic_and_hash_bound(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "ambispective-sterling"
    fixture_dir.mkdir()
    source_input = fixture_dir / "source-input.md"
    approved_source = fixture_dir / "approved-source.md"
    approved_reference = fixture_dir / "approved-reference.json"
    source_input.write_text("explicitly synthetic input\n", encoding="utf-8")
    approved_source.write_text("explicitly reviewed synthetic source\n", encoding="utf-8")
    approved_reference.write_text(json.dumps({
        "meta": {"study_type": "Ambispective", "icf_template": "Sterling"},
        "approval": {"status": "approved"},
    }), encoding="utf-8")
    hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (source_input, approved_source, approved_reference)
    }
    (fixture_dir / "fixture.json").write_text(json.dumps({
        "schema_version": "release-certification-fixture/v1",
        "fixture_id": "ambispective-sterling",
        "synthetic": True,
        "contains_private_data": False,
        "study_type": "Ambispective",
        "icf_family": "Sterling",
        "expected_outputs": ["icf.docx", "protocol.docx", "study.xml"],
        "artifacts": {
            "source_input": {"path": "source-input.md", "sha256": hashes["source-input.md"]},
            "approved_source": {"path": "approved-source.md", "sha256": hashes["approved-source.md"]},
            "approved_reference": {"path": "approved-reference.json", "sha256": hashes["approved-reference.json"]},
        },
        "hermes_configuration": {
            "source": "clinical-release-certification",
            "max_turns": 80,
            "skill": "clinical-document-drafting",
            "safe_mode": True,
        },
    }), encoding="utf-8")

    fixture = certification_fixture("ambispective-sterling", fixture_root=tmp_path)

    assert fixture["synthetic"] is True
    assert fixture["contains_private_data"] is False
    assert fixture["expected_outputs"] == ["icf.docx", "protocol.docx", "study.xml"]
    assert fixture["artifact_paths"]["approved_reference"] == approved_reference.resolve()

    source_input.write_text("mutated\n", encoding="utf-8")
    try:
        certification_fixture("ambispective-sterling", fixture_root=tmp_path)
    except ValueError as exc:
        assert "hash" in str(exc).casefold()
    else:
        raise AssertionError("A mutated certification fixture was accepted.")


def test_repository_certification_fixture_prepares_an_independent_approved_run(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"

    result = prepare_certification_run(
        "ambispective-sterling",
        run_dir,
        workflow_root=Path(__file__).resolve().parents[1],
    )

    assert result["status"] == "passed"
    assert (run_dir / "input/source-input.md").is_file()
    assert (run_dir / "reference/source-of-truth.md").is_file()
    reference = json.loads((run_dir / "reference/study.reference.json").read_text())
    assert reference["meta"]["study_type"] == "Ambispective"
    assert reference["meta"]["icf_template"] == "Sterling"
    assert reference["approval"]["approved_by"] == "Hermes Release Certification"
    provenance = json.loads((run_dir / "reference/input-provenance.json").read_text())
    assert provenance["fixture_id"] == "ambispective-sterling"
    assert provenance["synthetic"] is True
    assert provenance["status"] == "approved_normalization"


def test_visual_verifier_prompt_preserves_declared_authority_features(tmp_path: Path) -> None:
    prompt = _agent_prompt(
        tmp_path / "release",
        tmp_path / "revision",
        {
            "request_path": "hermes/verification-requests/visual.json",
            "response_path": "hermes/verification-responses/visual.json",
            "task": "rendered_page_visual_verification",
        },
        hermes_configuration={
            "layout_preservation_notes": [
                "The two-line Table 13.3.-1 contact caption is authority-preserved."
            ],
        },
    )

    assert "The two-line Table 13.3.-1 contact caption is authority-preserved." in prompt
    assert "Do not normalize" in prompt
    assert "Do not inspect production code or tests" in prompt


def test_content_verifier_prompt_goes_directly_to_bound_evidence(tmp_path: Path) -> None:
    prompt = _agent_prompt(
        tmp_path / "release",
        tmp_path / "revision",
        {
            "request_path": "hermes/verification-requests/content.json",
            "response_path": "hermes/verification-responses/content.json",
            "task": "clinical_content_verification",
        },
        hermes_configuration={
            "layout_preservation_notes": ["Visual-only authority note."],
        },
    )

    assert "Use the request's bound extracts and assessment matrices directly" in prompt
    assert "Do not inspect production code or tests" in prompt
    assert "Run the repository's real validator" in prompt
    assert "Visual-only authority note." not in prompt


def test_drafting_constraints_require_independent_section_prose() -> None:
    constraints = drafting._request_constraints()

    assert any("exact sentence or paragraph" in item for item in constraints)


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


def test_release_certification_adapter_uses_the_persisted_desktop_operation(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "run"
    revision_id = "r-test"
    (run_dir / "reference").mkdir(parents=True)
    (run_dir / "revisions" / revision_id).mkdir(parents=True)
    (run_dir / "output").mkdir()
    (run_dir / "reference/study.reference.json").write_text(json.dumps({
        "meta": {"study_type": "Retrospective"},
        "approval": {"revision_id": revision_id},
    }), encoding="utf-8")
    payload = b"published"
    output_path = run_dir / "output/protocol.docx"
    output_path.write_bytes(payload)
    manifest = {
        "status": "passed",
        "client_outputs": [{
            "path": "output/protocol.docx",
            "sha256": "b04e5ea201bb040cae53f693f6a38a3e00b62da6039ca248fecd59b7fc842894",
            "bytes": len(payload),
        }],
    }
    manifest_path = run_dir / "revisions" / revision_id / "delivery-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(workflow, "generate", lambda _run_dir, **_kwargs: {
        "status": "passed",
        "stage": "delivery",
        "manifest": manifest_path.relative_to(run_dir).as_posix(),
    })

    report = run_release_certification_operation(
        run_dir,
        release_root=Path(__file__).resolve().parents[1],
        desktop_operation=workflow.run_desktop_operation,
        release_identity={"package_fingerprint": "controlled-candidate"},
        hermes_configuration={
            "source": "clinical-release-certification",
            "max_turns": 80,
            "skill": "clinical-document-drafting",
            "safe_mode": True,
            "reasoning_configuration": "Hermes Desktop governed default",
        },
    )

    assert report["outcome"] == DiagnosticOutcome.PASSED.value
    assert (run_dir / "logs/desktop-operation.json").is_file()
    assert not (run_dir / "logs/hermes-operation.json").exists()
    state = json.loads((run_dir / "logs/desktop-operation.json").read_text())
    assert state["result"]["delivery"]["confirmed"] is True
    assert report["release_identity"]["package_fingerprint"] == "controlled-candidate"
    assert report["hermes_configuration"]["safe_mode"] is True
    assert report["desktop_operation_evidence"]["stage_timings"] == state["stage_timings"]
    assert report["certification_scope"] == "single_case_tracer"
    assert report["release_certification_status"] == "not_full_corpus"
    assert report["adapter_attempts"] == {"renderer": [], "page_renderer": []}
    assert report["bound_evidence"]["delivery_manifest"]["sha256"] == hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    assert report["bound_evidence"]["desktop_operation_state"]["path"] == (
        "logs/desktop-operation.json"
    )
    assert report["output_evidence"] == [{
        "path": "output/protocol.docx",
        "sha256": "b04e5ea201bb040cae53f693f6a38a3e00b62da6039ca248fecd59b7fc842894",
        "bytes": len(payload),
        "confirmed": True,
    }]


def test_release_certification_routes_visual_fallback_to_the_desktop_parent(tmp_path: Path) -> None:
    (tmp_path / "logs").mkdir()
    handoff = {
        "task": "rendered_page_visual_verification",
        "request_path": "hermes/verification-requests/visual.json",
        "response_path": "hermes/verification-responses/visual.json",
    }
    parent_reviews = []

    def controlled_operation(_run_dir, **kwargs):
        kwargs["fallback_handoff_runner"]([handoff], 12.0)
        return {"status": "blocked", "stage": "quality", "elapsed_seconds": 1.0, "client_outputs": []}

    run_release_certification_operation(
        tmp_path,
        release_root=tmp_path,
        desktop_operation=controlled_operation,
        release_identity={"package_fingerprint": "controlled-candidate"},
        parent_visual_reviewer=lambda handoffs, remaining: parent_reviews.append((handoffs, remaining)),
        state_path_resolver=workflow.desktop_operation_state_path,
    )

    assert parent_reviews == [([handoff], 12.0)]


def test_release_report_handles_a_resolved_state_path_behind_a_symlink(tmp_path: Path) -> None:
    real_run = tmp_path / "real-run"
    real_run.mkdir()
    alias = tmp_path / "alias-run"
    alias.symlink_to(real_run, target_is_directory=True)

    def controlled_operation(run_dir, **kwargs):
        state_path = workflow.desktop_operation_state_path(run_dir, kwargs["operation_id"])
        state_path.parent.mkdir(parents=True)
        state_path.write_text(json.dumps({"status": "blocked"}), encoding="utf-8")
        return {"status": "blocked", "stage": "quality", "elapsed_seconds": 1.0, "client_outputs": []}

    report = run_release_certification_operation(
        alias,
        release_root=tmp_path,
        desktop_operation=controlled_operation,
        release_identity={"package_fingerprint": "controlled-candidate"},
        state_path_resolver=workflow.desktop_operation_state_path,
    )

    assert report["bound_evidence"]["desktop_operation_state"]["path"] == "logs/desktop-operation.json"


def test_parent_visual_review_waits_for_bound_desktop_responses(tmp_path: Path) -> None:
    revision = tmp_path / "revisions/r-test"
    request_path = revision / "hermes/verification-requests/visual.json"
    response_path = revision / "hermes/verification-responses/visual.json"
    response_path.parent.mkdir(parents=True)
    request_path.parent.mkdir(parents=True)
    (tmp_path / "reference").mkdir()
    (tmp_path / "reference/study.reference.json").write_text(json.dumps({
        "approval": {"revision_id": "r-test"},
    }), encoding="utf-8")
    request = {
        "request_id": "visual",
        "request_sha256": "a" * 64,
        "task": "rendered_page_visual_verification",
        "response_path": "hermes/verification-responses/visual.json",
    }
    request_path.write_text(json.dumps(request), encoding="utf-8")
    response_path.write_text(json.dumps({
        "request_id": "visual",
        "request_sha256": "a" * 64,
        "task": "rendered_page_visual_verification",
        "producer": {"model_id": "desktop-parent/gpt-5.6-sol"},
    }), encoding="utf-8")

    wait_for_parent_visual_review(
        tmp_path,
        [{
            "request_path": "hermes/verification-requests/visual.json",
            "response_path": "hermes/verification-responses/visual.json",
            "task": "rendered_page_visual_verification",
        }],
        1.0,
    )

    marker = json.loads((tmp_path / "logs/desktop-parent-visual-review.json").read_text())
    assert marker["status"] == "completed"
    assert marker["response_paths"] == ["hermes/verification-responses/visual.json"]


def test_parent_visual_review_reports_progress_while_waiting(tmp_path: Path, monkeypatch) -> None:
    revision = tmp_path / "revisions/r-test"
    request_path = revision / "hermes/verification-requests/visual.json"
    request_path.parent.mkdir(parents=True)
    (tmp_path / "reference").mkdir()
    (tmp_path / "reference/study.reference.json").write_text(json.dumps({
        "approval": {"revision_id": "r-test"},
    }), encoding="utf-8")
    request_path.write_text(json.dumps({
        "request_id": "visual",
        "request_sha256": "a" * 64,
        "task": "rendered_page_visual_verification",
    }), encoding="utf-8")
    ticks = iter([0.0, 0.0, 61.0, 62.0])
    monkeypatch.setattr("hermes_e2e.time.monotonic", lambda: next(ticks))
    monkeypatch.setattr("hermes_e2e.time.sleep", lambda _seconds: None)
    progress = []

    try:
        wait_for_parent_visual_review(
            tmp_path,
            [{
                "request_path": "hermes/verification-requests/visual.json",
                "response_path": "hermes/verification-responses/visual.json",
                "task": "rendered_page_visual_verification",
            }],
            62.0,
            progress=lambda stage, remaining: progress.append((stage, remaining)),
        )
    except RuntimeError:
        pass

    assert progress
    assert progress[0][0] == "desktop_parent_visual_review"


def test_real_release_certification_rejects_the_editable_checkout() -> None:
    try:
        _certified_release(Path(__file__).resolve().parents[1])
    except ValueError as exc:
        assert "editable checkout" in str(exc)
    else:
        raise AssertionError("The editable checkout was accepted for real Release Certification.")


def test_real_release_certification_requires_clean_commit_identity(tmp_path: Path) -> None:
    (tmp_path / "RELEASE-MANIFEST.json").write_text(
        json.dumps({"package_fingerprint": "candidate"}),
        encoding="utf-8",
    )

    try:
        _certified_release(tmp_path)
    except ValueError as exc:
        assert "clean commit" in str(exc)
    else:
        raise AssertionError("A release without clean-commit identity was accepted.")


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


def test_bound_response_completion_terminates_and_reaps_the_owned_worker(monkeypatch) -> None:
    signals = []

    class WorkerWithCompletedResponse:
        pid = 12345
        returncode = None

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.returncode = -15
            return self.returncode

    process = WorkerWithCompletedResponse()
    monkeypatch.setattr("hermes_e2e.os.killpg", lambda pid, sent_signal: signals.append((pid, sent_signal)))

    timed_out, completions = _wait_for_processes(
        [process],
        timeout_seconds=30.0,
        completion_check=lambda _process: True,
    )

    assert timed_out is False
    assert completions[id(process)][0] == -15
    assert signals == [(process.pid, 15)]


def test_wait_reports_progress_while_workers_are_still_running(monkeypatch) -> None:
    class CompletesOnSecondPoll:
        pid = 12345
        returncode = None
        polls = iter((None, 0))

        def poll(self):
            self.returncode = next(self.polls)
            return self.returncode

    progress = []
    monkeypatch.setattr("hermes_e2e.PROGRESS_INTERVAL_SECONDS", 0.0)

    timed_out, _ = _wait_for_processes(
        [CompletesOnSecondPoll()],
        timeout_seconds=1.0,
        progress=lambda observed_at: progress.append(observed_at),
    )

    assert timed_out is False
    assert progress


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


def test_handoff_wave_keeps_sandbox_profile_until_the_worker_finishes(tmp_path: Path, monkeypatch) -> None:
    profile = tmp_path / "worker.sb"
    profile.write_text("(version 1)\n(allow default)\n", encoding="utf-8")

    class CompletedProcess:
        pid = 12345
        returncode = 0

        def poll(self):
            return 0

    monkeypatch.setattr(
        "hermes_e2e.sandbox_command",
        lambda _root, _run_dir, command: (["sandbox-exec", "-f", str(profile), *command], profile),
    )
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: CompletedProcess())

    def observed_wait(processes, **_kwargs):
        assert profile.is_file()
        return False, {id(processes[0]): (0, 2.0)}

    monkeypatch.setattr("hermes_e2e._wait_for_processes", observed_wait)
    revision = tmp_path / "run/revisions/r-test"
    revision.mkdir(parents=True)

    _run_handoff_wave(
        tmp_path / "run",
        revision,
        [{
            "request_path": "hermes/requests/draft-1.json",
            "response_path": "hermes/responses/draft-1.json",
            "task": "section_drafting",
            "batch_id": "protocol-foundations",
        }],
        timeout_seconds=1.0,
        sandbox=True,
    )

    assert not profile.exists()


def test_workflow_subprocess_timeout_is_reported_explicitly(tmp_path: Path, monkeypatch) -> None:
    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", raise_timeout)

    result, returncode = _workflow(tmp_path, "generate", timeout_seconds=0.01)

    assert returncode == 124
    assert result == {"status": "timeout", "stage": "generate"}


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


def test_diagnostic_uses_the_retrospective_branch_output_set_and_requires_delivery(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    revision_id = "r-test"
    (run_dir / "reference").mkdir(parents=True)
    (run_dir / "output").mkdir()
    (run_dir / "reference/study.reference.json").write_text(
        json.dumps({
            "meta": {"study_type": "Retrospective"},
            "approval": {"revision_id": revision_id},
        }),
        encoding="utf-8",
    )
    (run_dir / "output/protocol.docx").write_bytes(b"published")

    without_delivery = inspect_run(
        run_dir,
        final_result={"status": "passed", "stage": "delivery"},
        elapsed_seconds=1.0,
        timed_out=False,
        child_returncode=0,
    )
    with_delivery = inspect_run(
        run_dir,
        final_result={
            "status": "passed",
            "stage": "desktop_delivery",
            "delivery": {"confirmed": True},
        },
        elapsed_seconds=1.0,
        timed_out=False,
        child_returncode=0,
    )
    slow_delivery = inspect_run(
        run_dir,
        final_result={
            "status": "passed",
            "stage": "desktop_delivery",
            "delivery": {"confirmed": True},
        },
        elapsed_seconds=900.0,
        timed_out=False,
        child_returncode=0,
    )

    assert without_delivery["outcome"] != DiagnosticOutcome.PASSED.value
    assert with_delivery["outcome"] == DiagnosticOutcome.PASSED.value
    assert slow_delivery["outcome"] == DiagnosticOutcome.NON_CERTIFYING_RUNTIME.value
    assert slow_delivery["output_published"] is True
    assert with_delivery["required_outputs"] == ["protocol.docx"]


def test_diagnostic_preserves_a_classified_layout_blocker_after_response_invalidation(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    revision = run_dir / "revisions/r-test"
    requests = revision / "hermes/verification-requests"
    requests.mkdir(parents=True)
    (run_dir / "reference").mkdir()
    (run_dir / "reference/study.reference.json").write_text(json.dumps({
        "meta": {"study_type": "Retrospective"},
        "approval": {"revision_id": "r-test"},
    }), encoding="utf-8")
    (requests / "visual.json").write_text(json.dumps({
        "request_id": "visual",
        "request_sha256": "a" * 64,
        "task": "rendered_page_visual_verification",
        "response_path": "hermes/verification-responses/visual.json",
    }), encoding="utf-8")

    report = inspect_run(
        run_dir,
        final_result={
            "status": "blocked",
            "stage": "layout_repair_classification",
            "findings": [{"category": "visual", "issue": "authority feature misclassified"}],
        },
        elapsed_seconds=10.0,
        timed_out=False,
        child_returncode=None,
    )

    assert report["outcome"] == DiagnosticOutcome.BLOCKED.value
    assert report["missing_response_paths"] == ["hermes/verification-responses/visual.json"]


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
