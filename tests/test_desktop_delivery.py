import json
from pathlib import Path
import subprocess

import pytest

import workflow
from quality import RESPONSE_SCHEMA, VISUAL_CHECKS, verification_request_sha256


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


def test_desktop_confirmation_rejects_an_opener_completion_after_the_hard_ceiling(tmp_path):
    now = [0.0]
    reply = workflow.desktop_attachment_reply(_manifest(), run_dir=tmp_path)

    def late_opener(path):
        now[0] = 6.0
        return b"1234" if path.endswith("Protocol final.docx") else b"567"

    result = workflow.confirm_desktop_delivery(
        _manifest(),
        reply,
        late_opener,
        deadline=5.0,
        clock=lambda: now[0],
    )

    assert result["status"] == "blocked"
    assert result["confirmed"] is False
    assert result["opened"] == []
    assert result["findings"][0]["recovery_class"] == "transport_fault"


def test_desktop_confirmation_blocks_mismatch_and_does_not_certify_quality(tmp_path):
    reply = workflow.desktop_attachment_reply(_manifest(), run_dir=tmp_path)

    result = workflow.confirm_desktop_delivery(_manifest(), reply, lambda path: b"wrong")

    assert result["status"] == "blocked"
    assert result["confirmed"] is False
    assert result["findings"][0]["category"] == "delivery"
    assert result["findings"][0]["recovery_class"] == "transport_fault"
    assert result["findings"][0]["action"] == "retry_exact_bytes"
    assert result["attempts"] == 3


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


def test_desktop_operation_persists_governed_identity_attempts_timings_and_cleanup(tmp_path, monkeypatch):
    now = [10.0]
    handoff = {
        "request_id": "r1.draft.introduction.initial.a1",
        "request_sha256": "a" * 64,
        "request_path": "hermes/requests/draft.json",
        "response_path": "hermes/responses/draft.json",
        "task": "section_drafting",
        "attempts": {"protocol.introduction": 1},
    }
    results = iter([
        {"status": "awaiting_hermes", "stage": "drafting", "revision_id": "r1", "handoffs": [handoff]},
        {"status": "passed", "stage": "delivery", "manifest": "revisions/r1/delivery-manifest.json"},
    ])
    manifest_path = tmp_path / "revisions/r1/delivery-manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps(_manifest()), encoding="utf-8")

    def generate(_run_dir, **_kwargs):
        now[0] += 2.0
        return next(results)

    def handoff_runner(_handoffs, _remaining):
        now[0] += 3.0

    cleanups = []
    monkeypatch.setattr(workflow, "generate", generate)

    result = workflow.run_desktop_operation(
        tmp_path,
        handoff_runner=handoff_runner,
        opener=lambda path: b"1234" if path.endswith("Protocol final.docx") else b"567",
        release_identity={"package_fingerprint": "release-abc", "git_commit": "deadbeef"},
        cleanup=lambda status, _remaining: cleanups.append(status) or {"owned_processes_reaped": True},
        budget_seconds=30.0,
        clock=lambda: now[0],
        wall_clock=lambda: 1_000.0,
    )

    state = json.loads((tmp_path / "logs/desktop-operation.json").read_text())
    assert result["status"] == "passed"
    assert state["release_identity"] == {"package_fingerprint": "release-abc", "git_commit": "deadbeef"}
    assert state["stage"] == "desktop_delivery"
    assert state["attempt_counters"]["drafting"] == {"protocol.introduction": 1}
    assert state["attempt_counters"]["handoff_dispatches"] == {"a" * 64: 1}
    assert state["stage_timings"]["generate"]["elapsed_seconds"] == 4.0
    assert state["stage_timings"]["drafting"]["elapsed_seconds"] == 3.0
    assert state["cleanup"] == {"owned_processes_reaped": True}
    assert state["result"] == result
    assert cleanups == ["passed"]


