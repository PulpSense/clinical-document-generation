import json
from pathlib import Path
import subprocess

import pytest

import workflow


def _manifest():
    return {
        "status": "passed",
        "client_outputs": [
            {"path": "output/Protocol final.docx", "sha256": "03ac674216f3e15c761ee1a5e255f067953623c8b388b4459e13f978d7c846f4", "bytes": 4},
            {"path": "output/study data.xml", "sha256": "97a6d21df7c51e8289ac1a8c026aaac143e15aa1957f54f42e30d8f8a85c3a55", "bytes": 3},
        ],
    }


def test_desktop_reply_exposes_only_manifest_outputs_as_actionable_file_links(tmp_path):
    reply = workflow.desktop_attachment_reply(_manifest(), run_dir=tmp_path)

    assert reply["type"] == "desktop_file_attachments"
    assert [item["filename"] for item in reply["attachments"]] == ["Protocol final.docx", "study data.xml"]
    assert reply["attachments"][0]["absolute_path"] == (tmp_path / "output/Protocol final.docx").as_posix()
    assert reply["attachments"][0]["link"].startswith("[Protocol final.docx](")
    assert reply["client_outputs_only"] is True


def test_desktop_confirmation_opens_every_file_and_accepts_transport_path_variants(tmp_path):
    files = {
        (tmp_path / "output/Protocol final.docx").as_posix(): b"1234",
        (tmp_path / "output/study data.xml").as_posix(): b"567",
    }
    reply = workflow.desktop_attachment_reply(_manifest(), run_dir=tmp_path)
    opened = []

    def opener(path):
        opened.append(path)
        return files[path]

    result = workflow.confirm_desktop_delivery(_manifest(), reply, opener)

    assert result["status"] == "confirmed"
    assert result["confirmed"] is True
    assert [item["filename"] for item in result["opened"]] == ["Protocol final.docx", "study data.xml"]
    assert opened == list(files)


def test_desktop_confirmation_retries_same_bytes_without_regenerating(tmp_path):
    reply = workflow.desktop_attachment_reply(_manifest(), run_dir=tmp_path)
    calls = []

    def opener(path):
        calls.append(path)
        if len(calls) == 1:
            raise OSError("temporary transfer failure")
        return b"1234" if path.endswith("Protocol final.docx") else b"567"

    result = workflow.confirm_desktop_delivery(_manifest(), reply, opener, retries=1)

    assert result["status"] == "confirmed"
    assert result["opened"][0]["attempts"] == 2
    assert len(calls) == 3


def test_desktop_confirmation_blocks_mismatch_and_does_not_certify_quality(tmp_path):
    reply = workflow.desktop_attachment_reply(_manifest(), run_dir=tmp_path)

    result = workflow.confirm_desktop_delivery(_manifest(), reply, lambda path: b"wrong")

    assert result["status"] == "blocked"
    assert result["confirmed"] is False
    assert result["findings"][0]["category"] == "delivery"
    assert result["findings"][0]["recovery_class"] == "transport_fault"
    assert result["findings"][0]["action"] == "retry_exact_bytes"


def test_desktop_confirmation_blocks_missing_attachment_without_opening_anything(tmp_path):
    reply = workflow.desktop_attachment_reply(_manifest(), run_dir=tmp_path)
    reply["attachments"].pop()
    calls = []

    result = workflow.confirm_desktop_delivery(_manifest(), reply, lambda path: calls.append(path))

    assert result["status"] == "blocked"
    assert calls == []


def test_desktop_operation_routes_handoffs_then_confirms_the_published_manifest(tmp_path, monkeypatch):
    calls = []
    results = iter([
        {"status": "awaiting_hermes", "stage": "drafting", "handoffs": [{"request_path": "draft.json"}]},
        {"status": "passed", "stage": "delivery", "manifest": "revisions/r1/delivery-manifest.json"},
    ])
    manifest = _manifest()
    manifest_path = tmp_path / "revisions/r1/delivery-manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(workflow, "generate", lambda run_dir, **_kwargs: next(results))

    def route(handoffs, remaining_seconds):
        calls.append((handoffs, remaining_seconds))

    result = workflow.run_desktop_operation(
        tmp_path,
        handoff_runner=route,
        opener=lambda path: b"1234" if path.endswith("Protocol final.docx") else b"567",
        budget_seconds=30,
    )

    assert result["status"] == "passed"
    assert result["stage"] == "desktop_delivery"
    assert len(calls) == 1
    assert result["delivery"]["confirmed"] is True
    state = json.loads((tmp_path / "logs/desktop-operation.json").read_text())
    assert state["status"] == "passed"
    assert state["operation_id"] == "default"


