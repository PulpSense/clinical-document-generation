"""Evidence gates use real returned coverage and durable identity, not claims."""
import json
from pathlib import Path
import sqlite3

import pytest
import quality
from tui_visual_callback import observer_metadata


def metadata_fixture(tmp_path, reads, image_result=None, tool_name='vision_analyze', duplicate_result=None):
    revision = tmp_path / 'revisions/r1'
    revision.mkdir(parents=True)
    image = revision / 'page.png'
    image.write_bytes(b'bound synthetic image')
    request = revision / 'hermes/visual-review-requests/unit.json'
    request.parent.mkdir(parents=True)
    request.write_text('{}')
    native = revision / 'protocol.docx'
    native.write_bytes(b'synthetic native')
    evidence = revision / 'evidence.json'
    evidence.write_text('{}')
    unit = {'request_id': 'unit', 'artifacts': [{'docx': 'protocol.docx'}],
        'document_evidence': {'path': 'evidence.json'},
        'visual_scope': [{'pages': [{'path': 'page.png', 'sha256': quality.sha256_file(image)}]}]}
    state = revision / 'hermes/visual-review-observers/test'
    state.mkdir(parents=True)
    db = sqlite3.connect(state / 'state.db')
    db.executescript('CREATE TABLE sessions(id TEXT,model TEXT,input_tokens INTEGER,output_tokens INTEGER);'
        'CREATE TABLE messages(session_id TEXT,role TEXT,tool_calls TEXT,tool_call_id TEXT,tool_name TEXT,content TEXT,timestamp REAL);')
    db.execute('INSERT INTO sessions VALUES(?,?,0,0)', ('synthetic-session', 'synthetic-model'))
    calls = []
    for n, path in enumerate([request, native, evidence]):
        for i, (args, result) in enumerate(reads):
            cid = f'read-{n}-{i}'
            calls.append({'id': cid, 'function': {'name': 'read_file', 'arguments': json.dumps({'path': str(path), **args})}})
            db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)', ('synthetic-session','tool',None,cid,'read_file',json.dumps(result),2))
    calls.append({'id': 'image', 'function': {'name': 'vision_analyze', 'arguments': json.dumps({'image_url': str(image)})}})
    db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)', ('synthetic-session','assistant',json.dumps(calls),None,None,'',1))
    db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)', ('synthetic-session','tool',None,'image',tool_name,image_result or json.dumps({'success': True, 'analysis': 'synthetic analysis'}),2))
    if duplicate_result is not None:
        db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)', ('synthetic-session','tool',None,'image','vision_analyze',duplicate_result,3))
    db.commit()
    db.close()
    return observer_metadata(state, revision, unit)


@pytest.mark.parametrize('reads,complete', [
    ([({'offset': 100, 'limit': 1}, {'content': '100|last line', 'total_lines': 100, 'truncated': False})], False),
    ([({}, {'content': '100|last line', 'total_lines': 100, 'truncated': False, 'full_read': True})], False),
    ([({'offset': 1, 'limit': 2}, {'content': '1|first\n2|second', 'total_lines': 3, 'truncated': True}),
      ({'offset': 3, 'limit': 1}, {'content': '3|third', 'total_lines': 3, 'truncated': False})], True),
    ([({}, {'content': '1|first\n3|third', 'total_lines': 3, 'truncated': False})], False),
    ([({}, {'content': '1|first\n2|second', 'total_lines': 3, 'truncated': False}),
      ({'offset': 2}, {'content': '2|second', 'total_lines': 3, 'truncated': False})], False),
    ([({}, {'success': False, 'content': '1|first', 'total_lines': 1, 'truncated': False})], False),
    ([({}, {'content': '1|first\n2|second\n3|third', 'total_lines': 3, 'truncated': False})], True),
])
def test_complete_inspection_requires_union_of_actual_returned_lines(tmp_path, reads, complete):
    evidence = metadata_fixture(tmp_path, reads)
    assert evidence['request_inspection_complete'] is complete
    assert evidence['native_inspection_complete'] is complete


@pytest.mark.parametrize('tool,result', [
    ('read_file', 'Image loaded into your context — you can see it natively now. Use your built-in vision to answer the user.'),
    ('vision_analyze', json.dumps({'success': True, 'error': 'No image loaded'})),
    ('vision_analyze', json.dumps({'success': True, 'error': None, 'analysis': 'contradiction'})),
])
def test_image_credit_rejects_mismatched_or_error_bearing_results(tmp_path, tool, result):
    assert metadata_fixture(tmp_path, [], result, tool)['inspected_paths'] == []


