"""Public Desktop scheduling must not credit runtime-poisoned wave evidence.

The tiny inventory is integrity-only: no rendering or paid model calls.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import quality
import workflow
from test_content_review_recovery import operation, FAMILIES
from test_handoff_quality import acceptance_verification
from test_parent_runtime_guard import lightweight_renderer


@pytest.mark.parametrize('manual_review', [True])
@pytest.mark.parametrize('recovery', ['aggregate', 'resume'])
@pytest.mark.parametrize('poison_wave', [1, 2])
@pytest.mark.parametrize('failure', ['none', 'cleanup', 'launch'])
def test_public_schedule_disqualifies_poisoned_saved_wave(
    tmp_path, lightweight_renderer, monkeypatch, manual_review, poison_wave, failure, recovery,
):
    class InterruptedParent(BaseException):
        pass
    real_schedule_result = workflow.content_review_schedule_result
    interrupted = []
    def schedule_result(revision, parent_path, paths, **options):
        result = real_schedule_result(revision, parent_path, paths, **options)
        ledger_path = revision / f"hermes/review-schedules/{json.loads(parent_path.read_text())['request_id']}.json"
        if recovery == 'resume' and not interrupted and ledger_path.is_file():
            waves = json.loads(ledger_path.read_text())['waves']
            if waves and 'integrity_rejection' in waves[-1]:
                interrupted.append(True)
                raise InterruptedParent()
        return result
    monkeypatch.setattr(workflow, 'content_review_schedule_result', schedule_result)
    target = tmp_path / 'runtime/python/renderer.py'
    original_runtime = target.read_bytes()
    run = tmp_path / 'run'
    real_operation = workflow.run_desktop_operation
    real_popen = subprocess.Popen
    wave = [0]
    active_handoffs = []
    launched = []
    poisoned = []
    observed_errors = []
    monkeypatch.setattr(workflow, '_managed_hermes_pair', lambda: (tmp_path / 'bin/hermes', Path(sys.executable)))
    monkeypatch.setattr(workflow, '_production_subprocess_environment', lambda _: {**os.environ, 'HERMES_HOME': str(tmp_path / 'home')})
    monkeypatch.setattr(workflow, '_production_sandbox_prefix', lambda *a, **k: [])
    monkeypatch.setattr(workflow, '_production_agent_prompt', lambda *a, **k: 'unused')
    monkeypatch.setattr(workflow, '_production_publish_quiet_response', lambda *a: None)

    class Proxy:
        port = 43101
        def close(self):
            if failure == 'cleanup' and wave[0] == poison_wave:
                raise RuntimeError('ordinary cleanup diagnostic')
    monkeypatch.setattr(workflow, '_start_production_connect_proxy', lambda **k: Proxy())

    def popen(command, **kwargs):
        if not active_handoffs:
            return real_popen(command, **kwargs)
        if failure == 'launch' and wave[0] == poison_wave and launched:
            raise RuntimeError('ordinary launch diagnostic')
        handoff = active_handoffs[len(launched)]
        revision = next((run / 'revisions').iterdir())
        request_path = revision / handoff['request_path']
        request = json.loads(request_path.read_text())
        response = acceptance_verification(request)
        code = 'from pathlib import Path\n'
        for relative in (request['response_path'], request['review_transport']['progress_path']):
            code += f'p = Path({str(revision / relative)!r}); p.parent.mkdir(parents=True, exist_ok=True); p.write_text({json.dumps(response)!r})\n'
        if wave[0] == poison_wave:
            code += f'p = Path({str(target)!r}); p.write_bytes(p.read_bytes() + b"# unauthorized\\n")\n'
        process = real_popen([sys.executable, '-B', '-c', code], **kwargs)
        launched.append(process)
        assert process.wait(timeout=5) == 0
        return process
    monkeypatch.setattr(workflow.subprocess, 'Popen', popen)

    def wrapped_operation(root, **options):
        ordinary = options['handoff_runner']
        def dispatch(items, budget):
            if not items or '.unit-' not in str(items[0].get('request_id') or ''):
                return ordinary(items, budget)
            wave[0] += 1
            active_handoffs[:] = items
            launched.clear()
            if wave[0] == poison_wave:
                poisoned.extend(items)
            revision = next((run / 'revisions').iterdir())
            try:
                return workflow._production_dispatch_handoffs(items, budget, revision,
                    workflow.CERTIFIED_HERMES_CONFIGURATION, skill_root=tmp_path,
                    run_dir=run, runtime_identity={'executable': sys.executable},
                    require_promoted_runtime=False)
            except Exception as exc:
                observed_errors.append(exc)
                raise
            finally:
                active_handoffs.clear()
        options['handoff_runner'] = options['fallback_handoff_runner'] = dispatch
        return real_operation(root, **options)
    monkeypatch.setattr(workflow, 'run_desktop_operation', wrapped_operation)
    if recovery == 'resume':
        with pytest.raises(InterruptedParent):
            operation(run, monkeypatch, FAMILIES[-1],
                lambda r, s, d: s, lambda r, s, d, h: s)
        revision = next((run / 'revisions').iterdir())
        original_state = json.loads((run / 'logs/desktop-operation.json').read_text())
    else:
        result, revision, _ = operation(run, monkeypatch, FAMILIES[-1],
            lambda r, s, d: s, lambda r, s, d, h: s)
        assert result['status'] != 'passed'
    assert quality._pdfium_runtime_integrity(tmp_path, require_promoted_runtime=False)['status'] == 'blocked', (wave, observed_errors)
    ledger_path = next((revision / 'hermes/review-schedules').glob('*.json'))
    ledger = json.loads(ledger_path.read_text())
    assert ledger['waves'][poison_wave - 1]['gained_assessments'] == 0, ledger['waves']
    assert poisoned and observed_errors
    # Repairing the runtime cannot rehabilitate either checkpoint or final.
    target.write_bytes(original_runtime)
    assert quality._pdfium_runtime_integrity(tmp_path, require_promoted_runtime=False)['status'] == 'passed'
    for handoff in poisoned:
        assert quality.content_review_unit_result(revision, revision / handoff['request_path']) is None
    parent_path = next((revision / 'hermes/verification-requests').glob('*content.json'))
    paths = [revision / value for value in ledger['requests']]
    recovered = quality.content_review_schedule_result(revision, parent_path, paths)
    assert recovered['completed'] == (0 if poison_wave == 1 else 9)
    assert not quality.verification_response_is_complete(revision, parent_path)
    if recovery == 'resume':
        approved = (revision / 'approved-reference.json').read_bytes()
        resumed_requests = []
        def clean_dispatch(items, budget):
            for handoff in items:
                request = json.loads((revision / handoff['request_path']).read_text())
                resumed_requests.append(request['request_id'])
                path = revision / request['response_path']
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(acceptance_verification(request)))
        result = real_operation(run, handoff_runner=clean_dispatch,
            fallback_handoff_runner=clean_dispatch, opener=lambda p: Path(p).read_bytes(),
            budget_seconds=180, require_promoted_runtime=False)
        assert result['status'] == 'passed', result
        final_state = json.loads((run / 'logs/desktop-operation.json').read_text())
        for key in ('started_at_epoch', 'deadline_at_epoch', 'approval_identity'):
            assert final_state[key] == original_state[key]
        assert (revision / 'approved-reference.json').read_bytes() == approved
        assert not set(resumed_requests) & {h['request_id'] for h in poisoned}
        for handoff in poisoned:
            assert quality.content_review_unit_result(revision, revision / handoff['request_path']) is None
    if failure != 'none':
        assert any('ordinary ' + failure + ' diagnostic' in str(exc if failure == 'launch' else exc.__cause__.__cause__) for exc in observed_errors)


@pytest.mark.parametrize('saved', ['checkpoint', 'final'])
def test_public_schedule_preserves_saved_judgments_on_ordinary_error(tmp_path, monkeypatch, saved):
    def worker(request, response, revision, *args):
        relative = (request['review_transport']['progress_path']
                    if saved == 'checkpoint' else request['response_path'])
        path = revision / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(response))
        raise RuntimeError('Ordinary provider interruption after productive judgments')
    result, revision, _ = operation(tmp_path, monkeypatch, FAMILIES[-1], worker, worker)
    assert result['status'] == 'passed', result
    ledger = json.loads(next((revision / 'hermes/review-schedules').glob('*.json')).read_text())
    assert ledger['waves'][0]['gained_assessments'] == 3
    assert all('integrity_rejection' not in wave for wave in ledger['waves'])
    assert all('integrity_rejection' not in json.loads(path.read_text())
               for path in (revision / 'hermes/content-review-ledgers').glob('*.json'))
