"""Authenticated visual transport at its public boundaries, no live approval fixtures."""
import copy
import json

import pytest
import quality
from test_desktop_delivery import _visual_handoff_fixture

FAMILIES = ['prospective-advarra', 'prospective-sterling', 'ambispective-advarra',
            'ambispective-sterling', 'retrospective']


def parent_fixture(tmp_path, family, count=4):
    handoff, parent, _ = _visual_handoff_fixture(tmp_path, 'protocol')
    revision = tmp_path / 'revisions/r1'
    parent['source_identity_sha256'] = '1' * 64
    parent['generation_authority_sha256'] = '2' * 64
    parent['family'] = family
    for number in range(2, count + 1):
        path = revision / f'rendered/protocol/page-{number}.png'
        path.write_bytes(f'{family}-{number}'.encode())
        parent['artifacts'][0]['pages'].append({'page': number,
            'path': path.relative_to(revision).as_posix(), 'sha256': quality.sha256_file(path)})
    from visual_review import visual_review_plan
    parent['visual_review_plan'] = visual_review_plan(parent)
    parent['request_sha256'] = quality.verification_request_sha256(parent)
    path = revision / handoff['request_path']
    path.write_text(json.dumps(parent))
    ledger = revision / 'request-ledger' / (parent['request_id'] + '.json')
    ledger.write_text(json.dumps(quality.verification_request_ledger_record(path, parent)))
    return revision, path, parent


def response_for(unit, targets=None):
    targets = unit['visual_scope'] if targets is None else targets
    return {'schema_version': quality.RESPONSE_SCHEMA,
        **{k: unit[k] for k in ('request_id', 'request_sha256', 'task', 'revision_id')},
        'producer': {'model_id': 'test-model', 'reviewer_id': 'independent-fixture'},
        'status': 'in_progress', 'findings': [],
        'visual_assessments': [{**row, 'status': 'passed', 'notes': 'Inspected fixture',
             'checks': row['checks']} for row in targets]}


@pytest.mark.parametrize('family', FAMILIES)
def test_partial_visual_progress_is_recovered_without_crediting_missing_scope(tmp_path, family):
    from visual_review import create_visual_review_unit, visual_review_result
    revision, parent_path, parent = parent_fixture(tmp_path, family)
    unit_path = create_visual_review_unit(revision, parent_path,
        parent['visual_review_plan']['targets'][:2], 1)
    unit = json.loads(unit_path.read_text())
    checkpoint = revision / unit['review_transport']['progress_path']
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_text(json.dumps(response_for(unit, unit['visual_scope'][:1])))
    result = visual_review_result(revision, parent_path)
    assert len(result['assessments']) == 1
    assert not result['complete']
    assert not (revision / parent['response_path']).exists()
    assert len(result['missing']) == 7  # four pages, three boundaries, one document


@pytest.mark.parametrize('family', FAMILIES)
def test_malformed_unit_file_cannot_erase_valid_sibling_progress(tmp_path, family):
    from visual_review import create_visual_review_unit, visual_review_result
    revision, path, parent = parent_fixture(tmp_path, family)
    unit_path = create_visual_review_unit(revision, path, parent['visual_review_plan']['targets'][:1], 1)
    unit = json.loads(unit_path.read_text())
    checkpoint = revision / unit['review_transport']['progress_path']
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_text(json.dumps(response_for(unit)))
    (unit_path.parent / 'malformed.json').write_text('{broken')
    assert len(visual_review_result(revision, path)['assessments']) == 1


@pytest.mark.parametrize('notes, accepted', [('Observed complete page', True),
    ({'clipping': 'The full text is visible'}, True), ({'clipping': True}, False), ({}, False), (True, False)])
def test_visual_notes_support_real_per_check_observations_not_truthy_placeholders(tmp_path, notes, accepted):
    from visual_review import create_visual_review_unit, visual_review_result
    revision, path, parent = parent_fixture(tmp_path, 'retrospective')
    unit_path = create_visual_review_unit(revision, path, parent['visual_review_plan']['targets'][:1], 1)
    unit = json.loads(unit_path.read_text())
    output = revision / unit['response_path']
    output.parent.mkdir(parents=True)
    response = response_for(unit)
    response['visual_assessments'][0]['notes'] = notes
    output.write_text(json.dumps(response))
    assert bool(visual_review_result(revision, path)['assessments']) is accepted



