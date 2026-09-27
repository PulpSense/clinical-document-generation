import copy
import json
from pathlib import Path

import pytest

import drafting

ROOT = Path(__file__).parent
SOURCE = json.loads((ROOT / "fixtures/reliability-replays/sterling-rendered-scope/source.json").read_text())
REPLAY = json.loads((ROOT / 'fixtures/reliability-replays/hypothesis-purpose-block.json').read_text())


def test_accurate_participant_facing_hypothesis_can_pass_drafting():
    accepted, findings = drafting.validate_response(REPLAY['request'], REPLAY['response'])
    assert not findings
    assert accepted is not None


def test_definite_difference_cannot_replace_qualified_hypothesis():
    response = copy.deepcopy(REPLAY['response'])
    paragraph = response['section_results'][0]['paragraphs'][1]
    paragraph['text'] = paragraph['text'].replace('may differ', 'will differ')
    accepted, findings = drafting.validate_response(REPLAY['request'], response)
    assert not accepted or not accepted["drafts"]
    assert any('uncertainty' in finding['issue'].lower() and 'may differ' in finding['next_action'] for finding in findings)


def test_removing_superiority_limitation_cannot_become_a_positive_claim():
    response = copy.deepcopy(REPLAY['response'])
    paragraph = response['section_results'][0]['paragraphs'][1]
    paragraph['text'] = paragraph['text'].replace('not designed to establish', 'designed to establish')
    accepted, findings = drafting.validate_response(REPLAY['request'], response)
    assert not accepted or not accepted['drafts']
    assert any('superiority' in finding['issue'].lower() and 'study.hypothesis' in finding['next_action'] for finding in findings)


def candidate_with_purpose(response):
    from docx import Document
    doc = Document(ROOT / 'fixtures/reliability-replays/sterling-rendered-scope/candidate-3.docx')
    paragraphs = iter(response['section_results'][0]['paragraphs'])
    inside = False
    for paragraph in doc.paragraphs:
        if paragraph.text == 'PURPOSE':
            inside = True
            continue
        if inside and paragraph.text == 'DURATION':
            break
        if inside and paragraph.text.strip() and not paragraph.text.startswith('The study is expected to include'):
            paragraph.text = next(paragraphs)['text']
    return doc


def test_sterling_accepts_same_accurate_purpose_without_a_literal_purpose_word():
    import quality
    doc = candidate_with_purpose(REPLAY['response'])
    result = quality.validate_sterling_clause_contract(doc, REPLAY['request']['approved_source'])
    assert result['status'] == 'passed', result['findings']


def test_existing_review_receives_exact_hypothesis_and_semantic_obligations(tmp_path):
    import quality
    request_path = quality.create_verification_requests(tmp_path, SOURCE, {'artifacts': []})[0]
    request = json.loads(request_path.read_text())
    obligation = next(item for item in request['semantic_evidence'] if item['source_path'] == 'study.hypothesis')
    assert obligation['source_excerpt'] == REPLAY['request']['approved_source']['study']['hypothesis']
    assert 'icf.study-purpose' in obligation['target_ids']
    assert any('uncertainty' in item for item in obligation['requirements'])
    assert 'source_supported' in request['checks']
    assert 'semantic_evidence' in request['instructions']


def test_all_archived_purpose_paraphrases_pass_source_fidelity():
    for attempt in REPLAY['other_actual_attempts']:
        response = copy.deepcopy(REPLAY['response'])
        response['section_results'][0]['paragraphs'] = attempt['paragraphs']
        accepted, findings = drafting.validate_response(REPLAY['request'], response)
        assert not findings, (attempt['attempt'], findings)
        assert accepted['drafts']


def test_wrong_endpoint_distance_remains_blocking():
    response = copy.deepcopy(REPLAY['response'])
    response['section_results'][0]['paragraphs'][2]['text'] = response['section_results'][0]['paragraphs'][2]['text'].replace('66 cm', '60 cm')
    accepted, findings = drafting.validate_response(REPLAY['request'], response)
    assert not accepted or not accepted['drafts']
    assert any('endpoints.primary' in item['issue'] for item in findings)


def test_sterling_rejects_same_amplified_hypothesis_as_drafting():
    import quality
    response = copy.deepcopy(REPLAY['response'])
    response['section_results'][0]['paragraphs'][1]['text'] = response['section_results'][0]['paragraphs'][1]['text'].replace('may differ', 'will differ')
    result = quality.validate_sterling_clause_contract(candidate_with_purpose(response), SOURCE)
    finding = next(item for item in result['findings'] if item['clause_id'] == 'sterling.purpose.study-purpose')
    assert any('uncertainty' in item for item in finding['source_fidelity_details'])


