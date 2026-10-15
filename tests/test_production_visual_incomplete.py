"""Real production dispatch/route with tiny local children, not clinical judgments."""
import json
import os
import subprocess
import sys
from pathlib import Path
import pytest
import workflow
from visual_review import create_visual_review_unit, visual_review_result
from test_visual_units import parent_fixture, response_for


@pytest.mark.parametrize('parallel', [False, True])
@pytest.mark.parametrize('fault', ['ordinary', 'persistent', 'launch', 'cleanup', 'authentication', 'renderer', 'ledger', 'bad_final_hash', 'malformed_final', 'unknown_exit', 'bad_final_file', 'bad_final_file_complete_progress', 'self_term', 'own_budget', 'own_budget_exit2', 'bound_parent_term', 'unknown_exit_complete', 'missing_binding_key', 'own_budget_bad_final_file', 'own_budget_bad_stdout', 'cleanup_replace_final', 'bad_final_hash_complete_progress', 'missing_binding_complete_progress', 'malformed_complete_progress', 'bad_then_good_stdout', 'good_then_bad_stdout', 'valid_stdout', 'malformed_nested_complete_progress', 'malformed_then_good_stdout', 'good_then_malformed_stdout', 'log_prefixed_malformed', 'disk_missing_binding_complete_progress', 'ordinary_log_valid_stdout', 'json_envelope_valid_stdout', 'quoted_brace_valid_stdout', 'own_budget_keyboardinterrupt', 'self_int', 'bound_parent_keyboardinterrupt'])
def test_production_missing_visual_scope_reaches_only_safe_fallback(tmp_path, monkeypatch, parallel, fault):
    run = tmp_path / 'run'
    revision, parent_path, parent = parent_fixture(run, 'retrospective')
    reference = run / workflow.REFERENCE
    reference.parent.mkdir(parents=True)
    reference.write_text(json.dumps({'approval': {'revision_id': 'r1'}}))
    root = tmp_path / 'skill'
    root.mkdir()
    (root / 'bin').mkdir()
    (root / 'bin/hermes').write_text('# controlled local launcher')
    (root / workflow.RELEASE_MANIFEST).write_text('{}')
    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setattr(workflow, '_installed_release_identity', lambda *a: {'package_fingerprint': 'fixture', 'git_commit': 'fixture'})
    monkeypatch.setattr(workflow, '_production_worker_readiness', lambda *a, **k: {'status': 'passed'})
    renderer_ok = [True]
    monkeypatch.setattr(workflow, '_pdfium_runtime_integrity', lambda *a, **k: {'status': 'passed' if renderer_ok[0] else 'blocked'})
    monkeypatch.setattr(workflow, '_manifest_integrity', lambda *a, **k: [])
    monkeypatch.setattr(workflow, '_managed_hermes_pair', lambda: (root / 'bin/hermes', Path(sys.executable)))
    monkeypatch.setattr(workflow, '_production_subprocess_environment', lambda _: {**os.environ, 'HERMES_HOME': str(home)})
    monkeypatch.setattr(workflow, '_production_sandbox_prefix', lambda *a, **k: [])
    monkeypatch.setattr(workflow, '_production_agent_prompt', lambda _root, _rev, h, *_a, **_k: json.dumps(h))
    class Proxy:
        port = 43101
        def close(self): pass
    monkeypatch.setattr(workflow, '_start_production_connect_proxy', lambda **k: Proxy())
    real_popen = subprocess.Popen
    launched, callbacks = [], []
    def popen(command, **options):
        if '-q' not in command:
            return real_popen(command, **options)
        h = json.loads(command[command.index('-q') + 1])
        if fault == 'launch': raise RuntimeError('controlled unknown launch integrity failure')
        unit = json.loads((revision / h['request_path']).read_text())
        response = response_for(unit)
        response['visual_assessments'] = response['visual_assessments'][:1]
        response['status'] = 'in_progress'
        target = revision / unit['review_transport']['progress_path']
        if fault.startswith('finding_'):
            row = response['visual_assessments'][0]
            row['status'] = 'blocked'
            response['findings'] = [{'target_id': row['target_id'], 'artifact': row['artifact'],
                'page': row['pages'][0]['page'], 'check': row['checks'][0],
                'element': 'Controlled paragraph', 'recommended_action': 'Repair controlled defect',
                'issue': 'Retained checkpoint concern', 'finding_id': 'retained-concern'}]
        code = (f'from pathlib import Path; p=Path({str(target)!r}); p.write_text({json.dumps(response)!r})'
                if not launched else 'from pathlib import Path')
        if fault in {'bad_final_hash', 'bad_final_hash_complete_progress'}:
            bad = response_for(unit)
            bad['request_sha256'] = '0' * 64
            bad['status'] = 'passed'
            code += '; print(' + repr(json.dumps(bad)) + ')'
        if fault == 'malformed_nested_complete_progress':
            code += '; print(' + repr('{"schema_version":"hermes-response/v2","request_sha256": INVALID,"producer":{"model_id":"controlled"}}') + ')'
        if fault in {'malformed_then_good_stdout', 'good_then_malformed_stdout', 'log_prefixed_malformed'}:
            malformed = '{"request_id":' + json.dumps(unit['request_id']) + ',"request_sha256":"' + '0'*64 + '","visual_assessments":['
            good = json.dumps(response_for(unit))
            lines = ([malformed, good] if fault == 'malformed_then_good_stdout' else
                     [good, malformed] if fault == 'good_then_malformed_stdout' else ['INFO ordinary lifecycle log ' + malformed])
            for line in lines:
                code += '; print(' + repr(line) + ')'
        if fault == 'disk_missing_binding_complete_progress':
            bad = response_for(unit); del bad['request_sha256']
            final = revision / unit['response_path']
            code += '; q=Path(' + repr(str(final)) + '); q.parent.mkdir(parents=True,exist_ok=True); q.write_text(' + repr(json.dumps(bad)) + ')'
            code += '; Path(' + repr(str(target)) + ').write_text(' + repr(json.dumps(response_for(unit))) + ')'
        if fault in {'json_envelope_valid_stdout', 'quoted_brace_valid_stdout'}:
            good = response_for(unit)
            if fault == 'json_envelope_valid_stdout':
                good = {'response': good}
            else:
                good['visual_assessments'][0]['notes'] = 'Inspected literal {"request_sha256": INVALID} in quoted fixture notes'
            code += '; print(' + repr(json.dumps(good, indent=2)) + ')'
        if fault == 'ordinary_log_valid_stdout':
            code += '; print("INFO ordinary cache {miss}; continuing")'
            code += '; print(' + repr(json.dumps(response_for(unit))) + ')'
        if fault == 'valid_stdout':
            code += '; print(' + repr(json.dumps(response_for(unit))) + ')'
        if fault in {'bad_then_good_stdout', 'good_then_bad_stdout'}:
            good = response_for(unit)
            bad = dict(good, request_sha256='0' * 64)
            finals = (bad, good) if fault == 'bad_then_good_stdout' else (good, bad)
            for final in finals:
                code += '; print(' + repr(json.dumps(final)) + ')'
        if fault in {'malformed_final', 'malformed_complete_progress'}:
            code += '; print("{malformed controlled final")'
        if fault == 'unknown_exit':
            code += '; import sys; print("controlled worker runtime crash", file=sys.stderr); sys.exit(2)'
        if fault in {'bad_final_file', 'bad_final_file_complete_progress'}:
            bad = response_for(unit)
            bad['request_sha256'] = '0' * 64
            final = revision / unit['response_path']
            code += '; p=Path(' + repr(str(final)) + '); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(' + repr(json.dumps(bad)) + ')'
        if fault == 'bad_final_file_complete_progress':
            code += '; Path(' + repr(str(target)) + ').write_text(' + repr(json.dumps(response_for(unit))) + ')'
        if fault == 'unknown_exit_complete':
            code += '; print(' + repr(json.dumps(response_for(unit))) + '); import sys; sys.exit(2)'
        if fault in {'missing_binding_key', 'missing_binding_complete_progress'}:
            bad=response_for(unit); del bad['request_sha256']
            code += '; print(' + repr(json.dumps(bad)) + ')'
        if fault.endswith('complete_progress') and fault not in {'bad_final_file_complete_progress', 'disk_missing_binding_complete_progress'}:
            saved = revision / unit['response_path']
            code += '; q=Path(' + repr(str(saved)) + '); q.parent.mkdir(parents=True,exist_ok=True); q.write_text(' + repr(json.dumps(response)) + ')'
            code += '; Path(' + repr(str(target)) + ').write_text(' + repr(json.dumps(response_for(unit))) + ')'
        if fault in {'own_budget_bad_final_file', 'own_budget_bad_stdout', 'cleanup_replace_final'}:
            bad = response_for(unit); bad['request_sha256'] = '0' * 64
            final = revision / unit['response_path']; final.parent.mkdir(parents=True, exist_ok=True)
            if fault == 'cleanup_replace_final':
                code += '; Path(' + repr(str(final)) + ').write_text(' + repr(json.dumps(response_for(unit))) + ')'
                code += '; Path(' + repr(str(target)) + ').write_text(' + repr(json.dumps(response_for(unit))) + ')'
            action = ('print(' + repr(json.dumps(bad)) + ',flush=True)' if fault.endswith('stdout')
                      else 'Path(' + repr(str(final)) + ').write_text(' + repr(json.dumps(bad)) + ')')
            code += '; import time,signal,sys; signal.signal(signal.SIGTERM,lambda *_: (' + action + ',sys.exit(0))); time.sleep(60)'
        if fault == 'self_int':
            code += '; import os,signal; signal.signal(signal.SIGINT,signal.default_int_handler); os.kill(os.getpid(),signal.SIGINT)'
        if fault in {'own_budget_keyboardinterrupt', 'bound_parent_keyboardinterrupt'}:
            if fault == 'bound_parent_keyboardinterrupt':
                final = revision / unit['response_path']; final.parent.mkdir(parents=True, exist_ok=True)
                code += '; Path(' + repr(str(final)) + ').write_text(' + repr(json.dumps(response_for(unit))) + ')'
            ready = target.with_name(target.name + '.handler-ready')
            code += '; import signal,time; signal.signal(signal.SIGTERM,lambda *_: (_ for _ in ()).throw(KeyboardInterrupt())); Path(' + repr(str(ready)) + ').write_text("ready"); time.sleep(60)'
        if fault == 'self_term':
            code += '; import os,signal; os.kill(os.getpid(),signal.SIGTERM)'
        if fault == 'bound_parent_term':
            code += '; q=Path(' + repr(str(revision / unit['response_path'])) + '); q.parent.mkdir(parents=True,exist_ok=True); q.write_text(' + repr(json.dumps(response_for(unit))) + '); import time; time.sleep(60)'
        if fault in {'own_budget', 'own_budget_exit2'}:
            code += '; import time,signal,sys'
            if fault == 'own_budget_exit2': code += '; signal.signal(signal.SIGTERM,lambda *args: sys.exit(2))'
            code += '; time.sleep(60)'
        transport = fault.removeprefix('finding_').removesuffix('_valid_stdout')
        if transport in {'truncated_disk', 'encoding_disk', 'nonobject_disk',
                         'truncated_stdout', 'encoding_stdout', 'nonobject_stdout'}:
            malformed = (b'{"schema_version":' if transport.startswith('truncated') else
                         b'\xff\xfe' if transport.startswith('encoding') else b'[1, null, "not a response"]')
            if transport.endswith('disk'):
                final = revision / unit['response_path']
                code += '; q=Path(' + repr(str(final)) + '); q.parent.mkdir(parents=True,exist_ok=True); q.write_bytes(' + repr(malformed) + ')'
            else:
                code += '; import sys; sys.stdout.buffer.write(' + repr(malformed) + '); sys.stdout.flush()'
        if fault == 'finding_later_pass' or fault.endswith('_disk_valid_stdout'):
            code += '; print(' + repr(json.dumps(response_for(unit))) + ')'
        if fault == 'authentication':
            code += '; import sys; print("authentication required", file=sys.stderr); sys.exit(1)'
        child = real_popen([sys.executable, '-B', '-c', code], **options)
        launched.append(child)
        if fault not in {'own_budget', 'own_budget_exit2', 'bound_parent_term', 'own_budget_bad_final_file', 'own_budget_bad_stdout', 'cleanup_replace_final', 'own_budget_keyboardinterrupt', 'bound_parent_keyboardinterrupt'}:
            assert child.wait(timeout=5) == (1 if fault == 'authentication' else -2 if fault == 'self_int' else -15 if fault == 'self_term' else 2 if fault in {'unknown_exit', 'unknown_exit_complete'} else 0)
        else:
            import time
            until=time.monotonic()+3
            if fault in {'own_budget_keyboardinterrupt', 'bound_parent_keyboardinterrupt'}:
                while not ready.exists() and time.monotonic() < until: time.sleep(.01)
                assert ready.exists(), 'TERM handler not installed before dispatch starts'
            while launched == [child] and (not target.exists() or target.stat().st_size == 0) and time.monotonic()<until: time.sleep(.01)
        if fault == 'bad_request_hash':
            request_path = revision / h['request_path']
            changed = json.loads(request_path.read_text())
            changed['request_sha256'] = '0' * 64
            request_path.write_text(json.dumps(changed))
        if fault == 'manifest': (root / workflow.RELEASE_MANIFEST).write_text('{"mutated":true}')
        if fault == 'postcheck_raise':
            def broken_postcheck(*args, **kwargs): raise RuntimeError('controlled runtime postcheck failure')
            monkeypatch.setattr(workflow, '_pdfium_runtime_integrity', broken_postcheck)
        if fault == 'renderer': renderer_ok[0] = False
        if fault == 'ledger':
            ledger = revision / f"hermes/visual-review-ledgers/{unit['request_id']}.json"
            value = json.loads(ledger.read_text())
            value['integrity_rejection'] = {'issue': 'controlled poisoned assignment'}
            ledger.write_text(json.dumps(value))
        return child
    monkeypatch.setattr(workflow.subprocess, 'Popen', popen)
    original_reap = workflow._reap_production_worker
    def reap(*args):
        original_reap(*args)
        if fault == 'cleanup': raise RuntimeError('controlled cleanup failure')
    monkeypatch.setattr(workflow, '_reap_production_worker', reap)
    # Parallel ordinary work is separate from real visual production dispatch.
    original_dispatch = workflow._production_dispatch_handoffs
    def dispatch(items, *args, **kwargs):
        if items[0].get('task') == 'ordinary-fixture': return
        if fault in {'own_budget', 'own_budget_exit2', 'own_budget_bad_final_file', 'own_budget_bad_stdout', 'cleanup_replace_final', 'own_budget_keyboardinterrupt', 'bound_parent_keyboardinterrupt'}:
            args=list(args); args[0]=5.15; args=tuple(args)
        return original_dispatch(items, *args, **kwargs)
    monkeypatch.setattr(workflow, '_production_dispatch_handoffs', dispatch)
    def callback(items, budget, active_revision, config):
        callbacks.append((budget, visual_review_result(revision, parent_path, publish=False)))
        if fault == 'persistent': return
        missing = visual_review_result(revision, parent_path, publish=False)['missing']
        for index, target in enumerate(missing):
            p = create_visual_review_unit(revision, parent_path, [target], 30 + index)
            unit = json.loads(p.read_text())
            out = revision / unit['response_path']
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(response_for(unit)))
        visual_review_result(revision, parent_path)
    def generate(*args, **kwargs):
        if (revision / parent['response_path']).exists():
            return {'status': 'blocked', 'stage': 'synthetic_probe_done', 'findings': [], 'client_outputs': []}
        h = {'task': parent['task'], 'fallback_owner': 'parent', 'request_id': parent['request_id'],
             'request_sha256': parent['request_sha256'], 'request_path': parent_path.relative_to(revision).as_posix(),
             'response_path': parent['response_path']}
        return {'status': 'awaiting_hermes', 'stage': 'independent_verification', 'revision_id': 'r1',
                'handoffs': [h] + ([{'task': 'ordinary-fixture', 'request_path': 'not-read.json'}] if parallel else [])}
    monkeypatch.setattr(workflow, 'generate', generate)
    result = workflow.run_production_desktop_operation(run, skill_root=root, host_mode='hermes-tui',
        manual_review=True, parent_visual_reviewer=callback, opener=workflow.local_output_reader(run))
    observation = {'fault': fault, 'parallel': parallel, 'result_stage': result.get('stage'),
        'status': result.get('status'), 'callback_count': len(callbacks),
        'callback_budget': callbacks[0][0] if callbacks else None,
        'retained_assessments': len(callbacks[0][1]['assessments']) if callbacks else None,
        'missing_at_callback': len(callbacks[0][1]['missing']) if callbacks else None,
        'returncodes': [p.poll() for p in launched], 'client_outputs': result.get('client_outputs'), 'result': result}
    (tmp_path / 'observation.json').write_text(json.dumps(observation) + '\n')
    assert all(p.poll() is not None for p in launched)
    if fault == 'self_int':
        # Assert outside the adapter: it deliberately catches launch errors,
        # including fixture assertions, and could otherwise mask a bad probe.
        assert launched and all(p.returncode == -2 for p in launched)
    assert not result.get('client_outputs')
    if fault.endswith('_disk_valid_stdout'):
        assert not callbacks
        assert result['stage'] == 'synthetic_probe_done'
        return
    if fault.startswith('finding_'):
        retained = visual_review_result(revision, parent_path, publish=False)
        assert any(f['finding_id'] == 'retained-concern' for f in retained['findings'])
        assert retained['assessments'][0]['status'] == 'blocked'
        assert not callbacks, 'Substantive findings must return to generation/repair, not missing-scope fallback'
        assert result['stage'] == 'synthetic_probe_done'
        assert any(f['finding_id'] == 'retained-concern' for f in json.loads((revision / parent['response_path']).read_text())['findings'])
        return
    if fault in {'launch', 'cleanup', 'authentication', 'renderer', 'ledger', 'bad_final_hash', 'bad_request_hash', 'manifest', 'postcheck_raise', 'unknown_exit', 'bad_final_file', 'bad_final_file_complete_progress', 'self_term', 'own_budget_exit2', 'unknown_exit_complete', 'missing_binding_key', 'own_budget_bad_final_file', 'own_budget_bad_stdout', 'cleanup_replace_final', 'bad_final_hash_complete_progress', 'missing_binding_complete_progress', 'bad_then_good_stdout', 'good_then_bad_stdout', 'disk_missing_binding_complete_progress', 'self_int'}:
        assert callbacks == []
        assert result['stage'] == ('worker_authentication' if fault == 'authentication' else 'parent_visual_integrity')
    else:
        if fault in {'malformed_complete_progress', 'malformed_nested_complete_progress', 'bound_parent_term', 'valid_stdout', 'ordinary_log_valid_stdout', 'json_envelope_valid_stdout', 'quoted_brace_valid_stdout', 'bound_parent_keyboardinterrupt'}:
            assert not callbacks
            assert result['stage']=='synthetic_probe_done'
            return
        assert callbacks, 'Production ordinary incompletion was mislabeled fatal before fallback'
        assert callbacks[0][0] > 0
        assert callbacks[0][1]['assessments'], 'Authenticated partial judgments lost'
        # A callback returning without any response is still a fatal adapter
        # contract violation; invoking it is not evidence of completed review.
        assert result['stage'] == ('parent_visual_integrity' if fault == 'persistent' else 'synthetic_probe_done')
