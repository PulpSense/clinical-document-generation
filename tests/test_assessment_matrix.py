import copy
import json
from pathlib import Path

import pytest
import contracts
import drafting

CASES = json.loads((Path(__file__).parent / 'fixtures/reliability-replays/matrix-visits-block.json').read_text())


@pytest.mark.parametrize('case', CASES)
def test_actual_visit_drafts_do_not_require_matrix_marks(case):
    accepted, findings = drafting.validate_response(case['request'], case['response'])
    assert not findings
    assert accepted['drafts']


def test_matrix_reaches_table_with_exact_assignments_and_no_marker_notes():
    source = copy.deepcopy(CASES[-1]['request']['approved_source'])
    original = copy.deepcopy(source)
    table = contracts.protocol_table_contracts(source)['schedule-of-assessments']
    assert table['rows'][0] == ['Activity', 'Screening', 'Operative (each eye)', 'Month 1', 'Month 3', 'Month 6']
    actual = {row[0]: row[1:] for row in table['rows'][2:]}
    for row in source['procedures']['visit_schedule_table']:
        assert actual[row['activity']] == [row[key] for key in table['rows'][0][1:]]
    assert not table['unallocated_assessments']
    assert not any('Screening: X' in note for note in table['supplemental_notes'])
    assert source == original


def test_matrix_and_typed_visits_construct_the_same_schedule():
    matrix = {'procedures': {'assessments': [
        {'activity': 'Blood sample at 5 mL', 'Week 2': 'X', 'Week 6': ''},
        {'activity': 'Questionnaire', 'Week 2': '', 'Week 6': 'X'},
    ]}}
    matrix['procedures']['visit_schedule_table'] = copy.deepcopy(matrix['procedures']['assessments'])
    typed = {'procedures': {'assessments': ['Blood sample at 5 mL', 'Questionnaire'], 'visit_schedule_table': [
        {'visit': 'Week 2', 'timing': 'Week 2', 'procedures': ['Blood sample at 5 mL']},
        {'visit': 'Week 6', 'timing': 'Week 6', 'procedures': ['Questionnaire']},
    ]}}
    assert contracts.protocol_table_contracts(matrix)['schedule-of-assessments']['rows'] == contracts.protocol_table_contracts(typed)['schedule-of-assessments']['rows']


def test_unallocated_matrix_activity_is_retained_without_inventing_a_visit():
    source = copy.deepcopy(CASES[-1]['request']['approved_source'])
    row = {key: '' for key in source['procedures']['assessments'][0]}
    row['activity'] = 'Unscheduled blood draw at 5 mL'
    for path in ('assessments', 'visit_schedule', 'visit_schedule_table'):
        source['procedures'][path].append(copy.deepcopy(row))
    table = contracts.protocol_table_contracts(source)['schedule-of-assessments']
    assert 'Unscheduled blood draw at 5 mL' in table['supplemental_notes']
    assert not any(row[0] == 'Unscheduled blood draw at 5 mL' for row in table['rows'][2:])


@pytest.mark.parametrize('field', ['assessments', 'visit_schedule', 'visit_schedule_table'])
def test_projection_preserves_clinical_facts_but_not_binary_glyphs(field):
    raw = [{'activity': 'Blood sample at 5 mL', 'Week 2': 'X', 'Week 6': ''}]
    original = copy.deepcopy(raw)
    scoped = drafting.section_evidence_value('icf.procedures', f'procedures.{field}', raw)
    assert drafting.evidence_grounded('At Week 2 draw a blood sample at 5 mL; Week 6 has no assigned activity.', scoped, all_items=True)
    assert not drafting.evidence_grounded('At Week 2 draw a blood sample at 9 mL; Week 6 has no assigned activity.', scoped, all_items=True)
    assert raw == original


@pytest.mark.parametrize('value', ['Sometimes', 'Conditional', '5 mg'])
def test_unknown_matrix_cell_is_not_interpreted_as_a_visit_assignment(value):
    raw = [{'activity': 'Study drug', 'Week 2': value}]
    assert drafting.section_evidence_value('icf.procedures', 'procedures.assessments', raw) == raw


def test_missing_clinical_distance_in_real_visit_draft_still_blocks():
    case = copy.deepcopy(CASES[-1])
    for paragraph in case['response']['section_results'][0]['paragraphs']:
        paragraph['text'] = paragraph['text'].replace('66 cm', 'far away')
    accepted, findings = drafting.validate_response(case['request'], case['response'])
    assert findings and not accepted['drafts']


def test_explicit_visit_inventory_order_survives_sorted_matrix_keys():
    source = copy.deepcopy(CASES[-1]['request']['approved_source'])
    for path in ('assessments', 'visit_schedule', 'visit_schedule_table'):
        source['procedures'][path] = [dict(sorted(row.items())) for row in source['procedures'][path]]
    visits = contracts.normalized_visit_records(source)
    assert [row['visit'] for row in visits] == ['Screening', 'Operative (each eye)', 'Month 1', 'Month 3', 'Month 6']
    assert len(visits) == 5


@pytest.mark.parametrize('header', ['required', 'optional', '', 'Cohort A'])
def test_binary_metadata_is_not_an_invented_visit(header):
    raw = [{'activity': 'Blood draw', header: True}]
    assert contracts.assessment_matrix(raw) is None
    assert drafting.section_evidence_value('icf.procedures', 'procedures.assessments', raw) == raw


def test_declared_custom_visit_headers_share_the_same_projection_and_table_policy():
    source = {'procedures': {
        'visits': ['Alpha contact', 'Beta contact'],
        'visit_schedule_table': [{'activity': 'Blood draw at 5 mL', 'Alpha contact': 'X', 'Beta contact': ''}],
    }}
    visits = contracts.normalized_visit_records(source)
    assert [visit['visit'] for visit in visits] == ['Alpha contact', 'Beta contact']
    raw = source['procedures']['visit_schedule_table']
    scoped = drafting.section_evidence_value('icf.procedures', 'procedures.visit_schedule_table', raw, source)
    assert drafting.evidence_grounded('Alpha contact: blood draw at 5 mL; Beta contact has no assigned activities.', scoped, all_items=True)
