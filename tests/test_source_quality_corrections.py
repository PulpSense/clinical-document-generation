"""Source fidelity regressions: no invented IDs, timing, or authority."""
import copy
import json
from pathlib import Path

import pytest
import contracts
import drafting

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("shape", ["visit_schedule", "visit_schedule_table"])
@pytest.mark.parametrize("branch", ["Prospective", "Ambispective", "Retrospective"])
def test_normalized_visit_records_preserve_ids_and_source(shape, branch):
    rows = [
        {"visitNumber": "7", "visitName": "Screening", "visitWindow": "Day -7", "procedures": "Consent; Eligibility", "CRFnumber": "S"},
        {"visitNumber": 42, "visit": "Baseline", "timing": "Week 2", "procedures": ["Walking"]},
        {"visit": "Final", "timing": "Week 12", "procedures": "Return"},
    ]
    reference = {"meta": {"study_type": branch}, "procedures": {shape: rows}}
    original = copy.deepcopy(reference)
    assert hasattr(contracts, "normalized_visit_records")
    records = contracts.normalized_visit_records(reference)
    assert [r["visitNumber"] for r in records] == ["7", 42, "3"]
    assert [(r["visit"], r["timing"], r["procedures"]) for r in records] == [
        ("Screening", "Day -7", ["Consent", "Eligibility"]),
        ("Baseline", "Week 2", ["Walking"]), ("Final", "Week 12", ["Return"])]
    assert records[0]["CRFnumber"] == "S"
    assert reference == original
    matrix = contracts.protocol_table_contracts(reference)["schedule-of-assessments"]["rows"]
    assert matrix[1] == ["Activity", "Visit 7", "Visit 42", "Visit 3"]


@pytest.mark.parametrize("branch", ["Prospective", "Ambispective", "Retrospective"])
@pytest.mark.parametrize("shape", ["visit_schedule", "visit_schedule_table"])
def test_mixed_inventory_preserves_unallocated_assessments_and_contact_safety(branch, shape):
    reference = {"meta": {"study_type": branch}, "procedures": {
        shape: [
            {"visit": "Historical abstraction", "procedures": ["Record review"]},
            {"visit": "Screening / consent", "procedures": ["Consent"]},
            {"visit": "Telephone follow-up", "procedures": ["Device check"]}],
        "assessments": "Device check; 0-to-10 knee-pain rating; Data download",
        "evaluation": ["Walking assessment"],
    }, "safety": {"monitoring": "Adverse events are reviewed at each contact."}}
    original = copy.deepcopy(reference)
    table = contracts.protocol_table_contracts(reference)["schedule-of-assessments"]
    rows = table["rows"]
    for label in ("0-to-10 knee-pain rating", "Data download", "Walking assessment"):
        row = next((r for r in rows if label in r[0]), None)
        assert row is not None, label
        assert row[1:] == ["", "", ""]
        assert "timing not specified" in row[0].lower()
    ae = [r for r in rows if "adverse event" in r[0].lower()]
    if branch == "Retrospective":
        assert all("X" not in cell for row in ae for cell in row[1:])
    else:
        assert len(ae) == 1
        assert ae[0][1:] == ["", "X", "X"]
        assert "after consent" in ae[0][0].lower()
    assert reference == original


def test_evaluation_only_inventory_survives_no_structured_schedule():
    rows = contracts.protocol_table_contracts({"procedures": {"evaluation": "Pain rating; Data download"}})["schedule-of-assessments"]["rows"]
    assert any("Pain rating" in row[0] for row in rows)
    assert any("Data download" in row[0] for row in rows)


@pytest.mark.parametrize("branch", ["Prospective", "Ambispective"])
def test_source_rules_constrain_boilerplate_and_section_evidence(branch):
    sections = {s.section_id: s for s in contracts.protocol_contract(branch)}
    assert "procedures.completion" in sections["endpoint-criteria.completion"].evidence
    assert {"procedures.evaluation", "safety.monitoring", "safety.adverse_events"} <= set(sections["evaluation-procedures"].evidence)
    reference = {"procedures": {"completion": "Week 12 visit and device return.", "study_termination": "The sponsor alone may stop the study for feasibility."}}
    boilerplate = json.loads((ROOT / "references/fixed-clinical-boilerplate.json").read_text())["sections"]
    completion = boilerplate["completion"].lower()
    assert "or is discontinued" not in completion
    assert "discontinuation" in completion and "distinct" in completion
    termination = boilerplate["study-termination"].lower()
    assert "sponsor or investigator" not in termination
    assert "approved" in termination and "authority" in termination
    payload = drafting._section_payload(sections["endpoint-criteria.completion"], boilerplate, reference)
    assert "procedures.completion" in payload["minimum_evidence"]
    constraints = " ".join(drafting._request_constraints()).lower()
    assert "source supersedes" in constraints
    assert "must not expand" in constraints


