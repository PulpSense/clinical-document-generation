import json
import hashlib
import shutil
from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from pypdf import PdfWriter

from contracts import batch_plan, contracted_template_bundle
from drafting import accepted_cross_section_duplicate_findings, accepted_draft, create_drafting_request, governing_resources, ingest_responses, pending_requests, recorded_acceptance_response, response_template, retry_attempts, schedule_requests, sha256_value, validate_response
from quality import CONTENT_CHECKS, RESPONSE_SCHEMA, VISUAL_CHECKS, create_verification_requests, deterministic_content_check, validate_verifications, verification_request_sha256
from contracts import icf_retained_sections
from rendering import audit_docx
from workflow import approve, generate, prepare, validate
import workflow


ROOT = Path(__file__).resolve().parents[1]


def test_single_artifact_retrospective_verification_omits_cross_document_checks(tmp_path):
    revision_dir = tmp_path / "r-retrospective"
    revision_dir.mkdir()

    request_paths = create_verification_requests(
        revision_dir,
        {"meta": {"study_type": "Retrospective"}},
        {"artifacts": []},
    )
    content_request = json.loads(request_paths[0].read_text(encoding="utf-8"))

    assert content_request["task"] == "clinical_content_verification"
    assert content_request["cross_document_checks"] == []
    assert "assess every cross-document check" not in content_request["instructions"].casefold()


def _require_renderer():
    assert workflow.renderer() is not None


def acceptance_verification(request):
    response = {
        "schema_version": RESPONSE_SCHEMA,
        "request_id": request["request_id"],
        "request_sha256": request["request_sha256"],
        "task": request["task"],
        "producer": {"model_id": "TestAcceptanceVerifier/v1"},
        "status": "passed",
        "findings": [],
    }
    if request["task"] == "rendered_page_visual_verification":
        response["page_assessments"] = [
            {
                "artifact": artifact["artifact"],
                "page": page["page"],
                "sha256": page["sha256"],
                "status": "passed",
                "checks": list(VISUAL_CHECKS),
            }
            for artifact in request.get("artifacts", [])
            for page in artifact.get("pages", [])
        ]
    else:
        response["section_assessments"] = [
            {
                "artifact": item["artifact"],
                "section_id": item["section_id"],
                "status": "passed",
                "checks": list(CONTENT_CHECKS),
            }
            for item in request.get("sections", [])
        ]
        response["cross_document_assessments"] = [
            {"check": check, "status": "passed"}
            for check in request.get("cross_document_checks", [])
        ]
    return response


