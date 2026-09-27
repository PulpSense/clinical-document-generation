"""Clinical visit evidence must not require structural row identifiers in prose."""
import copy
import json
from pathlib import Path
import pytest
import contracts
import drafting

DATA = json.loads((Path(__file__).parent / 'fixtures/reliability-replays/icf-procedures-visit-identifiers.json').read_text())


@pytest.mark.parametrize('case', DATA)
def test_archived_procedure_drafts_are_not_blocked_by_visit_identifiers(case):
    assert not drafting.validate_response(case['request'], case['response'])[1]


@pytest.mark.parametrize('path', ['procedures.visit_schedule', 'procedures.visit_schedule_table'])
@pytest.mark.parametrize('key', ['visitNumber', 'visit_number'])
def test_request_and_validation_scope_excludes_only_row_identifier(path, key):
    value = [{'visit': 'Month 3', 'timing': '3 months after surgery', 'procedures': 'Test at 40 cm', key: '987'}]
    original = copy.deepcopy(value)
    scoped = drafting._section_evidence_value('icf.procedures', path, value)
    assert scoped == [{'visit': 'Month 3', 'timing': '3 months after surgery', 'procedures': 'Test at 40 cm'}]
    assert value == original
    source = {'procedures': {path.rsplit('.', 1)[1]: value}}
    if path == 'procedures.visit_schedule_table':
        section = next(s for s in contracts.protocol_contract('Prospective') if s.section_id == 'evaluation-procedures')
    else:
        section = next(s for s in contracts.icf_contract('Prospective', 'Sterling') if s.section_id == 'icf.procedures')
    payload = drafting._section_payload(section, {}, source)
    assert next(s['value'] for s in payload['evidence_scopes'] if s['path'] == path) == scoped
    assert drafting.evidence_grounded('Month 3, 3 months after surgery, test at 40 cm.', scoped, all_items=True)
    assert not drafting.evidence_grounded('Month 3, 3 months after surgery, test at 66 cm.', scoped, all_items=True)


def test_explicit_number_in_visit_name_is_still_clinical_evidence():
    value = [{'visit': 'Visit 9', 'visitNumber': '9', 'timing': 'Week 2', 'procedures': 'Blood sample'}]
    scoped = drafting._section_evidence_value('icf.procedures', 'procedures.visit_schedule', value)
    assert not drafting.evidence_grounded('Visit at Week 2 for a blood sample.', scoped, all_items=True)


def test_metadata_outside_a_visit_schedule_is_untouched():
    value = [{'visitNumber': '9', 'dose': '5 mg'}]
    assert drafting._section_evidence_value('icf.procedures', 'procedures.assessments', value) == value


def test_archived_draft_with_missing_clinical_distance_still_fails():
    case = copy.deepcopy(DATA[-1])
    for block in case['response']['section_results'][0]['lists']:
        block['items'] = [item.replace('66 cm', 'far away') for item in block['items']]
    assert drafting.validate_response(case['request'], case['response'])[1]


@pytest.mark.parametrize('identifiers', [['101', '102', '103', '104', '105'], ['A', 'B', 'C', 'D', 'E']])
def test_structural_identifier_changes_do_not_change_narrative_verdict(identifiers):
    case = copy.deepcopy(DATA[-1])
    for field in case['request']['approved_input']:
        if field['path'] == 'procedures.visit_schedule':
            for record, identifier in zip(field['value'], identifiers):
                record['visitNumber'] = identifier
            field['sha256'] = drafting.sha256_value(field['value'])
    for record, identifier in zip(case['request']['approved_source']['procedures']['visit_schedule'], identifiers):
        record['visitNumber'] = identifier
    assert not drafting.validate_response(case['request'], case['response'])[1]


def test_structured_table_keeps_original_visit_numbers():
    source = copy.deepcopy(DATA[-1]['request']['approved_source'])
    original = copy.deepcopy(source)
    drafting._section_evidence_value('icf.procedures', 'procedures.visit_schedule', source['procedures']['visit_schedule'])
    assert source == original
    table = contracts.protocol_table_contracts(source)['schedule-of-assessments']
    assert table['rows'][1][1:] == ['Visit 1', 'Visit 2', 'Visit 3', 'Visit 4', 'Visit 5']
