"""Existing restricted Hermes hosts must generate without claiming remote delivery."""
import hashlib
import json
import subprocess
from pathlib import Path

import pytest
import workflow


def test_tui_readiness_does_not_require_privileged_campaign(tmp_path, monkeypatch):
    root = tmp_path / 'profile/skills/clinical-document-generation'
    root.mkdir(parents=True)
    monkeypatch.setattr(workflow, '_managed_hermes_pair', lambda: (tmp_path / 'bin/hermes', Path('/fake/python')))
    monkeypatch.setattr(workflow.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 0,
        json.dumps({'logged_in': True, 'inspection_readable': True, 'provider': 'openai-codex'}), ''))
    monkeypatch.setattr(workflow, '_worker_capability_assurance', lambda root: pytest.fail('TUI must not require privileged campaign'))
    result = workflow._production_worker_readiness(root, host_mode='hermes-tui')
    assert result['status'] == 'passed'
    assert result['capability_assurance']['os_isolation_verified'] is False
    assert result['capability_assurance']['recipient_delivery_verified'] is False


def test_tui_prefix_does_not_require_namespaces(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow.platform, 'system', lambda: 'Linux')
    assert workflow._production_sandbox_prefix(tmp_path / 'missing', host_mode='hermes-tui') == []


def test_local_output_is_verified_without_claiming_recipient_delivery(tmp_path):
    path = tmp_path / 'protocol.docx'
    path.write_bytes(b'native bytes')
    manifest = {'client_outputs': [{'path': 'output/protocol.docx', 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': 12}]}
    reply = workflow.desktop_attachment_reply(manifest)
    reply['attachments'][0]['absolute_path'] = str(path)
    result = workflow.confirm_desktop_delivery(manifest, reply, workflow.local_output_reader(tmp_path))
    assert result['status'] == 'locally_available'
    assert result['confirmed'] is False
    assert result['bytes_verified'] is True
    assert result['recipient_delivery_verified'] is False
    path.write_bytes(b'wrong')
    result = workflow.confirm_desktop_delivery(manifest, reply, workflow.local_output_reader(tmp_path))
    assert result['status'] == 'blocked'
    assert not result['bytes_verified']


def test_local_reader_refuses_outside_run(tmp_path):
    outside = tmp_path / 'elsewhere'
    outside.write_text('private')
    run = tmp_path / 'run'
    run.mkdir()
    with pytest.raises(ValueError):
        workflow.local_output_reader(run)(str(outside))


@pytest.mark.parametrize('process_inspectable', [True, False], ids=['cleanup-proven', 'cleanup-deferred'])
def test_public_tui_adapter_routes_and_persists_local_outcome(tmp_path, monkeypatch, process_inspectable):
    import sys
    root = tmp_path / 'profile/skills/clinical-document-generation'
    root.mkdir(parents=True)
    # The public TUI now requires the shipped executable callback contract.
    # Retain actual package bytes/mode rather than a fake passing executable.
    import shutil
    (root / 'scripts').mkdir()
    for name in ('tui_visual_callback', 'tui_visual_callback.py', 'visual_review.py'):
        shutil.copy2(workflow.SCRIPT_DIR / name, root / 'scripts' / name)
    run = tmp_path / 'run'
    manifest_path = run / 'revisions/r1/delivery-manifest.json'
    manifest_path.parent.mkdir(parents=True)
    data = b'1234'
    output = run / 'output/protocol.docx'
    output.parent.mkdir()
    output.write_bytes(data)
    manifest_path.write_text(json.dumps({'status': 'passed', 'client_outputs': [
        {'path': 'output/protocol.docx', 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': 4}]}))
    reference = run / 'reference/study.reference.json'
    reference.parent.mkdir()
    reference.write_text(json.dumps({'meta': {'study_type': 'Retrospective'}, 'approval': {'status': 'approved', 'revision_id': 'r1'}}))
    monkeypatch.setattr(workflow, '_installed_release_identity', lambda r: {'package_fingerprint': 'test-candidate', 'git_commit': 'test'})
    monkeypatch.setattr(workflow, '_pdfium_runtime_integrity', lambda *a, **k: {'status': 'passed'})
    monkeypatch.setattr(workflow, '_managed_hermes_identity', lambda: {'launcher': 'test'})
    monkeypatch.setattr(workflow, 'resolve_python_runtime', lambda **k: {'executable': sys.executable, 'version_info': list(sys.version_info[:3])})
    monkeypatch.setattr(workflow, '_production_worker_readiness', lambda r, **k: {'status': 'passed', 'host_mode': k['host_mode']})
    results = iter([
        {'status': 'awaiting_hermes', 'stage': 'drafting', 'revision_id': 'r1', 'handoffs': [{'task': 'section_drafting', 'request_path': 'hermes/draft-requests/test.json'}]},
        {'status': 'passed', 'stage': 'delivery', 'revision_id': 'r1', 'client_outputs': ['output/protocol.docx'], 'manifest': 'revisions/r1/delivery-manifest.json'}])
    monkeypatch.setattr(workflow, 'generate', lambda *a, **k: next(results))
    dispatched = []
    for worker in ('one', 'two'):
        cache = run / '.hermes-cache' / worker
        (cache / 'bin').mkdir(parents=True)
        (cache / 'bin/tool').write_bytes(b'exact disposable tool copy')
        (cache / 'state.db').write_bytes(b'unique tool session audit')
    unique = run / '.hermes-cache/three/bin/tool'
    unique.parent.mkdir(parents=True)
    unique.write_bytes(b'nonduplicate tool evidence')
    # Inspect a controlled Linux process namespace through the real checker.
    # Unrelated CI runner processes may legitimately be non-inspectable; they
    # cannot be treated as deletion proof or an unconditional test success.
    import storage_retention as storage
    checker = storage.stopped_references
    observed = []
    code = ('import ctypes,time; assert ctypes.CDLL(None).prctl(4,'
        + ('1' if process_inspectable else '0')
        + ",0,0,0)==0; print('ready',flush=True); time.sleep(30)")
    child = subprocess.Popen([sys.executable, '-B', '-c', code], stdout=subprocess.PIPE, text=True)
    class ControlledProc:
        def is_dir(self): return True
        def iterdir(self): return iter([Path('/proc') / str(child.pid)])
    def controlled_path(value, *parts):
        return ControlledProc() if value == '/proc' and not parts else Path(value, *parts)
    def inspect_controlled_namespace(target):
        observed.append(str(target))
        with monkeypatch.context() as scope:
            scope.setattr(storage, 'Path', controlled_path)
            return checker(target)
    monkeypatch.setattr(storage, 'stopped_references', inspect_controlled_namespace)
    monkeypatch.setattr(workflow, '_production_dispatch_handoffs', lambda *a, **k: dispatched.append(k['host_mode']))
    try:
        assert child.stdout.readline().strip() == 'ready'
        result = workflow.run_production_desktop_operation(run, skill_root=root, manual_review=True, host_mode='hermes-tui')
    finally:
        child.terminate()
        child.wait(timeout=5)
    assert observed and child.returncode is not None
    assert dispatched == ['hermes-tui'], result
    assert result['status'] == 'passed'
    assert result['stage'] == 'local_output_availability'
    assert result['delivery']['confirmed'] is False
    assert result['delivery_status'] == 'locally_available'
    completion = json.loads((run / 'storage-retention/completion.json').read_text())
    if process_inspectable:
        assert not (run / '.hermes-cache/two/bin').exists()
        assert completion['status'] == 'passed'
        assert completion['retired']
        assert all(r['process_proof']['owned_pids_checked'] == [child.pid] for r in completion['retired'])
    else:
        assert (run / '.hermes-cache/two/bin/tool').read_bytes() == b'exact disposable tool copy'
        assert completion['status'] == 'deferred'
        assert completion['error'] == 'OwnedProcessProofUnavailable: Owned process proof unavailable: ' + str(child.pid)
    assert result['storage_retention']['status'] == completion['status']
    assert unique.read_bytes() == b'nonduplicate tool evidence'
    assert (run / '.hermes-cache/one/bin/tool').read_bytes() == b'exact disposable tool copy'
    assert (run / '.hermes-cache/two/state.db').read_bytes() == b'unique tool session audit'
    saved = json.loads((run / 'logs/desktop-operation.json').read_text())
    assert saved['result']['recipient_delivery_verified'] is False
    assert saved['release_identity']['host_mode'] == 'hermes-tui'
    with pytest.raises(ValueError, match='manual candidate'):
        workflow.run_production_desktop_operation(run, skill_root=root, host_mode='hermes-tui')


def test_local_completion_retains_pending_delivery_ledger_and_reopens(tmp_path, monkeypatch):
    from quality import GOVERNED_GATE_SEQUENCE, build_gate_ledger
    root = workflow.SCRIPT_DIR.parent
    ledger = build_gate_ledger(root, {gate: {'fixture': gate} for gate in GOVERNED_GATE_SEQUENCE},
        attempt_id='local-test', statuses={'exact_byte_atomic_delivery': 'pending'})
    reference = tmp_path / 'reference/study.reference.json'
    reference.parent.mkdir()
    reference.write_text(json.dumps({'meta': {'study_type': 'Retrospective'}}))
    output = tmp_path / 'output/protocol.docx'
    output.parent.mkdir()
    output.write_bytes(b'1234')
    manifest = {'status': 'passed', 'gate_ledger': ledger, 'client_outputs': [
        {'path': 'output/protocol.docx', 'sha256': hashlib.sha256(b'1234').hexdigest(), 'bytes': 4}]}
    manifest_path = tmp_path / 'revisions/r1/delivery-manifest.json'
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps(manifest))
    bundle = {'identity_sha256': 'fixture-bundle'}
    monkeypatch.setattr(workflow, 'contracted_template_bundle', lambda *a: bundle)
    generated = []
    monkeypatch.setattr(workflow, 'generate', lambda *a, **k: generated.append(True) or {
        'status': 'passed', 'stage': 'delivery', 'manifest': 'revisions/r1/delivery-manifest.json',
        'contracted_template_bundle': bundle, 'client_outputs': ['output/protocol.docx']})
    arguments = {'handoff_runner': lambda *a: None, 'opener': workflow.local_output_reader(tmp_path),
        'release_identity': {'package_fingerprint': 'fixture', 'host_mode': 'hermes-tui'}, 'require_promoted_runtime': False}
    first = workflow.run_desktop_operation(tmp_path, **arguments)
    assert first['gate_ledger'] == ledger
    assert first['delivery']['confirmed'] is False
    resumed = workflow.run_desktop_operation(tmp_path, **arguments)
    assert resumed['status'] == 'passed', resumed
    assert resumed['recipient_delivery_verified'] is False
    assert generated == [True]
    output.write_bytes(b'xxxx')
    assert workflow.run_desktop_operation(tmp_path, **arguments)['status'] == 'blocked'


@pytest.mark.parametrize("checkpoint_state", ["draft", "missing", "existing"])
def test_tui_dispatch_uses_managed_worker_and_tcp_proxy_without_sandbox(tmp_path, monkeypatch, checkpoint_state):
    import sys
    root = tmp_path / 'profile/skills/clinical-document-generation'
    root.mkdir(parents=True)
    (root / workflow.RELEASE_MANIFEST).write_text('{}')
    run = tmp_path / 'run'
    launcher = tmp_path / 'hermes/venv/bin/hermes'
    revision = run / 'revisions/r1'
    progress = revision / 'hermes/review-progress/unit.json'
    request_path = 'hermes/requests/draft.json'
    task = 'section_drafting'
    if checkpoint_state != 'draft':
        task = 'clinical_content_verification'
        request_path = 'hermes/content-review-requests/unit.json'
        request = revision / request_path
        request.parent.mkdir(parents=True)
        request.write_text(json.dumps({'review_transport': {'progress_path': 'hermes/review-progress/unit.json'}}))
        if checkpoint_state == 'existing':
            progress.parent.mkdir(parents=True)
            progress.write_bytes(b'authenticated checkpoint bytes')
    monkeypatch.setattr(workflow.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(workflow, '_managed_hermes_pair', lambda: (launcher, Path(sys.executable)))
    monkeypatch.setattr(workflow, '_manifest_integrity', lambda *a, **k: [])
    captured = {}
    def stop(command, **kwargs):
        captured.update(command=command, **kwargs)
        raise RuntimeError('launch observed')
    monkeypatch.setattr(workflow.subprocess, 'Popen', stop)
    with pytest.raises(RuntimeError, match='launch observed'):
        workflow._production_dispatch_handoffs([
            {'request_path': request_path, 'response_path': 'hermes/responses/draft.json', 'task': task}],
            30, run / 'revisions/r1', workflow.CERTIFIED_HERMES_CONFIGURATION,
            skill_root=root, run_dir=run, runtime_identity={'executable': sys.executable}, host_mode='hermes-tui')
    if checkpoint_state != 'draft':
        assert progress.is_file()
        assert progress.read_bytes() == (b'authenticated checkpoint bytes' if checkpoint_state == 'existing' else b'')
    assert captured['command'][:2] == [sys.executable, str(launcher)]
    assert '--safe-mode' in captured['command']
    assert captured['start_new_session'] is True
    assert captured['env']['HERMES_HOME'].startswith(str(run / '.hermes-cache'))
    assert captured['env']['HTTPS_PROXY'].startswith('http://127.0.0.1:')
    assert captured['env']['CLINICAL_PYTHON'] == sys.executable
    prompt = captured['command'][captured['command'].index('-q') + 1]
    assert '"$CLINICAL_PYTHON" -B' in prompt
    assert not list(root.parent.parent.joinpath('.tmp').glob('clinical-production-adapter-*.sock'))


def test_incomplete_review_remains_review_only_and_locally_available(tmp_path, monkeypatch):
    from test_review_output import _candidate_run
    run, _ = _candidate_run(tmp_path, monkeypatch, 'Retrospective')
    monkeypatch.setattr(workflow, 'generate', lambda *a, **k: {
        'status': 'blocked', 'stage': 'independent_verification',
        'findings': [{'issue': 'Page inspection incomplete.'}], 'client_outputs': []})
    arguments = {'handoff_runner': lambda *a: None, 'opener': workflow.local_output_reader(run),
        'release_identity': {'package_fingerprint': 'fixture', 'host_mode': 'hermes-tui'}, 'require_promoted_runtime': False}
    result = workflow.run_desktop_operation(run, **arguments)
    assert result['status'] == 'review_required'
    assert result['review_delivery']['confirmed'] is False
    assert result['review_delivery']['bytes_verified'] is True
    assert result['recipient_delivery_verified'] is False
    assert 'NOT CLIENT READY' in (run / result['review_notice']).read_text()
    assert workflow.run_desktop_operation(run, **arguments)['review_outputs'] == result['review_outputs']


@pytest.mark.parametrize('unsafe', ['absolute', 'traversal', 'file-symlink', 'directory-symlink', 'occupied-directory'])
def test_checkpoint_preparation_rejects_unsafe_paths_without_changing_evidence(tmp_path, unsafe):
    revision = tmp_path / 'revision'
    revision.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    sentinel = outside / 'saved.json'
    sentinel.write_bytes(b'original evidence')
    relative = 'progress/saved.json'
    if unsafe == 'absolute':
        relative = str(sentinel)
    elif unsafe == 'traversal':
        relative = '../outside/saved.json'
    elif unsafe == 'directory-symlink':
        (revision / 'progress').symlink_to(outside, target_is_directory=True)
    else:
        (revision / 'progress').mkdir()
        if unsafe == 'file-symlink':
            (revision / relative).symlink_to(sentinel)
        else:
            (revision / relative).mkdir()
    with pytest.raises((ValueError, workflow.NativeRepairIntegrityError)):
        workflow._prepare_worker_checkpoint(revision, relative)
    assert sentinel.read_bytes() == b'original evidence'
    assert sorted(p.name for p in outside.iterdir()) == ['saved.json']


def test_native_worker_imports_leave_installed_runtime_unchanged(tmp_path):
    import sys
    root = tmp_path / 'profile/skills/clinical-document-generation'
    module = root / 'runtime/python/pypdfium2/__init__.py'
    module.parent.mkdir(parents=True)
    module.write_text('VERSION = "probe"\n')
    environment = workflow._production_subprocess_environment(root)
    program = 'import sys; sys.path.insert(0, sys.argv[1]); import pypdfium2; assert pypdfium2.VERSION == "probe"'
    for _ in range(2):
        result = subprocess.run([sys.executable, '-c', program, str(module.parent.parent)],
            env=environment, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert sorted(str(p.relative_to(root / 'runtime')) for p in (root / 'runtime').rglob('*') if p.is_file()) == ['python/pypdfium2/__init__.py']
