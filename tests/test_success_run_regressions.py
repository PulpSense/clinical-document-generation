"""Regressions captured from the September 2026 successful Hermes run."""

import json
from pathlib import Path

import drafting
import pytest
from contracts import batch_plan
from drafting import create_drafting_request, recorded_acceptance_response, validate_response


ROOT = Path(__file__).resolve().parents[1]


def _request_and_response(tmp_path, *, batch_id, icf_template="Advarra"):
    reference = json.loads(
        (ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text(encoding="utf-8")
    )
    reference["meta"]["icf_template"] = icf_template
    batch = next(item for item in batch_plan("Prospective", icf_template) if item.batch_id == batch_id)
    request_path = create_drafting_request(
        repo_root=ROOT,
        revision_dir=tmp_path,
        revision_id=f"r-success-{batch_id}",
        reference=reference,
        batch=batch,
        attempts={section_id: 1 for section_id in batch.section_ids},
        wave="initial",
    )
    request = json.loads(request_path.read_text(encoding="utf-8"))
    return request, recorded_acceptance_response(request)


def test_missing_completion_rule_does_not_force_invented_visit_criterion(tmp_path):
    request, response = _request_and_response(tmp_path, batch_id="protocol-operations")
    assert not request["approved_source"]["procedures"].get("completion")
    completion_contract = next(item for item in request["section_contracts"] if item["section_id"] == "endpoint-criteria.completion")
    assert completion_contract["minimum_evidence"] == ["study.timeline"]
    assert completion_contract["fixed_boilerplate"] == []
    assert completion_contract["allowed_modes"] == ["agent_draft"]
    assert "do not derive one" in completion_contract["content_expectations"][0]
    result = next(item for item in response["section_results"] if item["section_id"] == "endpoint-criteria.completion")
    result["paragraphs"] = [{
        "text": "The planned participant follow-up is 3 months. Participant completion and discontinuation are distinct dispositions; the visit schedule is described in Section 15.",
        "evidence_refs": ["source:study.timeline"],
        "boilerplate_refs": [],
    }]
    result["lists"] = []

    accepted, findings = validate_response(request, response)

    assert not [item for item in findings if item.get("field") == "endpoint-criteria.completion"]
    assert "endpoint-criteria.completion" in {item["section_id"] for item in accepted["drafts"]}


def test_recorded_acceptance_does_not_invent_completion_from_visits(tmp_path):
    request, response = _request_and_response(tmp_path, batch_id="protocol-operations")

    accepted, findings = validate_response(request, response)

    assert not [item for item in findings if item.get("field") == "endpoint-criteria.completion"]
    completion = next(item for item in accepted["drafts"] if item["section_id"] == "endpoint-criteria.completion")
    assert "completes the study after" not in " ".join(p["text"] for p in completion["paragraphs"])


@pytest.mark.parametrize("claim", [
    "A participant completes the study after the Baseline visit on Day 0.",
    "Participant completion is documented on the Month 3 exit form.",
])
def test_missing_completion_rule_rejects_claim_derived_from_visit_schedule(tmp_path, claim):
    request, response = _request_and_response(tmp_path, batch_id="protocol-operations")
    result = next(item for item in response["section_results"] if item["section_id"] == "endpoint-criteria.completion")
    result["paragraphs"] = [{
        "text": claim,
        "evidence_refs": ["source:study.timeline"],
        "boilerplate_refs": [],
    }]
    result["lists"] = []

    accepted, findings = validate_response(request, response)

    assert any("completion criterion" in item["issue"] for item in findings if item.get("field") == "endpoint-criteria.completion")
    assert "endpoint-criteria.completion" not in {item["section_id"] for item in (accepted or {}).get("drafts", [])}


def test_icf_repeated_sentence_is_caught_before_rendering(tmp_path):
    request, response = _request_and_response(tmp_path, batch_id="icf-narrative", icf_template="Sterling")
    results = {item["section_id"]: item for item in response["section_results"]}
    risk_contract = next(item for item in request["section_contracts"] if item["section_id"] == "icf.risks")
    fixed_risk = next(item for item in risk_contract["fixed_boilerplate"] if item["boilerplate_id"] == "icf-sparse-risks")
    repeated = "There is also a risk that private information could be disclosed, although safeguards will be used to protect it."
    summary = results["icf.key-information-summary"]
    risks = results["icf.risks"]
    summary["paragraphs"][0]["text"] += " " + repeated
    risks["paragraphs"] = [{
        "text": fixed_risk["text"],
        "evidence_refs": [],
        "boilerplate_refs": ["icf-sparse-risks"],
    }]

    _, findings = validate_response(request, response)

    assert any(
        item.get("field") == "icf.key-information-summary" and "duplicated" in item["issue"]
        for item in findings
    )


def test_icf_repeated_sentence_is_caught_after_targeted_retry(tmp_path, monkeypatch):
    reference = json.loads(
        (ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text(encoding="utf-8")
    )
    reference["meta"]["icf_template"] = "Sterling"
    repeated = "There is also a risk that private information could be disclosed, although safeguards will be used to protect it."
    drafts = {
        "icf.key-information-summary": {"paragraphs": [{"text": "Study activities may be inconvenient. " + repeated}]},
        "icf.risks": {"paragraphs": [{"text": "Taking part may involve inconvenience. " + repeated}]},
    }
    monkeypatch.setattr(drafting, "accepted_draft", lambda _dir, section_id, _governing: drafts.get(section_id))

    findings = drafting.accepted_cross_section_duplicate_findings(tmp_path, reference, {})

    assert any(item["target_ids"] == ["icf.key-information-summary"] for item in findings)


def test_allowed_static_consent_language_is_not_retried_as_a_duplicate(tmp_path, monkeypatch):
    reference = json.loads(
        (ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text(encoding="utf-8")
    )
    reference["meta"]["icf_template"] = "Sterling"
    voluntary = json.loads(
        (ROOT / "references/fixed-clinical-boilerplate.json").read_text(encoding="utf-8")
    )["sections"]["icf-voluntary"]
    drafts = {
        "icf.key-information-summary": {"paragraphs": [{"text": voluntary}]},
        "icf.alternatives": {"paragraphs": [{"text": voluntary}]},
    }
    monkeypatch.setattr(drafting, "accepted_draft", lambda _dir, section_id, _governing: drafts.get(section_id))

    findings = drafting.accepted_cross_section_duplicate_findings(tmp_path, reference, {})

    assert findings == []
