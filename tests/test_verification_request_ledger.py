import copy
import hashlib
import json
from pathlib import Path

import pytest

import quality
from quality import (
    CONTENT_CHECKS,
    RESPONSE_SCHEMA,
    VISUAL_CHECKS,
    validate_verifications,
    verification_recovery_request_findings,
    verification_request_sha256,
    verification_response_is_complete,
    verification_response_is_terminal,
)


ROOT = Path(__file__).resolve().parents[1]


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _request(revision: Path, task: str) -> tuple[Path, dict]:
    request_id = f"{revision.name}.review-1.verify.{'content' if task == 'clinical_content_verification' else 'visual.protocol'}"
    request = {
        "schema_version": "hermes-verification-request/v2",
        "request_id": request_id,
        "task": task,
        "revision_id": revision.name,
        "review_set": 1,
        "checks": list(CONTENT_CHECKS if task == "clinical_content_verification" else VISUAL_CHECKS),
        "response_path": f"hermes/verification-responses/{request_id}.json",
    }
    if task == "clinical_content_verification":
        request.update({
            "artifacts": [],
            "sections": [],
            "cross_document_checks": [],
            "approved_source": {"study": {"title": "Canonical source"}},
        })
    else:
        docx = revision / "candidate/protocol.docx"
        pdf = revision / "rendered/protocol.pdf"
        page = revision / "rendered/protocol/page-001.png"
        for path, data in ((docx, b"docx"), (pdf, b"pdf"), (page, b"png")):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        request["artifacts"] = [{
            "artifact": "protocol",
            "docx": "candidate/protocol.docx",
            "docx_sha256": _sha256(docx),
            "pdf": "rendered/protocol.pdf",
            "pdf_sha256": _sha256(pdf),
            "pages": [{
                "page": 1,
                "path": "rendered/protocol/page-001.png",
                "sha256": _sha256(page),
            }],
        }]
    request["request_sha256"] = verification_request_sha256(request)
    path = revision / "hermes/verification-requests" / f"{request_id}.json"
    _write_json(path, request)
    return path, request


def _ledger(revision: Path, request_path: Path, request: dict, **overrides) -> Path:
    record = {
        "schema_version": "verification-request-ledger/v1",
        "request_id": request["request_id"],
        "request_sha256": request["request_sha256"],
        "request_file_sha256": _sha256(request_path),
        "task": request["task"],
        "revision_id": request["revision_id"],
        "review_set": request["review_set"],
        **overrides,
    }
    path = revision / "request-ledger" / f"{request['request_id']}.json"
    _write_json(path, record)
    return path


def _response(revision: Path, request: dict, *, task=None) -> Path:
    response = {
        "schema_version": RESPONSE_SCHEMA,
        "request_id": request["request_id"],
        "request_sha256": request["request_sha256"],
        "task": task or request["task"],
        "revision_id": request["revision_id"],
        "producer": {"model_id": "focused-test-model", "reviewer_id": "independent-reviewer"},
        "status": "passed",
        "findings": [],
    }
    if request["task"] == "clinical_content_verification":
        response.update({"section_assessments": [], "cross_document_assessments": []})
    else:
        page = request["artifacts"][0]["pages"][0]
        response["page_assessments"] = [{
            "artifact": "protocol",
            "page": page["page"],
            "sha256": page["sha256"],
            "status": "passed",
            "checks": list(VISUAL_CHECKS),
        }]
    path = revision / request["response_path"]
    _write_json(path, response)
    return path


@pytest.mark.parametrize("task", ["clinical_content_verification", "rendered_page_visual_verification"])
def test_valid_canonical_ledger_bound_verification_response_passes(tmp_path, task):
    revision = tmp_path / "r-test"
    request_path, request = _request(revision, task)
    _ledger(revision, request_path, request)
    _response(revision, request)

    findings, evidence = validate_verifications(revision)

    assert findings == []
    assert evidence
    assert verification_response_is_complete(revision, request_path) is True
    assert verification_response_is_terminal(revision, request_path) is True


