"""A failed content review still leaves a labeled, complete review copy."""

import json
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

from docx import Document
import pytest

import drafting
import quality
import workflow


def _candidate_run(tmp_path: Path, monkeypatch, study_type: str = "Prospective") -> tuple[Path, Path]:
    monkeypatch.setattr(workflow, "contracted_template_bundle", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(workflow, "_approval_valid", lambda *_args, **_kwargs: (True, ""))
    run_dir = tmp_path / "run"
    reference_path = run_dir / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    reference_path.write_text(json.dumps({
        "approval": {"revision_id": "r-approved"},
        "meta": {"study_type": study_type},
    }), encoding="utf-8")
    candidate = run_dir / "revisions/r-approved/candidate"
    candidate.mkdir(parents=True)
    for name in workflow.document_set(study_type):
        if name.endswith(".xml"):
            ElementTree.ElementTree(ElementTree.Element("clinical_study")).write(
                candidate / name, encoding="utf-8", xml_declaration=True,
            )
            continue
        document = Document()
        document.add_paragraph(name)
        document.save(candidate / name)
    records = [
        {"path": f"candidate/{path.name}", "sha256": workflow.sha256_file(path)}
        for path in sorted(candidate.iterdir())
    ]
    (candidate.parent / "candidate-build.json").write_text(
        json.dumps({"candidate_files": records}), encoding="utf-8",
    )
    (candidate.parent / "candidate-structure.json").write_text(
        json.dumps({"candidate_files": records}), encoding="utf-8",
    )
    return run_dir, candidate


@pytest.mark.parametrize("study_type", ["Prospective", "Ambispective", "Retrospective"])
def test_content_block_exports_complete_review_only_documents_and_findings(tmp_path, monkeypatch, study_type):
    run_dir, candidate = _candidate_run(tmp_path, monkeypatch, study_type)
    result = workflow._review_copy(run_dir, {
        "status": "blocked", "stage": "quality",
        "findings": [{"issue": "Required consent language is absent."}],
    })

    assert len(result["review_outputs"]) == len(workflow.document_set(study_type))
    assert all(item["delivery_status"] == "review_only_not_client_ready" for item in result["review_outputs"])
    assert not (run_dir / "output").exists()
    report = json.loads((run_dir / result["review_findings"]).read_text())
    assert report["findings"] == [{
        "issue": "Required consent language is absent.",
        "document_locations": ["Document location not specified by the check"],
    }]
    readme = (run_dir / "review-output/READ-ME-FIRST.txt").read_text()
    assert "Required consent language is absent." in readme
    assert "automated check" in readme.casefold()
    assert "review" in readme.casefold()
    for item in result["review_outputs"]:
        source = candidate / Path(item["path"]).name.removeprefix("REVIEW-ONLY-")
        assert workflow.sha256_file(run_dir / item["path"]) == workflow.sha256_file(source)


def test_review_copy_names_exact_protocol_icf_and_xml_locations(tmp_path, monkeypatch):
    run_dir, _candidate = _candidate_run(tmp_path, monkeypatch)
    result = workflow._review_copy(run_dir, {
        "status": "blocked", "stage": "quality",
        "findings": [
            {"target_ids": ["quality-safety.reporting"], "issue": "A safety detail needs review."},
            {"target_ids": ["icf.risks"], "issue": "A risk statement needs review."},
            {"target_ids": ["prs.eligibility"], "issue": "An XML criterion needs review."},
        ],
    })
    report = json.loads((run_dir / result["review_findings"]).read_text())
    locations = [item["document_locations"] for item in report["findings"]]
    assert locations == [
        ["Protocol §13.3 — Procedures for Recording and Reporting AEs and SAEs"],
        ["ICF — Risks and discomforts"],
        ["PRS XML — prs.eligibility"],
    ]
    readme = (run_dir / "review-output/READ-ME-FIRST.txt").read_text()
    for location in locations:
        assert location[0] in readme

    retrospective = workflow._review_finding_locations(
        {"meta": {"study_type": "Retrospective"}},
        {"target_ids": ["study-procedure.enrollment"]},
    )
    assert retrospective == ["Protocol §8.1 — Informed Consent / Subject Enrollment"]
    assert workflow._review_finding_locations(
        {"meta": {"study_type": "Prospective"}},
        {"field": "quality-safety.reporting"},
    ) == ["Protocol §13.3 — Procedures for Recording and Reporting AEs and SAEs"]


def test_tampered_candidate_cannot_be_exported_for_review(tmp_path, monkeypatch):
    run_dir, candidate = _candidate_run(tmp_path, monkeypatch)
    (candidate / "icf.docx").write_bytes(b"changed after build")

    assert workflow._review_copy(run_dir, {
        "status": "blocked", "stage": "quality", "findings": [],
    }) == {}
    assert not (run_dir / "review-output").exists()


def test_complete_render_failed_candidate_is_available_as_review_copy(tmp_path, monkeypatch):
    run_dir, _candidate = _candidate_run(tmp_path, monkeypatch)
    (run_dir / "revisions/r-approved/candidate-build.json").unlink()

    result = workflow._review_copy(run_dir, {
        "status": "blocked", "stage": "render_assurance",
        "findings": [{"issue": "The rendered layout needs review."}],
    })

    assert len(result["review_outputs"]) == 3
    report = json.loads((run_dir / result["review_findings"]).read_text())
    assert report["candidate_evidence"] == "candidate-structure.json"


def test_desktop_operation_finishes_with_review_required_and_keeps_client_output_empty(
    tmp_path, monkeypatch,
):
    run_dir, _candidate = _candidate_run(tmp_path, monkeypatch)
    monkeypatch.setattr(workflow, "generate", lambda _run_dir, **_kwargs: {
        "status": "blocked", "stage": "quality",
        "findings": [{"issue": "Required consent language is absent."}],
        "client_outputs": [],
    })

    result = workflow.run_desktop_operation(
        run_dir, handoff_runner=lambda _handoffs, _remaining: None,
        opener=lambda _path: b"unused", budget_seconds=30.0,
        runtime_identity={"executable": "/test/python", "implementation": "CPython", "version": "3.13.0"},
        release_identity={"package_fingerprint": "test-release"},
    )

    assert result["status"] == "review_required"
    assert result["client_outputs"] == []
    assert len(result["review_outputs"]) == 3
    archive_path = run_dir / result["diagnostic_archive"]["path"]
    assert archive_path == run_dir / "output/BLOCKED-RUN-DIAGNOSTICS.zip"
    with ZipFile(archive_path) as bundle:
        assert bundle.testzip() is None
        assert "review-output/findings.json" in bundle.namelist()
        assert "logs/desktop-operation.json" in bundle.namelist()
    resumed = workflow.run_desktop_operation(
        run_dir, handoff_runner=lambda _handoffs, _remaining: None,
        opener=lambda _path: b"unused", budget_seconds=30.0,
        runtime_identity={"executable": "/test/python", "implementation": "CPython", "version": "3.13.0"},
        release_identity={"package_fingerprint": "test-release"},
    )
    assert resumed["status"] == "review_required"


def test_warning_only_drafting_response_is_accepted_and_reported(tmp_path, monkeypatch):
    request = {
        "schema_version": drafting.REQUEST_SCHEMA,
        "prompt_version": drafting.PROMPT_VERSION,
        "request_id": "warning-request",
        "batch_id": "icf-narrative",
        "response_path": "hermes/responses/warning-request.json",
        "section_contracts": [{"section_id": "icf.background"}],
    }
    request_path = tmp_path / "hermes/requests/warning-request.json"
    request_path.parent.mkdir(parents=True)
    request_path.write_text(json.dumps(request), encoding="utf-8")
    response_path = tmp_path / request["response_path"]
    response_path.parent.mkdir(parents=True)
    response_path.write_text("{}", encoding="utf-8")
    warning = {
        "category": "drafting", "field": "icf.background",
        "code": "icf-lexical-evidence-uncertainty",
        "publication_disposition": "warning",
        "issue": "The cited fact needs contextual review.",
    }
    accepted = {"kind": "sections", "drafts": [{
        "section_id": "icf.background", "request_id": "warning-request",
        "warnings": [warning], "paragraphs": [], "lists": [],
    }]}
    monkeypatch.setattr(drafting, "_trusted_request_valid", lambda *_args: True)
    monkeypatch.setattr(drafting, "validate_response", lambda *_args: (accepted, [warning]))

    assert drafting.ingest_responses(tmp_path) == []
    assert (tmp_path / "hermes/accepted/icf.background.json").is_file()
    assert not (tmp_path / "hermes/rejected/warning-request.json").exists()
    assert quality._accepted_drafting_warnings(tmp_path) == [warning]


def test_final_quality_keeps_drafting_and_render_warnings_without_blocking(tmp_path, monkeypatch):
    accepted = tmp_path / "hermes/accepted/icf.background.json"
    accepted.parent.mkdir(parents=True)
    drafting_warning = {
        "code": "icf-lexical-evidence-uncertainty",
        "publication_disposition": "warning",
        "issue": "Check the source paraphrase in context.",
    }
    render_warning = {
        "code": "visible-duplicate-word",
        "publication_disposition": "warning",
        "issue": "Visible text repeats a word.",
    }
    accepted.write_text(json.dumps({"warnings": [drafting_warning]}), encoding="utf-8")
    monkeypatch.setattr(quality, "deterministic_content_check", lambda *_args: [])
    monkeypatch.setattr(quality, "validate_verifications", lambda *_args: ([], {}))
    monkeypatch.setattr(quality, "_final_verification_scope_findings", lambda *_args: [])
    reference = {"meta": {"study_type": "Retrospective"}}
    render = {"artifacts": [{"warnings": [render_warning]}]}

    report = quality.quality_report(tmp_path, reference, render, None)

    assert report["status"] == "passed"
    assert report["warnings"] == [drafting_warning, render_warning]
    assert quality.final_exact_artifact_review_findings(tmp_path, reference, render, report) == []