def test_missing_worker_response_cannot_be_replaced_by_a_changed_request(tmp_path, monkeypatch):
    original = {
        "request_id": "r1.draft.introduction.initial.a1",
        "request_sha256": "a" * 64,
        "request_path": "hermes/requests/draft.json",
        "response_path": "hermes/responses/draft.json",
        "task": "section_drafting",
        "attempts": {"protocol.introduction": 1},
    }
    changed = {**original, "request_sha256": "b" * 64}
    results = iter([
        {"status": "awaiting_hermes", "stage": "drafting", "revision_id": "r1", "handoffs": [original]},
        {"status": "awaiting_hermes", "stage": "drafting", "revision_id": "r1", "handoffs": [changed]},
    ])
    routed = []
    monkeypatch.setattr(workflow, "generate", lambda _run_dir, **_kwargs: next(results))

    result = workflow.run_desktop_operation(
        tmp_path,
        handoff_runner=lambda handoffs, _remaining: routed.append(handoffs),
        opener=lambda _path: b"unused",
        budget_seconds=30.0,
    )

    state = json.loads((tmp_path / "logs/desktop-operation.json").read_text())
    assert result["status"] == "blocked"
    assert result["stage"] == "hermes_handoff_integrity"
    assert routed == [[original]]
    assert state["attempt_counters"]["drafting"] == {"protocol.introduction": 1}
    assert state["attempt_counters"]["handoff_dispatches"] == {"a" * 64: 1}
    assert state["pending_handoffs"] == [original]


@pytest.mark.parametrize("pending_stage", [
    "drafting",
    "candidate",
    "render_assurance",
    "independent_verification",
    "delivery",
])
def test_hard_ceiling_preserves_the_exact_pending_stage_and_completed_candidates(
    tmp_path, monkeypatch, pending_stage,
):
    now = [0.0]
    retained = [{
        "path": "candidate/protocol.docx",
        "sha256": "c" * 64,
        "bytes": 123,
        "delivery_status": "internal_candidate",
    }]

    def generate(_run_dir, **_kwargs):
        now[0] = 6.0
        return {
            "status": "awaiting_hermes" if pending_stage in {"drafting", "independent_verification"} else "blocked",
            "stage": pending_stage,
            "candidate_outputs": retained,
            "client_outputs": [],
        }

    monkeypatch.setattr(workflow, "generate", generate)
    result = workflow.run_desktop_operation(
        tmp_path,
        handoff_runner=lambda *_args: None,
        opener=lambda _path: b"unused",
        budget_seconds=5.0,
        clock=lambda: now[0],
        wall_clock=lambda: 1_000.0,
    )

    state = json.loads((tmp_path / "logs/desktop-operation.json").read_text())
    assert result["status"] == "timeout"
    assert result["stage"] == "desktop_operation"
    assert result["pending_stage"] == pending_stage
    assert result["candidate_outputs"] == retained
    assert state["stage"] == pending_stage


def test_stage_soft_budget_triggers_diagnostics_without_ending_the_operation(tmp_path, monkeypatch):
    now = [0.0]
    handoff = {
        "request_id": "r1.draft.introduction.initial.a1",
        "request_sha256": "a" * 64,
        "request_path": "hermes/requests/draft.json",
        "response_path": "hermes/responses/draft.json",
        "task": "section_drafting",
        "attempts": {"protocol.introduction": 1},
    }
    results = iter([
        {"status": "awaiting_hermes", "stage": "drafting", "revision_id": "r1", "handoffs": [handoff]},
        {"status": "blocked", "stage": "drafting", "findings": [], "client_outputs": []},
    ])
    received_timeouts = []
    monkeypatch.setattr(workflow, "generate", lambda _run_dir, **_kwargs: next(results))

    def slow_worker(_handoffs, timeout_seconds):
        received_timeouts.append(timeout_seconds)
        now[0] += 6.0

    result = workflow.run_desktop_operation(
        tmp_path,
        handoff_runner=slow_worker,
        opener=lambda _path: b"unused",
        budget_seconds=30.0,
        stage_soft_budgets={"drafting": 5.0},
        clock=lambda: now[0],
        wall_clock=lambda: 1_000.0,
    )

    state = json.loads((tmp_path / "logs/desktop-operation.json").read_text())
    assert result["status"] == "blocked"
    assert received_timeouts == [30.0]
    assert state["soft_budget_events"] == [{
        "stage": "drafting",
        "budget_seconds": 5.0,
        "elapsed_seconds": 6.0,
        "action": "record_diagnostic",
    }]


