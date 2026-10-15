"""Controlled subprocess transport tests; not real Linux/model capability evidence."""
import json
import time

import pytest
import tui_visual_callback as callback
from visual_review import IncompleteVisualReview, run_visual_review, visual_review_result
from test_observer_clean_partial import setup_observer


def controlled(tmp_path, monkeypatch, mode):
    revision, path, parent, envelope = setup_observer(tmp_path, monkeypatch)
    import workflow
    launcher, _ = workflow._managed_hermes_pair()
    source = launcher.read_text()
    # Every control loads all assigned images; response validity alone varies.
    source = source.replace("images = {p['path'] for t in targets for p in t['pages']}",
                            "images = {p['path'] for t in unit['visual_scope'] for p in t['pages']}")
    source = source.replace("checkpoint.write_text(json.dumps(response))", """
if len(history) == 1 and MODE == 'malformed-checkpoint':
    checkpoint.write_bytes(b'{broken checkpoint\\xff')
elif len(history) == 1 and MODE == 'missing':
    pass
elif len(history) == 1 and MODE == 'malformed-only':
    checkpoint.write_bytes(b'{malformed checkpoint')
else:
    checkpoint.write_text(json.dumps(response))
""")
    source = source.replace("print(json.dumps(response), flush=True)", """
if len(history) == 1:
    if MODE in ('malformed-checkpoint', 'checkpoint-bad-final'):
        response = response_for(unit)
    if MODE == 'invalid-notes':
        response['visual_assessments'][0]['notes'] = True
        checkpoint.write_text(json.dumps(response))
    if MODE == 'foreign-sibling':
        foreign = response_for(unit)
        foreign['request_sha256'] = '0' * 64
        print(json.dumps(foreign), flush=True)
    if MODE == 'missing-identity':
        response.pop('revision_id')
    if MODE == 'checkpoint-bad-final':
        print('{broken final', flush=True)
    elif MODE == 'malformed-only':
        print('{malformed stdout', flush=True)
    elif MODE != 'missing':
        print(json.dumps(response), flush=True)
else:
    print(json.dumps(response), flush=True)
""")
    source = source.replace("sys.exit(7 if FAULT == 'exit' else 0)",
        "sys.exit(7 if MODE == 'crash-complete' else 0)")
    if mode in ('foreign-sibling', 'missing-identity', 'crash-complete'):
        source = source.replace("targets = unit['visual_scope'][:1] if len(history) == 1 else unit['visual_scope']",
                                "targets = unit['visual_scope']")
    source = source.replace("response = response_for(unit, targets)", """
response = response_for(unit, targets)
if len(history) == 1 and MODE == 'substantive-bad-final':
    t = targets[0]
    response['visual_assessments'][0]['status'] = 'blocked'
    response['findings'] = [{'target_id': t['target_id'], 'artifact': t['artifact'],
        'page': t['pages'][0]['page'], 'check': t['checks'][0], 'element': 'Controlled paragraph',
        'recommended_action': 'Correct controlled defect', 'severity': 'major',
        'issue': 'Controlled substantive sibling concern'}]
""")
    source = source.replace("if MODE == 'checkpoint-bad-final':", "if MODE in ('checkpoint-bad-final', 'substantive-bad-final'):")
    launcher.write_text('MODE = ' + repr(mode) + '\n' + source)
    return revision, path, parent, envelope


@pytest.mark.parametrize('mode', ['missing', 'malformed-only'])
def test_transport_only_feedback_reaches_bound_replacement_assignment(tmp_path, monkeypatch, mode):
    import quality
    revision, path, parent, envelope = controlled(tmp_path, monkeypatch, mode)
    assignments, diagnostics = [], {}
    def dispatch(handoffs, budget):
        for handoff in handoffs:
            unit_path = revision / handoff['request_path']
            unit = json.loads(unit_path.read_text())
            assignments.append((unit, handoff))
            try:
                callback.observe_unit(revision, handoff, budget, envelope)
            finally:
                ledger = json.loads((revision / 'hermes/visual-review-ledgers' / unit_path.name).read_text())
                if ledger.get('observer_transport_feedback'):
                    diagnostics[unit['request_id']] = ledger['observer_transport_feedback']
    result = run_visual_review(revision, path, dispatch, 59, observer_evidence_required=True)
    assert result['complete'] and diagnostics
    retries = []
    for index, (unit, handoff) in enumerate(assignments):
        earlier = {prior['request_id'] for prior, _ in assignments[:index]}
        ids = {t['target_id'] for t in unit['visual_scope']}
        expected = []
        for original, feedback in diagnostics.items():
            if original not in earlier:
                continue
            for row in feedback:
                shared = [k for k in row['target_ids'] if k in ids]
                if shared:
                    expected.append({**row, 'target_ids': shared})
        if not expected:
            continue
        retries.append(unit)
        feedback = unit.get('validation_feedback', [])
        assert all(row in feedback for row in expected)
        assert all(set(row['target_ids']) <= ids for row in feedback)
        assert handoff['validation_feedback'] == feedback
        assert quality.verification_request_hash_valid(unit)
        ledger = json.loads((revision / f"hermes/visual-review-ledgers/{unit['request_id']}.json").read_text())
        assert ledger['assignment_validation_feedback'] == feedback
    assert retries, 'must inspect actual missing/malformed-only replacement scope'


