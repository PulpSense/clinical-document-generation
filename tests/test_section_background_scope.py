import copy
import json
from pathlib import Path

import pytest
import contracts
import drafting

DATA = json.loads((Path(__file__).parent / 'fixtures/reliability-replays/bilateral-background-block.json').read_text())


@pytest.mark.parametrize('case', DATA)
def test_archived_background_drafts_pass_with_the_background_scope(case):
    request = copy.deepcopy(case['request'])
    section = next(s for s in contracts.icf_contract('Prospective', 'Sterling') if s.section_id == 'icf.background')
    request['section_contracts'] = [drafting._section_payload(section, {}, request['approved_source'])]
    assert not drafting.validate_response(request, case['response'])[1]


def test_drafting_and_validation_share_background_projection():
    source = copy.deepcopy(DATA[0]['request']['approved_source'])
    section = next(s for s in contracts.icf_contract('Prospective', 'Sterling') if s.section_id == 'icf.background')
    payload = drafting._section_payload(section, {}, source)
    scope = next(s['value'] for s in payload['evidence_scopes'] if s['path'] == 'study.background')
    assert 'The objective is' not in scope
    assert 'Lens selection will' not in scope
    assert 'randomized controlled trial' in scope
    assert 'They do not establish which lens' in scope
    assert scope == drafting._section_evidence_value('icf.background', 'study.background', source['study']['background'])


def test_prior_trial_numbers_still_require_coverage():
    background = 'A prior trial followed 120 patients for 6 months. Evidence remains limited.\n\nThe objective is to measure near vision at 3 months.'
    scope = drafting._section_evidence_value('icf.background', 'study.background', background)
    assert '120' in scope and '6 months' in scope
    assert '3 months' not in scope
    assert not drafting.evidence_grounded('A prior trial followed patients. Evidence remains limited.', scope)


def test_purpose_and_design_keep_full_source_evidence():
    value = DATA[0]['request']['approved_source']['study']['background']
    assert drafting._section_evidence_value('icf.study-purpose', 'study.background', value) == value
    assert drafting._section_evidence_value('study-design.design', 'study.background', value) == value


def test_both_groups_preserves_two_but_not_three():
    assert drafting.evidence_grounded('Both groups follow the same schedule.', 'Two cohorts follow the same schedule.')
    assert not drafting.evidence_grounded('Both groups follow the same schedule.', 'Three cohorts follow the same schedule.')


def test_background_without_proposal_blocks_is_not_rewritten():
    value = 'A prior randomized trial followed 120 patients for 6 months.\n\nEvidence for the new treatment remains limited.'
    assert drafting._section_evidence_value('icf.background', 'study.background', value) == value.replace('\n\n', ' ')


def test_intro_uses_same_projection_as_background():
    value = DATA[0]['request']['approved_source']['study']['background']
    assert drafting._section_evidence_value('introduction', 'study.background', value) == drafting._section_evidence_value('icf.background', 'study.background', value)


def test_mixed_objective_paragraph_retains_later_prior_evidence():
    value = 'Clinical context is limited.\n\nThe objective is to measure near vision at 3 months. A prior trial followed 120 patients for 6 months. Evidence for this treatment remains limited.'
    scope = drafting._section_evidence_value('icf.background', 'study.background', value)
    assert '3 months' not in scope
    assert '120 patients for 6 months' in scope
    assert 'Evidence for this treatment remains limited' in scope
    assert not drafting.evidence_grounded('Clinical context is limited. Evidence remains limited.', scope)


def test_both_groups_cannot_supply_missing_duration_number():
    assert not drafting.evidence_grounded('Both groups follow the same schedule for weeks.', 'Two cohorts follow the same schedule for 2 weeks.')
