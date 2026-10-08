"""Ordinary finding contract and developer guardrails; no clinical certification."""
import pytest
from finding_policy import blocks_construction, blocks_publication, normalize_finding

@pytest.mark.parametrize('raw', [
    {'issue': 'Unknown check', 'publication_disposition': 'warning'},
    {'issue': 'Bad contract', 'finding_policy': {'classification': 'editorial_warning', 'reason': 'unsafe', 'repair_owner': 'drafting'}},
])
def test_unknown_policy_preserves_evidence_and_names_maintenance_owner(raw):
    finding = normalize_finding(raw, producer='ordinary-test')
    assert finding['code'] == 'finding-policy-classification'
    assert finding['original_finding'] == raw
    assert finding['finding_policy'] == {'classification': 'technical_failure', 'reason': 'finding-policy-classification', 'repair_owner': 'construction'}
    assert finding['recovery_class'] == 'capability_gap'
    assert blocks_construction(finding) and blocks_publication(finding)


def test_legacy_warning_cannot_authorize_publication():
    assert blocks_publication({'issue': 'Unknown warning', 'publication_disposition': 'warning'})


def _developer_fixture(tmp_path, source, declarations):
    import json
    import offline_reliability_gate as gate
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    (scripts / 'example.py').write_text(source)
    audit = tmp_path / gate.AUDIT.relative_to(gate.ROOT)
    audit.parent.mkdir(parents=True)
    audit.write_text(json.dumps({'checks': declarations}))
    return gate


def test_audited_class_method_with_unclassified_early_return_is_rejected(tmp_path):
    gate = _developer_fixture(tmp_path, 'class Check:\n    def validate(self):\n        return [{"issue": "unknown finding"}]\n', [])
    records = gate.blocking_check_inventory(tmp_path)
    assert records[0]['function'] == 'Check.validate'
    records[0].update(scope='ordinary', role='producer')
    import json
    (tmp_path / gate.AUDIT.relative_to(gate.ROOT)).write_text(json.dumps({'checks': records}))
    assert any('Unclassified finding producer' in issue for issue in gate.policy_findings(tmp_path))


def test_fingerprinted_raw_warning_decision_still_fails_policy_guard(tmp_path):
    gate = _developer_fixture(tmp_path, 'def publish(findings):\n    return [f for f in findings if f.get("publication_disposition") != "warning"]\n', [])
    records = gate.blocking_check_inventory(tmp_path)
    records[0].update(scope='ordinary', role='decision')
    import json
    (tmp_path / gate.AUDIT.relative_to(gate.ROOT)).write_text(json.dumps({'checks': records}))
    assert any('Raw finding decision' in issue for issue in gate.policy_findings(tmp_path))


def test_fingerprinted_presence_veto_still_fails_policy_guard(tmp_path):
    gate = _developer_fixture(tmp_path, 'def publish(findings):\n    return {"status": "blocked" if findings else "passed"}\n', [])
    records = gate.blocking_check_inventory(tmp_path)
    records[0].update(scope='ordinary', role='decision', decision_inputs=['findings'])
    import json
    (tmp_path / gate.AUDIT.relative_to(gate.ROOT)).write_text(json.dumps({'checks': records}))
    assert any('Raw finding decision' in issue for issue in gate.policy_findings(tmp_path))


def test_declared_clinical_owner_cannot_authorize_other_repair_cause():
    raw = {'issue': 'Clinical defect', 'finding_policy': {'classification': 'essential_defect', 'reason': 'fact', 'repair_owner': 'drafting'}, 'recovery_class': 'deterministic_structure_defect', 'action': 'rebuild_deterministic_structure'}
    finding = normalize_finding(raw, producer='ordinary-test')
    assert finding['code'] == 'finding-policy-classification'
    assert finding['original_finding'] == raw


