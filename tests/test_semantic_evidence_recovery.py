"""Lexical uncertainty is deferred to real review, never treated as clinical proof."""
import json

import pytest

import drafting
import quality


@pytest.mark.parametrize("section", ["study-design.bias", "icf.procedures", "analysis-plan.considerations"])
def test_faithful_non_numeric_paraphrase_reaches_review_on_every_branch(section):
    path = "procedures.retention"
    value = "Personnel will telephone enrolled participants to remind them about scheduled follow-up appointments."
    request = {"approved_input": [{"path": path, "value": value}], "approved_source": {}}
    contract = {"minimum_evidence": [path], "source_coverage": "all_material_items"}
    findings = drafting._coverage_findings(
        request, contract, section,
        "Staff call people ahead of visits so they remember to attend.", ["source:" + path])
    assert len(findings) == 1
    assert findings[0]["publication_disposition"] == "warning"
    assert findings[0]["evidence_diagnostics"][0]["release_acceptance"] is False


@pytest.mark.parametrize("value,text", [
    ("Blood draw at 5 mL", "Blood is collected at 6 mL."),
    ("none", "Compensation is provided."),
])
def test_missing_quantity_and_negative_polarity_are_not_lexical_uncertainty(value, text):
    diagnostic = drafting.source_evidence_diagnostics(text, "procedures.assessments", value)
    assert diagnostic["passed"] is False
    assert not drafting.lexical_evidence_uncertainty([diagnostic])


def test_missing_source_citation_remains_a_drafting_failure():
    path = "procedures.retention"
    findings = drafting._coverage_findings(
        {"approved_input": [{"path": path, "value": "Reminder calls"}], "approved_source": {}},
        {"minimum_evidence": [path], "source_coverage": "all_material_items"},
        "study-design.bias", "Staff make reminder calls.", [])
    assert findings and not any(f.get("publication_disposition") == "warning" for f in findings)


def reviewed_caution(tmp_path, branch="Prospective", template="Advarra"):
    from test_handoff_quality import acceptance_verification
    warning = {"code": "lexical-evidence-uncertainty", "field": "study-design.bias",
               "publication_disposition": "warning", "issue": "Reminder-call wording needs meaning review."}
    accepted = tmp_path / "hermes/accepted"
    accepted.mkdir(parents=True)
    (accepted / "study-design.bias.json").write_text(json.dumps({"warnings": [warning]}))
    paths = quality.create_verification_requests(tmp_path, {"meta": {"study_type": branch, "icf_template": template}}, {"artifacts": []})
    request = json.loads(paths[0].read_text())
    assert request["lexical_review_cautions"][0]["caution"] == warning
    for path in paths:
        payload = json.loads(path.read_text())
        response = acceptance_verification(payload)
        (tmp_path / payload["response_path"]).write_text(json.dumps(response))
    findings, evidence = quality.validate_verifications(tmp_path)
    assert findings == []
    return warning, request, paths[0], evidence


@pytest.mark.parametrize("branch,template", [
    ("Retrospective", "Advarra"), ("Prospective", "Advarra"), ("Prospective", "Sterling"),
    ("Ambispective", "Advarra"), ("Ambispective", "Sterling"),
])
def test_authenticated_review_resolves_only_presented_lexical_caution(tmp_path, branch, template):
    warning, request, path, evidence = reviewed_caution(tmp_path, branch, template)
    editorial = {"publication_disposition": "warning", "code": "editorial-repetition"}
    remaining, resolved = quality._reviewed_lexical_warnings([warning, editorial], evidence, [])
    assert remaining == [editorial]
    assert resolved[0]["verification_request_id"] == request["request_id"]
    other = {**warning, "issue": "A new, unreviewed source mismatch."}
    assert quality._reviewed_lexical_warnings([other], evidence, [])[0] == [other]


def test_stale_artifact_or_failed_review_cannot_clear_lexical_caution(tmp_path):
    warning, request, path, evidence = reviewed_caution(tmp_path)
    response_path = tmp_path / request["response_path"]
    response = json.loads(response_path.read_text())
    response["request_sha256"] = "stale"
    response_path.write_text(json.dumps(response))
    findings, evidence = quality.validate_verifications(tmp_path)
    assert findings
    assert quality._reviewed_lexical_warnings([warning], evidence, findings) == ([warning], [])


def test_actual_omission_remains_blocking_and_is_routed_to_drafting(tmp_path):
    warning, request, path, evidence = reviewed_caution(tmp_path)
    response_path = tmp_path / request["response_path"]
    response = json.loads(response_path.read_text())
    response["status"] = "blocked"
    response["findings"] = [{"finding_id": "missing-reminder-call", "category": "content",
        "check": "source_supported", "artifact": "protocol", "target_ids": ["study-design.bias"],
        "issue": "The supplied reminder calls are absent.", "affected_passage": "Unrelated prose",
        "source_excerpt": "Personnel make reminder calls", "contradiction": False}]
    for row in response["section_assessments"]:
        if row["section_id"] == "study-design.bias": row["status"] = "blocked"
    response_path.write_text(json.dumps(response))
    findings, evidence = quality.validate_verifications(tmp_path)
    defect = next(f for f in findings if f.get("check") == "source_supported")
    assert defect["recovery_class"] == "drafting_defect"
    assert quality._reviewed_lexical_warnings([warning], evidence, findings) == ([warning], [])
