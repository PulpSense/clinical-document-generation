"""Installed TUI evidence must never masquerade as remote certification."""
import hashlib
import json
from pathlib import Path
import sys

import pytest
import workflow
import ai_quality_campaign as campaign
from readiness_injection import campaign_adapter
from hermes_tui_host_checks import collect


def host_report(identity):
    return {'schema_version': 'hermes-tui-host-checks/v1', 'status': 'passed', 'host_mode': 'hermes-tui',
        'candidate_identity': identity, 'recipient_delivery_verified': False, 'os_isolation_verified': False,
        'checks': {key: {'status': 'passed'} for key in ('profile_login_and_installed_read_tool',
            'bounded_reads_checkpoint_and_native_tools', 'worker_descendant_cleanup',
            'render_before_native_repair', 'render_after_native_repair', 'local_exact_bytes')}}


def test_fixed_tui_campaign_counts_local_audited_outcomes_without_remote_claims():
    identity = {'git_commit': 'candidate'}
    host = host_report(identity)
    manifest = campaign.readiness_plan(identity, 'hermes-tui', host)
    operations = manifest['baseline_operations'] + manifest['supplemental_operations']
    assert len(operations) == 28
    assert len({c['family'] for c in manifest['cases']}) == 5
    f2 = next(p for p in operations if p['case_id'] == 'F2')
    assert any(s['challenge'] == 'transient_local_output_retrieval' for s in f2['seeds'])
    f3 = next(p for p in operations if p['case_id'] == 'F3')
    assert any(s['challenge'] == 'repair_author_unavailable' for s in f3['seeds'])
    rows = [{'operation_id': p['planned_operation_id'], 'planned_operation_id': p['planned_operation_id'],
        'status': p['expected_status'], 'local_bytes_verified': True, 'delivery_confirmed': False,
        'review_delivery_confirmed': False, 'independent_audit_passed': True, 'elapsed_seconds': 100}
        for p in operations]
    summary = campaign.summarize_readiness(manifest, rows)
    assert all(g['rate'] == 1 for g in summary['planned_groups'].values())
    assert summary['groups']['clean']['client_ready_under_25_minutes'] == 0
    rows[0]['independent_audit_passed'] = False
    assert campaign.summarize_readiness(manifest, rows)['planned_groups']['clean']['rate'] < 1
    host['candidate_identity'] = {'git_commit': 'different'}
    with pytest.raises(ValueError, match='exact installed candidate'):
        campaign.validate_tui_host_checks(host, identity, manifest)


def test_local_collector_rechecks_published_bytes_and_quality(tmp_path):
    output = tmp_path / 'output'
    output.mkdir()
    path = output / 'protocol.docx'
    path.write_bytes(b'1234')
    manifest = {'status': 'passed', 'quality': {'status': 'passed'}, 'client_outputs': [
        {'path': 'output/protocol.docx', 'bytes': 4, 'sha256': hashlib.sha256(b'1234').hexdigest()}]}
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    result = {'status': 'passed', 'manifest': 'manifest.json', 'client_outputs': ['output/protocol.docx'],
        'delivery': {'status': 'locally_available', 'confirmed': False, 'bytes_verified': True, 'recipient_delivery_verified': False}}
    assert campaign.verified_local_outputs(tmp_path, result, ['protocol.docx'])
    path.write_bytes(b'wrong')
    with pytest.raises(ValueError, match='bytes changed'):
        campaign.verified_local_outputs(tmp_path, result, ['protocol.docx'])
    campaign.verify_local_receipt({'delivery_status': 'review_only_locally_available', 'confirmed': False,
        'bytes_verified': True, 'recipient_delivery_verified': False})
    result['delivery']['confirmed'] = True
    with pytest.raises(ValueError, match='without recipient confirmation'):
        campaign.verify_local_receipt(result['delivery'])


def test_tui_faults_use_local_read_retry_and_real_launch_failure(tmp_path):
    manifest = campaign.readiness_plan({}, 'hermes-tui')
    f2 = next(p for p in manifest['supplemental_operations'] if p['case_id'] == 'F2')
    output = tmp_path / 'probe.docx'
    output.write_bytes(b'1234')
    with campaign_adapter(workflow, f2, tmp_path, workflow.local_output_reader(tmp_path)) as (reader, events):
        assert reader.local_outputs_only
        with pytest.raises(OSError):
            reader(str(output))
        assert reader(str(output)) == b'1234'
        assert workflow._production_sandbox_prefix(Path('/missing'), host_mode='hermes-tui') == []
    with campaign_adapter(workflow, f2, tmp_path, workflow.local_output_reader(tmp_path)) as (reader, events):
        assert reader(str(output)) == b'1234'  # Resume does not inject it twice.
    f3 = next(p for p in manifest['supplemental_operations'] if p['case_id'] == 'F3')
    with campaign_adapter(workflow, f3, tmp_path, workflow.local_output_reader(tmp_path)):
        with pytest.raises(RuntimeError, match='repair-worker launch fault'):
            workflow._production_dispatch_handoffs([{'task': 'document_repair'}], 10, tmp_path, {}, host_mode='hermes-tui')
    assert 'repair_author_unavailable' in (tmp_path / 'campaign-fault-evidence/events.json').read_text()


