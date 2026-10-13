#!/usr/bin/env python3
"""Developer release check using local fixtures; never a client activation gate."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Explicit selection prevents accidental execution of live certification/corpora.
TEST_FILES = (
    'test_ai_quality_boundary.py', 'test_ai_review_handoff.py',
    'test_general_document_repair.py', 'test_ai_delivery_outcomes.py',
    'test_reviewer_transport.py', 'test_worker_readiness.py', 'test_hermes_tui.py',
    'test_offline_reliability_gate.py', 'test_ai_quality_campaign.py',
    'test_content_review_recovery.py', 'test_review_scheduler.py', 'test_readiness_recovery.py', 'test_worker_boundary.py', 'test_readiness_campaign.py',
)







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
    args = parser.parse_args()
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
    code = 1
    if not findings:
        try:
            with tempfile.TemporaryDirectory(prefix='clinical-offline-office-') as directory:
                environment, office = test_environment(Path(directory))
                result['renderer_path_for_pytest'] = office
                completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=args.timeout, env=environment)
            code = completed.returncode
            result.update(stdout=completed.stdout, stderr=completed.stderr)
        except subprocess.TimeoutExpired as exc:
            result['error'] = f'Local developer check exceeded {args.timeout:g} seconds'
            # TimeoutExpired may contain bytes even when text=True.
            result['stdout'] = exc.stdout.decode(errors='replace') if isinstance(exc.stdout, bytes) else exc.stdout or ''
    result.update(status='passed' if code == 0 else 'failed', elapsed_seconds=time.monotonic()-started)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