@pytest.mark.parametrize("task", ["clinical_content_verification", "rendered_page_visual_verification"])
def test_missing_canonical_ledger_blocks_before_acceptance(tmp_path, task):
    revision = tmp_path / "r-test"
    request_path, request = _request(revision, task)
    response_path = _response(revision, request)
    original_response = response_path.read_bytes()

    findings, evidence = validate_verifications(revision)

    assert any(item.get("code") == "verification_request_ledger_missing" for item in findings)
    assert evidence == {}
    assert verification_response_is_complete(revision, request_path) is False
    assert verification_response_is_terminal(revision, request_path) is False
    assert response_path.read_bytes() == original_response
    assert not (revision / "attempts").exists()
    assert not (revision / "gate-attempt-journal.json").exists()


@pytest.mark.parametrize(
    ("ledger_override", "expected_code"),
    [
        ({"request_sha256": "0" * 64}, "verification_request_canonical_hash_mismatch"),
        ({"revision_id": "r-other"}, "verification_request_wrong_revision"),
        ({"task": "rendered_page_visual_verification"}, "verification_request_wrong_task"),
    ],
)
def test_canonical_ledger_binding_mismatch_blocks(tmp_path, ledger_override, expected_code):
    revision = tmp_path / "r-test"
    request_path, request = _request(revision, "clinical_content_verification")
    _ledger(revision, request_path, request, **ledger_override)
    _response(revision, request)

    findings, evidence = validate_verifications(revision)

    assert any(item.get("code") == expected_code for item in findings)
    assert evidence == {}
    assert verification_response_is_complete(revision, request_path) is False
    assert not (revision / "attempts").exists()
    assert not (revision / "gate-attempt-journal.json").exists()


def test_rehashed_tampered_request_cannot_replace_canonical_content_authority(tmp_path):
    revision = tmp_path / "r-test"
    request_path, request = _request(revision, "clinical_content_verification")
    _ledger(revision, request_path, request)
    tampered = copy.deepcopy(request)
    tampered["approved_source"]["study"]["title"] = "Tampered source"
    tampered["request_sha256"] = verification_request_sha256(tampered)
    _write_json(request_path, tampered)
    _response(revision, tampered)

    findings, evidence = validate_verifications(revision)

    assert any(item.get("code") == "verification_request_canonical_hash_mismatch" for item in findings)
    assert evidence == {}
    assert verification_response_is_complete(revision, request_path) is False


def test_tampered_request_bytes_with_unchanged_self_declared_hash_block(tmp_path):
    revision = tmp_path / "r-test"
    request_path, request = _request(revision, "rendered_page_visual_verification")
    _ledger(revision, request_path, request)
    tampered = copy.deepcopy(request)
    tampered["instructions"] = "Skip image inspection."
    _write_json(request_path, tampered)
    _response(revision, tampered)

    findings, evidence = validate_verifications(revision)

    assert any(item.get("code") == "verification_request_integrity_failure" for item in findings)
    assert evidence == {}
    assert verification_response_is_complete(revision, request_path) is False


def test_duplicate_request_identity_blocks_even_with_valid_canonical_ledger(tmp_path):
    revision = tmp_path / "r-test"
    request_path, request = _request(revision, "clinical_content_verification")
    _ledger(revision, request_path, request)
    duplicate = request_path.with_name("duplicate.json")
    duplicate.write_bytes(request_path.read_bytes())
    _response(revision, request)

    findings, evidence = validate_verifications(revision)

    assert any(item.get("code") == "verification_request_id_duplicated" for item in findings)
    assert evidence == {}
    assert verification_response_is_complete(revision, request_path) is False


