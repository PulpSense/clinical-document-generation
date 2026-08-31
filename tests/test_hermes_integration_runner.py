from __future__ import annotations

import hashlib
import inspect
import json
import shlex
from datetime import datetime, timedelta
from pathlib import Path
import subprocess
import sys
import tempfile

import pytest

from hermes_e2e import (
    CERTIFICATION_CORPUS,
    CERTIFICATION_LAYOUT_COVERAGE,
    CERTIFICATION_VISUAL_CHECKS,
    DETERMINISTIC_BRANCH_ACCEPTANCE_CASES,
    EXPECTED_OUTPUTS,
    DiagnosticOutcome,
    _agent_prompt,
    _canonical_reviewed_fixture_reference,
    _certified_release,
    _reduce_release_certification_corpus,
    _response_is_bound,
    _run_handoff_wave,
    _wait_for_processes,
    certification_fixture,
    certification_corpus,
    certify_release_corpus,

    _workflow,
    input_provenance,
    inspect_run,
    prepare_certification_run,
    run_release_certification_corpus,
    subprocess_environment,
    sandbox_command,
    wait_for_parent_visual_review,
)
import workflow
import drafting
import hermes_e2e
import quality


ROOT = Path(__file__).resolve().parents[1]


def _certify_fixture_corpus(case_report_paths, **kwargs):
    """Supply controller-captured report bytes only inside reducer unit tests."""
    return _reduce_release_certification_corpus(
        case_report_paths,
        controller_report_sha256={
            str(Path(path).resolve()): hashlib.sha256(Path(path).resolve().read_bytes()).hexdigest()
            for path in case_report_paths
        },
        **kwargs,
    )


def test_command_desktop_opener_emits_exact_bytes_and_rejects_aliases(tmp_path: Path) -> None:
    attachment = tmp_path / "attachment.docx"
    attachment.write_bytes(b"exact desktop bytes")
    command = tmp_path / "desktop-opener"
    command.write_text("#!/bin/sh\nexec /bin/cat -- \"$1\"\n", encoding="utf-8")
    command.chmod(0o700)

    opener = workflow.command_desktop_opener(command)

    assert opener(str(attachment)) == b"exact desktop bytes"
    alias = tmp_path / "aliased-opener"
    alias.symlink_to(command)
    with pytest.raises(ValueError, match="non-symlinked"):
        workflow.command_desktop_opener(alias)
    with pytest.raises(ValueError, match="absolute"):
        workflow.command_desktop_opener(Path("relative-opener"))
    command.chmod(0o600)
    with pytest.raises(ValueError, match="not executable"):
        workflow.command_desktop_opener(command)


