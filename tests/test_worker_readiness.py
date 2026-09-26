"""Worker environment defects must be found before consuming study time."""
import json
import subprocess
from pathlib import Path

import pytest
import workflow


@pytest.mark.parametrize("logged_in", [True, False])
def test_readiness_checks_exact_worker_profile_and_never_records_credentials(tmp_path, monkeypatch, logged_in):
    root = tmp_path / "profile/skills/clinical-document-generation"
    root.mkdir(parents=True)
    launcher = tmp_path / "hermes/bin/hermes"
    monkeypatch.setattr(workflow, "_managed_hermes_pair", lambda: (launcher, Path("/fake/python")))
    captured = {}

    def run(command, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(command, 0, json.dumps({
            "logged_in": logged_in, "provider": "openai-codex",
            "access_token": "secret-not-for-logs",
        }), "secret-not-for-logs")

    monkeypatch.setattr(workflow.subprocess, "run", run)
    result = workflow._production_worker_readiness(root)
    assert captured["env"]["HERMES_HOME"] == str(root.parent.parent)
    assert captured["timeout"] <= 20
    assert result["status"] == ("passed" if logged_in else "blocked")
    assert "secret-not-for-logs" not in json.dumps(result)


def test_logged_out_worker_stops_before_creating_the_deadline(tmp_path, monkeypatch):
    root = tmp_path / "profile/skills/clinical-document-generation"
    root.mkdir(parents=True)
    monkeypatch.setattr(workflow, "_installed_release_identity", lambda root: {"package_fingerprint": "test"})
    monkeypatch.setattr(workflow, "_pdfium_runtime_integrity", lambda *a, **k: {"status": "passed"})
    monkeypatch.setattr(workflow, "resolve_python_runtime", lambda **k: {"executable": "/fake/python"})
    monkeypatch.setattr(workflow, "_managed_hermes_identity", lambda: {})
    monkeypatch.setattr(workflow, "_production_worker_readiness", lambda root: {
        "status": "blocked", "logged_in": False, "provider": "openai-codex",
        "issue": "The isolated worker is logged out.",
    })
    monkeypatch.setattr(workflow, "run_desktop_operation", lambda *a, **k: pytest.fail("Deadline started while logged out"))
    result = workflow.run_production_desktop_operation(
        tmp_path / "run", skill_root=root, manual_review=True, opener=lambda path: b"",
    )
    assert result["stage"] == "worker_readiness"
    assert not (tmp_path / "run/logs/desktop-operation.json").exists()


@pytest.mark.parametrize("visual_fallback", [False, True])
def test_authentication_failure_during_handoff_is_not_redispatched(tmp_path, monkeypatch, visual_fallback):
    request = {"request_path": "draft.json", "response_path": "response.json", "task": "section_drafting"}
    if visual_fallback:
        request.update(task="rendered_page_visual_verification", fallback_owner="parent")
    monkeypatch.setattr(workflow, "generate", lambda *a, **k: {
        "status": "awaiting_hermes",
        "stage": "independent_verification" if visual_fallback else "drafting",
        "revision_id": "r1", "handoffs": [request],
    })
    calls = []

    def dispatch(*args):
        calls.append(1)
        raise workflow.WorkerAuthenticationError("The worker subscription is logged out.")

    result = workflow.run_desktop_operation(
        tmp_path, handoff_runner=dispatch, opener=lambda path: b"", budget_seconds=30,
    )
    assert result["stage"] == "worker_authentication"
    assert len(calls) == 1

@pytest.mark.parametrize("message, expected", [
    ("HTTP 401: Incorrect API key provided: masked", True),
    ("No Codex credentials available", True),
    ("Connection reset by peer", False),
    ("The clinical draft discusses authentication procedures", False),
])
def test_worker_log_diagnosis_distinguishes_authentication_from_transient_failure(tmp_path, message, expected):
    log = tmp_path / "worker.log"
    log.write_text(message)
    assert workflow._worker_log_reports_authentication_failure([log]) is expected