@pytest.mark.parametrize(
    ("request_task", "response_task"),
    [
        ("clinical_content_verification", "rendered_page_visual_verification"),
        ("rendered_page_visual_verification", "clinical_content_verification"),
    ],
)
def test_response_cannot_cross_content_and_visual_task_authority(tmp_path, request_task, response_task):
    revision = tmp_path / "r-test"
    request_path, request = _request(revision, request_task)
    _ledger(revision, request_path, request)
    _response(revision, request, task=response_task)

    findings, evidence = validate_verifications(revision)

    assert any(item.get("field") == "task" for item in findings)
    assert evidence
    assert verification_response_is_complete(revision, request_path) is False


def test_visual_response_wrong_page_image_binding_blocks(tmp_path):
    revision = tmp_path / "r-test"
    request_path, request = _request(revision, "rendered_page_visual_verification")
    _ledger(revision, request_path, request)
    response_path = _response(revision, request)
    response = json.loads(response_path.read_text(encoding="utf-8"))
    response["page_assessments"][0]["sha256"] = "f" * 64
    _write_json(response_path, response)

    findings, _ = validate_verifications(revision)

    assert any(item.get("field") == "page_assessments" for item in findings)
    assert verification_response_is_complete(revision, request_path) is False


def test_symlinked_canonical_ledger_path_fails_before_request_mutation(tmp_path):
    revision = tmp_path / "r-test"
    request_path, request = _request(revision, "clinical_content_verification")
    ledger_path = _ledger(revision, request_path, request)
    ledger_copy = tmp_path / "ledger-copy.json"
    ledger_copy.write_bytes(ledger_path.read_bytes())
    ledger_path.unlink()
    ledger_path.symlink_to(ledger_copy)
    original_request = request_path.read_bytes()

    with pytest.raises(ValueError, match="ledger path is unsafe"):
        quality.create_verification_requests(
            revision,
            {"meta": {"study_type": "Retrospective"}},
            {"status": "passed", "artifacts": []},
        )

    assert request_path.read_bytes() == original_request
    assert ledger_path.is_symlink()


@pytest.mark.parametrize(
    "relative_root",
    ("hermes", "hermes/verification-requests", "hermes/verification-responses", "request-ledger"),
)
def test_symlinked_mutation_root_fails_before_any_request_write(tmp_path, relative_root):
    revision = tmp_path / "r-test"
    revision.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    root = revision / relative_root
    root.parent.mkdir(parents=True, exist_ok=True)
    root.symlink_to(external, target_is_directory=True)

    with pytest.raises(ValueError, match="path is unsafe"):
        quality.create_verification_requests(
            revision,
            {"meta": {"study_type": "Retrospective"}},
            {"status": "passed", "artifacts": []},
        )

    assert list(external.iterdir()) == []


def test_tampered_occupied_request_cannot_drive_cleanup_or_rewrite(tmp_path):
    revision = tmp_path / "r-test"
    request_path = quality.create_verification_requests(
        revision,
        {"meta": {"study_type": "Retrospective"}},
        {"status": "passed", "artifacts": []},
    )[0]
    original = json.loads(request_path.read_text(encoding="utf-8"))
    response_path = revision / original["response_path"]
    response_path.write_bytes(b"canonical-response")
    victim = tmp_path / "victim.txt"
    victim.write_bytes(b"do-not-delete")
    tampered = copy.deepcopy(original)
    tampered["response_path"] = str(victim)
    tampered["request_sha256"] = verification_request_sha256(tampered)
    _write_json(request_path, tampered)
    tampered_bytes = request_path.read_bytes()

    with pytest.raises(ValueError, match="identity collision"):
        quality.create_verification_requests(
            revision,
            {"meta": {"study_type": "Retrospective"}},
            {"status": "passed", "artifacts": []},
        )

    assert request_path.read_bytes() == tampered_bytes
    assert response_path.read_bytes() == b"canonical-response"
    assert victim.read_bytes() == b"do-not-delete"


