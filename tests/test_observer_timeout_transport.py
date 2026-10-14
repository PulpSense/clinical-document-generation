"""Real owned timeout must reach fallback as timeout, never generic integrity loss."""
import json
import sys
import subprocess
from pathlib import Path
import pytest
import workflow
import tui_visual_callback as callback
from visual_review import create_visual_review_unit
from test_visual_units import parent_fixture


@pytest.mark.parametrize('cleanup_change', [None, 'missing', 'content', 'hash-only'])
def test_reaped_observer_timeout_preserves_type_for_fallback(tmp_path, monkeypatch, cleanup_change):
    revision, parent_path, parent = parent_fixture(tmp_path, 'retrospective')
    path = create_visual_review_unit(revision, parent_path,
        parent['visual_review_plan']['targets'][:1], 1, observer_evidence_required=True)
    profile = tmp_path / 'profile'
    profile.mkdir()
    (profile / 'config.yaml').write_text('controlled local timeout fixture')
    launcher = tmp_path / 'sleeping-launcher.py'
    launcher.write_text('import time\ntime.sleep(30)\n')
    monkeypatch.setattr(workflow, '_managed_hermes_pair', lambda: (launcher, Path(sys.executable)))
    monkeypatch.setattr(workflow, '_managed_hermes_identity', lambda: {'controlled_timeout_fixture': True})
    from owned_observer_runtime import OwnedObserverLifetimeUnresolved
    original_result = callback.visual_review_unit_result
    def tamper_after_result(*args, **kwargs):
        result = original_result(*args, **kwargs)
        if cleanup_change:
            state = next((revision / 'hermes/visual-review-observers').iterdir())
            proof = state / 'owned-descendant-cleanup.json'
            if cleanup_change == 'missing':
                proof.unlink()
            elif cleanup_change == 'content':
                content = json.loads(proof.read_text())
                content['descendants_reaped'] = False
                proof.write_text(json.dumps(content))
            else:
                proof.write_text(proof.read_text() + ' ')
        return result
    monkeypatch.setattr(callback, 'visual_review_unit_result', tamper_after_result)
    expected = OwnedObserverLifetimeUnresolved if cleanup_change else subprocess.TimeoutExpired
    with pytest.raises(expected):
        callback.observe_unit(revision, {'request_path': path.relative_to(revision).as_posix()},
            0.3, {'profile_path': str(profile), 'configuration': {'source': 'fixture', 'max_turns': 1}})
    state = next((revision / 'hermes/visual-review-observers').iterdir())
    diagnostic = json.loads((state / 'diagnostic.json').read_text())
    assert diagnostic['error_type'] == 'TimeoutExpired'
    assert not (revision / json.loads(path.read_text())['response_path']).exists()
    if cleanup_change:
        return
    cleanup = json.loads((state / 'owned-descendant-cleanup.json').read_text())
    assert diagnostic['descendants_reaped'] is True
    assert cleanup['descendants_reaped'] is True and cleanup['errors'] == []
    assert not Path('/proc', str(cleanup['owner_pid'])).exists()
    assert not (revision / json.loads(path.read_text())['response_path']).exists()
