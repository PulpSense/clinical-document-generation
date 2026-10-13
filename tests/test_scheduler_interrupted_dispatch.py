"""Dispatch-boundary crash regression, promoted from the independent diagnosis.
Tiny integrity inventory and real worker subprocesses; no clinical/model claim.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import quality
import workflow
from test_content_review_recovery import operation, FAMILIES
from test_handoff_quality import acceptance_verification
from test_parent_runtime_guard import lightweight_renderer

class ParentStopped(BaseException):
    pass


@pytest.mark.parametrize('manual_review', [True, False])
@pytest.mark.parametrize('saved', ['checkpoint', 'final'])
def test_dispatch_rejection_survives_stop_before_scheduler_persistence(
    tmp_path, lightweight_renderer, monkeypatch, saved, manual_review,
):
    manual = manual_review
    case = f'{saved}-' + ('candidate' if manual else 'promoted')
    evidence = tmp_path / ('integration-' + case)
    evidence.mkdir(exist_ok=True)
    root = tmp_path
    mp = monkeypatch
    run = root / 'run'
    runtime_file = root / 'runtime/python/renderer.py'
    original = runtime_file.read_bytes()
    real_operation = workflow.run_desktop_operation
    real_popen = subprocess.Popen
    active, launched, rejected, dispatched, errors = [], [], [], [], []
    wave = [0]
    stale_parent = [None]
    mp.setattr(workflow, '_managed_hermes_pair', lambda: (root / 'bin/hermes', Path(sys.executable)))
    mp.setattr(workflow, '_production_subprocess_environment', lambda _: {**os.environ, 'HERMES_HOME': str(root / 'home')})
    mp.setattr(workflow, '_production_sandbox_prefix', lambda *a, **k: [])
    mp.setattr(workflow, '_production_agent_prompt', lambda *a, **k: 'unused')
    mp.setattr(workflow, '_production_publish_quiet_response', lambda *a: None)
    class Proxy:
        port = 43101
        def close(self):
            pass
    mp.setattr(workflow, '_start_production_connect_proxy', lambda **k: Proxy())

    def popen(command, **kwargs):
        if not active:
            return real_popen(command, **kwargs)
        revision = next((run / 'revisions').iterdir())
        handoff = active[len(launched)]
        request = json.loads((revision / handoff['request_path']).read_text())
        response = acceptance_verification(request)
        relative = request['review_transport']['progress_path'] if saved == 'checkpoint' else request['response_path']
        code = ('from pathlib import Path\n'
                f'p=Path({str(revision / relative)!r}); p.parent.mkdir(parents=True, exist_ok=True); p.write_text({json.dumps(response)!r})\n')
        if wave[0] == 2:
            code += f'p=Path({str(runtime_file)!r}); p.write_bytes(p.read_bytes()+b"# unauthorized\\n")\n'
        child = real_popen([sys.executable, '-B', '-c', code], **kwargs)
        launched.append(child)
        assert child.wait(timeout=5) == 0
        # Simulate a stale saved parent assembled before the dispatch postcheck.
        if wave[0] == 2 and len(launched) == len(active):
            parent = next((revision / 'hermes/verification-requests').glob('*content.json'))
            schedule = json.loads(next((revision / 'hermes/review-schedules').glob('*.json')).read_text())
            stale_parent[0] = quality.content_review_schedule_result(revision, parent,
                [revision / v for v in schedule['requests']], publish=False)['response']
        return child
    mp.setattr(workflow.subprocess, 'Popen', popen)

    def wrapped(root_run, **options):
        ordinary = options['handoff_runner']
        def dispatch(items, budget):
            if not items or '.unit-' not in str(items[0].get('request_id') or ''):
                return ordinary(items, budget)
            wave[0] += 1
            active[:] = items
            launched.clear()
            dispatched.extend(h['request_id'] for h in items)
            revision = next((run / 'revisions').iterdir())
            try:
                workflow._production_dispatch_handoffs(items, budget, revision,
                    workflow.CERTIFIED_HERMES_CONFIGURATION, skill_root=root,
                    run_dir=run, runtime_identity={'executable': sys.executable},
                    require_promoted_runtime=not manual)
            except Exception as exc:
                errors.append({'type': type(exc).__name__, 'message': str(exc),
                    'integrity_failure': getattr(exc, 'worker_integrity_failure', None)})
                if wave[0] != 2:
                    raise  # Checkpoint-only exit may be ordinary incomplete transport.
                rejected.extend(items)
                # Stop before scheduler catches the error or records this wave.
                raise ParentStopped() from exc
            finally:
                active.clear()
        options['handoff_runner'] = options['fallback_handoff_runner'] = dispatch
        return real_operation(root_run, **options)
    mp.setattr(workflow, 'run_desktop_operation', wrapped)
    with pytest.raises(ParentStopped):
        operation(run, mp, FAMILIES[-1], lambda r,s,d: s, lambda r,s,d,h: s)
    revision = next((run / 'revisions').iterdir())
    parent = next((revision / 'hermes/verification-requests').glob('*content.json'))
    schedule_path = next((revision / 'hermes/review-schedules').glob('*.json'))
    schedule = json.loads(schedule_path.read_text())
    initial_state = json.loads((run / 'logs/desktop-operation.json').read_text())
    approved = (revision / 'approved-reference.json').read_bytes()
    assert quality._pdfium_runtime_integrity(root, require_promoted_runtime=not manual)['status'] == 'blocked'
    assert len(schedule['waves']) == 1 and schedule['waves'][0]['gained_assessments'] == 9
    assert errors and any(e['integrity_failure'] for e in errors), errors
    assert rejected
    for h in rejected:
        ledger = revision / f"hermes/content-review-ledgers/{h['request_id']}.json"
        assert 'integrity_rejection' in json.loads(ledger.read_text())
        shutil.copy2(ledger, evidence / ledger.name)
    runtime_file.write_bytes(original)
    assert quality._pdfium_runtime_integrity(root, require_promoted_runtime=not manual)['status'] == 'passed'
    assert all(quality.content_review_unit_result(revision, revision / h['request_path']) is None for h in rejected)
    assert stale_parent[0] is not None
    (revision / json.loads(parent.read_text())['response_path']).write_text(json.dumps(stale_parent[0]))
    findings, _ = quality.validate_verifications(revision, request_paths=[parent])
    assert any(f.get('code') == 'scheduled_review_evidence_invalid' for f in findings), findings
    recovered = quality.content_review_schedule_result(revision, parent, [revision / v for v in schedule['requests']])
    assert recovered['completed'] == 9 and not recovered['complete']
    resumed = []
    def clean_dispatch(items, budget):
        for h in items:
            resumed.append(h['request_id'])
            request = json.loads((revision / h['request_path']).read_text())
            path = revision / request['response_path']
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(acceptance_verification(request)))
    result = real_operation(run, handoff_runner=clean_dispatch, fallback_handoff_runner=clean_dispatch,
        opener=lambda p: Path(p).read_bytes(), budget_seconds=180, require_promoted_runtime=False)
    assert result['status'] == 'passed', result
    assert not set(resumed) & set(dispatched), 'Earlier productive or rejected request was redispatched'
    assert all(quality.content_review_unit_result(revision, revision / h['request_path']) is None for h in rejected)
    final_state = json.loads((run / 'logs/desktop-operation.json').read_text())
    assert all(initial_state[k] == final_state[k] for k in ('started_at_epoch','deadline_at_epoch','approval_identity'))
    assert approved == (revision / 'approved-reference.json').read_bytes()
    record = {'case': case, 'status': 'passed', 'actual_worker_subprocesses': sum(len(w['workloads']) for w in schedule['waves']) + len(rejected),
        'poisoned_unit_count': len(rejected), 'completed_after_recovery': recovered['completed'],
        'persisted_waves_at_interruption': len(schedule['waves']), 'stale_parent_rejected_codes': [f.get('code') for f in findings],
        'resumed_request_count': len(resumed), 'resumed_requests_overlap_old': False,
        'approval_and_deadline_preserved': True, 'final_status': result['status'], 'errors': errors}
    (evidence / 'outcome.json').write_text(json.dumps(record, indent=2))
    (evidence / 'schedule-at-interruption.json').write_text(json.dumps(schedule, indent=2))
    (evidence / 'stale-parent.json').write_text(json.dumps(stale_parent[0], indent=2))
    shutil.copy2(schedule_path, evidence / 'schedule-after-resume.json')
    print(json.dumps(record), flush=True)
