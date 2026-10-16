"""Omit exact repeated table assignments, retaining additional source meaning."""
import copy
import json
from pathlib import Path

import pytest

from contracts import protocol_table_contracts


def source(activity="Monitor for Adverse Events and Device Deficiencies", matrix=False):
    visits = [{"visit": "Week 2", "timing": "Week 2", "procedures": [activity]},
              {"visit": "Week 6", "timing": "Week 6", "procedures": ["Questionnaire"]}]
    schedule = ([{"activity": activity, "Week 2": "X", "Week 6": ""},
                 {"activity": "Questionnaire", "Week 2": "", "Week 6": "X"}]
                if matrix else visits)
    return {"meta": {"study_type": "Prospective"}, "procedures": {"visit_schedule_table": schedule}}


@pytest.mark.parametrize("matrix", [False, True])
@pytest.mark.parametrize("activity", ["Monitor for Adverse Events and Device Deficiencies", "Blood sample at 5 mL"])
@pytest.mark.parametrize("wording", ["{activity} at Week 2.", "Week 2: {activity}.", "At Week 2, {activity}."])
def test_table_assignment_is_not_repeated_as_safety_note(matrix, activity, wording):
    reference = source(activity, matrix)
    reference["safety"] = {"monitoring": wording.format(activity=activity)}
    original = copy.deepcopy(reference)
    table = protocol_table_contracts(reference)["schedule-of-assessments"]
    assert table["supplemental_notes"] == []
    assert any(row[0] == activity and row[1:] == ["X", ""] for row in table["rows"][2:])
    assert reference == original


def test_only_repeated_sentence_is_removed_and_new_instruction_survives():
    reference = source()
    reference["safety"] = {"adverse_events":
        "Monitor for Adverse Events and Device Deficiencies at Week 2. Report serious events within 24 hours."}
    assert protocol_table_contracts(reference)["schedule-of-assessments"]["supplemental_notes"] == [
        "Report serious events within 24 hours."]


@pytest.mark.parametrize("note", [
    "Monitor for Adverse Events and Device Deficiencies at Week 6.",
    "Monitor for Adverse Events and Device Deficiencies only at Week 2.",
    "Do not monitor for Adverse Events and Device Deficiencies at Week 2.",
    "Monitor for Adverse Events and Device Deficiencies at Week 2 if clinically indicated.",
    "Monitor for Adverse Events and Device Deficiencies at Week 2 and by phone between visits.",
    "The investigator monitors adverse events and device deficiencies at Week 2.",
    "Review adverse events at every study contact after consent.",
])
def test_changed_timing_scope_actor_or_qualification_is_retained(note):
    reference = source()
    reference["safety"] = {"monitoring": note}
    assert note in protocol_table_contracts(reference)["schedule-of-assessments"]["supplemental_notes"]


def test_note_is_retained_without_a_marked_table_relationship():
    reference = {"procedures": {"visit_schedule": [{"visit": "Week 2", "timing": "Week 2"}]},
                 "safety": {"monitoring": "Blood draw at Week 2."}}
    assert protocol_table_contracts(reference)["schedule-of-assessments"]["supplemental_notes"] == ["Blood draw at Week 2."]


def test_shared_timing_alias_does_not_hide_an_ambiguous_note():
    reference = source("Blood draw")
    for visit in reference["procedures"]["visit_schedule_table"]:
        visit["timing"] = "Day 0"
    reference["safety"] = {"monitoring": "Blood draw at Day 0."}
    assert protocol_table_contracts(reference)["schedule-of-assessments"]["supplemental_notes"] == ["Blood draw at Day 0."]


@pytest.mark.parametrize("qualification", ["Only if clinically indicated.", "This includes a telephone review.",
                                            "Repeat when clinically indicated."])
def test_cross_sentence_qualification_keeps_its_activity_context(qualification):
    reference = source()
    note = "Monitor for Adverse Events and Device Deficiencies at Week 2. " + qualification
    reference["safety"] = {"monitoring": note}
    assert note in protocol_table_contracts(reference)["schedule-of-assessments"]["supplemental_notes"]


def test_native_protocol_keeps_the_table_and_omits_its_repeated_note(tmp_path):
    import rendering
    root = Path(__file__).resolve().parents[1]
    reference = json.loads((root / "tests/fixtures/prospective-acceptance-source.json").read_text())
    reference["procedures"] = source()["procedures"]
    note = "Monitor for Adverse Events and Device Deficiencies at Week 2."
    reference["safety"] = {"monitoring": note + " Report serious events within 24 hours."}
    rendering.render_documents(root, tmp_path, reference, {"protocol": [], "icf": {}, "prs": {}},
                               artifact_names={"protocol"}, audit_output=False)
    section = rendering.protocol_section_snapshot(tmp_path / "candidate/protocol.docx", "evaluation-procedures")
    paragraphs = [item.get("paragraph", "") for item in section]
    assert note not in paragraphs
    assert "Report serious events within 24 hours." in paragraphs
    tables = [item["table"] for item in section if "table" in item]
    assert any(row == ["Monitor for Adverse Events and Device Deficiencies", "X", ""]
               for table in tables for row in table)
