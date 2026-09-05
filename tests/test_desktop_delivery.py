import json
import os
from pathlib import Path
import shutil
import signal
import socket
import socketserver
import subprocess
import sys
import threading

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


def test_shipped_production_adapter_drives_actual_desktop_operation(tmp_path, monkeypatch):
    branch_manifest = {
        "status": "passed",
        "client_outputs": [{
            **_manifest()["client_outputs"][0],
            "path": "output/protocol.docx",
        }],
    }
    handoff = {
        "request_path": "hermes/requests/draft.json",
        "response_path": "hermes/responses/draft.json",
        "task": "section_drafting",
    }
    results = iter([
        {"status": "awaiting_hermes", "stage": "drafting", "revision_id": "r1", "handoffs": [handoff]},
        {"status": "passed", "stage": "delivery", "manifest": "revisions/r1/delivery-manifest.json"},
    ])
    manifest_path = tmp_path / "revisions/r1/delivery-manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps(branch_manifest), encoding="utf-8")
    reference_path = tmp_path / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    reference_path.write_text(json.dumps({
        "meta": {"study_type": "Retrospective"},
        "approval": {"status": "approved", "revision_id": "r1"},
    }), encoding="utf-8")
    monkeypatch.setattr(workflow, "generate", lambda _run_dir, **_kwargs: next(results))
    monkeypatch.setattr(workflow, "_installed_release_identity", lambda _root: {
        "package_fingerprint": "production-candidate",
        "git_commit": None,
        "source": "shipped_production_adapter",
    })
    dispatched = []

    def dispatch(handoffs, remaining_seconds, revision_dir, configuration, **_kwargs):
        assert remaining_seconds > 0
        assert revision_dir == tmp_path / "revisions/r1"
        assert configuration["safe_mode"] is True
        dispatched.extend(handoff["task"] for handoff in handoffs)

    monkeypatch.setattr(workflow, "_production_dispatch_handoffs", dispatch)
    result = workflow.run_production_desktop_operation(
        tmp_path,
        opener=lambda _path: b"1234",
        release_identity={"package_fingerprint": "production-candidate"},
    )

    assert result["status"] == "passed", result
    assert result["stage"] == "desktop_delivery"
    assert result["delivery"]["confirmed"] is True
    assert dispatched == ["section_drafting"]


def test_production_verifier_relies_on_parent_validation_without_terminal_consent(tmp_path):
    prompt = workflow._production_agent_prompt(
        tmp_path / "skill",
        tmp_path / "revision",
        {
            "request_path": "hermes/verification-requests/visual.json",
            "response_path": "hermes/verification-responses/visual.json",
            "task": "rendered_page_visual_verification",
        },
        {},
        workspace_root=tmp_path,
    )

    assert "The Desktop parent validates it automatically" in prompt
    assert "Return the exact response JSON as your final answer" in prompt
    assert "Do not call write_file, patch, or terminal to publish the response" in prompt
    assert "/usr/bin/python3 -c" not in prompt


def test_production_parent_publishes_bound_quiet_stdout_response(tmp_path):
    revision_dir = tmp_path / "revision"
    request_path = revision_dir / "hermes/requests/draft.json"
    response_path = revision_dir / "hermes/responses/draft.json"
    request_path.parent.mkdir(parents=True)
    response_path.parent.mkdir(parents=True)
    request = {
        "schema_version": "hermes-request/v2",
        "request_id": "draft-1",
        "request_sha256": "a" * 64,
        "revision_id": "r1",
        "task": "section_drafting",
        "batch_id": "protocol-foundations",
    }
    request_path.write_text(json.dumps(request), encoding="utf-8")
    response = {
        "schema_version": "hermes-response/v2",
        "request_id": "draft-1",
        "request_sha256": "a" * 64,
        "revision_id": "r1",
        "task": "section_drafting",
        "batch_id": "protocol-foundations",
        "producer": {"model_id": "test-model"},
        "section_results": [],
    }
    stdout_log = tmp_path / "worker.stdout.log"
    stdout_log.write_text(
        "session_id: test-session\n" + json.dumps(response, indent=2) + "\n",
        encoding="utf-8",
    )
    handoff = {
        "request_path": "hermes/requests/draft.json",
        "response_path": "hermes/responses/draft.json",
        "task": "section_drafting",
    }

    assert workflow._production_publish_quiet_response(
        revision_dir,
        handoff,
        stdout_log,
    ) is True
    assert json.loads(response_path.read_text(encoding="utf-8")) == response


def test_production_parent_retains_failed_content_review_as_a_blocking_response(tmp_path):
    revision_dir = tmp_path / "revision"
    request_path = revision_dir / "hermes/verification-requests/review-2-content.json"
    response_path = revision_dir / "hermes/verification-responses/review-2-content.json"
    request_path.parent.mkdir(parents=True)
    response_path.parent.mkdir(parents=True)
    request = {
        "schema_version": "hermes-verification/v1",
        "request_id": "r1.review-2.verify.content",
        "task": "clinical_content_verification",
        "revision_id": "r1",
        "review_set": 2,
        "artifacts": [],
        "approved_source": {},
        "authorized_boilerplate": {},
        "sections": [],
        "checks": [],
        "cross_document_checks": [],
        "instructions": "",
        "response_path": response_path.relative_to(revision_dir).as_posix(),
    }
    request["request_sha256"] = verification_request_sha256(request)
    request_path.write_text(json.dumps(request), encoding="utf-8")
    response = {
        "schema_version": RESPONSE_SCHEMA,
        "request_id": request["request_id"],
        "request_sha256": request["request_sha256"],
        "task": request["task"],
        "producer": {"model_id": "test-model"},
        "status": "failed",
        "findings": [{
            "target_ids": ["study-procedure.visits"],
            "issue": "The visit table assigns unsupported visit numbers to procedures.",
        }],
        "section_assessments": [],
        "cross_document_assessments": [],
    }
    stdout_log = tmp_path / "worker.stdout.log"
    stdout_log.write_text(
        "reasoning before the final object\n" + json.dumps(response, indent=2) + "\n",
        encoding="utf-8",
    )
    handoff = {
        "request_path": request_path.relative_to(revision_dir).as_posix(),
        "response_path": request["response_path"],
        "task": request["task"],
    }

    assert workflow._production_publish_quiet_response(
        revision_dir,
        handoff,
        stdout_log,
    ) is True
    assert json.loads(response_path.read_text(encoding="utf-8")) == response