def test_synchronous_candidate_stage_records_timing_and_soft_budget_diagnostic(tmp_path, monkeypatch):
    def generate(_run_dir, **kwargs):
        kwargs["stage_observer"]("candidate", 6.0)
        return {"status": "blocked", "stage": "candidate", "findings": [], "client_outputs": []}

    monkeypatch.setattr(workflow, "generate", generate)
    result = workflow.run_desktop_operation(
        tmp_path,
        handoff_runner=lambda *_args: None,
        opener=lambda _path: b"unused",
        stage_soft_budgets={"candidate": 5.0},
    )

    state = json.loads((tmp_path / "logs/desktop-operation.json").read_text())
    assert result["status"] == "blocked"
    assert state["stage_timings"]["candidate"]["elapsed_seconds"] == 6.0
    assert state["soft_budget_events"] == [{
        "stage": "candidate",
        "budget_seconds": 5.0,
        "elapsed_seconds": 6.0,
        "action": "record_diagnostic",
    }]


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


def test_visual_soft_budget_routes_early_parent_fallback_without_shortening_the_operation(tmp_path, monkeypatch):
    now = [0.0]
    handoff = {
        "request_id": "r1.verify.visual",
        "request_sha256": "v" * 64,
        "request_path": "hermes/verification-requests/visual.json",
        "response_path": "hermes/verification-responses/visual.json",
        "task": "rendered_page_visual_verification",
        "fallback_owner": "parent",
    }
    results = iter([
        {"status": "awaiting_hermes", "stage": "independent_verification", "revision_id": "r1", "handoffs": [handoff]},
        {"status": "blocked", "stage": "quality", "findings": [], "client_outputs": []},
    ])
    primary_timeouts = []
    parent_reviews = []
    monkeypatch.setattr(workflow, "generate", lambda _run_dir, **_kwargs: next(results))

    def primary(_handoffs, timeout_seconds):
        primary_timeouts.append(timeout_seconds)
        now[0] += timeout_seconds

    result = workflow.run_desktop_operation(
        tmp_path,
        handoff_runner=primary,
        fallback_handoff_runner=lambda handoffs, _remaining: parent_reviews.extend(handoffs),
        opener=lambda _path: b"unused",
        budget_seconds=30.0,
        stage_soft_budgets={"independent_verification": 5.0},
        clock=lambda: now[0],
        wall_clock=lambda: 1_000.0,
    )

    state = json.loads((tmp_path / "logs/desktop-operation.json").read_text())
    assert result["status"] == "blocked"
    assert primary_timeouts == [5.0]
    assert parent_reviews == [handoff]
    assert state["soft_budget_events"][0]["action"] == "early_parent_fallback"
    assert state["deadline_at_epoch"] == 1_030.0


