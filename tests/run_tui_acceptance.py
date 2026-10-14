#!/usr/bin/env python3
"""Run a frozen TUI pilot or remaining cases; retain first failures, never retry them."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from ai_quality_campaign import collect_readiness_runs, validate_readiness_manifest, validate_tui_host_checks


def select_phase_operations(manifest, phase):
    """Return only frozen IDs; owner five-case scope cannot expand to other cases."""
    validate_readiness_manifest(manifest)
    if phase not in {'pilot', 'remaining'}:
        raise ValueError('Unknown TUI campaign phase')
    if manifest.get('execution_scope') == 'owner-five-pilot-only' and phase != 'pilot':
        raise ValueError('owner-five-pilot-only: other fixed cases are not authorized')
    pilot = manifest['pilot_operation_ids']
    planned = manifest['baseline_operations'] + manifest['supplemental_operations']
    if phase == 'pilot':
        by_id = {p['planned_operation_id']: p for p in planned}
        return [by_id[key] for key in pilot]
    return [p for p in planned if p['planned_operation_id'] not in set(pilot)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--host-checks', type=Path, required=True)
    parser.add_argument('--release-root', type=Path, required=True)
    parser.add_argument('--runs-root', type=Path, required=True)
    parser.add_argument('--parent-visual-review-command', type=Path, required=True)
    parser.add_argument('--callback-probe', type=Path)
    parser.add_argument('--approved-by', required=True)
    parser.add_argument('--phase', choices=['pilot', 'remaining'], required=True)
    parser.add_argument('--authorize-paid-campaign', action='store_true')
    args = parser.parse_args()
    if not args.authorize_paid_campaign:
        parser.error('Explicit owner authorization for paid synthetic operations is required')
    callback = args.parent_visual_review_command
    if not callback.is_file() or not os.access(callback, os.X_OK):
        parser.error('parent_visual_callback_unavailable: select a genuine executable image-review callback before paid cases')
    manifest = json.loads(args.manifest.read_text())
    host = json.loads(args.host_checks.read_text())
    validate_readiness_manifest(manifest)
    validate_tui_host_checks(host, manifest['candidate_identity'], manifest, args.host_checks.parent)
    if manifest.get('host_mode') != 'hermes-tui':
        parser.error('This runner only accepts an explicit TUI manifest')
    try:
        selected = select_phase_operations(manifest, args.phase)
    except ValueError as exc:
        parser.error(str(exc))
    sys.path.insert(0, str(args.release_root / 'scripts'))
    from visual_review import validate_callback_probe
    try:
        if args.callback_probe is None:
            raise ValueError('callback_image_capability_unproven: --callback-probe is required before paid cases')
        validate_callback_probe(callback, args.callback_probe, manifest['candidate_identity'])
    except ValueError as exc:
        parser.error(str(exc))
    runs = args.runs_root.absolute()
    if runs.resolve().is_relative_to(args.release_root.resolve()):
        parser.error('Campaign runs must remain outside installed code')
    runs.mkdir(parents=True, exist_ok=True)
    pilot = set(manifest['pilot_operation_ids'])
    if args.phase == 'remaining':
        collected = collect_readiness_runs(manifest, runs, host)
        first = {row['planned_operation_id']: row for row in collected['operation_records'] if not row.get('retry_of')}
        if (collected['evidence_errors'] or collected['unmatched_operation_states']
                or not all(first.get(key, {}).get('status') == 'passed'
                    and first[key].get('local_bytes_verified') is True
                    and first[key].get('independent_audit_passed') is True for key in pilot)):
            parser.error('Audit all three passing pilot outputs independently before running remaining cases')
    failures = []
    for planned in selected:
        run = runs / planned['planned_operation_id']
        # A resume is exclusively the predeclared F1 parent interruption. Failed
        # terminal cases are never replaced by a later lucky attempt.
        interrupted = run / 'campaign-interruption.json'
        if run.exists() and (planned['case_id'] != 'F1' or not interrupted.is_file()
                             or (run / 'campaign-result.json').exists()):
            parser.error(f'Retained operation already exists: {run}. Collect it; do not rerun this phase.')
        command = [sys.executable, '-B', str(Path(__file__).with_name('run_readiness_case.py')),
            '--manifest', str(args.manifest.absolute()), '--host-checks', str(args.host_checks.absolute()),
            '--host-mode', 'hermes-tui', '--planned-operation-id', planned['planned_operation_id'],
            '--release-root', str(args.release_root.absolute()), '--run-dir', str(run),
            '--parent-visual-review-command', str(args.parent_visual_review_command.absolute()),
            '--approved-by', args.approved_by, '--authorize-paid-operation']
        resume = run.exists()
        log = runs / (planned['planned_operation_id'] + '.launcher.log')
        with log.open('a' if resume else 'x') as output:
            completed = subprocess.run(command + (['--resume'] if resume else []), stdout=output, stderr=subprocess.STDOUT)
            if not resume and planned['case_id'] == 'F1' and interrupted.is_file() and not (run / 'campaign-result.json').exists():
                completed = subprocess.run(command + ['--resume'], stdout=output, stderr=subprocess.STDOUT)
        if completed.returncode:
            failures.append(planned['planned_operation_id'])
            break
    report = collect_readiness_runs(manifest, runs, host)
    if manifest.get('execution_scope') == 'owner-five-pilot-only':
        report['execution_scope'] = manifest['execution_scope']
        report['owner_pilot_operation_ids'] = list(manifest['pilot_operation_ids'])
        report['other_fixed_cases_excluded_by_owner_direction'] = [p['planned_operation_id']
            for p in manifest['baseline_operations'] + manifest['supplemental_operations']
            if p['planned_operation_id'] not in pilot]
    (runs / ('phase-' + args.phase + '-report.json')).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'phase': args.phase, 'unexpected_outcomes': failures,
        'tui_local_acceptance': report['tui_local_acceptance'],
        'next_step': 'Independently audit retained native files and every final page; then collect. No automatic study run.'}, indent=2))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
