"""Shared evidence ownership through the public scheduler, controlled adapters only."""
import copy
import json

from pathlib import Path

import pytest

import quality

from test_visual_units import FAMILIES, parent_fixture, response_for
from visual_review import run_visual_review, visual_review_unit_result


def save_response(revision, unit, response, *, progress=False):
    relative = unit['review_transport']['progress_path'] if progress else unit['response_path']
    path = revision / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(response))


def concern(target, page=4, basis='native'):
    return {'finding_id': 'original-concern', 'target_id': target['target_id'],
        'artifact': target['artifact'], 'page': page, 'check': 'template_preservation',
        'evidence_basis': basis, 'element': 'Bound element',
        'issue': 'An independently reported concern requires investigation.',
        'recommended_action': 'Inspect and correct the identified element.'}


@pytest.mark.parametrize('family', FAMILIES)
@pytest.mark.parametrize('defect', ['finding-location', 'findings-channel', 'assessment-row', 'final-channel'])
def test_recoverable_errors_keep_valid_sibling_and_precise_durable_feedback(tmp_path, family, defect):
    revision, parent_path, parent = parent_fixture(tmp_path, family, count=5)
    now, paths = [0.0], []

    def dispatch(handoffs, budget):
        for handoff in handoffs:
            path = revision / handoff['request_path']
            paths.append(path)
            unit = json.loads(path.read_text())
            response = response_for(unit)
            if defect == 'finding-location':
                response['findings'] = [concern(unit['visual_scope'][0], 999)]
            elif defect == 'findings-channel':
                response['findings'] = {'not': 'a list'}
            elif defect == 'assessment-row':
                response['visual_assessments'][-1]['notes'] = False
            else:
                save_response(revision, unit, response, progress=True)
                response['visual_assessments'] = 'malformed'
            save_response(revision, unit, response)
        now[0] = 240

    result = run_visual_review(revision, parent_path, dispatch, 240, clock=lambda: now[0])
    assert result['assessments'], 'a malformed sibling cannot erase valid rows'
    for path in paths:
        unit_result = visual_review_unit_result(revision, path)
        assert unit_result and unit_result['validation_feedback']
        feedback = unit_result['validation_feedback']
        assert all(set(row) == {'category', 'issue', 'target_ids', 'channel'} for row in feedback)
        assert all(row['target_ids'] for row in feedback)
        ledger = revision / 'hermes/visual-review-ledgers' / path.name
        assert json.loads(ledger.read_text())['validation_feedback'] == feedback
    assert not any(f.get('page') == 999 for f in result['findings'])


@pytest.mark.parametrize('family', FAMILIES)
@pytest.mark.parametrize('resolution', [False, True])
def test_uninspected_pixel_concern_gets_exact_targeted_followup_not_generic_clearance(tmp_path, family, resolution):
    revision, parent_path, parent = parent_fixture(tmp_path, family, count=5)
    followups = []
    original = [None]

    def dispatch(handoffs, budget):
        for handoff in handoffs:
            unit = json.loads((revision / handoff['request_path']).read_text())
            response = response_for(unit)
            if unit.get('finding_followup'):
                followups.append(unit)
                response['producer']['reviewer_id'] = 'independent-followup'
                if resolution:
                    response['finding_resolutions'] = [{
                        'finding_id': 'original-concern', 'status': 'dismissed',
                        'target_ids': [t['target_id'] for t in unit['visual_scope']],
                        'notes': 'Inspected this concern in the exact assigned page and boundary images; the element is intact.'}]
            elif unit['visual_scope'][0]['kind'] == 'document':
                target = unit['visual_scope'][0]
                original[0] = concern(target, basis='visual')
                response['findings'] = [original[0]]
                response['visual_assessments'][0]['status'] = 'blocked'
            save_response(revision, unit, response)

    result = run_visual_review(revision, parent_path, dispatch, 240)
    assert followups, 'uninspected pixels require a bound follow-up rather than dropping the concern'
    wanted = {'protocol:page:4', 'protocol:boundary:3-4', 'protocol:boundary:4-5'}
    assert {t['target_id'] for u in followups for t in u['visual_scope']} == wanted
    assert all(t['kind'] != 'document' for u in followups for t in u['visual_scope'])
    assert all(u['finding_followup'][0]['finding']['finding_id'] == 'original-concern' for u in followups)
    assert all(u['finding_followup'][0]['finding']['issue'] == original[0]['issue'] for u in followups)
    assert all(u['finding_followup'][0]['proof']['response_sha256'] for u in followups)
    # A follow-up may complete in more than one bounded unit, but no scope repeats.
    ids = [t['target_id'] for u in followups for t in u['visual_scope']]
    assert len(ids) == len(set(ids))
    if resolution:
        assert not result['findings']
        assert result['finding_resolutions']
        published = json.loads((revision / parent['response_path']).read_text())
        assert published['findings'] == result['findings']
        assert published['finding_resolutions'] == result['finding_resolutions']
        assert published['status'] == 'blocked'  # Dismissal never invents the missing document judgment.
    else:
        retained = next(f for f in result['findings'] if f['finding_id'] == 'original-concern')
        assert retained['issue'] == original[0]['issue']
        assert retained['evidence_status'] == 'needs_visual_followup'
        assert not result['complete']
        assert not any(r['kind'] == 'document' for r in result['assessments'])


