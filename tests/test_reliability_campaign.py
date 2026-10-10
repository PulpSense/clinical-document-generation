"""Developer campaign CLI; live model judgments remain external evidence."""
import json
import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

import workflow
from reliability_campaign import campaign_cases
from test_clean_delivery import deliver

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'tests/reliability_campaign.py'


def cli(*args):
    return subprocess.run([sys.executable, str(CLI), *map(str, args)],
                          cwd=ROOT, capture_output=True, text=True)


def test_build_exports_raw_inputs_and_separate_expectations_for_all_families(tmp_path):
    pack = tmp_path / 'pack'
    built = cli('build', '--output', pack)
    assert built.returncode == 0, built.stderr
    manifest = json.loads((pack / 'campaign.json').read_text())
    assert len(manifest['cases']) == 10
    assert len([c for c in manifest['cases'] if c['pilot']]) == 3
    assert {(c['study_type'], c['icf_template']) for c in manifest['cases']} == {
        ('Retrospective', None), ('Prospective', 'Advarra'), ('Prospective', 'Sterling'),
        ('Ambispective', 'Advarra'), ('Ambispective', 'Sterling')}
    for case in manifest['cases']:
        raw = (pack / case['input']).read_text()
        assert 'SYNTHETIC' in raw
        assert 'approved_by' not in raw
        assert 'required_facts' not in raw
        assert (pack / case['oracle']).is_file()
    assert cli('build', '--output', pack).returncode != 0


@pytest.mark.parametrize('case', campaign_cases(), ids=lambda c: c['id'])
def test_campaign_sources_pass_public_admission_without_adding_optional_inputs(tmp_path, case):
    path = tmp_path / 'reference/study.reference.json'
    path.parent.mkdir()
    path.write_text(json.dumps(case['reference']))
    result = workflow.prepare(tmp_path)
    assert result['status'] == 'awaiting_approval', result
    assert workflow.approve(tmp_path, approved_by='synthetic-test-owner')['status'] == 'passed'
    assert workflow.validate(tmp_path)['status'] == 'passed'