@pytest.mark.parametrize("substitution", ["relocated", "symlink"])
def test_request_must_use_canonical_nonsymlinked_path(tmp_path, substitution):
    revision = tmp_path / "r-test"
    request_path, request = _request(revision, "clinical_content_verification")
    _ledger(revision, request_path, request)
    _response(revision, request)
    canonical = request_path
    alternate = canonical.with_name("alternate.json")
    if substitution == "relocated":
        canonical.rename(alternate)
        checked = alternate
    else:
        alternate.write_bytes(canonical.read_bytes())
        canonical.unlink()
        canonical.symlink_to(alternate.name)
        checked = canonical

    findings, evidence = validate_verifications(revision, request_paths=[checked])

    assert any(item.get("code") == "verification_request_noncanonical_path" for item in findings)
    assert evidence == {}


@pytest.mark.parametrize(
    "mutation",
    [
        lambda ledger: ledger.update(schema_version="verification-request-ledger/v0"),
        lambda ledger: ledger.update(extra_authority="forged"),
    ],
)
def test_canonical_ledger_requires_exact_schema_and_shape(tmp_path, mutation):
    revision = tmp_path / "r-test"
    request_path, request = _request(revision, "clinical_content_verification")
    ledger_path = _ledger(revision, request_path, request)
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    mutation(ledger)
    _write_json(ledger_path, ledger)
    _response(revision, request)

    findings, evidence = validate_verifications(revision)

    assert any(item.get("code") == "verification_request_ledger_invalid" for item in findings)
    assert evidence == {}


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [
        ("{", "verification_request_invalid_json"),
        (json.dumps({"request_id": "missing-task"}), "verification_request_missing_binding"),
        (json.dumps({"task": "clinical_content_verification"}), "verification_request_missing_binding"),
    ],
)
def test_malformed_request_inventory_fails_closed_without_raising(tmp_path, payload, expected_code):
    revision = tmp_path / "r-test"
    request_path = revision / "hermes/verification-requests/bad.json"
    request_path.parent.mkdir(parents=True)
    request_path.write_text(payload, encoding="utf-8")

    findings, evidence = validate_verifications(revision)

    assert any(item.get("code") == expected_code for item in findings)
    assert evidence == {}


def _canonical_recovery_content_request(revision: Path) -> tuple[dict, dict]:
    reference = json.loads((
        ROOT / "tests/fixtures/release-certification/prospective-advarra/approved-reference.json"
    ).read_text(encoding="utf-8"))
    candidate = revision / "candidate"
    candidate.mkdir(parents=True)
    for name, data in (("protocol.docx", b"protocol"), ("icf.docx", b"icf"), ("study.xml", b"xml")):
        (candidate / name).write_bytes(data)
    request_id = f"{revision.name}.review-1.verify.content"
    request = {
        "schema_version": "hermes-verification-request/v2",
        "request_id": request_id,
        "task": "clinical_content_verification",
        "revision_id": revision.name,
        "review_set": 1,
        "response_path": f"hermes/verification-responses/{request_id}.json",
        "artifacts": [
            {"artifact": name if name.endswith(".xml") else Path(name).stem,
             "path": f"candidate/{name}", "sha256": _sha256(candidate / name)}
            for name in sorted(("protocol.docx", "icf.docx", "study.xml"))
        ],
        "sections": quality.content_review_sections(reference),
        "approved_source": reference,
        "checks": list(CONTENT_CHECKS),
        "cross_document_checks": list(quality.CROSS_DOCUMENT_CHECKS),
    }
    request["request_sha256"] = verification_request_sha256(request)
    path = revision / "hermes/verification-requests" / f"{request_id}.json"
    _write_json(path, request)
    _ledger(revision, path, request)
    return reference, request


