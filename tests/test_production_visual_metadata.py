"""Response discovery respects semantic descendants, not just matching key names."""
import copy
import json

import pytest
import workflow
from test_visual_units import parent_fixture, response_for
from visual_review import create_visual_review_unit, visual_review_unit_result
from test_production_visual_incomplete import test_production_missing_visual_scope_reaches_only_safe_fallback as exercise


def unit_fixture(tmp_path):
    revision, parent_path, parent = parent_fixture(tmp_path, 'retrospective', count=1)
    path = create_visual_review_unit(revision, parent_path, parent['visual_review_plan']['targets'][:1], 1)
    unit = json.loads(path.read_text())
    response = response_for(unit)
    handoff = {'visual_unit': True, 'task': unit['task'], 'request_id': unit['request_id'],
        'request_path': path.relative_to(revision).as_posix(), 'response_path': unit['response_path']}
    final = revision / unit['response_path']
    final.parent.mkdir(parents=True, exist_ok=True)
    stdout = tmp_path / 'stdout.log'
    return revision, path, handoff, response, final, stdout


@pytest.mark.parametrize('envelope', ['direct', 'response', 'nested'])
@pytest.mark.parametrize('placement', ['assessment', 'finding', 'metadata'])
def test_parser_accepts_genuine_nested_metadata(tmp_path, envelope, placement):
    revision, path, handoff, response, final, stdout = unit_fixture(tmp_path)
    producer = copy.deepcopy(response['producer'])
    row = response['visual_assessments'][0]
    if placement == 'assessment':
        row['producer'] = producer
    elif placement == 'finding':
        row['status'] = 'blocked'
        response['findings'] = [{'target_id': row['target_id'], 'artifact': row['artifact'],
            'page': row['pages'][0]['page'], 'check': row['checks'][0],
            'element': 'Controlled paragraph', 'recommended_action': 'Repair controlled defect',
            'issue': 'Controlled retained concern', 'producer': producer}]
    else:
        row['metadata'] = {'reviewer': {'producer': producer}, 'task': 'reviewer metadata, not a final'}
    original = copy.deepcopy(response)
    final.write_text(json.dumps(response))
    assert visual_review_unit_result(revision, path)['complete']
    payload = response if envelope == 'direct' else {'response': response}
    if envelope == 'nested':
        payload = {'envelope': {'response': response}}
    stdout.write_text(json.dumps(payload))
    assert workflow._production_publish_quiet_response(revision, handoff, stdout)
    assert json.loads(final.read_text()) == original
    retained = visual_review_unit_result(revision, path)
    assert retained['complete']
    if placement == 'finding':
        assert retained['findings'] and retained['assessments'][0]['status'] == 'blocked'


@pytest.mark.parametrize('ordering', ['bad-first', 'bad-last', 'envelope'])
@pytest.mark.parametrize('fault', ['hash', 'request_id', 'task', 'missing_binding'])
def test_actual_invalid_response_cannot_hide_beside_valid_metadata_response(tmp_path, ordering, fault):
    revision, _, handoff, good, final, stdout = unit_fixture(tmp_path)
    good['visual_assessments'][0]['producer'] = copy.deepcopy(good['producer'])
    bad = copy.deepcopy(good)
    if fault == 'missing_binding':
        del bad['request_sha256']
    else:
        bad[{'hash': 'request_sha256', 'request_id': 'request_id', 'task': 'task'}[fault]] = 'foreign-value'
    final.write_text(json.dumps(good))
    original = final.read_bytes()
    if ordering == 'envelope':
        payload = json.dumps({'response': good, 'other_response': bad})
    else:
        payload = '\n'.join(json.dumps(r) for r in ([bad, good] if ordering == 'bad-first' else [good, bad]))
    stdout.write_text(payload)
    with pytest.raises(ValueError):
        workflow._production_publish_quiet_response(revision, handoff, stdout)
    assert final.read_bytes() == original
    assert stdout.read_text() == payload


def test_nested_metadata_does_not_validate_invalid_assessment(tmp_path):
    revision, path, handoff, response, final, stdout = unit_fixture(tmp_path)
    row = response['visual_assessments'][0]
    row['producer'] = copy.deepcopy(response['producer'])
    del row['checks']
    final.write_text(json.dumps(response))
    stdout.write_text(json.dumps({'response': response}))
    assert not workflow._production_publish_quiet_response(revision, handoff, stdout)
    result = visual_review_unit_result(revision, path)
    assert not result or not result['complete']


@pytest.mark.parametrize('parallel', [False, True])
@pytest.mark.parametrize('fault', ['nested_producer_stdout', 'nested_producer_envelope_stdout',
    'nested_producer_foreign_first', 'nested_producer_foreign_last',
    'nested_producer_foreign_envelope', 'finding_nested_producer_stdout'])
def test_public_adapter_discovers_response_boundaries(tmp_path, monkeypatch, parallel, fault):
    exercise(tmp_path, monkeypatch, parallel, fault)
    observation = json.loads((tmp_path / 'observation.json').read_text())
    assert observation['returncodes'] and set(observation['returncodes']) == {0}
    assert observation['client_outputs'] == []
