"""Construction regressions using manually drafted prompt trials, not model-quality evals."""
import copy
import json
from pathlib import Path

import pytest
from docx import Document

import contracts
import drafting
import rendering

ROOT = Path(__file__).resolve().parents[1]
TRIALS = ROOT / "docs/experiments/prompt-trials"


def trial(name):
    request = json.loads((TRIALS / f"{name}.request.json").read_text())
    response = json.loads((TRIALS / f"{name}.response.json").read_text())
    return request, response


@pytest.mark.parametrize("name", ["near", "comfort", "sparse"])
def test_historical_trial_response_uses_the_production_transport(name):
    request, response = trial(name)
    reference = request["source"]
    # Historical receipts retain their original instructions. Later corrections
    # must not rewrite the record of what produced these manual drafts.
    current = drafting.generation_only_prompt_payload(ROOT, reference, request["section_contracts"])
    assert request["generation_only_prompts"]["prompts"] == current["prompts"]
    count = 0
    for batch in contracts.batch_plan(reference["meta"]["study_type"], reference["meta"]["icf_template"]):
        sections = [s for s in request["section_contracts"] if s["section_id"] in batch.section_ids]
        if not sections:
            continue
        ids = {s["section_id"] for s in sections}
        bound_request = {"task": "section_drafting", "section_contracts": sections,
                         "artifact": batch.artifact, "batch_id": batch.batch_id,
                         "attempts": {sid: 1 for sid in ids}}
        bound_response = {"producer": {"model_id": "Codex manual development trial"},
                          "section_results": [s for s in response["section_results"] if s["section_id"] in ids]}
        accepted = drafting._generation_only_response(bound_request, bound_response)
        count += len(accepted["drafts"])
    assert count == 10


@pytest.mark.parametrize("name", ["near", "comfort"])
def test_generated_icf_keeps_drafted_injury_withdrawal_and_all_site_contacts(name, tmp_path):
    request, response = trial(name)
    source = request["source"]
    icf = {item["section_id"]: item for item in response["section_results"] if item["section_id"].startswith("icf.")}
    rendering.render_documents(ROOT, tmp_path, source, {"protocol": [], "icf": icf, "prs": {}},
                               artifact_names={"icf"}, audit_output=False)
    document = Document(tmp_path / "candidate/icf.docx")
    visible = "\n".join(p.text for p in document.paragraphs)
    for section_id in ["icf.injury", "icf.withdrawal"]:
        for paragraph in icf[section_id]["paragraphs"]:
            assert visible.count(paragraph["text"]) == 1
    assert "Do not promise free treatment" not in visible
    assert "ordinary treatment may be billed" in visible.casefold()
    for site in source["sites"]:
        assert site["facility"]["name"] in visible
        assert site["contact"]["name"] in visible
        assert site["contact"]["business_phone"] in visible
        assert rendering._facility_address(site["facility"]) in visible
    if name == "near":
        front = "\n".join(c.text for row in document.tables[0].rows for c in row.cells)
        assert "Study Site Addresses:" in front
        assert "Clearview Eye Center" in front and "Riverside Vision Clinic" in front
    else:
        assert "GENETIC INFORMATION NONDISCRIMINATION ACT" in visible
        assert "will not receive individual genetic results" in visible
        gina = next(p for p in document.paragraphs if p.text == "GENETIC INFORMATION NONDISCRIMINATION ACT")
        assert gina.runs[0].font.name == "Arial"
        assert gina.runs[0].bold
        gina_body = next(p for p in document.paragraphs if p.text.startswith("A federal law, called"))
        assert all(run.font.name == "Arial" for run in gina_body.runs)
        assert gina_body.paragraph_format.left_indent == 0


@pytest.mark.parametrize("family", ["Advarra", "Sterling"])
def test_paraphrased_rescheduling_rule_is_not_appended_again(family, tmp_path):
    request, response = trial("near")
    source = copy.deepcopy(request["source"])
    source["meta"]["icf_template"] = family
    procedures = next(s for s in response["section_results"] if s["section_id"] == "icf.procedures")
    rendering.render_documents(ROOT, tmp_path, source,
        {"protocol": [], "icf": {"icf.procedures": procedures}, "prs": {}},
        artifact_names={"icf"}, audit_output=False)
    visible = "\n".join(p.text for p in Document(tmp_path / "candidate/icf.docx").paragraphs)
    assert source["procedures"]["retention"] not in visible
    assert visible.count("Staff may contact you once") == 1


def test_sterling_generated_risk_body_uses_body_font_not_annotation_emphasis(tmp_path):
    request, _ = trial("comfort")
    text = "Research testing can cause temporary discomfort."
    model = {"protocol": [], "icf": {"icf.risks": {"paragraphs": [{"text": text}], "lists": []}}, "prs": {}}
    rendering.render_documents(ROOT, tmp_path, request["source"], model,
        artifact_names={"icf"}, audit_output=False)
    document = Document(tmp_path / "candidate/icf.docx")
    paragraph = next(p for p in document.paragraphs if p.text == text)
    assert all(run.font.name == "Arial" and not run.bold and not run.underline for run in paragraph.runs)


def test_completion_draft_is_not_replaced_with_raw_timeline(tmp_path):
    request, response = trial("near")
    source = copy.deepcopy(request["source"])
    source["study"].pop("completion")
    source["study"]["timeline"] += " INTERNAL AUTHORING DIRECTION."
    draft = next(s for s in response["section_results"] if s["section_id"] == "endpoint-criteria.study-completion")
    rendering.render_documents(ROOT, tmp_path, source, {"protocol": [draft], "icf": {}, "prs": {}},
                               artifact_names={"protocol"}, audit_output=False)
    visible = "\n".join(p.text for p in Document(tmp_path / "candidate/protocol.docx").paragraphs)
    assert draft["paragraphs"][0]["text"] in visible
    assert "INTERNAL AUTHORING DIRECTION" not in visible
    assert "18.4. Study Termination" not in visible


def test_followup_is_separate_from_appointment_length():
    request, _ = trial("near")
    source = copy.deepcopy(request["source"])
    assert contracts.participant_followup_summary(source) == "12 weeks after Day 0"
    source["study"].pop("participation_duration")
    source["procedures"]["visit_schedule_table"][-1]["timing"] += "; approximately 35 minutes"
    assert contracts.participant_followup_summary(source) == "Day 84 +/- 7 days after Day 0"


def test_intake_activity_projection_preserves_choices_and_omission_notes():
    request, _ = trial("near")
    table = contracts.protocol_table_contracts(request["source"])["schedule-of-assessments"]
    rows = table["rows"]
    assert any("Reading-glasses use" in row[0] and "never, sometimes, often, always" in row[0] for row in rows)
    assert not any(row[0].startswith("No separate") or row[0] == "Never, sometimes, often, always" for row in rows)
    assert "No separate exit form or extra closeout visit." in table["supplemental_notes"]


def test_ambispective_projection_keeps_phone_tests_separate_from_record_review():
    request, _ = trial("comfort")
    table = contracts.protocol_table_contracts(request["source"])["schedule-of-assessments"]
    rows = table["rows"]
    assert len(rows[0]) == 4  # activity plus three future contacts
    saliva = next(row for row in rows if "saliva collection" in row[0])
    acuity = next(row for row in rows if "visual acuity" in row[0])
    assert saliva[1:] == ["X", "", ""]
    assert acuity[1:] == ["X", "", "X"]
    assert any("existing records" in text for text in table["supplemental_notes"])
