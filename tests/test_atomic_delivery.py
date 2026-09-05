import hashlib
import json
from pathlib import Path

import pytest

import workflow
import quality
from quality import RESPONSE_SCHEMA, VISUAL_CHECKS, verification_request_sha256


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
    renderer = {"kind": "test-office", "path": "/test/office"}
    page_renderer = {"kind": "pypdfium2", "path": "python:pypdfium2"}
    (revision_dir / "candidate-build.json").write_text(json.dumps({
        "governing_resources": {},
        "candidate_files": candidate_files,
        "render_report": {
            "status": "passed",
            "renderer": renderer,
            "page_renderer": page_renderer,
            "artifacts": render_artifacts,
        },
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


def _passing_quality(revision_dir: Path, reference):
    build = json.loads((revision_dir / "candidate-build.json").read_text(encoding="utf-8"))
    requests = revision_dir / "hermes/verification-requests"
    responses = revision_dir / "hermes/verification-responses"
    requests.mkdir(parents=True, exist_ok=True)
    responses.mkdir(parents=True, exist_ok=True)
    content_id = "r-test.review-1.verify.content"
    content_request = {
        "schema_version": "hermes-verification/v1",
        "request_id": content_id,
        "task": "clinical_content_verification",
        "review_set": 1,
        "artifacts": list(build["candidate_files"]),
        "sections": quality._content_review_sections(reference),
        "checks": list(quality.CONTENT_CHECKS),
        "cross_document_checks": list(quality.CROSS_DOCUMENT_CHECKS),
        "response_path": f"hermes/verification-responses/{content_id}.json",
    }
    content_request["request_sha256"] = verification_request_sha256(content_request)
    (requests / "content.json").write_text(json.dumps(content_request), encoding="utf-8")
    (revision_dir / content_request["response_path"]).write_text(json.dumps({
        "schema_version": RESPONSE_SCHEMA,
        "request_id": content_id,
        "request_sha256": content_request["request_sha256"],
        "task": content_request["task"],
        "producer": {"model_id": "client-selected-test-model", "reviewer_id": "independent-content"},
        "status": "passed",
        "findings": [],
        "section_assessments": [{
            "artifact": item["artifact"],
            "section_id": item["section_id"],
            "status": "passed",
            "checks": list(quality.CONTENT_CHECKS),
        } for item in content_request["sections"]],
        "cross_document_assessments": [{
            "check": check,
            "status": "passed",
        } for check in content_request["cross_document_checks"]],
    }), encoding="utf-8")
    for artifact in build["render_report"]["artifacts"]:
        artifact_name = artifact["artifact"]
        request_id = f"r-test.review-1.verify.visual.{artifact_name}"
        renderer = {"kind": "test-office", "path": "/test/office"}
        page_renderer = {"kind": "pypdfium2", "path": "python:pypdfium2"}
        request = {
            "schema_version": "hermes-verification/v1",
            "request_id": request_id,
            "task": "rendered_page_visual_verification",
            "review_set": 1,
            "renderer": renderer,
            "page_renderer": page_renderer,
            "checks": list(VISUAL_CHECKS),
            "artifacts": [artifact],
            "response_path": f"hermes/verification-responses/{request_id}.json",
        }
        request["request_sha256"] = verification_request_sha256(request)
        (requests / f"visual-{artifact_name}.json").write_text(json.dumps(request), encoding="utf-8")
        (revision_dir / request["response_path"]).write_text(json.dumps({
            "schema_version": RESPONSE_SCHEMA,
            "request_id": request_id,
            "request_sha256": request["request_sha256"],
            "task": request["task"],
            "producer": {"model_id": "client-selected-test-model", "reviewer_id": f"independent-{artifact_name}"},
            "status": "passed",
            "findings": [],
            "page_assessments": [{
                "artifact": artifact_name,
                "page": page["page"],
                "sha256": page["sha256"],
                "status": "passed",
                "checks": list(VISUAL_CHECKS),
            } for page in artifact["pages"]],
        }), encoding="utf-8")
    verification_findings, evidence = quality.validate_verifications(revision_dir)
    assert verification_findings == []
    assert quality._final_verification_scope_findings(
        revision_dir, reference, build["render_report"], evidence
    ) == []
    candidate_hashes = {
        path.relative_to(revision_dir).as_posix(): workflow.quality_sha256(path)
        for path in sorted((revision_dir / "candidate").glob("*")) if path.is_file()
    }
    final_review = {
        "schema_version": "final-exact-artifact-review/v1",
        "scope": "complete_branch_document_set",
        "status": "passed",
        "branch_document_set": ["icf.docx", "protocol.docx", "study.xml"],
        "candidate_hashes": candidate_hashes,
        "rendered_hashes": quality._exact_rendered_hashes(revision_dir, build["render_report"]),
        "verification_evidence_sha256": workflow.canonical_evidence_sha256(evidence),
        "review_bindings": quality._final_review_bindings(evidence),
        "mandatory_visual_checks": list(VISUAL_CHECKS),
        "every_page": True,
        "section_three_and_orphan_heading_checks": True,
    }
    return {
        "status": "passed",
        "findings": [],
        "verification_evidence": evidence,
        "final_exact_artifact_review": final_review,
    }


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
    quality = _passing_quality(revision_dir, reference)
    page = revision_dir / "rendered/protocol/page-01.png"
    pdf = revision_dir / "rendered/protocol.pdf"
    original_copy = workflow.shutil.copy2

    def mutate_reviewed_page_after_copy(source, target):
        copied = original_copy(source, target)
        page.write_bytes(b"changed during staging")
        return copied

    monkeypatch.setattr(workflow.shutil, "copy2", mutate_reviewed_page_after_copy)

    with pytest.raises(RuntimeError, match="stale publication evidence"):
        workflow._publish(run_dir, revision_dir, reference, quality)

    assert (run_dir / "output/protocol.docx").read_bytes() == b"old protocol"


def test_publish_rechecks_reviewer_evidence_after_staging(tmp_path, monkeypatch):
    run_dir, revision_dir, reference = _publish_fixture(tmp_path)
    quality_report = _passing_quality(revision_dir, reference)
    response = next((revision_dir / "hermes/verification-responses").glob("*.json"))
    original_copy = workflow.shutil.copy2
    mutated = False

    def mutate_reviewer_response_after_copy(source, target):
        nonlocal mutated
        copied = original_copy(source, target)
        if not mutated:
            response.write_text(
                '{"status":"passed","producer":{"model_id":"changed","reviewer_id":"changed"}}',
                encoding="utf-8",
            )
            mutated = True
        return copied

    monkeypatch.setattr(workflow.shutil, "copy2", mutate_reviewer_response_after_copy)

    with pytest.raises(RuntimeError, match="stale publication evidence"):
        workflow._publish(run_dir, revision_dir, reference, quality_report)

    assert (run_dir / "output/protocol.docx").read_bytes() == b"old protocol"


def test_publish_failure_keeps_the_previous_package_intact(tmp_path, monkeypatch):
    run_dir, revision_dir, reference = _publish_fixture(tmp_path)
    quality = _passing_quality(revision_dir, reference)
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
        workflow._publish(run_dir, revision_dir, reference, quality)

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


def test_publish_rejects_missing_final_exact_artifact_review(tmp_path):
    run_dir, revision_dir, reference = _publish_fixture(tmp_path)

    with pytest.raises(RuntimeError, match="Final Exact-Artifact Review is required"):
        workflow._publish(run_dir, revision_dir, reference, {})

    assert (run_dir / "output/protocol.docx").read_bytes() == b"old protocol"


def test_publish_swaps_the_complete_package_and_removes_obsolete_outputs(tmp_path):
    run_dir, revision_dir, reference = _publish_fixture(tmp_path)

    result = workflow._publish(
        run_dir,
        revision_dir,
        reference,
        _passing_quality(revision_dir, reference),
    )

    assert result["status"] == "passed"
    assert sorted(path.name for path in (run_dir / "output").iterdir()) == ["icf.docx", "protocol.docx", "study.xml"]
    assert (run_dir / "output/protocol.docx").read_bytes() == b"new protocol"


def test_publish_rejects_changed_final_reviewer_response(tmp_path):
    run_dir, revision_dir, reference = _publish_fixture(tmp_path)
    quality = _passing_quality(revision_dir, reference)
    response = next((revision_dir / "hermes/verification-responses").glob("*.json"))
    response.write_text('{"status":"passed","producer":{"model_id":"changed"}}', encoding="utf-8")

    with pytest.raises(RuntimeError, match="final verification is incomplete"):
        workflow._publish(run_dir, revision_dir, reference, quality)

    assert (run_dir / "output/protocol.docx").read_bytes() == b"old protocol"


def test_failed_quality_attempt_evidence_is_archived_immutably(tmp_path):
    revision_dir = tmp_path / "revisions/r-traceable"
    reference_path = tmp_path / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    working_reference = {"generation": {}}
    reference_path.write_text(json.dumps(working_reference), encoding="utf-8")
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
    working_reference["generation"]["gate_attempts"] = json.loads(
        (revision_dir / "gate-attempt-journal.json").read_text(encoding="utf-8")
    )["entries"]
    workflow._finalize_recovery_attempt(
        revision_dir, first, reference_path, working_reference,
    )

    (revision_dir / "candidate/protocol.docx").write_bytes(b"failed candidate two")
    second = workflow._archive_failed_attempt(
        revision_dir,
        "quality",
        [{"category": "visual", "issue": "Second failed page"}],
    )
    working_reference["generation"]["gate_attempts"] = json.loads(
        (revision_dir / "gate-attempt-journal.json").read_text(encoding="utf-8")
    )["entries"]
    workflow._finalize_recovery_attempt(
        revision_dir, second, reference_path, working_reference,
    )

    assert second != first
    second_ledger = json.loads((second / "gate-ledger.json").read_text(encoding="utf-8"))
    assert second_ledger["predecessors"][-1]["ledger_sha256"] == first_ledger["ledger_sha256"]
    assert second_ledger["predecessors"][-1]["blocked_findings"] == first_ledger["records"][4]["findings"]
    expected_attempts = [
        {
            "path": path.relative_to(revision_dir).as_posix(),
            "attempt_manifest_sha256": workflow.sha256_file(path / "attempt-manifest.json"),
            "gate_ledger_sha256": json.loads((path / "gate-ledger.json").read_text(encoding="utf-8"))["ledger_sha256"],
            "strategy_ids": [
                action["strategy_id"]
                for action in json.loads(
                    (path / "attempt-manifest.json").read_text(encoding="utf-8")
                )["recovery_actions"]
            ],
        }
        for path in (first, second)
    ]
    prepared = workflow._prepared_gate_ledger(revision_dir, {}, {}, [], expected_attempts)
    assert [item["ledger_sha256"] for item in prepared["predecessors"]] == [
        first_ledger["ledger_sha256"],
        second_ledger["ledger_sha256"],
    ]
    assert prepared["predecessors"][-1]["blocked_findings"] == second_ledger["records"][4]["findings"]
    assert first_candidate.read_bytes() == b"failed candidate one"
    assert (second / "candidate/protocol.docx").read_bytes() == b"failed candidate two"
    workflow.shutil.rmtree(second)
    with pytest.raises(ValueError, match="inventory count"):
        workflow._prepared_gate_ledger(revision_dir, {}, {}, [], expected_attempts)