@pytest.mark.parametrize('family', FAMILIES)
def test_bounded_scheduler_recombines_explicit_document_and_boundary_review(tmp_path, family):
    from visual_review import run_visual_review, visual_response_coverage_errors
    revision, path, parent = parent_fixture(tmp_path, family)
    seen = []
    def dispatch(handoffs, budget):
        assert 0 < budget <= 240
        for handoff in handoffs:
            unit = json.loads((revision / handoff['request_path']).read_text())
            seen.extend(t['kind'] for t in unit['visual_scope'])
            assert len({p['path'] for t in unit['visual_scope'] for p in t['pages']}) <= 3
            response = response_for(unit)
            response['status'] = 'passed'
            output = revision / unit['response_path']
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(response))
    result = run_visual_review(revision, path, dispatch, 240)
    response = json.loads((revision / parent['response_path']).read_text())
    assert result['complete'] and response['status'] == 'passed'
    assert seen.count('page') == 4 and seen.count('boundary') == 3 and seen.count('document') == 1
    assert visual_response_coverage_errors(revision, parent, response) == []
    response['visual_assessments'] = response['visual_assessments'][:-1]
    assert visual_response_coverage_errors(revision, parent, response)


@pytest.mark.parametrize('defect', ['foreign', 'stale-page', 'duplicate', 'missing-check', 'malformed', 'poison', 'native'])
def test_bad_progress_never_produces_visual_credit(tmp_path, defect):
    from visual_review import create_visual_review_unit, visual_review_result, invalidate_visual_review_units
    revision, path, parent = parent_fixture(tmp_path, 'retrospective')
    unit_path = create_visual_review_unit(revision, path, parent['visual_review_plan']['targets'][:1], 1)
    unit = json.loads(unit_path.read_text())
    response = response_for(unit)
    if defect == 'foreign': response['request_sha256'] = '0' * 64
    elif defect == 'stale-page': response['visual_assessments'][0]['pages'][0]['sha256'] = '0' * 64
    elif defect == 'duplicate': response['visual_assessments'] *= 2
    elif defect == 'missing-check': response['visual_assessments'][0]['checks'] = []
    output = revision / unit['review_transport']['progress_path']
    output.parent.mkdir(parents=True)
    output.write_text('{' if defect == 'malformed' else json.dumps(response))
    if defect == 'poison':
        invalidate_visual_review_units(revision, [unit_path], {'issue': 'renderer changed'})
        # Recreate identical unit during interrupted-parent recovery must not reset poison.
        create_visual_review_unit(revision, path, parent['visual_review_plan']['targets'][:1], 1)
    if defect == 'native': (revision / parent['artifacts'][0]['docx']).write_bytes(b'mutated')
    if defect == 'native':
        with pytest.raises(ValueError): visual_review_result(revision, path)
    else:
        assert visual_review_result(revision, path)['assessments'] == []


def test_scheduler_recovers_timeout_partial_without_resetting_budget(tmp_path):
    from visual_review import run_visual_review, visual_review_result
    revision, path, parent = parent_fixture(tmp_path, 'retrospective')
    now = [0.0]
    def interrupted(handoffs, budget):
        unit = json.loads((revision / handoffs[0]['request_path']).read_text())
        output = revision / unit['review_transport']['progress_path']
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(response_for(unit, unit['visual_scope'][:1])))
        now[0] = 40.0  # parent interruption consumes the remaining original allocation
        raise TimeoutError('delegated wave expired')
    result = run_visual_review(revision, path, interrupted, 40, clock=lambda: now[0])
    assert not result['complete']
    assert result['assessments']
    assert now[0] <= 40
    assert not (revision / parent['response_path']).exists()
    assert visual_review_result(revision, path)['assessments'] == result['assessments']