def test_production_verifier_prompt_includes_layout_preservation_notes(tmp_path):
    prompt = workflow._production_agent_prompt(
        tmp_path / "skill",
        tmp_path / "revision",
        {
            "request_path": "hermes/verification-requests/visual.json",
            "response_path": "hermes/verification-responses/visual.json",
            "task": "rendered_page_visual_verification",
        },
        {
            "layout_preservation_notes": [
                "Keep Section 15 and its assessment table together on the following page.",
            ],
        },
        workspace_root=tmp_path,
    )

    assert "Keep Section 15 and its assessment table together on the following page." in prompt


def test_production_adapter_uses_unpromoted_runtime_only_for_verified_certification_candidate(
    tmp_path, monkeypatch,
):
    skill_root = tmp_path / "isolated-home/skills/clinical-document-generation"
    skill_root.mkdir(parents=True)
    monkeypatch.setattr(workflow, "_installed_release_identity", lambda _root: {
        "package_fingerprint": "certification-candidate",
        "git_commit": "candidate-commit",
        "source": "shipped_production_adapter",
    })
    integrity_calls = []
    monkeypatch.setattr(
        workflow,
        "_pdfium_runtime_integrity",
        lambda root, **options: integrity_calls.append((root, options)) or {"status": "passed"},
    )
    monkeypatch.setattr(
        workflow,
        "run_desktop_operation",
        lambda _run_dir, **options: {"status": "passed", "options": options},
    )
    preflight = tmp_path / "evidence/preflight.json"
    preflight.parent.mkdir()
    unsigned_preflight = {
        "schema_version": "release-certification-preflight/v1",
        "status": "passed",
        "repository_clean": True,
        "candidate": {
            "package_fingerprint": "certification-candidate",
            "git_commit": "candidate-commit",
            "release_root": str(skill_root.resolve()),
        },
        "producer": {
            "path": "tests/hermes_e2e.py",
            "git_commit": "candidate-commit",
        },
        "checks": {
            name: {"status": "passed", "returncode": 0}
            for name in (
                "static_release_checks", "layout_preservation_corpus",
                "deterministic_branch_acceptance_corpus", "repository_regression_suite",
            )
        },
    }
    signing_key_path = Path(__file__).parent / "fixtures/test-certification-signing-key.json"
    signing_key = json.loads(signing_key_path.read_text(encoding="utf-8"))
    public_key = {
        key: value for key, value in signing_key.items()
        if key != "private_exponent"
    }
    public_key_path = skill_root / workflow.RELEASE_CERTIFICATION_PUBLIC_KEY
    public_key_path.parent.mkdir(parents=True)
    public_key_path.write_text(json.dumps(public_key), encoding="utf-8")
    monkeypatch.setattr(
        workflow, "RELEASE_CERTIFICATION_TRUSTED_KEY_ID",
        workflow.release_certification_key_id(public_key),
    )
    preflight.write_text(json.dumps(
        workflow._sign_release_certification(unsigned_preflight, signing_key_path)
    ), encoding="utf-8")

    result = workflow.run_production_desktop_operation(
        tmp_path / "run",
        opener=lambda _path: b"unused",
        release_identity={
            "package_fingerprint": "certification-candidate",
            "git_commit": "candidate-commit",
        },
        skill_root=skill_root,
        certification_preflight=preflight,
    )

    assert integrity_calls == [(skill_root.resolve(), {"require_promoted_runtime": False})]
    assert result["options"]["require_promoted_runtime"] is False
    managed_identity = result["options"]["release_identity"]["managed_hermes_identity"]
    assert len(managed_identity["launcher_sha256"]) == 64
    assert len(managed_identity["interpreter_target_sha256"]) == 64

    monkeypatch.setattr(
        workflow,
        "_pdfium_runtime_integrity",
        lambda *_args, **_kwargs: {
            "status": "blocked",
            "finding": {"code": "renderer.pdfium_runtime_file_changed"},
        },
    )
    with pytest.raises(ValueError, match="verified provisioned certification candidate"):
        workflow.run_production_desktop_operation(
            tmp_path / "run",
            opener=lambda _path: b"unused",
            release_identity={
                "package_fingerprint": "certification-candidate",
                "git_commit": "candidate-commit",
            },
            skill_root=skill_root,
            certification_preflight=preflight,
        )

    rebound = json.loads(preflight.read_text())
    rebound["candidate"]["release_root"] = str(
        tmp_path / "copied-home/skills/clinical-document-generation"
    )
    preflight.write_text(json.dumps(rebound), encoding="utf-8")
    with pytest.raises(ValueError, match="lifecycle-owned preflight"):
        workflow.run_production_desktop_operation(
            tmp_path / "run",
            opener=lambda _path: b"unused",
            release_identity={
                "package_fingerprint": "certification-candidate",
                "git_commit": "candidate-commit",
            },
            skill_root=skill_root,
            certification_preflight=preflight,
        )


def test_production_adapter_allows_explicit_manual_review_on_verified_unpromoted_candidate(
    tmp_path, monkeypatch,
):
    skill_root = tmp_path / "isolated-home/skills/clinical-document-generation"
    skill_root.mkdir(parents=True)
    monkeypatch.setattr(workflow, "_installed_release_identity", lambda _root: {
        "package_fingerprint": "manual-review-candidate",
        "git_commit": "candidate-commit",
        "source": "shipped_production_adapter",
    })
    integrity_calls = []
    monkeypatch.setattr(
        workflow,
        "_pdfium_runtime_integrity",
        lambda root, **options: integrity_calls.append((root, options)) or {"status": "passed"},
    )
    monkeypatch.setattr(
        workflow,
        "run_desktop_operation",
        lambda _run_dir, **options: {"status": "passed", "options": options},
    )

    result = workflow.run_production_desktop_operation(
        tmp_path / "run",
        opener=lambda _path: b"unused",
        release_identity={
            "package_fingerprint": "manual-review-candidate",
            "git_commit": "candidate-commit",
        },
        skill_root=skill_root,
        manual_review=True,
    )

    assert integrity_calls == [(skill_root.resolve(), {"require_promoted_runtime": False})]
    assert result["options"]["require_promoted_runtime"] is False
    assert result["options"]["release_identity"]["manual_review"] is True
    assert result["review_mode"] == "manual_pre_release"


