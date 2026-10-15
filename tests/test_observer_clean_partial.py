"""Unpaid external execution controls; synthetic tool records are not clinical approval."""
import json
import sys
import time
from pathlib import Path

import pytest
import quality
import tui_visual_callback as callback
import workflow
from visual_review import IncompleteVisualReview, run_visual_review, visual_review_result
from test_visual_units import parent_fixture


WORKER = r'''
import json, os, sqlite3, sys
from pathlib import Path
sys.path[:0] = REPO_PATHS
from test_visual_units import response_for
prompt = sys.argv[sys.argv.index('-q') + 1]
path = Path(prompt.split('bounded request at ', 1)[1].split('. Inspect assigned', 1)[0])
unit = json.loads(path.read_text())
revision = Path.cwd()
state = Path(os.environ['HERMES_HOME'])
marker = revision / 'controlled-dispatches.json'
history = json.loads(marker.read_text()) if marker.exists() else []
history.append([t['target_id'] for t in unit['visual_scope']])
marker.write_text(json.dumps(history))
targets = unit['visual_scope'][:1] if len(history) == 1 else unit['visual_scope']
response = response_for(unit, targets)
if FAULT == 'binding':
    response['request_sha256'] = '0' * 64
if FAULT == 'finding':
    response['findings'] = [{'target_id': targets[0]['target_id'],
        'artifact': targets[0]['artifact'], 'page': targets[0]['pages'][0]['page'],
        'check': targets[0]['checks'][0], 'element': 'Controlled paragraph',
        'recommended_action': 'Correct the controlled defect',
        'issue': 'Controlled substantive visual concern', 'severity': 'major'}]
    response['visual_assessments'][0]['status'] = 'blocked'
checkpoint = revision / unit['review_transport']['progress_path']
checkpoint.write_text(json.dumps(response))
db = sqlite3.connect(state / 'state.db')
db.executescript('CREATE TABLE sessions(id TEXT,model TEXT,input_tokens INTEGER,output_tokens INTEGER);'
    'CREATE TABLE messages(session_id TEXT,role TEXT,tool_calls TEXT,tool_call_id TEXT,tool_name TEXT,content TEXT,timestamp REAL);')
db.execute('INSERT INTO sessions VALUES(?,?,0,0)', ('controlled-session', 'controlled-model'))
paths = [path, *[revision / a['docx'] for a in unit['artifacts']]]
if unit.get('document_evidence'):
    paths.append(revision / unit['document_evidence']['path'])
paths.extend(revision / b['path'] for b in unit.get('template_baseline_evidence', []))
calls = []
for n, p in enumerate(paths):
    text = p.read_text() if p.suffix == '.json' else 'controlled native extraction'
    lines = text.splitlines()
    result = {'content': '\n'.join(f'{j}|{s}' for j, s in enumerate(lines, 1)), 'total_lines': len(lines), 'truncated': False}
    cid = f'read-{n}'
    calls.append({'id': cid, 'function': {'name': 'read_file', 'arguments': json.dumps({'path': str(p)})}})
    db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)', ('controlled-session','tool',None,cid,'read_file',json.dumps(result),2))
images = {p['path'] for t in targets for p in t['pages']}
for n, image in enumerate(sorted(images)):
    cid = f'image-{n}'
    calls.append({'id': cid, 'function': {'name': 'vision_analyze', 'arguments': json.dumps({'image_url': str(revision / image)})}})
    db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)', ('controlled-session','tool',None,cid,'vision_analyze',json.dumps({'success': True, 'analysis': 'controlled image fixture'}),2))
db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)', ('controlled-session','assistant',json.dumps(calls),None,None,'',1))
db.commit()
db.close()
print(json.dumps(response), flush=True)
sys.exit(7 if FAULT == 'exit' else 0)
'''


def setup_observer(tmp_path, monkeypatch, fault=None):
    revision, parent_path, parent = parent_fixture(tmp_path, 'retrospective', count=2)
    profile = tmp_path / 'profile'
    profile.mkdir()
    (profile / 'config.yaml').write_text('controlled unpaid execution')
    launcher = tmp_path / 'controlled-observer.py'
    repo = Path(__file__).resolve().parents[1]
    launcher.write_text('REPO_PATHS = ' + repr([str(repo / 'scripts'), str(repo / 'tests')])
        + '\nFAULT = ' + repr(fault) + '\n' + WORKER)
    monkeypatch.setattr(workflow, '_managed_hermes_pair', lambda: (launcher, Path(sys.executable)))
    monkeypatch.setattr(workflow, '_managed_hermes_identity', lambda: {'controlled_external_execution': True})
    envelope = {'profile_path': str(profile), 'configuration': {'source': 'fixture', 'max_turns': 1}}
    return revision, parent_path, parent, envelope


