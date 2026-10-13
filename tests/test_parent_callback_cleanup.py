"""Real bounded subprocess regressions; no model or image-review simulation."""
import errno
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import traceback

import pytest
import workflow


def _alive(pid):
    status = Path(f'/proc/{pid}/stat')
    try:
        return status.read_text().split()[2] != 'Z'
    except (FileNotFoundError, ProcessLookupError):
        return False


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux process-group regression')
@pytest.mark.parametrize('parent_exits', [False, True])
@pytest.mark.parametrize('inherited_pipes', [False, True])
@pytest.mark.parametrize('detached', [False, True])
def test_parent_callback_reaps_sigterm_ignoring_descendant_and_retains_output(tmp_path, parent_exits, inherited_pipes, detached):
    revision = tmp_path / 'revisions/r1'
    revision.mkdir(parents=True)
    pid_path = tmp_path / 'child.pid'
    command = tmp_path / 'callback'
    command.write_text(
        f'#!{sys.executable}\n'
        'import subprocess, sys, time\n'
        f'child = subprocess.Popen([sys.executable, "-c", '
        f'"import os, signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); '
        f'open({str(pid_path)!r}, chr(119)).write(str(os.getpid())); time.sleep(60)"], '
        + f'start_new_session={detached!r}, '
        + ('stdout=None, stderr=None)\n' if inherited_pipes else 'stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n')
        + f'while not __import__("pathlib").Path({str(pid_path)!r}).exists(): time.sleep(0.01)\n'
        + 'print("partial stdout", flush=True)\n'
        + 'print("partial stderr", file=sys.stderr, flush=True)\n'
        + ('sys.exit(0)\n' if parent_exits else 'time.sleep(60)\n')
    )
    command.chmod(0o700)
    started = time.monotonic()
    try:
        if parent_exits:
            workflow.command_parent_visual_reviewer(command)([], 0.5, revision, {})
        else:
            with pytest.raises(subprocess.TimeoutExpired):
                workflow.command_parent_visual_reviewer(command)([], 0.5, revision, {})
        pid = int(pid_path.read_text())
        deadline = time.monotonic() + 2
        while _alive(pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not _alive(pid), 'callback descendant survived callback completion'
        assert time.monotonic() - started < 4
        diagnostics = list((tmp_path / 'logs/parent-visual-reviewer').glob('*.json'))
        assert len(diagnostics) == 1
        record = json.loads(diagnostics[0].read_text())
        assert record['stdout'] == 'partial stdout\n'
        assert record['stderr'] == 'partial stderr\n'
        assert record['timed_out'] is (not parent_exits)
        assert record['cleanup_complete'] is True
        assert record['cleanup_errors'] == []
        assert diagnostics[0].stat().st_mode & 0o777 == 0o600
        assert not list((revision / 'hermes/verification-responses').glob('*.json'))
    finally:
        if pid_path.exists():
            pid = int(pid_path.read_text())
            if _alive(pid):
                os.kill(pid, signal.SIGKILL)


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux subreaper ownership regression')
def test_parent_callback_owns_double_fork_but_not_unrelated_host_child(tmp_path):
    revision = tmp_path / 'revisions/r1'
    revision.mkdir(parents=True)
    pid_path = tmp_path / 'orphan.pid'
    command = tmp_path / 'callback'
    command.write_text(
        f'#!{sys.executable}\n'
        'import os, subprocess, sys, time\n'
        'from pathlib import Path\n'
        f'code = "import os, time; os.setsid(); pid = os.fork(); '
        f'os._exit(0) if pid else None; open({str(pid_path)!r}, chr(119)).write(str(os.getpid())); time.sleep(60)"\n'
        'subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).wait()\n'
        f'while not Path({str(pid_path)!r}).exists(): time.sleep(0.01)\n'
    )
    command.chmod(0o700)
    unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    try:
        workflow.command_parent_visual_reviewer(command)([], 1.0, revision, {})
        assert not _alive(int(pid_path.read_text()))
        assert unrelated.poll() is None
    finally:
        unrelated.kill()
        unrelated.wait(timeout=1)
        if pid_path.exists() and _alive(int(pid_path.read_text())):
            os.kill(int(pid_path.read_text()), signal.SIGKILL)


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux supervisor failure regression')
@pytest.mark.parametrize('callback_stays_alive', [False, True])
def test_parent_callback_reports_incomplete_cleanup_when_owner_dies(tmp_path, callback_stays_alive):
    revision = tmp_path / 'revisions/r1'
    revision.mkdir(parents=True)
    pid_path = tmp_path / 'callback.pid'
    command = tmp_path / 'callback'
    command.write_text(
        f'#!{sys.executable}\n'
        'import os, signal, sys, time\n'
        f'open({str(pid_path)!r}, "w").write(str(os.getpid()))\n'
        'print("callback stdout", flush=True)\n'
        'print("callback stderr", file=sys.stderr, flush=True)\n'
        'os.kill(os.getppid(), signal.SIGKILL)\n'
        + ('time.sleep(60)\n' if callback_stays_alive else '')
    )
    command.chmod(0o700)
    try:
        expected = subprocess.TimeoutExpired if callback_stays_alive else RuntimeError
        with pytest.raises(expected) as caught:
            workflow.command_parent_visual_reviewer(command)([], 0.5, revision, {})
        if callback_stays_alive:
            assert any('cleanup incomplete' in note for note in caught.value.__notes__)
        else:
            assert 'cleanup incomplete' in str(caught.value)
        diagnostics = list((tmp_path / 'logs/parent-visual-reviewer').glob('*.json'))
        assert len(diagnostics) == 1
        record = json.loads(diagnostics[0].read_text())
        assert record['cleanup_complete'] is False
        assert record['cleanup_errors']
        assert record['error_type'] == expected.__name__
        assert record['stdout'] == 'callback stdout\n'
        assert record['stderr'] == 'callback stderr\n'
    finally:
        if pid_path.exists() and _alive(int(pid_path.read_text())):
            os.kill(int(pid_path.read_text()), signal.SIGKILL)


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux executable callback regression')
@pytest.mark.parametrize('outcome', ['timeout', 'nonzero', 'success', 'signal'])
@pytest.mark.parametrize('fault', ['create', 'write', 'unlink'])
def test_parent_callback_preserves_primary_when_evidence_persistence_fails(
    tmp_path, monkeypatch, outcome, fault,
):
    revision = tmp_path / 'revisions/r1'
    revision.mkdir(parents=True)
    command = tmp_path / 'callback'
    command.write_text(
        f'#!{sys.executable}\nimport os, signal, sys, time\n'
        'print("host-failure-stdout-marker", flush=True)\n'
        'print("host-failure-stderr-marker", file=sys.stderr, flush=True)\n'
        + ('time.sleep(60)\n' if outcome == 'timeout' else
           'sys.exit(7)\n' if outcome == 'nonzero' else
           'os.kill(os.getpid(), signal.SIGTERM)\n' if outcome == 'signal' else '')
    )
    command.chmod(0o700)
    injected = OSError(errno.ENOSPC, f'injected {fault} persistence failure')
    hits = []
    real_open, real_dump, real_unlink = os.open, json.dump, Path.unlink

    def diagnostic_open(path, *args, **kwargs):
        if Path(path).parent.name == 'parent-visual-reviewer' and not str(path).endswith('.cleanup.json'):
            hits.append(fault)
            raise injected
        return real_open(path, *args, **kwargs)

    def diagnostic_dump(payload, *args, **kwargs):
        if isinstance(payload, dict) and 'cleanup_complete' in payload:
            hits.append(fault)
            raise injected
        return real_dump(payload, *args, **kwargs)

    def report_unlink(path, *args, **kwargs):
        if str(path).endswith('.cleanup.json'):
            hits.append(fault)
            raise injected
        return real_unlink(path, *args, **kwargs)

    if fault == 'create':
        monkeypatch.setattr(os, 'open', diagnostic_open)
    elif fault == 'write':
        monkeypatch.setattr(json, 'dump', diagnostic_dump)
    else:
        monkeypatch.setattr(Path, 'unlink', report_unlink)
    expected = subprocess.TimeoutExpired if outcome == 'timeout' else RuntimeError
    with pytest.raises(expected) as caught:
        workflow.command_parent_visual_reviewer(command)([], 0.5 if outcome == 'timeout' else 5, revision, {})
    assert hits == [fault]
    if outcome == 'timeout':
        assert caught.value.timeout == 0.5
    elif outcome == 'nonzero':
        assert 'status 7' in str(caught.value)
    elif outcome == 'signal':
        assert f'status {-signal.SIGTERM}' in str(caught.value)
    else:
        assert 'persistence failed' in str(caught.value)
    output = caught.value.desktop_parent_output_evidence
    assert output['stdout'] == 'host-failure-stdout-marker\n'
    assert output['stderr'] == 'host-failure-stderr-marker\n'
    assert output['stdout_truncated'] is False
    assert output['stderr_truncated'] is False
    assert output['timed_out'] is (outcome == 'timeout')
    assert output['returncode'] == (7 if outcome == 'nonzero' else 0 if outcome == 'success' else
                                  -signal.SIGTERM if outcome == 'signal' else -signal.SIGKILL)
    evidence = '; '.join(getattr(caught.value, '__notes__', []))
    assert 'host-failure-stdout-marker' not in str(caught.value) + evidence
    assert 'host-failure-stderr-marker' not in str(caught.value) + evidence
    assert f'injected {fault} persistence failure' in evidence
    assert 'OSError' in evidence
    # A diagnostic failure must not skip report removal; a removal failure
    # must retain the completed supervisor report for investigation.
    reports = list((tmp_path / 'logs/parent-visual-reviewer').glob('*.cleanup.json'))
    assert len(reports) == (1 if fault == 'unlink' else 0)


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux executable callback regression')
@pytest.mark.parametrize('fault', ['create', 'write'])
@pytest.mark.parametrize('output', ['', 'unicode-secret-λ-marker' + 'λ' * 6000], ids=['empty', 'unicode-long'])
def test_parent_callback_memory_evidence_is_bounded_without_mutating_timeout(
    tmp_path, monkeypatch, fault, output,
):
    revision = tmp_path / 'revisions/r1'
    revision.mkdir(parents=True)
    command = tmp_path / 'callback'
    command.write_text(
        f'#!{sys.executable}\nimport sys, time\n'
        f'sys.stdout.write({output!r}); sys.stdout.flush()\n'
        f'sys.stderr.write({output!r}); sys.stderr.flush()\n'
        'time.sleep(60)\n'
    )
    command.chmod(0o700)
    real_open, real_dump = os.open, json.dump
    real_communicate = subprocess.Popen.communicate
    primary = []
    original_fields = []
    hits = []

    def communicate(process, *args, **kwargs):
        try:
            return real_communicate(process, *args, **kwargs)
        except subprocess.TimeoutExpired as exc:
            primary.append(exc)
            original_fields.append((exc.args, exc.cmd, exc.timeout, exc.output, exc.stderr))
            raise

    def diagnostic_open(path, *args, **kwargs):
        if Path(path).parent.name == 'parent-visual-reviewer' and not str(path).endswith('.cleanup.json'):
            hits.append(fault)
            raise OSError(errno.ENOSPC, 'bounded output creation failure')
        return real_open(path, *args, **kwargs)

    def diagnostic_dump(payload, *args, **kwargs):
        if isinstance(payload, dict) and 'cleanup_complete' in payload:
            hits.append(fault)
            raise OSError(errno.ENOSPC, 'bounded output write failure')
        return real_dump(payload, *args, **kwargs)

    monkeypatch.setattr(subprocess.Popen, 'communicate', communicate)
    if fault == 'create':
        monkeypatch.setattr(os, 'open', diagnostic_open)
    else:
        monkeypatch.setattr(json, 'dump', diagnostic_dump)
    with pytest.raises(subprocess.TimeoutExpired) as caught:
        workflow.command_parent_visual_reviewer(command)([], 0.5, revision, {})
    assert hits == [fault]
    assert primary == [caught.value]
    assert (caught.value.args, caught.value.cmd, caught.value.timeout,
            caught.value.output, caught.value.stderr) == original_fields[0]
    evidence = caught.value.desktop_parent_output_evidence
    assert evidence['stdout'] == output[:4096]
    assert evidence['stderr'] == output[:4096]
    assert evidence['stdout_truncated'] is bool(output)
    assert evidence['stderr_truncated'] is bool(output)
    rendered = ''.join(traceback.format_exception_only(caught.value))
    assert 'unicode-secret-λ-marker' not in rendered
    assert not list((tmp_path / 'logs/parent-visual-reviewer').glob('*.cleanup.json'))


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux executable callback regression')
@pytest.mark.parametrize('outcome', ['nonzero', 'success', 'timeout', 'signal'])
@pytest.mark.parametrize('fault', ['create', 'write'])
def test_parent_callback_retains_status_when_supervisor_report_persistence_fails(
    tmp_path, monkeypatch, outcome, fault,
):
    revision = tmp_path / 'revisions/r1'
    revision.mkdir(parents=True)
    command = tmp_path / 'callback'
    command.write_text(
        f'#!{sys.executable}\nimport os, signal, sys, time\n'
        'print("callback stdout", flush=True)\n'
        'print("callback stderr", file=sys.stderr, flush=True)\n'
        + ('time.sleep(60)\n' if outcome == 'timeout' else
           'sys.exit(7)\n' if outcome == 'nonzero' else
           'os.kill(os.getpid(), signal.SIGTERM)\n' if outcome == 'signal' else '')
    )
    command.chmod(0o700)
    # Inject only the isolated supervisor's report I/O, not host diagnostics
    # or the real executable callback. No disk exhaustion or source-file edits.
    source = workflow._PARENT_CALLBACK_SUPERVISOR
    target = ('    descriptor = os.open(status_path,' if fault == 'create' else
              '        json.dump({"returncode": returncode, "errors": errors}, handle)')
    indent = '    ' if fault == 'create' else '        '
    assert source.count(target) == 1
    source = source.replace(target, indent + f'raise OSError(28, "injected supervisor {fault} failure")\n' + target)
    monkeypatch.setattr(workflow, '_PARENT_CALLBACK_SUPERVISOR', source)
    expected = subprocess.TimeoutExpired if outcome == 'timeout' else RuntimeError
    with pytest.raises(expected) as caught:
        workflow.command_parent_visual_reviewer(command)([], 0.5 if outcome == 'timeout' else 5, revision, {})
    if outcome == 'nonzero':
        assert 'status 7' in str(caught.value)
    elif outcome == 'signal':
        assert f'status {-signal.SIGTERM}' in str(caught.value)
    elif outcome == 'success':
        assert 'cleanup incomplete' in str(caught.value)
    else:
        assert caught.value.timeout == 0.5
    record_paths = list((tmp_path / 'logs/parent-visual-reviewer').glob('*.json'))
    assert len(record_paths) == 1
    record = json.loads(record_paths[0].read_text())
    assert record['returncode'] == (7 if outcome == 'nonzero' else 0 if outcome == 'success' else
                                   -signal.SIGTERM if outcome == 'signal' else -signal.SIGKILL)
    assert record['stdout'] == 'callback stdout\n'
    assert 'callback stderr\n' in record['stderr']
    assert f'injected supervisor {fault} failure' in record['stderr']
    assert record['timed_out'] is (outcome == 'timeout')
    assert record['cleanup_complete'] is False
    assert record['cleanup_errors']
    assert record['error_type'] == expected.__name__
    assert any('cleanup incomplete' in note for note in caught.value.__notes__)
    assert not list((revision / 'hermes/verification-responses').glob('*.json'))