@pytest.mark.parametrize('family', FAMILIES)
def test_followup_retries_only_missing_scopes_and_retains_original_context(tmp_path, family):
    revision, parent_path, parent = parent_fixture(tmp_path, family, count=5)
    scopes = []

    def dispatch(handoffs, budget):
        for handoff in handoffs:
            unit = json.loads((revision / handoff['request_path']).read_text())
            response = response_for(unit)
            if unit.get('finding_followup'):
                scopes.append([t['target_id'] for t in unit['visual_scope']])
                response['producer']['reviewer_id'] = 'followup-observer'
                if len(scopes) == 1:
                    response['visual_assessments'] = response['visual_assessments'][:1]
            elif unit['visual_scope'][0]['kind'] == 'document':
                response['findings'] = [concern(unit['visual_scope'][0], basis='visual')]
                response['visual_assessments'][0]['status'] = 'blocked'
            save_response(revision, unit, response)

    result = run_visual_review(revision, parent_path, dispatch, 240)
    assert len(scopes) == 2
    assert set(scopes[1]) == set(scopes[0][1:])
    assert not result['followup_missing']
    assert result['findings'] and not result['complete']


@pytest.mark.parametrize('family', FAMILIES)
def test_unknown_malformed_finding_does_not_erase_valid_sibling_findings(tmp_path, family):
    revision, parent_path, parent = parent_fixture(tmp_path, family, count=5)
    now = [0.0]

    def dispatch(handoffs, budget):
        for handoff in handoffs:
            unit = json.loads((revision / handoff['request_path']).read_text())
            response = response_for(unit)
            target = unit['visual_scope'][0]
            valid = concern(target, page=target['pages'][0]['page'])
            response['findings'] = [valid, {'target_id': 'foreign', 'issue': 'malformed sibling'}]
            response['visual_assessments'][0]['status'] = 'blocked'
            save_response(revision, unit, response)
        now[0] = 240

    result = run_visual_review(revision, parent_path, dispatch, 240, clock=lambda: now[0])
    assert result['assessments'] and result['findings']
    assert all(f['target_id'] != 'foreign' for f in result['findings'])
    assert result['validation_feedback']



@pytest.mark.parametrize('family', FAMILIES)
@pytest.mark.parametrize('field', ['task', 'review_set', 'source_identity_sha256',
    'generation_authority_sha256', 'response_path', 'review_transport'])
def test_rebound_noncanonical_unit_metadata_remains_fatal_at_scheduler_boundary(tmp_path, family, field):
    revision, parent_path, parent = parent_fixture(tmp_path, family, count=5)

    def dispatch(handoffs, budget):
        path = revision / handoffs[0]['request_path']
        unit = json.loads(path.read_text())
        unit[field] = {'progress_path': '../foreign.json'} if field == 'review_transport' else 'foreign'
        unit['request_sha256'] = quality.verification_request_sha256(unit)
        path.write_text(json.dumps(unit))
        ledger_path = revision / 'hermes/visual-review-ledgers' / path.name
        ledger = json.loads(ledger_path.read_text())
        ledger.update(request_sha256=unit['request_sha256'], request_file_sha256=quality.sha256_file(path))
        ledger_path.write_text(json.dumps(ledger))
        if field not in {'response_path', 'review_transport'}:
            save_response(revision, unit, response_for(unit))

    with pytest.raises(ValueError):
        run_visual_review(revision, parent_path, dispatch, 240)


