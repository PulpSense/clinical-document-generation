"""Public lifecycle evidence for AI-owned meaning; adapters are not live review proof."""
import json

import pytest

import drafting
import quality
from test_clean_delivery import CASES, ROOT, deliver
from test_handoff_quality import acceptance_verification


@pytest.mark.parametrize('case', [case for case in CASES if case['descriptor']['profile'].startswith('sparse')], ids=lambda case: case['descriptor']['fixture_id'])
def test_concise_paraphrase_and_negation_reach_independent_review_without_rule_decisions(tmp_path, monkeypatch, case):
    source = quality.branch_acceptance_source(ROOT, case)
    reviewed = []

    def draft(request):
        response = drafting.recorded_acceptance_response(request)
        for section in response.get('section_results', []):
            if section['section_id'] == 'introduction':
                section['paragraphs'][0]['text'] = 'Not a clinical trial.'
        return response

    def review(request):
        reviewed.append(request['task'])
        assert not request.get('lexical_review_cautions')
        response = acceptance_verification(request)
        response.pop('uncertainty_resolutions', None)
        return response

    result, revision = deliver(tmp_path, monkeypatch, source, draft=draft, review=review)
    assert result['status'] == 'passed', result
    assert 'clinical_content_verification' in reviewed
    manifest = json.loads((tmp_path / result['manifest']).read_text())
    assert not manifest['quality']['resolved_evidence_cautions']


def test_xml_structure_rejects_duplicate_scalar_even_when_values_are_equal(tmp_path):
    import copy
    from xml.etree import ElementTree as ET
    import prs_xml
    from test_prs_xml import TEMPLATE, MANUAL_REFERENCE, fixture
    source = fixture()
    path = tmp_path / 'study.xml'
    prs_xml.generate(TEMPLATE, path, source, {'brief_summary': 'Summary.', 'detailed_description': 'Description.'})
    tree = ET.parse(path)
    study = next(tree.getroot().iter('clinical_study'))
    study.insert(list(study).index(study.find('brief_title')), copy.deepcopy(study.find('brief_title')))
    tree.write(path)
    findings = prs_xml.validate_output(path, source, MANUAL_REFERENCE, generation_template=TEMPLATE)
    assert any(row['field'] == 'structure' for row in findings)


@pytest.mark.parametrize('mutation', ['malformed', 'missing-node', 'reordered-node', 'missing-repeat'])
def test_xml_structural_failures_remain_detected(tmp_path, mutation):
    from xml.etree import ElementTree as ET
    import prs_xml
    from test_prs_xml import TEMPLATE, MANUAL_REFERENCE, fixture
    source = fixture()
    path = tmp_path / 'study.xml'
    prs_xml.generate(TEMPLATE, path, source, {'brief_summary': 'Summary.', 'detailed_description': 'Description.'})
    if mutation == 'malformed':
        path.write_text('<clinical_study>')
    else:
        tree = ET.parse(path)
        study = next(tree.getroot().iter('clinical_study'))
        tag = 'primary_outcome' if mutation == 'missing-repeat' else 'brief_title'
        node = study.find(tag)
        study.remove(node)
        if mutation == 'reordered-node':
            study.append(node)
        tree.write(path)
    assert prs_xml.validate_output(path, source, MANUAL_REFERENCE, generation_template=TEMPLATE)


def test_xml_values_are_reviewed_by_ai_instead_of_source_comparison_veto(tmp_path):
    from xml.etree import ElementTree as ET
    import prs_xml
    from test_prs_xml import TEMPLATE, MANUAL_REFERENCE, fixture
    source = fixture()
    path = tmp_path / 'study.xml'
    prs_xml.generate(TEMPLATE, path, source, {'brief_summary': 'Summary.', 'detailed_description': 'Description.'})
    tree = ET.parse(path)
    next(tree.getroot().iter('enrollment')).text = '999'
    tree.write(path)
    assert prs_xml.validate_output(path, source, MANUAL_REFERENCE, generation_template=TEMPLATE) == []


def test_corrupt_docx_remains_an_availability_failure(tmp_path):
    import rendering
    path = tmp_path / 'protocol.docx'
    path.write_bytes(b'not-a-docx')
    assert rendering.audit_docx(path)[0]['category'] == 'document-structure'


def test_semantic_intake_interpretation_does_not_veto_present_required_values(tmp_path):
    import workflow
    from test_clean_delivery import reminder_source
    source = reminder_source()
    source['study']['timeline'] = 'Participants are followed for one week after baseline.'
    source['procedures']['visit_schedule'] = [{'visit': 'Baseline', 'timing': 'Day 0'}, {'visit': 'Final', 'timing': 'Month 12'}]
    source['design']['number_of_sites'] = '1'
    source['design']['study_design'] = 'Multicenter observational study.'
    source['sites'][0]['facility']['address'] = 'at the clinic, details in investigator packet'
    reference = tmp_path / 'reference/study.reference.json'
    reference.parent.mkdir()
    reference.write_text(json.dumps(source))
    assert workflow.prepare(tmp_path)['status'] == 'awaiting_approval'
