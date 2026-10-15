"""Public production-adapter transport recovery; controlled unpaid subprocesses only."""
import json

import pytest
from test_production_visual_incomplete import test_production_missing_visual_scope_reaches_only_safe_fallback as exercise


@pytest.mark.parametrize('parallel', [False, True])
@pytest.mark.parametrize('channel', ['disk', 'stdout'])
@pytest.mark.parametrize('transport', ['truncated', 'encoding', 'nonobject'])
def test_malformed_final_preserves_independent_checkpoint(tmp_path, monkeypatch, parallel, channel, transport):
    exercise(tmp_path, monkeypatch, parallel, transport + '_' + channel)
    observation = json.loads((tmp_path / 'observation.json').read_text())
    assert observation['callback_count'] == 1
    assert observation['retained_assessments'] == 1
    assert observation['missing_at_callback'] > 0
    assert observation['callback_budget'] > 0
    result = observation['result']
    assert result['deadline_at_epoch'] - result['started_at_epoch'] == result['operation_deadline_seconds'] == 2700
    assert result['elapsed_seconds'] < result['operation_deadline_seconds']
    assert observation['returncodes'] and set(observation['returncodes']) == {0}
    expected = (b'{"schema_version":' if transport == 'truncated' else
                b'\xff\xfe' if transport == 'encoding' else b'[1, null, "not a response"]')
    revision = tmp_path / 'run/revisions/r1'
    assert any(p.read_bytes() == expected for p in (revision / 'hermes/visual-final-transport').glob('*.bin'))
    if channel == 'disk':
        assert any(p.read_bytes() == expected for p in (revision / 'hermes/visual-review-responses').glob('*.json')) or any(
            (revision / json.loads(p.read_text())['response_path']).read_bytes() == expected
            for p in (revision / 'hermes/visual-review-requests').glob('*.json')
            if (revision / json.loads(p.read_text())['response_path']).exists())
    else:
        events = [json.loads(line) for line in (tmp_path / 'run/logs/hermes-agent-events.jsonl').read_text().splitlines()]
        assert any((tmp_path / 'run' / e['stdout_log']).read_bytes() == expected for e in events)


@pytest.mark.parametrize('parallel', [False, True])
@pytest.mark.parametrize('transport', ['truncated', 'encoding', 'nonobject'])
def test_valid_stdout_survives_bad_disk_final_without_losing_diagnostics(tmp_path, monkeypatch, parallel, transport):
    exercise(tmp_path, monkeypatch, parallel, transport + '_disk_valid_stdout')
    expected = (b'{"schema_version":' if transport == 'truncated' else
                b'\xff\xfe' if transport == 'encoding' else b'[1, null, "not a response"]')
    retained = tmp_path / 'run/revisions/r1/hermes/visual-final-transport'
    assert any(p.read_bytes() == expected for p in retained.glob('*.bin'))


@pytest.mark.parametrize('parallel', [False, True])
@pytest.mark.parametrize('fault', ['bad_request_hash', 'manifest', 'postcheck_raise'])
def test_runtime_and_request_integrity_still_stop(tmp_path, monkeypatch, parallel, fault):
    exercise(tmp_path, monkeypatch, parallel, fault)
    observation = json.loads((tmp_path / 'observation.json').read_text())
    assert observation['callback_count'] == 0
    assert observation['result_stage'] == 'parent_visual_integrity'


@pytest.mark.parametrize('parallel', [False, True])
@pytest.mark.parametrize('transport', ['truncated_disk', 'encoding_disk', 'nonobject_disk',
    'truncated_stdout', 'encoding_stdout', 'nonobject_stdout', 'later_pass'])
def test_checkpoint_concern_survives_final_and_returns_to_repair(tmp_path, monkeypatch, parallel, transport):
    exercise(tmp_path, monkeypatch, parallel, 'finding_' + transport)