def _write_complete_visual_verification(revision_dir: Path) -> tuple[dict, Path, Path, Path]:
    request_path = revision_dir / "hermes/verification-requests/visual.json"
    response_path = revision_dir / "hermes/verification-responses/visual.json"
    docx_path = revision_dir / "candidate/protocol.docx"
    pdf_path = revision_dir / "rendered/protocol.pdf"
    page_path = revision_dir / "rendered/protocol/page-1.png"
    for path, payload in (
        (docx_path, b"bound docx bytes"),
        (pdf_path, b"bound pdf bytes"),
        (page_path, b"bound page bytes"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    request = {
        "schema_version": "hermes-verification/v1",
        "request_id": "visual",
        "task": "rendered_page_visual_verification",
        "response_path": response_path.relative_to(revision_dir).as_posix(),
        "checks": list(quality.VISUAL_CHECKS),
        "artifacts": [{
            "artifact": "protocol",
            "docx": docx_path.relative_to(revision_dir).as_posix(),
            "docx_sha256": quality.sha256_file(docx_path),
            "pdf": pdf_path.relative_to(revision_dir).as_posix(),
            "pdf_sha256": quality.sha256_file(pdf_path),
            "pages": [{
                "path": page_path.relative_to(revision_dir).as_posix(),
                "page": 1,
                "sha256": quality.sha256_file(page_path),
            }],
        }],
    }
    request["request_sha256"] = quality.verification_request_sha256(request)
    request_path.parent.mkdir(parents=True, exist_ok=True)
    request_path.write_text(json.dumps(request), encoding="utf-8")
    response_path.parent.mkdir(parents=True, exist_ok=True)
    response_path.write_text(json.dumps({
        "schema_version": quality.RESPONSE_SCHEMA,
        "request_id": request["request_id"],
        "request_sha256": request["request_sha256"],
        "task": request["task"],
        "status": "passed",
        "findings": [],
        "producer": {"model_id": "gpt-5.6-sol"},
        "page_assessments": [{
            "artifact": "protocol",
            "page": 1,
            "sha256": quality.sha256_file(page_path),
            "status": "passed",
            "checks": list(quality.VISUAL_CHECKS),
        }],
    }), encoding="utf-8")
    handoff = {
        "request_path": request_path.relative_to(revision_dir).as_posix(),
        "response_path": response_path.relative_to(revision_dir).as_posix(),
    }
    return handoff, request_path, response_path, page_path


def test_ticket_43_attempt_ledger_retains_rejected_candidates_without_local_paths() -> None:
    path = ROOT / "tests/fixtures/release-certification/evidence/ticket-43-attempts.json"
    ledger = json.loads(path.read_text(encoding="utf-8"))

    assert ledger["ticket"] == 43
    assert [attempt["outcome"] for attempt in ledger["attempts"]] == [
        "failed_preflight",
        "failed_first_real_case",
        "failed_second_real_case",
        "failed_third_real_case",
        "failed_second_real_case_slow",
        "failed_first_real_case_invalid_hermes_response",
        "failed_third_real_case_slow",
        "failed_first_real_case_at_correctness_ceiling",
        "passed_complete_three_case_corpus",
    ]
    assert all(attempt["candidate_package_fingerprint"] for attempt in ledger["attempts"])
    retrospective_attempt = next(
        attempt for attempt in ledger["attempts"]
        if attempt["id"] == "retrospective-objectives-and-canonical-reference-identity"
    )
    assert retrospective_attempt["failed_case"]["final_content_response_sha256"] == (
        "f1a3207d7a7cd770e3689ce12152d8d5c96de4d491c14399dcb38bcfe3dafe28"
    )
    certified_attempt = ledger["attempts"][-1]
    assert certified_attempt["classification"] == "certified_candidate"
    assert certified_attempt["corpus_status"] == "passed"
    assert certified_attempt["candidate_git_commit"] == (
        "10231c52bc25edae27e498bd180cc7309f33dfa8"
    )
    assert certified_attempt["candidate_package_fingerprint"] == (
        "f5792fb8c5761d2119e43505fba14e613e61ef573c55350586271527eed78420"
    )
    assert certified_attempt["preflight_evidence_sha256"] == (
        "a12fa6d74ce44ee0f38a3fccf280b844e1b0045e4b956dd75a0fe49b139544fd"
    )
    assert certified_attempt["corpus_report_sha256"] == (
        "40e3c94915bea3700c168c7e3db706341af0d25cac982784eef7bce5d25cdc63"
    )
    cases = certified_attempt["cases"]
    assert tuple(case["fixture_id"] for case in cases) == (
        "ambispective-sterling", "prospective-advarra", "retrospective",
    )
    assert all(case["operation_outcome"] == "passed" for case in cases)
    assert all(case["under_15_minutes"] is True for case in cases)
    assert all(
        0 < case["approval_to_confirmed_retrieval_elapsed_seconds"] < 900
        for case in cases
    )
    assert all(
        len(case[hash_key]) == 64
        for case in cases
        for hash_key in ("case_report_sha256", "desktop_operation_state_sha256")
    )
    assert certified_attempt["all_required_gates"] == "passed"
    assert set(certified_attempt["layout_preservation"].values()) == {"passed"}
    assert certified_attempt["delivery_confirmation"] == "passed"
    assert "/tmp/" not in path.read_text(encoding="utf-8")


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
            "skill": "clinical-document-generation",
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


def test_repository_certification_corpus_covers_every_live_release_branch() -> None:
    fixtures = certification_corpus()

    assert tuple(fixture["fixture_id"] for fixture in fixtures) == CERTIFICATION_CORPUS
    assert {
        (fixture["study_type"], fixture.get("icf_family"))
        for fixture in fixtures
    } == {
        ("Ambispective", "Sterling"),
        ("Prospective", "Advarra"),
        ("Retrospective", None),
    }
    assert all(fixture["synthetic"] is True for fixture in fixtures)
    assert all(fixture["contains_private_data"] is False for fixture in fixtures)
    assert all(fixture["review_status"] == "approved for release certification" for fixture in fixtures)
    assert all(fixture["privacy_statement"] for fixture in fixtures)
    assert {
        fixture["fixture_id"]: fixture["expected_outputs"]
        for fixture in fixtures
    } == {
        "ambispective-sterling": ["icf.docx", "protocol.docx", "study.xml"],
        "prospective-advarra": ["icf.docx", "protocol.docx", "study.xml"],
        "retrospective": ["protocol.docx"],
    }
    governed = {
        json.dumps(
            {
                key: fixture["hermes_configuration"][key]
                for key in (
                    "source", "max_turns", "skill", "safe_mode",
                    "reasoning_configuration",
                )
            },
            sort_keys=True,
        )
        for fixture in fixtures
    }
    assert len(governed) == 1


def _write_corpus_preflight(tmp_path: Path) -> Path:
    logs = tmp_path / "preflight-logs"
    logs.mkdir()
    checks = {}
    command_arguments = {
        "static_release_checks": [
            "-m", "py_compile", *(f"scripts/{name}.py" for name in ("workflow", "contracts", "drafting", "rendering", "quality", "prs_xml")), "tests/hermes_e2e.py",
        ],
        "layout_preservation_corpus": [
            "-m", "pytest",
            "tests/test_runtime_regressions.py::test_parallel_bundle_identity_preserves_candidate_bytes_and_visible_formatting",
            "tests/test_client_output_acceptance.py::test_every_protocol_and_icf_family_uses_natural_body_pagination",
            "-q",
        ],
        "deterministic_branch_acceptance_corpus": [
            "-m", "pytest", "tests/test_release_gate.py::test_all_six_public_lifecycle_cases_pass_and_publish_exact_sets", "-q",
        ],
        "repository_regression_suite": ["-m", "pytest", "-q"],
    }
    for index, (name, arguments) in enumerate(command_arguments.items()):
        path = logs / f"{name}.log"
        path.write_text(f"{name}: passed\n", encoding="utf-8")
        checks[name] = {
            "status": "passed",
            "command": [sys.executable, *arguments],
            "returncode": 0,
            "started_at": f"2026-08-27T23:{56 + index:02d}:00+00:00",
            "completed_at": (
                "2026-08-28T00:00:00+00:00"
                if index == 3
                else f"2026-08-27T23:{57 + index:02d}:00+00:00"
            ),
            "log_path": path.relative_to(tmp_path).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    checks["layout_preservation_corpus"]["coverage"] = list(CERTIFICATION_LAYOUT_COVERAGE)
    checks["deterministic_branch_acceptance_corpus"].update({
        "assurance": "recorded-drafting-structural-only",
        "case_ids": list(DETERMINISTIC_BRANCH_ACCEPTANCE_CASES),
    })
    checks["repository_regression_suite"]["test_count"] = 313
    path = tmp_path / "preflight.json"
    path.write_text(json.dumps({
        "schema_version": "release-certification-preflight/v1",
        "status": "passed",
        "completed_at": "2026-08-28T00:00:00+00:00",
        "candidate": {
            "package_fingerprint": "candidate-fingerprint",
            "git_commit": "a" * 40,
        },
        "snapshot": {
            "git_commit": "a" * 40,
            "git_tree": "b" * 40,
            "detached": True,
            "package_reconstructions": [
                {
                    "phase": phase,
                    "package_fingerprint": "candidate-fingerprint",
                    "git_commit": "a" * 40,
                    "archive_sha256": "c" * 64,
                }
                for phase in ("before", "after")
            ],
        },
        "python_runtime": {
            "version": sys.version,
            "implementation": sys.implementation.name,
            "executable_sha256": hashlib.sha256(Path(sys.executable).resolve().read_bytes()).hexdigest(),
        },
        "repository_clean": True,
        "producer": {
            "path": "tests/hermes_e2e.py",
            "sha256": hashlib.sha256((ROOT / "tests/hermes_e2e.py").read_bytes()).hexdigest(),
            "git_commit": "a" * 40,
        },
        "checks": checks,
    }), encoding="utf-8")
    return path


def _write_passing_case_report(
    tmp_path: Path,
    fixture_id: str,
    *,
    elapsed_seconds: float = 600.0,
    producer_model_id: str = "gpt-5.6-sol",
) -> Path:
    fixture = certification_fixture(fixture_id)
    run_dir = tmp_path / fixture_id
    logs = run_dir / "logs"
    logs.mkdir(parents=True)
    revision = run_dir / "revisions/r-test"
    manifest_path = revision / "delivery-manifest.json"
    output_dir = run_dir / "output"
    output_dir.mkdir()
    (run_dir / "input").mkdir()
    (run_dir / "reference").mkdir()
    (run_dir / "input/source-input.md").write_bytes(fixture["artifact_paths"]["source_input"].read_bytes())
    (run_dir / "reference/source-of-truth.md").write_bytes(fixture["artifact_paths"]["approved_source"].read_bytes())
    approved_reference = _canonical_reviewed_fixture_reference(fixture, workflow)
    bundle = {
        "identity_sha256": "c" * 64,
        "layout_preservation_baseline": {"sha256": "d" * 64},
    }
    approved_reference["approval"] = {
        "status": "approved",
        "approved_by": "Hermes Release Certification",
        "approved_at": "2026-08-28T00:00:00+00:00",
        "revision_id": "r-test",
        "source_sha256": hashlib.sha256((run_dir / "reference/source-of-truth.md").read_bytes()).hexdigest(),
    }
    approved_reference["approval"]["governing_sha256"] = drafting.sha256_value(
        drafting.governing_resources(ROOT, approved_reference, contracted_bundle=bundle)
    )
    run_reference = run_dir / "reference/study.reference.json"
    run_reference.write_text(json.dumps(approved_reference), encoding="utf-8")
    (revision / "approved-source.md").parent.mkdir(parents=True, exist_ok=True)
    (revision / "approved-source.md").write_bytes((run_dir / "reference/source-of-truth.md").read_bytes())
    (revision / "approved-reference.json").write_bytes(run_reference.read_bytes())
    approved_reference["approval"]["approved_reference_sha256"] = hashlib.sha256(
        (revision / "approved-reference.json").read_bytes()
    ).hexdigest()
    run_reference.write_text(json.dumps(approved_reference), encoding="utf-8")
    accepted_dir = revision / "hermes/accepted"
    accepted_requests_dir = revision / "hermes/accepted-requests"
    accepted_dir.mkdir(parents=True)
    accepted_requests_dir.mkdir(parents=True)
    drafting_request = accepted_requests_dir / "draft-1.json"
    drafting_request.write_text(json.dumps({
        "request_id": "draft-1",
        "request_sha256": "3" * 64,
        "task": "section_drafting",
    }), encoding="utf-8")
    accepted_draft = accepted_dir / "protocol.synopsis.json"
    accepted_draft.write_text(json.dumps({
        "section_id": "protocol.synopsis",
        "request_id": "draft-1",
        "request_sha256": "3" * 64,
        "producer": {"model_id": producer_model_id},
    }), encoding="utf-8")
    drafting_evidence = [{
        "path": accepted_draft.relative_to(revision).as_posix(),
        "sha256": hashlib.sha256(accepted_draft.read_bytes()).hexdigest(),
        "request_id": "draft-1",
        "request_sha256": "3" * 64,
        "accepted_request_path": drafting_request.relative_to(revision).as_posix(),
        "accepted_request_file_sha256": hashlib.sha256(drafting_request.read_bytes()).hexdigest(),
        "producer": {"model_id": producer_model_id},
    }]
    manifest_outputs = []
    for name in fixture["expected_outputs"]:
        output = output_dir / name
        output.write_bytes(f"delivered {fixture_id} {name}\n".encode())
        manifest_outputs.append({
            "path": f"output/{name}",
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "bytes": output.stat().st_size,
        })
    outputs = [{**item, "confirmed": True} for item in manifest_outputs]
    verification = {}
    content_request = revision / "hermes/verification-requests/content.json"
    content_response = revision / "hermes/verification-responses/content.json"
    content_response.parent.mkdir(parents=True)
    content_request.parent.mkdir(parents=True)
    content_request.write_text(json.dumps({
        "request_id": "content",
        "request_sha256": "1" * 64,
        "task": "clinical_content_verification",
    }), encoding="utf-8")
    content_response.write_text(json.dumps({
        "request_id": "content",
        "request_sha256": "1" * 64,
        "task": "clinical_content_verification",
        "status": "passed",
        "producer": {"model_id": producer_model_id},
        "section_assessments": [{"artifact": "protocol", "section_id": "protocol.title-page", "status": "passed"}],
        "cross_document_assessments": [{"check": "study_title", "status": "passed"}],
    }), encoding="utf-8")
    verification["clinical_content_verification"] = {
        "request": content_request.relative_to(revision).as_posix(),
        "request_sha256": hashlib.sha256(content_request.read_bytes()).hexdigest(),
        "response": content_response.relative_to(revision).as_posix(),
        "response_sha256": hashlib.sha256(content_response.read_bytes()).hexdigest(),
    }
    render_artifacts = []
    docx_artifacts = {}
    active_renderer = {"kind": "LibreOffice", "path": "/controlled/soffice"}
    active_page_renderer = {"kind": "pypdfium2", "path": "python:pypdfium2"}
    fonts = {"Arial": {"state": "available", "match": "controlled font inventory"}}
    for output in manifest_outputs:
        if not output["path"].endswith(".docx"):
            continue
        artifact = Path(output["path"]).stem
        candidate = revision / f"candidate/{artifact}.docx"
        pdf = revision / f"rendered/{artifact}.pdf"
        page = revision / f"rendered/{artifact}/page-1.png"
        page.parent.mkdir(parents=True)
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_bytes((run_dir / output["path"]).read_bytes())
        pdf.write_bytes(f"pdf {artifact}\n".encode())
        page.write_bytes(f"page {artifact}\n".encode())
        pages = [{
            "page": 1,
            "path": page.relative_to(revision).as_posix(),
            "sha256": hashlib.sha256(page.read_bytes()).hexdigest(),
        }]
        render_artifact = {
            "artifact": artifact,
            "renderer": active_renderer,
            "page_renderer": active_page_renderer,
            "font_evidence": fonts,
            "font_substitutions": {},
            "docx": candidate.relative_to(revision).as_posix(),
            "docx_sha256": output["sha256"],
            "pdf": pdf.relative_to(revision).as_posix(),
            "pdf_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
            "pages": pages,
        }
        render_artifacts.append(render_artifact)
        visual_request = revision / f"hermes/verification-requests/visual-{artifact}.json"
        visual_response = revision / f"hermes/verification-responses/visual-{artifact}.json"
        visual_request.write_text(json.dumps({
            "request_id": f"visual-{artifact}",
            "request_sha256": "2" * 64,
            "task": "rendered_page_visual_verification",
            "artifacts": [{
                key: value
                for key, value in render_artifact.items()
                if key not in {"renderer", "page_renderer"}
            }],
        }), encoding="utf-8")
        visual_response.write_text(json.dumps({
            "request_id": f"visual-{artifact}",
            "request_sha256": "2" * 64,
            "task": "rendered_page_visual_verification",
            "status": "passed",
            "producer": {"model_id": producer_model_id},
            "page_assessments": [{
                "artifact": artifact,
                "page": 1,
                "sha256": pages[0]["sha256"],
                "status": "passed",
                "checks": sorted(CERTIFICATION_VISUAL_CHECKS),
            }],
        }), encoding="utf-8")
        verification[f"visual-{artifact}"] = {
            "request": visual_request.relative_to(revision).as_posix(),
            "request_sha256": hashlib.sha256(visual_request.read_bytes()).hexdigest(),
            "response": visual_response.relative_to(revision).as_posix(),
            "response_sha256": hashlib.sha256(visual_response.read_bytes()).hexdigest(),
            "producer": {"model_id": producer_model_id},
            "artifacts": [render_artifact],
        }
        docx_artifacts[artifact] = {
            "status": "passed",
            "request_sha256": hashlib.sha256(visual_request.read_bytes()).hexdigest(),
            "response_sha256": hashlib.sha256(visual_response.read_bytes()).hexdigest(),
            "producer_model_id": producer_model_id,
            "docx_sha256": render_artifact["docx_sha256"],
            "pdf_sha256": render_artifact["pdf_sha256"],
            "page_count": 1,
            "page_sha256": [pages[0]["sha256"]],
            "checks": sorted(CERTIFICATION_VISUAL_CHECKS),
        }
    manifest = {
        "status": "passed",
        "revision_id": "r-test",
        "study_type": fixture["study_type"],
        "approved_source_sha256": hashlib.sha256((revision / "approved-source.md").read_bytes()).hexdigest(),
        "approved_reference_sha256": hashlib.sha256((revision / "approved-reference.json").read_bytes()).hexdigest(),
        "client_outputs": manifest_outputs,
        "contracted_template_bundle": bundle,
        "drafting_evidence": drafting_evidence,
        "quality": {
            "status": "passed",
            "render_assurance": {
                "fonts": fonts,
                "font_substitutions": {},
                "structural_validation": {"status": "structurally_valid"},
                "render": {
                    "status": "passed",
                    "renderer": active_renderer,
                    "page_renderer": active_page_renderer,
                    "renderer_attempts": [{"adapter": active_renderer, "status": "passed"}],
                    "page_renderer_attempts": [{"adapter": active_page_renderer, "status": "passed"}],
                    "artifacts": render_artifacts,
                },
            },
            "verification_evidence": verification,
        },
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    identity = {
        "package_fingerprint": "candidate-fingerprint",
        "git_commit": "a" * 40,
        "hermes_configuration": fixture["hermes_configuration"],
        "managed_hermes_identity": {
            "launcher": "/managed/hermes/venv/bin/hermes",
            "launcher_sha256": "1" * 64,
            "interpreter": "/managed/hermes/venv/bin/python",
            "interpreter_target": "/managed/python/bin/python3.11",
            "interpreter_target_sha256": "2" * 64,
        },
    }
    state = logs / "desktop-operation.json"
    state.write_text(json.dumps({
        "status": "passed",
        "started_at": "2026-08-28T00:01:00+00:00",
        "deadline_at": "2026-08-28T00:31:00+00:00",
        "budget_seconds": 1800.0,
        "release_identity": identity,
        "approval_identity": {
            key: approved_reference["approval"].get(key)
            for key in (
                "status", "approved_by", "approved_at", "revision_id", "source_sha256",
                "approved_reference_sha256", "governing_sha256",
            )
        },
        "cleanup": {"owned_processes_reaped": True},
        "result": {
            "status": "passed",
            "elapsed_seconds": elapsed_seconds,
            "manifest": manifest_path.relative_to(run_dir).as_posix(),
            "delivery": {
                "confirmed": True,
                "opened": [
                    {
                        "filename": Path(item["path"]).name,
                        "sha256": item["sha256"],
                        "bytes": item["bytes"],
                    }
                    for item in manifest_outputs
                ],
            },
        },
    }), encoding="utf-8")
    report = {
        "outcome": "passed",
        "certification_scope": "production_single_case_tracer",
        "elapsed_seconds": elapsed_seconds,
        "release_identity": identity,
        "hermes_configuration": fixture["hermes_configuration"],
        "input_provenance": {
            "fixture_id": fixture_id,
            "synthetic": True,
            "contains_private_data": False,
            "fixture_manifest_sha256": hashlib.sha256(
                (fixture["artifact_paths"]["source_input"].parent / "fixture.json").read_bytes()
            ).hexdigest(),
        },
        "model_identifiers": [producer_model_id],
        "missing_response_paths": [],
        "invalid_response_paths": [],
        "recorded_response_paths": [],
        "invalid_rejection_paths": [],
        "required_outputs": fixture["expected_outputs"],
        "output_evidence": outputs,
        "desktop_operation_evidence": {
            "started_at": "2026-08-28T00:01:00+00:00",
            "deadline_at": "2026-08-28T00:31:00+00:00",
        },
        "approval_to_confirmed_retrieval_evidence": {
            "status": "approved",
            "approved_by": "Hermes Release Certification",
            "approved_at": "2026-08-28T00:00:00+00:00",
            "revision_id": "r-test",
            "source_sha256": hashlib.sha256((revision / "approved-source.md").read_bytes()).hexdigest(),
            "approved_reference_sha256": approved_reference["approval"]["approved_reference_sha256"],
            "governing_sha256": approved_reference["approval"]["governing_sha256"],
            "confirmed_retrieval_at": (
                datetime.fromisoformat("2026-08-28T00:01:00+00:00")
                + timedelta(seconds=elapsed_seconds)
            ).isoformat(),
            "elapsed_seconds": round(60.0 + elapsed_seconds, 3),
        },
        "bound_evidence": {
            "desktop_operation_state": {
                "path": "logs/desktop-operation.json",
                "sha256": hashlib.sha256(state.read_bytes()).hexdigest(),
                "bytes": state.stat().st_size,
            },
            "delivery_manifest": {
                "path": "revisions/r-test/delivery-manifest.json",
                "sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                "bytes": manifest_path.stat().st_size,
            },
        },
        "certification_case_evidence": {
            "fixture_id": fixture_id,
            "gate_statuses": {
                "source": "passed",
                "content": "passed",
                "document_structure": "passed",
                "prs_xml": "not_applicable" if fixture_id == "retrospective" else "passed",
                "package": "passed",
                "cross_document_consistency": "passed",
                "render_assurance": "passed",
                "every_page_visual_qa": "passed",
                "delivery_confirmation": "passed",
            },
            "layout_checks": {
                "natural_section_3_flow": "passed",
                "no_orphan_headings": "passed",
            },
            "visual_qa": docx_artifacts,
            "contracted_template_bundle_identity": "c" * 64,
            "layout_preservation_baseline_identity": "d" * 64,
        },
    }
    path = logs / "hermes-integration-report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def _use_controlled_certified_release(monkeypatch) -> Path:
    release_root = Path(tempfile.mkdtemp(prefix="controlled-certified-release-"))
    (release_root / "scripts").mkdir()
    manifest = {
        "package_fingerprint": "candidate-fingerprint",
        "git_commit": "a" * 40,
        "files": [
            {
                "path": f"scripts/{name}.py",
                "sha256": hashlib.sha256((ROOT / f"scripts/{name}.py").read_bytes()).hexdigest(),
            }
            for name in ("workflow", "contracts", "drafting", "rendering", "quality", "prs_xml")
        ],
        "inventory": {"pdf_page_renderer": workflow.PDF_PAGE_RENDERER},
    }
    (release_root / "RELEASE-MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")

    class ControlledWorkflow:
        SCRIPT_DIR = release_root / "scripts"
        parse_source_truth = staticmethod(workflow.parse_source_truth)

        @staticmethod
        def verification_response_is_complete(_revision_dir, _request_path):
            return True

        @staticmethod
        def missing_drafts(_revision_dir, _reference, _repo_root, *, contracted_bundle):
            governing = drafting.governing_resources(
                ROOT,
                _reference,
                contracted_bundle=contracted_bundle,
            )
            return [] if governing["approved_source_sha256"] else ["approval.source_sha256"]

        _approval_valid = staticmethod(workflow._approval_valid)

    monkeypatch.setattr(
        "hermes_e2e._certified_release",
        lambda _release_root: (
            ControlledWorkflow,
            {"package_fingerprint": "candidate-fingerprint", "git_commit": "a" * 40},
        ),
    )
    return release_root


def test_complete_real_corpus_report_binds_preflight_candidate_cases_and_gates(tmp_path: Path, monkeypatch) -> None:
    release_root = _use_controlled_certified_release(monkeypatch)
    preflight = _write_corpus_preflight(tmp_path)
    reports = [
        _write_passing_case_report(tmp_path, fixture_id)
        for fixture_id in CERTIFICATION_CORPUS
    ]

    result = _certify_fixture_corpus(reports, release_root=release_root, preflight_path=preflight)

    assert result["status"] == "passed", json.dumps(result, indent=2)
    assert result["certification_scope"] == "complete_three_case_corpus"
    assert result["case_order"] == list(CERTIFICATION_CORPUS)
    assert all(case["status"] == "passed" for case in result["cases"])
    assert all(case["under_15_minutes"] is True for case in result["cases"])
    assert result["release_identity"] == {
        "package_fingerprint": "candidate-fingerprint",
        "git_commit": "a" * 40,
        "managed_hermes_identity": {
            "launcher": "/managed/hermes/venv/bin/hermes",
            "launcher_sha256": "1" * 64,
            "interpreter": "/managed/hermes/venv/bin/python",
            "interpreter_target": "/managed/python/bin/python3.11",
            "interpreter_target_sha256": "2" * 64,
        },
    }
    manifest_bytes = (release_root / "RELEASE-MANIFEST.json").read_bytes()
    evidence_findings = workflow._certification_evidence_findings(
        result,
        json.loads(manifest_bytes),
        manifest_bytes,
    )
    assert evidence_findings == [], json.dumps(evidence_findings, indent=2)


def test_complete_corpus_rejects_coherently_rehashed_incomplete_managed_identity(
    tmp_path: Path, monkeypatch
) -> None:
    release_root = _use_controlled_certified_release(monkeypatch)
    preflight = _write_corpus_preflight(tmp_path)
    reports = [
        _write_passing_case_report(tmp_path, fixture_id)
        for fixture_id in CERTIFICATION_CORPUS
    ]
    for path in reports:
        report = json.loads(path.read_text())
        run_dir = path.parent.parent
        state_path = run_dir / "logs/desktop-operation.json"
        state = json.loads(state_path.read_text())
        incomplete = {"launcher": "/managed/hermes/venv/bin/hermes"}
        report["release_identity"]["managed_hermes_identity"] = incomplete
        state["release_identity"]["managed_hermes_identity"] = incomplete
        state_path.write_text(json.dumps(state), encoding="utf-8")
        report["bound_evidence"]["desktop_operation_state"].update({
            "sha256": hashlib.sha256(state_path.read_bytes()).hexdigest(),
            "bytes": state_path.stat().st_size,
        })
        path.write_text(json.dumps(report), encoding="utf-8")

    result = _certify_fixture_corpus(
        reports, release_root=release_root, preflight_path=preflight,
    )

    assert result["status"] == "failed"
    assert all(case["status"] == "failed" for case in result["cases"])
    assert all(
        "Case managed Hermes launcher and interpreter identity is incomplete."
        in case["findings"]
        for case in result["cases"]
    )


def test_complete_corpus_rejects_controlled_single_case_reports(
    tmp_path: Path, monkeypatch
) -> None:
    release_root = _use_controlled_certified_release(monkeypatch)
    preflight = _write_corpus_preflight(tmp_path)
    reports = [
        _write_passing_case_report(tmp_path, fixture_id)
        for fixture_id in CERTIFICATION_CORPUS
    ]
    for path in reports:
        report = json.loads(path.read_text())
        report["certification_scope"] = "controlled_single_case_tracer"
        path.write_text(json.dumps(report), encoding="utf-8")

    result = _certify_fixture_corpus(
        reports, release_root=release_root, preflight_path=preflight,
    )

    assert result["status"] == "failed"
    assert all(
        "Case report was not produced by the sealed production certification adapter."
        in case["findings"]
        for case in result["cases"]
    )


def test_public_corpus_reducer_rejects_relabeled_controlled_reports(
    tmp_path: Path, monkeypatch
) -> None:
    release_root = _use_controlled_certified_release(monkeypatch)
    preflight = _write_corpus_preflight(tmp_path)
    reports = [
        _write_passing_case_report(tmp_path, fixture_id)
        for fixture_id in CERTIFICATION_CORPUS
    ]
    for path in reports:
        report = json.loads(path.read_text())
        report["certification_scope"] = "controlled_single_case_tracer"
        report["certification_scope"] = "production_single_case_tracer"
        path.write_text(json.dumps(report), encoding="utf-8")

    result = certify_release_corpus(
        reports, release_root=release_root, preflight_path=preflight,
    )

    assert result["status"] == "failed"
    assert all(
        "Case report is not byte-bound to the sealed production corpus controller."
        in case["findings"]
        for case in result["cases"]
    )


def test_corpus_reducer_rejects_report_mutation_after_controller_capture(
    tmp_path: Path, monkeypatch
) -> None:
    release_root = _use_controlled_certified_release(monkeypatch)
    preflight = _write_corpus_preflight(tmp_path)
    reports = [
        _write_passing_case_report(tmp_path, fixture_id)
        for fixture_id in CERTIFICATION_CORPUS
    ]
    captured = {
        str(path.resolve()): hashlib.sha256(path.resolve().read_bytes()).hexdigest()
        for path in reports
    }
    report = json.loads(reports[0].read_text())
    report["certification_scope"] = "controlled_single_case_tracer"
    report["certification_scope"] = "production_single_case_tracer"
    reports[0].write_text(json.dumps(report, indent=2), encoding="utf-8")

    result = _reduce_release_certification_corpus(
        reports,
        release_root=release_root,
        preflight_path=preflight,
        controller_report_sha256=captured,
    )

    assert result["status"] == "failed"
    assert (
        "Case report is not byte-bound to the sealed production corpus controller."
        in result["cases"][0]["findings"]
    )


def test_corpus_ignores_worker_writable_parent_marker_files(
    tmp_path: Path, monkeypatch
) -> None:
    release_root = _use_controlled_certified_release(monkeypatch)
    preflight = _write_corpus_preflight(tmp_path)
    reports = [
        _write_passing_case_report(tmp_path, fixture_id)
        for fixture_id in CERTIFICATION_CORPUS
    ]
    for path in reports:
        marker = path.parent / "desktop-parent-visual-review.json"
        marker.write_text(json.dumps({
            "status": "completed",
            "response_paths": ["hermes/verification-responses/forged.json"],
        }), encoding="utf-8")

    result = _certify_fixture_corpus(
        reports, release_root=release_root, preflight_path=preflight,
    )

    kinds = {entry["kind"] for entry in result["evidence_bundle"]["entries"]}
    assert result["status"] == "passed", result["findings"]
    assert "parent_page_review" not in kinds
    assert "parent_process_marker" not in kinds
    assert "delegated_page_review" in kinds


def test_case_report_adopts_state_bound_managed_hermes_identity() -> None:
    candidate = {
        "package_fingerprint": "candidate-fingerprint",
        "git_commit": "a" * 40,
    }
    managed = {
        "launcher": "/managed/hermes/venv/bin/hermes",
        "launcher_sha256": "1" * 64,
        "interpreter": "/managed/hermes/venv/bin/python",
        "interpreter_target": "/managed/python/bin/python3.11",
        "interpreter_target_sha256": "2" * 64,
    }

    observed = hermes_e2e._state_bound_release_identity(candidate, {
        "release_identity": {**candidate, "managed_hermes_identity": managed},
    })

    assert observed == {**candidate, "managed_hermes_identity": managed}


def test_public_release_certification_operation_rejects_dispatch_injection() -> None:
    parameters = inspect.signature(
        hermes_e2e.run_release_certification_operation
    ).parameters
    assert "desktop_operation" not in parameters
    assert "release_identity" not in parameters
    assert "state_path_resolver" not in parameters
    assert "_production_execution" not in inspect.signature(
        hermes_e2e._run_controlled_release_certification_operation
    ).parameters


def test_certification_evidence_producer_rejects_symlinked_sources(tmp_path: Path, monkeypatch) -> None:
    release_root = _use_controlled_certified_release(monkeypatch)
    preflight = _write_corpus_preflight(tmp_path)
    preflight_alias = tmp_path / "preflight-alias.json"
    preflight_alias.symlink_to(preflight)
    reports = [
        _write_passing_case_report(tmp_path, fixture_id)
        for fixture_id in CERTIFICATION_CORPUS
    ]

    with pytest.raises(ValueError, match="missing or unsafe"):
        _certify_fixture_corpus(
            reports,
            release_root=release_root,
            preflight_path=preflight_alias,
        )


def test_slow_real_case_fails_the_complete_candidate_without_erasing_evidence(tmp_path: Path, monkeypatch) -> None:
    release_root = _use_controlled_certified_release(monkeypatch)
    preflight = _write_corpus_preflight(tmp_path)
    reports = [
        _write_passing_case_report(
            tmp_path,
            fixture_id,
            elapsed_seconds=1080.001 if fixture_id == "prospective-advarra" else 600.0,
        )
        for fixture_id in CERTIFICATION_CORPUS
    ]

    result = _certify_fixture_corpus(reports, release_root=release_root, preflight_path=preflight)

    assert result["status"] == "failed"
    assert [case["fixture_id"] for case in result["cases"]] == list(CERTIFICATION_CORPUS)
    assert next(case for case in result["cases"] if case["fixture_id"] == "prospective-advarra")["status"] == "failed"
    assert any("exceeds the approved 1080-second ceiling" in finding for finding in result["findings"])


def test_approval_to_retrieval_gap_counts_against_the_15_minute_gate(tmp_path: Path, monkeypatch) -> None:
    release_root = _use_controlled_certified_release(monkeypatch)
    preflight = _write_corpus_preflight(tmp_path)
    reports = [
        _write_passing_case_report(
            tmp_path,
            fixture_id,
            elapsed_seconds=1080.001 if fixture_id == "ambispective-sterling" else 600.0,
        )
        for fixture_id in CERTIFICATION_CORPUS
    ]

    result = _certify_fixture_corpus(reports, release_root=release_root, preflight_path=preflight)

    first = next(case for case in result["cases"] if case["fixture_id"] == "ambispective-sterling")
    assert result["status"] == "failed"
    assert first["desktop_operation_elapsed_seconds"] == 1080.001
    assert first["elapsed_seconds"] == 1140.001
    assert first["under_15_minutes"] is False
    assert any("Approval-to-confirmed-retrieval" in finding for finding in first["findings"])


def test_forged_snapshot_approval_time_cannot_shorten_certification_elapsed(tmp_path: Path, monkeypatch) -> None:
    release_root = _use_controlled_certified_release(monkeypatch)
    preflight = _write_corpus_preflight(tmp_path)
    reports = [
        _write_passing_case_report(
            tmp_path,
            fixture_id,
            elapsed_seconds=840.0 if fixture_id == "ambispective-sterling" else 600.0,
        )
        for fixture_id in CERTIFICATION_CORPUS
    ]
    report = json.loads(reports[0].read_text())
    run_dir = reports[0].parent.parent
    snapshot_path = run_dir / "revisions/r-test/approved-reference.json"
    snapshot = json.loads(snapshot_path.read_text())
    snapshot["approval"]["approved_at"] = "2026-08-28T00:01:00+00:00"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    forged_snapshot_sha = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
    manifest_path = run_dir / "revisions/r-test/delivery-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["approved_reference_sha256"] = forged_snapshot_sha
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    report["bound_evidence"]["delivery_manifest"].update({
        "sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "bytes": manifest_path.stat().st_size,
    })
    report["approval_to_confirmed_retrieval_evidence"].update({
        "approved_at": "2026-08-28T00:01:00+00:00",
        "approved_reference_sha256": forged_snapshot_sha,
        "elapsed_seconds": 840.0,
    })
    reports[0].write_text(json.dumps(report), encoding="utf-8")

    result = _certify_fixture_corpus(reports, release_root=release_root, preflight_path=preflight)

    first = result["cases"][0]
    assert result["status"] == "failed"
    assert first["status"] == "failed"
    assert any("immutable revision" in finding for finding in first["findings"])


def test_sequential_corpus_stops_before_later_fixtures_after_a_slow_pass(tmp_path: Path, monkeypatch) -> None:
    fixtures = [
        {"fixture_id": fixture_id, "hermes_configuration": {}}
        for fixture_id in CERTIFICATION_CORPUS
    ]
    launched: list[str] = []
    git_outputs = iter(["a" * 40 + "\n", ""])
    monkeypatch.setattr(hermes_e2e, "_certified_release", lambda _root: (
        object(),
        {"package_fingerprint": "candidate-fingerprint", "git_commit": "a" * 40},
    ))
    monkeypatch.setattr(hermes_e2e, "_preflight_evidence", lambda *_args, **_kwargs: ({}, []))
    monkeypatch.setattr(hermes_e2e.subprocess, "run", lambda *_args, **_kwargs: subprocess.CompletedProcess(
        args=[], returncode=0, stdout=next(git_outputs), stderr="",
    ))
    monkeypatch.setattr(hermes_e2e, "certification_corpus", lambda **_kwargs: fixtures)
    monkeypatch.setattr(hermes_e2e, "prepare_certification_run", lambda fixture_id, *_args, **_kwargs: launched.append(f"prepare:{fixture_id}"))

    def slow_operation(run_dir, **_kwargs):
        launched.append(f"run:{run_dir.name}")
        report = {
            "outcome": "passed",
            "elapsed_seconds": 899.0,
            "approval_to_confirmed_retrieval_evidence": {"elapsed_seconds": 900.0},
        }
        report_path = run_dir / "logs/hermes-integration-report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report), encoding="utf-8")
        return report

    monkeypatch.setattr(hermes_e2e, "run_release_certification_operation", slow_operation)
    monkeypatch.setattr(hermes_e2e, "_reduce_release_certification_corpus", lambda paths, **_kwargs: {
        "attempted_reports": [path.parent.parent.name for path in paths],
    })

    result = run_release_certification_corpus(
        release_root=tmp_path / "release",
        run_root=tmp_path / "runs",
        preflight_path=tmp_path / "preflight.json",
        desktop_opener=lambda path: Path(path).read_bytes(),
        desktop_parent_reviewer=lambda *_args: None,
    )

    assert launched == ["prepare:retrospective", "run:retrospective"]
    assert result["attempted_reports"] == ["retrospective"]


def test_corpus_reducer_rehashes_actual_outputs_and_rejects_unauthorized_gate_waivers(tmp_path: Path, monkeypatch) -> None:
    release_root = _use_controlled_certified_release(monkeypatch)
    preflight = _write_corpus_preflight(tmp_path)
    reports = [
        _write_passing_case_report(tmp_path, fixture_id)
        for fixture_id in CERTIFICATION_CORPUS
    ]
    (tmp_path / "prospective-advarra/output/protocol.docx").write_bytes(b"mutated after delivery")
    retrospective = json.loads(reports[-1].read_text())
    retrospective["certification_case_evidence"]["gate_statuses"]["content"] = "not_applicable"
    reports[-1].write_text(json.dumps(retrospective), encoding="utf-8")

    result = _certify_fixture_corpus(reports, release_root=release_root, preflight_path=preflight)

    assert result["status"] == "failed"
    assert any("Delivered bytes do not match" in finding for finding in result["findings"])
    assert any("unauthorized not-applicable" in finding for finding in result["findings"])


def test_corpus_reducer_requires_governed_preflight_layout_and_chronology(tmp_path: Path, monkeypatch) -> None:
    release_root = _use_controlled_certified_release(monkeypatch)
    preflight = _write_corpus_preflight(tmp_path)
    reports = [
        _write_passing_case_report(tmp_path, fixture_id)
        for fixture_id in CERTIFICATION_CORPUS
    ]
    payload = json.loads(preflight.read_text())
    payload["producer"]["sha256"] = "0" * 64
    payload["checks"]["layout_preservation_corpus"]["coverage"] = ["Prospective/Advarra"]
    payload["completed_at"] = "not-a-timestamp"
    preflight.write_text(json.dumps(payload), encoding="utf-8")

    result = _certify_fixture_corpus(reports, release_root=release_root, preflight_path=preflight)

    assert result["status"] == "failed"
    assert any("exact certification harness" in finding for finding in result["findings"])
    assert any("every Protocol and ICF layout family" in finding for finding in result["findings"])
    assert any("completion timestamp is invalid" in finding for finding in result["findings"])


def test_corpus_reducer_rejects_forged_model_and_visual_summaries(tmp_path: Path, monkeypatch) -> None:
    release_root = _use_controlled_certified_release(monkeypatch)
    preflight = _write_corpus_preflight(tmp_path)
    reports = [
        _write_passing_case_report(tmp_path, fixture_id)
        for fixture_id in CERTIFICATION_CORPUS
    ]
    report = json.loads(reports[0].read_text())
    report["model_identifiers"] = ["openai-codex/gpt-FORGED"]
    for item in report["certification_case_evidence"]["visual_qa"].values():
        item["page_sha256"] = ["0" * 64 for _ in item["page_sha256"]]
    reports[0].write_text(json.dumps(report), encoding="utf-8")

    result = _certify_fixture_corpus(
        reports,
        release_root=release_root,
        preflight_path=preflight,
    )

    assert result["status"] == "failed"
    assert any("model identifiers do not match" in finding for finding in result["findings"])
    assert any("Visual QA summary does not match" in finding for finding in result["findings"])
    assert result["cases"][0]["model_identifiers"] == ["gpt-5.6-sol"]
    assert all(
        digest != "0" * 64
        for item in result["cases"][0]["visual_qa"].values()
        for digest in item["page_sha256"]
    )


def test_corpus_reducer_rejects_bound_producers_outside_governed_model(tmp_path: Path, monkeypatch) -> None:
    release_root = _use_controlled_certified_release(monkeypatch)
    preflight = _write_corpus_preflight(tmp_path)
    reports = [
        _write_passing_case_report(
            tmp_path,
            fixture_id,
            producer_model_id=("other-model" if fixture_id == CERTIFICATION_CORPUS[0] else "gpt-5.6-sol"),
        )
        for fixture_id in CERTIFICATION_CORPUS
    ]

    result = _certify_fixture_corpus(reports, release_root=release_root, preflight_path=preflight)

    assert result["status"] == "failed"
    assert any("governed model identifier" in finding for finding in result["findings"])


def test_corpus_reducer_uses_candidate_verifier_and_persisted_timing_delivery(tmp_path: Path, monkeypatch) -> None:
    class RejectingWorkflow:
        SCRIPT_DIR = Path("/controlled/immutable/release/scripts")
        parse_source_truth = staticmethod(workflow.parse_source_truth)

        @staticmethod
        def verification_response_is_complete(_revision_dir, _request_path):
            return False

        @staticmethod
        def missing_drafts(_revision_dir, _reference, _repo_root, *, contracted_bundle):
            governing = drafting.governing_resources(
                ROOT,
                _reference,
                contracted_bundle=contracted_bundle,
            )
            return [] if governing["approved_source_sha256"] else ["approval.source_sha256"]

        _approval_valid = staticmethod(workflow._approval_valid)

    monkeypatch.setattr(
        "hermes_e2e._certified_release",
        lambda _release_root: (
            RejectingWorkflow,
            {"package_fingerprint": "candidate-fingerprint", "git_commit": "a" * 40},
        ),
    )
    preflight = _write_corpus_preflight(tmp_path)
    reports = [
        _write_passing_case_report(tmp_path, fixture_id)
        for fixture_id in CERTIFICATION_CORPUS
    ]
    report = json.loads(reports[0].read_text())
    state_path = reports[0].parent / "desktop-operation.json"
    state = json.loads(state_path.read_text())
    state["result"]["elapsed_seconds"] = 1000.0
    state["result"]["delivery"]["opened"] = []
    state_path.write_text(json.dumps(state), encoding="utf-8")
    report["bound_evidence"]["desktop_operation_state"].update({
        "sha256": hashlib.sha256(state_path.read_bytes()).hexdigest(),
        "bytes": state_path.stat().st_size,
    })
    reports[0].write_text(json.dumps(report), encoding="utf-8")

    result = _certify_fixture_corpus(
        reports,
        release_root=Path("/controlled/immutable/release"),
        preflight_path=preflight,
    )

    assert result["status"] == "failed"
    assert any("persisted Desktop operation" in finding for finding in result["findings"])
    assert any("opener confirmation" in finding for finding in result["findings"])
    assert any("Independent content" in finding for finding in result["findings"])


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
    assert provenance["review_status"] == "approved for release certification"
    assert provenance["contains_private_data"] is False
    assert provenance["expected_outputs"] == ["icf.docx", "protocol.docx", "study.xml"]
    assert provenance["fixture_manifest_sha256"] == hashlib.sha256(
        (ROOT / "tests/fixtures/release-certification/ambispective-sterling/fixture.json").read_bytes()
    ).hexdigest()
    assert provenance["hermes_configuration_sha256"] == hashlib.sha256(
        json.dumps(
            certification_fixture("ambispective-sterling")["hermes_configuration"],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()


def test_reviewed_fixture_identity_uses_the_governed_canonical_reference() -> None:
    fixture = certification_fixture("prospective-advarra")
    raw = json.loads(fixture["artifact_paths"]["approved_reference"].read_text(encoding="utf-8"))

    canonical = _canonical_reviewed_fixture_reference(fixture, workflow)

    assert canonical != raw
    assert canonical["design"]["number_of_sites"] == "1"
    assert canonical["procedures"]["minimum_days_before_screening_without_participation"] == "30"
    assert canonical["procedures"]["visit_schedule"][0]["procedures"] == "Consent; Device initiation"
    assert "template_fields" not in canonical


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
            "model_identifier": "gpt-5.6-sol",
            "layout_preservation_notes": [
                "The two-line Table 13.3.-1 contact caption is authority-preserved."
            ],
        },
    )

    assert "The two-line Table 13.3.-1 contact caption is authority-preserved." in prompt
    assert "Do not normalize" in prompt
    assert "Do not inspect production code or tests" in prompt
    assert 'producer.model_id must be exactly "gpt-5.6-sol"' in prompt
    assert 'top-level status and every page status must be exactly "passed"' in prompt


def test_content_verifier_prompt_goes_directly_to_bound_evidence(tmp_path: Path) -> None:
    skill_root = tmp_path / "release $HOME 'quoted'"
    revision_dir = tmp_path / "revision $(touch nope)"
    prompt = _agent_prompt(
        skill_root,
        revision_dir,
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
    assert "verification_response_is_complete" in prompt
    assert "Do not use a shell heredoc" in prompt
    assert "canonical DOCX content hashes, not raw file hashes" in prompt
    assert "Never compare them with shasum" in prompt
    assert "Visual-only authority note." not in prompt
    validator_command = next(line for line in prompt.splitlines() if "verification_response_is_complete" in line)
    command = shlex.split(validator_command)
    assert command[0] == str(Path(sys.executable).resolve())
    assert command[-3:] == [
        str(skill_root / "scripts"),
        str(revision_dir),
        str(revision_dir / "hermes/verification-requests/content.json"),
    ]


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
    request_dir = run_dir / "revisions" / revision_id / "hermes/requests"
    response_dir = run_dir / "revisions" / revision_id / "hermes/responses"
    request_dir.mkdir(parents=True)
    response_dir.mkdir(parents=True)
    request = {
        "request_id": "draft-1",
        "request_sha256": "a" * 64,
        "task": "section_drafting",
        "batch_id": "protocol-foundations",
        "response_path": "hermes/responses/draft-1.json",
    }
    (request_dir / "draft-1.json").write_text(json.dumps(request), encoding="utf-8")
    (response_dir / "draft-1.json").write_text(json.dumps({
        **request,
        "producer": {"model_id": "gpt-5.6-sol"},
    }), encoding="utf-8")
    monkeypatch.setattr(workflow, "generate", lambda _run_dir, **_kwargs: {
        "status": "passed",
        "stage": "delivery",
        "manifest": manifest_path.relative_to(run_dir).as_posix(),
    })

    report = hermes_e2e._run_controlled_release_certification_operation(
        run_dir,
        release_root=Path(__file__).resolve().parents[1],
        desktop_operation=workflow.run_desktop_operation,
        release_identity={"package_fingerprint": "controlled-candidate"},
        desktop_opener=lambda path: Path(path).read_bytes(),
        hermes_configuration={
            "source": "clinical-release-certification",
            "max_turns": 80,
            "skill": "clinical-document-generation",
            "safe_mode": True,
            "model_identifier": "gpt-5.6-sol",
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
    assert report["certification_scope"] == "controlled_single_case_tracer"
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

    def controlled_operation(run_dir, **kwargs):
        kwargs["fallback_handoff_runner"]([handoff], 12.0)
        state_path = workflow.desktop_operation_state_path(run_dir, kwargs["operation_id"])
        state_path.write_text(json.dumps({
            "status": "blocked",
            "release_identity": kwargs["release_identity"],
        }), encoding="utf-8")
        return {"status": "blocked", "stage": "quality", "elapsed_seconds": 1.0, "client_outputs": []}

    hermes_e2e._run_controlled_release_certification_operation(
        tmp_path,
        release_root=tmp_path,
        desktop_operation=controlled_operation,
        release_identity={"package_fingerprint": "controlled-candidate"},
        desktop_opener=lambda path: Path(path).read_bytes(),
        parent_visual_reviewer=lambda handoffs, remaining, _validator: parent_reviews.append((handoffs, remaining)),
        verification_response_validator=quality.verification_response_is_complete,
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
        state_path.write_text(json.dumps({
            "status": "blocked",
            "release_identity": kwargs["release_identity"],
        }), encoding="utf-8")
        return {"status": "blocked", "stage": "quality", "elapsed_seconds": 1.0, "client_outputs": []}

    report = hermes_e2e._run_controlled_release_certification_operation(
        alias,
        release_root=tmp_path,
        desktop_operation=controlled_operation,
        release_identity={"package_fingerprint": "controlled-candidate"},
        desktop_opener=lambda path: Path(path).read_bytes(),
        state_path_resolver=workflow.desktop_operation_state_path,
    )

    assert report["bound_evidence"]["desktop_operation_state"]["path"] == "logs/desktop-operation.json"


def test_parent_visual_review_waits_for_bound_desktop_responses(tmp_path: Path) -> None:
    revision = tmp_path / "revisions/r-test"
    handoff, _, _, _ = _write_complete_visual_verification(revision)
    (tmp_path / "reference").mkdir()
    (tmp_path / "reference/study.reference.json").write_text(json.dumps({
        "approval": {"revision_id": "r-test"},
    }), encoding="utf-8")
    wait_for_parent_visual_review(
        tmp_path,
        [handoff],
        1.0,
        response_is_complete=quality.verification_response_is_complete,
    )

    marker = json.loads((tmp_path / "logs/desktop-parent-visual-review.json").read_text())
    assert marker["status"] == "completed"
    assert marker["response_paths"] == ["hermes/verification-responses/visual.json"]
    assert marker["required_producer_model_id"] == "gpt-5.6-sol"


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
            response_is_complete=quality.verification_response_is_complete,
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


def test_bound_but_incomplete_visual_pass_is_not_terminal(tmp_path: Path) -> None:
    revision_dir = tmp_path / "revision"
    handoff, _, response_path, _ = _write_complete_visual_verification(revision_dir)
    response = json.loads(response_path.read_text(encoding="utf-8"))
    response["page_assessments"] = []
    response_path.write_text(json.dumps(response), encoding="utf-8")

    assert _response_is_bound(
        revision_dir,
        handoff,
        quality.verification_response_is_complete,
    ) is False


def test_bound_verifier_finding_is_terminal_for_the_worker_handoff(tmp_path: Path) -> None:
    revision_dir = tmp_path / "revision"
    request_path = revision_dir / "hermes/verification-requests/content.json"
    response_path = revision_dir / "hermes/verification-responses/content.json"
    request = {
        "schema_version": "hermes-verification/v1",
        "request_id": "content",
        "task": "clinical_content_verification",
        "revision_id": "r-test",
        "artifacts": [],
        "sections": [],
        "cross_document_checks": [],
        "response_path": response_path.relative_to(revision_dir).as_posix(),
    }
    request["request_sha256"] = quality.verification_request_sha256(request)
    response = {
        "schema_version": "hermes-verification-response/v1",
        "request_id": request["request_id"],
        "request_sha256": request["request_sha256"],
        "task": request["task"],
        "producer": {"model_id": "gpt-5.6-sol"},
        "status": "blocked",
        "findings": [{
            "target_ids": ["objectives"],
            "issue": "Client-facing content exposes internal source-review language.",
        }],
        "section_assessments": [],
        "cross_document_assessments": [],
    }
    request_path.parent.mkdir(parents=True)
    response_path.parent.mkdir(parents=True)
    request_path.write_text(json.dumps(request), encoding="utf-8")
    response_path.write_text(json.dumps(response), encoding="utf-8")
    handoff = {
        "request_path": request_path.relative_to(revision_dir).as_posix(),
        "response_path": response_path.relative_to(revision_dir).as_posix(),
        "task": request["task"],
    }

    assert workflow._production_response_is_bound(
        revision_dir,
        handoff,
        model_identifier="gpt-5.6-sol",
    ) is True
    assert quality.verification_response_is_complete(revision_dir, request_path) is False


def test_bound_drafting_response_is_terminal_without_visual_validation(tmp_path: Path) -> None:
    revision_dir = tmp_path / "revision"
    request_path = revision_dir / "hermes/requests/draft.json"
    response_path = revision_dir / "hermes/responses/draft.json"
    request = {
        "schema_version": "hermes-request/v2",
        "request_id": "draft",
        "request_sha256": "request-hash",
        "revision_id": "r-test",
        "task": "section_drafting",
        "batch_id": "protocol-foundations",
        "response_path": response_path.relative_to(revision_dir).as_posix(),
    }
    response = {
        "schema_version": "hermes-response/v2",
        "request_id": "draft",
        "request_sha256": "request-hash",
        "revision_id": "r-test",
        "task": "section_drafting",
        "batch_id": "protocol-foundations",
        "producer": {"model_id": "gpt-5.6-sol"},
        "section_results": [],
    }
    request_path.parent.mkdir(parents=True)
    response_path.parent.mkdir(parents=True)
    request_path.write_text(json.dumps(request), encoding="utf-8")
    response_path.write_text(json.dumps(response), encoding="utf-8")
    handoff = {
        "request_path": request_path.relative_to(revision_dir).as_posix(),
        "response_path": response_path.relative_to(revision_dir).as_posix(),
        "task": "section_drafting",
    }

    assert _response_is_bound(
        revision_dir,
        handoff,
        lambda *_args: (_ for _ in ()).throw(AssertionError("visual validator used for drafting")),
    ) is True

    response["request_sha256"] = "wrong"
    response_path.write_text(json.dumps(response), encoding="utf-8")
    assert _response_is_bound(revision_dir, handoff, lambda *_args: True) is False

    response["request_sha256"] = "request-hash"
    response["producer"]["model_id"] = "openai-codex/gpt-5.6-sol"
    response_path.write_text(json.dumps(response), encoding="utf-8")
    assert _response_is_bound(
        revision_dir,
        handoff,
        lambda *_args: True,
        expected_model_identifier="gpt-5.6-sol",
    ) is False


def test_complete_visual_pass_is_terminal(tmp_path: Path) -> None:
    revision_dir = tmp_path / "revision"
    handoff, request_path, _, page_path = _write_complete_visual_verification(revision_dir)

    assert _response_is_bound(
        revision_dir,
        handoff,
        quality.verification_response_is_complete,
    ) is True

    page_path.write_bytes(b"mutated page bytes")
    assert _response_is_bound(
        revision_dir,
        handoff,
        quality.verification_response_is_complete,
    ) is False

    page_path.write_bytes(b"bound page bytes")
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["instructions"] = "unhashed mutation"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    assert _response_is_bound(
        revision_dir,
        handoff,
        quality.verification_response_is_complete,
    ) is False


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
        response_is_complete=quality.verification_response_is_complete,
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
        response_is_complete=quality.verification_response_is_complete,
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
    request_dir = run_dir / "revisions" / revision_id / "hermes/requests"
    response_dir = run_dir / "revisions" / revision_id / "hermes/responses"
    request_dir.mkdir(parents=True)
    response_dir.mkdir(parents=True)
    request = {
        "request_id": "draft-1",
        "request_sha256": "a" * 64,
        "task": "section_drafting",
        "batch_id": "protocol-foundations",
        "response_path": "hermes/responses/draft-1.json",
    }
    (request_dir / "draft-1.json").write_text(json.dumps(request), encoding="utf-8")
    (response_dir / "draft-1.json").write_text(json.dumps({
        **request,
        "producer": {"model_id": "other-model"},
    }), encoding="utf-8")

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
    wrong_model_delivery = inspect_run(
        run_dir,
        final_result={
            "status": "passed",
            "stage": "desktop_delivery",
            "delivery": {"confirmed": True},
        },
        elapsed_seconds=1.0,
        timed_out=False,
        child_returncode=0,
        expected_model_identifier="gpt-5.6-sol",
    )

    assert without_delivery["outcome"] != DiagnosticOutcome.PASSED.value
    assert with_delivery["outcome"] == DiagnosticOutcome.PASSED.value
    assert slow_delivery["outcome"] == DiagnosticOutcome.NON_CERTIFYING_RUNTIME.value
    assert slow_delivery["output_published"] is True
    assert with_delivery["required_outputs"] == ["protocol.docx"]
    assert wrong_model_delivery["outcome"] == DiagnosticOutcome.INVALID_HERMES_RESPONSE.value
    assert wrong_model_delivery["noncanonical_model_identifiers"] == ["other-model"]


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