@pytest.mark.parametrize('contaminate', [False, True])
def test_host_check_exercises_real_tool_process_native_edit_and_cleanup(tmp_path, monkeypatch, contaminate):
    root = tmp_path / 'profile/skills/clinical-document-generation'
    root.mkdir(parents=True)
    (root / workflow.RELEASE_MANIFEST).write_text('{}')
    hermes = tmp_path / 'hermes'
    tools = hermes / 'tools'
    tools.mkdir(parents=True)
    (tools / '__init__.py').write_text('')
    (tools / 'file_tools.py').write_text('from pathlib import Path\ndef read_file_tool(path,offset=1,limit=100):\n return "".join(Path(path).read_text().splitlines(True)[offset-1:offset-1+limit])\ndef write_file_tool(path,value):\n Path(path).write_text(value)\n')
    launcher = hermes / '.venv/bin/hermes'
    monkeypatch.setattr('hermes_tui_host_checks.platform.system', lambda: 'Linux')
    monkeypatch.setattr(workflow, '_managed_hermes_pair', lambda: (launcher, Path(sys.executable)))
    monkeypatch.setattr(workflow, '_installed_release_identity', lambda root: {'git_commit': 'candidate'})
    monkeypatch.setattr(workflow, '_production_worker_readiness', lambda *a, **k: {'status': 'passed'})
    identity = {'runtime': 'original'}
    monkeypatch.setattr(workflow, '_worker_capability_identity', lambda root: dict(identity))
    monkeypatch.setattr(workflow, 'resolve_python_runtime', lambda **k: {'executable': sys.executable})
    rendered = []
    def render(root, revision, reference, **kwargs):
        from docx import Document
        text = Document(revision / 'candidate/probe.docx').paragraphs[0].text
        rendered.append(text)
        (revision / 'page.png').write_bytes(b'\x89PNG\r\n\x1a\n')
        if contaminate and text == 'After native repair':
            identity['runtime'] = 'cache-written'
        return {'status': 'passed'}
    monkeypatch.setattr(workflow, 'render_assurance', render)
    evidence = tmp_path / 'checks'
    report = collect(workflow, root, evidence)
    assert rendered == ['Before native repair', 'After native repair']
    assert report['status'] == ('blocked' if contaminate else 'passed')
    assert report['checks']['worker_descendant_cleanup']['status'] == 'passed'
    assert report['recipient_delivery_verified'] is False
    assert report['paid_model_calls'] == 0
    assert (evidence / 'candidate-identity.json').exists() is not contaminate
    assert json.loads((evidence / 'host-checks.json').read_text()) == report
    if contaminate:
        assert 'runtime changed' in report['issue']
    with pytest.raises(FileExistsError):
        collect(workflow, root, evidence)


def test_worker_launch_gap_returns_complete_review_only_without_spinning(tmp_path, monkeypatch):
    from test_review_output import _candidate_run
    run, _candidate = _candidate_run(tmp_path, monkeypatch, 'Retrospective')
    monkeypatch.setattr(workflow, 'generate', lambda *a, **k: {'status': 'awaiting_hermes',
        'stage': 'native_repair', 'revision_id': 'r-approved', 'handoffs': [{'task': 'document_repair'}]})
    calls = []
    def launch(*args):
        calls.append(args)
        raise workflow.WorkerLaunchUnavailableError('Required executable missing')
    result = workflow.run_desktop_operation(run, handoff_runner=launch,
        opener=workflow.local_output_reader(run), require_promoted_runtime=False)
    assert len(calls) == 1
    assert result['status'] == 'review_required'
    assert result['stage'] == 'review_tooling'
    assert result['review_delivery']['bytes_verified'] is True
    assert result['review_delivery']['confirmed'] is False
    assert 'Required executable missing' in (run / result['review_findings']).read_text()