def _visual_handoff_fixture(tmp_path, artifact):
    revision = tmp_path / "revisions/r1"
    files = {
        f"candidate/{artifact}.docx": f"{artifact}-docx".encode(),
        f"rendered/{artifact}.pdf": f"{artifact}-pdf".encode(),
        f"rendered/{artifact}/page-1.png": f"{artifact}-page-1".encode(),
    }
    for relative, payload in files.items():
        path = revision / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    digest = {relative: workflow.sha256_file(revision / relative) for relative in files}
    request_id = f"r1.verify.visual.{artifact}"
    request_path = f"hermes/verification-requests/{artifact}.json"
    response_path = f"hermes/verification-responses/{artifact}.json"
    handoff = {
        "request_path": request_path,
        "response_path": response_path,
        "task": "rendered_page_visual_verification",
        "fallback_owner": "parent",
    }
    request = {
        "schema_version": "hermes-verification/v1",
        "request_id": request_id,
        "task": handoff["task"],
        "response_path": response_path,
        "checks": list(VISUAL_CHECKS),
        "artifacts": [{
            "artifact": artifact,
            "docx": f"candidate/{artifact}.docx",
            "docx_sha256": digest[f"candidate/{artifact}.docx"],
            "pdf": f"rendered/{artifact}.pdf",
            "pdf_sha256": digest[f"rendered/{artifact}.pdf"],
            "pages": [{
                "page": 1,
                "path": f"rendered/{artifact}/page-1.png",
                "sha256": digest[f"rendered/{artifact}/page-1.png"],
            }],
        }],
    }
    request["request_sha256"] = verification_request_sha256(request)
    handoff["request_id"] = request_id
    handoff["request_sha256"] = request["request_sha256"]
    request_file = revision / request_path
    request_file.parent.mkdir(parents=True, exist_ok=True)
    request_file.write_text(json.dumps(request), encoding="utf-8")
    response = {
        "schema_version": RESPONSE_SCHEMA,
        "request_id": request_id,
        "request_sha256": request["request_sha256"],
        "task": handoff["task"],
        "producer": {"model_id": "test-verifier"},
        "status": "passed",
        "findings": [],
        "page_assessments": [{
            "artifact": artifact,
            "page": 1,
            "sha256": digest[f"rendered/{artifact}/page-1.png"],
            "status": "passed",
            "checks": list(VISUAL_CHECKS),
        }],
    }
    return handoff, request, response


def test_measured_mixed_verifier_wave_retains_completed_work_and_falls_back_only_the_stall(tmp_path, monkeypatch):
    now = [0.0]
    protocol_handoff, protocol_request, protocol_response = _visual_handoff_fixture(tmp_path, "protocol")
    icf_handoff, icf_request, _ = _visual_handoff_fixture(tmp_path, "icf")
    content_handoff = {
        "request_path": "hermes/verification-requests/content.json",
        "response_path": "hermes/verification-responses/content.json",
        "task": "clinical_content_verification",
    }
    content_request = {
        "request_id": "r1.verify.content",
        "request_sha256": "c" * 64,
        "task": content_handoff["task"],
        "response_path": content_handoff["response_path"],
    }
    content_handoff["request_id"] = content_request["request_id"]
    content_handoff["request_sha256"] = content_request["request_sha256"]
    content_request_path = tmp_path / "revisions/r1" / content_handoff["request_path"]
    content_request_path.parent.mkdir(parents=True, exist_ok=True)
    content_request_path.write_text(json.dumps(content_request), encoding="utf-8")
    handoffs = [content_handoff, protocol_handoff, icf_handoff]
    results = iter([
        {"status": "awaiting_hermes", "stage": "independent_verification", "revision_id": "r1", "handoffs": handoffs},
        {"status": "blocked", "stage": "quality", "findings": [], "client_outputs": []},
    ])
    primary_timeouts = []
    parent_reviews = []
    monkeypatch.setattr(workflow, "generate", lambda _run_dir, **_kwargs: next(results))

    def primary(received_handoffs, timeout_seconds):
        primary_timeouts.append(timeout_seconds)
        response_root = tmp_path / "revisions/r1/hermes/verification-responses"
        response_root.mkdir(parents=True, exist_ok=True)
        content_response = {
            "request_id": content_request["request_id"],
            "request_sha256": content_request["request_sha256"],
            "task": content_request["task"],
        }
        response_root.joinpath("content.json").write_text(json.dumps(content_response), encoding="utf-8")
        response_root.joinpath("protocol.json").write_text(json.dumps(protocol_response), encoding="utf-8")
        (tmp_path / "revisions/r1" / received_handoffs[2]["response_path"]).write_text(
            json.dumps({
                "request_id": icf_request["request_id"],
                "request_sha256": icf_request["request_sha256"],
                "task": icf_request["task"],
            }),
            encoding="utf-8",
        )
        now[0] += timeout_seconds

    result = workflow.run_desktop_operation(
        tmp_path,
        handoff_runner=primary,
        fallback_handoff_runner=lambda handoffs, _remaining: parent_reviews.extend(handoffs),
        opener=lambda _path: b"unused",
        budget_seconds=1_800.0,
        clock=lambda: now[0],
        wall_clock=lambda: 1_000.0,
    )

    state = json.loads((tmp_path / "logs/desktop-operation.json").read_text())
    assert result["status"] == "blocked"
    assert primary_timeouts == [240.0]
    assert parent_reviews == [handoffs[2]]
    assert state["soft_budget_events"] == [{
        "stage": "independent_verification",
        "budget_seconds": 240.0,
        "elapsed_seconds": 240.0,
        "action": "early_parent_fallback",
    }]
    assert state["deadline_at_epoch"] == 2_800.0


