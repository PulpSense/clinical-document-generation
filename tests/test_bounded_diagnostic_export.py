"""Public Desktop terminal exports must not amplify private worker profiles."""
import errno
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

import pytest
import storage_retention
import workflow


def _terminal(run, monkeypatch):
    monkeypatch.setattr(workflow, "generate", lambda *_args, **_kwargs: {
        "status": "blocked", "stage": "quality", "client_outputs": [],
        "findings": [{"issue": "Offline terminal fixture; no complete candidate."}],
    })
    return workflow.run_desktop_operation(
        run, handoff_runner=lambda *_args: None,
        opener=lambda path: Path(path).read_bytes(), budget_seconds=30,
        clock=lambda: 0.0, wall_clock=lambda: 1000.0,
        runtime_identity={"executable": "/test/python", "version": "3.13.0"},
        release_identity={"package_fingerprint": "offline-diagnostic-fixture"},
    )


def _put(run, relative, data):
    path = run / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_desktop_exports_evidence_within_quota_without_private_worker_amplification(tmp_path, monkeypatch):
    run = tmp_path / "run"
    required = {
        "input/source.md": b"approved fixture source",
        "revisions/r1/candidate/protocol.docx": b"unique native fixture",
        "revisions/r1/render/protocol.pdf": b"unique PDF fixture",
        "revisions/r1/render/page-1.png": b"unique page fixture",
        "revisions/r1/hermes/requests/review.json": b"unique request",
        "revisions/r1/hermes/responses/review.json": b"unique response",
        "logs/hermes-agents/worker.stderr.log": b"unique worker error",
        ".hermes-cache/worker/diagnostic.json": b"unique worker diagnostic",
        ".hermes-cache/worker/logs/agent.log": b"unique worker execution trace",
        ".hermes-cache/worker/logs/errors.log": b"unique worker failure detail",
        "revisions/r1/hermes/visual-review-observers/observer/provenance.json": b"unique provenance",
        "revisions/r1/hermes/visual-review-observers/observer/stdout.log": b"unique stdout",
    }
    private = {
        ".hermes-cache/worker/auth.json": b"synthetic-secret-token",
        ".hermes-cache/worker/config.yaml": b"synthetic-private-config",
        ".hermes-cache/worker/.env": b"synthetic-private-environment",
        ".hermes-cache/worker/state.db": b"private-session" * 20000,
        ".hermes-cache/worker/skills/large/SKILL.md": b"copied skill" * 20000,
        "revisions/r1/hermes/visual-review-observers/observer/.cache/blob": b"private cache" * 20000,
        "revisions/r1/hermes/visual-review-observers/observer/sessions/session.json": b"private session",
    }
    original = {name: _put(run, name, data).read_bytes() for name, data in {**required, **private}.items()}
    # Model an output-volume quota, not a full disk: reject cumulative member
    # writes beyond 128 KiB, without allocating disk-filling fixture payloads.
    original_open = ZipFile.open
    written = [0]
    def quota_open(self, name, mode="r", *args, **kwargs):
        member = original_open(self, name, mode, *args, **kwargs)
        if mode == "w":
            original_write = member.write
            def bounded_write(data):
                written[0] += len(data)
                if written[0] > 128 * 1024:
                    raise OSError(errno.ENOSPC, "injected diagnostic export quota")
                return original_write(data)
            member.write = bounded_write
        return member
    monkeypatch.setattr(ZipFile, "open", quota_open)

    result = _terminal(run, monkeypatch)

    assert "diagnostic_archive_error" not in result, result.get("diagnostic_archive_error")
    assert result["status"] == "blocked"
    assert result["client_outputs"] == []
    assert not result.get("review_outputs")
    path = run / result["diagnostic_archive"]["path"]
    assert path.stat().st_size < 128 * 1024
    assert hashlib.sha256(path.read_bytes()).hexdigest() == result["diagnostic_archive"]["sha256"]
    with ZipFile(path) as archive:
        assert archive.testzip() is None
        assert set(required) <= set(archive.namelist())
        assert not set(private).intersection(archive.namelist())
        assert "logs/desktop-operation.json" in archive.namelist()
        inventory = json.loads(archive.read("diagnostic-inventory.json"))
        assert {row["path"] for row in inventory["files"]} == set(archive.namelist()) - {"diagnostic-inventory.json"}
        for row in inventory["files"]:
            data = archive.read(row["path"])
            assert len(data) == row["bytes"]
            assert hashlib.sha256(data).hexdigest() == row["sha256"]
        for name, data in required.items():
            assert archive.read(name) == data
    assert {name: (run / name).read_bytes() for name in original} == original
    assert not list((run / "output").glob(".diagnostics-*"))


