"""Independent source-review reproductions; no source mutation permitted."""
import copy
import contracts
import pytest


def test_r2_structured_inventory_preserves_record_relationships():
    record = {'assessment': 'Pain rating', 'timing': 'Week 12', 'unit': 'points', 'required': True}
    reference = {'procedures': {'visit_schedule': [
        {'visit': 'Baseline', 'timing': 'Day 0', 'procedures': ['Consent']}], 'evaluation': [record]}}
    original = copy.deepcopy(reference)
    result = table(reference)
    assert not any(row[0].startswith(('Week 12', 'points', 'True')) for row in result['rows'])
    assert result['assessment_inventory'] == [{'record': record, 'source_path': 'procedures.evaluation.0'}]
    notes = ' '.join(result['supplemental_notes'])
    assert all(value in notes for value in ('Pain rating', 'Week 12', 'points', 'required'))
    assert 'Timing not specified' not in str(result)
    assert reference == original


def test_r3_prose_with_explicit_timing_is_a_whole_table_note():
    prose = 'Pain rating at Week 12.'
    result = table({'procedures': {'evaluation': prose}})
    assert result['supplemental_notes'] == [prose]
    assert 'Timing not specified' not in str(result)
    assert not any(prose in row[0] for row in result['rows'])


def timeline_reference(text, visits):
    return {'meta': {'study_type': 'Prospective', 'icf_template': 'Advarra'},
            'study': {'timeline': text}, 'procedures': {'visit_schedule': visits}}


def test_r4_timeline_matches_event_not_first_relative_expression():
    reference = timeline_reference('Interim assessment 4 weeks after baseline; final contact 12 weeks after baseline.', [
        {'visit': 'Baseline', 'timing': 'Day 0'},
        {'visit': 'Interim', 'timing': 'Week 4 after baseline'},
        {'visit': 'Final', 'timing': 'Week 12 after baseline'}])
    assert contracts.timeline_findings(reference) == []
    reference['study']['timeline'] = 'Interim assessment 5 weeks after baseline; final contact 12 weeks after baseline.'
    assert contracts.timeline_findings(reference)


def test_r5_optional_interim_visit_is_not_final():
    reference = timeline_reference('Final contact 12 weeks after baseline.', [
        {'visit': 'Baseline', 'timing': 'Day 0'},
        {'visit': 'Interim', 'timing': 'Week 4 after baseline'}])
    assert contracts.timeline_findings(reference) == []


def test_r6_distinct_explicit_origins_cannot_be_subtracted():
    reference = timeline_reference('Final contact 10 weeks after baseline.', [
        {'visit': 'Baseline', 'timing': 'Week 2 after enrollment'},
        {'visit': 'Final', 'timing': 'Week 14 after randomization'}])
    assert contracts.timeline_findings(reference) == []


def test_r7_duplicate_explicit_ids_are_findings_not_renumbered():
    reference = timeline_reference('', [
        {'visitNumber': '2', 'visit': 'Baseline', 'procedures': ['Consent']},
        {'visitNumber': '2', 'visit': 'Final', 'procedures': ['Pain rating']}])
    original = copy.deepcopy(reference)
    findings = [f for f in contracts.input_findings(reference) if 'visit' in f['field']]
    assert any('duplicate' in f['issue'].lower() for f in findings)
    assert table(reference)['rows'][1] == ['Activity', 'Visit 2', 'Visit 2']
    assert reference == original


def test_original_participant_followup_does_not_invent_a_conflict_from_unknown_origin():
    text = 'Enrollment over 8 months; each participant followed for approximately 11 weeks after baseline.'
    reference = timeline_reference(text, [
        {'visit': 'Baseline device fitting', 'timing': 'Week 2 after surgery'},
        {'visit': 'Final clinic visit', 'timing': 'Week 12'}])
    original = copy.deepcopy(reference)
    findings = contracts.timeline_findings(reference)
    assert findings == []
    assert reference == original


