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


def test_bibliography_bracket_label_is_not_a_clinical_quantity():
    source = "Participants have three months of follow-up.[7]\nReferences:\n7. Doe A. Monitoring study. 2026;20:1-8. doi:10.1234/example."
    assert drafting.evidence_grounded("Participants have three months of follow-up.", source)
    assert not drafting.evidence_grounded("Participants have two months of follow-up.", source)


@pytest.mark.parametrize("number,word", [(13, "thirteen"), (40, "forty"), (35, "thirty-five"), (99, "ninety nine")])
def test_larger_spelled_clinical_numbers_preserve_values(number, word):
    assert drafting.evidence_grounded(f"Blood draw at {word} mL", f"Blood draw at {number} mL")
    assert not drafting.evidence_grounded(f"Blood draw at {number + 1} mL", f"Blood draw at {word} mL")


def test_separate_number_words_do_not_combine_quantities_across_punctuation():
    assert drafting.evidence_grounded("Dose levels are 40, 3 mL.", "Dose levels are forty, three mL.")
