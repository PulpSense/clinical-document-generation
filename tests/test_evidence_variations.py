"""Cheap variation bank: supported syntax changes preserve the clinical schedule."""
import copy
import itertools

import pytest
import contracts
import drafting


@pytest.mark.parametrize('positive,negative,reverse', list(itertools.product(
    ['X', 'yes', True, 1, '✓', '✔'], ['', 'no', False, 0, None, '—'], [False, True],
)))
def test_binary_encodings_and_key_order_preserve_the_same_clinical_facts(positive, negative, reverse):
    rows = [
        {'activity': 'Blood draw at 5 mL', 'Week 2': positive, 'Week 6': negative},
        {'activity': 'Vision measured at 66 cm', 'Week 2': negative, 'Week 6': positive},
    ]
    if reverse:
        rows = [dict(reversed(list(row.items()))) for row in rows]
    source = {'procedures': {'visits': ['Week 2', 'Week 6'], 'assessments': rows, 'visit_schedule_table': copy.deepcopy(rows)}}
    original = copy.deepcopy(source)
    clinical = contracts.normalized_visit_records(source)
    assert [(row['visit'], row['procedures']) for row in clinical] == [
        ('Week 2', ['Blood draw at 5 mL']), ('Week 6', ['Vision measured at 66 cm']),
    ]
    for path in ['procedures.assessments', 'procedures.visit_schedule_table']:
        scoped = drafting.section_evidence_value('icf.procedures', path, rows, source)
        assert drafting.source_evidence_grounded('Week 2: Blood draw at 5 mL. Week 6: Vision measured at 66 cm.', path, scoped, all_items=True)
        assert not drafting.source_evidence_grounded('Week 2: Blood draw at 9 mL. Week 6: Vision measured at 66 cm.', path, scoped, all_items=True)
        assert not drafting.source_evidence_grounded('Week 2: Blood draw at 5 mL. Week 6: No assessment.', path, scoped, all_items=True)
    assert source == original


@pytest.mark.parametrize('number,word', [(0,'zero'),(1,'one'),(2,'two'),(6,'six'),(12,'twelve')])
def test_spelled_numbers_preserve_values_without_accepting_a_wrong_quantity(number, word):
    value = f'Blood draw at {number} mL'
    assert drafting.evidence_grounded(f'Blood draw at {word} mL', value)
    assert not drafting.evidence_grounded(f'Blood draw at {number+1} mL', value)