def test_new_drafting_request_carries_shared_obligations(tmp_path):
    from contracts import batch_plan
    batch = next(item for item in batch_plan('Prospective', 'Sterling') if item.batch_id == 'icf-narrative')
    path = drafting.create_drafting_request(repo_root=ROOT.parent, revision_dir=tmp_path, revision_id='r-test', reference=SOURCE, batch=batch, attempts={'icf.study-purpose': 1}, wave='initial', target_ids=('icf.study-purpose',))
    request = json.loads(path.read_text())
    obligation = request['section_contracts'][0]['semantic_evidence'][0]
    assert obligation['source_excerpt'] == SOURCE['study']['hypothesis']
    assert any('negations' in item for item in obligation['requirements'])


def test_reported_missing_hypothesis_facts_remain_blocking_at_review(tmp_path):
    import quality
    request_path = quality.create_verification_requests(tmp_path, SOURCE, {'artifacts': []})[0]
    request = json.loads(request_path.read_text())
    response = {
        'schema_version': quality.RESPONSE_SCHEMA,
        **{key: request[key] for key in ('request_id', 'request_sha256', 'task', 'revision_id')},
        'producer': {'model_id': 'test-verifier', 'reviewer_id': 'independent-test-reviewer'},
        'status': 'blocked',
        'findings': [{
            'finding_id': 'Hypothesis-Missing-Satisfaction', 'category': 'content',
            'check': 'source_supported', 'artifact': 'icf', 'target_ids': ['icf.study-purpose'],
            'issue': 'The purpose omits the supplied expectation of high patient satisfaction from study.hypothesis.',
            'contradiction': False, 'safety_critical': False,
            'obscures_required_information': False, 'materially_unusable': False,
        }],
        'section_assessments': [
            {'artifact': item['artifact'], 'section_id': item['section_id'],
             'status': 'failed' if item['section_id'] == 'icf.study-purpose' else 'passed',
             'checks': list(quality.CONTENT_CHECKS), 'notes': 'Hypothesis-Missing-Satisfaction'}
            for item in request['sections']
        ],
        'cross_document_assessments': [{'check': check, 'status': 'passed'} for check in request['cross_document_checks']],
    }
    (tmp_path / request['response_path']).write_text(json.dumps(response))
    findings, evidence = quality.validate_verifications(tmp_path, request_paths=[request_path])
    defect = next(item for item in findings if 'omits the supplied expectation' in item['issue'])
    assert defect['action'] == 'retry_drafting_target'
    assert defect.get('publication_disposition') != 'warning'
    assert not any(item['recovery_class'] == 'verifier_transient' for item in findings)
    assert next(iter(evidence.values()))['semantic_evidence'] == request['semantic_evidence']


def test_discussing_uncertainty_does_not_assert_definite_difference():
    response = copy.deepcopy(REPLAY['response'])
    paragraph = response['section_results'][0]['paragraphs'][1]
    paragraph['text'] = paragraph['text'].replace('may differ between groups', 'may differ between groups; it is uncertain whether they will differ')
    accepted, findings = drafting.validate_response(REPLAY['request'], response)
    assert not [item for item in findings if 'hypothesis' in item['issue'].lower() or 'uncertainty' in item['issue'].lower()]


def test_introduction_does_not_receive_hypothesis_owner_obligations(tmp_path):
    from contracts import batch_plan
    batch = next(item for item in batch_plan('Prospective') if item.batch_id == 'protocol-foundations')
    path = drafting.create_drafting_request(repo_root=ROOT.parent, revision_dir=tmp_path, revision_id='r-test', reference=SOURCE, batch=batch, attempts={'introduction': 1}, wave='initial', target_ids=('introduction',))
    request = json.loads(path.read_text())
    assert not request['section_contracts'][0]['semantic_evidence']


def test_unrelated_study_design_comparison_is_not_a_hypothesis_reversal():
    response = copy.deepcopy(REPLAY['response'])
    response['section_results'][0]['paragraphs'][1]['text'] += ' This study will differ from earlier studies in its follow-up schedule.'
    _, findings = drafting.validate_response(REPLAY['request'], response)
    assert not [item for item in findings if 'uncertainty' in item['issue'].lower() or 'study.hypothesis' in item['issue']]


@pytest.mark.parametrize("comparison", ["from earlier studies", "between groups"])
def test_schedule_comparison_mentioning_outcomes_is_not_a_clinical_reversal(comparison):
    response = copy.deepcopy(REPLAY['response'])
    response['section_results'][0]['paragraphs'][1]['text'] += f' The follow-up schedule for visual symptom assessments will differ {comparison}.'
    _, findings = drafting.validate_response(REPLAY['request'], response)
    assert not [item for item in findings if 'uncertainty' in item['issue'].lower() or 'study.hypothesis' in item['issue']]


def test_sterling_accepts_equivalent_expectation_wording():
    import quality
    response = copy.deepcopy(REPLAY['response'])
    paragraph = response['section_results'][0]['paragraphs'][1]
    paragraph['text'] = paragraph['text'].replace('Researchers expect', 'Researchers anticipate')
    result = quality.validate_sterling_clause_contract(candidate_with_purpose(response), SOURCE)
    assert result['status'] == 'passed', result['findings']
