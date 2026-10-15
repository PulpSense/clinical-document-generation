"""Public unpaid subprocess controls; synthetic tool records are not quality approval."""
import hashlib
import json
from pathlib import Path

import pytest
import tui_visual_callback as callback
from visual_review import IncompleteVisualReview, create_visual_review_unit, visual_review_unit_result
from test_observer_clean_partial import setup_observer


TAIL = r'''
import copy
passed = copy.deepcopy(response)
negative = copy.deepcopy(response)
t = targets[0]
negative['findings'] = [{'finding_id': 'original-concern-identity',
    'target_id': t['target_id'], 'artifact': t['artifact'], 'page': t['pages'][0]['page'],
    'check': t['checks'][0], 'element': 'Controlled paragraph',
    'recommended_action': 'Restore controlled language', 'issue': 'Original substantive concern',
    'severity': 'major', 'evidence_basis': 'pixels' if CASE == 'pixel' else 'native'}]
negative['visual_assessments'][0]['status'] = 'blocked'
final = revision / unit['response_path']
final.parent.mkdir(parents=True, exist_ok=True)
checkpoint.write_text('{broken')
if CASE == 'disk':
    final.write_text(json.dumps(negative))
    print(json.dumps(passed))
elif CASE == 'multiple':
    print(json.dumps(negative, indent=2))
    print(json.dumps(passed))
elif CASE == 'native-malformed-rows':
    negative['visual_assessments'] = 'not an assessment array'
    print(json.dumps(negative))
elif CASE.startswith('malformed-sibling-'):
    value = {'list': [], 'dict': {}, 'missing': None, 'bool': True,
        'int': 7, 'unknown': 'not-an-assigned-target', 'nonobject': []}[CASE.removeprefix('malformed-sibling-')]
    row = [] if CASE.endswith('-nonobject') else {'target_id': value}
    negative['visual_assessments'].append(row)
    print(json.dumps(negative))
elif CASE.startswith('bad-status-'):
    negative['status'] = {'list': [], 'dict': {}, 'null': None,
        'bool': True, 'int': 7, 'unknown': 'not-a-response-status'}[CASE.removeprefix('bad-status-')]
    final.write_text(json.dumps(negative))
    print(json.dumps(passed))
elif CASE == 'utf8':
    passed['visual_assessments'][0]['notes'] = 'raw-utf8-token'
    sys.stdout.buffer.write(json.dumps(passed).encode().replace(b'raw-utf8-token', b'raw-utf8-' + bytes([255])) + bytes([10]))
elif CASE in ('native', 'pixel'):
    print(json.dumps(negative))
elif CASE in ('malformed', 'checkpoint'):
    if CASE == 'checkpoint':
        checkpoint.write_text(json.dumps(passed))
    print('{"wrapper":' + json.dumps(passed))
elif CASE == 'quoted':
    print(json.dumps(json.dumps({'schema_version': 'foreign', 'request_id': 'foreign'})))
    print(json.dumps(passed))
elif CASE == 'foreign':
    print(json.dumps(passed))
    foreign = copy.deepcopy(passed)
    foreign['request_id'] = 'foreign'
    print(json.dumps(foreign))
'''


def exercise(tmp_path, monkeypatch, case):
    revision, parent_path, parent, envelope = setup_observer(tmp_path, monkeypatch)
    launcher = tmp_path / 'controlled-observer.py'
    worker = launcher.read_text().replace("print(json.dumps(response), flush=True)", TAIL)
    if case in ('native', 'pixel', 'native-malformed-rows'):
        worker = worker.replace("images = {p['path'] for t in targets for p in t['pages']}", 'images = set()')
    launcher.write_text('CASE = ' + repr(case) + '\n' + worker)
    targets = parent['visual_review_plan']['targets']
    target = next(t for t in targets if t['kind'] == ('document' if case in ('native', 'pixel', 'native-malformed-rows') else 'page'))
    if case in ('native', 'pixel', 'native-malformed-rows'):
        from test_visual_units import response_for
        local_path = create_visual_review_unit(revision, parent_path,
            [t for t in targets if t['kind'] != 'document'], 1)
        local = json.loads(local_path.read_text())
        output = revision / local['response_path']
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(response_for(local)))
    unit_path = create_visual_review_unit(revision, parent_path, [target], 1, observer_evidence_required=True)
    error = None
    try:
        callback.observe_unit(revision, {'request_path': unit_path.relative_to(revision).as_posix()}, 30, envelope)
    except (IncompleteVisualReview, RuntimeError, ValueError) as exc:
        error = exc
    unit = json.loads(unit_path.read_text())
    ledger = json.loads((revision / f"hermes/visual-review-ledgers/{unit['request_id']}.json").read_text())
    state = next((revision / 'hermes/visual-review-observers').iterdir())
    return revision, unit, ledger, state, visual_review_unit_result(revision, unit_path), error


