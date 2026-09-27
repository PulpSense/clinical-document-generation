import json
from pathlib import Path
import offline_reliability_gate as gate


def test_every_direct_blocking_producer_has_a_current_audit():
    assert gate.audit_findings() == []
    inventory = json.loads(gate.AUDIT.read_text())
    assert all(item['family'] in inventory['families'] for item in inventory['checks'])
    assert all(item['authority'] and item['false_rejection_risk'] and item['duplicate_policy'] for item in inventory['families'].values())


def test_release_check_is_explicit_and_excludes_live_suites():
    command = gate.test_command('python')
    assert command[:3] == ['python', '-m', 'pytest']
    assert len(gate.TEST_FILES) < len(list((gate.ROOT / 'tests').glob('test_*.py')))
    assert all((gate.ROOT / 'tests' / filename).is_file() for filename in gate.TEST_FILES)
    assert 'test_assessment_matrix.py' in gate.TEST_FILES
    assert 'test_hypothesis_fidelity.py' in gate.TEST_FILES
    assert 'test_sterling_rendered_scope.py' in gate.TEST_FILES
    assert not any('e2e' in node or 'certification' in node or 'corpus' in node for node in command)


def test_new_blocking_producer_requires_developer_audit(tmp_path):
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    (scripts / 'example.py').write_text('def check():\n    return {"status": "blocked"}\n')
    audit = tmp_path / gate.AUDIT.relative_to(gate.ROOT)
    audit.parent.mkdir(parents=True)
    audit.write_text('{"checks": []}')
    assert gate.audit_findings(tmp_path) == ['Blocking-check audit requires review: scripts/example.py:check']