def test_production_adapter_isolates_profile_environment_and_rejects_symlink(tmp_path, monkeypatch):
    hermes_home = tmp_path / "isolated-home"
    skill_root = hermes_home / "skills/clinical-document-generation"
    skill_root.mkdir(parents=True)
    monkeypatch.setenv("HOME", "/ambient/home")
    monkeypatch.setenv("HERMES_HOME", "/ambient/hermes")
    monkeypatch.setenv("PYTHONPATH", "/ambient/python")
    monkeypatch.setenv("PATH", "/ambient/editable/bin")
    monkeypatch.setenv("DEVELOPMENT_CHECKOUT", "/ambient/editable/checkout")

    environment = workflow._production_subprocess_environment(skill_root)

    assert environment["HOME"] == str(hermes_home.resolve())
    assert environment["HERMES_HOME"] == str(hermes_home.resolve())
    assert "PYTHONPATH" not in environment
    assert "DEVELOPMENT_CHECKOUT" not in environment
    assert environment["PATH"] == "/usr/bin:/bin:/usr/sbin:/sbin"
    assert environment["TMPDIR"] == str(hermes_home.resolve() / ".tmp")
    assert environment["XDG_CACHE_HOME"] == str(hermes_home.resolve() / ".cache")

    linked_root = hermes_home / "skills/linked-clinical-document-generation"
    linked_root.symlink_to(skill_root, target_is_directory=True)
    with pytest.raises(ValueError, match="non-symlinked"):
        workflow._production_subprocess_environment(linked_root)

    real_home = tmp_path / "real-home"
    (real_home / "skills/clinical-document-generation").mkdir(parents=True)
    linked_home = tmp_path / "linked-home"
    linked_home.symlink_to(real_home, target_is_directory=True)
    with pytest.raises(ValueError, match="non-symlinked"):
        workflow._production_subprocess_environment(
            linked_home / "skills/clinical-document-generation"
        )


def test_production_launcher_and_sandbox_ignore_ambient_path(tmp_path, monkeypatch):
    account_home = tmp_path / "account"
    launcher = account_home / ".hermes/hermes-agent/venv/bin/hermes"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\n", encoding="utf-8")
    launcher.chmod(0o700)
    (launcher.parent / "python").symlink_to(Path(sys.executable))
    attacker = tmp_path / "attacker/bin"
    attacker.mkdir(parents=True)
    monkeypatch.setenv("PATH", str(attacker))
    monkeypatch.setattr(
        workflow.pwd, "getpwuid", lambda _uid: type("Account", (), {"pw_dir": str(account_home)})(),
    )

    selected_launcher, selected_python = workflow._managed_hermes_pair()

    assert selected_launcher == launcher
    assert selected_python == launcher.parent / "python"
    assert workflow._production_sandbox_executable() == Path("/usr/bin/sandbox-exec")
    identity = workflow._managed_hermes_identity()
    assert identity["launcher"] == str(launcher)
    assert len(identity["launcher_sha256"]) == 64
    assert identity["interpreter"] == str(launcher.parent / "python")
    assert len(identity["interpreter_target_sha256"]) == 64
    launcher.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    assert workflow._managed_hermes_identity() != identity


