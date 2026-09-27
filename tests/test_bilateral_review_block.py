"""Replays of the bilateral-study mapping, ownership and verifier failures."""
import copy
import json
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
import contracts
import drafting
import prs_xml
import quality
import rendering
import workflow

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT / 'tests/fixtures/reliability-replays/bilateral-review-block.json').read_text())
TEMPLATE = ROOT / 'assets/client-templates/prs/clinicaltrials_prs_full_placeholder_template.xml'


def source():
    return copy.deepcopy(DATA['source'])


def section_case(section_id):
    request = copy.deepcopy(DATA['request'])
    response = copy.deepcopy(DATA['response'])
    spec = next(s for s in contracts.protocol_contract('Prospective') if s.section_id == section_id)
    boilerplate = {item['boilerplate_id']: item['text'] for section in request['section_contracts'] for item in section.get('fixed_boilerplate', [])}
    request['section_contracts'] = [drafting._section_payload(spec, boilerplate, request['approved_source'])]
    response['section_results'] = [s for s in response['section_results'] if s['section_id'] == section_id]
    return request, response


@pytest.mark.parametrize('value,expected', [
    ('36 subjects per cohort; 72 subjects total', '72'),
    ('24 per arm; total enrollment: 48 participants', '48'),
    ('80 participants (40 per cohort)', '80'),
    ('Total planned sample size: 1,200 participants, 600 per group', '1200'),
    ('72', '72'),
])
def test_enrollment_is_total_regardless_of_text_order(value, expected):
    assert prs_xml._enrollment_count(value) == expected


def test_actual_prs_maps_and_validates_total_and_both_cohort_links(tmp_path):
    ref = source()
    output = tmp_path / 'study.xml'
    prs_xml.generate(TEMPLATE, output, ref, {'brief_summary': {'text': 'Summary.'}, 'detailed_description': {'text': 'Description.'}})
    tree = ET.parse(output)
    study = next(tree.getroot().iter('clinical_study'))
    assert study.findtext('enrollment') == '72'
    labels = [n.text for n in study.findall('intervention/arm_group_label')]
    assert labels == ['Bilateral TECNIS PureSee', 'Bilateral TECNIS Odyssey']
    assert not prs_xml.compare_structure(TEMPLATE, output)
    assert not prs_xml.validate_output(output, ref, TEMPLATE)
    study.find('enrollment').text = '36'
    study.find('intervention').remove(study.findall('intervention/arm_group_label')[-1])
    tree.write(output, encoding='utf-8', xml_declaration=True)
    findings = prs_xml.validate_output(output, ref, TEMPLATE)
    assert any(f['field'] == 'enrollment' for f in findings)
    assert any('arm_group_label' in f['field'] for f in findings)


def test_concise_participant_completion_does_not_require_visit_inventory():
    request, response = section_case('endpoint-criteria.completion')
    result = response['section_results'][0]
    result['paragraphs'] = [{
        'text': 'Participant follow-up is complete after the 6-month assessment following second-eye surgery and completion of the exit form. Participants may withdraw voluntarily at any time. Withdrawal is distinct from completion.',
        'evidence_refs': ['source:procedures.completion'], 'boilerplate_refs': ['completion'],
    }]
    assert not drafting.validate_response(request, response)[1]
    result['paragraphs'][0]['text'] = 'Participant follow-up is complete after the exit form.'
    assert drafting.validate_response(request, response)[1]


def test_study_completion_requires_supplied_closeout_trigger():
    request, response = section_case('endpoint-criteria.study-completion')
    result = response['section_results'][0]
    assert drafting.validate_response(request, response)[1]
    result['paragraphs'][0]['text'] += ' Study data analysis will begin after scheduled follow-up and database checks are complete.'
    result['paragraphs'][0]['evidence_refs'].append('source:study.completion')
    assert not drafting.validate_response(request, response)[1]


def test_followup_synopsis_excludes_enrollment_and_analysis():
    text = rendering._protocol_followup_summary(source())
    assert '6 months after second-eye surgery' in text
    assert 'Enrollment' not in text and 'analysis' not in text


def test_table_notes_remove_only_represented_schedule_and_keep_safety():
    ref = source()
    notes = contracts.protocol_table_contracts(ref)['schedule-of-assessments']['supplemental_notes']
    assert not any('See structured visit schedule' in n for n in notes)
    assert any('from consent through the final study contact' in n for n in notes)
    ref['procedures']['assessments'] += ' Bring all current medications to each visit.'
    notes = contracts.protocol_table_contracts(ref)['schedule-of-assessments']['supplemental_notes']
    assert any('Bring all current medications' in n for n in notes)


def content_fixture(tmp_path, notes):
    rev = tmp_path / 'r1'
    req_path = rev / 'hermes/verification-requests/r1.review-1.verify.content.json'
    req_path.parent.mkdir(parents=True)
    request = {
        'schema_version': 'hermes-verification/v1', 'request_id': 'r1.review-1.verify.content',
        'task': 'clinical_content_verification', 'revision_id': 'r1', 'review_set': 1,
        'artifacts': [], 'approved_source': {}, 'authorized_boilerplate': {},
        'sections': [{'artifact': 'study.xml', 'section_id': 'prs.structured'}],
        'checks': list(quality.CONTENT_CHECKS), 'cross_document_checks': ['population'],
        'instructions': '', 'response_path': 'hermes/verification-responses/content.json',
    }
    request['request_sha256'] = quality.verification_request_sha256(request)
    req_path.write_text(json.dumps(request))
    ledger = rev / 'request-ledger' / (request['request_id'] + '.json')
    ledger.parent.mkdir(parents=True)
    ledger.write_text(json.dumps(quality.verification_request_ledger_record(req_path, request)))
    response = {
        'schema_version': quality.RESPONSE_SCHEMA,
        **{k: request[k] for k in ('request_id', 'request_sha256', 'task', 'revision_id')},
        'producer': {'model_id': 'test-model', 'reviewer_id': 'content-reviewer'},
        'status': 'blocked', 'findings': [{
            'finding_id': 'PRS-Enrollment-Total', 'artifact': 'study.xml',
            'target_ids': ['prs.structured'], 'issue': 'Total enrollment is 36 instead of approved 72.',
            'contradiction': True,
        }],
        'section_assessments': [{'artifact': 'study.xml', 'section_id': 'prs.structured', 'status': 'failed', 'checks': list(quality.CONTENT_CHECKS)}],
        'cross_document_assessments': [{'check': 'population', 'status': 'failed', 'notes': notes}],
    }
    log = tmp_path / 'stdout.log'; log.write_text('Reasoning\n' + json.dumps(response))
    handoff = {'task': request['task'], 'request_path': str(req_path.relative_to(rev)), 'response_path': request['response_path']}
    return rev, handoff, log


