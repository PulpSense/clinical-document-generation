import hashlib
import json
from pathlib import Path

import pytest

import workflow


def _publish_fixture(tmp_path: Path):
    run_dir = tmp_path / "run"
    revision_dir = run_dir / "revisions/r-test"
    candidate = revision_dir / "candidate"
    candidate.mkdir(parents=True)
    (candidate / "protocol.docx").write_bytes(b"new protocol")
    (candidate / "icf.docx").write_bytes(b"new icf")
    (candidate / "study.xml").write_bytes(b"<clinical_study/>")
    (revision_dir / "approved-reference.json").write_text("{}", encoding="utf-8")
    candidate_files = [
        {
            "path": path.relative_to(revision_dir).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size,
        }
        for path in sorted(candidate.iterdir())
    ]
    rendered = revision_dir / "rendered"
    render_artifacts = []
    for artifact in ("icf", "protocol"):
        pdf = rendered / f"{artifact}.pdf"
        page = rendered / artifact / "page-01.png"
        page.parent.mkdir(parents=True, exist_ok=True)
        pdf.write_bytes(f"approved {artifact} pdf".encode())
        page.write_bytes(f"approved {artifact} page".encode())
        render_artifacts.append({
            "artifact": artifact,
            "status": "passed",
            "docx": f"candidate/{artifact}.docx",
            "docx_sha256": hashlib.sha256((candidate / f"{artifact}.docx").read_bytes()).hexdigest(),
            "pdf": f"rendered/{artifact}.pdf",
            "pdf_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
            "page_count": 1,
            "pages": [{
                "page": 1,
                "path": f"rendered/{artifact}/page-01.png",
                "sha256": hashlib.sha256(page.read_bytes()).hexdigest(),
            }],
        })
    (revision_dir / "candidate-build.json").write_text(json.dumps({
        "governing_resources": {},
        "candidate_files": candidate_files,
        "render_report": {"status": "passed", "artifacts": render_artifacts},
    }), encoding="utf-8")
    output = run_dir / "output"
    output.mkdir()
    (output / "protocol.docx").write_bytes(b"old protocol")
    (output / "obsolete.txt").write_text("old", encoding="utf-8")
    reference = {
        "meta": {"study_type": "Prospective"},
        "approval": {"source_sha256": "approved"},
    }
    return run_dir, revision_dir, reference


@pytest.mark.parametrize("changed_evidence", ["docx", "pdf", "page"])
def test_publish_rejects_changed_bytes_after_evidence_and_preserves_prior_output(tmp_path, changed_evidence):
    run_dir, revision_dir, reference = _publish_fixture(tmp_path)
    rendered = revision_dir / "rendered"
    page = rendered / "protocol/page-01.png"
    pdf = rendered / "protocol.pdf"

    changed = {
        "docx": revision_dir / "candidate/protocol.docx",
        "pdf": pdf,
        "page": page,
    }[changed_evidence]
    changed.write_bytes(b"changed after evidence")

    with pytest.raises(RuntimeError, match="stale publication evidence"):
        workflow._publish(run_dir, revision_dir, reference, {})

    assert (run_dir / "output/protocol.docx").read_bytes() == b"old protocol"
    assert sorted(path.name for path in (run_dir / "output").iterdir()) == ["obsolete.txt", "protocol.docx"]


def test_publish_rechecks_reviewed_evidence_after_staging(tmp_path, monkeypatch):
    run_dir, revision_dir, reference = _publish_fixture(tmp_path)
    page = revision_dir / "rendered/protocol/page-01.png"
    pdf = revision_dir / "rendered/protocol.pdf"
    original_copy = workflow.shutil.copy2

    def mutate_reviewed_page_after_copy(source, target):
        copied = original_copy(source, target)
        page.write_bytes(b"changed during staging")
        return copied

    monkeypatch.setattr(workflow.shutil, "copy2", mutate_reviewed_page_after_copy)

    with pytest.raises(RuntimeError, match="stale publication evidence"):
        workflow._publish(run_dir, revision_dir, reference, {})

    assert (run_dir / "output/protocol.docx").read_bytes() == b"old protocol"