def operation_fixture(root, pack, case, name, status, elapsed):
    run = root / name
    (run / 'input').mkdir(parents=True)
    (run / 'input/source.md').write_bytes((pack / case['input']).read_bytes())
    result = {'status': status, 'elapsed_seconds': elapsed, 'delivery': {'confirmed': status == 'passed'},
              'client_outputs': [], 'manifest': 'revisions/r1/generation-manifest.json'}
    quality = {'status': 'passed', 'warnings': []}
    files = []
    if status == 'passed':
        for name in ['protocol.docx', 'icf.docx', 'study.xml']:
            path = run / 'output' / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(('synthetic ' + name).encode())
            files.append({'path': 'output/' + name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        result['client_outputs'] = [x['path'] for x in files]
    manifest = run / result['manifest']
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({'status': status, 'quality': quality, 'client_outputs': files}))
    state = {'status': status, 'operation_id': 'default', 'started_at_epoch': 100 if status != 'passed' else 1100,
             'release_identity': {'git_commit': 'synthetic-candidate', 'package_fingerprint': 'synthetic'},
             'approval_identity': {'revision_id': 'r1', 'status': 'approved'},
             'attempt_counters': {'handoff_dispatches': {'review': 1}}, 'result': result}
    (run / 'logs').mkdir()
    (run / 'logs/desktop-operation.json').write_text(json.dumps(state))
    return run


def test_report_counts_failed_first_attempt_and_successful_restart_separately(tmp_path):
    pack = tmp_path / 'pack'
    assert cli('build', '--output', pack).returncode == 0
    case = json.loads((pack / 'campaign.json').read_text())['cases'][0]
    runs = tmp_path / 'runs'
    operation_fixture(runs, pack, case, 'attempt-1', 'review_required', 1000)
    operation_fixture(runs, pack, case, 'attempt-2', 'passed', 800)
    report = cli('report', '--pack', pack, '--runs-root', runs, '--evidence-kind', 'controlled_fixture')
    assert report.returncode == 0, report.stderr
    data = json.loads(report.stdout)
    assert data['first_operation_delivery'] == {'numerator': 0, 'denominator': 1}
    assert data['eventual_delivery'] == {'numerator': 1, 'denominator': 1}
    assert data['terminal_failures'] == {'numerator': 1, 'denominator': 2}
    assert data['total_elapsed_seconds'] == 1800
    assert data['same_operation_recovery']['numerator'] == 0
    assert data['external_audit_complete']['numerator'] == 0
    assert data['certification'] is False
    assert len(data['unrun_cases']) == 9


@pytest.mark.parametrize('defect', ['timeout', 'nested-counter', 'counter-container', 'delivery-shape', 'quality-shape'])
def test_report_retains_deadline_and_malformed_attempts_alongside_valid_delivery(tmp_path, defect):
    pack = tmp_path / 'pack'
    assert cli('build', '--output', pack).returncode == 0
    case = json.loads((pack / 'campaign.json').read_text())['cases'][0]
    runs = tmp_path / 'runs'
    run = operation_fixture(runs, pack, case, 'attempt-1', 'passed', 700)
    path = run / 'logs/desktop-operation.json'
    state = json.loads(path.read_text())
    state['started_at_epoch'] = 100
    if defect == 'timeout':
        state['status'] = state['result']['status'] = 'timeout'
    elif defect == 'nested-counter':
        state['attempt_counters'] = {'drafting': 2}
    elif defect == 'counter-container':
        state['attempt_counters'] = 'broken'
    elif defect == 'delivery-shape':
        state['result']['delivery'] = []
    else:
        manifest_path = run / state['result']['manifest']
        manifest = json.loads(manifest_path.read_text())
        manifest['quality'] = []
        manifest_path.write_text(json.dumps(manifest))
    path.write_text(json.dumps(state))
    operation_fixture(runs, pack, case, 'attempt-2', 'passed', 800)
    result = cli('report', '--pack', pack, '--runs-root', runs, '--evidence-kind', 'controlled_fixture')
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert len(report['operations']) == 2
    assert report['total_elapsed_seconds'] == 1500
    assert report['terminal_failures'] == {'numerator': 1, 'denominator': 2}
    assert report['eventual_delivery'] == {'numerator': 1, 'denominator': 1}
    if defect != 'timeout':
        assert report['evidence_errors']


@pytest.mark.parametrize('defect', ['bytes', 'extra-output', 'missing-duration', 'unknown-input', 'malformed-state', 'nonobject-state'])
def test_report_keeps_incomplete_or_corrupt_attempt_evidence_visible(tmp_path, defect):
    pack = tmp_path / 'pack'
    assert cli('build', '--output', pack).returncode == 0
    case = json.loads((pack / 'campaign.json').read_text())['cases'][0]
    runs = tmp_path / 'runs'
    run = operation_fixture(runs, pack, case, 'attempt', 'passed', 800)
    state_path = run / 'logs/desktop-operation.json'
    if defect == 'bytes':
        (run / 'output/protocol.docx').write_text('changed')
    elif defect == 'extra-output':
        (run / 'output/diagnostics.zip').write_text('not a deliverable')
    elif defect == 'missing-duration':
        state = json.loads(state_path.read_text())
        state['result'].pop('elapsed_seconds')
        state_path.write_text(json.dumps(state))
    elif defect == 'unknown-input':
        (run / 'input/source.md').write_text('unknown source')
    elif defect == 'malformed-state':
        state_path.write_text('not json')
    else:
        state_path.write_text('[]')
    result = cli('report', '--pack', pack, '--runs-root', runs, '--evidence-kind', 'controlled_fixture')
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert len(report['operations']) == 1
    assert report['certification'] is False
    if defect == 'missing-duration':
        assert report['unmeasured_operations'] == [str(state_path)]
    else:
        assert report['evidence_errors']
        assert report['operations'][0]['delivered'] is False


def test_equivalent_inputs_have_identical_expectations_and_pack_tampering_is_rejected(tmp_path):
    pack = tmp_path / 'pack'
    assert cli('build', '--output', pack).returncode == 0
    cases = json.loads((pack / 'campaign.json').read_text())['cases']
    for narrative, structured in zip(cases[::2], cases[1::2]):
        assert narrative['oracle_sha256'] == structured['oracle_sha256']
        assert narrative['input_sha256'] != structured['input_sha256']
    (pack / cases[0]['oracle']).write_text('{}')
    result = cli('report', '--pack', pack, '--runs-root', tmp_path, '--evidence-kind', 'controlled_fixture')
    assert result.returncode != 0
    assert 'Campaign oracle changed' in result.stderr


@pytest.mark.parametrize('counter,count', [('generation', 2), ('verification', 2),
                                          ('parent_visual_callbacks', 1), ('handoff_dispatches', 2)])
def test_report_counts_recovery_inside_one_operation(tmp_path, counter, count):
    pack = tmp_path / 'pack'
    assert cli('build', '--output', pack).returncode == 0
    case = json.loads((pack / 'campaign.json').read_text())['cases'][0]
    runs = tmp_path / 'runs'
    run = operation_fixture(runs, pack, case, 'attempt', 'passed', 800)
    path = run / 'logs/desktop-operation.json'
    state = json.loads(path.read_text())
    state['attempt_counters'][counter] = {'review': count}
    path.write_text(json.dumps(state))
    result = cli('report', '--pack', pack, '--runs-root', runs, '--evidence-kind', 'controlled_fixture')
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report['same_operation_recovery'] == {'numerator': 1, 'denominator': 1}
    assert report['first_operation_delivery'] == {'numerator': 1, 'denominator': 1}


@pytest.mark.parametrize('case', campaign_cases(), ids=lambda c: c['id'])
def test_campaign_sources_reach_publication_with_controlled_models_and_renderer(tmp_path, monkeypatch, case):
    result, revision = deliver(tmp_path, monkeypatch, case['reference'])
    assert result['status'] == 'passed', result
    assert result['warnings'] == []
    expected = case['oracle']['document_set']
    assert sorted(path.name for path in (tmp_path / 'output').iterdir()) == sorted(expected)
    assert (revision / 'approved-reference.json').is_file()


def test_phrase_uncertainty_cannot_publish_without_independent_resolution(tmp_path, monkeypatch):
    from test_handoff_quality import acceptance_verification

    observed = []
    def review(request):
        response = acceptance_verification(request)
        targets = {row['caution_sha256'] for row in request.get('lexical_review_cautions', [])
                   if row['caution'].get('clause_id') == 'sterling.privacy.authorization-duration'}
        observed.extend(targets)
        response['uncertainty_resolutions'] = [row for row in response.get('uncertainty_resolutions', [])
                                              if row['caution_sha256'] not in targets]
        return response

    result, _ = deliver(tmp_path, monkeypatch, campaign_cases()[0]['reference'], review=review)
    assert observed
    assert result['status'] != 'passed'
    assert not (tmp_path / 'output').exists()