def fixture():
    return json.loads((ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text(encoding="utf-8"))


def test_drafting_request_is_scoped_and_hash_bound(tmp_path):
    reference = fixture(); batch = batch_plan("Prospective")[0]
    path = create_drafting_request(repo_root=ROOT, revision_dir=tmp_path, revision_id="r-test", reference=reference, batch=batch, attempts={item: 1 for item in batch.section_ids}, wave="initial")
    request = json.loads(path.read_text(encoding="utf-8"))
    assert (tmp_path / request["response_path"]).parent.is_dir()
    assert set(request["approved_source"]) <= set(batch.field_families)
    assert "template_fields" not in request["approved_source"]
    response = recorded_acceptance_response(request)
    accepted, findings = validate_response(request, response)
    assert accepted and not findings


def test_governed_drafting_response_rejects_duplicate_prose_across_contracts(tmp_path):
    reference = fixture()
    batch = next(item for item in batch_plan("Prospective") if item.batch_id == "protocol-operations")
    path = create_drafting_request(
        repo_root=ROOT,
        revision_dir=tmp_path,
        revision_id="r-duplicate-reproduction",
        reference=reference,
        batch=batch,
        attempts={item: 1 for item in batch.section_ids},
        wave="initial",
    )
    request = json.loads(path.read_text(encoding="utf-8"))
    assert any(
        "exact sentence or paragraph" in item and "exact list item" in item
        for item in request["constraints"]
    )
    response = recorded_acceptance_response(request)
    visits = next(item for item in response["section_results"] if item["section_id"] == "study-procedure.visits")
    evaluation = next(item for item in response["section_results"] if item["section_id"] == "evaluation-procedures")
    evaluation["paragraphs"] = json.loads(json.dumps(visits["paragraphs"]))
    evaluation["lists"] = json.loads(json.dumps(visits["lists"]))

    accepted, findings = validate_response(request, response)

    assert accepted is not None
    assert {
        item["section_id"] for item in accepted["drafts"]
    }.isdisjoint({"evaluation-procedures", "study-procedure.visits"})
    assert {
        item["section_id"] for item in accepted["drafts"]
    } == set(batch.section_ids) - {"evaluation-procedures", "study-procedure.visits"}
    duplicate_findings = [item for item in findings if "duplicated across separately contracted" in item["issue"]]
    assert duplicate_findings
    assert duplicate_findings[0]["target_ids"] == ["evaluation-procedures", "study-procedure.visits"]


def test_duplicate_ingestion_preserves_both_retry_targets_and_accepts_the_rest(tmp_path):
    reference = fixture()
    batch = next(item for item in batch_plan("Prospective") if item.batch_id == "protocol-operations")
    request_path = create_drafting_request(
        repo_root=ROOT,
        revision_dir=tmp_path,
        revision_id="r-duplicate-local-retry",
        reference=reference,
        batch=batch,
        attempts={item: 1 for item in batch.section_ids},
        wave="initial",
    )
    request = json.loads(request_path.read_text(encoding="utf-8"))
    response = recorded_acceptance_response(request)
    visits = next(item for item in response["section_results"] if item["section_id"] == "study-procedure.visits")
    evaluation = next(item for item in response["section_results"] if item["section_id"] == "evaluation-procedures")
    evaluation["paragraphs"] = json.loads(json.dumps(visits["paragraphs"]))
    evaluation["lists"] = json.loads(json.dumps(visits["lists"]))
    response_path = tmp_path / request["response_path"]
    response_path.parent.mkdir(parents=True, exist_ok=True)
    response_path.write_text(json.dumps(response), encoding="utf-8")

    governing = governing_resources(ROOT, reference)
    findings = ingest_responses(tmp_path, governing)

    assert findings[0]["target_ids"] == ["evaluation-procedures", "study-procedure.visits"]
    accepted_ids = {
        section_id for section_id in batch.section_ids
        if accepted_draft(tmp_path, section_id, governing) is not None
    }
    assert accepted_ids == set(batch.section_ids) - {"evaluation-procedures", "study-procedure.visits"}
    attempts, exhausted = retry_attempts(findings, {})
    assert exhausted == []
    created = schedule_requests(
        repo_root=ROOT,
        revision_dir=tmp_path,
        revision_id="r-duplicate-local-retry",
        reference=reference,
        attempts=attempts,
        wave="retry",
        findings=findings,
    )
    retry = next(
        json.loads(path.read_text(encoding="utf-8"))
        for path in created
        if json.loads(path.read_text(encoding="utf-8"))["batch_id"] == batch.batch_id
    )
    assert [item["section_id"] for item in retry["section_contracts"]] == [
        "study-procedure.visits",
        "evaluation-procedures",
    ]


def test_authenticated_cross_batch_duplicate_prose_is_found_before_rendering(tmp_path):
    reference = fixture()
    for batch_id, section_id in (
        ("protocol-foundations", "objectives"),
        ("protocol-operations", "study-procedure.measurements"),
    ):
        batch = next(item for item in batch_plan("Prospective") if item.batch_id == batch_id)
        path = create_drafting_request(
            repo_root=ROOT,
            revision_dir=tmp_path,
            revision_id="r-cross-batch-duplicate",
            reference=reference,
            batch=batch,
            attempts={item: 1 for item in batch.section_ids},
            wave="initial",
        )
        request = json.loads(path.read_text(encoding="utf-8"))
        response = recorded_acceptance_response(request)
        target = next(item for item in response["section_results"] if item["section_id"] == section_id)
        target["paragraphs"].append({
            "text": "The approved hypothesis states that prospective monitoring will describe recovery.",
            "evidence_refs": ["source:study.hypothesis"],
            "boilerplate_refs": [],
        })
        response_path = tmp_path / request["response_path"]
        response_path.parent.mkdir(parents=True, exist_ok=True)
        response_path.write_text(json.dumps(response), encoding="utf-8")

    governing = governing_resources(ROOT, reference)
    assert ingest_responses(tmp_path, governing) == []

    findings = accepted_cross_section_duplicate_findings(tmp_path, reference, governing)

    assert len(findings) == 1
    assert findings[0]["target_ids"] == ["objectives", "study-procedure.measurements"]
    assert findings[0]["recovery_class"] == "drafting_defect"
    assert findings[0]["action"] == "retry_drafting_target"


def test_cross_batch_duplicate_routes_localized_retry_before_candidate_render(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    reference_path = run_dir / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    reference_path.write_text(json.dumps(fixture()), encoding="utf-8")
    assert prepare(run_dir)["status"] == "awaiting_approval"
    approval = approve(run_dir, approved_by="reviewer")
    revision_dir = run_dir / "revisions" / approval["revision_id"]
    shared_text = "The approved hypothesis states that prospective monitoring will describe recovery."

    drafting = generate(run_dir)
    for relative in drafting["requests"]:
        request = json.loads((revision_dir / relative).read_text(encoding="utf-8"))
        response = recorded_acceptance_response(request)
        for result in response.get("section_results", []):
            if result["section_id"] in {"objectives", "study-procedure.measurements"}:
                result["paragraphs"].append({
                    "text": shared_text,
                    "evidence_refs": ["source:study.hypothesis"],
                    "boilerplate_refs": [],
                })
        response_path = revision_dir / request["response_path"]
        response_path.parent.mkdir(parents=True, exist_ok=True)
        response_path.write_text(json.dumps(response), encoding="utf-8")

    dependent = generate(run_dir)
    for relative in dependent["requests"]:
        request = json.loads((revision_dir / relative).read_text(encoding="utf-8"))
        response_path = revision_dir / request["response_path"]
        response_path.parent.mkdir(parents=True, exist_ok=True)
        response_path.write_text(json.dumps(recorded_acceptance_response(request)), encoding="utf-8")

    monkeypatch.setattr(
        workflow,
        "render_documents",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("rendered too early")),
    )
    result = generate(run_dir)

    assert result["status"] == "awaiting_hermes"
    assert result["stage"] == "drafting_retry"
    assert {item["field"] for item in result["findings"]} == {"study-procedure.measurements"}
    assert not (revision_dir / "candidate").exists()


def test_fixed_boilerplate_outcome_cannot_bypass_duplicate_prose_gate(tmp_path):
    reference = fixture()
    batch = next(item for item in batch_plan("Prospective") if item.batch_id == "protocol-operations")
    path = create_drafting_request(
        repo_root=ROOT,
        revision_dir=tmp_path,
        revision_id="r-duplicate-boilerplate-bypass",
        reference=reference,
        batch=batch,
        attempts={item: 1 for item in batch.section_ids},
        wave="initial",
    )
    request = json.loads(path.read_text(encoding="utf-8"))
    response = recorded_acceptance_response(request)
    visits = next(item for item in response["section_results"] if item["section_id"] == "study-procedure.visits")
    evaluation = next(item for item in response["section_results"] if item["section_id"] == "evaluation-procedures")
    evaluation["paragraphs"] = json.loads(json.dumps(visits["paragraphs"]))
    evaluation["lists"] = json.loads(json.dumps(visits["lists"]))
    visits["outcome"] = "fixed_boilerplate"
    evaluation["outcome"] = "fixed_boilerplate"

    accepted, findings = validate_response(request, response)

    assert accepted is None
    assert {
        item["field"]
        for item in findings
        if "does not authorize the fixed_boilerplate outcome" in item["issue"]
    } == {"study-procedure.visits", "evaluation-procedures"}
    assert any("duplicated across separately contracted" in item["issue"] for item in findings)


def test_fixed_boilerplate_outcome_rejects_case_mutated_contract_text(tmp_path):
    reference = fixture()
    batch = next(item for item in batch_plan("Prospective") if item.batch_id == "protocol-operations")
    path = create_drafting_request(
        repo_root=ROOT,
        revision_dir=tmp_path,
        revision_id="r-mutated-boilerplate",
        reference=reference,
        batch=batch,
        attempts={item: 1 for item in batch.section_ids},
        wave="initial",
    )
    request = json.loads(path.read_text(encoding="utf-8"))
    response = recorded_acceptance_response(request)
    consent = next(item for item in response["section_results"] if item["section_id"] == "study-procedure.consent")
    assert consent["outcome"] == "fixed_boilerplate"
    consent["paragraphs"][0]["text"] = consent["paragraphs"][0]["text"].upper()

    accepted, findings = validate_response(request, response)

    assert accepted is None
    assert any(
        item["field"] == "study-procedure.consent"
        and "not its exact authorized boilerplate" in item["issue"]
        for item in findings
    )


def test_authorized_boilerplate_does_not_hide_an_unauthorized_cross_section_copy(tmp_path):
    reference = fixture()
    batch = next(item for item in batch_plan("Prospective") if item.batch_id == "protocol-foundations")
    path = create_drafting_request(
        repo_root=ROOT,
        revision_dir=tmp_path,
        revision_id="r-asymmetric-boilerplate-copy",
        reference=reference,
        batch=batch,
        attempts={item: 1 for item in batch.section_ids},
        wave="initial",
    )
    request = json.loads(path.read_text(encoding="utf-8"))
    response = recorded_acceptance_response(request)
    bias_contract = next(item for item in request["section_contracts"] if item["section_id"] == "study-design.bias")
    introduction = next(item for item in response["section_results"] if item["section_id"] == "introduction")
    introduction["paragraphs"].append({
        "text": bias_contract["fixed_boilerplate"][0]["text"],
        "evidence_refs": ["source:study.background"],
        "boilerplate_refs": [],
    })

    accepted, findings = validate_response(request, response)

    assert accepted is not None
    assert {
        item["section_id"] for item in accepted["drafts"]
    }.isdisjoint({"introduction", "study-design.bias"})
    duplicate = next(item for item in findings if "duplicated across separately contracted" in item["issue"])
    assert duplicate["target_ids"] == ["introduction", "study-design.bias"]


def test_mutated_drafting_request_with_stale_hash_is_blocked_before_response_ingestion(tmp_path):
    reference = fixture()
    batch = batch_plan("Prospective")[0]
    path = create_drafting_request(
        repo_root=ROOT,
        revision_dir=tmp_path,
        revision_id="r-integrity",
        reference=reference,
        batch=batch,
        attempts={item: 1 for item in batch.section_ids},
        wave="initial",
    )
    request = json.loads(path.read_text(encoding="utf-8"))
    request["approved_source"]["study"]["title"] = "Injected unapproved title"
    path.write_text(json.dumps(request), encoding="utf-8")
    response_path = tmp_path / request["response_path"]
    response_path.parent.mkdir(parents=True, exist_ok=True)
    response_path.write_text(json.dumps(recorded_acceptance_response(request)), encoding="utf-8")

    findings = ingest_responses(tmp_path, governing_resources(ROOT, reference))

    assert any(item["category"] == "request-integrity" for item in findings)
    assert not (tmp_path / "hermes/accepted-requests" / path.name).exists()


def test_mutated_drafting_request_cannot_be_resigned_with_unapproved_content(tmp_path):
    reference = fixture()
    batch = batch_plan("Prospective")[0]
    path = create_drafting_request(
        repo_root=ROOT,
        revision_dir=tmp_path,
        revision_id="r-resigned-integrity",
        reference=reference,
        batch=batch,
        attempts={item: 1 for item in batch.section_ids},
        wave="initial",
    )
    request = json.loads(path.read_text(encoding="utf-8"))
    request["approved_source"]["study"]["title"] = "Injected unapproved title"
    request.pop("request_sha256")
    request["request_sha256"] = sha256_value(request)
    path.write_text(json.dumps(request), encoding="utf-8")
    ledger = tmp_path / "request-ledger" / f"{request['request_id']}.json"
    ledger.write_text(json.dumps({
        "request_id": request["request_id"],
        "request_sha256": request["request_sha256"],
    }), encoding="utf-8")
    response_path = tmp_path / request["response_path"]
    response_path.parent.mkdir(parents=True, exist_ok=True)
    response_path.write_text(json.dumps(recorded_acceptance_response(request)), encoding="utf-8")

    findings = ingest_responses(tmp_path, governing_resources(ROOT, reference))

    assert any(item["category"] == "request-integrity" for item in findings)
    assert not (tmp_path / "hermes/accepted-requests" / path.name).exists()


def test_recorded_acceptance_spells_out_the_screening_interval_with_units(tmp_path):
    reference = fixture()
    batch = next(item for item in batch_plan("Prospective") if item.batch_id == "protocol-foundations")
    path = create_drafting_request(
        repo_root=ROOT,
        revision_dir=tmp_path,
        revision_id="r-screening",
        reference=reference,
        batch=batch,
        attempts={item: 1 for item in batch.section_ids},
        wave="initial",
    )
    response = recorded_acceptance_response(json.loads(path.read_text(encoding="utf-8")))
    inclusion = next(item for item in response["section_results"] if item["section_id"] == "subjects.inclusion")
    visible = "\n".join(
        [paragraph["text"] for paragraph in inclusion["paragraphs"]]
        + [item for group in inclusion["lists"] for item in group["items"]]
    )

    assert "30 days" in visible


def test_sparse_complete_approval_cannot_create_post_approval_source_questions(tmp_path, monkeypatch):
    _require_renderer()
    reference = fixture()
    reference["risks_benefits"] = {
        "compensation_or_reimbursement": reference["risks_benefits"]["compensation_or_reimbursement"]
    }
    run_dir = tmp_path / "run"
    reference_path = run_dir / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    reference_path.write_text(json.dumps(reference), encoding="utf-8")

    assert prepare(run_dir)["status"] == "awaiting_approval"
    approval = approve(run_dir, approved_by="reviewer")
    assert approval["status"] == "passed"

    result = generate(run_dir)
    assert result["status"] == "awaiting_hermes"
    revision_dir = run_dir / "revisions" / approval["revision_id"]
    requests = [json.loads((revision_dir / relative).read_text(encoding="utf-8")) for relative in result["requests"]]
    serialized = json.dumps(requests).casefold()

    assert "source_gap" not in serialized
    assert "source question" not in serialized
    risk_benefit_contracts = {
        section["section_id"]: section
        for request in requests
        for section in request.get("section_contracts", [])
        if section["section_id"] in {"risks-benefits.risks", "risks-benefits.benefits", "icf.risks", "icf.benefits"}
    }
    assert set(risk_benefit_contracts) == {"risks-benefits.risks", "risks-benefits.benefits", "icf.risks", "icf.benefits"}
    assert all(contract["fixed_boilerplate"] for contract in risk_benefit_contracts.values())


def test_desktop_drafting_requests_bind_the_complete_contracted_template_bundle(tmp_path, monkeypatch):
    _require_renderer()
    reference = fixture()
    run_dir = tmp_path / "run"
    reference_path = run_dir / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    reference_path.write_text(json.dumps(reference), encoding="utf-8")

    assert prepare(run_dir)["status"] == "awaiting_approval"
    assert approve(run_dir, approved_by="reviewer")["status"] == "passed"
    result = generate(run_dir)

    assert result["status"] == "awaiting_hermes"
    revision_dir = run_dir / "revisions" / result["revision_id"]
    requests = [
        json.loads((revision_dir / relative).read_text(encoding="utf-8"))
        for relative in result["requests"]
    ]
    expected_bundle = contracted_template_bundle(ROOT, reference)
    for request in requests:
        governing = request["governing_resources"]
        assert governing["contracted_template_bundle"] == expected_bundle
        assert "template_sha256" not in governing
        assert "boilerplate_sha256" not in governing


def test_incomplete_contracted_template_bundle_blocks_before_drafting(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    reference_path = run_dir / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    reference_path.write_text(json.dumps(fixture()), encoding="utf-8")
    assert prepare(run_dir)["status"] == "awaiting_approval"
    assert approve(run_dir, approved_by="reviewer")["status"] == "passed"

    broken_release = tmp_path / "broken-release"
    shutil.copytree(ROOT / "assets", broken_release / "assets")
    shutil.copytree(ROOT / "references", broken_release / "references")
    scripts = broken_release / "scripts"
    scripts.mkdir()
    (broken_release / "assets/client-templates/docx/prospective-protocol.template.docx").unlink()
    monkeypatch.setattr(workflow, "SCRIPT_DIR", scripts)

    result = generate(run_dir)

    assert result["status"] == "blocked"
    assert result["stage"] == "contracted_template_bundle"
    assert len(result["findings"]) == 1
    assert result["findings"][0]["field"] == "contracted_template_bundle"
    assert not list((run_dir / "revisions").glob("*/hermes/requests/*.json"))


def test_awaiting_hermes_exposes_path_only_response_bound_handoffs(tmp_path, monkeypatch):
    _require_renderer()
    run_dir = tmp_path / "run"
    reference_path = run_dir / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    reference_path.write_text(json.dumps(fixture()), encoding="utf-8")
    assert prepare(run_dir)["status"] == "awaiting_approval"
    approval = approve(run_dir, approved_by="reviewer")

    result = generate(run_dir)

    revision_dir = run_dir / "revisions" / approval["revision_id"]
    expected = []
    for relative in result["requests"]:
        request = json.loads((revision_dir / relative).read_text(encoding="utf-8"))
        expected.append({
            "request_path": relative,
            "response_path": request["response_path"],
            "task": request["task"],
            "batch_id": request["batch_id"],
        })
    assert result["status"] == "awaiting_hermes"
    assert result["handoffs"] == expected


def test_environment_failure_retains_a_complete_candidate_built_before_render_assurance(tmp_path, monkeypatch):
    reference = json.loads((ROOT / "tests/fixtures/retrospective-acceptance-source.json").read_text(encoding="utf-8"))
    run_dir = tmp_path / "run"
    reference_path = run_dir / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    reference_path.write_text(json.dumps(reference), encoding="utf-8")
    assert prepare(run_dir)["status"] == "awaiting_approval"
    approval = approve(run_dir, approved_by="reviewer")

    drafting = generate(run_dir)
    revision_dir = run_dir / "revisions" / approval["revision_id"]
    for relative in drafting["requests"]:
        request = json.loads((revision_dir / relative).read_text(encoding="utf-8"))
        response = recorded_acceptance_response(request)
        response_path = revision_dir / request["response_path"]
        response_path.parent.mkdir(parents=True, exist_ok=True)
        response_path.write_text(json.dumps(response), encoding="utf-8")

    monkeypatch.setattr(workflow, "render_assurance", lambda *_args, **_kwargs: {
        "schema_version": "render-assurance/v1",
        "status": "blocked",
        "fonts": {},
        "font_substitutions": {},
        "candidate": {"files": []},
        "render": {"status": "blocked", "renderer_attempts": [], "page_renderer_attempts": [], "findings": []},
        "findings": [{"category": "renderer", "field": "renderer", "recovery_class": "adapter_fault", "action": "advance_adapter", "issue": "fallback stack unavailable"}],
        "diagnostic": {"recovery_class": "adapter_fault", "action": "advance_adapter", "outcome": "adapters_exhausted", "candidate_disposition": "preserved", "office_attempts": [], "page_attempts": []},
    })

    result = generate(run_dir)

    assert result["status"] == "blocked"
    assert result["stage"] == "render_assurance"
    assert (revision_dir / "candidate/protocol.docx").is_file()
    assert [item["path"] for item in result["candidate_outputs"]] == ["candidate/protocol.docx"]
    assert result["client_outputs"] == []


def test_repeated_adapter_exhaustion_reuses_candidate_without_drafting_or_regeneration(tmp_path, monkeypatch):
    reference = json.loads((ROOT / "tests/fixtures/retrospective-acceptance-source.json").read_text(encoding="utf-8"))
    run_dir = tmp_path / "run"
    reference_path = run_dir / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    reference_path.write_text(json.dumps(reference), encoding="utf-8")
    assert prepare(run_dir)["status"] == "awaiting_approval"
    approval = approve(run_dir, approved_by="reviewer")
    drafting = generate(run_dir)
    revision_dir = run_dir / "revisions" / approval["revision_id"]
    for relative in drafting["requests"]:
        request = json.loads((revision_dir / relative).read_text(encoding="utf-8"))
        response_path = revision_dir / request["response_path"]
        response_path.parent.mkdir(parents=True, exist_ok=True)
        response_path.write_text(json.dumps(recorded_acceptance_response(request)), encoding="utf-8")

    renders = 0
    real_render_documents = workflow.render_documents

    def counted_render(*args, **kwargs):
        nonlocal renders
        renders += 1
        return real_render_documents(*args, **kwargs)

    def exhausted(*_args, **_kwargs):
        candidate = revision_dir / "candidate/protocol.docx"
        return {
            "schema_version": "render-assurance/v1",
            "status": "blocked",
            "fonts": {},
            "font_substitutions": {},
            "candidate": {"files": [{"path": "candidate/protocol.docx", "sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(), "bytes": candidate.stat().st_size}]},
            "render": {"status": "blocked", "renderer_attempts": [], "page_renderer_attempts": [], "findings": []},
            "findings": [{"category": "renderer", "field": "rendering", "recovery_class": "adapter_fault", "action": "advance_adapter", "issue": "all adapters exhausted"}],
            "diagnostic": {"recovery_class": "adapter_fault", "action": "advance_adapter", "outcome": "adapters_exhausted", "candidate_disposition": "preserved", "office_attempts": [], "page_attempts": []},
        }

    monkeypatch.setattr(workflow, "render_documents", counted_render)
    monkeypatch.setattr(workflow, "render_assurance", exhausted)

    first = generate(run_dir)
    candidate_hash = hashlib.sha256((revision_dir / "candidate/protocol.docx").read_bytes()).hexdigest()
    second = generate(run_dir)
    state = json.loads(reference_path.read_text(encoding="utf-8"))["generation"]

    assert first["stage"] == second["stage"] == "render_assurance"
    assert first["repair_report"] == second["repair_report"] == "reference/render-assurance-diagnostic.md"
    assert hashlib.sha256((revision_dir / "candidate/protocol.docx").read_bytes()).hexdigest() == candidate_hash
    assert renders == 1
    assert state["attempts"] == {}


def test_generation_routes_legacy_missing_prs_study_type_to_source_review(tmp_path):
    run_dir = tmp_path / "run"
    reference_path = run_dir / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    reference_path.write_text(json.dumps(fixture()), encoding="utf-8")
    assert prepare(run_dir)["status"] == "awaiting_approval"
    approval = approve(run_dir, approved_by="reviewer")
    revision_dir = run_dir / "revisions" / approval["revision_id"]

    working = json.loads(reference_path.read_text(encoding="utf-8"))
    approved = json.loads((revision_dir / "approved-reference.json").read_text(encoding="utf-8"))
    working["regulatory"]["prs"].pop("study_type")
    approved["regulatory"]["prs"].pop("study_type")
    (revision_dir / "approved-reference.json").write_text(json.dumps(approved), encoding="utf-8")
    working["approval"]["approved_reference_sha256"] = hashlib.sha256(
        (revision_dir / "approved-reference.json").read_bytes()
    ).hexdigest()
    reference_path.write_text(json.dumps(working), encoding="utf-8")

    result = generate(run_dir)

    report = (run_dir / result["repair_report"]).read_text(encoding="utf-8")
    assert result["status"] == "blocked"
    assert result["stage"] == "approval_gate"
    assert result["findings"] == [{
        "category": "source-evidence",
        "field": "regulatory.prs.study_type",
        "issue": "Required Source Input is missing.",
        "required": "PRS study type (Observational or Interventional)",
    }]
    assert "## regulatory.prs.study_type" in report
    assert not (revision_dir / "attempts").exists()


def test_source_gap_response_is_a_retryable_drafting_failure_not_a_reviewer_question(tmp_path):
    reference = fixture()
    batch = next(item for item in batch_plan("Prospective") if item.batch_id == "icf-narrative")
    path = create_drafting_request(
        repo_root=ROOT,
        revision_dir=tmp_path,
        revision_id="r-test",
        reference=reference,
        batch=batch,
        attempts={item: 1 for item in batch.section_ids},
        wave="initial",
    )
    request = json.loads(path.read_text(encoding="utf-8"))
    response = recorded_acceptance_response(request)
    risk = next(item for item in response["section_results"] if item["section_id"] == "icf.risks")
    risk.update({"outcome": "source_gap", "paragraphs": [], "question": "Supply more information."})

    _, findings = validate_response(request, response)

    risk_findings = [item for item in findings if item["field"] == "icf.risks"]
    assert risk_findings
    assert all(item["category"] == "drafting" for item in risk_findings)
    assert "ask" not in json.dumps(risk_findings).casefold()


def test_legacy_question_capable_handoff_is_ignored_after_contract_upgrade(tmp_path):
    reference = fixture()
    batch = batch_plan("Prospective")[0]
    current_path = create_drafting_request(
        repo_root=ROOT,
        revision_dir=tmp_path,
        revision_id="r-test",
        reference=reference,
        batch=batch,
        attempts={item: 1 for item in batch.section_ids},
        wave="initial",
    )
    legacy = json.loads(current_path.read_text(encoding="utf-8"))
    legacy.update({
        "schema_version": "hermes-request/v1",
        "prompt_version": "section-drafting-v1",
        "request_id": "legacy-question-capable-request",
        "response_path": "hermes/responses/legacy-question-capable-request.json",
    })
    legacy["governing_resources"]["prompt_version"] = "section-drafting-v1"
    legacy.pop("request_sha256")
    legacy["request_sha256"] = sha256_value(legacy)
    legacy_path = tmp_path / "hermes/requests/legacy-question-capable-request.json"
    legacy_path.write_text(json.dumps(legacy), encoding="utf-8")
    legacy_response = tmp_path / legacy["response_path"]
    legacy_response.parent.mkdir(parents=True, exist_ok=True)
    legacy_response.write_text(json.dumps({"outcome": "source_gap", "question": "Supply more information."}), encoding="utf-8")

    expected = governing_resources(ROOT, reference)
    assert pending_requests(tmp_path, expected) == [current_path]
    assert ingest_responses(tmp_path, expected) == []


def test_prepare_requires_editable_source_truth_file_delivery(tmp_path):
    run_dir = tmp_path / "run"
    reference_path = run_dir / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    reference_path.write_text(json.dumps(fixture()), encoding="utf-8")

    result = prepare(run_dir)
    delivery = result["review_delivery"]
    source = Path(delivery["absolute_path"])

    assert result["status"] == "awaiting_approval"
    assert delivery["mode"] == "file"
    assert delivery["path"] == result["source_of_truth"]
    assert delivery["mime_type"] == "text/markdown"
    assert delivery["editable"] is True
    assert delivery["inline_chat"] is False
    assert source.is_file()
    assert source.read_text(encoding="utf-8").count("<!-- field:") >= 35


def test_prepare_defaults_editable_document_control_date_without_inventing_version(tmp_path):
    reference = fixture()
    reference["meta"].pop("date", None)
    reference["meta"].pop("version", None)
    run_dir = tmp_path / "run"
    reference_path = run_dir / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    reference_path.write_text(json.dumps(reference), encoding="utf-8")

    result = prepare(run_dir, today=date(2026, 8, 24))
    prepared = json.loads(reference_path.read_text(encoding="utf-8"))
    source = (run_dir / result["source_of_truth"]).read_text(encoding="utf-8")

    assert prepared["meta"]["date"] == "24 Aug 2026"
    assert prepared["meta"]["version"] == ""
    assert "<!-- field: meta.date -->\n24 Aug 2026\n<!-- /field -->" in source
    assert "<!-- field: meta.version -->\n\n<!-- /field -->" in source
    assert "<!-- field: meta.icf_template -->" in source


def test_generation_resource_change_cannot_overwrite_an_approved_revision(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    reference_path = run_dir / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    reference_path.write_text(json.dumps(fixture()), encoding="utf-8")
    prepare(run_dir)
    approval = approve(run_dir, approved_by="reviewer")
    original = workflow.governing_resources

    def changed_resources(repo_root, reference, **kwargs):
        resources = original(repo_root, reference, **kwargs)
        resources["prompt_version"] = "changed-after-approval"
        return resources

    monkeypatch.setattr(workflow, "governing_resources", changed_resources)

    result = generate(run_dir)

    assert result["status"] == "blocked"
    assert result["stage"] == "approval_gate"
    assert approval["revision_id"] in json.dumps(json.loads(reference_path.read_text(encoding="utf-8")))


def test_prepare_exposes_optional_clinical_and_prs_fields_in_the_editable_source(tmp_path):
    reference = fixture()
    for path in ("condition",):
        reference["study"].pop(path, None)
    run_dir = tmp_path / "run"
    reference_path = run_dir / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    reference_path.write_text(json.dumps(reference), encoding="utf-8")

    result = prepare(run_dir, today=date(2026, 8, 24))
    source = (run_dir / result["source_of_truth"]).read_text(encoding="utf-8")

    assert "<!-- field: study.condition -->" in source
    assert "<!-- field: risks_benefits.costs -->" in source
    assert "<!-- field: risks_benefits.injury_handling -->" in source
    assert "<!-- field: regulatory.prs.time_perspective -->" in source
    assert "<!-- field: regulatory.prs.start_date -->" in source
    assert "<!-- field: regulatory.prs.study_completion_date -->" in source
    assert "<!-- field: statistics.analysis_populations -->" in source
    assert "<!-- field: statistics.missing_data_handling -->" in source
    assert "analysis_method" in source
    assert "description" in source


def test_prepare_derives_prs_study_type_from_unambiguous_design_evidence(tmp_path):
    reference = fixture()
    reference["regulatory"]["prs"].pop("study_type")
    run_dir = tmp_path / "run"
    reference_path = run_dir / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    reference_path.write_text(json.dumps(reference), encoding="utf-8")

    result = prepare(run_dir, today=date(2026, 8, 24))
    prepared = json.loads(reference_path.read_text(encoding="utf-8"))
    source = (run_dir / result["source_of_truth"]).read_text(encoding="utf-8")

    assert result["status"] == "awaiting_approval"
    assert prepared["regulatory"]["prs"]["study_type"] == "Observational"
    assert "<!-- field: regulatory.prs.study_type -->\nObservational\n<!-- /field -->" in source


def test_prepare_reports_missing_prs_study_type_before_approval(tmp_path):
    reference = fixture()
    reference["regulatory"]["prs"].pop("study_type")
    reference["design"]["study_design"] = "Prospective, single-center device study."
    run_dir = tmp_path / "run"
    reference_path = run_dir / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    reference_path.write_text(json.dumps(reference), encoding="utf-8")

    result = prepare(run_dir, today=date(2026, 8, 24))
    report = (run_dir / result["missing_inputs"]).read_text(encoding="utf-8")

    assert result["status"] == "blocked"
    assert result["stage"] == "input_collection"
    assert "## regulatory.prs.study_type" in report
    assert "PRS study type (Observational or Interventional)" in report
    assert not (run_dir / "revisions").exists()


def test_approval_does_not_restore_a_reviewer_cleared_prs_study_type(tmp_path):
    reference = fixture()
    reference["regulatory"]["prs"].pop("study_type")
    run_dir = tmp_path / "run"
    reference_path = run_dir / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    reference_path.write_text(json.dumps(reference), encoding="utf-8")

    prepared = prepare(run_dir, today=date(2026, 8, 24))
    source_path = run_dir / prepared["source_of_truth"]
    source = source_path.read_text(encoding="utf-8")
    source_path.write_text(
        source.replace(
            "<!-- field: regulatory.prs.study_type -->\nObservational\n<!-- /field -->",
            "<!-- field: regulatory.prs.study_type -->\n\n<!-- /field -->",
        ),
        encoding="utf-8",
    )

    result = approve(run_dir, approved_by="reviewer")

    assert result["status"] == "blocked"
    assert any(
        item["field"] == "regulatory.prs.study_type"
        for item in result["findings"]
    )
    assert not (run_dir / "revisions").exists()


def test_protocol_leaf_heading_without_body_content_is_blocked(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/retrospective-acceptance-source.json").read_text(encoding="utf-8"))
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    document = __import__("docx").Document()
    for section in __import__("contracts").protocol_contract("Retrospective"):
        style = "Heading 1" if section.number.count(".") == 1 else "Heading 2"
        document.add_paragraph(f"{section.number} {section.title}", style=style)
        if section.role == "leaf" and section.section_id != "introduction":
            document.add_paragraph(f"Complete source-grounded content for {section.title.lower()} is present in this section.")
    document.save(candidate / "protocol.docx")

    findings = deterministic_content_check(tmp_path, reference)

    assert any(
        item.get("field") == "introduction" and "no substantive content" in item.get("issue", "").casefold()
        for item in findings
    )


def test_unlocalized_protocol_duplicate_stops_as_a_structural_defect(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/retrospective-acceptance-source.json").read_text(encoding="utf-8"))
    run_dir = tmp_path / "run"
    revision = run_dir / "revisions/r-test"
    candidate = revision / "candidate"
    candidate.mkdir(parents=True)
    document = Document()
    document.add_paragraph(reference["study"]["title"])
    repeated = "This repeated paragraph appears before any contracted section heading is recognized."
    document.add_paragraph(repeated)
    document.add_paragraph(repeated)
    for section in __import__("contracts").protocol_contract("Retrospective"):
        style = "Heading 1" if section.number.count(".") == 1 else "Heading 2"
        document.add_paragraph(f"{section.number} {section.title}", style=style)
        if section.role == "leaf":
            document.add_paragraph(f"Complete source-grounded content for {section.title.lower()} is present in this section.")
    document.save(candidate / "protocol.docx")

    findings = deterministic_content_check(revision, reference)
    duplicate = next(item for item in findings if "duplicated in protocol section protocol" in item["issue"])
    reference_path = run_dir / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    reference_path.write_text(json.dumps({"generation": {}}), encoding="utf-8")
    result = workflow._quality_retry(
        run_dir,
        reference_path,
        {"generation": {}},
        reference,
        revision,
        {},
        [duplicate],
        "quality",
    )

    assert (duplicate["recovery_class"], duplicate["action"]) == ("document_structure_defect", "preserve_and_stop")
    assert result["stage"] == "document_structure"


def test_stale_icf_cost_language_uses_the_supported_branch_drafting_target(tmp_path):
    from rendering import render_documents

    reference = fixture()
    render_documents(ROOT, tmp_path, reference, {"protocol": [], "icf": {}, "prs": {}})
    icf_path = tmp_path / "candidate/icf.docx"
    document = Document(icf_path)
    document.add_paragraph("All charges for medical care will be billed to your insurance company.")
    document.save(icf_path)

    findings = deterministic_content_check(tmp_path, reference)
    stale = next(item for item in findings if "all charges for medical care" in item["issue"])

    assert stale["target_ids"] == ["icf.costs"]
    assert (stale["recovery_class"], stale["action"]) == ("drafting_defect", "retry_drafting_target")


def test_complete_bundle_is_part_of_governing_resources():
    resources = governing_resources(ROOT, fixture())
    bundle = resources["contracted_template_bundle"]
    assert "assets/client-templates/prs/clinicaltrials_prs_full_placeholder_template.xml" in bundle["resource_hashes"]
    assert "assets/client-templates/reference/protocol-reference.docx" in bundle["resource_hashes"]
    assert "assets/client-templates/reference/advarra-icf-reference.docx" in bundle["resource_hashes"]
    assert set(resources["implementation_sha256"]) == {
        f"scripts/{name}"
        for name in ("contracts.py", "drafting.py", "prs_xml.py", "quality.py", "rendering.py", "workflow.py")
    }


def test_content_verifier_receives_authorized_boilerplate_and_blank_field_policy(tmp_path):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    for name in ("protocol.docx", "icf.docx", "study.xml"):
        (candidate / name).write_bytes(b"candidate")

    paths = create_verification_requests(tmp_path, fixture(), {"renderer": {}, "artifacts": []})
    content_path = next(path for path in paths if json.loads(path.read_text())["task"] == "clinical_content_verification")
    request = json.loads(content_path.read_text(encoding="utf-8"))

    assert (tmp_path / request["response_path"]).parent.is_dir()
    assert request["authorized_boilerplate"]["version"]
    assert request["authorized_boilerplate"]["sections"]["costs"]
    assert "Do not fail optional fields" in request["instructions"]
    assert "unknown version" in request["instructions"]
    assessed_ids = {item["section_id"] for item in request["sections"] if item["artifact"] == "icf"}
    expected_retained = {section_id for section_id, _title in icf_retained_sections("Prospective", "Advarra")}
    assert expected_retained <= assessed_ids
    assert "icf.introduction" in assessed_ids
    assert "icf.leaving-study" in assessed_ids


def test_visual_verification_is_split_by_document_for_concurrent_review(tmp_path):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    for artifact in ("protocol", "icf"):
        document = Document()
        document.add_paragraph(f"Stable {artifact} content")
        document.save(candidate / f"{artifact}.docx")
    (candidate / "study.xml").write_bytes(b"candidate")
    rendered = tmp_path / "rendered"
    rendered.mkdir()
    artifacts = []
    for artifact, page_count in (("protocol", 11), ("icf", 6)):
        pdf = rendered / f"{artifact}.pdf"
        pdf.write_bytes(f"{artifact}-pdf".encode())
        pages = []
        for page_number in range(1, page_count + 1):
            page = rendered / artifact / f"page-{page_number}.png"
            page.parent.mkdir(parents=True, exist_ok=True)
            page.write_bytes(f"{artifact}-{page_number}".encode())
            pages.append({
                "page": page_number,
                "path": page.relative_to(tmp_path).as_posix(),
                "sha256": hashlib.sha256(page.read_bytes()).hexdigest(),
            })
        docx = candidate / f"{artifact}.docx"
        artifacts.append({
            "artifact": artifact,
            "docx": docx.relative_to(tmp_path).as_posix(),
            "docx_sha256": hashlib.sha256(docx.read_bytes()).hexdigest(),
            "pdf": pdf.relative_to(tmp_path).as_posix(),
            "pdf_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
            "pages": pages,
        })
    render_report = {
        "renderer": {"kind": "test"},
        "artifacts": artifacts,
    }

    paths = create_verification_requests(tmp_path, fixture(), render_report)
    requests = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    visual = [item for item in requests if item["task"] == "rendered_page_visual_verification"]

    assert len(visual) == 2
    assert {item["artifacts"][0]["artifact"] for item in visual} == {"protocol", "icf"}
    assert all(len(item["artifacts"]) == 1 for item in visual)
    assert len({item["response_path"] for item in visual}) == 2
    for request in requests:
        response_path = tmp_path / request["response_path"]
        response_path.parent.mkdir(parents=True, exist_ok=True)
        response_path.write_text(json.dumps(acceptance_verification(request)), encoding="utf-8")

    findings, evidence = validate_verifications(tmp_path)

    assert findings == []
    assert set(evidence) == {item["request_id"] for item in visual} | {"clinical_content_verification"}
    for request in visual:
        assert evidence[request["request_id"]]["artifacts"] == request["artifacts"]

    protocol_artifact = next(item for item in artifacts if item["artifact"] == "protocol")
    protocol_pdf = tmp_path / protocol_artifact["pdf"]
    protocol_page = tmp_path / protocol_artifact["pages"][0]["path"]
    protocol_pdf.write_bytes(b"repaired-protocol-pdf")
    protocol_page.write_bytes(b"repaired-protocol-page")
    protocol_docx = tmp_path / protocol_artifact["docx"]
    formatted = Document(protocol_docx)
    formatted.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
    formatted.save(protocol_docx)
    protocol_artifact["docx_sha256"] = hashlib.sha256(protocol_docx.read_bytes()).hexdigest()
    protocol_artifact["pdf_sha256"] = hashlib.sha256(protocol_pdf.read_bytes()).hexdigest()
    protocol_artifact["pages"][0]["sha256"] = hashlib.sha256(protocol_page.read_bytes()).hexdigest()

    create_verification_requests(tmp_path, fixture(), render_report)

    response_by_artifact = {
        item["artifacts"][0]["artifact"]: tmp_path / item["response_path"]
        for item in visual
    }
    content_response = tmp_path / next(
        item["response_path"] for item in requests if item["task"] == "clinical_content_verification"
    )
    assert not response_by_artifact["protocol"].exists()
    assert response_by_artifact["icf"].is_file()
    assert content_response.is_file()

    content_changed = Document(protocol_docx)
    content_changed.paragraphs[0].text = "Changed protocol content"
    content_changed.save(protocol_docx)
    create_verification_requests(tmp_path, fixture(), render_report)
    assert not content_response.exists()


def test_response_with_wrong_request_hash_is_rejected(tmp_path):
    reference = fixture(); batch = batch_plan("Prospective")[0]
    path = create_drafting_request(repo_root=ROOT, revision_dir=tmp_path, revision_id="r-test", reference=reference, batch=batch, attempts={item: 1 for item in batch.section_ids}, wave="initial")
    request = json.loads(path.read_text(encoding="utf-8")); response = recorded_acceptance_response(request)
    response["request_sha256"] = "wrong"
    accepted, findings = validate_response(request, response)
    assert accepted is None
    assert any(item["field"] == "request_sha256" for item in findings)


def test_none_source_value_is_grounded_by_an_explicit_negative_statement(tmp_path):
    reference = fixture()
    reference["risks_benefits"]["compensation_or_reimbursement"] = "None"
    batch = next(item for item in batch_plan("Prospective") if item.batch_id == "icf-narrative")
    path = create_drafting_request(
        repo_root=ROOT,
        revision_dir=tmp_path,
        revision_id="r-none",
        reference=reference,
        batch=batch,
        attempts={item: 1 for item in batch.section_ids},
        wave="initial",
    )
    request = json.loads(path.read_text(encoding="utf-8"))
    response = recorded_acceptance_response(request)
    payment = next(item for item in response["section_results"] if item["section_id"] == "icf.payment")
    payment["paragraphs"] = [{
        "text": "You will not be paid for taking part in this study.",
        "evidence_refs": ["source:risks_benefits.compensation_or_reimbursement"],
        "boilerplate_refs": [],
    }]

    accepted, findings = validate_response(request, response)

    assert "icf.payment" in {draft["section_id"] for draft in (accepted or {}).get("drafts", [])}
    assert not [item for item in findings if item["field"] == "icf.payment"]


def test_invalid_section_preserves_other_sections_and_increments_once(tmp_path):
    reference = fixture(); batch = batch_plan("Prospective")[0]
    path = create_drafting_request(repo_root=ROOT, revision_dir=tmp_path, revision_id="r-test", reference=reference, batch=batch, attempts={item: 1 for item in batch.section_ids}, wave="initial")
    request = json.loads(path.read_text(encoding="utf-8")); response = recorded_acceptance_response(request)
    failed = response["section_results"][0]["section_id"]
    response["section_results"][0]["paragraphs"][0]["text"] = "Too short"
    accepted, findings = validate_response(request, response)
    assert accepted is not None
    assert failed not in {draft["section_id"] for draft in accepted["drafts"]}
    for finding in findings: finding["target_ids"] = [failed]
    attempts, exhausted = retry_attempts(findings, {})
    assert attempts[failed] == 2
    assert exhausted == []


def test_partial_batch_ingestion_retries_only_the_failed_section(tmp_path):
    reference = fixture()
    batch = batch_plan("Prospective")[0]
    path = create_drafting_request(
        repo_root=ROOT,
        revision_dir=tmp_path,
        revision_id="r-partial-ingest",
        reference=reference,
        batch=batch,
        attempts={item: 1 for item in batch.section_ids},
        wave="initial",
    )
    request = json.loads(path.read_text(encoding="utf-8"))
    response = recorded_acceptance_response(request)
    failed = response["section_results"][0]["section_id"]
    response["section_results"][0]["paragraphs"][0]["text"] = "Too short"
    response_path = tmp_path / request["response_path"]
    response_path.parent.mkdir(parents=True, exist_ok=True)
    response_path.write_text(json.dumps(response), encoding="utf-8")

    findings = ingest_responses(tmp_path, governing_resources(ROOT, reference))
    valid = set(batch.section_ids) - {failed}
    assert valid
    assert all(accepted_draft(tmp_path, section_id, governing_resources(ROOT, reference)) for section_id in valid)
    attempts, exhausted = retry_attempts(findings, {})
    assert exhausted == []
    created = schedule_requests(
        repo_root=ROOT,
        revision_dir=tmp_path,
        revision_id="r-partial-ingest",
        reference=reference,
        attempts=attempts,
        wave="retry",
        findings=findings,
    )
    retried_batch = [
        json.loads(item.read_text(encoding="utf-8"))
        for item in created
        if json.loads(item.read_text(encoding="utf-8"))["batch_id"] == batch.batch_id
    ]
    assert len(retried_batch) == 1
    assert [item["section_id"] for item in retried_batch[0]["section_contracts"]] == [failed]


def test_prs_retry_preserves_the_accepted_narrative_target(tmp_path):
    reference = fixture()
    batch = next(item for item in batch_plan("Prospective") if item.batch_id == "prs-narrative")
    request_path = create_drafting_request(
        repo_root=ROOT,
        revision_dir=tmp_path,
        revision_id="r-prs-partial",
        reference=reference,
        batch=batch,
        attempts={item: 1 for item in batch.section_ids},
        wave="initial",
    )
    request = json.loads(request_path.read_text(encoding="utf-8"))
    response = recorded_acceptance_response(request)
    response["narrative"]["detailed_description"]["text"] = "Too short"

    accepted, findings = validate_response(request, response)

    assert set((accepted or {})["narrative"]) == {"brief_summary"}
    assert {target for finding in findings for target in finding.get("target_ids", [])} == {"prs.detailed-description"}

    retry_path = create_drafting_request(
        repo_root=ROOT,
        revision_dir=tmp_path,
        revision_id="r-prs-partial",
        reference=reference,
        batch=batch,
        target_ids=("prs.detailed-description",),
        attempts={"prs.detailed-description": 2},
        wave="retry",
        findings=findings,
    )
    retry = json.loads(retry_path.read_text(encoding="utf-8"))
    assert [item["section_id"] for item in retry["section_contracts"]] == ["prs.detailed-description"]
    assert set(response_template(retry)["narrative"]) == {"detailed_description"}


def test_prs_narrative_rejects_evidence_outside_the_target_contract(tmp_path):
    reference = fixture()
    batch = next(item for item in batch_plan("Prospective") if item.batch_id == "prs-narrative")
    request_path = create_drafting_request(
        repo_root=ROOT,
        revision_dir=tmp_path,
        revision_id="r-prs-scope",
        reference=reference,
        batch=batch,
        attempts={item: 1 for item in batch.section_ids},
        wave="initial",
    )
    request = json.loads(request_path.read_text(encoding="utf-8"))
    response = recorded_acceptance_response(request)
    response["narrative"]["brief_summary"]["evidence_refs"].append("source:study.background")

    accepted, findings = validate_response(request, response)

    assert set((accepted or {})["narrative"]) == {"detailed_description"}
    assert any(
        item["field"] == "prs.brief-summary" and "not approved for this target" in item["issue"]
        for item in findings
    )


def test_visual_gate_rejects_unassessed_pages(tmp_path):
    request_dir = tmp_path / "hermes/verification-requests"; response_dir = tmp_path / "hermes/verification-responses"
    request_dir.mkdir(parents=True); response_dir.mkdir(parents=True)
    request = {"schema_version": "hermes-verification/v1", "request_id": "r.verify.visual", "task": "rendered_page_visual_verification", "response_path": "hermes/verification-responses/r.verify.visual.json", "artifacts": [{"artifact": "protocol", "pages": [{"page": 1, "sha256": "one"}, {"page": 2, "sha256": "two"}]}]}
    request["request_sha256"] = verification_request_sha256(request)
    response = {"schema_version": RESPONSE_SCHEMA, "request_id": request["request_id"], "request_sha256": request["request_sha256"], "task": request["task"], "producer": {"model_id": "test"}, "status": "passed", "findings": [], "page_assessments": [{"artifact": "protocol", "page": 1, "sha256": "one", "status": "passed", "checks": list(VISUAL_CHECKS)}]}
    (request_dir / "r.verify.visual.json").write_text(json.dumps(request), encoding="utf-8")
    (response_dir / "r.verify.visual.json").write_text(json.dumps(response), encoding="utf-8")
    findings, _ = validate_verifications(tmp_path)
    incomplete = next(item for item in findings if item["field"] == "page_assessments")
    assert incomplete["recovery_class"] == "verifier_transient"
    assert incomplete["action"] == "retry_verifier"


def test_visual_gate_preserves_the_exact_failed_layout_element(tmp_path):
    request_dir = tmp_path / "hermes/verification-requests"; response_dir = tmp_path / "hermes/verification-responses"
    request_dir.mkdir(parents=True); response_dir.mkdir(parents=True)
    request = {"schema_version": "hermes-verification/v1", "request_id": "r.verify.visual", "task": "rendered_page_visual_verification", "response_path": "hermes/verification-responses/r.verify.visual.json", "artifacts": [{"artifact": "protocol", "pages": []}]}
    request["request_sha256"] = verification_request_sha256(request)
    response = {
        "schema_version": RESPONSE_SCHEMA,
        "request_id": request["request_id"],
        "request_sha256": request["request_sha256"],
        "task": request["task"],
        "producer": {"model_id": "test"},
        "status": "failed",
        "findings": [{
            "artifact": "protocol",
            "page": 7,
            "check": "bad_table_split",
            "element": "Table 13.3.-1",
            "issue": "The contact table splits badly.",
        }],
        "page_assessments": [],
    }
    (request_dir / "r.verify.visual.json").write_text(json.dumps(request), encoding="utf-8")
    (response_dir / "r.verify.visual.json").write_text(json.dumps(response), encoding="utf-8")

    findings, _ = validate_verifications(tmp_path)

    failed_table = next(item for item in findings if item.get("check") == "bad_table_split")
    assert failed_table["element"] == "Table 13.3.-1"
    assert failed_table["target_ids"] == ["layout:protocol"]


def test_render_gate_detects_a_textless_pdf_page(tmp_path):
    from quality import _blank_pdf_pages

    path = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with path.open("wb") as handle:
        writer.write(handle)

    assert _blank_pdf_pages(path) == [1]


def test_render_gate_does_not_call_a_sparse_body_page_textless(monkeypatch):
    import quality

    class Page:
        def extract_text(self):
            return (
                "Prospective sparse acceptance Page 3 of 11\n"
                "v 1.0 21 Aug 2026\n"
                "Variables • Primary outcome (Month 3)\n"
                "• Safety outcome (Month 3)\n"
                "Duration / Follow-up 3 months"
            )

    monkeypatch.setattr(quality, "PdfReader", lambda _: type("Reader", (), {"pages": [Page()]})())

    assert quality._blank_pdf_pages(Path("unused.pdf")) == []


def test_raw_document_word_count_alone_does_not_block_delivery(tmp_path):
    path = tmp_path / "short.docx"
    document = __import__("docx").Document()
    document.add_paragraph("Concise source-grounded content.")
    document.save(path)

    assert audit_docx(path) == []


def test_docx_audit_assigns_recovery_classes_at_the_finding_producer(tmp_path):
    from docx.oxml import OxmlElement

    path = tmp_path / "governed.docx"
    document = Document()
    document.add_paragraph("Unresolved {study_title}")
    document.settings.element.append(OxmlElement("w:trackRevisions"))
    document.save(path)

    findings = audit_docx(path)

    drafting = next(item for item in findings if "Unresolved template token" in item["issue"])
    structure = next(item for item in findings if "Tracked changes" in item["issue"])
    assert (drafting["recovery_class"], drafting["action"]) == ("document_structure_defect", "preserve_and_stop")
    assert (structure["recovery_class"], structure["action"]) == ("document_structure_defect", "preserve_and_stop")


def test_generic_content_pass_without_per_section_evidence_is_rejected(tmp_path):
    request_dir = tmp_path / "hermes/verification-requests"; response_dir = tmp_path / "hermes/verification-responses"
    request_dir.mkdir(parents=True); response_dir.mkdir(parents=True)
    request = {"schema_version": "hermes-verification/v1", "request_id": "r.verify.content", "task": "clinical_content_verification", "response_path": "hermes/verification-responses/r.verify.content.json", "artifacts": [], "sections": [{"artifact": "protocol", "section_id": "introduction"}], "checks": list(CONTENT_CHECKS), "cross_document_checks": ["study_title"]}
    request["request_sha256"] = verification_request_sha256(request)
    response = {"schema_version": RESPONSE_SCHEMA, "request_id": request["request_id"], "request_sha256": request["request_sha256"], "task": request["task"], "producer": {"model_id": "test"}, "status": "passed", "findings": []}
    (request_dir / "r.verify.content.json").write_text(json.dumps(request), encoding="utf-8")
    (response_dir / "r.verify.content.json").write_text(json.dumps(response), encoding="utf-8")
    findings, _ = validate_verifications(tmp_path)
    assert sum("explicitly assessed" in item["issue"] for item in findings) == 2


def test_visual_response_is_rejected_after_any_bound_artifact_changes(tmp_path):
    request_dir = tmp_path / "hermes/verification-requests"; request_dir.mkdir(parents=True)
    for relative, data in (("candidate/protocol.docx", b"docx"), ("rendered/protocol.pdf", b"pdf"), ("rendered/protocol/page-1.png", b"png")):
        path = tmp_path / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
    digest = lambda relative: hashlib.sha256((tmp_path / relative).read_bytes()).hexdigest()
    request = {"schema_version": "hermes-verification/v1", "request_id": "r.verify.visual", "task": "rendered_page_visual_verification", "response_path": "hermes/verification-responses/r.verify.visual.json", "artifacts": [{"artifact": "protocol", "docx": "candidate/protocol.docx", "docx_sha256": digest("candidate/protocol.docx"), "pdf": "rendered/protocol.pdf", "pdf_sha256": digest("rendered/protocol.pdf"), "pages": [{"page": 1, "path": "rendered/protocol/page-1.png", "sha256": digest("rendered/protocol/page-1.png")}]}], "checks": list(VISUAL_CHECKS)}
    request["request_sha256"] = verification_request_sha256(request)
    request_path = request_dir / "r.verify.visual.json"; request_path.write_text(json.dumps(request), encoding="utf-8")
    response_path = tmp_path / request["response_path"]; response_path.parent.mkdir(parents=True); response_path.write_text(json.dumps(acceptance_verification(request)), encoding="utf-8")
    for relative in (
        "candidate/protocol.docx",
        "rendered/protocol.pdf",
        "rendered/protocol/page-1.png",
    ):
        path = tmp_path / relative
        original = path.read_bytes()
        path.write_bytes(b"changed")
        findings, _ = validate_verifications(tmp_path)
        stale = next(item for item in findings if "stale" in item["issue"] and relative in item["issue"])
        assert stale["recovery_class"] == "document_structure_defect"
        assert stale["action"] == "preserve_and_stop"
        path.write_bytes(original)


def test_visual_review_contract_rejects_artificial_pagination_defects():
    assert "excessive_whitespace" in VISUAL_CHECKS
    assert "artificial_pagination" in VISUAL_CHECKS


def test_generation_rejects_study_input_mutation_after_approval(tmp_path):
    run_dir = tmp_path / "run"; reference_path = run_dir / "reference/study.reference.json"; reference_path.parent.mkdir(parents=True)
    reference_path.write_text(json.dumps(fixture()), encoding="utf-8")
    assert prepare(run_dir)["status"] == "awaiting_approval"
    assert approve(run_dir, approved_by="reviewer")["status"] == "passed"
    changed = json.loads(reference_path.read_text(encoding="utf-8")); changed["study"]["title"] = "Changed after approval"
    reference_path.write_text(json.dumps(changed), encoding="utf-8")
    assert validate(run_dir)["status"] == "blocked"
    result = generate(run_dir)
    assert result["status"] == "blocked"
    assert result["stage"] == "approval_gate"


def test_generation_keeps_exhausted_retry_blocked_across_restart(tmp_path, monkeypatch):
    _require_renderer()
    run_dir = tmp_path / "run"; reference_path = run_dir / "reference/study.reference.json"; reference_path.parent.mkdir(parents=True)
    reference_path.write_text(json.dumps(fixture()), encoding="utf-8")
    assert prepare(run_dir)["status"] == "awaiting_approval"
    assert approve(run_dir, approved_by="reviewer")["status"] == "passed"
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    reference["generation"] = {"attempts": {"introduction": 4}}
    reference_path.write_text(json.dumps(reference), encoding="utf-8")
    first = generate(run_dir); second = generate(run_dir)
    assert first["status"] == second["status"] == "blocked"
    assert first["stage"] == second["stage"] == "retry_limit"
