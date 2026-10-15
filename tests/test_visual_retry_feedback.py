"""Tiny controlled public scheduler regressions; no model or clinical evidence."""
import copy
import json

import pytest
import quality
from test_visual_units import parent_fixture, response_for
from test_visual_evidence_followup import save_response, concern
from visual_review import run_visual_review, visual_review_unit_result


def test_retry_delivers_only_precise_missing_scope_feedback(tmp_path):
    revision, parent_path, _ = parent_fixture(tmp_path, 'retrospective', count=3)
    rejected, accepted, retries = [], set(), []
    now = [0.0]

    def dispatch(handoffs, budget):
        assert budget <= 240 - now[0]
        for handoff in handoffs:
            path = revision / handoff['request_path']
            unit = json.loads(path.read_text())
            response = response_for(unit)
            ids = {t['target_id'] for t in unit['visual_scope']}
            if not rejected:
                rejected.append(response['visual_assessments'][-1]['target_id'])
                response['visual_assessments'][-1]['notes'] = False
                accepted.update(ids - set(rejected))
            elif set(rejected) & ids:
                retries.append(unit)
                assert not ids & accepted
                feedback = unit.get('validation_feedback', [])
                assert any('exact scope, checks, status and substantive notes' in f['issue'] for f in feedback)
                assert all(set(f['target_ids']) <= ids for f in feedback)
                assert handoff['validation_feedback'] == feedback
                assert quality.verification_request_hash_valid(unit)
                ledger = json.loads((revision / 'hermes/visual-review-ledgers' / path.name).read_text())
                assert ledger['assignment_validation_feedback'] == feedback
            else:
                assert not unit.get('validation_feedback'), 'unrelated document scope must not receive local feedback'
            save_response(revision, unit, response)
        now[0] += 10

    result = run_visual_review(revision, parent_path, dispatch, 240, clock=lambda: now[0])
    assert result['complete'] and len(retries) == 1


@pytest.mark.parametrize('bad_status', [[], {}])
def test_malformed_sibling_status_cannot_erase_original_concern(tmp_path, bad_status):
    from visual_review import create_visual_review_unit
    revision, parent_path, parent = parent_fixture(tmp_path, 'retrospective', count=3)
    targets = parent['visual_review_plan']['targets'][:2]
    path = create_visual_review_unit(revision, parent_path, targets, 1)
    unit = json.loads(path.read_text())
    response = response_for(unit)
    response['findings'] = [concern(targets[0], page=targets[0]['pages'][0]['page'])]
    response['visual_assessments'][0]['status'] = 'blocked'
    response['visual_assessments'][1]['status'] = bad_status
    save_response(revision, unit, response)
    result = visual_review_unit_result(revision, path)
    assert result and result['findings'][0]['finding_id'] == 'original-concern'
    assert [r['target_id'] for r in result['assessments']] == [targets[0]['target_id']]
    assert any(f['category'] == 'malformed_assessment' and
        f['target_ids'] == [targets[1]['target_id']] for f in result['validation_feedback'])
    calls = []
    def ordinary_pass(handoffs, budget):
        calls.append(handoffs)
        for handoff in handoffs:
            retry = json.loads((revision / handoff['request_path']).read_text())
            save_response(revision, retry, response_for(retry))
    resumed = run_visual_review(revision, parent_path, ordinary_pass, 59)
    assert not calls, 'accepted concern must preempt unrelated missing scope'
    assert resumed['findings'][0]['finding_id'] == 'original-concern'
    assert not resumed['complete']


@pytest.mark.parametrize('bad_status', [[], {}])
def test_malformed_resolution_keeps_inspected_scope_and_original_concern(tmp_path, bad_status):
    revision, parent_path, _ = parent_fixture(tmp_path, 'retrospective', count=5)
    scopes = []
    def dispatch(handoffs, budget):
        for handoff in handoffs:
            unit = json.loads((revision / handoff['request_path']).read_text())
            response = response_for(unit)
            if unit.get('finding_followup'):
                scopes.extend(t['target_id'] for t in unit['visual_scope'])
                response['producer']['reviewer_id'] = 'independent-followup'
                response['finding_resolutions'] = [{'finding_id': 'original-concern',
                    'status': bad_status, 'target_ids': [t['target_id'] for t in unit['visual_scope']],
                    'notes': 'Malformed disposition must not erase completed image inspections.'}]
            elif unit['visual_scope'][0]['kind'] == 'document':
                response['findings'] = [concern(unit['visual_scope'][0], basis='visual')]
                response['visual_assessments'][0]['status'] = 'blocked'
            save_response(revision, unit, response)
    result = run_visual_review(revision, parent_path, dispatch, 59)
    assert scopes and len(scopes) == len(set(scopes))
    assert {r['assessment']['target_id'] for r in result['followup_assessments']} == set(scopes)
    assert any(f['finding_id'] == 'original-concern' for f in result['findings'])
    assert not result['finding_resolutions'] and not result['complete']
    assert any(f['category'] == 'unsupported_resolution' for f in result['validation_feedback'])