def test_production_sandbox_read_policy_is_allowlisted(tmp_path, monkeypatch):
    skill_root = tmp_path / "profile/skills/clinical-document-generation"
    run_dir = tmp_path / "run"
    unrelated = tmp_path / "unrelated-checkout"
    authentication_path = tmp_path / "account/.hermes/auth.json"
    skill_root.mkdir(parents=True)
    unrelated.mkdir()
    captured = {}
    monkeypatch.setattr(workflow.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(workflow, "_production_sandbox_executable", lambda: Path("/usr/bin/sandbox-exec"))
    monkeypatch.setattr(workflow, "_production_authentication_path", lambda: authentication_path)
    monkeypatch.setattr(
        workflow, "_managed_hermes_pair",
        lambda: (Path("/managed/hermes/venv/bin/hermes"), Path(sys.executable)),
    )

    def stop(command, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs["cwd"]
        captured["environment"] = kwargs["env"]
        captured["profile_path"] = tmp_path / "captured-production-profile.sb"
        shutil.copyfile(command[2], captured["profile_path"])
        captured["profile"] = captured["profile_path"].read_text(encoding="utf-8")
        raise RuntimeError("probe complete")

    real_popen = subprocess.Popen
    monkeypatch.setattr(workflow.subprocess, "Popen", stop)
    with pytest.raises(RuntimeError, match="probe complete"):
        workflow._production_dispatch_handoffs(
            [{"request_path": "hermes/requests/a.json", "response_path": "hermes/responses/a.json"}],
            30.0, run_dir / "revision", workflow.CERTIFIED_HERMES_CONFIGURATION,
            skill_root=skill_root, run_dir=run_dir,
            runtime_identity={"executable": sys.executable},
        )

    assert captured["command"][0] == "/usr/bin/sandbox-exec"
    assert captured["cwd"] == run_dir
    assert "-Q" in captured["command"]
    assert "--safe-mode" in captured["command"]
    assert "--skills" not in captured["command"]
    prompt = next(part for part in captured["command"] if part.startswith("Complete one isolated"))
    assert str(skill_root.resolve()) not in prompt
    assert str((run_dir / "revision").resolve()) not in prompt
    assert "profile/skills/clinical-document-generation/SKILL.md" in prompt
    assert "revision/hermes/requests/a.json" in prompt
    assert "revision/hermes/responses/a.json" in prompt
    assert "deny file-read*" in captured["profile"]
    read_rules = "\n".join(
        line for line in captured["profile"].splitlines() if "deny file-read*" in line
    )
    allow_rules = "\n".join(
        line for line in captured["profile"].splitlines() if "allow file-read*" in line
    )
    assert str(skill_root.resolve()) not in read_rules
    assert str(run_dir.resolve()) not in read_rules
    assert str(tmp_path.resolve()) in read_rules
    assert str(skill_root.resolve()) in allow_rules
    assert str(run_dir.resolve()) in allow_rules
    assert f'(literal "{authentication_path}")' in allow_rules
    assert f'(subpath "{authentication_path.parent}")' not in allow_rules
    assert f'(deny file-write* (literal "{authentication_path}"))' in captured["profile"]
    assert str(unrelated.resolve()) not in allow_rules
    assert "(deny network*)" in captured["profile"]
    proxy_url = captured["environment"]["HTTPS_PROXY"]
    assert proxy_url.startswith("http://127.0.0.1:")
    assert captured["environment"]["HTTP_PROXY"] == proxy_url
    assert captured["environment"]["ALL_PROXY"] == proxy_url
    assert captured["environment"]["NO_PROXY"] == ""
    assert f'(remote tcp "localhost:{proxy_url.rsplit(":", 1)[1]}")' in captured["profile"]
    monkeypatch.setattr(workflow.subprocess, "Popen", real_popen)
    completed = subprocess.run(
        ["/usr/bin/sandbox-exec", "-f", str(captured["profile_path"]), "/usr/bin/true"],
        capture_output=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    response_dir = run_dir / "revision/hermes/responses"
    response_dir.mkdir(parents=True)
    relative_response = "revision/hermes/responses/probe.json"
    allowed_write = subprocess.run(
        [
            "/usr/bin/sandbox-exec", "-f", str(captured["profile_path"]),
            "/usr/bin/python3", "-c",
            f"from pathlib import Path; Path({relative_response!r}).write_text('passed')",
        ],
        cwd=run_dir, capture_output=True, check=False,
    )
    assert allowed_write.returncode == 0, allowed_write.stderr
    assert (run_dir / relative_response).read_text(encoding="utf-8") == "passed"
    denied_skill_write = subprocess.run(
        [
            "/usr/bin/sandbox-exec", "-f", str(captured["profile_path"]),
            "/usr/bin/python3", "-c",
            "from pathlib import Path; Path('profile/skills/clinical-document-generation/probe').write_text('blocked')",
        ],
        cwd=tmp_path, capture_output=True, check=False,
    )
    assert denied_skill_write.returncode != 0
    assert not (skill_root / "probe").exists()
    denied_file = unrelated / "created-after-profile"
    denied_file.write_text("denied", encoding="utf-8")
    denied = subprocess.run(
        [
            "/usr/bin/sandbox-exec", "-f", str(captured["profile_path"]),
            "/bin/cat", str(denied_file),
        ],
        capture_output=True,
        check=False,
    )
    assert denied.returncode != 0
    captured["profile_path"].unlink(missing_ok=True)


def test_production_connect_proxy_relays_only_the_governed_target():
    class EchoHandler(socketserver.BaseRequestHandler):
        def handle(self):
            while payload := self.request.recv(4096):
                self.request.sendall(payload)

    upstream = socketserver.ThreadingTCPServer(("127.0.0.1", 0), EchoHandler)
    upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    upstream_thread.start()
    proxy = workflow._start_production_connect_proxy(
        "127.0.0.1", int(upstream.server_address[1]),
    )
    try:
        with socket.create_connection(("127.0.0.1", proxy.port), timeout=2.0) as client:
            target = f"127.0.0.1:{upstream.server_address[1]}"
            client.sendall(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n".encode("ascii"))
            assert client.recv(4096).startswith(b"HTTP/1.1 200")
            client.sendall(b"governed-relay")
            assert client.recv(4096) == b"governed-relay"
        with socket.create_connection(("127.0.0.1", proxy.port), timeout=2.0) as client:
            client.sendall(b"CONNECT example.com:443 HTTP/1.1\r\n\r\n")
            assert client.recv(4096).startswith(b"HTTP/1.1 403")
    finally:
        proxy.close()
        upstream.shutdown()
        upstream.server_close()
        upstream_thread.join(timeout=5.0)


def test_production_connect_proxy_attempts_every_close_after_shutdown_failure():
    calls = []

    class FakeServer:
        server_address = ("127.0.0.1", 43100)

        def shutdown(self):
            calls.append("shutdown")
            raise RuntimeError("shutdown failed")

        def server_close(self):
            calls.append("server_close")

    class FakeThread:
        def join(self, timeout=None):
            calls.append(("join", timeout))

        def is_alive(self):
            return True

    proxy = workflow._ProductionConnectProxy(FakeServer(), FakeThread())

    with pytest.raises(RuntimeError, match="could not be fully closed"):
        proxy.close()

    assert calls == ["shutdown", "server_close", ("join", 5.0)]


def test_production_connect_proxy_treats_peer_reset_as_normal_close(monkeypatch):
    class FakeClient:
        def __init__(self):
            self.reads = 0

        def settimeout(self, _timeout):
            pass

        def recv(self, _size):
            self.reads += 1
            if self.reads == 1:
                return b"CONNECT chatgpt.com:443 HTTP/1.1\r\n\r\n"
            raise ConnectionResetError("peer closed")

        def sendall(self, _payload):
            pass

    class FakeUpstream:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def settimeout(self, _timeout):
            pass

        def recv(self, _size):
            return b""

        def sendall(self, _payload):
            pass

    client = FakeClient()
    server = object.__new__(workflow._ProductionConnectProxyServer)
    server.governed_host = "chatgpt.com"
    server.governed_port = 443
    monkeypatch.setattr(workflow.socket, "create_connection", lambda *_args, **_kwargs: FakeUpstream())
    monkeypatch.setattr(workflow.select, "select", lambda *_args, **_kwargs: ([client], (), ()))

    workflow._ProductionConnectProxyHandler(client, ("127.0.0.1", 12345), server)

    assert client.reads == 2


def test_production_connect_proxy_closes_listener_when_thread_construction_fails(monkeypatch):
    calls = []

    class FakeServer:
        def __init__(self, host, port):
            calls.append(("server", host, port))

        def serve_forever(self):
            raise AssertionError("must not run")

        def server_close(self):
            calls.append("server_close")

    class FakeThread:
        def __init__(self, **_kwargs):
            calls.append("thread_constructor")
            raise RuntimeError("thread construction failed")

    monkeypatch.setattr(workflow, "_ProductionConnectProxyServer", FakeServer)
    monkeypatch.setattr(workflow.threading, "Thread", FakeThread)

    with pytest.raises(RuntimeError, match="thread construction failed"):
        workflow._start_production_connect_proxy()

    assert calls == [
        ("server", workflow.PRODUCTION_HERMES_NETWORK_HOST, workflow.PRODUCTION_HERMES_NETWORK_PORT),
        "thread_constructor",
        "server_close",
    ]


def test_production_connect_proxy_closes_listener_when_thread_start_fails(monkeypatch):
    calls = []

    class FakeServer:
        def __init__(self, host, port):
            calls.append(("server", host, port))

        def serve_forever(self):
            raise AssertionError("must not run")

        def shutdown(self):
            calls.append("shutdown")

        def server_close(self):
            calls.append("server_close")

    class FakeThread:
        def __init__(self, **kwargs):
            calls.append(("thread", kwargs["daemon"]))
            self.alive = False

        def start(self):
            self.alive = True
            raise RuntimeError("thread start failed")

        def join(self, timeout=None):
            calls.append(("join", timeout))
            self.alive = False

        def is_alive(self):
            return self.alive

    monkeypatch.setattr(workflow, "_ProductionConnectProxyServer", FakeServer)
    monkeypatch.setattr(workflow.threading, "Thread", FakeThread)

    with pytest.raises(RuntimeError, match="thread start failed"):
        workflow._start_production_connect_proxy()

    assert calls == [
        ("server", workflow.PRODUCTION_HERMES_NETWORK_HOST, workflow.PRODUCTION_HERMES_NETWORK_PORT),
        ("thread", True),
        "shutdown",
        "server_close",
        ("join", 5.0),
    ]


def test_production_partial_launch_failure_reaps_prior_worker_and_proxies(tmp_path, monkeypatch):
    skill_root = tmp_path / "profile/skills/clinical-document-generation"
    run_dir = tmp_path / "run"
    launcher = tmp_path / "managed/hermes/venv/bin/hermes"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\n", encoding="utf-8")
    launcher.chmod(0o700)
    managed_python = launcher.parent / "python"
    managed_python.symlink_to(Path(sys.executable).resolve())
    skill_root.mkdir(parents=True)
    monkeypatch.setattr(workflow, "_managed_hermes_pair", lambda: (launcher, managed_python))

    class FakeProxy:
        def __init__(self, port, *, fail=False):
            self.port = port
            self.closed = False
            self.fail = fail

        def close(self):
            self.closed = True
            if self.fail:
                raise RuntimeError("proxy close failed")

    created_proxies = [
        FakeProxy(43101, fail=True), FakeProxy(43102), FakeProxy(43103),
    ]
    pending_proxies = iter(created_proxies)
    monkeypatch.setattr(
        workflow, "_start_production_connect_proxy", lambda: next(pending_proxies),
    )

    class FakeProcess:
        def __init__(self, pid, *, fail_first_wait=False):
            self.pid = pid
            self.returncode = None
            self.wait_calls = 0
            self.fail_first_wait = fail_first_wait

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.wait_calls += 1
            if self.fail_first_wait and self.wait_calls == 1:
                raise PermissionError("wait denied")
            self.returncode = -signal.SIGKILL
            return self.returncode

    processes = [FakeProcess(987654, fail_first_wait=True), FakeProcess(987655)]
    calls = []
    profile_paths = []

    def popen(command, **_kwargs):
        calls.append(command)
        profile_paths.append(Path(command[2]))
        if len(calls) <= 2:
            return processes[len(calls) - 1]
        raise RuntimeError("third launch failed")

    killed = []

    def killpg(pid, sig):
        killed.append((pid, sig))
        if pid == processes[0].pid and sig == signal.SIGTERM:
            raise PermissionError("term denied")

    monkeypatch.setattr(workflow.subprocess, "Popen", popen)
    monkeypatch.setattr(workflow.os, "killpg", killpg)

    with pytest.raises(RuntimeError, match="third launch failed"):
        workflow._production_dispatch_handoffs(
            [
                {"request_path": "hermes/requests/a.json", "response_path": "hermes/responses/a.json"},
                {"request_path": "hermes/requests/b.json", "response_path": "hermes/responses/b.json"},
                {"request_path": "hermes/requests/c.json", "response_path": "hermes/responses/c.json"},
            ],
            30.0, run_dir / "revision", workflow.CERTIFIED_HERMES_CONFIGURATION,
            skill_root=skill_root, run_dir=run_dir,
            runtime_identity={"executable": "/usr/bin/python3"},
        )

    assert len(created_proxies) == 3
    assert all(proxy.closed for proxy in created_proxies)
    assert [process.wait_calls for process in processes] == [2, 1]
    assert killed == [
        (processes[0].pid, signal.SIGTERM),
        (processes[0].pid, signal.SIGKILL),
        (processes[1].pid, signal.SIGTERM),
    ]
    assert all(not path.exists() for path in profile_paths)


def test_production_profile_write_failure_closes_proxy_and_removes_profile(tmp_path, monkeypatch):
    skill_root = tmp_path / "profile/skills/clinical-document-generation"
    run_dir = tmp_path / "run"
    launcher = tmp_path / "managed/hermes/venv/bin/hermes"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\n", encoding="utf-8")
    launcher.chmod(0o700)
    managed_python = launcher.parent / "python"
    managed_python.symlink_to(Path(sys.executable).resolve())
    skill_root.mkdir(parents=True)
    monkeypatch.setattr(workflow, "_managed_hermes_pair", lambda: (launcher, managed_python))

    profile_path = tmp_path / "failed-profile.sb"

    class FailingProfile:
        name = str(profile_path)
        closed = False

        def write(self, _text):
            profile_path.write_text("partial", encoding="utf-8")
            raise RuntimeError("profile write failed")

        def close(self):
            self.closed = True
            raise RuntimeError("profile close failed")

    class FakeProxy:
        port = 43103
        closed = False

        def close(self):
            self.closed = True

    profile = FailingProfile()
    proxy = FakeProxy()
    monkeypatch.setattr(workflow.tempfile, "NamedTemporaryFile", lambda *_args, **_kwargs: profile)
    monkeypatch.setattr(workflow, "_start_production_connect_proxy", lambda: proxy)

    with pytest.raises(RuntimeError, match="profile write failed"):
        workflow._production_dispatch_handoffs(
            [{"request_path": "hermes/requests/a.json", "response_path": "hermes/responses/a.json"}],
            30.0, run_dir / "revision", workflow.CERTIFIED_HERMES_CONFIGURATION,
            skill_root=skill_root, run_dir=run_dir,
            runtime_identity={"executable": "/usr/bin/python3"},
        )

    assert profile.closed is True
    assert proxy.closed is True
    assert not profile_path.exists()


def test_production_sandbox_allows_bound_resolved_managed_interpreter(tmp_path, monkeypatch):
    probe_root = Path("/private/tmp") / f"issue56-managed-sandbox-{os.getpid()}"
    shutil.rmtree(probe_root, ignore_errors=True)
    skill_root = probe_root / "profile/skills/clinical-document-generation"
    run_dir = probe_root / "run"
    launcher = probe_root / "managed/hermes/venv/bin/hermes"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\n", encoding="utf-8")
    launcher.chmod(0o700)
    managed_python = launcher.parent / "python"
    managed_python.symlink_to(Path(sys.executable).resolve())
    skill_root.mkdir(parents=True)
    captured = {}
    monkeypatch.setattr(
        workflow, "_managed_hermes_pair", lambda: (launcher, managed_python),
    )
    real_popen = subprocess.Popen

    def stop(command, **_kwargs):
        captured["profile_path"] = probe_root / "captured-production-profile.sb"
        shutil.copyfile(command[2], captured["profile_path"])
        raise RuntimeError("probe complete")

    monkeypatch.setattr(workflow.subprocess, "Popen", stop)
    try:
        with pytest.raises(RuntimeError, match="probe complete"):
            workflow._production_dispatch_handoffs(
                [{
                    "request_path": "hermes/requests/a.json",
                    "response_path": "hermes/responses/a.json",
                }],
                30.0,
                run_dir / "revision",
                workflow.CERTIFIED_HERMES_CONFIGURATION,
                skill_root=skill_root,
                run_dir=run_dir,
                runtime_identity={"executable": "/usr/bin/python3"},
            )
        monkeypatch.setattr(workflow.subprocess, "Popen", real_popen)
        assert captured["profile_path"].stat().st_size <= 65_535
        unrelated_home_file = Path.home() / f"issue56-sandbox-denied-{os.getpid()}.txt"
        unrelated_private_tmp = Path("/private/tmp") / f"issue56-sandbox-denied-{os.getpid()}.txt"
        unrelated_mac_tmp = tmp_path / "created-after-profile.txt"
        for sentinel in (unrelated_home_file, unrelated_private_tmp, unrelated_mac_tmp):
            sentinel.write_text("denied", encoding="utf-8")

        for interpreter in (managed_python, managed_python.resolve(strict=True)):
            completed = subprocess.run(
                [
                    "/usr/bin/sandbox-exec", "-f", str(captured["profile_path"]),
                    str(interpreter), "-c", "print('managed-interpreter-ok')",
                ],
                cwd=run_dir,
                capture_output=True,
                text=True,
                check=False,
            )
            assert completed.returncode == 0, completed.stderr
            assert completed.stdout.strip() == "managed-interpreter-ok"

        for sentinel in (unrelated_home_file, unrelated_private_tmp, unrelated_mac_tmp):
            denied = subprocess.run(
                [
                    "/usr/bin/sandbox-exec", "-f", str(captured["profile_path"]),
                    "/bin/cat", str(sentinel),
                ],
                capture_output=True,
                check=False,
            )
            assert denied.returncode != 0
    finally:
        Path(captured.get("profile_path", "")).unlink(missing_ok=True)
        for sentinel in (
            Path.home() / f"issue56-sandbox-denied-{os.getpid()}.txt",
            Path("/private/tmp") / f"issue56-sandbox-denied-{os.getpid()}.txt",
            tmp_path / "created-after-profile.txt",
        ):
            sentinel.unlink(missing_ok=True)
        shutil.rmtree(probe_root, ignore_errors=True)


def test_production_read_boundaries_are_stable_and_broad():
    boundaries = workflow._production_read_boundaries()

    assert Path("/Users") in boundaries
    assert Path("/private/tmp") in boundaries
    assert Path("/Volumes") in boundaries
    assert Path(workflow.tempfile.gettempdir()).resolve() in boundaries


def test_production_parent_fallback_never_redispatches_or_claims_parent_provenance(
    tmp_path, monkeypatch,
):
    skill_root = tmp_path / "profile/skills/clinical-document-generation"
    skill_root.mkdir(parents=True)
    reference = tmp_path / "run/reference/study.reference.json"
    reference.parent.mkdir(parents=True)
    reference.write_text(json.dumps({"approval": {"revision_id": "r1"}}), encoding="utf-8")
    monkeypatch.setattr(workflow, "_installed_release_identity", lambda _root: {
        "package_fingerprint": "installed", "git_commit": "abc", "source": "test",
    })
    monkeypatch.setattr(
        workflow, "resolve_python_runtime",
        lambda **_kwargs: {"executable": sys.executable, "version_info": [3, 11, 0]},
    )

    def invoke_fallback(_run_dir, **options):
        options["fallback_handoff_runner"]([{
            "request_path": "hermes/verification-requests/visual.json",
            "response_path": "hermes/verification-responses/visual.json",
        }], 10.0)

    monkeypatch.setattr(workflow, "run_desktop_operation", invoke_fallback)
    monkeypatch.setattr(
        workflow, "_production_dispatch_handoffs",
        lambda *_args, **_kwargs: pytest.fail("parent fallback must not redispatch to a worker"),
    )

    with pytest.raises(RuntimeError, match="genuine Desktop-parent"):
        workflow.run_production_desktop_operation(
            tmp_path / "run", skill_root=skill_root,
            opener=lambda _path: b"unused",
            release_identity={"package_fingerprint": "installed", "git_commit": "abc"},
        )
    assert not (tmp_path / "run/logs/desktop-parent-visual-review.json").exists()


def test_external_parent_visual_reviewer_receives_one_bound_request_path(tmp_path):
    command = tmp_path / "parent-reviewer"
    command.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    command.chmod(0o700)
    revision = tmp_path / "revisions/r1"
    revision.mkdir(parents=True)
    reviewer = workflow.command_parent_visual_reviewer(command)

    reviewer([{
        "request_path": "hermes/verification-requests/visual.json",
        "response_path": "hermes/verification-responses/visual.json",
    }], 10.0, revision, {})

    request = json.loads((revision / "hermes/desktop-parent-visual-review-request.json").read_text())
    assert request["revision_id"] == "r1"
    assert request["producer_model_policy"] == "record_actual_nonempty_model_id"
    assert len(request["handoffs"]) == 1


def test_external_parent_visual_reviewer_selects_outer_bound_response_not_nested_finding(tmp_path):
    revision = tmp_path / "revisions/r1"
    request_path = revision / "hermes/verification-requests/visual.json"
    response_path = revision / "hermes/verification-responses/visual.json"
    request_path.parent.mkdir(parents=True)
    request = {
        "schema_version": "hermes-verification/v1",
        "request_id": "r1.verify.visual.protocol",
        "task": "rendered_page_visual_verification",
        "response_path": "hermes/verification-responses/visual.json",
        "artifacts": [{"artifact": "protocol", "pages": []}],
        "checks": list(VISUAL_CHECKS),
    }
    request["request_sha256"] = verification_request_sha256(request)
    request_path.write_text(json.dumps(request), encoding="utf-8")
    response = {
        "schema_version": RESPONSE_SCHEMA,
        "request_id": request["request_id"],
        "request_sha256": request["request_sha256"],
        "task": request["task"],
        "producer": {"model_id": "test-parent-model"},
        "status": "blocked",
        "findings": [{
            "artifact": "protocol",
            "page": 3,
            "check": "bad_table_split",
            "element": "3. GENERAL INFORMATION – Variables / Secondary endpoint(s)",
            "issue": "The label is separated from its first bullet.",
        }],
        "page_assessments": [],
    }
    command = tmp_path / "parent-reviewer"
    command.write_text(
        "#!/bin/sh\nprintf '%s\\n' '" + json.dumps(response) + "'\n",
        encoding="utf-8",
    )
    command.chmod(0o700)

    reviewer = workflow.command_parent_visual_reviewer(command)
    reviewer([{
        "request_path": "hermes/verification-requests/visual.json",
        "response_path": "hermes/verification-responses/visual.json",
        "request_id": request["request_id"],
        "request_sha256": request["request_sha256"],
        "task": request["task"],
    }], 10.0, revision, {})

    assert json.loads(response_path.read_text(encoding="utf-8")) == response


def test_external_parent_visual_reviewer_binds_semantic_only_response(tmp_path):
    revision = tmp_path / "revisions/r1"
    request_path = revision / "hermes/verification-requests/visual.json"
    response_path = revision / "hermes/verification-responses/visual.json"
    request_path.parent.mkdir(parents=True)
    request = {
        "schema_version": "hermes-verification/v1",
        "request_id": "r1.verify.visual.protocol",
        "task": "rendered_page_visual_verification",
        "response_path": "hermes/verification-responses/visual.json",
        "artifacts": [{"artifact": "protocol", "pages": []}],
        "checks": list(VISUAL_CHECKS),
    }
    request["request_sha256"] = verification_request_sha256(request)
    request_path.write_text(json.dumps(request), encoding="utf-8")
    semantic_response = {
        "producer": {"model_id": "client-selected-model"},
        "status": "blocked",
        "finding": {
            "artifact": "protocol",
            "page": 3,
            "check": "bad_table_split",
            "element": "3. GENERAL INFORMATION",
            "issue": "The table split separates a label from its first item.",
        },
    }
    command = tmp_path / "parent-reviewer"
    command.write_text(
        "#!/bin/sh\nprintf '%s\\n' '" + json.dumps(semantic_response) + "'\n",
        encoding="utf-8",
    )
    command.chmod(0o700)

    workflow.command_parent_visual_reviewer(command)([{
        "request_path": "hermes/verification-requests/visual.json",
        "response_path": "hermes/verification-responses/visual.json",
    }], 10.0, revision, {})

    bound = json.loads(response_path.read_text(encoding="utf-8"))
    assert bound["schema_version"] == RESPONSE_SCHEMA
    assert bound["request_id"] == request["request_id"]
    assert bound["request_sha256"] == request["request_sha256"]
    assert bound["task"] == request["task"]
    assert bound["findings"] == [semantic_response["finding"]]
    assert set(bound["workflow_binding"]["added_fields"]) == {
        "schema_version", "request_id", "request_sha256", "task",
    }


def test_production_adapter_rejects_identity_and_configuration_rebinding(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow, "_installed_release_identity", lambda _root: {
        "package_fingerprint": "installed",
        "git_commit": "abc123",
        "source": "shipped_production_adapter",
    })

    with pytest.raises(ValueError, match="does not match the installed candidate"):
        workflow.run_production_desktop_operation(
            tmp_path,
            release_identity={"package_fingerprint": "forged", "git_commit": "abc123"},
        )

    with pytest.raises(ValueError, match="exact governed Hermes configuration"):
        workflow.run_production_desktop_operation(
            tmp_path,
            release_identity={"package_fingerprint": "installed", "git_commit": "abc123"},
            hermes_configuration={**workflow.CERTIFIED_HERMES_CONFIGURATION, "safe_mode": False},
        )

    with pytest.raises(ValueError, match="exact governed Hermes configuration"):
        workflow.run_production_desktop_operation(
            tmp_path,
            release_identity={"package_fingerprint": "installed", "git_commit": "abc123"},
            hermes_configuration={
                **workflow.CERTIFIED_HERMES_CONFIGURATION,
                "unexpected": "not-governed",
            },
        )

    with pytest.raises(ValueError, match="actual Desktop opener"):
        workflow.run_production_desktop_operation(
            tmp_path,
            release_identity={"package_fingerprint": "installed", "git_commit": "abc123"},
        )


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
    primary_calls = []
    parent_reviews = []
    monkeypatch.setattr(workflow, "generate", lambda _run_dir, **_kwargs: next(results))

    def primary(received_handoffs, timeout_seconds):
        primary_calls.append((received_handoffs, timeout_seconds))
        response_root = tmp_path / "revisions/r1/hermes/verification-responses"
        response_root.mkdir(parents=True, exist_ok=True)
        if received_handoffs == [protocol_handoff, icf_handoff]:
            response_root.joinpath("protocol.json").write_text(
                json.dumps(protocol_response), encoding="utf-8",
            )
            now[0] += timeout_seconds
        elif received_handoffs == [content_handoff]:
            content_response = {
                "request_id": content_request["request_id"],
                "request_sha256": content_request["request_sha256"],
                "task": content_request["task"],
            }
            response_root.joinpath("content.json").write_text(
                json.dumps(content_response), encoding="utf-8",
            )
        else:
            raise AssertionError(f"unexpected mixed timeout domain: {received_handoffs!r}")

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
    timeouts_by_tasks = {
        tuple(item["task"] for item in received): timeout
        for received, timeout in primary_calls
    }
    assert timeouts_by_tasks == {
        ("rendered_page_visual_verification", "rendered_page_visual_verification"): 240.0,
        ("clinical_content_verification",): 1_800.0,
    }
    assert parent_reviews == [icf_handoff]
    assert state["soft_budget_events"] == [{
        "stage": "independent_verification",
        "budget_seconds": 240.0,
        "elapsed_seconds": 240.0,
        "action": "early_parent_fallback",
    }]
    assert state["deadline_at_epoch"] == 2_800.0


def test_new_visual_request_hash_gets_a_fresh_soft_budget(tmp_path, monkeypatch):
    now = [0.0]
    first_handoff, first_request, _ = _visual_handoff_fixture(tmp_path, "protocol")
    second_request = json.loads(json.dumps(first_request))
    second_handoff = dict(first_handoff)
    second_request["request_id"] = f'{first_request["request_id"]}.retry'
    second_request["response_path"] = "hermes/verification-responses/protocol-retry.json"
    second_request.pop("request_sha256", None)
    second_request["request_sha256"] = verification_request_sha256(second_request)
    second_handoff["request_path"] = "hermes/verification-requests/protocol-retry.json"
    second_handoff["response_path"] = second_request["response_path"]
    second_handoff["request_id"] = second_request["request_id"]
    second_handoff["request_sha256"] = second_request["request_sha256"]
    second_request_path = tmp_path / "revisions/r1" / second_handoff["request_path"]
    calls = [0]

    def generate(_run_dir, **_kwargs):
        calls[0] += 1
        if calls[0] == 1:
            return {
                "status": "awaiting_hermes",
                "stage": "independent_verification",
                "revision_id": "r1",
                "handoffs": [first_handoff],
            }
        if calls[0] == 2:
            second_request_path.write_text(json.dumps(second_request), encoding="utf-8")
            return {
                "status": "awaiting_hermes",
                "stage": "independent_verification",
                "revision_id": "r1",
                "handoffs": [second_handoff],
            }
        return {"status": "blocked", "stage": "quality", "findings": [], "client_outputs": []}

    timeouts = []

    def complete_visual(handoffs, timeout_seconds):
        handoff = handoffs[0]
        timeouts.append(timeout_seconds)
        response_path = tmp_path / "revisions/r1" / handoff["response_path"]
        response_path.parent.mkdir(parents=True, exist_ok=True)
        response_path.write_text(json.dumps({
            "request_id": handoff["request_id"],
            "request_sha256": handoff["request_sha256"],
            "task": handoff["task"],
        }), encoding="utf-8")
        now[0] += timeout_seconds

    monkeypatch.setattr(workflow, "generate", generate)
    result = workflow.run_desktop_operation(
        tmp_path,
        handoff_runner=complete_visual,
        fallback_handoff_runner=lambda *_args: None,
        opener=lambda _path: b"unused",
        budget_seconds=30.0,
        stage_soft_budgets={"independent_verification": 5.0},
        clock=lambda: now[0],
        wall_clock=lambda: 1_000.0,
    )

    assert result["status"] == "blocked"
    assert timeouts == [5.0, 5.0], (result, calls, timeouts)


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


def test_parent_fallback_is_attempted_exactly_once_when_it_raises(tmp_path, monkeypatch):
    handoff, _, _ = _visual_handoff_fixture(tmp_path, "protocol")
    monkeypatch.setattr(workflow, "generate", lambda _run_dir, **_kwargs: {
        "status": "awaiting_hermes",
        "stage": "independent_verification",
        "revision_id": "r1",
        "handoffs": [handoff],
    })
    fallback_calls = []

    def failed_fallback(pending, _remaining):
        fallback_calls.append(list(pending))
        raise RuntimeError("parent fallback failed")

    def failed_worker(*_args):
        raise RuntimeError("worker failed")

    result = workflow.run_desktop_operation(
        tmp_path,
        handoff_runner=failed_worker,
        fallback_handoff_runner=failed_fallback,
        opener=lambda _path: b"unused",
        budget_seconds=30.0,
    )

    assert result["status"] == "blocked"
    assert fallback_calls == [[handoff]]


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
    pdf = revision_dir / "rendered/protocol.pdf"
    page = revision_dir / "rendered/protocol/page-01.png"
    page.parent.mkdir(parents=True)
    pdf.write_bytes(b"approved pdf")
    page.write_bytes(b"approved page")
    (revision_dir / "candidate-build.json").write_text(json.dumps({
        "candidate_files": [{
            "path": "candidate/protocol.docx",
            "sha256": workflow.quality_sha256(candidate / "protocol.docx"),
            "bytes": (candidate / "protocol.docx").stat().st_size,
        }],
        "render_report": {"status": "passed", "artifacts": [{
            "artifact": "protocol",
            "status": "passed",
            "docx": "candidate/protocol.docx",
            "docx_sha256": workflow.quality_sha256(candidate / "protocol.docx"),
            "pdf": "rendered/protocol.pdf",
            "pdf_sha256": workflow.quality_sha256(pdf),
            "page_count": 1,
            "pages": [{
                "page": 1,
                "path": "rendered/protocol/page-01.png",
                "sha256": workflow.quality_sha256(page),
            }],
        }]},
    }), encoding="utf-8")
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
