"""Public production fallback rejects real disposable renderer mutations."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import quality

import pytest
import workflow
from test_desktop_delivery import _visual_handoff_fixture


@pytest.fixture
def lightweight_renderer(tmp_path, request):
    """Tiny integrity-only inventory; never use this fixture for rendering.

    Real files and lifecycle hashes exercise the unmodified strict checker.
    Each case owns its files; no native library or checkout copies accumulate.
    """
    payload = b'# disposable integrity-only fixture\n'
    runtime = tmp_path / 'runtime/python'
    runtime.mkdir(parents=True)
    (runtime / 'renderer.py').write_bytes(payload)
    wheel = tmp_path / 'assets/runtime-wheels/integrity-fixture.whl'
    wheel.parent.mkdir(parents=True)
    with zipfile.ZipFile(wheel, 'w') as archive:
        archive.writestr('renderer.py', payload)
    renderer = {
        'kind': 'pypdfium2', 'version': 'integrity-fixture',
        'wheel': wheel.relative_to(tmp_path).as_posix(),
        'wheel_sha256': hashlib.sha256(wheel.read_bytes()).hexdigest(),
        'platform': 'integrity-fixture',
        'runtime_inventory': [{'path': 'renderer.py', 'bytes': len(payload),
                               'sha256': hashlib.sha256(payload).hexdigest()}],
    }
    manifest = {'inventory': {'pdf_page_renderer': renderer}}
    fingerprint = hashlib.sha256(json.dumps(
        manifest, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
    ).encode()).hexdigest()
    (tmp_path / 'RELEASE-MANIFEST.json').write_text(json.dumps({
        **manifest, 'package_fingerprint': fingerprint,
    }))
    (tmp_path / 'runtime/PDF-RENDERER.json').write_text(json.dumps({
        key: value for key, value in renderer.items() if key != 'runtime_inventory'
    }))
    if not request.node.callspec.params['manual_review']:
        smoke = {'status': 'passed', 'release_identity': {
            'git_commit': None, 'package_fingerprint': fingerprint,
        }}
        assurance = tmp_path / 'INSTALLATION-ASSURANCE.json'
        assurance.write_text(json.dumps({
            'schema_version': 'installation-assurance/v2',
            'status': 'passed', 'active_path_smoke': smoke,
        }))
        (tmp_path / 'PROMOTION-RECORD.json').write_text(json.dumps({
            'schema_version': 'promoted-release/v1', 'status': 'active',
            'package_fingerprint': fingerprint,
            'activation_commit_point': quality.PROMOTED_ACTIVATION_COMMIT_POINT,
            'active_path_smoke_sha256': quality.canonical_evidence_sha256(smoke),
            'runtime_assurance_sha256': hashlib.sha256(assurance.read_bytes()).hexdigest(),
        }))
    try:
        yield
    finally:
        shutil.rmtree(tmp_path)


@pytest.mark.parametrize('manual_review', [False, True])
@pytest.mark.parametrize('outcome', ['success', 'nonzero', 'timeout', 'unbound'])
@pytest.mark.parametrize('mutation', ['changed', 'added-cache', 'missing', 'symlink', 'intact'])
def test_public_parent_fallback_checks_strict_renderer_after_callback(
    tmp_path, lightweight_renderer, monkeypatch, manual_review, outcome, mutation,
):
    _exercise_parent(tmp_path, monkeypatch, manual_review, outcome, mutation, 'during')


@pytest.mark.parametrize('manual_review', [False, True])
@pytest.mark.parametrize('mutation', ['changed', 'added-cache', 'missing', 'symlink'])
def test_public_parent_fallback_checks_renderer_before_executable_launch(
    tmp_path, lightweight_renderer, monkeypatch, manual_review, mutation,
):
    _exercise_parent(tmp_path, monkeypatch, manual_review, 'success', mutation, 'before')


def _exercise_parent(root, monkeypatch, manual_review, outcome, mutation, when):
    run = root / 'run'
    handoff, _request, response = _visual_handoff_fixture(run, 'protocol')
    revision = run / 'revisions/r1'
    reference = run / workflow.REFERENCE
    reference.parent.mkdir(parents=True, exist_ok=True)
    reference.write_text(json.dumps({'approval': {'revision_id': 'r1'}}))
    runtime = root / 'runtime/python'
    target = next(runtime.rglob('*.py'))
    marker = run / 'callback-executed'
    response_path = revision / handoff['response_path']
    mutations = {
        'changed': f'p = Path({str(target)!r}); p.write_bytes(p.read_bytes() + b"\\n# changed\\n")',
        'added-cache': f'p = Path({str(runtime / "__pycache__/unexpected.pyc")!r}); p.parent.mkdir(); p.write_bytes(b"cache")',
        'missing': f'shutil.rmtree(Path({str(runtime)!r}))',
        'symlink': f'p = Path({str(target)!r}); saved = p.with_suffix(".saved"); p.rename(saved); p.symlink_to(saved)',
        'intact': 'pass',
    }
    mutation_code = mutations[mutation]
    command = root / 'parent-callback'
    command.write_text(
        f'#!{sys.executable}\nimport shutil, sys, time\nfrom pathlib import Path\n'
        f'Path({str(marker)!r}).write_text("executed")\n'
        + (mutation_code + '\n' if when == 'during' else '')
        + 'print("callback stdout", flush=True)\nprint("callback stderr", file=sys.stderr, flush=True)\n'
        + (f'p = Path({str(response_path)!r}); p.parent.mkdir(parents=True, exist_ok=True); p.write_text({json.dumps(response)!r})\n' if outcome == 'success' else '')
        + ('sys.exit(7)\n' if outcome == 'nonzero' else 'time.sleep(60)\n' if outcome == 'timeout' else '')
    )
    command.chmod(0o700)
    calls = []
    real_integrity = workflow._pdfium_runtime_integrity
    def integrity(*args, **kwargs):
        result = real_integrity(*args, **kwargs)
        calls.append((kwargs['require_promoted_runtime'], result['status']))
        return result
    monkeypatch.setattr(workflow, '_pdfium_runtime_integrity', integrity)
    monkeypatch.setattr(workflow, '_installed_release_identity', lambda _: {'package_fingerprint': 'fixture', 'git_commit': None})
    monkeypatch.setattr(workflow, '_managed_hermes_identity', lambda: {'fixture': 'unchanged'})
    monkeypatch.setattr(workflow, 'resolve_python_runtime', lambda **_: {'executable': sys.executable})
    monkeypatch.setattr(workflow, '_production_worker_readiness', lambda *a, **k: {'status': 'passed'})
    def invoke_fallback(_run, **options):
        calls.clear()  # Count fallback checks, separately from candidate preflight.
        if when == 'before':
            exec(mutation_code, {'Path': Path, 'shutil': __import__('shutil')})
        # Include isolated supervisor startup; still far below callback's 60s sleep.
        options['fallback_handoff_runner']([handoff], 0.5 if outcome == 'timeout' else 5)
        return {'status': 'fixture-only'}
    monkeypatch.setattr(workflow, 'run_desktop_operation', invoke_fallback)
    callback_errors = []
    executable_reviewer = workflow.command_parent_visual_reviewer(command)
    def parent_reviewer(*args):
        try:
            return executable_reviewer(*args)
        except BaseException as exc:
            callback_errors.append(exc)
            raise
    options = dict(skill_root=root, manual_review=manual_review, opener=lambda _: b'unused',
                   parent_visual_reviewer=parent_reviewer)
    error = None
    if when == 'before' or mutation != 'intact' or outcome != 'success':
        expected = 'runtime integrity' if when == 'before' else 'status 7' if outcome == 'nonzero' else None if outcome == 'timeout' else 'bound terminal response' if outcome == 'unbound' else 'runtime changed'
        with pytest.raises(subprocess.TimeoutExpired if outcome == 'timeout' and when != 'before' else RuntimeError, match=expected) as caught:
            workflow.run_production_desktop_operation(run, **options)
        error = caught.value
    else:
        result = workflow.run_production_desktop_operation(run, **options)
        assert result['parent_visual_review']['status'] == 'completed'
    if when == 'before':
        assert not marker.exists(), 'mutated renderer was allowed to launch callback'
        assert calls == [(not manual_review, 'blocked')]
        return
    assert marker.read_text() == 'executed'
    if outcome != 'success':
        assert len(callback_errors) == 1
        assert error is callback_errors[0], 'original callback exception was replaced'
    else:
        assert not callback_errors
    assert len(calls) == 2, 'strict pre/post fallback integrity boundary was bypassed'
    assert calls[0] == (not manual_review, 'passed')
    assert calls[1] == (not manual_review, 'passed' if mutation == 'intact' else 'blocked')
    if outcome != 'success' and mutation != 'intact':
        assert any('runtime changed' in note for note in error.__notes__)
    elif error is not None:
        assert not getattr(error, '__notes__', [])
    diagnostics = list((run / 'logs/parent-visual-reviewer').glob('*.json'))
    assert len(diagnostics) == 1
    record = json.loads(diagnostics[0].read_text())
    assert record['stdout'] == 'callback stdout\n'
    assert record['stderr'] == 'callback stderr\n'
    assert record['timed_out'] is (outcome == 'timeout')
    assert record['returncode'] is not None
    assert reference.read_text() == json.dumps({'approval': {'revision_id': 'r1'}})
