"""Minor review findings must not turn a complete package into review copies."""
import json
from pathlib import Path

import pytest
import quality
import workflow
from rendering import protocol_section_snapshot, render_documents
from test_handoff_quality import acceptance_verification

ROOT = Path(__file__).resolve().parents[1]
FAMILIES = [("Retrospective", "Advarra"), ("Prospective", "Advarra"),
            ("Prospective", "Sterling"), ("Ambispective", "Advarra"),
            ("Ambispective", "Sterling")]


def repetition_review(root, branch, template, render_report=None):
    source = {"meta": {"study_type": branch, "icf_template": template}}
    paths = quality.create_verification_requests(root, source, render_report or {"artifacts": []})
    path = paths[0]
    for visual_path in paths[1:]:
        visual_request = json.loads(visual_path.read_text())
        (root / visual_request["response_path"]).write_text(json.dumps(acceptance_verification(visual_request)))
    request = json.loads(path.read_text())
    response = acceptance_verification(request)
    response["status"] = "blocked"
    for item in response["section_assessments"]:
        if item["section_id"] == "analysis-plan.considerations":
            item["status"] = "blocked"
    response["findings"] = [{
        "finding_id": "redundant-methods", "category": "content",
        "artifact": "protocol", "check": "concept_repetition",
        "issue": "General considerations repeats the statistical method.",
        "target_ids": ["analysis-plan.considerations"],
        "concept_id": "statistical-methods",
        "primary_section": "analysis-plan.methodology",
        "secondary_section": "analysis-plan.considerations",
        "primary_paragraphs": ["The approved statistical method."],
        "secondary_paragraphs": ["The same statistical method."],
        "treatment": "excessive", "necessary": False, "concise": False,
        "material": False, "safety_critical": False, "contradiction": False,
        "obscures_required_information": False, "materially_unusable": False,
    }]
    response_path = root / request["response_path"]
    response_path.write_text(json.dumps(response))
    return path, response_path, response


@pytest.mark.parametrize("branch,template", FAMILIES)
def test_warning_only_review_publishes_normal_exact_bytes_with_location(tmp_path, monkeypatch, branch, template):
    from test_atomic_delivery import _publish_fixture
    # Byte sentinels isolate publication from clinical/visual content assessment.
    # Real requests, artifact bindings, final review and atomic publication run.
    monkeypatch.setattr(quality, "deterministic_content_check", lambda *_args: [])
    run, revision, source = _publish_fixture(tmp_path)
    source["meta"].update(study_type=branch, icf_template=template)
    build_path = revision / "candidate-build.json"
    build = json.loads(build_path.read_text())
    if branch == "Retrospective":
        (revision / "candidate/icf.docx").unlink()
        (revision / "candidate/study.xml").unlink()
        build["candidate_files"] = [row for row in build["candidate_files"] if row["path"].endswith("protocol.docx")]
        build["render_report"]["artifacts"] = [row for row in build["render_report"]["artifacts"] if row["artifact"] == "protocol"]
    build_path.write_text(json.dumps(build))
    (revision / "approved-reference.json").write_text(json.dumps(source))
    repetition_review(revision, branch, template, build["render_report"])
    report = quality.quality_report(revision, source, build["render_report"], None)
    assert report["status"] == "passed"
    result = workflow._publish(run, revision, source, report)
    expected = ["protocol.docx"] if branch == "Retrospective" else ["icf.docx", "protocol.docx", "study.xml"]
    assert sorted(path.name for path in (run / "output").iterdir()) == expected
    assert result["status"] == "passed"
    number = "9.3" if branch == "Retrospective" else "10.3"
    assert result["warnings"][0]["document_locations"] == [f"Protocol §{number} — General Statistical Considerations"]
    assert (run / "output/protocol.docx").read_bytes() == b"new protocol"
    assert result["desktop_reply"]["cautions"] == result["warnings"]


@pytest.mark.parametrize("branch,template", FAMILIES)
def test_structured_minor_repetition_needs_no_optional_magic_labels(tmp_path, branch, template):
    path, _, _ = repetition_review(tmp_path, branch, template)
    findings, _ = quality.validate_verifications(tmp_path, request_paths=[path])
    assert len(findings) == 1
    assert findings[0]["publication_disposition"] == "warning"
    assert findings[0]["target_ids"] == ["analysis-plan.considerations"]
    assert quality.verification_response_is_complete(tmp_path, path)