@pytest.mark.parametrize('rebind', [False, True])
def test_retry_feedback_tampering_is_fatal_at_public_boundary(tmp_path, rebind):
    revision, parent_path, _ = parent_fixture(tmp_path, 'retrospective', count=2)
    first = [True]

    def dispatch(handoffs, budget):
        for handoff in handoffs:
            path = revision / handoff['request_path']
            unit = json.loads(path.read_text())
            response = response_for(unit)
            if first[0]:
                response['visual_assessments'][-1]['notes'] = False
                first[0] = False
            else:
                unit['validation_feedback'] = [{'category': 'invented', 'issue': 'unrelated',
                    'target_ids': ['foreign:page:999'], 'channel': 'foreign'}]
                if rebind:
                    unit['request_sha256'] = quality.verification_request_sha256(unit)
                path.write_text(json.dumps(unit))
                if rebind:
                    ledger_path = revision / 'hermes/visual-review-ledgers' / path.name
                    ledger = json.loads(ledger_path.read_text())
                    ledger.update(request_sha256=unit['request_sha256'], request_file_sha256=quality.sha256_file(path))
                    ledger_path.write_text(json.dumps(ledger))
            save_response(revision, unit, response)

    with pytest.raises(ValueError):
        run_visual_review(revision, parent_path, dispatch, 240)


@pytest.mark.parametrize('defect', ['none', 'hash', 'path', 'cleanup'])
def test_all_attested_finals_keep_native_concerns_without_image_credit(tmp_path, monkeypatch, defect):
    import tui_visual_callback as callback
    import owned_observer_runtime as runtime
    revision, parent_path, _ = parent_fixture(tmp_path, 'retrospective', count=3)
    metadata, document_paths = {}, []
    monkeypatch.setattr(callback, 'observer_metadata', lambda state, *_: copy.deepcopy(metadata[str(state)]))

    def cleanup(state):
        if defect == 'cleanup' and state.name.endswith('-extra'):
            raise ValueError('controlled cleanup rejection')

    monkeypatch.setattr(runtime, 'validate_owned_observer_cleanup', cleanup)

    def dispatch(handoffs, budget):
        for handoff in handoffs:
            path = revision / handoff['request_path']
            unit = json.loads(path.read_text())
            ledger_path = revision / 'hermes/visual-review-ledgers' / path.name
            ledger = json.loads(ledger_path.read_text())
            ledger['observer_attestations'] = {}
            is_document = unit['visual_scope'][0]['kind'] == 'document'
            if is_document:
                document_paths.append(path)
            for extra in ([False, True] if is_document else [False]):
                state = revision / 'hermes/visual-review-observers' / (unit['request_id'] + ('-extra' if extra else ''))
                state.mkdir(parents=True, exist_ok=True)
                (state / 'state.db').write_bytes(b'controlled adapter, not runtime proof')
                observed = {'state_path': str(state), 'database_sha256': quality.sha256_file(state / 'state.db'),
                    'request_inspection_complete': True, 'native_inspection_complete': True,
                    'session_id': 'independent-fixture', 'model_id': 'test-model',
                    'inspected_paths': [] if extra else [p['path'] for t in unit['visual_scope'] for p in t['pages']],
                    'image_tool_results': [], 'provenance_sha256': 'controlled-adapter'}
                metadata[str(state)] = observed
                response = response_for(unit)
                response['observer_evidence'] = observed
                if extra:
                    response['findings'] = [concern(unit['visual_scope'][0], page=2)]
                    response['visual_assessments'][0]['status'] = 'blocked'
                    output = state / 'authenticated-finals' / ('a' * 64 + '.json')
                    if defect == 'path':
                        output = revision / 'hermes/arbitrary-final.json'
                    relative = output.relative_to(revision).as_posix()
                    ledger['observer_final_channels'] = [relative]
                else:
                    relative = unit['response_path']
                    output = revision / relative
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(json.dumps(response))
                ledger['observer_attestations'][relative] = {
                    'response_sha256': quality.sha256_file(output),
                    'producer': response['producer'], 'observer_evidence': observed}
                if extra and defect == 'hash':
                    output.write_text(json.dumps({**response, 'findings': []}))
            ledger_path.write_text(json.dumps(ledger))

    if defect == 'none':
        result = run_visual_review(revision, parent_path, dispatch, 240, observer_evidence_required=True)
    else:
        with pytest.raises(ValueError, match='integrity|rejected'):
            run_visual_review(revision, parent_path, dispatch, 240, observer_evidence_required=True)
        from visual_review import visual_review_result
        result = visual_review_result(revision, parent_path, publish=False)
    assert result['assessments'], 'invalid extra must preserve valid sibling local judgments'
    document = visual_review_unit_result(revision, document_paths[-1])
    if defect == 'none':
        assert result['findings'] and result['findings'][0]['finding_id'] == 'original-concern'
        assert result['findings'][0]['proof']['response_path'].endswith('a' * 64 + '.json')
        assert len(document['assessments']) == 1 and document['assessments'][0]['status'] == 'passed'
        assert document['findings'], 'native concern survives without claiming image coverage'
    elif defect == 'cleanup':
        assert document is None
        ledger = json.loads((revision / 'hermes/visual-review-ledgers' / document_paths[-1].name).read_text())
        assert 'integrity_rejection' in ledger
    else:
        assert document is None
        assert not result['complete'] and result['integrity_rejections']