def test_desktop_operation_uses_parent_visual_review_when_delegated_review_fails(tmp_path, monkeypatch):
    handoff = {
        "request_path": "hermes/verification-requests/visual.json",
        "response_path": "hermes/verification-responses/visual.json",
        "task": "rendered_page_visual_verification",
        "fallback_owner": "parent",
    }
    results = iter([
        {"status": "awaiting_hermes", "stage": "independent_verification", "revision_id": "r1", "handoffs": [handoff]},
        {"status": "passed", "stage": "delivery", "manifest": "revisions/r1/delivery-manifest.json"},
    ])
    manifest_path = tmp_path / "revisions/r1/delivery-manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps(_manifest()), encoding="utf-8")
    monkeypatch.setattr(workflow, "generate", lambda _run_dir, **_kwargs: next(results))
    parent_reviews = []

    result = workflow.run_desktop_operation(
        tmp_path,
        handoff_runner=lambda *_args: None,
        fallback_handoff_runner=lambda handoffs, _remaining: parent_reviews.extend(handoffs),
        opener=lambda path: b"1234" if path.endswith("Protocol final.docx") else b"567",
        budget_seconds=30,
    )

    assert result["status"] == "passed"
    assert parent_reviews == [handoff]


def test_desktop_operation_routes_parent_takeover_without_an_optional_second_runner(tmp_path, monkeypatch):
    handoff = {
        "request_path": "hermes/verification-requests/visual.json",
        "response_path": "hermes/verification-responses/visual.json",
        "task": "rendered_page_visual_verification",
        "fallback_owner": "parent",
    }
    results = iter([
        {"status": "awaiting_hermes", "stage": "independent_verification", "revision_id": "r1", "handoffs": [handoff]},
        {"status": "blocked", "stage": "quality", "findings": [], "client_outputs": []},
    ])
    monkeypatch.setattr(workflow, "generate", lambda _run_dir, **_kwargs: next(results))
    routed = []

    result = workflow.run_desktop_operation(
        tmp_path,
        handoff_runner=lambda handoffs, _remaining: routed.append(handoffs),
        opener=lambda _path: b"unused",
        budget_seconds=30,
    )

    assert result["status"] == "blocked"
    assert len(routed) == 2
    assert routed[1][0]["response_path"] == handoff["response_path"]
    assert routed[1][0]["reviewer_owner"] == "parent"


def test_desktop_operation_uses_one_persistent_deadline_and_does_not_resume_after_timeout(tmp_path, monkeypatch):
    now = [100.0]
    generated = []
    monkeypatch.setattr(workflow, "generate", lambda run_dir, **_kwargs: generated.append(True) or {
        "status": "awaiting_hermes",
        "stage": "drafting",
        "handoffs": [{"request_path": "draft.json"}],
    })

    def route(handoffs, remaining_seconds):
        now[0] = 111.0

    first = workflow.run_desktop_operation(
        tmp_path,
        handoff_runner=route,
        opener=lambda path: b"unused",
        budget_seconds=10,
        clock=lambda: now[0],
    )
    second = workflow.run_desktop_operation(
        tmp_path,
        handoff_runner=route,
        opener=lambda path: b"unused",
        budget_seconds=99,
        clock=lambda: now[0],
    )

    assert first["status"] == second["status"] == "timeout"
    assert first["stage"] == second["stage"] == "desktop_operation"
    assert len(generated) == 1
    assert second["deadline_at_epoch"] == first["deadline_at_epoch"]


