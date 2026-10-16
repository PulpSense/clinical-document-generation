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


@pytest.mark.parametrize("family", ["Advarra", "Sterling"])
def test_withdrawal_fixed_sentences_have_one_owner_and_keep_added_policies(family, tmp_path):
    source = json.loads((ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text())
    source["meta"]["icf_template"] = family
    fixed = rendering._boilerplate(ROOT, rendering.contracted_template_bundle(ROOT, source), source)["icf-withdrawal"]
    opening = " ".join(fixed.split(". ")[:2]) + "."
    details = "Tell or write to your enrolling site's coordinator. Follow-up is optional."
    payment = "Earned payments remain due if you withdraw."
    model = {"protocol": [], "prs": {}, "icf": {"icf.withdrawal": {
        "paragraphs": [{"text": opening + " " + details}, {"text": payment}], "lists": []}}}
    rendering.render_documents(ROOT, tmp_path, source, model, artifact_names={"icf"}, audit_output=False)
    visible = "\n".join(p.text for p in Document(tmp_path / "candidate/icf.docx").paragraphs)
    assert visible.count(opening) == 1
    assert visible.count(details) == 1
    assert visible.count(payment) == 1
    assert fixed in visible
    if family == "Advarra":
        document = Document(tmp_path / "candidate/icf.docx")
        introduction = next(p for p in document.paragraphs if p.text.startswith("This consent document contains important information"))
        assert introduction.paragraph_format.keep_together


def test_labeled_endpoint_groups_survive_drafting_and_native_assembly(tmp_path):
    source = json.loads((ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text())
    section = {"section_id": "study-design.design", "outcome": "drafted",
        "paragraphs": [{"text": "Primary endpoint: Near vision at Week 12."}],
        "lists": [{"label": "Secondary endpoints at Week 12", "items": ["Reading-glasses use.", "Satisfaction."]},
                  {"label": "Exploratory endpoint", "items": ["Change in near vision from Day 0 to Week 6."]}]}
    request = {"task": "section_drafting", "section_contracts": [{"section_id": section["section_id"]}],
               "artifact": "protocol", "batch_id": "test", "attempts": {section["section_id"]: 1}}
    accepted = drafting._generation_only_response(request, {"producer": {"model_id": "manual regression"},
                                                           "section_results": [section]})
    rendering.render_documents(ROOT, tmp_path, source, {"protocol": accepted["drafts"], "icf": {}, "prs": {}},
                               artifact_names={"protocol"}, audit_output=False)
    paragraphs = Document(tmp_path / "candidate/protocol.docx").paragraphs
    texts = [p.text for p in paragraphs]
    secondary = texts.index("Secondary endpoints at Week 12")
    exploratory = texts.index("Exploratory endpoint")
    assert texts[secondary:exploratory+2] == ["Secondary endpoints at Week 12", "Reading-glasses use.",
        "Satisfaction.", "Exploratory endpoint", "Change in near vision from Day 0 to Week 6."]
    for index in [secondary, exploratory]:
        assert not paragraphs[index]._p.xpath("./w:pPr/w:numPr")
    for index in [secondary+1, secondary+2, exploratory+1]:
        assert paragraphs[index]._p.xpath("./w:pPr/w:numPr")


def test_risk_note_edits_remove_only_covered_prose_and_keep_unique_timing(tmp_path):
    source = json.loads((ROOT / "tests/fixtures/prospective-acceptance-source.json").read_text())
    repeated = "Research risks include fatigue and discomfort. Staff may pause testing and refer persistent symptoms."
    unique = "Administer the questionnaire before dilation only."
    mixed = repeated + " " + unique
    source["safety"]["monitoring"] = mixed
    source["safety"]["adverse_events"] = repeated
    source["risks_benefits"]["risks"] = repeated
    source["procedures"]["visit_schedule_table"] = [{"visit": "Week 6", "timing": "Day 42", "procedures": ["Vision test"]}]
    source["procedures"].pop("visit_schedule", None)
    from contracts import assessment_presentation_contract
    context = assessment_presentation_contract(source)
    assert context["related_source"]["risks_section"] == repeated
    assert mixed in context["notes"] and repeated in context["notes"]
    batch = next(b for b in batch_plan("Prospective", source["meta"]["icf_template"])
                 if "evaluation-procedures" in b.section_ids)
    path = drafting.create_drafting_request(repo_root=ROOT, revision_dir=tmp_path,
        revision_id="risk-note", reference=source, batch=batch,
        attempts={target: 1 for target in batch.section_ids}, wave="generation-only")
    request = json.loads(path.read_text())
    response = drafting.recorded_acceptance_response(request)
    section = next(s for s in response["section_results"] if s["section_id"] == "evaluation-procedures")
    section["assessment_presentation"] = {"notes": [
        {"source_text": repeated, "display_text": "", "rationale": "Covered by the safety and risks sections."},
        {"source_text": mixed, "display_text": unique, "rationale": "Retain the unique questionnaire timing; safety sections own the general policy."}]}
    accepted = drafting._generation_only_response(request, response)
    rendering.render_documents(ROOT, tmp_path, source, {"protocol": accepted["drafts"], "icf": {}, "prs": {}},
                               artifact_names={"protocol"}, audit_output=False)
    snapshot = rendering.protocol_section_snapshot(tmp_path / "candidate/protocol.docx", "evaluation-procedures")
    paragraphs = [item["paragraph"] for item in snapshot if "paragraph" in item]
    assert unique in paragraphs
    assert not any(repeated in text for text in paragraphs)


@pytest.mark.parametrize('anchor', ['screening', 'Day 0', 'enrollment'])
def test_xml_keeps_supplied_exclusion_interval_once_with_its_conditions(anchor, tmp_path):
    from xml.etree import ElementTree as ET
    import prs_xml
    source = json.loads((ROOT / 'tests/fixtures/prospective-acceptance-source.json').read_text())
    source['procedures']['minimum_days_before_screening_without_participation'] = '30'
    rule = f'Participation in another interventional research study within the 30 days before {anchor}, or planned participation during follow-up.'
    source['population']['inclusion_criteria'] = ['Able to consent.']
    source['population']['exclusion_criteria'] = [rule]
    output = tmp_path / 'study.xml'
    template = ROOT / 'assets/client-templates/prs/clinicaltrials_prs_full_placeholder_template.xml'
    prs_xml.generate(template, output, source, {'brief_summary': 'Summary.', 'detailed_description': 'Description.'}, check_output=False)
    text = next(ET.parse(output).getroot().iter('clinical_study')).findtext('eligibility/criteria/textblock')
    assert rule in text
    assert text.count('30 days') == 1
    assert 'At least 30 days without' not in text
    assert text.split('Exclusion Criteria:')[0].strip() == 'Inclusion Criteria:\n• Able to consent.'


@pytest.mark.parametrize('existing', ['', 'Participation in another interventional study within 60 days before screening.'])
def test_xml_still_adds_interval_when_no_same_period_is_supplied(existing, tmp_path):
    from xml.etree import ElementTree as ET
    import prs_xml
    source = json.loads((ROOT / 'tests/fixtures/prospective-acceptance-source.json').read_text())
    source['procedures']['minimum_days_before_screening_without_participation'] = '30'
    source['population']['inclusion_criteria'] = ['Able to consent.']
    source['population']['exclusion_criteria'] = [existing] if existing else []
    output = tmp_path / 'study.xml'
    template = ROOT / 'assets/client-templates/prs/clinicaltrials_prs_full_placeholder_template.xml'
    prs_xml.generate(template, output, source, {'brief_summary': 'Summary.', 'detailed_description': 'Description.'}, check_output=False)
    text = next(ET.parse(output).getroot().iter('clinical_study')).findtext('eligibility/criteria/textblock')
    assert text.count('30 days') == 1
    assert 'At least 30 days without participation' in text
    if existing:
        assert existing in text


def test_withdrawal_fixed_only_fallback_is_retained_once():
    fixed = 'Participation is voluntary. You may leave without penalty.'
    model = {'icf': {'icf.withdrawal': {'paragraphs': [{'text': fixed}], 'lists': []}}}
    assert rendering._icf_withdrawal_blocks(model, {'icf-withdrawal': fixed}) == [(fixed, False)]
    assert rendering._icf_withdrawal_blocks({'icf': {}}, {'icf-withdrawal': fixed}) == [(fixed, False)]


def test_current_prompts_assign_endpoint_note_and_withdrawal_ownership():
    source = json.loads((ROOT / 'tests/fixtures/prospective-acceptance-source.json').read_text())
    payload = drafting.generation_only_prompt_payload(ROOT, source, [
        {'section_id': key} for key in ['study-design.design', 'evaluation-procedures', 'icf.withdrawal']])
    corrections = payload['editorial_corrections']
    assert "label 'Exploratory endpoint'" in ' '.join(corrections['study-design.design'])
    assert 'related_source' in ' '.join(corrections['evaluation-procedures'])
    assert 'Assembly supplies the exact authorized' in ' '.join(corrections['icf.withdrawal'])