@pytest.mark.parametrize('family', FAMILIES)
@pytest.mark.parametrize('defect', ['native-uninspected', 'runtime-provenance', 'cleanup', 'foreign-final'])
def test_observer_authentication_negative_controls_never_become_substantive_credit(tmp_path, monkeypatch, family, defect):
    import tui_visual_callback as callback
    import owned_observer_runtime as runtime
    revision, parent_path, parent = parent_fixture(tmp_path, family, count=5)
    metadata = {}

    def observe(state, *_args):
        value = copy.deepcopy(metadata[str(state)])
        if defect == 'runtime-provenance':
            value['provenance_sha256'] = 'foreign-runtime'
        return value

    def cleanup(state):
        if defect == 'cleanup':
            raise ValueError('fixture cleanup rejected')

    monkeypatch.setattr(callback, 'observer_metadata', observe)
    monkeypatch.setattr(runtime, 'validate_owned_observer_cleanup', cleanup)

    def dispatch(handoffs, budget):
        for handoff in handoffs:
            unit_path = revision / handoff['request_path']
            unit = json.loads(unit_path.read_text())
            response = response_for(unit)
            if unit['visual_scope'][0]['kind'] == 'document':
                response['findings'] = [concern(unit['visual_scope'][0])]
                response['visual_assessments'][0]['status'] = 'blocked'
            state = revision / 'hermes/visual-review-observers' / unit['request_id']
            state.mkdir(parents=True)
            (state / 'state.db').write_bytes(b'controlled adapter, not real runtime evidence')
            observed = {'state_path': str(state), 'database_sha256': quality.sha256_file(state / 'state.db'),
                'request_inspection_complete': True, 'native_inspection_complete': defect != 'native-uninspected',
                'session_id': 'independent-fixture', 'model_id': 'test-model',
                'inspected_paths': [p['path'] for t in unit['visual_scope'] for p in t['pages']],
                'image_tool_results': [], 'provenance_sha256': 'controlled-adapter'}
            metadata[str(state)] = observed
            response['observer_evidence'] = observed
            if defect == 'foreign-final':
                response['request_sha256'] = '0' * 64
            save_response(revision, unit, response)
            response_path = revision / unit['response_path']
            ledger_path = revision / 'hermes/visual-review-ledgers' / unit_path.name
            ledger = json.loads(ledger_path.read_text())
            ledger['observer_attestations'] = {unit['response_path']: {
                'response_sha256': quality.sha256_file(response_path),
                'producer': response['producer'], 'observer_evidence': observed}}
            ledger_path.write_text(json.dumps(ledger))

    if defect != 'native-uninspected':
        with pytest.raises(ValueError, match='integrity|rejected'):
            run_visual_review(revision, parent_path, dispatch, 240, observer_evidence_required=True)
        from visual_review import visual_review_result
        result = visual_review_result(revision, parent_path, publish=False)
        assert result['integrity_rejections']
    else:
        result = run_visual_review(revision, parent_path, dispatch, 240, observer_evidence_required=True)
    assert not result['complete'] and not result['findings']
    assert not any(r['kind'] == 'document' for r in result['assessments'])
    if defect != 'native-uninspected':
        assert not result['assessments']


@pytest.mark.parametrize('family', FAMILIES)
def test_malformed_findings_channel_cannot_convert_full_coverage_into_approval(tmp_path, family):
    revision, parent_path, parent = parent_fixture(tmp_path, family, count=5)
    now = [0.0]

    def dispatch(handoffs, budget):
        for handoff in handoffs:
            unit = json.loads((revision / handoff['request_path']).read_text())
            response = response_for(unit)
            if unit['visual_scope'][0]['kind'] == 'document':
                response['findings'] = 'missing findings channel'
                now[0] = 240
            save_response(revision, unit, response)

    result = run_visual_review(revision, parent_path, dispatch, 240, clock=lambda: now[0])
    assert result['assessments']  # Retain independently completed rows for recovery.
    assert not result['complete']
    assert {t['target_id'] for t in result['missing']} == {'protocol:document'}
    assert not (revision / parent['response_path']).exists()


@pytest.mark.parametrize('family', FAMILIES)
def test_supported_native_concern_returns_for_repair_before_waiting_for_pixel_sibling(tmp_path, family):
    revision, parent_path, parent = parent_fixture(tmp_path, family, count=5)

    def dispatch(handoffs, budget):
        for handoff in handoffs:
            unit = json.loads((revision / handoff['request_path']).read_text())
            assert not unit.get('finding_followup'), 'authenticated substantive native concern is already repair-ready'
            response = response_for(unit)
            if unit['visual_scope'][0]['kind'] == 'document':
                target = unit['visual_scope'][0]
                native, pixels = concern(target), concern(target, basis='visual')
                native['finding_id'] = 'native-ready-for-repair'
                response['findings'] = [native, pixels]
                response['visual_assessments'][0]['status'] = 'blocked'
            save_response(revision, unit, response)

    result = run_visual_review(revision, parent_path, dispatch, 240)
    assert {f['finding_id'] for f in result['findings']} == {'native-ready-for-repair', 'original-concern'}
    assert result['followup_missing']
    assert not result['complete']