def test_desktop_operation_resume_uses_wall_time_across_monotonic_epochs_and_runtimes(tmp_path, monkeypatch):
    monotonic = [1000.0]
    wall_time = [10_000.0]
    first_runtime = {
        "executable": "/opt/python3.10",
        "implementation": "CPython",
        "version": "3.10.14",
    }
    second_runtime = {
        "executable": "/opt/python3.11",
        "implementation": "CPython",
        "version": "3.11.15",
    }
    interrupted = iter([
        {"status": "awaiting_hermes", "stage": "drafting", "handoffs": [{"request_path": "draft.json"}]},
    ])
    monkeypatch.setattr(workflow, "generate", lambda _run_dir, **_kwargs: next(interrupted))

    def interrupt(_handoffs, _remaining_seconds):
        wall_time[0] = 10_008.0
        monotonic[0] = 1008.0
        raise KeyboardInterrupt

    try:
        workflow.run_desktop_operation(
            tmp_path,
            handoff_runner=interrupt,
            opener=lambda _path: b"unused",
            budget_seconds=20.0,
            clock=lambda: monotonic[0],
            wall_clock=lambda: wall_time[0],
            runtime_identity=first_runtime,
        )
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError("The simulated process interruption was not propagated.")

    monotonic[0] = 4.0
    wall_time[0] = 10_012.0
    monkeypatch.setattr(workflow, "generate", lambda _run_dir, **_kwargs: {
        "status": "awaiting_hermes",
        "stage": "drafting",
        "handoffs": [{"request_path": "draft.json"}],
    })

    def exhaust(_handoffs, remaining_seconds):
        assert remaining_seconds == 8.0
        monotonic[0] = 12.0

    resumed = workflow.run_desktop_operation(
        tmp_path,
        handoff_runner=exhaust,
        opener=lambda _path: b"unused",
        budget_seconds=999.0,
        clock=lambda: monotonic[0],
        wall_clock=lambda: wall_time[0],
        runtime_identity=second_runtime,
    )

    assert resumed["status"] == "timeout"
    assert resumed["elapsed_seconds"] == 20.0
    assert resumed["deadline_at_epoch"] == 10_020.0
    state = json.loads((tmp_path / "logs/desktop-operation.json").read_text())
    assert [item["version"] for item in state["runtime_history"]] == ["3.10.14", "3.11.15"]


def test_desktop_operation_persists_deadline_before_first_generate(tmp_path, monkeypatch):
    monotonic = [100.0]
    wall_time = [10_000.0]

    def interrupt_during_generate(_run_dir, **_kwargs):
        state = json.loads((tmp_path / "logs/desktop-operation.json").read_text())
        assert state["status"] == "running"
        assert state["deadline_at_epoch"] == 10_020.0
        raise KeyboardInterrupt

    monkeypatch.setattr(workflow, "generate", interrupt_during_generate)
    try:
        workflow.run_desktop_operation(
            tmp_path,
            handoff_runner=lambda *_args: None,
            opener=lambda _path: b"unused",
            budget_seconds=20.0,
            clock=lambda: monotonic[0],
            wall_clock=lambda: wall_time[0],
        )
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError("The simulated process interruption was not propagated.")

    monotonic[0] = 2.0
    wall_time[0] = 10_015.0
    monkeypatch.setattr(workflow, "generate", lambda _run_dir, **_kwargs: {
        "status": "awaiting_hermes",
        "stage": "drafting",
        "handoffs": [{"request_path": "draft.json"}],
    })

    def exhaust(_handoffs, remaining_seconds):
        assert remaining_seconds == 5.0
        monotonic[0] = 7.0

    resumed = workflow.run_desktop_operation(
        tmp_path,
        handoff_runner=exhaust,
        opener=lambda _path: b"unused",
        budget_seconds=999.0,
        clock=lambda: monotonic[0],
        wall_clock=lambda: wall_time[0],
    )

    assert resumed["status"] == "timeout"
    assert resumed["deadline_at_epoch"] == 10_020.0


def test_resumed_elapsed_time_keeps_truthful_performance_classification(tmp_path, monkeypatch):
    monotonic = [100.0]
    wall_time = [10_000.0]
    monkeypatch.setattr(workflow, "generate", lambda _run_dir, **_kwargs: {
        "status": "awaiting_hermes",
        "stage": "drafting",
        "handoffs": [{"request_path": "draft.json"}],
    })

    def interrupt(_handoffs, _remaining_seconds):
        monotonic[0] = 200.0
        wall_time[0] = 10_100.0
        raise KeyboardInterrupt

    try:
        workflow.run_desktop_operation(
            tmp_path,
            handoff_runner=interrupt,
            opener=lambda _path: b"unused",
            budget_seconds=800.0,
            clock=lambda: monotonic[0],
            wall_clock=lambda: wall_time[0],
        )
    except KeyboardInterrupt:
        pass

    monotonic[0] = 5.0
    wall_time[0] = 10_650.0
    monkeypatch.setattr(workflow, "generate", lambda _run_dir, **_kwargs: {
        "status": "blocked",
        "stage": "quality",
        "findings": [],
        "client_outputs": [],
    })
    result = workflow.run_desktop_operation(
        tmp_path,
        handoff_runner=lambda *_args: None,
        opener=lambda _path: b"unused",
        budget_seconds=999.0,
        clock=lambda: monotonic[0],
        wall_clock=lambda: wall_time[0],
    )

    assert result["elapsed_seconds"] == 650.0
    assert result["performance_classification"] == "target_window"