@pytest.mark.parametrize("payload", ["{", "{}"])
def test_malformed_companion_request_blocks_recovery_authorization(tmp_path, payload):
    revision = tmp_path / "r-test"
    reference, request = _canonical_recovery_content_request(revision)
    (revision / "hermes/verification-requests/malformed.json").write_text(payload, encoding="utf-8")
    findings = verification_recovery_request_findings(
        revision, request["request_id"], expected_task="clinical_content_verification",
        current_review_set=1, reference=reference, render_report={},
        bound_artifact="icf", section_target_ids={"icf.procedures"},
    )
    assert findings[0]["code"] == "verification_request_invalid_inventory"


def test_non_json_companion_entry_blocks_recovery_authorization(tmp_path):
    revision = tmp_path / "r-test"
    reference, request = _canonical_recovery_content_request(revision)
    (revision / "hermes/verification-requests/unexpected.txt").write_text("{}", encoding="utf-8")
    findings = verification_recovery_request_findings(
        revision, request["request_id"], expected_task="clinical_content_verification",
        current_review_set=1, reference=reference, render_report={},
        bound_artifact="icf", section_target_ids={"icf.procedures"},
    )
    assert findings[0]["code"] == "verification_request_invalid_inventory"


def test_non_json_request_entry_blocks_response_acceptance(tmp_path):
    revision = tmp_path / "r-test"
    request_path, request = _request(revision, "clinical_content_verification")
    _ledger(revision, request_path, request)
    _response(revision, request)
    (revision / "hermes/verification-requests/unexpected.txt").write_text("{}", encoding="utf-8")
    findings, _ = validate_verifications(revision)
    assert any(item.get("code") == "verification_request_invalid_inventory" for item in findings)
    assert verification_response_is_complete(revision, request_path) is False


def test_stale_content_artifact_hash_blocks_recovery_authorization(tmp_path):
    revision = tmp_path / "r-test"
    reference, request = _canonical_recovery_content_request(revision)
    (revision / "candidate/icf.docx").write_bytes(b"changed")
    findings = verification_recovery_request_findings(
        revision, request["request_id"], expected_task="clinical_content_verification",
        current_review_set=1, reference=reference, render_report={},
        bound_artifact="icf", section_target_ids={"icf.procedures"},
    )
    assert findings[0]["code"] == "verification_request_stale_artifact"


def test_altered_approved_source_cannot_authorize_content_recovery(tmp_path):
    revision = tmp_path / "r-test"
    reference, request = _canonical_recovery_content_request(revision)
    request["approved_source"] = copy.deepcopy(reference)
    request["approved_source"]["study"]["title"] = "Altered authority"
    request["request_sha256"] = verification_request_sha256(request)
    request_path = revision / "hermes/verification-requests" / f"{request['request_id']}.json"
    _write_json(request_path, request)
    _ledger(revision, request_path, request)

    findings = verification_recovery_request_findings(
        revision, request["request_id"], expected_task="clinical_content_verification",
        current_review_set=1, reference=reference, render_report={},
        bound_artifact="icf", section_target_ids={"icf.procedures"},
    )

    assert findings[0]["code"] == "verification_request_incomplete_scope"


def test_stale_visual_page_hash_blocks_recovery_authorization(tmp_path):
    revision = tmp_path / "r-test"
    request_path, request = _request(revision, "rendered_page_visual_verification")
    _ledger(revision, request_path, request)
    render_report = {"artifacts": [copy.deepcopy(request["artifacts"][0])]}
    (revision / request["artifacts"][0]["pages"][0]["path"]).write_bytes(b"changed-page")
    reference = json.loads((
        ROOT / "tests/fixtures/release-certification/prospective-advarra/approved-reference.json"
    ).read_text(encoding="utf-8"))

    findings = verification_recovery_request_findings(
        revision, request["request_id"], expected_task="rendered_page_visual_verification",
        current_review_set=1, reference=reference, render_report=render_report,
        bound_artifact="protocol", _validate_companions=False,
    )

    assert findings[0]["code"] == "verification_request_stale_artifact"