@pytest.mark.parametrize("branch,template", FAMILIES[1:])
@pytest.mark.parametrize("material", [False, True])
def test_icf_editorial_repetition_is_distinct_from_material_cost_disclosure(tmp_path, branch, template, material):
    path, response_path, response = repetition_review(tmp_path, branch, template)
    for item in response["section_assessments"]:
        item["status"] = "blocked" if item["section_id"] == "icf.costs" else "passed"
    response["findings"] = [{
        "finding_id": "icf-cost-wording", "category": "content", "artifact": "icf",
        "check": "editorial_relevance", "target_ids": ["icf.costs"],
        "issue": "The cost disclosure repeats the same sentence.",
        "affected_passage": "The repeated disclosure.", "recommended_action": "Remove the duplicate sentence.",
        "material": material, "safety_critical": False, "contradiction": False,
        "obscures_required_information": False, "materially_unusable": False,
    }]
    response_path.write_text(json.dumps(response))
    assert quality.verification_response_is_complete(tmp_path, path) is (not material)


@pytest.mark.parametrize("mutation", ["material", "safety", "unknown", "wrong-owner", "missing-flag", "stale"])
def test_repetition_warning_preserves_material_and_response_guards(tmp_path, mutation):
    path, response_path, response = repetition_review(tmp_path, "Prospective", "Sterling")
    finding = response["findings"][0]
    if mutation == "material": finding["material"] = True
    if mutation == "safety": finding["safety_critical"] = True
    if mutation == "unknown": finding["check"] = "unknown_check"
    if mutation == "wrong-owner": finding["primary_section"] = "introduction"
    if mutation == "missing-flag": del finding["material"]
    if mutation == "stale": response["request_sha256"] = "stale"
    response_path.write_text(json.dumps(response))
    assert not quality.verification_response_is_complete(tmp_path, path)


@pytest.mark.parametrize("branch,template", FAMILIES)
@pytest.mark.parametrize("safety", ["absent", True])
def test_previously_valid_structured_warning_remains_compatible_without_hiding_safety(tmp_path, branch, template, safety):
    path, response_path, response = repetition_review(tmp_path, branch, template)
    finding = response["findings"][0]
    finding.update(code="protocol-concept-repetition", disposition="manual_review")
    if safety == "absent":
        del finding["safety_critical"]
    else:
        finding["safety_critical"] = safety
    response_path.write_text(json.dumps(response))
    assert quality.verification_response_is_complete(tmp_path, path) is (safety == "absent")


@pytest.mark.parametrize("branch,template", FAMILIES[1:])
@pytest.mark.parametrize("repair", [
    "The planned timeline comprises 6 months for enrollment, postoperative follow-up through 3 months, and 1 month for data analysis.",
    "Enrollment is planned to be completed over 6 months, postoperative follow-up lasts 3 months, and data analysis takes 1 month.",
    "No separate study-completion criterion is specified. The planned timeline comprises 6 months for enrollment, postoperative follow-up through 3 months, and 1 month for data analysis.",
])
def test_accepted_timeline_repair_survives_actual_docx_construction(tmp_path, branch, template, repair):
    source = json.loads((ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text())
    source["meta"].update(study_type=branch, icf_template=template)
    source["study"].update(completion="", timeline=(
        "Enrollment: 6 months; Follow-up: 3 months postoperatively; Data analysis: 1 month. "
        "Screening is preoperative, surgery has one operative visit per eye, "
        "and the postoperative assessment is at Month 3."))
    model = {"protocol": [{"section_id": "endpoint-criteria.study-completion",
                           "paragraphs": [{"text": repair}], "lists": []}], "icf": {}, "prs": {}}
    render_documents(ROOT, tmp_path, source, model, artifact_names={"protocol"})
    snapshot = protocol_section_snapshot(tmp_path / "candidate/protocol.docx", "endpoint-criteria.study-completion")
    body = "\n".join(item.get("paragraph", "") for item in snapshot)
    assert repair in body
    assert "surgery has one operative visit per eye" not in body


@pytest.mark.parametrize("branch,template", FAMILIES[1:])
@pytest.mark.parametrize("claim", [
    "Study closeout follows the planned 3-month study timeline.",
    "The study will be considered complete after 3 months.",
    "The study ends after 3 months.",
    "No separate study-completion criterion is specified. The study will be considered complete after 3 months.",
])
def test_unsupplied_study_completion_assertions_still_use_source_timeline(tmp_path, branch, template, claim):
    source = json.loads((ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text())
    source["meta"].update(study_type=branch, icf_template=template)
    source["study"].update(timeline="3 months", completion="")
    model = {"protocol": [{"section_id": "endpoint-criteria.study-completion",
                           "paragraphs": [{"text": claim}], "lists": []}], "icf": {}, "prs": {}}
    render_documents(ROOT, tmp_path, source, model, artifact_names={"protocol"})
    body = "\n".join(item.get("paragraph", "") for item in protocol_section_snapshot(
        tmp_path / "candidate/protocol.docx", "endpoint-criteria.study-completion"))
    assert "The planned study timeline is 3 months." in body
    assert claim not in body