def test_clean_partial_observer_retries_only_missing_scope(tmp_path, monkeypatch):
    revision, parent_path, parent, envelope = setup_observer(tmp_path, monkeypatch)
    deadline = time.monotonic() + 60
    partials = []
    def dispatch(handoffs, budget):
        assert 0 < budget <= deadline - time.monotonic()
        for handoff in handoffs:
            try:
                callback.observe_unit(revision, handoff, budget, envelope)
            except IncompleteVisualReview:
                partial = visual_review_result(revision, parent_path, publish=False)
                assert len(partial['assessments']) == 1
                assert not partial['complete']
                partials.append(partial)
                raise
    result = run_visual_review(revision, parent_path, dispatch, 59, observer_evidence_required=True)
    assert len(partials) == 1
    history = json.loads((revision / 'controlled-dispatches.json').read_text())
    first_accepted = partials[0]['assessments'][0]['target_id']
    assert len(history) >= 3  # initial partial, missing locals, dependent document
    assert all(first_accepted not in assigned for assigned in history[1:])
    assert result['complete']
    assert {r['target_id'] for r in result['assessments']} == {t['target_id'] for t in parent['visual_review_plan']['targets']}
    assert time.monotonic() < deadline
    assert result['dispatch_errors'][0].startswith('IncompleteVisualReview:')
    for p in (revision / 'hermes/visual-review-observers').glob('*/diagnostic.json'):
        diagnostic = json.loads(p.read_text())
        cleanup = json.loads((p.parent / 'owned-descendant-cleanup.json').read_text())
        assert diagnostic['returncode'] == 0 and diagnostic['descendants_reaped'] is True
        assert cleanup['descendants_reaped'] is True and cleanup['errors'] == []
        assert not Path('/proc', str(cleanup['owner_pid'])).exists()


def test_clean_partial_preserves_substantive_findings(tmp_path, monkeypatch):
    revision, parent_path, _, envelope = setup_observer(tmp_path, monkeypatch, 'finding')
    def dispatch(handoffs, budget):
        callback.observe_unit(revision, handoffs[0], budget, envelope)
    result = run_visual_review(revision, parent_path, dispatch, 30, observer_evidence_required=True)
    assert not result['complete']
    assert len(result['assessments']) == 1
    assert result['assessments'][0]['status'] == 'blocked'
    assert any(f['issue'] == 'Controlled substantive visual concern' for f in result['findings'])
    assert len(json.loads((revision / 'controlled-dispatches.json').read_text())) == 1
    assert result['dispatch_errors'][0].startswith('IncompleteVisualReview:')


@pytest.mark.parametrize('fault', ['binding', 'cleanup', 'request', 'metadata', 'exit',
    'proof-after-credit', 'provenance-after-credit'])
def test_clean_partial_does_not_demote_integrity_or_execution_failures(tmp_path, monkeypatch, fault):
    revision, parent_path, _, envelope = setup_observer(tmp_path, monkeypatch, fault)
    import owned_observer_runtime as runtime
    original = runtime.run_owned_observer
    def execute(*args, **kwargs):
        result = original(*args, **kwargs)
        assert result['cleanup']['descendants_reaped'] is True
        if fault == 'cleanup':
            (kwargs['state'] / 'owned-descendant-cleanup.json').unlink()
        if fault == 'request':
            path = next((revision / 'hermes/visual-review-requests').glob('*.json'))
            path.write_text(path.read_text() + ' ')
        return result
    monkeypatch.setattr(runtime, 'run_owned_observer', execute)
    if fault == 'metadata':
        def reject(*args):
            raise ValueError('controlled observer authentication failure')
        monkeypatch.setattr(callback, 'observer_metadata', reject)
    original_result = callback.visual_review_unit_result
    def tamper_after_credit(*args, **kwargs):
        result = original_result(*args, **kwargs)
        assert result and len(result['assessments']) == 1
        state = next((revision / 'hermes/visual-review-observers').iterdir())
        if fault == 'proof-after-credit':
            proof = state / 'owned-descendant-cleanup.json'
            data = json.loads(proof.read_text())
            data['descendants_reaped'] = False
            proof.write_text(json.dumps(data))
        else:
            provenance = state / 'provenance.json'
            data = json.loads(provenance.read_text())
            data['request_sha256'] = '0' * 64
            provenance.write_text(json.dumps(data))
        return result
    if fault.endswith('after-credit'):
        monkeypatch.setattr(callback, 'visual_review_unit_result', tamper_after_credit)
    calls = []
    def dispatch(handoffs, budget):
        calls.append(handoffs)
        callback.observe_unit(revision, handoffs[0], budget, envelope)
    with pytest.raises((RuntimeError, ValueError)) as caught:
        run_visual_review(revision, parent_path, dispatch, 30, observer_evidence_required=True)
    assert not isinstance(caught.value, IncompleteVisualReview)
    assert len(calls) == 1
    assert not visual_review_result(revision, parent_path, publish=False)['complete']