def test_conflicting_results_for_one_image_call_are_not_access_proof(tmp_path):
    assert metadata_fixture(tmp_path, [], duplicate_result=json.dumps({'success': False, 'error': 'image unavailable'}))['inspected_paths'] == []


@pytest.mark.parametrize('fault', ['candidate-relabel', 'last-line-request', 'last-line-native', 'wrong-tool-result', 'error-envelope', 'missing-cleanup', 'unresolved-cleanup', 'foreign-cleanup'])
def test_persisted_evidence_cannot_be_relabelled_or_self_attested(tmp_path, fault):
    from test_visual_units import parent_fixture, response_for
    from tui_visual_callback import _authenticate_observer_response
    from visual_review import create_visual_review_unit, visual_review_result, validate_callback_probe
    revision, parent_path, parent = parent_fixture(tmp_path / 'probe', 'retrospective', count=1)
    states = []
    for i, target in enumerate(parent['visual_review_plan']['targets']):
        path = create_visual_review_unit(revision, parent_path, [target], 1, observer_evidence_required=True)
        unit = json.loads(path.read_text())
        state = revision / f'hermes/visual-review-observers/synthetic-{i}'
        state.mkdir(parents=True)
        db = sqlite3.connect(state / 'state.db')
        db.executescript('CREATE TABLE sessions(id TEXT,model TEXT,input_tokens INTEGER,output_tokens INTEGER);'
            'CREATE TABLE messages(session_id TEXT,role TEXT,tool_calls TEXT,tool_call_id TEXT,tool_name TEXT,content TEXT,timestamp REAL);')
        db.execute('INSERT INTO sessions VALUES(?,?,0,0)', (f'synthetic-{i}', 'synthetic-model'))
        paths = [path, revision / unit['artifacts'][0]['docx']]
        if unit.get('document_evidence'):
            paths.append(revision / unit['document_evidence']['path'])
        calls = []
        for n, p in enumerate(paths):
            # Synthetic runtime records at the validator seam, never model proof.
            text = p.read_text() if p.suffix == '.json' else 'synthetic extracted native fixture'
            lines = text.splitlines()
            result = {'content': '\n'.join(f'{j}|{s}' for j, s in enumerate(lines, 1)), 'total_lines': len(lines), 'truncated': False}
            calls.append({'id': f'read-{n}', 'function': {'name': 'read_file', 'arguments': json.dumps({'path': str(p)})}})
            db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)', (f'synthetic-{i}', 'tool', None, f'read-{n}', 'read_file', json.dumps(result), 2))
        image = revision / target['pages'][0]['path']
        calls.append({'id': 'image', 'function': {'name': 'vision_analyze', 'arguments': json.dumps({'image_url': str(image)})}})
        db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)', (f'synthetic-{i}', 'assistant', json.dumps(calls), None, None, '', 1))
        db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)', (f'synthetic-{i}', 'tool', None, 'image', 'vision_analyze', json.dumps({'success': True, 'analysis': 'synthetic image fixture'}), 2))
        db.commit()
        db.close()
        # Explicit validator fixture, never actual-host descendant assurance.
        import tui_visual_callback as callback
        command_hash = 'unpaid-fixture-command'
        launch = {'pid': 99999999, 'start_ticks': '1', 'owned_command_sha256': command_hash,
            'supervisor_sha256': quality.sha256_file(Path(callback.__file__).with_name('owned_observer_process.py'))}
        (state / 'launch.json').write_text(json.dumps(launch))
        (state / 'provenance.json').write_text(json.dumps({'command_sha256': command_hash}))
        proof = {'fixture_only': True, 'descendants_reaped': True, 'errors': [],
            'owner_pid': launch['pid'], 'owner_start_ticks': launch['start_ticks'], 'command_sha256': command_hash}
        (state / 'owned-descendant-cleanup.json').write_text(json.dumps(proof))
        metadata = observer_metadata(state, revision, unit)
        response = revision / unit['response_path']
        response.parent.mkdir(parents=True, exist_ok=True)
        response.write_text(json.dumps(response_for(unit)))
        _authenticate_observer_response(revision, response, unit, metadata)
        (state / 'diagnostic.json').write_text(json.dumps({'request_path': path.relative_to(revision).as_posix(),
            'returncode': 0, 'observer_evidence': metadata}))
        states.append(state)
    timed_out = revision / 'hermes/visual-review-observers/synthetic-timeout'
    timed_out.mkdir()
    (timed_out / 'diagnostic.json').write_text(json.dumps({'error_type': 'TimeoutExpired'}))
    assert visual_review_result(revision, parent_path)['complete']
    if fault.endswith('cleanup'):
        certificate = states[-1] / 'owned-descendant-cleanup.json'
        original_certificate = certificate.read_text()
        if fault == 'missing-cleanup':
            certificate.unlink()
        else:
            changed = json.loads(original_certificate)
            if fault == 'unresolved-cleanup': changed['descendants_reaped'] = False
            else: changed['command_sha256'] = 'foreign'
            certificate.write_text(json.dumps(changed))
        rejected = visual_review_result(revision, parent_path, publish=False)
        assert not rejected['complete']
        assert len(rejected['assessments']) == len(states) - 1
        certificate.write_text(original_certificate)
        # Restoring a certificate cannot erase the recorded integrity rejection.
        assert not visual_review_result(revision, parent_path, publish=False)['complete']
        return
    if fault != 'candidate-relabel':
        state = states[-1]  # Document target requires full native/evidence access.
        diagnostic = json.loads((state / 'diagnostic.json').read_text())
        path = revision / diagnostic['request_path']
        unit = json.loads(path.read_text())
        db = sqlite3.connect(state / 'state.db')
        if fault.startswith('last-line-'):
            call_id = 'read-0' if fault == 'last-line-request' else 'read-1'
            db.execute("UPDATE messages SET content=? WHERE role='tool' AND tool_call_id=?",
                (json.dumps({'content': '100|last line only', 'total_lines': 100, 'truncated': False}), call_id))
        elif fault == 'wrong-tool-result':
            db.execute("UPDATE messages SET tool_name='read_file' WHERE role='tool' AND tool_call_id='image'")
        else:
            db.execute("UPDATE messages SET content=? WHERE role='tool' AND tool_call_id='image'",
                (json.dumps({'success': True, 'error': 'image unavailable'}),))
        db.commit()
        db.close()
        claimed = diagnostic['observer_evidence']
        claimed['database_sha256'] = quality.sha256_file(state / 'state.db')
        # Even matching report/ledger self-claims cannot overrule actual access.
        _authenticate_observer_response(revision, revision / unit['response_path'], unit, claimed)
        assert not visual_review_result(revision, parent_path, publish=False)['complete']
        return
    root = tmp_path / 'synthetic-NOT-installed-candidate'
    scripts = root / 'scripts'
    scripts.mkdir(parents=True)
    for name in ('tui_visual_callback', 'tui_visual_callback.py', 'visual_review.py'):
        (scripts / name).write_text('synthetic callback source fixture\n')
    command = scripts / 'tui_visual_callback'
    command.chmod(0o700)
    identity = {'package_fingerprint': 'synthetic-relabel', 'git_commit': 'synthetic-relabel'}
    operation = {'release_identity': {'package_fingerprint': 'synthetic-development', 'host_mode': 'hermes-tui',
        'probe_scope': 'development_callback_transport_not_candidate_assurance'}}
    logs = revision.parent.parent / 'logs'
    logs.mkdir()
    (logs / 'desktop-operation.json').write_text(json.dumps(operation))
    report = {'schema_version': 'tui-visual-callback-probe/v1', 'scope': 'synthetic callback transport; no clinical approval',
        'revision_path': str(revision), 'parent_request_path': parent_path.relative_to(revision).as_posix(),
        'candidate_identity': identity, 'operation': operation, 'delegated_timeout_observed': True, 'fallback_callback_completed': True,
        'callback_sha256': quality.sha256_file(command), 'callback_module_sha256': quality.sha256_file(scripts / 'tui_visual_callback.py'),
        'transport_module_sha256': quality.sha256_file(scripts / 'visual_review.py')}
    evidence = tmp_path / 'explicitly-synthetic-relabel.json'
    evidence.write_text(json.dumps(report))
    with pytest.raises(ValueError, match='callback_image_capability_unproven'):
        validate_callback_probe(command, evidence, identity)