def test_callback_cannot_credit_self_reported_image_access_without_host_attestation(tmp_path):
    from visual_review import create_visual_review_unit, visual_review_unit_result
    revision, path, parent = parent_fixture(tmp_path, 'retrospective')
    unit_path = create_visual_review_unit(revision, path, parent['visual_review_plan']['targets'][:1], 1,
        observer_evidence_required=True)
    unit = json.loads(unit_path.read_text())
    response = response_for(unit)
    response['observer_evidence'] = {'session_id': 'invented', 'image_tool_results': [{'success': True}]}
    output = revision / unit['review_transport']['progress_path']
    output.parent.mkdir(parents=True)
    output.write_text(json.dumps(response))
    assert visual_review_unit_result(revision, unit_path) is None


def test_partial_substantive_visual_finding_is_not_replaced_by_missing_review(tmp_path):
    from visual_review import create_visual_review_unit
    revision, path, parent = parent_fixture(tmp_path, 'retrospective')
    target = parent['visual_review_plan']['targets'][0]
    unit_path = create_visual_review_unit(revision, path, [target], 1)
    unit = json.loads(unit_path.read_text())
    response = response_for(unit)
    response['visual_assessments'][0]['status'] = 'blocked'
    response['findings'] = [{'target_id': target['target_id'], 'artifact': 'protocol', 'page': 1,
        'check': 'clipping', 'element': 'Synthetic table', 'issue': 'A cell is clipped.',
        'recommended_action': 'Widen the cell without altering content.'}]
    output = revision / unit['review_transport']['progress_path']
    output.parent.mkdir(parents=True)
    output.write_text(json.dumps(response))
    findings, _ = quality.validate_verifications(revision, request_paths=[path])
    real = [f for f in findings if f.get('verification_source_finding')]
    assert len(real) == 1 and real[0]['issue'] == 'A cell is clipped.'
    assert real[0]['partial_review'] is True


def test_unit_recombination_rejects_overlapping_scopes_from_different_observers(tmp_path):
    from visual_review import create_visual_review_unit, visual_review_result
    revision, path, parent = parent_fixture(tmp_path, 'retrospective')
    for attempt in (1, 2):
        unit_path = create_visual_review_unit(revision, path, parent['visual_review_plan']['targets'][:1], attempt)
        unit = json.loads(unit_path.read_text())
        output = revision / unit['response_path']
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(response_for(unit)))
    with pytest.raises(ValueError, match='Overlapping'):
        visual_review_result(revision, path)