def test_unclassified_render_caution_cannot_disappear_from_final_publication(tmp_path, monkeypatch):
    import quality
    from test_atomic_delivery import _publish_fixture, _passing_quality
    run, revision, source = _publish_fixture(tmp_path)
    monkeypatch.setattr(quality, 'deterministic_content_check', lambda *_: [])
    assert _passing_quality(revision, source)['status'] == 'passed'
    import json
    build = json.loads((revision / 'candidate-build.json').read_text())
    build['render_report']['artifacts'][0]['warnings'] = [{'issue': 'Undeclared renderer warning', 'publication_disposition': 'warning'}]
    report = quality.quality_report(revision, source, build['render_report'], None)
    assert report['status'] == 'blocked'
    assert any(item.get('code') == 'finding-policy-classification' for item in report['findings'])


def test_fingerprint_refresh_cannot_silently_downgrade_a_declared_essential_reason(tmp_path):
    import json
    source = 'def check():\n    return classify_finding({"issue": "Wrong fact"}, classification="essential_defect", reason="approved-fact", repair_owner="drafting")\n'
    gate = _developer_fixture(tmp_path, source, [])
    import ast
    record = gate.blocking_check_inventory(tmp_path)[0]
    record.update(scope='ordinary', role='producer', policy_declarations=gate.policy_declarations(ast.parse(source).body[0]))
    mutated = source.replace('essential_defect', 'editorial_warning').replace('"drafting"', '"none"')
    (tmp_path / 'scripts/example.py').write_text(mutated)
    record['code_sha256'] = gate.blocking_check_inventory(tmp_path)[0]['code_sha256']
    (tmp_path / gate.AUDIT.relative_to(gate.ROOT)).write_text(json.dumps({'checks': [record]}))
    assert any('reason/classification/owner audit' in issue for issue in gate.policy_findings(tmp_path))


def test_unknown_finding_does_not_erase_a_valid_companion():
    import quality
    from finding_policy import classify_finding
    clinical = classify_finding({'issue': 'Wrong enrollment'}, classification='essential_defect', reason='fact', repair_owner='drafting')
    findings = quality._blocking_findings([{'issue': 'Unknown check'}, clinical])
    assert len(findings) == 2
    assert findings[0]['code'] == 'finding-policy-classification'
    assert findings[1] == clinical


@pytest.mark.parametrize('classification,owner,construction,publication', [
    ('editorial_warning', 'none', False, False),
    ('semantic_uncertainty', 'independent_review', False, True),
    ('essential_defect', 'drafting', True, True),
    ('technical_failure', 'integrity', True, True),
])
def test_stage_decisions_preserve_review_and_essential_repair(classification, owner, construction, publication):
    from finding_policy import classify_finding
    finding = classify_finding({'issue': 'Declared cause'}, classification=classification, reason='declared-cause', repair_owner=owner)
    assert blocks_construction(finding) is construction
    assert blocks_publication(finding) is publication


def test_malformed_policy_is_a_diagnosable_technical_stage_failure():
    raw = {'issue': 'Invalid declaration', 'finding_policy': {'classification': 'editorial_warning'}}
    assert blocks_construction(raw) and blocks_publication(raw)
    assert normalize_finding(raw, producer='ordinary-test')['code'] == 'finding-policy-classification'


def test_developer_guardrails_are_not_ordinary_runtime_gates():
    import ast
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for path in (root / 'scripts').glob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                assert all('offline_reliability_gate' not in item.name for item in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert 'offline_reliability_gate' not in (node.module or '')


def test_fingerprinted_compound_presence_veto_still_fails_policy_guard(tmp_path):
    gate = _developer_fixture(tmp_path, 'def publish(findings, allowed):\n    return {"status": "blocked" if findings and allowed else "passed"}\n', [])
    records = gate.blocking_check_inventory(tmp_path)
    records[0].update(scope='ordinary', role='decision', decision_inputs=['findings'])
    import json
    (tmp_path / gate.AUDIT.relative_to(gate.ROOT)).write_text(json.dumps({'checks': records}))
    assert any('Raw finding decision' in issue for issue in gate.policy_findings(tmp_path))
