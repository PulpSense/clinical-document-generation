"""Replay both approved schedule representations through actual table construction."""
import copy
import json
from pathlib import Path

import pytest

from contracts import normalized_visit_records, protocol_table_contracts
from contracts import _schedule_activity_identity


def failed_source():
    return json.loads((Path(__file__).parent / "fixtures/reliability-replays/prospective-mixed-visit-representations.json").read_text())


@pytest.mark.parametrize("branch", ["Prospective", "Ambispective"])
def test_mixed_matrix_and_narrative_preserve_three_clinical_stages(branch):
    source = failed_source()
    source["meta"]["study_type"] = branch
    original = copy.deepcopy(source)
    visits = normalized_visit_records(source)
    assert [v["visit"] for v in visits] == [
        "Preoperative screening", "Operative visit for each eye", "Month 3 postoperative"]
    assert [v["timing"] for v in visits] == ["Preoperative", "One visit per eye", "3 months postoperatively"]
    rows = protocol_table_contracts(source)["schedule-of-assessments"]["rows"]
    assert len(rows[0]) == 4
    consent = [r for r in rows[2:] if r[0].casefold() == "informed consent"]
    assert len(consent) == 1 and consent[0][1:] == ["X", "", ""]
    aiolis = [r for r in rows[2:] if r[0] == "AIOLIS"]
    assert len(aiolis) == 1 and aiolis[0][1:] == ["", "", "X"]
    assert source == original


def test_matrix_alias_does_not_merge_distinct_contacts_or_timings():
    source = {"procedures": {
        "visit_schedule_table": [{"Activity": "Questionnaire", "Week 3": "X"}],
        "visit_schedule": [
            {"visit": "Week 3 phone contact", "timing": "Week 3", "procedures": "Questionnaire"},
            {"visit": "Week 3 clinic contact", "timing": "Week 3", "procedures": "Examination"},
        ],
    }}
    assert len(normalized_visit_records(source)) == 3
    source["procedures"]["visit_schedule"] = [{"visit": "Week 3 clinic contact", "timing": "Week 4"}]
    assert len(normalized_visit_records(source)) == 2


def test_activity_normalization_preserves_quantities_and_units():
    source = {"procedures": {
        "visit_schedule_table": [{"Activity": "Blood draw (5mL)", "Screening": "X"}],
        "visit_schedule": [{"visit": "Preoperative screening", "timing": "Preoperative", "procedures": [
            "Blood draw (5 mL)", "Blood draw (6 mL)"]}],
    }}
    visits = normalized_visit_records(source)
    assert len(visits) == 1
    assert visits[0]["procedures"] == ["Blood draw (5mL)", "Blood draw (6 mL)"]


@pytest.mark.parametrize("activity", ["Blood draw (>5 mL)", "Blood draw (≤5 mL)", "Blood draw (5 μL)"])
def test_activity_normalization_preserves_clinical_symbols(activity):
    source = {"procedures": {
        "visit_schedule_table": [{"Activity": "Blood draw (5 mL)", "Screening": "X"}],
        "visit_schedule": [{"visit": "Preoperative screening", "procedures": [activity]}],
    }}
    assert normalized_visit_records(source)[0]["procedures"] == ["Blood draw (5 mL)", activity]


def test_activity_identity_preserves_signed_values_and_ranges():
    assert _schedule_activity_identity("Storage at -5 °C") != _schedule_activity_identity("Storage at 5 °C")
    assert _schedule_activity_identity("Blood draw 5–6 mL") != _schedule_activity_identity("Blood draw 5 6 mL")
    assert _schedule_activity_identity("Dose 1e-3 mg") != _schedule_activity_identity("Dose 1e3 mg")
    assert _schedule_activity_identity("Dose 1,5 mg") != _schedule_activity_identity("Dose 1 5 mg")


def test_explicit_matrix_timepoint_is_not_erased_or_combined():
    source = {"procedures": {
        "visit_schedule_table": [{"Activity": "Questionnaire", "Month 3": "X"}],
        "visit_schedule": [{"visit": "Month 3 postoperative"}],
    }}
    visits = normalized_visit_records(source)
    assert len(visits) == 1 and visits[0]["timing"] == "Month 3"
    source["procedures"]["visit_schedule"] = [{"visit": "Month 3 and Month 6 contacts"}]
    assert len(normalized_visit_records(source)) == 2
