import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
import pytest
import offline_reliability_gate as gate


def test_collected_parameterized_cases_are_partitioned_exactly_once():
    ids = ['tests/test_example.py::test_case[second]',
           'tests/test_example.py::test_case[first]',
           'tests/test_example.py::test_other']
    shards = [gate.shard_ids(ids, index, 5) for index in range(5)]
    assert sorted(node for shard in shards for node in shard) == sorted(ids)
    assert shards == [sorted(ids)[index::5] for index in range(5)]
    with pytest.raises(ValueError):
        gate.shard_ids(ids, 5, 5)
    with pytest.raises(ValueError):
        gate.shard_ids(ids + ids[:1], 0, 5)




def test_release_check_is_explicit_and_excludes_live_suites():
    command = gate.test_command('python')
    assert command[:3] == ['python', '-m', 'pytest']
    assert len(gate.TEST_FILES) < len(list((gate.ROOT / 'tests').glob('test_*.py')))
    assert all((gate.ROOT / 'tests' / filename).is_file() for filename in gate.TEST_FILES)
    assert {'test_ai_quality_boundary.py', 'test_ai_review_handoff.py',
            'test_general_document_repair.py', 'test_ai_delivery_outcomes.py'} <= set(gate.TEST_FILES)
    assert {'test_content_review_recovery.py', 'test_review_scheduler.py'} <= set(gate.TEST_FILES)
    assert {'test_observer_clean_partial.py', 'test_production_visual_transport.py',
            'test_visual_transport_retention.py', 'test_production_visual_incomplete.py',
            'test_production_visual_metadata.py'} <= set(gate.TEST_FILES)
    assert {'test_document_review_ownership.py', 'test_visual_evidence_followup.py',
            'test_observer_review_recovery.py', 'test_shared_review_to_repair.py',
            'test_parent_review_recovery_report.py', 'test_parent_partial_integrity.py',
            'test_review_outer_framing.py', 'test_observer_concern_channels.py',
            'test_visual_retry_feedback.py', 'test_attested_channel_integrity.py',
            'test_review_repair_priority.py', 'test_bounded_diagnostic_export.py',
            'test_repair_with_incomplete_visual.py',
            'test_repair_visual_stop_conditions.py'} <= set(gate.TEST_FILES)
    assert 'test_review_resolutions.py' not in gate.TEST_FILES
    assert 'test_hypothesis_fidelity.py' not in gate.TEST_FILES
    assert not any('e2e' in node or 'certification' in node or 'corpus' in node for node in command)










def test_ci_uses_five_disjoint_shards_with_always_uploaded_evidence():
    workflow = (gate.ROOT / '.github/workflows/presentation-delivery.yml').read_text()
    assert 'shard: [0, 1, 2, 3, 4]' in workflow
    assert 'fail-fast: false' in workflow
    assert '--timeout 1200 --shard-index ${{ matrix.shard }} --shard-count 5' in workflow
    assert 'timeout-minutes: 30' in workflow
    assert '--verify-shards' in workflow and 'needs: delivery-policy' in workflow
    assert workflow.count('uses: actions/upload-artifact@v4') == 2
    assert workflow.count('if: always()') >= 4
    assert 'python -m pytest tests/test_worker_boundary.py' not in workflow


def test_shard_artifact_coverage_rejects_missing_duplicate_and_incomplete_cases(tmp_path):
    ids = ['tests/probe.py::test_case[a]', 'tests/probe.py::test_case[b]',
           'tests/probe.py::test_case[c]']
    paths = []
    for index in range(2):
        selected = gate.shard_ids(ids, index, 2)
        path = tmp_path / f'shard-{index}.cases.json'
        path.write_text(json.dumps({'index': index, 'count': 2, 'all': ids,
                                    'selected': selected, 'completed': selected}))
        paths.append(path)
    assert gate.verify_coverage(tmp_path, 2) == 3
    original = paths[0].read_text()
    manifest = json.loads(original)
    for field, value in [('completed', []), ('selected', ids), ('all', ids[:-1]),
                         ('completed', manifest['completed'] * 2), ('index', 1)]:
        changed = dict(manifest, **{field: value})
        paths[0].write_text(json.dumps(changed))
        with pytest.raises(ValueError):
            gate.verify_coverage(tmp_path, 2)
    paths[0].write_text(original)
    paths[1].unlink()
    with pytest.raises(ValueError):
        gate.verify_coverage(tmp_path, 2)


