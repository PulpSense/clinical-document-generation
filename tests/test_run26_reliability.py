"""Exact drafting replays from the September 26 synthetic study timeout."""
import json
from pathlib import Path

import pytest
import drafting

FIXTURE = Path(__file__).parent / "fixtures/reliability-replays/run26-drafting.json"


def replay(case):
    value = json.loads(FIXTURE.read_text())[case]
    return value["request"], value["response"]


@pytest.mark.parametrize("case", ["background", "methods"])
def test_exact_source_grounded_draft_passes_without_traceability_or_other_section_repetition(case):
    request, response = replay(case)
    accepted, findings = drafting.validate_response(request, response)
    assert findings == []
    assert accepted["drafts"]


def test_background_citation_normalization_preserves_prose_and_canonical_binding():
    request, response = replay("background")
    accepted, findings = drafting.validate_response(request, response)
    assert findings == []
    actual = accepted["drafts"][0]["paragraphs"]
    original = response["section_results"][0]["paragraphs"]
    assert [p["text"] for p in actual] == [p["text"] for p in original]
    assert all(p["evidence_refs"] == ["source:study.background"] for p in actual)


@pytest.mark.parametrize("reference", ["study.unknown", "source:study.unknown", "statistics.analysis_plan"])
def test_unknown_or_unrelated_citation_still_fails(reference):
    request, response = replay("background")
    response["section_results"][0]["paragraphs"][0]["evidence_refs"] = [reference]
    assert drafting.validate_response(request, response)[1]


def test_missing_clinical_numeric_value_still_fails_with_numbered_references():
    request, response = replay("background")
    value = "The trial included 40 participants. " + request["approved_input"][0]["value"]
    request["approved_input"][0]["value"] = value
    request["approved_source"]["study"]["background"] = value
    assert any("not observable" in f["issue"] for f in drafting.validate_response(request, response)[1])


def test_qualified_trial_claim_cannot_be_strengthened():
    request, response = replay("background")
    for p in response["section_results"][0]["paragraphs"]:
        p["text"] = p["text"].replace("suggested better", "demonstrated better")
    assert any("qualified trial" in f["issue"] for f in drafting.validate_response(request, response)[1])


def test_numbered_procedure_values_are_not_treated_as_bibliography():
    assert not drafting.evidence_grounded("Participants attend the study visits.", "1. Screen 40 participants.\n2. Measure vision at 3 months.")
    assert not drafting.evidence_grounded(
        "Participants attend the study visits.",
        "1. Measure vision in 40 participants following the 2024 method, doi:10.1000/example.",
    )


def test_method_scope_keeps_real_method_numbers():
    request, response = replay("methods")
    for item in request["approved_input"]:
        if item["path"] == "statistics.analysis_plan":
            item["value"] += " A 95% confidence interval will be reported."
    assert any("analysis method" in f["issue"] for f in drafting.validate_response(request, response)[1])


def test_population_sentence_containing_a_method_is_not_silently_discarded():
    value = "The analysis population will include a mean estimate with a 95% confidence interval."
    assert drafting._section_evidence_value("analysis-plan.methodology", "statistics.analysis_plan", value) == value