def test_verifier_exception_falls_back_only_for_incomplete_parent_work(tmp_path, monkeypatch):
    protocol_handoff, _, protocol_response = _visual_handoff_fixture(tmp_path, "protocol")
    icf_handoff, _, _ = _visual_handoff_fixture(tmp_path, "icf")
    handoffs = [protocol_handoff, icf_handoff]
    results = iter([
        {"status": "awaiting_hermes", "stage": "independent_verification", "revision_id": "r1", "handoffs": handoffs},
        {"status": "blocked", "stage": "quality", "findings": [], "client_outputs": []},
    ])
    monkeypatch.setattr(workflow, "generate", lambda _run_dir, **_kwargs: next(results))
    parent_reviews = []

    def primary(_handoffs, _timeout_seconds):
        response = tmp_path / "revisions/r1" / protocol_handoff["response_path"]
        response.parent.mkdir(parents=True, exist_ok=True)
        response.write_text(json.dumps(protocol_response), encoding="utf-8")
        raise RuntimeError("adapter failed after partial completion")

    result = workflow.run_desktop_operation(
        tmp_path,
        handoff_runner=primary,
        fallback_handoff_runner=lambda pending, _remaining: parent_reviews.extend(pending),
        opener=lambda _path: b"unused",
        budget_seconds=30.0,
    )

    assert result["status"] == "blocked"
    assert parent_reviews == [icf_handoff]


def test_mutated_visual_request_cannot_suppress_parent_fallback(tmp_path, monkeypatch):
    handoff, request, response = _visual_handoff_fixture(tmp_path, "protocol")
    request["artifacts"][0]["pages"] = []
    request["request_sha256"] = verification_request_sha256(request)
    response["request_sha256"] = request["request_sha256"]
    response["page_assessments"] = []
    request_path = tmp_path / "revisions/r1" / handoff["request_path"]
    request_path.write_text(json.dumps(request), encoding="utf-8")
    response_path = tmp_path / "revisions/r1" / handoff["response_path"]
    response_path.parent.mkdir(parents=True, exist_ok=True)
    response_path.write_text(json.dumps(response), encoding="utf-8")
    results = iter([
        {"status": "awaiting_hermes", "stage": "independent_verification", "revision_id": "r1", "handoffs": [handoff]},
        {"status": "blocked", "stage": "quality", "findings": [], "client_outputs": []},
    ])
    monkeypatch.setattr(workflow, "generate", lambda _run_dir, **_kwargs: next(results))
    parent_reviews = []

    result = workflow.run_desktop_operation(
        tmp_path,
        handoff_runner=lambda *_args: None,
        fallback_handoff_runner=lambda pending, _remaining: parent_reviews.extend(pending),
        opener=lambda _path: b"unused",
        budget_seconds=30.0,
    )

    assert result["status"] == "blocked"
    assert parent_reviews == [handoff]


