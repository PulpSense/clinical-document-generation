"""Unpaid real subprocess deadline controls; no clinical evidence."""
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
import pytest
import run_tui_acceptance as runner


def test_owner_case_stops_at_mission_ceiling_and_preserves_cleanup(tmp_path):
    deadline = (datetime.now(timezone.utc) + timedelta(seconds=9)).isoformat()
    started = time.monotonic()
    result = runner.run_owner_case([sys.executable, '-c', 'import time; print("partial", flush=True); time.sleep(60)'],
        deadline_utc=deadline, state=tmp_path / 'launcher', cwd=tmp_path, env=dict(os.environ))
    assert result['returncode'] != 0
    assert time.monotonic() - started < 10
    assert result['cleanup']['descendants_reaped'] is True
    assert 'partial' in (tmp_path / 'launcher/stdout.log').read_text()
    assert json.loads((tmp_path / 'launcher/outcome.json').read_text())['deadline_utc'] == deadline


def test_expired_owner_case_never_launches(tmp_path):
    with pytest.raises(ValueError, match='deadline'):
        runner.run_owner_case([sys.executable, '-c', 'raise SystemExit(0)'],
            deadline_utc='2000-01-01T00:00:00+00:00', state=tmp_path / 'launcher', cwd=tmp_path, env=dict(os.environ))
    assert not (tmp_path / 'launcher').exists()