def test_request_ledger_collision_does_not_mutate_existing_request(tmp_path):
    reference = json.loads((
        ROOT / "tests/fixtures/release-certification/prospective-advarra/approved-reference.json"
    ).read_text(encoding="utf-8"))
    request_path = quality.create_verification_requests(
        tmp_path, reference, {"status": "passed", "artifacts": []},
    )[0]
    original = request_path.read_bytes()
    changed = copy.deepcopy(reference)
    changed["study"]["title"] = "Changed after canonical request creation"
    with pytest.raises(ValueError, match="identity collision"):
        quality.create_verification_requests(
            tmp_path, changed, {"status": "passed", "artifacts": []},
        )
    assert request_path.read_bytes() == original


def test_incomplete_canonical_companion_request_blocks_recovery(tmp_path):
    revision = tmp_path / "r-test"
    reference, request = _canonical_recovery_content_request(revision)
    companion_id = f"{revision.name}.review-1.verify.visual.protocol"
    companion = {
        "schema_version": "hermes-verification-request/v2",
        "request_id": companion_id,
        "task": "rendered_page_visual_verification",
        "revision_id": revision.name,
        "review_set": 1,
        "response_path": f"hermes/verification-responses/{companion_id}.json",
        "artifacts": [],
        "checks": [],
    }
    companion["request_sha256"] = verification_request_sha256(companion)
    companion_path = revision / "hermes/verification-requests" / f"{companion_id}.json"
    _write_json(companion_path, companion)
    _ledger(revision, companion_path, companion)
    findings = verification_recovery_request_findings(
        revision, request["request_id"], expected_task="clinical_content_verification",
        current_review_set=1, reference=reference, render_report={},
        bound_artifact="icf", section_target_ids={"icf.procedures"},
    )
    assert findings[0]["code"] == "verification_request_invalid_inventory"


def test_missing_expected_visual_companion_blocks_recovery(tmp_path):
    revision = tmp_path / "r-test"
    reference, request = _canonical_recovery_content_request(revision)
    render_report = {"artifacts": [{"artifact": "protocol"}]}
    findings = verification_recovery_request_findings(
        revision, request["request_id"], expected_task="clinical_content_verification",
        current_review_set=1, reference=reference, render_report=render_report,
        bound_artifact="icf", section_target_ids={"icf.procedures"},
        allow_missing_response=True,
    )
    assert findings[0]["code"] == "verification_request_invalid_inventory"


def test_symlinked_request_parent_is_not_canonical_authority(tmp_path):
    revision = tmp_path / "r-test"
    request_path, request = _request(revision, "clinical_content_verification")
    _ledger(revision, request_path, request)
    external = tmp_path / "external-requests"
    request_path.parent.rename(external)
    request_path.parent.symlink_to(external, target_is_directory=True)
    linked_path = request_path.parent / request_path.name
    findings, evidence = validate_verifications(revision, request_paths=[linked_path])
    assert any(item.get("code") == "verification_request_noncanonical_path" for item in findings)
    assert evidence == {}


def test_symlinked_ledger_parent_is_not_canonical_authority(tmp_path):
    revision = tmp_path / "r-test"
    request_path, request = _request(revision, "clinical_content_verification")
    _ledger(revision, request_path, request)
    ledger_parent = revision / "request-ledger"
    external = tmp_path / "external-ledgers"
    ledger_parent.rename(external)
    ledger_parent.symlink_to(external, target_is_directory=True)
    findings, evidence = validate_verifications(revision, request_paths=[request_path])
    assert any(item.get("code") == "verification_request_ledger_missing" for item in findings)
    assert evidence == {}


def test_symlinked_revision_ancestor_is_not_canonical_authority(tmp_path):
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    revision = linked_parent / "r-test"
    request_path, request = _request(revision, "clinical_content_verification")
    _ledger(revision, request_path, request)
    findings, evidence = validate_verifications(revision, request_paths=[request_path])
    assert any(item.get("code") == "verification_request_noncanonical_path" for item in findings)
    assert evidence == {}