@pytest.mark.parametrize('mode', ['malformed-checkpoint', 'checkpoint-bad-final', 'missing', 'invalid-notes'])
def test_clean_transport_channels_recover_with_only_missing_retry(tmp_path, monkeypatch, mode):
    revision, path, parent, envelope = controlled(tmp_path, monkeypatch, mode)
    accepted = set()
    snapshots = []
    deadline = time.monotonic() + 60
    def dispatch(handoffs, budget):
        assert 0 < budget <= 59
        for handoff in handoffs:
            unit = json.loads((revision / handoff['request_path']).read_text())
            assert not accepted.intersection(t['target_id'] for t in unit['visual_scope'])
            try:
                callback.observe_unit(revision, handoff, budget, envelope)
            except IncompleteVisualReview as exc:
                assert exc.validation_feedback
                assert all(set(f) >= {'category', 'issue', 'target_ids', 'channel'} for f in exc.validation_feedback)
                snapshot = visual_review_result(revision, path, publish=False)
                accepted.update(r['target_id'] for r in snapshot['assessments'])
                snapshots.append(snapshot)
                raise
            snapshot = visual_review_result(revision, path, publish=False)
            accepted.update(r['target_id'] for r in snapshot['assessments'])
    result = run_visual_review(revision, path, dispatch, 59, observer_evidence_required=True)
    assert result['complete']
    assert time.monotonic() < deadline
    assert len(result['assessments']) == len(parent['visual_review_plan']['targets'])
    if mode == 'malformed-checkpoint':
        assert not snapshots  # independently valid complete final
        assert any((state / 'raw-progress.json').is_file()
            and (state / 'raw-progress.json').read_bytes() == b'{broken checkpoint\xff'
            for state in (revision / 'hermes/visual-review-observers').iterdir())
    else:
        assert snapshots
        ledgers = [json.loads(p.read_text()) for p in (revision / 'hermes/visual-review-ledgers').glob('*.json')]
        feedback = [f for ledger in ledgers
            for f in ledger.get('validation_feedback', []) + ledger.get('observer_transport_feedback', [])]
        assert feedback
        assert all(set(f) >= {'category', 'issue', 'target_ids', 'channel'} for f in feedback)
        if mode == 'missing':
            assert any(f['channel'] == 'checkpoint' and f['issue'] == 'Missing response channel'
                and f['target_ids'] for f in feedback)
            assert any(f['channel'] == 'stdout' and f['issue'] == 'Missing or malformed final response JSON'
                for f in feedback)


@pytest.mark.parametrize('mode', ['malformed-checkpoint', 'foreign-sibling', 'crash-complete'])
def test_interrupted_callback_reauthenticates_all_channels_and_exit(tmp_path, monkeypatch, mode):
    from visual_review import create_visual_review_unit
    revision, path, parent, envelope = controlled(tmp_path, monkeypatch, mode)
    unit_path = create_visual_review_unit(revision, path, parent['visual_review_plan']['targets'][:2], 1,
        observer_evidence_required=True)
    unit = json.loads(unit_path.read_text())
    metadata = callback.observer_metadata
    def interrupt(*args):
        raise KeyboardInterrupt('controlled interruption after subprocess cleanup, before authentication')
    monkeypatch.setattr(callback, 'observer_metadata', interrupt)
    with pytest.raises(KeyboardInterrupt):
        callback.observe_unit(revision, {'request_path': unit_path.relative_to(revision).as_posix()}, 30, envelope)
    monkeypatch.setattr(callback, 'observer_metadata', metadata)
    callback.recover_completed_observers(revision, path)
    result = visual_review_result(revision, path, publish=False)
    assert len(result['assessments']) == (2 if mode == 'malformed-checkpoint' else 0)
    callback.recover_completed_observers(revision, path)
    assert len(visual_review_result(revision, path, publish=False)['assessments']) == len(result['assessments'])


def test_malformed_final_preserves_authenticated_substantive_checkpoint(tmp_path, monkeypatch):
    revision, path, _, envelope = controlled(tmp_path, monkeypatch, 'substantive-bad-final')
    calls = []
    def dispatch(handoffs, budget):
        calls.append(handoffs)
        callback.observe_unit(revision, handoffs[0], budget, envelope)
    result = run_visual_review(revision, path, dispatch, 30, observer_evidence_required=True)
    assert len(calls) == 1
    assert not result['complete']
    assert len(result['assessments']) == 1
    assert result['assessments'][0]['status'] == 'blocked'
    assert any(f['issue'] == 'Controlled substantive sibling concern' for f in result['findings'])
    assert result['dispatch_errors'][0].startswith('IncompleteVisualReview:')


