#!/usr/bin/env python3
"""Developer release check using local fixtures; never a client activation gate."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import signal
import threading
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Explicit selection prevents accidental execution of live certification/corpora.
TEST_FILES = (
    'test_ai_quality_boundary.py', 'test_ai_review_handoff.py',
    'test_general_document_repair.py', 'test_ai_delivery_outcomes.py',
    'test_reviewer_transport.py', 'test_worker_readiness.py', 'test_hermes_tui.py', 'test_tui_acceptance.py',
    'test_offline_reliability_gate.py', 'test_ai_quality_campaign.py',
    'test_observer_clean_partial.py', 'test_production_visual_transport.py',
    'test_visual_transport_retention.py', 'test_production_visual_metadata.py',
    'test_production_visual_incomplete.py',
    'test_document_review_ownership.py', 'test_visual_evidence_followup.py',
    'test_observer_review_recovery.py', 'test_shared_review_to_repair.py',
    'test_parent_review_recovery_report.py', 'test_parent_partial_integrity.py',
    'test_review_outer_framing.py', 'test_observer_concern_channels.py',
    'test_visual_retry_feedback.py', 'test_attested_channel_integrity.py',
    'test_review_repair_priority.py', 'test_bounded_diagnostic_export.py',
    'test_repair_with_incomplete_visual.py', 'test_repair_visual_stop_conditions.py',
    'test_content_review_recovery.py', 'test_review_scheduler.py', 'test_readiness_recovery.py', 'test_worker_boundary.py', 'test_readiness_campaign.py',
)







def shard_ids(nodeids: list[str], index: int, count: int) -> list[str]:
    """Partition actual collected cases, not files or parameterization functions."""
    if count < 1 or not 0 <= index < count or len(set(nodeids)) != len(nodeids):
        raise ValueError('Invalid shard coordinates or duplicate collected node IDs')
    return sorted(nodeids)[index::count]


def verify_coverage(directory: Path, count: int) -> int:
    """Fail closed on absent shards, collection drift, overlap or unfinished cases."""
    manifests = [json.loads(path.read_text(encoding='utf-8'))
                 for path in sorted(directory.rglob('*.cases.json'))]
    if count < 1 or len(manifests) != count:
        raise ValueError(f'Expected {count} shard manifests, found {len(manifests)}')
    if sorted(m['index'] for m in manifests) != list(range(count)):
        raise ValueError('Missing or duplicate shard indices')
    expected = manifests[0]['all']
    if not expected:
        raise ValueError('Empty collection is not coverage')
    union = []
    for manifest in manifests:
        selected = shard_ids(expected, manifest['index'], count)
        if (manifest['count'] != count or manifest['all'] != expected
                or manifest['selected'] != selected
                or sorted(manifest['completed']) != selected):
            raise ValueError(f"Collection/selection/completion mismatch in shard {manifest['index']}")
        union.extend(manifest['selected'])
    if sorted(union) != sorted(expected):
        raise ValueError('Shards must cover every collected case exactly once')
    return len(expected)


def test_command(python: str = sys.executable) -> list[str]:
    return [python, '-m', 'pytest', *[f'tests/{name}' for name in TEST_FILES], '-q']


def test_environment(office_alias_dir: Path) -> tuple[dict[str, str], str | None]:
    """Pass the office installation discoverable by an installation smoke to pytest.

    Hermes background workers need not source terminal shell init files, so their
    inherited PATH may omit the profile's already-installed LibreOffice.
    Resolve it through the same renderer discovery as the installation smoke.
    """
    scripts = str(ROOT / 'scripts')
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from quality import renderer

    environment = os.environ.copy()
    home = environment.get('HERMES_HOME')
    skill_root = Path(home) / 'skills/clinical-document-generation' if home else ROOT
    selected = renderer(environment=environment, skill_root=skill_root)
    if selected and selected['kind'] == 'LibreOffice':
        office = Path(selected['path'])
        # Tests look up either name; bind both to the smoke-selected executable,
        # even when another launcher is installed alongside it.
        if os.name == 'nt':
            directory = office.parent
        else:
            for name in ('libreoffice', 'soffice'):
                (office_alias_dir / name).symlink_to(office)
            directory = office_alias_dir
        environment['PATH'] = str(directory) + os.pathsep + environment.get('PATH', '')
        return environment, str(office)
    return environment, None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list', action='store_true', help='Show selected local tests without executing them')
    parser.add_argument('--report', type=Path, help='Retain the command, elapsed time and test output')
    parser.add_argument('--timeout', type=float, default=300, help='Developer check budget; unrelated to generation deadline')
    parser.add_argument('--shard-index', type=int, default=0)
    parser.add_argument('--shard-count', type=int, default=1)
    parser.add_argument('--verify-shards', type=Path, help='Verify downloaded shard manifests without running tests')
    args = parser.parse_args()
    if args.verify_shards:
        try:
            total = verify_coverage(args.verify_shards, args.shard_count)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            print(f'Shard coverage FAILED: {exc}', file=sys.stderr)
            return 1
        print(f'Shard coverage passed: {total} collected cases executed exactly once across {args.shard_count} shards')
        return 0
    if args.shard_count < 1 or not 0 <= args.shard_index < args.shard_count:
        parser.error('Require 0 <= shard-index < shard-count')
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
    command = test_command()
    if args.list:
        print(json.dumps({'command': command, 'paid_model_calls': 0, 'client_activation_gate': False}, indent=2))
        return 0
    started = time.monotonic()
    findings = []
    result = {'scope': 'offline_focused_reliability', 'command': command, 'audit_findings': findings,
              'paid_model_calls': 0, 'client_activation_gate': False}
    from offline_gate_reporting import atomic_text, write_junit

    report = (args.report or Path('offline-focused-report.json')).resolve()
    report.parent.mkdir(parents=True, exist_ok=True)
    result.update(status='running', timed_out=False, shard_index=args.shard_index,
                  shard_count=args.shard_count, log=str(report.with_suffix('.log')))
    atomic_text(report, json.dumps(result, indent=2) + '\n')
    write_junit(report.with_suffix('.xml'), {})
    code = 1
    try:
        with tempfile.TemporaryDirectory(prefix='clinical-offline-office-') as directory:
            environment, office = test_environment(Path(directory))
            result['renderer_path_for_pytest'] = office
            environment['PYTHONPATH'] = str(Path(__file__).resolve().parent) + os.pathsep + environment.get('PYTHONPATH', '')
            environment['PYTHONUNBUFFERED'] = '1'
            environment['OFFLINE_GATE_EVIDENCE'] = json.dumps(
                {'path': str(report), 'index': args.shard_index, 'count': args.shard_count})
            command.extend(['-p', 'offline_gate_reporting', '-vv', '--tb=short'])
            with report.with_suffix('.log').open('w', encoding='utf-8') as log:
                child = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, text=True, errors='replace',
                                         env=environment, start_new_session=os.name != 'nt')
                stop_reader = threading.Event()
                def stream():
                    for line in child.stdout:
                        if stop_reader.is_set():
                            break
                        log.write(line)
                        log.flush()
                        print(line, end='', flush=True)
                reader = threading.Thread(target=stream, daemon=True)
                reader.start()
                try:
                    code = child.wait(timeout=args.timeout)
                except subprocess.TimeoutExpired:
                    result.update(timed_out=True, error=f'Local developer check exceeded {args.timeout:g} seconds')
                finally:
                    # Also reap descendants that outlive a normally exiting pytest.
                    if os.name != 'nt':
                        try:
                            os.killpg(child.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    elif child.poll() is None:
                        child.kill()
                    child.wait()
                    # A detached descendant may inherit stdout beyond pytest's
                    # lifetime. Never let that pipe suppress timeout evidence.
                    reader.join(timeout=1)
                    if reader.is_alive():
                        stop_reader.set()
                        result['output_drain_incomplete'] = True
                if result['timed_out']:
                    import xml.etree.ElementTree as ET
                    path = report.with_suffix('.xml')
                    suite = ET.parse(path).getroot()
                    case = ET.SubElement(suite, 'testcase', name='offline-gate-timeout')
                    ET.SubElement(case, 'error', type='timeout', message=result['error'])
                    suite.set('tests', str(len(suite)))
                    suite.set('errors', str(len(suite.findall('.//error'))))
                    atomic_text(path, ET.tostring(suite, encoding='unicode') + '\n')
    except Exception as exc:
        result['error'] = f'{type(exc).__name__}: {exc}'
    result.update(status='passed' if code == 0 and not result.get('error') else 'failed',
                  elapsed_seconds=time.monotonic()-started)
    atomic_text(report, json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