def test_parent_consumes_blocking_review_with_cited_cross_document_finding(tmp_path):
    rev, handoff, log = content_fixture(tmp_path, 'PRS-Enrollment-Total: XML differs from approved population.')
    assert workflow._production_publish_quiet_response(rev, handoff, log)
    findings, _ = quality.validate_verifications(rev, request_paths=[rev / handoff['request_path']])
    assert findings  # The error remains blocking, it is not a passing review.
    assert not any(f.get('recovery_class') == 'verifier_transient' for f in findings)


@pytest.mark.parametrize('notes', ['Unexplained population failure.', 'PRS-Enrollment-Total-other: unrelated ID.'])
def test_parent_rejects_uncovered_cross_document_failure(tmp_path, notes):
    rev, handoff, log = content_fixture(tmp_path, notes)
    assert not workflow._production_publish_quiet_response(rev, handoff, log)


@pytest.mark.parametrize('value', ['36 in each cohort', 'Cohort A: 36 participants; Cohort B: 36 participants', '36 subjects per group', '72 total; 80 overall'])
def test_subgroup_only_or_conflicting_sample_size_is_not_a_total(value):
    assert prs_xml._enrollment_count(value) == ''


def test_nested_product_name_does_not_link_unrelated_cohort():
    ref = source()
    ref['design']['arms'] = [{'name': 'Drug A'}, {'name': 'Drug AB'}]
    ref['design']['intervention_name'] = 'Drug AB'
    assert prs_xml._intervention_items(ref)[0]['arm_group_labels'] == ['Drug AB']


def test_new_assessment_timing_relationship_is_not_a_schedule_restatement():
    ref = source()
    ref['procedures']['assessments'] = 'Assessments at 1 month after second-eye surgery.'
    notes = contracts.protocol_table_contracts(ref)['schedule-of-assessments']['supplemental_notes']
    assert ref['procedures']['assessments'] in notes


def test_schedule_qualification_is_not_deleted():
    ref = source()
    ref['procedures']['assessments'] = 'No assessments at Month 1. Only Month 6 assessments are required.'
    notes = contracts.protocol_table_contracts(ref)['schedule-of-assessments']['supplemental_notes']
    assert any('No assessments' in n and 'Only Month 6' in n for n in notes)


def test_completion_cannot_drop_exit_form_while_preserving_duration():
    request, response = section_case('endpoint-criteria.completion')
    response['section_results'][0]['paragraphs'] = [{
        'text': 'Participant follow-up is complete after the 6-month assessment following second-eye surgery. Participants may withdraw voluntarily at any time. Withdrawal is distinct from completion.',
        'evidence_refs': ['source:procedures.completion'], 'boilerplate_refs': ['completion'],
    }]
    assert drafting.validate_response(request, response)[1]


def test_study_completion_citation_cannot_hide_missing_database_checks():
    request, response = section_case('endpoint-criteria.study-completion')
    response['section_results'][0]['paragraphs'][0]['text'] += ' Study data analysis will begin after scheduled follow-up is complete.'
    response['section_results'][0]['paragraphs'][0]['evidence_refs'].append('source:study.completion')
    assert drafting.validate_response(request, response)[1]


@pytest.mark.parametrize('value', ['36 in cohort A and 36 in cohort B', '36 participants in cohort A; 36 participants in cohort B'])
def test_after_number_subgroup_labels_do_not_become_total(value):
    assert prs_xml._enrollment_count(value) == ''


def test_longer_compound_cohort_name_does_not_imply_shorter_cohort():
    ref = source(); ref['design']['arms'] = [{'name': 'Device A'}, {'name': 'Device A Plus'}]
    ref['design']['intervention_name'] = 'Device A Plus'
    assert prs_xml._intervention_items(ref)[0]['arm_group_labels'] == ['Device A Plus']
    ref['design']['intervention_name'] = 'Device A or Device A Plus'
    assert prs_xml._intervention_items(ref)[0]['arm_group_labels'] == ['Device A', 'Device A Plus']


def test_decimal_completion_interval_does_not_require_a_different_integer():
    request, response = section_case('endpoint-criteria.completion')
    value = 'A participant completes study follow-up after the 1.5-month assessment and completion of the exit form.'
    request['approved_source']['procedures']['completion'] = value
    for item in request['approved_input']:
        if item['path'] == 'procedures.completion':
            item['value'] = value
            item['sha256'] = drafting.sha256_value(value)
    response['section_results'][0]['paragraphs'] = [{
        'text': value + ' Withdrawal is distinct from completion.',
        'evidence_refs': ['source:procedures.completion'], 'boilerplate_refs': ['completion'],
    }]
    assert not drafting.validate_response(request, response)[1]
