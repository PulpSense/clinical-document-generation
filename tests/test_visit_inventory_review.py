import copy

from contracts import normalized_visit_records, protocol_table_contracts, timeline_findings


def test_ambiguous_repeated_contacts_are_not_collapsed_into_one_visit():
    reference = {'procedures': {
        'visit_schedule_table': [{'visitName': 'Baseline', 'visitWindow': 'Day 0'}],
        'visit_schedule': [
            {'visit': 'Baseline', 'timing': 'Day 0', 'procedures': ['Consent']},
            {'visit': 'Baseline', 'timing': 'Day 0', 'procedures': ['Device review']},
        ],
    }}
    original = copy.deepcopy(reference)
    rows = normalized_visit_records(reference)
    assert len(rows) == 3
    assert [row['procedures'] for row in rows] == [[], ['Consent'], ['Device review']]
    assert reference == original


def test_unassigned_extra_contact_is_preserved_in_both_table_inventories():
    reference = {'procedures': {
        'visit_schedule_table': [{'visitNumber': 'B', 'visitName': 'Baseline', 'visitWindow': 'Day 0'}],
        'visit_schedule': [{'visitNumber': 'T', 'visit': 'Telephone review', 'timing': 'Day 14'}],
    }}
    original = copy.deepcopy(reference)
    visits = normalized_visit_records(reference)
    tables = protocol_table_contracts(reference)
    assert [(row['visitNumber'], row['visit']) for row in visits] == [('B', 'Baseline'), ('T', 'Telephone review')]
    assessment = next(value for value in tables.values() if value.get('rows') and value['rows'][0][0] == 'Approved visit or assessment')
    assert assessment['rows'][1:] == [['Baseline', 'Day 0'], ['Telephone review', 'Day 14']]
    assert reference == original


def test_trailing_event_label_still_rejects_a_real_timeline_conflict():
    reference = {
        'study': {'timeline': '4 weeks after baseline (interim assessment) and 13 weeks after baseline (final contact).'},
        'procedures': {'visit_schedule': [
            {'visit': 'Baseline', 'timing': 'Day 0'},
            {'visit': 'Interim', 'timing': 'Week 4 after baseline'},
            {'visit': 'Final', 'timing': 'Week 12 after baseline'},
        ]},
    }
    assert timeline_findings(reference)