def test_upstream_generation_time_does_not_consume_the_verification_soft_budget(tmp_path, monkeypatch):
    now = [0.0]
    handoff = {
        "request_id": "r1.verify.visual",
        "request_sha256": "v" * 64,
        "request_path": "hermes/verification-requests/visual.json",
        "response_path": "hermes/verification-responses/visual.json",
        "task": "rendered_page_visual_verification",
        "fallback_owner": "parent",
    }
    results = iter([
        {"status": "awaiting_hermes", "stage": "independent_verification", "revision_id": "r1", "handoffs": [handoff]},
        {"status": "blocked", "stage": "quality", "findings": [], "client_outputs": []},
    ])

    def generate(_run_dir, **_kwargs):
        result = next(results)
        if result["status"] == "awaiting_hermes":
            now[0] += 20.0
        return result

    primary_timeouts = []
    monkeypatch.setattr(workflow, "generate", generate)
    result = workflow.run_desktop_operation(
        tmp_path,
        handoff_runner=lambda _handoffs, timeout: primary_timeouts.append(timeout),
        fallback_handoff_runner=lambda *_args: None,
        opener=lambda _path: b"unused",
        budget_seconds=30.0,
        stage_soft_budgets={"independent_verification": 5.0},
        clock=lambda: now[0],
        wall_clock=lambda: 1_000.0,
    )

    state = json.loads((tmp_path / "logs/desktop-operation.json").read_text())
    assert result["status"] == "blocked"
    assert primary_timeouts == [5.0]
    assert state["stage_timings"]["independent_verification"]["elapsed_seconds"] == 0.0


def test_atomic_publication_does_not_replace_outputs_when_staging_crosses_the_deadline(tmp_path):
    revision_dir = tmp_path / "revisions/r1"
    candidate = revision_dir / "candidate"
    candidate.mkdir(parents=True)
    (candidate / "protocol.docx").write_bytes(b"new candidate")
    (revision_dir / "approved-reference.json").write_text("{}", encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir()
    (output / "protocol.docx").write_bytes(b"previous release")
    times = iter([9.0, 10.0])

    with pytest.raises(workflow.OperationDeadlineExpired):
        workflow._publish(
            tmp_path,
            revision_dir,
            {"meta": {"study_type": "Retrospective"}},
            {},
            operation_deadline=10.0,
            clock=lambda: next(times),
        )

    assert (output / "protocol.docx").read_bytes() == b"previous release"


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
    cleanups = []
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
        cleanup=lambda status, _remaining: cleanups.append(status) or {"owned_processes_reaped": True},
    )
    second = workflow.run_desktop_operation(
        tmp_path,
        handoff_runner=route,
        opener=lambda path: b"unused",
        budget_seconds=99,
        clock=lambda: now[0],
        cleanup=lambda status, _remaining: cleanups.append(status) or {"owned_processes_reaped": True},
    )

    assert first["status"] == second["status"] == "timeout"
    assert first["stage"] == second["stage"] == "desktop_operation"
    assert len(generated) == 1
    assert second["deadline_at_epoch"] == first["deadline_at_epoch"]
    assert cleanups == ["timeout"]


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


def test_terminal_desktop_delivery_is_invalidated_when_the_release_fingerprint_changes(tmp_path, monkeypatch):
    state_path = tmp_path / "logs/desktop-operation.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({
        "operation_id": "default",
        "status": "passed",
        "release_identity": {"package_fingerprint": "old-release"},
        "result": {
            "status": "passed",
            "stage": "desktop_delivery",
            "contracted_template_bundle": {"identity_sha256": "same-bundle"},
            "client_outputs": ["output/protocol.docx"],
        },
    }), encoding="utf-8")
    reference_path = tmp_path / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    reference_path.write_text(json.dumps({"meta": {"study_type": "Retrospective"}}), encoding="utf-8")
    monkeypatch.setattr(
        workflow,
        "contracted_template_bundle",
        lambda _root, _reference: {"identity_sha256": "same-bundle"},
    )

    result = workflow.run_desktop_operation(
        tmp_path,
        handoff_runner=lambda *_args: None,
        opener=lambda _path: b"unused",
        release_identity={"package_fingerprint": "new-release"},
    )

    assert result["status"] == "blocked"
    assert result["stage"] == "release_identity"
    assert result["client_outputs"] == []