def test_blocked_visual_response_with_unbound_page_is_not_terminal(tmp_path):
    revision = tmp_path / "r-test"
    request_path, request = _request(revision, "rendered_page_visual_verification")
    _ledger(revision, request_path, request)
    response = {
        "schema_version": RESPONSE_SCHEMA,
        "request_id": request["request_id"],
        "request_sha256": request["request_sha256"],
        "task": request["task"],
        "revision_id": request["revision_id"],
        "producer": {"model_id": "model", "reviewer_id": "reviewer"},
        "status": "blocked",
        "findings": [{
            "issue": "Unbound page.", "artifact": "protocol", "page": 99,
            "check": "clipping", "element": "Heading",
        }],
        "page_assessments": [],
    }
    _write_json(revision / request["response_path"], response)
    assert verification_response_is_terminal(revision, request_path) is False


def test_symlinked_response_parent_is_not_terminal(tmp_path):
    revision = tmp_path / "r-test"
    request_path, request = _request(revision, "rendered_page_visual_verification")
    _ledger(revision, request_path, request)
    response_path = _response(revision, request)
    response_parent = response_path.parent
    external = tmp_path / "external-responses"
    response_parent.rename(external)
    response_parent.symlink_to(external, target_is_directory=True)
    assert verification_response_is_terminal(revision, request_path) is False
    assert verification_response_is_complete(revision, request_path) is False


def test_symlinked_rendered_artifact_parent_is_stale(tmp_path):
    revision = tmp_path / "r-test"
    request_path, request = _request(revision, "rendered_page_visual_verification")
    _ledger(revision, request_path, request)
    _response(revision, request)
    rendered = revision / "rendered"
    external = tmp_path / "external-rendered"
    rendered.rename(external)
    rendered.symlink_to(external, target_is_directory=True)
    findings, _ = validate_verifications(revision, request_paths=[request_path])
    assert any("stale" in item.get("issue", "").casefold() for item in findings)


def test_response_originated_recovery_requires_bound_response_and_producer(tmp_path):
    revision = tmp_path / "r-test"
    reference, request = _canonical_recovery_content_request(revision)
    findings = verification_recovery_request_findings(
        revision, request["request_id"], expected_task="clinical_content_verification",
        current_review_set=1, reference=reference, render_report={},
        bound_artifact="icf", section_target_ids={"icf.procedures"},
        allow_missing_response=False,
    )
    assert findings[0]["code"] == "verification_response_missing"


def test_fabricated_recovery_finding_not_in_response_is_rejected(tmp_path):
    revision = tmp_path / "r-test"
    reference, request = _canonical_recovery_content_request(revision)
    _write_json(revision / request["response_path"], {
        "schema_version": RESPONSE_SCHEMA,
        "request_id": request["request_id"],
        "request_sha256": request["request_sha256"],
        "task": request["task"],
        "revision_id": request["revision_id"],
        "producer": {"model_id": "model", "reviewer_id": "reviewer"},
        "status": "blocked",
        "findings": [{"issue": "A different finding.", "target_ids": ["icf.risks"]}],
    })
    fabricated_source = {
        "issue": "Fabricated finding.", "target_ids": ["icf.procedures"],
        "artifact": "icf", "unexpected_authority": "forged",
    }
    fabricated = {
        "issue": "Fabricated finding.", "target_ids": ["icf.procedures"],
        "artifact": "icf", "recovery_class": "drafting_defect",
        "verification_source_finding": fabricated_source,
    }
    findings = verification_recovery_request_findings(
        revision, request["request_id"], expected_task="clinical_content_verification",
        current_review_set=1, reference=reference, render_report={},
        bound_artifact="icf", section_target_ids={"icf.procedures"},
        originating_finding=fabricated,
    )
    assert findings[0]["code"] == "verification_response_finding_mismatch"