def test_gate_retains_early_failure_and_partial_junit_on_timeout(tmp_path, monkeypatch, capsys):
    import xml.etree.ElementTree as ET
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'tests/test_probe.py').write_text(
        'import time\n'
        'def test_a_failure():\n    assert False, "EARLY_FAILURE_VISIBLE"\n'
        'def test_b_hang():\n    time.sleep(60)\n')
    report = tmp_path / 'report.json'
    monkeypatch.setattr(gate, 'ROOT', tmp_path)
    monkeypatch.setattr(gate, 'TEST_FILES', ('test_probe.py',))
    monkeypatch.setattr(gate, 'test_environment', lambda _: (os.environ.copy(), None))
    monkeypatch.setattr(sys, 'argv', ['gate', '--timeout', '2', '--report', str(report)])
    import threading
    import time
    codes = []
    worker = threading.Thread(target=lambda: codes.append(gate.main()))
    worker.start()
    log = report.with_suffix('.log')
    until = time.monotonic() + 5
    try:
        while worker.is_alive() and time.monotonic() < until:
            if log.exists() and 'EARLY_FAILURE_VISIBLE' in log.read_text():
                break
            time.sleep(0.01)
        # Evidence must be available while the later test is still hung, not
        # merely reconstructed by the parent after its timeout.
        assert worker.is_alive()
        assert json.loads(report.read_text())['status'] == 'running'
        assert ET.parse(report.with_suffix('.xml')).find('.//failure') is not None
    finally:
        worker.join(timeout=10)
    assert not worker.is_alive() and codes == [1]
    output = capsys.readouterr().out
    assert 'EARLY_FAILURE_VISIBLE' in output
    assert 'EARLY_FAILURE_VISIBLE' in report.with_suffix('.log').read_text()
    result = json.loads(report.read_text())
    assert result['timed_out'] is True
    cases = json.loads(report.with_suffix('.cases.json').read_text())
    assert len(cases['all']) == 2
    assert cases['completed'] == ['tests/test_probe.py::test_a_failure']
    junit = ET.parse(report.with_suffix('.xml'))
    assert junit.find('.//failure') is not None
    assert junit.find('.//error[@type="timeout"]') is not None
    assert junit.find('.//testcase[@name="tests/test_probe.py::test_b_hang"]/error[@type="incomplete"]') is not None


@pytest.mark.skipif(os.name == 'nt', reason='POSIX detached process probe')
def test_timeout_does_not_wait_for_detached_descendant_output_pipe(tmp_path, monkeypatch):
    import signal
    import time
    (tmp_path / 'tests').mkdir()
    pid_file = tmp_path / 'descendant.pid'
    (tmp_path / 'tests/test_probe.py').write_text(
        'import subprocess, sys, time\nfrom pathlib import Path\n'
        'def test_hang():\n'
        '    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(8)"], start_new_session=True)\n'
        f'    Path({str(pid_file)!r}).write_text(str(child.pid))\n'
        '    time.sleep(60)\n')
    monkeypatch.setattr(gate, 'ROOT', tmp_path)
    monkeypatch.setattr(gate, 'TEST_FILES', ('test_probe.py',))
    monkeypatch.setattr(gate, 'test_environment', lambda _: (os.environ.copy(), None))
    monkeypatch.setattr(sys, 'argv', ['gate', '--timeout', '2', '--report', str(tmp_path / 'report.json')])
    original_command = gate.test_command
    monkeypatch.setattr(gate, 'test_command', lambda: original_command() + ['-s'])
    started = time.monotonic()
    try:
        assert gate.main() == 1
        assert time.monotonic() - started < 5
    finally:
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_gate_preserves_collection_errors_as_junit(tmp_path, monkeypatch):
    import xml.etree.ElementTree as ET
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'tests/test_probe.py').write_text('raise RuntimeError("COLLECTION_FAILURE")\n')
    report = tmp_path / 'report.json'
    monkeypatch.setattr(gate, 'ROOT', tmp_path)
    monkeypatch.setattr(gate, 'TEST_FILES', ('test_probe.py',))
    monkeypatch.setattr(gate, 'test_environment', lambda _: (os.environ.copy(), None))
    monkeypatch.setattr(sys, 'argv', ['gate', '--timeout', '10', '--report', str(report)])
    assert gate.main() == 1
    junit = ET.parse(report.with_suffix('.xml'))
    assert 'COLLECTION_FAILURE' in junit.find('.//error').text
    assert 'INTERNALERROR' not in report.with_suffix('.log').read_text()


