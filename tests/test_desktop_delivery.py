import json

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
    monkeypatch.setattr(workflow, "generate", lambda run_dir: next(results))

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


def test_desktop_operation_uses_one_persistent_deadline_and_does_not_resume_after_timeout(tmp_path, monkeypatch):
    now = [100.0]
    generated = []
    monkeypatch.setattr(workflow, "generate", lambda run_dir: generated.append(True) or {
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
    assert second["deadline_monotonic"] == first["deadline_monotonic"]


def test_desktop_operation_does_not_report_delivery_when_attachment_retrieval_fails(tmp_path, monkeypatch):
    manifest = _manifest()
    manifest_path = tmp_path / "revisions/r1/delivery-manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(workflow, "generate", lambda run_dir: {
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
