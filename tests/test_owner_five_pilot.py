"""Explicit owner five-family pilot never authorizes the other fixed cases."""
import hashlib
import json
import subprocess
import sys

import pytest
import ai_quality_campaign as campaign
import run_tui_acceptance as runner
from test_tui_acceptance import host_report

FIVE = ['retrospective-sparse-complete.r1', 'prospective-advarra-sparse-complete.r1',
        'prospective-sterling-sparse-complete.r1', 'ambispective-sterling-sparse-complete.r1',
        'ambispective-advarra-sparse-complete.r1']


def test_owner_five_pilot_freezes_existing_ids_without_weakening_full_criteria():
    default = campaign.readiness_plan({'git_commit': 'synthetic-unit-test'}, 'hermes-tui')
    owner = campaign.readiness_plan({'git_commit': 'synthetic-unit-test'}, 'hermes-tui', pilot_scope='owner-five-only')
    campaign.validate_readiness_manifest(owner)
    assert default['pilot_operation_ids'] == FIVE[:3]
    assert 'execution_scope' not in default
    assert owner['pilot_operation_ids'] == FIVE
    selected = runner.select_phase_operations(owner, 'pilot')
    assert [p['planned_operation_id'] for p in selected] == FIVE
    cases = {c['case_id']: c for c in owner['cases']}
    assert {cases[p['case_id']]['family'] for p in selected} == {'Retrospective/none', 'Prospective/Advarra', 'Prospective/Sterling', 'Ambispective/Advarra', 'Ambispective/Sterling'}
    assert len(owner['baseline_operations'] + owner['supplemental_operations']) == 28
    for key in ('baseline_denominator','supplemental_denominator','clean_denominator','repair_denominator',
                'deadline_seconds','target_seconds_exclusive','minimum_under_target_per_cohort'):
        assert owner[key] == default[key]
    assert campaign.summarize_readiness(owner, [])['planned_groups'] == campaign.summarize_readiness(default, [])['planned_groups']
    with pytest.raises(ValueError, match='owner-five'):
        runner.select_phase_operations(owner, 'remaining')
    # Rehashing a tampered outer manifest must not change the authorized IDs.
    owner['pilot_operation_ids'][-1] = 'prospective-advarra-rich-complete.r1'
    unsigned = {k: v for k, v in owner.items() if k != 'manifest_sha256'}
    owner['manifest_sha256'] = hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    with pytest.raises(ValueError, match='owner-five'):
        campaign.validate_readiness_manifest(owner)


@pytest.mark.parametrize('phase,expected_calls', [('pilot', 1), ('remaining', 0)])
def test_owner_scope_launches_exactly_five_or_refuses_before_spending(tmp_path, monkeypatch, phase, expected_calls):
    identity = {'git_commit': 'synthetic-unit-test'}
    host = host_report(identity)
    retained = tmp_path / 'retained.txt'
    retained.write_bytes(b'synthetic host fixture')
    host['evidence_inventory'] = {'retained.txt': {'bytes': retained.stat().st_size,
        'sha256': hashlib.sha256(retained.read_bytes()).hexdigest()}}
    manifest = campaign.readiness_plan(identity, 'hermes-tui', host, pilot_scope='owner-five-only')
    (tmp_path / 'host.json').write_text(json.dumps(host))
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    callback = tmp_path / 'synthetic-NOT-real-callback'
    callback.write_text('#!/bin/sh\nexit 1\n')
    callback.chmod(0o700)
    import visual_review
    probes = []
    monkeypatch.setattr(visual_review, 'validate_callback_probe', lambda *a: probes.append(a))
    monkeypatch.setattr(runner, 'collect_readiness_runs', lambda *a: {'operation_records': [],
        'evidence_errors': [], 'unmatched_operation_states': [], 'tui_local_acceptance': 'incomplete'})
    calls = []
    forecast = {'schema_version': 'sequential-storage-forecast/v1', 'candidate_identity': identity,
        'cases': [dict(case_id=key, retained_bytes=20, worker_peak_bytes=50, scratch_peak_bytes=10) for key in FIVE],
        'margin_bytes': 15, 'evidence_inventory': [{'path': str(retained),
            'sha256': hashlib.sha256(retained.read_bytes()).hexdigest()}]}
    (tmp_path / 'forecast.json').write_text(json.dumps(forecast))
    # This test isolates selection/spending. Real storage validation has separate
    # positive and negative public-seam tests with actual allocated inventories.
    monkeypatch.setattr(runner, 'admit_storage', lambda *a: {'admitted': True, 'fixture_only': True})
    monkeypatch.setattr(runner.subprocess, 'run', lambda command, **kwargs: calls.append(command) or subprocess.CompletedProcess(command, 0))
    ledger = tmp_path / 'attempts.json'
    ledger.write_text(json.dumps({'deadline_utc':'2026-10-14T09:12:25.124854+00:00',
        'limits':{'study_operations':10,'capability_probes':3},'study_operations':[], 'capability_probes':[], 'counters':{}}))
    monkeypatch.setattr(sys, 'argv', ['runner', '--manifest', str(tmp_path / 'manifest.json'),
        '--host-checks', str(tmp_path / 'host.json'), '--release-root', str(tmp_path / 'skill'),
        '--runs-root', str(tmp_path / 'runs'), '--parent-visual-review-command', str(callback),
        '--callback-probe', str(tmp_path / 'synthetic-proof.json'), '--approved-by', 'synthetic-test',
        '--storage-forecast', str(tmp_path / 'forecast.json'), '--attempt-ledger', str(ledger),
        '--phase', phase, '--authorize-paid-campaign'])
    if phase == 'remaining':
        with pytest.raises(SystemExit) as error:
            runner.main()
        assert error.value.code == 2
        assert probes == []
        assert not (tmp_path / 'runs').exists()
    else:
        assert runner.main() == 0
        assert len(probes) == 1
    assert len(calls) == expected_calls
    if calls:
        assert [c[c.index('--planned-operation-id') + 1] for c in calls] == FIVE[:1]
        assert all('--resume' not in c for c in calls)