def test_desktop_runtime_resolver_skips_unsupported_python_and_records_explicit_path(monkeypatch):
    def probe(command, **_kwargs):
        executable = command[0]
        version = [3, 9, 6] if executable.endswith("python3") else [3, 11, 15]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({
                "executable": executable,
                "implementation": "CPython",
                "version": ".".join(str(item) for item in version),
                "version_info": version,
            }),
            stderr="",
        )

    monkeypatch.setattr(workflow.subprocess, "run", probe)

    runtime = workflow.resolve_python_runtime(
        candidates=[Path("/usr/bin/python3"), Path("/opt/python3.11")]
    )

    assert runtime == {
        "executable": "/opt/python3.11",
        "implementation": "CPython",
        "version": "3.11.15",
        "version_info": [3, 11, 15],
    }


def test_desktop_runtime_resolver_respects_an_explicit_empty_environment(monkeypatch):
    observed = []

    def probe(command, **kwargs):
        observed.append(kwargs["env"])
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({
                "executable": command[0],
                "implementation": "CPython",
                "version": "3.11.15",
                "version_info": [3, 11, 15],
            }),
            stderr="",
        )

    monkeypatch.setattr(workflow.subprocess, "run", probe)

    workflow.resolve_python_runtime(candidates=[Path("/opt/python3.11")], environment={})

    assert observed == [{}]


def test_unreadable_persisted_deadline_fails_closed_instead_of_starting_again(tmp_path, monkeypatch):
    state_path = tmp_path / "logs/desktop-operation.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text("not-json", encoding="utf-8")
    generated = []
    monkeypatch.setattr(workflow, "generate", lambda *_args, **_kwargs: generated.append(True))

    result = workflow.run_desktop_operation(
        tmp_path,
        handoff_runner=lambda *_args: None,
        opener=lambda _path: b"unused",
        clock=lambda: 5.0,
        wall_clock=lambda: 10_000.0,
    )

    assert result["status"] == "timeout"
    assert generated == []


def test_terminal_desktop_delivery_is_invalidated_when_the_contracted_bundle_changes(tmp_path, monkeypatch):
    state_path = tmp_path / "logs/desktop-operation.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({
        "operation_id": "default",
        "status": "passed",
        "result": {
            "status": "passed",
            "stage": "desktop_delivery",
            "contracted_template_bundle": {"identity_sha256": "old-bundle"},
            "client_outputs": ["output/protocol.docx"],
        },
    }), encoding="utf-8")
    reference_path = tmp_path / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    reference_path.write_text(json.dumps({"meta": {"study_type": "Retrospective"}}), encoding="utf-8")
    monkeypatch.setattr(
        workflow,
        "contracted_template_bundle",
        lambda _root, _reference: {"identity_sha256": "new-bundle"},
    )

    result = workflow.run_desktop_operation(
        tmp_path,
        handoff_runner=lambda *_args: None,
        opener=lambda _path: b"unused",
    )

    assert result["status"] == "blocked"
    assert result["stage"] == "contracted_template_bundle"
    assert result["client_outputs"] == []


def test_legacy_passing_desktop_delivery_without_bundle_identity_fails_closed(tmp_path):
    state_path = tmp_path / "logs/desktop-operation.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({
        "operation_id": "default",
        "status": "passed",
        "result": {
            "status": "passed",
            "stage": "desktop_delivery",
            "client_outputs": ["output/protocol.docx"],
        },
    }), encoding="utf-8")

    result = workflow.run_desktop_operation(
        tmp_path,
        handoff_runner=lambda *_args: None,
        opener=lambda _path: b"unused",
    )

    assert result["status"] == "blocked"
    assert result["stage"] == "contracted_template_bundle"
    assert result["client_outputs"] == []


