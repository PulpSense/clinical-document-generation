import json
from pathlib import Path

from docx import Document
from docx.enum.style import WD_STYLE_TYPE

from quality import RESPONSE_SCHEMA, validate_verifications
import quality
from rendering import render_documents
import rendering
from prs_xml import generate as generate_xml
import workflow


ROOT = Path(__file__).resolve().parents[1]


def _source():
    return json.loads(
        (ROOT / "runs/ps-mm-001/reference/study.reference.json").read_text(encoding="utf-8")
    )


def _visible(document):
    paragraphs = [paragraph.text for paragraph in document.paragraphs]
    cells = [cell.text for table in document.tables for row in table.rows for cell in row.cells]
    return "\n".join(paragraphs + cells)


def test_renderer_preflight_blocks_before_smoke_export_when_renderer_is_missing(tmp_path, monkeypatch):
    reference = _source()
    monkeypatch.setattr(quality, "renderer", lambda **_: None)
    report = quality.preflight(ROOT, reference, deadline_seconds=2)

    assert report["status"] == "blocked"
    assert report["smoke"]["status"] == "not_run"
    assert any("renderer" == finding["field"] for finding in report["findings"])


def test_renderer_preflight_records_renderer_font_and_smoke_evidence(tmp_path, monkeypatch):
    reference = _source()
    identity = {"kind": "LibreOffice", "path": "/usr/bin/soffice", "version": "test", "platform": "Linux"}
    monkeypatch.setattr(quality, "renderer", lambda **_: identity)
    monkeypatch.setattr(quality, "_font_probe", lambda *_args, **_kwargs: (True, "test-font"))

    def fake_export(_docx, output_dir, _identity, **_kwargs):
        from pypdf import PdfWriter
        output = output_dir / "preflight.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        with output.open("wb") as handle:
            writer.write(handle)
        return output

    monkeypatch.setattr(quality, "_render_pdf", fake_export)
    report = quality.preflight(ROOT, reference, deadline_seconds=10)

    assert report["status"] == "passed"
    assert report["renderer"] == identity
    assert report["elapsed_seconds"] < report["deadline_seconds"]
    assert report["smoke"] == {"status": "passed", "pdf": "disposable/preflight.pdf", "page_image": "disposable/preflight.png", "pages": 1}


def test_renderer_preflight_can_run_an_actual_local_renderer_smoke_export(monkeypatch):
    identity = quality.renderer()
    if identity is None:
        import pytest
        pytest.skip("No supported local renderer installed")
    monkeypatch.setattr(quality, "_font_probe", lambda *_args, **_kwargs: (True, "test-font"))
    report = quality.preflight(ROOT, _source(), deadline_seconds=30)

    assert report["status"] == "passed"
    assert report["smoke"]["status"] == "passed"
    assert report["smoke"]["pages"] >= 1


def test_approved_investigator_and_facility_values_populate_protocol_agreement(tmp_path):
    reference = _source()
    render_documents(ROOT, tmp_path, reference, {"protocol": [], "icf": {}, "prs": {}})

    document = Document(tmp_path / "candidate/protocol.docx")
    agreement = next(
        table for table in document.tables
        if any("Signature of Investigator" in cell.text for row in table.rows for cell in row.cells)
    )
    values = [cell.text for row in agreement.rows for cell in row.cells]
    assert "Dana Roberts" in values
    assert "MD" in values
    assert "North Neurology Research Center" in values
    assert "Boston" in "\n".join(values)


def test_protocol_visit_schedule_has_rows_when_approved_source_has_assessments_only(tmp_path):
    reference = _source()
    reference["procedures"].pop("visit_schedule", None)
    reference["procedures"].pop("visit_schedule_table", None)
    reference["procedures"]["assessments"] = ["Screening", "Month 1", "Month 3"]
    render_documents(ROOT, tmp_path, reference, {"protocol": [], "icf": {}, "prs": {}})

    document = Document(tmp_path / "candidate/protocol.docx")
    schedule = next(table for table in document.tables if table.cell(0, 0).text.strip() == "Visit Number")
    assert [cell.text for row in schedule.rows[1:] for cell in row.cells]
    assert "Screening" in "\n".join(cell.text for row in schedule.rows for cell in row.cells)


def test_advarra_icf_contact_and_withdrawal_are_source_bound(tmp_path):
    reference = _source()
    model = {
        "protocol": [],
        "prs": {},
        "icf": {
            "icf.contact-information": {
                "paragraphs": [{"text": "Call the study doctor at the toll-free IRB number and ask the Study Subject Adviser."}],
                "lists": [],
            },
            "icf.leaving-study": {
                "paragraphs": [{"text": "Call to schedule study exit procedures."}],
                "lists": [],
            },
        },
    }
    render_documents(ROOT, tmp_path, reference, model)
    visible = _visible(Document(tmp_path / "candidate/icf.docx")).casefold()

    assert "toll-free" not in visible
    assert "study subject adviser" not in visible
    assert "schedule study exit procedures" not in visible
    assert "555-310-2000" in visible
    assert "no new routine research procedures" in visible