@pytest.mark.parametrize('family', FAMILIES)
def test_production_tui_uses_bounded_units_and_bundled_callback_without_phantom_attempt(tmp_path, monkeypatch, family):
    import shutil
    import workflow
    run = tmp_path / 'run'
    revision, path, parent = parent_fixture(run, family)
    reference = run / workflow.REFERENCE
    reference.parent.mkdir(parents=True)
    reference.write_text(json.dumps({'approval': {'revision_id': 'r1'}}))
    root = tmp_path / 'profile/skills/clinical-document-generation'
    (root / 'scripts').mkdir(parents=True)
    shutil.copy2(__import__('pathlib').Path(workflow.__file__).parent / 'tui_visual_callback', root / 'scripts/tui_visual_callback')
    monkeypatch.setattr(workflow, '_installed_release_identity', lambda *a: {'package_fingerprint': 'fixture', 'git_commit': 'fixture'})
    monkeypatch.setattr(workflow, '_production_worker_readiness', lambda *a, **k: {'status': 'passed'})
    monkeypatch.setattr(workflow, '_pdfium_runtime_integrity', lambda *a, **k: {'status': 'passed'})
    import threading
    ordinary_started = threading.Event()
    starvation = []
    seen = []
    def dispatch(handoffs, budget, *_args, **_kwargs):
        if handoffs[0].get('task') == 'ordinary-fixture':
            ordinary_started.set()
            return
        if not ordinary_started.wait(0.1):
            starvation.append(True)
            raise RuntimeError('Content review was starved behind visual scheduling')
        for handoff in handoffs:
            assert handoff['visual_unit']
            unit = json.loads((revision / handoff['request_path']).read_text())
            seen.extend(t['target_id'] for t in unit['visual_scope'])
            output = revision / unit['response_path']
            output.parent.mkdir(parents=True, exist_ok=True)
            response = response_for(unit)
            response['status'] = 'passed'
            output.write_text(json.dumps(response))
    monkeypatch.setattr(workflow, '_production_dispatch_handoffs', dispatch)
    def generate(_run, **options):
        assert options['bounded_visual_review'] is True
        if not (revision / parent['response_path']).exists():
            return {'status': 'awaiting_hermes', 'stage': 'independent_verification', 'revision_id': 'r1',
                'handoffs': [{'task': parent['task'], 'fallback_owner': 'parent',
                    'request_id': parent['request_id'], 'request_sha256': parent['request_sha256'],
                    'request_path': path.relative_to(revision).as_posix(), 'response_path': parent['response_path']},
                    {'task': 'ordinary-fixture', 'request_path': 'fixture-not-read.json'}]}
        return {'status': 'blocked', 'stage': 'synthetic_probe_done', 'findings': [], 'client_outputs': []}
    monkeypatch.setattr(workflow, 'generate', generate)
    result = workflow.run_production_desktop_operation(run, skill_root=root,
        host_mode='hermes-tui', manual_review=True, opener=workflow.local_output_reader(run))
    assert result['stage'] == 'synthetic_probe_done'
    assert starvation == []
    assert result['parent_visual_callback']['configured'] is True
    state = json.loads((run / 'logs/desktop-operation.json').read_text())
    assert state['status'] == result['status']
    assert state['attempt_counters']['parent_visual_callbacks'] == {}
    assert set(seen) == {t['target_id'] for t in parent['visual_review_plan']['targets']}


@pytest.mark.parametrize('family', FAMILIES)
def test_parent_integrity_poison_survives_restored_renderer_and_retains_prior_productive_scope(tmp_path, monkeypatch, family):
    import workflow
    from visual_review import create_visual_review_unit, visual_review_result
    run = tmp_path / 'run'
    revision, path, parent = parent_fixture(run, family)
    reference = run / workflow.REFERENCE
    reference.parent.mkdir(parents=True)
    reference.write_text(json.dumps({'approval': {'revision_id': 'r1'}}))
    root = tmp_path / 'skill'
    root.mkdir()
    prior = create_visual_review_unit(revision, path, parent['visual_review_plan']['targets'][:1], 1)
    first = json.loads(prior.read_text())
    output = revision / first['response_path']
    output.parent.mkdir(parents=True)
    output.write_text(json.dumps(response_for(first)))
    intact = [True]
    monkeypatch.setattr(workflow, '_pdfium_runtime_integrity', lambda *a, **k: {'status': 'passed' if intact[0] else 'blocked'})
    monkeypatch.setattr(workflow, '_installed_release_identity', lambda *a: {'package_fingerprint': 'fixture', 'git_commit': 'fixture'})
    monkeypatch.setattr(workflow, '_production_worker_readiness', lambda *a, **k: {'status': 'passed'})
    def callback(*_args):
        created = create_visual_review_unit(revision, path, parent['visual_review_plan']['targets'][1:2], 1)
        unit = json.loads(created.read_text())
        (revision / unit['response_path']).write_text(json.dumps(response_for(unit)))
        intact[0] = False
    handoff = {'task': parent['task'], 'request_path': path.relative_to(revision).as_posix(),
        'response_path': parent['response_path']}
    def invoke(_run, **options):
        options['fallback_handoff_runner']([handoff], 20)
    monkeypatch.setattr(workflow, 'run_desktop_operation', invoke)
    with pytest.raises(RuntimeError):
        workflow.run_production_desktop_operation(run, skill_root=root, opener=lambda _: b'unused',
            parent_visual_reviewer=callback)
    intact[0] = True
    recovered = visual_review_result(revision, path)
    assert len(recovered['assessments']) == 1
    assert recovered['assessments'][0]['target_id'] == 'protocol:page:1'
    assert not recovered['complete']