@pytest.mark.parametrize("invalid_state", [
    {
        "started_at_epoch": "not-an-epoch",
        "deadline_at_epoch": 10_020.0,
        "budget_seconds": 20.0,
        "runtime_history": [],
    },
    {
        "started_at_epoch": 10_010.0,
        "deadline_at_epoch": 10_000.0,
        "budget_seconds": 20.0,
        "runtime_history": [],
    },
    {
        "started_at_epoch": 10_000.0,
        "deadline_at_epoch": float("nan"),
        "budget_seconds": 20.0,
        "runtime_history": [],
    },
    {
        "started_at_epoch": 10_000.0,
        "deadline_at_epoch": 10_020.0,
        "budget_seconds": 20.0,
        "runtime_history": "not-a-list",
    },
    {
        "started_at_epoch": 10_000.0,
        "deadline_at_epoch": 10_020.0,
        "budget_seconds": 20.0,
        "runtime_history": [],
        "stage_history": None,
    },
])
def test_malformed_persisted_deadline_fails_closed_instead_of_starting_again(
    tmp_path, monkeypatch, invalid_state,
):
    state_path = tmp_path / "logs/desktop-operation.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({
        "operation_id": "default",
        "status": "running",
        **invalid_state,
    }), encoding="utf-8")
    generated = []
    monkeypatch.setattr(workflow, "generate", lambda *_args, **_kwargs: generated.append(True))

    result = workflow.run_desktop_operation(
        tmp_path,
        handoff_runner=lambda *_args: None,
        opener=lambda _path: b"unused",
        clock=lambda: 5.0,
        wall_clock=lambda: 10_000.0,
    )

    assert result["status"] == "timeout"
    assert generated == []


def test_desktop_operation_does_not_report_delivery_when_attachment_retrieval_fails(tmp_path, monkeypatch):
    manifest = _manifest()
    manifest_path = tmp_path / "revisions/r1/delivery-manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(workflow, "generate", lambda run_dir, **_kwargs: {
        "status": "passed",
        "stage": "delivery",
        "manifest": "revisions/r1/delivery-manifest.json",
    })

    result = workflow.run_desktop_operation(
        tmp_path,
        handoff_runner=lambda handoffs, remaining_seconds: None,
        opener=lambda path: b"wrong",
        budget_seconds=30,
    )

    assert result["status"] == "blocked"
    assert result["stage"] == "desktop_delivery"
    assert result["delivery"]["confirmed"] is False


def test_runtime_target_is_ten_to_twelve_minutes_with_a_thirty_minute_ceiling():
    assert workflow.NORMAL_RUNTIME_TARGET_MIN_SECONDS == 600.0
    assert workflow.NORMAL_RUNTIME_TARGET_MAX_SECONDS == 720.0
    assert workflow.DESKTOP_OPERATION_BUDGET_SECONDS == 1800.0
    assert workflow.performance_classification(599.0) == "below_target_window"
    assert workflow.performance_classification(600.0) == "target_window"
    assert workflow.performance_classification(720.0) == "target_window"
    assert workflow.performance_classification(721.0) == "above_target_within_deadline"
    assert workflow.performance_classification(1800.0) == "above_target_within_deadline"
    assert workflow.performance_classification(1800.001) == "deadline_exceeded"


def test_desktop_operation_continues_after_fifteen_minutes(tmp_path, monkeypatch):
    now = [100.0]
    manifest = _manifest()
    manifest_path = tmp_path / "revisions/r1/delivery-manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def generated(_run_dir, **_kwargs):
        now[0] = 1001.0
        return {
            "status": "passed",
            "stage": "delivery",
            "manifest": "revisions/r1/delivery-manifest.json",
        }

    monkeypatch.setattr(workflow, "generate", generated)
    result = workflow.run_desktop_operation(
        tmp_path,
        handoff_runner=lambda *_: None,
        opener=lambda path: b"1234" if path.endswith("Protocol final.docx") else b"567",
        clock=lambda: now[0],
    )

    assert result["status"] == "passed"
    assert result["elapsed_seconds"] == 901.0
    assert result["performance_classification"] == "above_target_within_deadline"