def test_terminal_desktop_delivery_is_invalidated_when_governed_configuration_changes(tmp_path):
    state_path = tmp_path / "logs/desktop-operation.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({
        "operation_id": "default",
        "status": "blocked",
        "release_identity": {
            "package_fingerprint": "same-release",
            "hermes_configuration": {"max_turns": 40},
        },
        "result": {"status": "blocked", "stage": "quality", "client_outputs": []},
    }), encoding="utf-8")

    result = workflow.run_desktop_operation(
        tmp_path,
        handoff_runner=lambda *_args: None,
        opener=lambda _path: b"unused",
        release_identity={
            "package_fingerprint": "same-release",
            "hermes_configuration": {"max_turns": 80},
        },
    )

    assert result["status"] == "blocked"
    assert result["stage"] == "release_identity"
    assert "configuration" in result["findings"][0]["issue"]


def test_desktop_operation_state_path_uses_the_workflow_slug(tmp_path):
    assert workflow.desktop_operation_state_path(tmp_path, "Case 42 / Sterling") == (
        tmp_path / "logs/desktop-operation-case-42-sterling.json"
    )


def test_terminal_desktop_delivery_is_revalidated_against_accessible_output_bytes(tmp_path, monkeypatch):
    reference_path = tmp_path / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    reference_path.write_text(json.dumps({"meta": {"study_type": "Retrospective"}}), encoding="utf-8")
    output_path = tmp_path / "output/protocol.docx"
    output_path.parent.mkdir()
    output_path.write_bytes(b"1234")
    manifest = {
        "status": "passed",
        "client_outputs": [{
            "path": "output/protocol.docx",
            "sha256": "03ac674216f3e15c761ee1a5e255f067953623c8b388b4459e13f978d7c846f4",
            "bytes": 4,
        }],
    }
    manifest_path = tmp_path / "revisions/r1/delivery-manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    generated = []
    monkeypatch.setattr(workflow, "generate", lambda _run_dir, **_kwargs: generated.append(True) or {
        "status": "passed",
        "stage": "delivery",
        "manifest": "revisions/r1/delivery-manifest.json",
        "contracted_template_bundle": {"identity_sha256": "bundle-1"},
    })
    monkeypatch.setattr(workflow, "contracted_template_bundle", lambda _root, _reference: {
        "identity_sha256": "bundle-1",
    })
    arguments = {
        "handoff_runner": lambda *_args: None,
        "opener": lambda path: Path(path).read_bytes(),
        "release_identity": {"package_fingerprint": "release-1"},
    }

    first = workflow.run_desktop_operation(tmp_path, **arguments)
    output_path.write_bytes(b"xxxx")
    resumed = workflow.run_desktop_operation(tmp_path, **arguments)

    assert first["status"] == "passed"
    assert resumed["status"] == "blocked"
    assert resumed["stage"] == "terminal_delivery_validation"
    assert resumed["client_outputs"] == []
    assert generated == [True]


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
    state = json.loads((tmp_path / "logs/desktop-operation.json").read_text())
    assert state["attempt_counters"]["delivery"] == 3


def test_desktop_operation_requires_the_exact_branch_output_set_before_opening_files(tmp_path, monkeypatch):
    reference_path = tmp_path / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    reference_path.write_text(json.dumps({"meta": {"study_type": "Retrospective"}}), encoding="utf-8")
    manifest = {
        "status": "passed",
        "client_outputs": [
            {"path": "output/protocol.docx", "sha256": "03ac674216f3e15c761ee1a5e255f067953623c8b388b4459e13f978d7c846f4", "bytes": 4},
            {"path": "output/study.xml", "sha256": "97a6d21df7c51e8289ac1a8c026aaac143e15aa1957f54f42e30d8f8a85c3a55", "bytes": 3},
        ],
    }
    manifest_path = tmp_path / "revisions/r1/delivery-manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(workflow, "generate", lambda _run_dir, **_kwargs: {
        "status": "passed",
        "stage": "delivery",
        "manifest": "revisions/r1/delivery-manifest.json",
    })
    opened = []

    result = workflow.run_desktop_operation(
        tmp_path,
        handoff_runner=lambda *_args: None,
        opener=lambda path: opened.append(path) or b"unused",
        budget_seconds=30.0,
    )

    assert result["status"] == "blocked"
    assert result["stage"] == "desktop_delivery_set"
    assert result["client_outputs"] == []
    assert opened == []


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
