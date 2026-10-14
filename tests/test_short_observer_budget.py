"""Real supervisor startup under the synthetic delegated-timeout budget."""
import json, os, sys, subprocess
from pathlib import Path
from owned_observer_runtime import run_owned_observer


def test_short_budget_establishes_cleanup_before_interrupting_worker(tmp_path):
    state = tmp_path / 'observer'
    state.mkdir()
    result = run_owned_observer(
        [sys.executable, '-B', '-c', 'import time; time.sleep(30)'],
        cwd=tmp_path, env=dict(os.environ), state=state, budget=0.3,
        write_launch=lambda row: (state / 'launch.json').write_text(json.dumps(row)),
    )
    assert isinstance(result['failure'], subprocess.TimeoutExpired)
    assert result['cleanup']['descendants_reaped'] is True
    assert result['cleanup']['errors'] == []
    assert not Path('/proc', str(result['cleanup']['owner_pid'])).exists()
