"""Native assembly preserves authored timing instead of appending literal recaps."""
import json
from pathlib import Path

import pytest
from docx import Document

import rendering
import drafting
from contracts import batch_plan

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("family", ["Advarra", "Sterling"])
def test_icf_plain_language_timing_does_not_get_a_second_schedule(family, tmp_path):
    source = json.loads((ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text())
    source["meta"]["icf_template"] = family
    source["procedures"]["visit_schedule_table"] = [
        {"visit": "Month 3 postoperative", "timing": "3 months postoperative", "procedures": ["Vision test"]}]
    source["procedures"].pop("visit_schedule", None)
    prose = "At the follow-up visit three months after surgery, you will have a vision test."
    model = {"protocol": [], "prs": {}, "icf": {"icf.procedures": {
        "paragraphs": [{"text": prose}], "lists": []}}}
    rendering.render_documents(ROOT, tmp_path, source, model, artifact_names={"icf"}, audit_output=False)
    document = Document(tmp_path / "candidate/icf.docx")
    texts = [p.text for p in document.paragraphs]
    assert prose in texts
    assert not any("Scheduled visit windows:" in text for text in texts)


def test_model_note_edits_survive_handoff_and_preserve_unique_instructions(tmp_path):
    source = json.loads((ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text())
    repeated = "The planned assessment is a vision test at the follow-up visit."
    unique = "Collect the questionnaire before dilation only."
    source["procedures"]["visit_schedule_table"] = [
        {"visit": "Follow-up", "timing": "Week 6", "procedures": ["Vision test"]}]
    source["procedures"].pop("visit_schedule", None)
    source["procedures"]["assessments"] = [repeated, unique]
    batch = next(b for b in batch_plan("Prospective", source["meta"]["icf_template"])
                 if "evaluation-procedures" in b.section_ids)
    path = drafting.create_drafting_request(repo_root=ROOT, revision_dir=tmp_path,
        revision_id="note-edit", reference=source, batch=batch,
        attempts={target: 1 for target in batch.section_ids}, wave="generation-only")
    request = json.loads(path.read_text())
    response = drafting.recorded_acceptance_response(request)
    section = next(s for s in response["section_results"] if s["section_id"] == "evaluation-procedures")
    section["assessment_presentation"] = {"notes": [{"source_text": repeated,
        "display_text": "", "rationale": "Vision test and its follow-up relationship are already in the table."}]}
    accepted, findings = drafting.validate_response(request, response)
    assert not findings
    rendering.render_documents(ROOT, tmp_path, source,
        {"protocol": accepted["drafts"], "icf": {}, "prs": {}},
        artifact_names={"protocol"}, audit_output=False)
    snapshot = rendering.protocol_section_snapshot(tmp_path / "candidate/protocol.docx", "evaluation-procedures")
    paragraphs = [item["paragraph"] for item in snapshot if "paragraph" in item]
    assert repeated not in paragraphs
    assert unique in paragraphs
    assert any(row == ["Vision test", "X"] for item in snapshot if "table" in item for row in item["table"])
