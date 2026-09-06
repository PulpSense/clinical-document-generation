"""Remaining independent SOURCE review regressions."""
import copy

import contracts
import pytest


@pytest.mark.parametrize("source", [
    "Adverse events are reviewed only at the final visit rather than at each contact.",
    "Adverse events are reviewed at the final visit rather than at each contact.",
    "Device function is checked at each contact;adverse events are reviewed only at the final visit.",
    "Device function is checked at each contact; adverse events are reviewed only at the final visit.",
    "Device function is checked at each contact and adverse events are reviewed only at the final visit.",
    "Adverse events are not reviewed at each contact.",
    "Adverse events are reviewed at the final visit instead of at every contact.",
])
def test_final_only_or_negative_ae_does_not_authorize_contact_marks(source):
    reference = {
        "meta": {"study_type": "Prospective"},
        "procedures": {
            "visit_schedule": [
                {"visitNumber": "7", "visit": "Baseline", "procedures": ["Consent"]},
                {"visitNumber": 42, "visit": "Final", "procedures": ["Pain rating"]},
            ],
            "evaluation": "Device-data download and pain rating are collected at the final visit.",
        },
        "safety": {"monitoring": source},
    }
    original = copy.deepcopy(reference)
    table = contracts.protocol_table_contracts(reference)["schedule-of-assessments"]
    assert table["each_contact_safety_evidence"] == []
    assert not any("each contact" in row[0] for row in table["rows"])
    assert table["rows"][1] == ["Activity", "Visit 7", "Visit 42"]
    assert table["supplemental_notes"] == [reference["procedures"]["evaluation"], source]
    assert reference == original


def timeline_reference(text):
    return {
        "study": {"timeline": text},
        "procedures": {"visit_schedule": [
            {"visitNumber": "7", "visit": "Baseline", "timing": "Day 0"},
            {"visitNumber": 42, "visit": "Interim", "timing": "Week 4 after baseline"},
            {"visitNumber": "F", "visit": "Final", "timing": "Week 12 after baseline"},
        ]},
    }


@pytest.mark.parametrize("separator", [" with ", " followed by ", ";", ", ", " and "])
@pytest.mark.parametrize("reverse", [False, True])
def test_each_duration_matches_its_own_named_event(separator, reverse):
    events = ["Interim assessment 4 weeks after baseline", "final contact 12 weeks after baseline"]
    if reverse:
        events.reverse()
    reference = timeline_reference(separator.join(events) + ".")
    original = copy.deepcopy(reference)
    assert contracts.timeline_findings(reference) == []
    assert reference == original


@pytest.mark.parametrize("correct,wrong", [("4", "5"), ("12", "13")])
def test_local_event_duration_still_detects_real_conflict(correct, wrong):
    text = "Interim assessment 4 weeks after baseline with final contact 12 weeks after baseline."
    reference = timeline_reference(text.replace(f"{correct} weeks", f"{wrong} weeks"))
    original = copy.deepcopy(reference)
    findings = contracts.timeline_findings(reference)
    assert len(findings) == 1
    assert f"{wrong} weeks after baseline" in findings[0]["issue"]
    assert f"{correct} weeks after baseline" in findings[0]["issue"]
    assert findings[0]["source_values"]["study.timeline"] == reference["study"]["timeline"]
    assert reference == original


@pytest.mark.parametrize("text", [
    "Interim or final assessment 12 weeks after baseline.",
    "Interim and final assessments 12 weeks after baseline.",
    "Interim/final assessment 12 weeks after baseline.",
    "Assessments 4 weeks after baseline with 12 weeks after baseline.",
])
def test_ambiguous_event_duration_relationship_is_not_a_contradiction(text):
    reference = timeline_reference(text)
    original = copy.deepcopy(reference)
    assert contracts.timeline_findings(reference) == []
    assert reference == original


def test_multiple_matching_scheduled_events_are_not_guessed():
    reference = timeline_reference("Interim assessment 4 weeks after baseline.")
    reference["procedures"]["visit_schedule"].append(
        {"visit": "Interim assessment B", "timing": "Week 8 after baseline"})
    assert contracts.timeline_findings(reference) == []
