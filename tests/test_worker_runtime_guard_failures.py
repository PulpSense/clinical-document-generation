"""Post-wave strict checks survive launch and cleanup errors without hiding them."""
import os
from pathlib import Path
import subprocess
import sys

import pytest
import workflow


@pytest.mark.parametrize('failure', ['launch', 'missing-launch', 'cleanup'])
@pytest.mark.parametrize('mutation', ['changed', 'added-cache', 'intact'])
def test_executed_worker_failure_retains_error_and_checks_renderer(
    tmp_path, governed_pdfium, monkeypatch, failure, mutation,
):
    run = tmp_path / 'run'
    revision = run / 'revision'
    revision.mkdir(parents=True)
    runtime = tmp_path / 'runtime/python'
    target = next(runtime.rglob('*.py'))
    marker = run / 'worker-executed'
    calls = []
    real_integrity = workflow._pdfium_runtime_integrity

    def integrity(*args, **kwargs):
        result = real_integrity(*args, **kwargs)
        calls.append(result)
        return result

    monkeypatch.setattr(workflow, '_pdfium_runtime_integrity', integrity)
    monkeypatch.setattr(workflow, '_managed_hermes_pair', lambda: (tmp_path / 'bin/hermes', Path(sys.executable)))
    monkeypatch.setattr(workflow, '_production_subprocess_environment', lambda _: {**os.environ, 'HERMES_HOME': str(tmp_path / 'home')})
    monkeypatch.setattr(workflow, '_production_sandbox_prefix', lambda *a, **k: [])
    monkeypatch.setattr(workflow, '_production_agent_prompt', lambda *a, **k: 'unused')
    monkeypatch.setattr(workflow, '_production_response_is_bound', lambda *a: True)
    monkeypatch.setattr(workflow, '_production_publish_quiet_response', lambda *a: None)

    class Proxy:
        port = 43101

        def close(self):
            if failure == 'cleanup':
                raise RuntimeError('proxy close diagnostic')

    monkeypatch.setattr(workflow, '_start_production_connect_proxy', lambda **k: Proxy())
    original_popen = subprocess.Popen
    workers = []
    launch_error = FileNotFoundError('second launch diagnostic') if failure == 'missing-launch' else RuntimeError('second launch diagnostic')
    code = f'from pathlib import Path; Path({str(marker)!r}).write_text("executed")\n'
    if mutation == 'changed':
        code += f'p = Path({str(target)!r}); p.write_bytes(p.read_bytes() + b"\\n# changed\\n")\n'
    elif mutation == 'added-cache':
        code += f'p = Path({str(runtime / "__pycache__/unexpected.pyc")!r}); p.parent.mkdir(); p.write_bytes(b"cache")\n'

    def popen(command, **kwargs):
        if workers:
            assert marker.read_text() == 'executed'
            raise launch_error
        worker = original_popen([sys.executable, '-c', code], **kwargs)
        workers.append(worker)
        assert worker.wait(timeout=5) == 0
        return worker

    monkeypatch.setattr(workflow.subprocess, 'Popen', popen)
    handoffs = [{'request_path': f'hermes/requests/{name}.json', 'response_path': f'hermes/responses/{name}.json'} for name in ['a', 'b']]
    expected = 'fully reaped' if failure == 'cleanup' else 'second launch diagnostic'
    with pytest.raises(RuntimeError, match=expected) as caught:
        workflow._production_dispatch_handoffs(
            handoffs[:1] if failure == 'cleanup' else handoffs,
            10, revision, workflow.CERTIFIED_HERMES_CONFIGURATION,
            skill_root=tmp_path, run_dir=run,
            runtime_identity={'executable': sys.executable},
            require_promoted_runtime=True,
        )
    error = caught.value
    if failure == 'launch':
        assert error is launch_error
    elif failure == 'missing-launch':
        assert isinstance(error, workflow.WorkerLaunchUnavailableError)
        assert error.__cause__ is launch_error
    else:
        assert 'proxy close diagnostic' in str(error.__cause__.__cause__)
    assert workers[0].poll() == 0
    assert marker.read_text() == 'executed'
    assert len(calls) == 2, 'strict post-wave integrity check was bypassed'
    assert calls[0]['status'] == 'passed'
    if mutation == 'intact':
        assert calls[1]['status'] == 'passed'
        assert not getattr(error, '__notes__', [])
    else:
        assert calls[1]['status'] != 'passed'
        assert any('renderer runtime changed' in note for note in error.__notes__)