def test_advarra_icf_replaces_unsupported_introduction_and_risk_shell_text(tmp_path):
    reference = _source()
    risk_text = (
        "Taking part may involve inconvenience or discomfort from the study procedures described in this consent form. "
        "There is also a risk that private information could be disclosed, although safeguards will be used to protect it."
    )
    model = {
        "protocol": [],
        "prs": {},
        "icf": {
            "icf.risks": {"paragraphs": [{"text": risk_text}], "lists": []},
        },
    }

    render_documents(ROOT, tmp_path, reference, model)
    visible = _visible(Document(tmp_path / "candidate/icf.docx")).casefold()

    assert "you are being invited to take part in a research study" in visible
    assert "past and present drug use" not in visible
    assert "very serious health consequences" not in visible
    assert "all devices can have side effects" not in visible
    assert "presently unforeseen and unknown risks" not in visible
    assert visible.count(risk_text.casefold()) == 1


def test_protocol_test_article_falls_back_to_approved_intervention_name():
    reference = _source()
    reference["design"].pop("arms", None)

    fields = rendering.render_fields(reference, {"protocol": [], "icf": {}, "prs": {}})

    assert fields["testArticle(s)"] == "Meridian Monitor"


def test_transient_verifier_failure_is_classified_for_retry_without_accepting_qa(tmp_path):
    revision = tmp_path / "revision"
    requests = revision / "hermes/verification-requests"
    responses = revision / "hermes/verification-responses"
    requests.mkdir(parents=True)
    responses.mkdir()
    request = {
        "schema_version": "hermes-verification/v1",
        "request_id": "r.verify.content",
        "request_sha256": "request-hash",
        "task": "clinical_content_verification",
        "response_path": "hermes/verification-responses/r.verify.content.json",
        "sections": [],
        "cross_document_checks": [],
        "artifacts": [],
    }
    (requests / "content.json").write_text(json.dumps(request), encoding="utf-8")
    response = {
        "schema_version": RESPONSE_SCHEMA,
        "request_id": request["request_id"],
        "request_sha256": request["request_sha256"],
        "task": request["task"],
        "producer": {"model_id": "Verifier"},
        "status": "retryable_error",
        "error": {"type": "api_unavailable", "message": "temporary connection failure"},
    }
    (responses / "r.verify.content.json").write_text(json.dumps(response), encoding="utf-8")

    findings, evidence = validate_verifications(revision)

    assert evidence[request["task"]]
    assert len(findings) == 1
    assert findings[0]["category"] == "reviewer-transient"
    assert findings[0]["target_ids"] == ["verification:content"]


def test_transient_verifier_failure_is_retried_with_a_bounded_counter(tmp_path):
    revision = tmp_path / "revision"
    requests = revision / "hermes/verification-requests"
    requests.mkdir(parents=True)
    for task in ("clinical_content_verification", "rendered_page_visual_verification"):
        (requests / f"{task}.json").write_text(
            json.dumps({"task": task, "response_path": f"hermes/verification-responses/{task}.json"}),
            encoding="utf-8",
        )
    run_dir = tmp_path / "run"
    reference_path = run_dir / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    working = {"generation": {}}
    reference_path.write_text(json.dumps(working), encoding="utf-8")
    finding = {"category": "reviewer-transient", "field": "clinical_content_verification", "target_ids": ["verification:content"], "issue": "temporary"}

    result = workflow._quality_retry(run_dir, reference_path, working, {}, revision, {}, [finding], "quality")

    assert result["status"] == "awaiting_hermes"
    assert result["stage"] == "independent_verification_retry"
    state = json.loads(reference_path.read_text(encoding="utf-8"))
    assert state["generation"]["verification_attempts"]["verification:content"] == 1
    assert not (revision / "hermes/verification-responses/clinical_content_verification.json").exists()


