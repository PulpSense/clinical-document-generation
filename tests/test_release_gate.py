import json
from pathlib import Path

from docx import Document

from contracts import contracted_template_bundle
from quality import CONTENT_CHECKS, RESPONSE_SCHEMA, VISUAL_CHECKS
from rendering import template_paths
from workflow import run_release_gate
import workflow


ROOT = Path(__file__).resolve().parents[1]


def _require_renderer(governed_pdfium):
    assert workflow.renderer() is not None
    assert governed_pdfium["source"] == "release-owned runtime"


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


def test_all_six_public_lifecycle_cases_pass_and_publish_exact_sets(monkeypatch, governed_pdfium):
    _require_renderer(governed_pdfium)
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
        expected_bundle = contracted_template_bundle(ROOT, reference)
        revision_dir = case_root / "revisions" / case["result"]["revision_id"]
        manifest = json.loads((case_root / case["result"]["manifest"]).read_text(encoding="utf-8"))
        build = json.loads((revision_dir / "candidate-build.json").read_text(encoding="utf-8"))
        verification_requests = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in (revision_dir / "hermes/verification-requests").glob("*.json")
        ]
        assert case["contracted_template_bundle"] == expected_bundle
        assert build["contracted_template_bundle"] == expected_bundle
        assert manifest["contracted_template_bundle"] == expected_bundle
        assert all(request["contracted_template_bundle"] == expected_bundle for request in verification_requests)
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
    assert {
        bundle["identity_sha256"]
        for bundle in report["contracted_template_bundles"]
    } == {
        case["contracted_template_bundle"]["identity_sha256"]
        for case in report["cases"]
    }


def test_recorded_drafting_keeps_release_gate_assurance_structural_with_external_verification(monkeypatch, governed_pdfium):
    _require_renderer(governed_pdfium)
    report = run_release_gate(ROOT, verification_responder=external_verification)

    assert report["status"] == "structural_passed"
    assert report["assurance"] == "recorded-drafting-structural-only"


def test_controlled_release_adapter_drives_the_complete_desktop_operation(tmp_path, monkeypatch, governed_pdfium):
    _require_renderer(governed_pdfium)
    run_dir = tmp_path / "controlled-retrospective"
    reference_path = run_dir / "reference/study.reference.json"
    reference_path.parent.mkdir(parents=True)
    reference = json.loads((ROOT / "tests/fixtures/retrospective-acceptance-source.json").read_text(encoding="utf-8"))
    reference["meta"]["protocol_number"] = "RET-CONTROLLED-41"
    reference["study"]["title"] = "Controlled Desktop Operation study"
    reference["approval"] = {"status": "draft"}
    reference_path.write_text(json.dumps(reference), encoding="utf-8")
    assert workflow.prepare(run_dir)["status"] == "awaiting_approval"
    assert workflow.approve(run_dir, approved_by="Controlled Release Adapter")["status"] == "passed"

    def handoff_runner(handoffs, _remaining_seconds):
        approved = json.loads(reference_path.read_text(encoding="utf-8"))
        revision_dir = run_dir / "revisions" / approved["approval"]["revision_id"]
        for handoff in handoffs:
            request_path = revision_dir / handoff["request_path"]
            if "verification-requests" in handoff["request_path"]:
                workflow._save_verification_response(revision_dir, request_path, acceptance_verification)
            else:
                workflow._save_recorded_handoff(revision_dir, request_path)

    result = workflow.run_desktop_operation(
        run_dir,
        handoff_runner=handoff_runner,
        opener=lambda path: Path(path).read_bytes(),
        operation_id="controlled-release-adapter",
        release_identity={"package_fingerprint": "controlled-candidate-41"},
    )

    assert result["status"] == "passed"
    assert result["stage"] == "desktop_delivery"
    assert result["client_outputs"] == ["output/protocol.docx"]
    assert result["delivery"]["confirmed"] is True
    state = json.loads((run_dir / "logs/desktop-operation-controlled-release-adapter.json").read_text())
    assert state["release_identity"]["package_fingerprint"] == "controlled-candidate-41"
    assert {"drafting", "candidate", "render_assurance", "independent_verification", "delivery"} <= set(state["stage_timings"])
    assert state["result"] == result
