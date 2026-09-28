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


def test_blocking_fingerprints_do_not_depend_on_python_ast_dump_format(monkeypatch):
    before = gate.blocking_check_inventory()
    monkeypatch.setattr(gate.ast, 'dump', lambda *args, **kwargs: 'runtime-specific-AST-format')
    assert gate.blocking_check_inventory() == before


def test_blocking_fingerprint_includes_function_decorators(tmp_path):
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    target = scripts / 'example.py'
    target.write_text('@first\ndef check():\n    return {"status": "blocked"}\n')
    before = gate.blocking_check_inventory(tmp_path)
    target.write_text('@second\ndef check():\n    return {"status": "blocked"}\n')
    after = gate.blocking_check_inventory(tmp_path)
    assert before[0]['code_sha256'] != after[0]['code_sha256']


def test_blocking_fingerprint_detects_a_changed_function_body(tmp_path):
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    target = scripts / 'example.py'
    target.write_text('def check():\n    return {"status": "blocked"}\n')
    before = gate.blocking_check_inventory(tmp_path)
    target.write_text('def check():\n    return {"status": "blocked", "reason": "changed"}\n')
    after = gate.blocking_check_inventory(tmp_path)
    assert before[0]['code_sha256'] != after[0]['code_sha256']
