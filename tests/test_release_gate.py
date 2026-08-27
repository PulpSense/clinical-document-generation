import json
from pathlib import Path

from docx import Document

from quality import CONTENT_CHECKS, RESPONSE_SCHEMA, VISUAL_CHECKS
from rendering import template_paths
from workflow import run_release_gate
import workflow


ROOT = Path(__file__).resolve().parents[1]


def _allow_renderer_preflight(monkeypatch):
    identity = workflow.renderer()
    assert identity is not None
    monkeypatch.setattr(workflow, "preflight", lambda *_args, **_kwargs: {
        "status": "passed",
        "renderer": identity,
        "required_fonts": [],
        "fonts": {},
        "smoke": {"status": "passed"},
        "deadline_seconds": 30.0,
        "elapsed_seconds": 0.0,
        "findings": [],
    })


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
            {"artifact": artifact["artifact"], "page": page["page"], "sha256": page["sha256"], "status": "passed", "checks": list(VISUAL_CHECKS)}
            for artifact in request.get("artifacts", []) for page in artifact.get("pages", [])
        ]
    else:
        response["section_assessments"] = [
            {"artifact": item["artifact"], "section_id": item["section_id"], "status": "passed", "checks": list(CONTENT_CHECKS)}
            for item in request.get("sections", [])
        ]
        response["cross_document_assessments"] = [{"check": check, "status": "passed"} for check in request.get("cross_document_checks", [])]
    return response


acceptance_verification.synthetic = True


def external_verification(request):
    return acceptance_verification(request)


def _section_geometry(document: Document) -> tuple[tuple[int | None, ...], ...]:
    return tuple((
        section.page_width, section.page_height, section.top_margin, section.right_margin,
        section.bottom_margin, section.left_margin, section.header_distance, section.footer_distance,
    ) for section in document.sections)


def test_all_six_public_lifecycle_cases_pass_and_publish_exact_sets(monkeypatch):
    _allow_renderer_preflight(monkeypatch)
    report = run_release_gate(ROOT, verification_responder=acceptance_verification)
    assert report["status"] == "structural_passed"
    assert report["assurance"] == "synthetic-structural-only"
    assert len(report["cases"]) == 6
    assert report["distinct_source_count"] == 6
    assert {case["icf_template"] for case in report["cases"] if case["icf_template"]} == {"Advarra", "Sterling"}
    for case in report["cases"]:
        assert case["status"] == "passed"
        outputs = case["result"]["client_outputs"]
        case_root = Path(report["evidence_root"]) / case["case"]
        reference = json.loads((case_root / "reference/study.reference.json").read_text(encoding="utf-8"))
        protocol_template, icf_template = template_paths(ROOT, reference)
        assert _section_geometry(Document(case_root / "output/protocol.docx")) == _section_geometry(Document(protocol_template))
        if case["case"].startswith("retrospective"):
            assert outputs == ["output/protocol.docx"]
            visible = "\n".join(paragraph.text for paragraph in Document(Path(report["evidence_root"]) / case["case"] / "output/protocol.docx").paragraphs)
            assert "Unable to complete follow-up" in visible
            if "rich" in case["case"]:
                assert "Month 6" in visible
                assert "6 months" in visible
        else:
            assert outputs == ["output/icf.docx", "output/protocol.docx", "output/study.xml"]
            assert icf_template is not None
            icf_output = Document(case_root / "output/icf.docx")
            assert _section_geometry(icf_output) == _section_geometry(Document(icf_template))
            visible = "\n".join(paragraph.text for paragraph in icf_output.paragraphs).casefold()
            assert any(phrase in visible for phrase in (
                "should not sign",
                "if you would like to participate, you will be asked to sign",
                "if you agree to participate, you will be asked to sign",
            ))


def test_recorded_drafting_keeps_release_gate_assurance_structural_with_external_verification(monkeypatch):
    _allow_renderer_preflight(monkeypatch)
    report = run_release_gate(ROOT, verification_responder=external_verification)

    assert report["status"] == "structural_passed"
    assert report["assurance"] == "recorded-drafting-structural-only"