@pytest.mark.parametrize('fault', ['runtime', 'source', 'request', 'cleanup'])
def test_complete_scope_cannot_mask_changed_trust_boundary(tmp_path, monkeypatch, fault):
    import workflow
    import owned_observer_runtime as runtime
    revision, path, _, envelope = controlled(tmp_path, monkeypatch, 'crash-complete')
    launcher, _ = workflow._managed_hermes_pair()
    launcher.write_text(launcher.read_text().replace("sys.exit(7 if MODE == 'crash-complete' else 0)", 'sys.exit(0)'))
    if fault == 'source':
        envelope['callback_release_binding'] = {'controlled_original': True}
        import visual_review
        monkeypatch.setattr(visual_review, 'callback_release_binding', lambda *_: {'controlled_changed': True})
    execute = runtime.run_owned_observer
    def tamper(*args, **kwargs):
        result = execute(*args, **kwargs)
        if fault == 'runtime':
            monkeypatch.setattr(workflow, '_managed_hermes_identity', lambda: {'controlled_changed': True})
        elif fault == 'request':
            p = next((revision / 'hermes/visual-review-requests').glob('*.json'))
            p.write_text(p.read_text() + ' ')
        elif fault == 'cleanup':
            (kwargs['state'] / 'owned-descendant-cleanup.json').unlink()
        return result
    monkeypatch.setattr(runtime, 'run_owned_observer', tamper)
    def dispatch(handoffs, budget):
        callback.observe_unit(revision, handoffs[0], budget, envelope)
    with pytest.raises((RuntimeError, ValueError, OSError)):
        run_visual_review(revision, path, dispatch, 30, observer_evidence_required=True)
    assert not visual_review_result(revision, path, publish=False)['complete']


@pytest.mark.parametrize('outcome', ['incomplete', 'finding', 'fatal'])
def test_callback_public_main_uses_bound_recoverable_protocol_only(tmp_path, monkeypatch, capsys, outcome):
    import sys
    import quality
    revision, path, _, envelope = controlled(tmp_path, monkeypatch, 'missing')
    envelope['handoffs'] = [{'request_path': path.relative_to(revision).as_posix()}] * 2
    import workflow
    envelope['managed_hermes_identity'] = workflow._managed_hermes_identity()
    invocation = revision / 'hermes/controlled-invocation.json'
    invocation.write_text(json.dumps(envelope))
    envelope['_invocation_path'] = str(invocation)
    envelope['_invocation_sha256'] = quality.sha256_file(invocation)
    monkeypatch.setattr(callback, 'callback_admission', lambda _: (envelope, revision, 59))
    monkeypatch.setattr(callback, 'recover_completed_observers', lambda *_: None)
    monkeypatch.setattr(sys, 'argv', ['tui_visual_callback', str(invocation)])
    calls = []
    def review(*args, **kwargs):
        calls.append(args)
        if outcome == 'fatal':
            raise RuntimeError('controlled unclassified execution failure')
        return {'complete': False, 'findings': [{'issue': 'Controlled substantive concern'}] if outcome == 'finding' else [],
            'missing': ['controlled-missing-target'], 'dispatch_errors': ['IncompleteVisualReview: controlled missing coverage']}
    monkeypatch.setattr(callback, 'run_visual_review', review)
    if outcome == 'fatal':
        with pytest.raises(RuntimeError):
            callback.main()
        assert not capsys.readouterr().out
    elif outcome == 'finding':
        assert callback.main() == 0
        assert len(calls) == 1
    else:
        assert callback.main() == 75
        report = json.loads(capsys.readouterr().out)
        assert report['schema_version'] == 'tui-visual-callback-recovery/v1'
        assert report['outcome'] == 'incomplete_authenticated_visual_scope'
        assert report['invocation_path'] == str(invocation)
        assert report['invocation_sha256'] == quality.sha256_file(invocation)
        assert report['revision_id'] == revision.name
        assert report['missing_target_ids'] == ['controlled-missing-target']


@pytest.mark.parametrize('mode', ['foreign-sibling', 'missing-identity', 'crash-complete'])
def test_complete_checkpoint_never_masks_fatal_raw_final_or_exit(tmp_path, monkeypatch, mode):
    revision, path, _, envelope = controlled(tmp_path, monkeypatch, mode)
    calls = []
    def dispatch(handoffs, budget):
        calls.append(handoffs)
        callback.observe_unit(revision, handoffs[0], budget, envelope)
    with pytest.raises((RuntimeError, ValueError)) as caught:
        run_visual_review(revision, path, dispatch, 30, observer_evidence_required=True)
    assert not isinstance(caught.value, IncompleteVisualReview)
    assert len(calls) == 1
    assert not visual_review_result(revision, path, publish=False)['complete']