def test_publish_failure_keeps_the_previous_package_intact(tmp_path, monkeypatch):
    run_dir, revision_dir, reference = _publish_fixture(tmp_path)
    original_copy = workflow.shutil.copy2
    copies = 0

    def interrupted_copy(source, target):
        nonlocal copies
        copies += 1
        if copies == 2:
            raise OSError("simulated interruption")
        return original_copy(source, target)

    monkeypatch.setattr(workflow.shutil, "copy2", interrupted_copy)

    with pytest.raises(OSError, match="simulated interruption"):
        workflow._publish(run_dir, revision_dir, reference, {})

    assert (run_dir / "output/protocol.docx").read_bytes() == b"old protocol"
    assert (run_dir / "output/obsolete.txt").read_text(encoding="utf-8") == "old"
    assert sorted(path.name for path in (run_dir / "output").iterdir()) == ["obsolete.txt", "protocol.docx"]


def test_publish_rejects_truncated_render_inventory(tmp_path):
    run_dir, revision_dir, reference = _publish_fixture(tmp_path)
    build_path = revision_dir / "candidate-build.json"
    build = json.loads(build_path.read_text(encoding="utf-8"))
    build["render_report"]["artifacts"] = []
    build_path.write_text(json.dumps(build), encoding="utf-8")

    with pytest.raises(RuntimeError, match="stale publication evidence"):
        workflow._publish(run_dir, revision_dir, reference, {})

    assert (run_dir / "output/protocol.docx").read_bytes() == b"old protocol"


def test_publish_swaps_the_complete_package_and_removes_obsolete_outputs(tmp_path):
    run_dir, revision_dir, reference = _publish_fixture(tmp_path)

    result = workflow._publish(run_dir, revision_dir, reference, {})

    assert result["status"] == "passed"
    assert sorted(path.name for path in (run_dir / "output").iterdir()) == ["icf.docx", "protocol.docx", "study.xml"]
    assert (run_dir / "output/protocol.docx").read_bytes() == b"new protocol"


def test_failed_quality_attempt_evidence_is_archived_immutably(tmp_path):
    revision_dir = tmp_path / "revisions/r-traceable"
    (revision_dir / "candidate").mkdir(parents=True)
    (revision_dir / "rendered/protocol").mkdir(parents=True)
    (revision_dir / "hermes/verification-responses").mkdir(parents=True)
    (revision_dir / "candidate/protocol.docx").write_bytes(b"failed candidate one")
    (revision_dir / "rendered/protocol/page-01.png").write_bytes(b"failed page one")
    (revision_dir / "candidate-build.json").write_text('{"fingerprint":"one"}', encoding="utf-8")
    (revision_dir / "hermes/verification-responses/check.json").write_text('{"status":"failed"}', encoding="utf-8")

    first = workflow._archive_failed_attempt(
        revision_dir,
        "quality",
        [{"category": "visual", "issue": "First failed page"}],
    )
    first_candidate = first / "candidate/protocol.docx"
    assert first_candidate.read_bytes() == b"failed candidate one"
    first_manifest = json.loads((first / "attempt-manifest.json").read_text(encoding="utf-8"))
    first_ledger = json.loads((first / "gate-ledger.json").read_text(encoding="utf-8"))
    assert first_manifest["revision_id"] == "r-traceable"
    assert first_manifest["findings"][0]["issue"] == "First failed page"
    assert first_manifest["gate_ledger_sha256"] == first_ledger["ledger_sha256"]
    assert first_ledger["attempt_id"] == "r-traceable"
    assert first_ledger["records"][4]["terminal_status"] == "blocked"

    (revision_dir / "candidate/protocol.docx").write_bytes(b"failed candidate two")
    second = workflow._archive_failed_attempt(
        revision_dir,
        "quality",
        [{"category": "visual", "issue": "Second failed page"}],
    )

    assert second != first
    second_ledger = json.loads((second / "gate-ledger.json").read_text(encoding="utf-8"))
    assert second_ledger["predecessors"][-1]["ledger_sha256"] == first_ledger["ledger_sha256"]
    assert second_ledger["predecessors"][-1]["blocked_findings"] == first_ledger["records"][4]["findings"]
    prepared = workflow._prepared_gate_ledger(revision_dir, {}, {}, [])
    assert [item["ledger_sha256"] for item in prepared["predecessors"]] == [
        first_ledger["ledger_sha256"],
        second_ledger["ledger_sha256"],
    ]
    assert prepared["predecessors"][-1]["blocked_findings"] == second_ledger["records"][4]["findings"]
    assert first_candidate.read_bytes() == b"failed candidate one"
    assert (second / "candidate/protocol.docx").read_bytes() == b"failed candidate two"