def test_low_capacity_refuses_before_temporary_creation_keeps_previous_export(tmp_path, monkeypatch):
    run = tmp_path / "run"
    previous = _put(run, "output/BLOCKED-RUN-DIAGNOSTICS.zip", b"previous exact archive")
    source = _put(run, "input/source.md", b"unique source")
    original_usage = storage_retention.shutil.disk_usage
    measured = []
    def no_capacity(path):
        measured.append(Path(path))
        usage = original_usage(path)
        return type(usage)(usage.total, usage.used, 0)
    monkeypatch.setattr(storage_retention.shutil, "disk_usage", no_capacity)
    def no_temporary(*_args, **_kwargs):
        pytest.fail("Capacity refusal must precede allocating an archive")
    monkeypatch.setattr(workflow.tempfile, "NamedTemporaryFile", no_temporary)

    result = _terminal(run, monkeypatch)

    assert result["status"] == "blocked"
    assert result["client_outputs"] == []
    assert "Insufficient diagnostic export capacity" in result["diagnostic_archive_error"]
    assert measured == [run / "output"]
    assert previous.read_bytes() == b"previous exact archive"
    assert source.read_bytes() == b"unique source"
    assert not list((run / "output").glob(".diagnostics-*"))


@pytest.mark.parametrize("fault", ["enospc", "changed_source", "corrupt_readback"])
def test_failed_export_retains_prior_archive_and_local_evidence(tmp_path, monkeypatch, fault):
    run = tmp_path / "run"
    previous = _put(run, "output/BLOCKED-RUN-DIAGNOSTICS.zip", b"previous exact archive")
    source = _put(run, "input/source.md", b"unique source")
    original_open = ZipFile.open
    def broken_open(self, name, mode="r", *args, **kwargs):
        member = original_open(self, name, mode, *args, **kwargs)
        if name == "input/source.md" and mode == "w":
            if fault == "changed_source":
                source.write_bytes(b"concurrently changed source")
            if fault == "enospc":
                def failed_write(_data):
                    raise OSError(errno.ENOSPC, "injected volume exhaustion")
                member.write = failed_write
        if name == "input/source.md" and mode == "r" and fault == "corrupt_readback":
            original_read = member.read
            def corrupt_read(*read_args, **read_kwargs):
                data = original_read(*read_args, **read_kwargs)
                return b"X" + data[1:] if data else data
            member.read = corrupt_read
        return member
    monkeypatch.setattr(ZipFile, "open", broken_open)

    result = _terminal(run, monkeypatch)

    assert result["status"] == "blocked"
    assert "diagnostic_archive" not in result
    expected = {"enospc": "injected volume exhaustion", "changed_source": "changed during export",
                "corrupt_readback": "member integrity differs"}[fault]
    assert expected in result["diagnostic_archive_error"]
    assert previous.read_bytes() == b"previous exact archive"
    assert source.read_bytes() == (b"concurrently changed source" if fault == "changed_source" else b"unique source")
    assert not list((run / "output").glob(".diagnostics-*"))


def test_export_omits_symlink_files_and_directories_without_modifying_targets(tmp_path, monkeypatch):
    run = tmp_path / "run"
    source = _put(run, "input/source.md", b"unique source")
    external = _put(tmp_path, "private/token.txt", b"synthetic external private bytes")
    (run / "linked-private").symlink_to(external.parent, target_is_directory=True)
    (run / "input/linked-file").symlink_to(external)
    result = _terminal(run, monkeypatch)
    with ZipFile(run / result["diagnostic_archive"]["path"]) as archive:
        assert not any("linked-" in name for name in archive.namelist())
        assert archive.read("input/source.md") == source.read_bytes()
    assert external.read_bytes() == b"synthetic external private bytes"
    assert (run / "linked-private").is_symlink()


def test_export_rejects_output_directory_symlink_without_touching_external_directory(tmp_path, monkeypatch):
    run = tmp_path / "run"
    _put(run, "input/source.md", b"unique source")
    external = tmp_path / "external"
    external.mkdir()
    (run / "output").symlink_to(external, target_is_directory=True)
    result = _terminal(run, monkeypatch)
    assert result["status"] == "blocked"
    assert "must not be a symlink" in result["diagnostic_archive_error"]
    assert list(external.iterdir()) == []


@pytest.mark.parametrize("study_type", ["Prospective", "Ambispective", "Retrospective"])
@pytest.mark.parametrize("candidate_state", ["complete", "missing", "tampered"])
def test_diagnostic_export_does_not_relax_branch_review_admission(tmp_path, monkeypatch, study_type, candidate_state):
    from test_review_output import _candidate_run
    run, candidate = _candidate_run(tmp_path, monkeypatch, study_type)
    protocol = candidate / "protocol.docx"
    if candidate_state == "missing":
        protocol.unlink()
    elif candidate_state == "tampered":
        protocol.write_bytes(b"changed after candidate evidence")

    result = _terminal(run, monkeypatch)

    assert "diagnostic_archive" in result
    assert result["client_outputs"] == []
    if candidate_state == "complete":
        assert result["status"] == "review_required"
        expected = {"REVIEW-ONLY-" + name for name in workflow.document_set(study_type)}
        assert {Path(row["path"]).name for row in result["review_outputs"]} == expected
        assert result["review_delivery"]["bytes_verified"] is True
    else:
        assert result["status"] == "blocked"
        assert not result.get("review_outputs")
        assert not (run / "review-output").exists()
    with ZipFile(run / result["diagnostic_archive"]["path"]) as archive:
        assert archive.testzip() is None
        saved = json.loads(archive.read("logs/desktop-operation.json"))
        assert saved["status"] == result["status"]