def test_real_collected_parameterized_shards_have_exact_once_coverage(tmp_path, monkeypatch):
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'tests/test_probe.py').write_text(
        'import pytest\n@pytest.mark.parametrize("value", range(7))\n'
        'def test_case(value):\n    assert value >= 0\n')
    monkeypatch.setattr(gate, 'ROOT', tmp_path)
    monkeypatch.setattr(gate, 'TEST_FILES', ('test_probe.py',))
    monkeypatch.setattr(gate, 'test_environment', lambda _: (os.environ.copy(), None))
    reports = tmp_path / 'evidence'
    for index in range(5):
        report = reports / f'shard-{index}.json'
        monkeypatch.setattr(sys, 'argv', ['gate', '--timeout', '10', '--shard-count', '5',
                                        '--shard-index', str(index), '--report', str(report)])
        assert gate.main() == 0
        assert json.loads(report.read_text())['status'] == 'passed'
    assert gate.verify_coverage(reports, 5) == 7
    monkeypatch.setattr(sys, 'argv', ['gate', '--verify-shards', str(reports), '--shard-count', '5'])
    assert gate.main() == 0


@pytest.mark.skipif(sys.platform != 'linux', reason='Hermes Linux profile office runtime')
def test_gate_subprocess_discovers_profile_office_with_restricted_worker_path(tmp_path, monkeypatch):
    office = tmp_path / 'clinical-office-runtime/bin/soffice'
    office.parent.mkdir(parents=True)
    office.write_text('#!/bin/sh\nprintf "LibreOffice test renderer\\n"\n')
    office.chmod(0o755)
    other = office.parent / 'libreoffice'
    other.write_text('#!/bin/sh\nprintf "different renderer\\n"\n')
    other.chmod(0o755)
    skill = tmp_path / 'skills/clinical-document-generation'
    skill.mkdir(parents=True)
    (skill / 'INSTALLATION-ASSURANCE.json').write_text(json.dumps({
        'status': 'passed',
        'active_path_smoke': {
            'status': 'passed', 'active_root': str(skill.resolve()),
            'assurance': {'status': 'passed', 'renderer': {'kind': 'LibreOffice', 'path': str(office)}},
        },
    }))
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    monkeypatch.setenv('PATH', str(tmp_path / 'restricted-worker-bin'))

    aliases = tmp_path / 'office-aliases'
    aliases.mkdir()
    environment, selected = gate.test_environment(aliases)
    assert selected == str(office)
    assert environment['PATH'].split(os.pathsep)[0] == str(aliases)
    assert Path(shutil.which('libreoffice', path=environment['PATH'])).resolve() == office
    assert Path(shutil.which('soffice', path=environment['PATH'])).resolve() == office
    result = subprocess.run(
        [sys.executable, '-c',
         'import sys; sys.path.insert(0, sys.argv[1]); '
         'from quality import renderer; print(renderer()["path"])',
         str(gate.ROOT / 'scripts')],
        env=environment, capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == str(office)