@pytest.mark.parametrize('case', ['disk', 'multiple'])
def test_independent_negative_channels_survive_later_pass(tmp_path, monkeypatch, case):
    revision, unit, ledger, state, result, error = exercise(tmp_path, monkeypatch, case)
    assert error is None or isinstance(error, IncompleteVisualReview)
    assert result and any(f['finding_id'] == 'original-concern-identity' for f in result['findings'])
    assert not any(r['status'] == 'passed' for r in result['assessments'])
    channels = ledger['observer_final_channels']
    assert len(channels) == (1 if case == 'disk' else 2)
    assert len(set(channels)) == len(channels)
    for relative in channels:
        path = revision / relative
        assert path.parent == state / 'authenticated-finals'
        raw = state / 'raw-finals' / path.name
        assert raw.read_bytes() in (state / 'raw-final.json').read_bytes()
        assert hashlib.sha256(raw.read_bytes()).hexdigest() == path.stem
        attested = json.loads(path.read_text())
        assert attested['model_reported_producer']['reviewer_id'] == 'independent-fixture'
        assert ledger['observer_attestations'][relative]['response_sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    callback.recover_completed_observers(revision, revision / unit['parent_request_path'])
    callback.recover_completed_observers(revision, revision / unit['parent_request_path'])
    for relative in channels:
        assert json.loads((revision / relative).read_text())['model_reported_producer']['reviewer_id'] == 'independent-fixture'
    concern = next(f for f in result['findings'] if f['finding_id'] == 'original-concern-identity')
    assert (revision / concern['proof']['response_path']).is_file()
    if case == 'disk':
        assert json.loads((revision / unit['response_path']).read_text())['findings'][0]['finding_id'] == 'original-concern-identity'
        assert json.loads((state / 'raw-disk-final.json').read_text())['producer']['reviewer_id'] == 'independent-fixture'


@pytest.mark.parametrize('case', ['native', 'pixel', 'native-malformed-rows'])
def test_concerns_survive_missing_images_without_assessment_credit(tmp_path, monkeypatch, case):
    revision, unit, ledger, state, result, error = exercise(tmp_path, monkeypatch, case)
    assert isinstance(error, IncompleteVisualReview)
    assert result and not result['assessments'] and not result['complete']
    concern = next(f for f in result['findings'] if f['finding_id'] == 'original-concern-identity')
    evidence = concern['proof']['observer_evidence']
    assert evidence['request_inspection_complete'] and evidence['native_inspection_complete']
    assert evidence['inspected_paths'] == []
    if case == 'pixel':
        assert concern['evidence_status'] == 'needs_visual_followup'


@pytest.mark.parametrize('shape', ['list', 'dict', 'missing', 'bool', 'int', 'unknown', 'nonobject'])
def test_malformed_target_row_preserves_substantive_sibling_for_repair(tmp_path, monkeypatch, shape):
    from visual_review import run_visual_review
    revision, unit, ledger, state, result, error = exercise(tmp_path, monkeypatch, 'malformed-sibling-' + shape)
    assert error is None or isinstance(error, IncompleteVisualReview)
    assert not ledger.get('integrity_rejection')
    assert result and result['findings'][0]['finding_id'] == 'original-concern-identity'
    assert len(result['assessments']) == 1 and result['assessments'][0]['status'] == 'blocked'
    assert any(f['category'] == 'malformed_assessment' for f in result['validation_feedback'])
    assert json.loads((state / 'raw-final.json').read_bytes())['findings'][0]['finding_id'] == 'original-concern-identity'
    calls = []
    def unrelated_retry(handoffs, budget):
        calls.append(handoffs)
    resumed = run_visual_review(revision, revision / unit['parent_request_path'], unrelated_retry, 59)
    assert not calls
    assert any(f['finding_id'] == 'original-concern-identity' for f in resumed['findings'])
    assert not resumed['complete']


@pytest.mark.parametrize('shape', ['list', 'dict', 'null', 'bool', 'int', 'unknown'])
def test_bad_envelope_status_cannot_erase_bound_concern_beside_valid_final(tmp_path, monkeypatch, shape):
    from visual_review import run_visual_review
    revision, unit, ledger, state, result, error = exercise(tmp_path, monkeypatch, 'bad-status-' + shape)
    assert error is None or isinstance(error, IncompleteVisualReview)
    assert not ledger.get('integrity_rejection')
    assert result and any(f['finding_id'] == 'original-concern-identity' for f in result['findings'])
    assert any(f['category'] == 'malformed_response_status' for f in result['validation_feedback'])
    assert b'original-concern-identity' in (state / 'raw-disk-final.json').read_bytes()
    calls = []
    resumed = run_visual_review(revision, revision / unit['parent_request_path'],
        lambda handoffs, budget: calls.append(handoffs), 59)
    assert not calls and not resumed['complete']
    assert any(f['finding_id'] == 'original-concern-identity' for f in resumed['findings'])


@pytest.mark.parametrize('kind,basis', [('page', None), ('boundary', None),
    ('page', 'unsupported'), ('boundary', 'unsupported'), ('document', 'unsupported'),
    ('page', []), ('boundary', {}), ('document', [])])
def test_uninspected_scope_claim_requires_bound_pixel_followup(tmp_path, monkeypatch, kind, basis):
    from visual_review import run_visual_review
    revision, parent_path, parent, envelope = setup_observer(tmp_path, monkeypatch, 'finding')
    launcher = tmp_path / 'controlled-observer.py'
    source = launcher.read_text().replace(
        "paths = [path, *[revision / a['docx'] for a in unit['artifacts']]]", 'paths = [path]')
    source = source.replace("images = {p['path'] for t in targets for p in t['pages']}", 'images = set()')
    if basis is not None:
        source = source.replace('checkpoint.write_text(json.dumps(response))',
            "for finding in response['findings']:\n    finding['evidence_basis'] = " + repr(basis) +
            '\ncheckpoint.write_text(json.dumps(response))')
    launcher.write_text(source)
    target = next(t for t in parent['visual_review_plan']['targets'] if t['kind'] == kind)
    if kind == 'document':
        from test_visual_units import response_for
        local = create_visual_review_unit(revision, parent_path,
            [t for t in parent['visual_review_plan']['targets'] if t['kind'] != 'document'], 1)
        local_unit = json.loads(local.read_text())
        local_response = revision / local_unit['response_path']
        local_response.parent.mkdir(parents=True, exist_ok=True)
        local_response.write_text(json.dumps(response_for(local_unit)))
    path = create_visual_review_unit(revision, parent_path, [target], 1, observer_evidence_required=True)
    with pytest.raises(IncompleteVisualReview):
        callback.observe_unit(revision, {'request_path': path.relative_to(revision).as_posix()}, 30, envelope)
    result = visual_review_unit_result(revision, path)
    assert result and result['findings'] and not result['assessments']
    finding = result['findings'][0]
    assert finding.get('evidence_status') == 'needs_visual_followup'
    evidence = finding['proof']['observer_evidence']
    assert not evidence['native_inspection_complete'] and not evidence['inspected_paths']
    calls, now = [], [0.0]
    def inspect_pending(handoffs, budget):
        calls.extend(json.loads((revision / h['request_path']).read_text()) for h in handoffs)
        now[0] = 59
    resumed = run_visual_review(revision, parent_path, inspect_pending, 59,
        clock=lambda: now[0], observer_evidence_required=True)
    assert calls and resumed['followup_missing'] and not resumed['complete']
    needed = {t['target_id'] for t in parent['visual_review_plan']['targets']
        if t['artifact'] == finding['artifact'] and t['kind'] != 'document'
        and finding['page'] in {p['page'] for p in t['pages']}}
    assert {t['target_id'] for u in calls for t in u['visual_scope']} == needed
    assert all(u['finding_followup'][0]['finding']['finding_id'] == finding['finding_id'] for u in calls)


def test_malformed_utf8_stdout_never_grants_repaired_text_approval(tmp_path, monkeypatch):
    _, _, ledger, state, result, error = exercise(tmp_path, monkeypatch, 'utf8')
    assert isinstance(error, IncompleteVisualReview)
    assert not result or not result['assessments'] and not result['complete']
    assert bytes([255]) in (state / 'raw-final.json').read_bytes()
    assert not ledger.get('observer_final_channels')
    assert any('UTF-8' in item['issue'] for item in ledger['observer_transport_feedback'])


@pytest.mark.parametrize('case', ['malformed', 'checkpoint', 'quoted', 'foreign'])
def test_outer_framing_and_independent_channels(tmp_path, monkeypatch, case):
    revision, unit, ledger, state, result, error = exercise(tmp_path, monkeypatch, case)
    assert (state / 'raw-final.json').read_bytes() == (state / 'stdout.log').read_bytes()
    if case == 'foreign':
        assert isinstance(error, (RuntimeError, ValueError)) and not isinstance(error, IncompleteVisualReview)
        assert ledger.get('integrity_rejection')
        assert not result or not result['complete']
    elif case == 'malformed':
        assert isinstance(error, IncompleteVisualReview)
        assert not result or not result['assessments'] and not result['complete']
        assert ledger.get('observer_transport_feedback')
        assert not ledger.get('observer_final_channels')
    else:
        assert error is None
        assert result and result['complete']
        if case == 'checkpoint':
            assert ledger.get('observer_transport_feedback')
            assert not ledger.get('observer_final_channels')
