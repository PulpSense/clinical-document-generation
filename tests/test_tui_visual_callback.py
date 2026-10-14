"""Executable callback rejects unsafe admissions before any paid model launch."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import workflow


def test_callback_envelope_carries_remaining_allocation_and_exact_runtime(tmp_path):
    from test_desktop_delivery import _visual_handoff_fixture
    handoff, _, response = _visual_handoff_fixture(tmp_path, 'protocol')
    revision = tmp_path / 'revisions/r1'
    command = tmp_path / 'observe-envelope'
    command.write_text(f'#!{sys.executable}\nimport json, sys\nfrom pathlib import Path\n'
        'request = json.loads(Path(sys.argv[1]).read_text())\n'
        f'Path({str(tmp_path / "envelope.json")!r}).write_text(json.dumps(request))\n'
        f'print({json.dumps(response)!r})\n')
    command.chmod(0o700)
    workflow.command_parent_visual_reviewer(command)([handoff], 27, revision, workflow.CERTIFIED_HERMES_CONFIGURATION)
    envelope = json.loads((tmp_path / 'envelope.json').read_text())
    assert envelope['remaining_seconds'] <= 27
    assert envelope['remaining_seconds'] > 0
    assert envelope['callback_deadline_utc']
    assert envelope['configuration'] == workflow.CERTIFIED_HERMES_CONFIGURATION
    assert envelope['revision_path'] == str(revision)


@pytest.mark.parametrize('fault', ['expired', 'wrong-revision', 'wrong-configuration'])
def test_bundled_callback_fails_closed_before_model_launch(tmp_path, fault):
    from datetime import datetime, timedelta, timezone
    revision = tmp_path / 'revisions/r1'
    revision.mkdir(parents=True)
    envelope = {'schema_version': 'desktop-parent-visual-review-request/v1',
        'revision_id': 'r1', 'revision_path': str(revision), 'handoffs': [],
        'remaining_seconds': 1,
        'callback_deadline_utc': (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat(),
        'configuration': workflow.CERTIFIED_HERMES_CONFIGURATION,
        'managed_hermes_identity': workflow._managed_hermes_identity()}
    if fault == 'expired': envelope['callback_deadline_utc'] = '2000-01-01T00:00:00+00:00'
    elif fault == 'wrong-revision': envelope['revision_id'] = 'foreign'
    else: envelope['configuration'] = {'model': 'unapproved'}
    request = revision / 'callback.json'
    request.write_text(json.dumps(envelope))
    command = Path(workflow.__file__).parent / 'tui_visual_callback'
    completed = subprocess.run([str(command), str(request)],
        env={**os.environ, 'CLINICAL_PYTHON': sys.executable}, capture_output=True, text=True, timeout=5)
    assert completed.returncode != 0
    assert not (revision / 'hermes/visual-review-observers').exists()
    assert 'callback admission' in completed.stderr.lower()


def test_candidate_provisioning_restores_only_manifest_bound_callback_execute_mode(tmp_path, monkeypatch):
    root = tmp_path / 'candidate'
    command = root / 'scripts/tui_visual_callback'
    command.parent.mkdir(parents=True)
    command.write_text('#!/bin/sh\nexit 0\n')
    command.chmod(0o644)  # Python zip extraction drops POSIX execute mode.
    manifest = {'files': [{'path': 'scripts/tui_visual_callback',
        'sha256': workflow.sha256_file(command), 'bytes': command.stat().st_size}],
        'inventory': {'executable_callbacks': ['scripts/tui_visual_callback']}}
    manifest['package_fingerprint'] = quality_fingerprint(manifest)
    (root / workflow.RELEASE_MANIFEST).write_text(json.dumps(manifest))
    monkeypatch.setattr(workflow, 'renderers', lambda **k: [{'kind': 'LibreOffice'}])
    monkeypatch.setattr(workflow, '_provision_page_renderer', lambda *a: {
        'status': 'passed', 'page_renderer': {}, 'provisioned': False})
    assert workflow.provision_render_assurance(root)['status'] == 'passed'
    assert os.access(command, os.X_OK)
    assert workflow.sha256_file(command) == manifest['files'][0]['sha256']
    command.write_text('foreign executable')
    command.chmod(0o644)
    assert workflow.provision_render_assurance(root)['status'] == 'blocked'
    assert not os.access(command, os.X_OK)


def quality_fingerprint(manifest):
    from quality import _manifest_package_fingerprint
    return _manifest_package_fingerprint(manifest)[1]


@pytest.mark.parametrize('encoding', ['auxiliary-json', 'native-main-model', 'error-text', 'crop-only'])
def test_observer_metadata_reads_actual_hermes_tool_encodings(tmp_path, encoding):
    import sqlite3
    from tui_visual_callback import observer_metadata
    state = tmp_path / 'observer'
    state.mkdir()
    revision = tmp_path / 'revisions/r1'
    revision.mkdir(parents=True)
    image = revision / 'page.png'
    image.write_bytes(b'bound tool fixture')
    unit = {'artifacts': [], 'visual_scope': [{'pages': [{'path': 'page.png', 'sha256': workflow.sha256_file(image)}]}]}
    db = sqlite3.connect(state / 'state.db')
    db.executescript('CREATE TABLE sessions(id TEXT, model TEXT, input_tokens INTEGER, output_tokens INTEGER);'
        'CREATE TABLE messages(session_id TEXT, role TEXT, tool_calls TEXT, tool_call_id TEXT, tool_name TEXT, content TEXT, timestamp REAL);')
    db.execute('INSERT INTO sessions VALUES(?,?,0,0)', ('fixture-session', 'fixture-model'))
    arguments = {'image_url': str(image), 'question': 'Inspect'}
    if encoding == 'crop-only': arguments['region'] = [0, 0, 10, 10]
    call = [{'id': 'fixture-call', 'function': {'name': 'vision_analyze', 'arguments': json.dumps(arguments)}}]
    db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)', ('fixture-session', 'assistant', json.dumps(call), None, None, '', 1))
    native = 'Image loaded into your context — you can see it natively now. Use your built-in vision to answer the user.\n\nQuestion: Inspect'
    content = json.dumps({'success': True, 'analysis': 'fixture'}) if encoding == 'auxiliary-json' else 'Unable to load image' if encoding == 'error-text' else native
    db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)', ('fixture-session', 'tool', None, 'fixture-call', 'vision_analyze', content, 2))
    db.commit()
    db.close()
    evidence = observer_metadata(state, revision, unit)
    assert evidence['model_id'] == 'fixture-model'
    assert evidence['inspected_paths'] == ([] if encoding in {'error-text', 'crop-only'} else ['page.png'])


def test_acceptance_cannot_use_file_presence_or_claimed_probe_success_as_image_proof(tmp_path):
    from visual_review import validate_callback_probe
    command = tmp_path / 'callback'
    command.write_text('#!/bin/sh\nexit 0\n')
    command.chmod(0o700)
    evidence = tmp_path / 'claimed-proof.json'
    evidence.write_text(json.dumps({'schema_version': 'tui-visual-callback-probe/v1',
        'response_accepted': True, 'response_complete_pass': True,
        'candidate_identity': {'package_fingerprint': 'fixture'},
        'callback_sha256': workflow.sha256_file(command)}))
    with pytest.raises(ValueError, match='callback_image_capability_unproven'):
        validate_callback_probe(command, evidence, {'package_fingerprint': 'fixture'})


@pytest.mark.parametrize('fault', ['none', 'live', 'poisoned', 'foreign'])
def test_interrupted_callback_recovers_only_stopped_authentic_observers(tmp_path, monkeypatch, fault):
    import tui_visual_callback as callback
    import quality
    from test_visual_units import parent_fixture, response_for
    from visual_review import create_visual_review_unit, visual_review_result
    revision, parent_path, parent = parent_fixture(tmp_path, 'retrospective')
    path = create_visual_review_unit(revision, parent_path, parent['visual_review_plan']['targets'][:1], 1,
        observer_evidence_required=True)
    unit = json.loads(path.read_text())
    state = revision / 'hermes/visual-review-observers/stopped-fixture'
    state.mkdir(parents=True)
    (state / 'stdout.log').write_text(json.dumps(response_for(unit)))
    (state / 'diagnostic.json').write_text(json.dumps({'request_path': path.relative_to(revision).as_posix(), 'returncode': -9}))
    if fault == 'live':
        stat = Path(f'/proc/{os.getpid()}/stat').read_text().rsplit(')', 1)[1].split()
        (state / 'launch.json').write_text(json.dumps({'pid': os.getpid(), 'start_ticks': stat[19],
            'request_path': path.relative_to(revision).as_posix()}))
    if fault == 'poisoned':
        ledger_path = revision / f"hermes/visual-review-ledgers/{unit['request_id']}.json"
        ledger = json.loads(ledger_path.read_text())
        ledger['integrity_rejection'] = {'issue': 'fixture poisoned renderer'}
        ledger_path.write_text(json.dumps(ledger))
    if fault == 'foreign':
        unit['parent_request_sha256'] = 'foreign'
        path.write_text(json.dumps(unit))
    (state / 'state.db').write_bytes(b'synthetic database; observer_metadata is mocked at this recovery seam')
    metadata = {'session_id': 'stopped-fixture-session', 'model_id': 'test-model',
        'state_path': str(state), 'database_sha256': quality.sha256_file(state / 'state.db'),
        'request_inspection_complete': True, 'native_inspection_complete': True,
        'inspected_paths': [p['path'] for t in unit['visual_scope'] for p in t['pages']],
        'image_tool_results': [{'tool': 'vision_analyze', 'page_path': p['path'], 'sha256': p['sha256'], 'success': True}
            for t in unit['visual_scope'] for p in t['pages']]}
    monkeypatch.setattr(callback, 'observer_metadata', lambda *a: metadata)
    callback.recover_completed_observers(revision, parent_path)
    result = visual_review_result(revision, parent_path)
    assert len(result['assessments']) == (1 if fault == 'none' else 0)