def test_layout_failure_rebuilds_and_reverifies_before_retry_limit(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    revision = run_dir / "revisions/r-test"
    reference_path = run_dir / "reference/study.reference.json"
    verification_response = revision / "hermes/verification-responses/visual.json"
    reference_path.parent.mkdir(parents=True)
    verification_response.parent.mkdir(parents=True)
    reference_path.write_text(json.dumps({"generation": {}}), encoding="utf-8")
    verification_response.write_text("{}", encoding="utf-8")
    (revision / "candidate-build.json").write_text("{}", encoding="utf-8")
    rerun = {"status": "awaiting_hermes", "stage": "independent_verification"}
    monkeypatch.setattr(workflow, "generate", lambda _run_dir: rerun)

    result = workflow._quality_retry(
        run_dir,
        reference_path,
        {"generation": {}},
        {},
        revision,
        {},
        [{"category": "visual", "field": "protocol.docx:10", "target_ids": ["layout:protocol.docx"], "issue": "orphan heading"}],
        "quality",
    )

    assert result == rerun
    state = json.loads(reference_path.read_text(encoding="utf-8"))
    assert state["generation"]["attempts"]["layout:protocol.docx"] == 2
    assert not (revision / "candidate-build.json").exists()
    assert not verification_response.exists()


def test_layout_failure_blocks_only_after_three_total_attempts(tmp_path):
    run_dir = tmp_path / "run"
    revision = run_dir / "revisions/r-test"
    reference_path = run_dir / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    reference_path.write_text(json.dumps({"generation": {}}), encoding="utf-8")
    finding = {"category": "visual", "field": "protocol.docx:10", "target_ids": ["layout:protocol.docx"], "issue": "orphan heading"}

    result = workflow._quality_retry(
        run_dir,
        reference_path,
        {"generation": {}},
        {},
        revision,
        {"layout:protocol.docx": 3},
        [finding],
        "quality",
    )

    assert result["status"] == "blocked"
    assert result["stage"] == "quality"
    assert result["findings"][0]["field"] == "layout:protocol.docx"
    assert "after 3 attempts" in result["findings"][0]["issue"]


def test_prs_generation_validates_against_the_retained_client_manual_authority(tmp_path):
    reference = json.loads((ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text(encoding="utf-8"))
    report = generate_xml(
        ROOT / "assets/client-templates/prs/clinicaltrials_prs_full_placeholder_template.xml",
        tmp_path / "study.xml",
        reference,
        {"brief_summary": {"text": "Approved summary."}, "detailed_description": {"text": "Approved description."}},
        structural_template=ROOT / "assets/client-templates/reference/prs-manual-reference.xml",
    )
    assert report["status"] == "passed"


def test_refresh_toc_uses_layout_extraction_to_find_body_heading(tmp_path, monkeypatch):
    document = Document()
    document.styles.add_style("toc 1", WD_STYLE_TYPE.PARAGRAPH)
    document.add_paragraph("4. TABLE OF CONTENTS", style="Heading 1")
    document.add_paragraph("15. STANDARD EVALUATION PROCEDURES\t5", style="toc 1")
    document.add_paragraph("15. STANDARD EVALUATION PROCEDURES", style="Heading 1")
    docx = tmp_path / "protocol.docx"
    document.save(docx)
    pdf = tmp_path / "protocol.pdf"
    pdf.write_bytes(b"pdf")

    class Page:
        def __init__(self, plain, layout):
            self.plain = plain
            self.layout = layout

        def extract_text(self, extraction_mode=None):
            return self.layout if extraction_mode == "layout" else self.plain

    class Reader:
        def __init__(self, _path):
            self.pages = [
                Page("4. TABLE OF CONTENTS", "4. TABLE OF CONTENTS"),
                Page("15. STANDARD EVALUATION PROCEDURES", "15. STANDARD EVALUATION PROCEDURES"),
                *[Page("", "") for _ in range(7)],
                Page("", "15. STANDARD EVALUATION PROCEDURES"),
            ]

    monkeypatch.setattr(rendering, "PdfReader", Reader)
    assert rendering.refresh_toc_from_pdf(docx, pdf)
    refreshed = Document(docx)
    toc = next(
        paragraph.text
        for paragraph in refreshed.paragraphs
        if paragraph.style.name == "toc 1" and paragraph.text.startswith("15.")
    )
    assert toc.endswith("\t10")


def test_protocol_omits_references_heading_when_no_references_are_supplied():
    document = Document()
    document.add_paragraph("REFERENCES", style="Heading 1")
    document.add_paragraph("")
    authority = Document()
    authority.add_paragraph("REFERENCES", style="Heading 1")

    rendering._ensure_protocol_references(document, authority, {})

    assert "REFERENCES" not in [paragraph.text.strip() for paragraph in document.paragraphs]


def test_layout_failure_rebuilds_the_candidate_before_blocking(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    revision = run_dir / "revisions/r-test"
    reference_path = run_dir / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    working = {"generation": {}}
    reference_path.write_text(json.dumps(working), encoding="utf-8")
    for relative in ("candidate", "rendered", "hermes/verification-responses"):
        path = revision / relative
        path.mkdir(parents=True)
        (path / "stale").write_text("stale", encoding="utf-8")
    (revision / "candidate-build.json").write_text("{}", encoding="utf-8")
    resumed = {"status": "awaiting_hermes", "stage": "independent_verification"}
    monkeypatch.setattr(workflow, "generate", lambda _: resumed)

    result = workflow._quality_retry(
        run_dir,
        reference_path,
        working,
        {"meta": {"study_type": "Retrospective"}},
        revision,
        {},
        [{"category": "visual", "field": "protocol", "target_ids": ["layout:protocol"], "issue": "orphaned heading"}],
        "quality",
    )

    assert result == resumed
    state = json.loads(reference_path.read_text(encoding="utf-8"))
    assert state["generation"]["attempts"]["layout:protocol"] == 2
    assert not (revision / "candidate").exists()
    assert not (revision / "rendered").exists()
    assert not (revision / "candidate-build.json").exists()
    assert not (revision / "hermes/verification-responses").exists()