@pytest.mark.parametrize("branch", ["Prospective", "Ambispective", "Retrospective"])
@pytest.mark.parametrize("shape", ["visit_schedule", "visit_schedule_table"])
def test_timeline_conflict_uses_baseline_anchor_not_enrollment_max(branch, shape):
    timeline = "Enrollment over 8 months; final contact approximately 11 weeks after baseline."
    reference = {"meta": {"study_type": branch}, "study": {"timeline": timeline}, "procedures": {shape: [
        {"visit": "Baseline", "timing": "Week 2 postoperative", "procedures": ["Walking"]},
        {"visit": "Final", "timing": "Week 12 postoperative", "procedures": ["Return"]}]}}
    original = copy.deepcopy(reference)
    findings = [f for f in contracts.input_findings(reference) if f["field"] == "study.timeline"]
    assert len(findings) == 1
    assert "baseline" in findings[0]["issue"].lower()
    assert findings[0]["source_values"]["study.timeline"] == timeline
    assert "11" in findings[0]["issue"] and "10" in findings[0]["issue"]
    assert reference == original
    reference["study"]["timeline"] = timeline.replace("11", "10")
    assert not [f for f in contracts.input_findings(reference) if f["field"] == "study.timeline"]


def test_enrollment_only_does_not_limit_participant_followup():
    reference = {"meta": {"study_type": "Prospective"}, "study": {"timeline": "Enrollment over 2 weeks."},
                 "procedures": {"visit_schedule": [{"visit": "Final", "timing": "Week 12 postoperative"}]}}
    assert not [f for f in contracts.input_findings(reference) if f["field"] == "study.timeline"]


def test_baseline_relative_final_does_not_subtract_postoperative_baseline():
    reference = {"meta": {"study_type": "Prospective"}, "study": {"timeline": "Follow-up 12 weeks after baseline."},
                 "procedures": {"visit_schedule": [{"visit": "Baseline", "timing": "Week 2 postoperative"},
                                                      {"visit": "Final", "timing": "Week 12 after baseline"}]}}
    assert not [f for f in contracts.input_findings(reference) if f["field"] == "study.timeline"]


@pytest.mark.parametrize("branch", ["Prospective", "Ambispective"])
def test_no_invented_contact_marks_or_fragmented_prose(branch):
    prose = "Download data, including speed, distance, and cadence, without changing treatment."
    reference = {"meta": {"study_type": branch}, "procedures": {
        "visit_schedule": [{"visitNumber": "2", "visit": "Screening", "timing": "Before consent", "procedures": ["Eligibility"]},
                           {"visit": "Baseline", "timing": "Day 0", "procedures": ["Consent"]}],
        "evaluation": prose}, "safety": {"monitoring": "Adverse events are reviewed at each contact."}}
    visits = contracts.normalized_visit_records(reference)
    assert [row["visitNumber"] for row in visits] == ["2", "3"]
    table = contracts.protocol_table_contracts(reference)["schedule-of-assessments"]
    rows = table["rows"]
    assert sum(prose in row[0] for row in rows) == 1
    assert len(rows) == 6  # headers, two procedures, whole prose, AE
    assert next(row for row in rows if "Adverse event" in row[0])[1:] == ["", "X"]
    assert "no visit assignment inferred" not in str(rows).lower()
    assert table["unallocated_assessments"] == [{"activity": prose, "source_path": "procedures.evaluation"}]
    reference["safety"]["monitoring"] = "Adverse events are not reviewed at each contact."
    rows = contracts.protocol_table_contracts(reference)["schedule-of-assessments"]["rows"]
    assert not any("each contact" in row[0] for row in rows)


def test_incomplete_or_differently_anchored_schedule_is_not_guessed():
    reference = {"study": {"timeline": "Follow-up 11 weeks after baseline."}, "procedures": {"visit_schedule": [
        {"visit": "Baseline", "timing": "Week 2 postoperative"}]}}
    assert contracts.timeline_findings(reference) == []
    reference["procedures"]["visit_schedule"].append({"visit": "Final", "timing": "Week 12 after enrollment"})
    assert contracts.timeline_findings(reference) == []


def test_assessments_only_do_not_create_visit_ids():
    assert hasattr(contracts, "normalized_visit_records")
    assert contracts.normalized_visit_records({"procedures": {"assessments": ["Pain rating", "Download"]}}) == []