def test_original_schedule_prose_and_completion_remain_whole_notes():
    assessments = ('Screening before surgery includes eligibility; Baseline device fitting at Week 2 after surgery; '
                   'Remote contact at Week 6; Final clinic visit at Week 12. Device-data download and pain rating are collected.')
    evaluation = 'Completion requires the final clinic visit and device return.'
    for visits in ([], [{'visit': 'Baseline device fitting', 'timing': 'Week 2 after surgery', 'procedures': ['Device fitting']},
                       {'visit': 'Final clinic visit', 'timing': 'Week 12', 'procedures': ['Device return']}]):
        reference = {'procedures': {'visit_schedule': visits, 'assessments': assessments, 'evaluation': evaluation}}
        original = copy.deepcopy(reference)
        result = table(reference)
        assert result['supplemental_notes'] == [assessments, evaluation]
        assert 'Timing not specified' not in str(result)
        assert all('Completion' not in row[0] and 'Screening before' not in row[0] for row in result['rows'])
        assert reference == original


def test_known_safety_timing_is_not_missing_on_retrospective_matrix():
    reference = {'meta': {'study_type': 'Retrospective'}, 'procedures': {'visit_schedule': [
        {'visit': 'Chart abstraction', 'procedures': ['Record review']}]},
        'safety': {'monitoring': 'Adverse events are reviewed at each contact.'}}
    result = table(reference)
    assert 'Timing not specified' not in str(result)
    assert reference['safety']['monitoring'] in result['supplemental_notes']


def test_exact_original_wording_and_explicit_completion_are_preserved():
    text = ('Enrollment is expected to last 8 months. Each participant is followed from screening through Week 12, '
            'for approximately 11 weeks after the baseline device fitting.')
    assessments = ['Screening and consent before any study procedures; baseline device fitting at Week 2 after surgery; '
                   'remote check-ins at Weeks 4 and 8; final clinic visit at Week 12. Assessments include device-data '
                   'download, 0-to-10 knee-pain rating, adverse-event review, and usability questionnaire at Week 12.',
                   'Completion of the Week 12 visit and return of the study device.']
    reference = timeline_reference(text, [
        {'visit': 'Baseline device fitting', 'timing': 'Week 2 after surgery', 'procedures': ['Device fitting']},
        {'visit': 'Final clinic visit', 'timing': 'Week 12', 'procedures': ['Device return']}])
    reference['procedures'].update(assessments=assessments, evaluation=None, completion=assessments[1])
    original = copy.deepcopy(reference)
    findings = contracts.timeline_findings(reference)
    assert findings == []
    result = table(reference)
    assert result['supplemental_notes'] == [assessments[0]]
    assert result['assessment_inventory'] == [{'activity': assessments[0], 'source_path': 'procedures.assessments.0'}]
    assert 'Timing not specified' not in str(result)
    assert reference == original


@pytest.mark.parametrize('separator', ['; ', ', ', ' and '])
@pytest.mark.parametrize('interim', ['4', '4.5'])
def test_r4_event_matching_preserves_decimals_and_clause_boundaries(separator, interim):
    reference = timeline_reference(f'Interim assessment {interim} weeks after baseline{separator}final contact 12 weeks after baseline.', [
        {'visit': 'Baseline', 'timing': 'Day 0'},
        {'visit': 'Interim', 'timing': f'Week {interim} after baseline'},
        {'visit': 'Final', 'timing': 'Week 12 after baseline'}])
    assert contracts.timeline_findings(reference) == []


def table(reference):
    return contracts.protocol_table_contracts(reference)['schedule-of-assessments']


def test_r1_each_contact_clause_does_not_govern_final_only_ae():
    reference = {'meta': {'study_type': 'Prospective'}, 'procedures': {'visit_schedule': [
        {'visit': 'Baseline', 'procedures': ['Consent']},
        {'visit': 'Final', 'procedures': ['Pain rating']}]}, 'safety': {
        'monitoring': 'Device function is checked at each contact, while adverse events are reviewed only at the final visit.'}}
    result = table(reference)
    assert not any('adverse event' in row[0].lower() and row[1] == 'X' for row in result['rows'])
    assert reference['safety']['monitoring'] in result['supplemental_notes']