def test_candidate_loader_in_fresh_process_rejects_checkout_dependency_cache(tmp_path):
    import shutil
    import subprocess
    root = tmp_path / 'installed'
    shutil.copytree(Path(workflow.__file__).parent, root / 'scripts')
    tests = Path(__file__).parent
    script = "import sys,json;from pathlib import Path;sys.path.insert(0,sys.argv[1]);from tui_campaign_contract import load_installed_workflow;w=load_installed_workflow(Path(sys.argv[2]));print(json.dumps({n:sys.modules[Path(n).stem].__file__ for n in w.PRODUCTION_MODULES}))"
    result = subprocess.run([sys.executable, '-B', '-c', script, str(tests), str(root)],
        text=True, capture_output=True, check=True)
    assert all(Path(p).is_relative_to(root) for p in json.loads(result.stdout).values())
    contaminated = "import sys;sys.path.insert(0,sys.argv[3]);import contracts;" + script
    result = subprocess.run([sys.executable, '-B', '-c', contaminated, str(tests), str(root),
        str(Path(workflow.__file__).parent)], text=True, capture_output=True)
    assert result.returncode != 0
    assert 'different installed candidate module: contracts.py' in result.stderr


def test_frozen_host_check_files_cannot_disappear_after_pass(tmp_path):
    identity = {'git_commit': 'candidate'}
    host = host_report(identity)
    evidence = tmp_path / 'render.json'
    evidence.write_bytes(b'actual retained evidence')
    host['evidence_inventory'] = {'render.json': {'bytes': evidence.stat().st_size,
        'sha256': hashlib.sha256(evidence.read_bytes()).hexdigest()}}
    manifest = campaign.readiness_plan(identity, 'hermes-tui', host)
    campaign.validate_tui_host_checks(host, identity, manifest, tmp_path)
    evidence.unlink()
    with pytest.raises(ValueError, match='evidence changed'):
        campaign.validate_tui_host_checks(host, identity, manifest, tmp_path)


def test_campaign_refuses_missing_visual_callback_before_any_paid_case(tmp_path, monkeypatch, capsys):
    import run_tui_acceptance as runner
    monkeypatch.setattr(sys, 'argv', ['runner', '--manifest', str(tmp_path / 'missing.json'),
        '--host-checks', str(tmp_path / 'missing-host.json'), '--release-root', str(tmp_path / 'skill'),
        '--runs-root', str(tmp_path / 'runs'), '--parent-visual-review-command', str(tmp_path / 'missing-callback'),
        '--approved-by', 'owner', '--phase', 'pilot', '--authorize-paid-campaign'])
    with pytest.raises(SystemExit) as error:
        runner.main()
    assert error.value.code == 2
    assert 'parent_visual_callback_unavailable' in capsys.readouterr().err
    assert not (tmp_path / 'runs').exists()


def test_remaining_campaign_stops_spending_after_first_unexpected_outcome(tmp_path, monkeypatch):
    import subprocess
    import run_tui_acceptance as runner
    identity = {'git_commit': 'controlled'}
    host = host_report(identity)
    evidence = tmp_path / 'retained.txt'
    evidence.write_bytes(b'retained')
    host['evidence_inventory'] = {'retained.txt': {'bytes': 8, 'sha256': hashlib.sha256(b'retained').hexdigest()}}
    manifest = campaign.readiness_plan(identity, 'hermes-tui', host)
    (tmp_path / 'host.json').write_text(json.dumps(host))
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    callback = tmp_path / 'real-callback'
    callback.write_text('#!/bin/sh\nexit 1\n')
    callback.chmod(0o700)
    collector = {'operation_records': [{'planned_operation_id': p, 'status': 'passed',
        'local_bytes_verified': True, 'independent_audit_passed': True} for p in manifest['pilot_operation_ids']],
        'evidence_errors': [], 'unmatched_operation_states': [], 'tui_local_acceptance': 'incomplete'}
    monkeypatch.setattr(runner, 'collect_readiness_runs', lambda *a: collector)
    calls = []
    def launch(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1)
    monkeypatch.setattr(runner.subprocess, 'run', launch)
    monkeypatch.setattr(sys, 'argv', ['runner', '--manifest', str(tmp_path / 'manifest.json'),
        '--host-checks', str(tmp_path / 'host.json'), '--release-root', str(tmp_path / 'skill'),
        '--runs-root', str(tmp_path / 'runs'), '--parent-visual-review-command', str(callback),
        '--approved-by', 'owner', '--phase', 'remaining', '--authorize-paid-campaign'])
    assert runner.main() == 1
    assert len(calls) == 1
    assert '--resume' not in calls[0]
    assert (tmp_path / 'runs/phase-remaining-report.json').is_file()
