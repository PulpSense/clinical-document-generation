"""Diagnostic retention uses production path checks, never follows symlinks."""
import hashlib
import json

import pytest
import workflow
from test_visual_units import parent_fixture
from visual_review import create_visual_review_unit


@pytest.fixture(params=['disk', 'stdout'])
def transport(tmp_path, request):
    revision, parent_path, parent = parent_fixture(tmp_path, 'retrospective', count=1)
    path = create_visual_review_unit(revision, parent_path, parent['visual_review_plan']['targets'][:1], 1)
    unit = json.loads(path.read_text())
    handoff = {'visual_unit': True, 'task': unit['task'], 'request_id': unit['request_id'],
        'request_path': path.relative_to(revision).as_posix(), 'response_path': unit['response_path']}
    raw = b'{"schema_version": "truncated original\xff'
    stdout = tmp_path / 'stdout.log'
    stdout.write_bytes(raw if request.param == 'stdout' else b'')
    if request.param == 'disk':
        final = revision / unit['response_path']
        final.parent.mkdir(parents=True, exist_ok=True)
        final.write_bytes(raw)
    destination = revision / 'hermes/visual-final-transport' / (
        unit['request_id'] + '.' + request.param + '.' + hashlib.sha256(raw).hexdigest() + '.bin')
    return revision, handoff, stdout, raw, destination


@pytest.mark.parametrize('inside', [False, True])
def test_symlinked_retention_directory_is_rejected(transport, tmp_path, inside):
    revision, handoff, stdout, raw, destination = transport
    target = (revision if inside else tmp_path) / 'symlink-directory-target'
    target.mkdir()
    destination.parent.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError):
        workflow._production_publish_quiet_response(revision, handoff, stdout)
    assert list(target.iterdir()) == []
    assert stdout.read_bytes() in (raw, b'')


@pytest.mark.parametrize('inside', [False, True])
def test_symlinked_diagnostic_file_is_rejected(transport, tmp_path, inside):
    revision, handoff, stdout, raw, destination = transport
    target = (revision if inside else tmp_path) / 'symlink-file-target'
    target.write_bytes(raw)
    destination.parent.mkdir()
    destination.symlink_to(target)
    with pytest.raises(ValueError):
        workflow._production_publish_quiet_response(revision, handoff, stdout)
    assert target.read_bytes() == raw
    assert destination.is_symlink()


def test_retention_preserves_exact_bytes_and_is_idempotent(transport):
    revision, handoff, stdout, raw, destination = transport
    assert workflow._production_publish_quiet_response(revision, handoff, stdout) is False
    assert destination.read_bytes() == raw
    before = destination.stat()
    assert workflow._production_publish_quiet_response(revision, handoff, stdout) is False
    assert destination.read_bytes() == raw
    after = destination.stat()
    assert (after.st_ino, after.st_mtime_ns) == (before.st_ino, before.st_mtime_ns)


def test_changed_existing_diagnostic_is_detected(transport):
    revision, handoff, stdout, raw, destination = transport
    workflow._production_publish_quiet_response(revision, handoff, stdout)
    destination.write_bytes(b'changed diagnostic')
    with pytest.raises(ValueError, match='diagnostic'):
        workflow._production_publish_quiet_response(revision, handoff, stdout)
    assert destination.read_bytes() == b'changed diagnostic'


def test_revision_external_diagnostic_destination_is_rejected(transport, tmp_path):
    revision, handoff, stdout, _, _ = transport
    # Disk transport validates its canonical request first; the handoff's
    # destination identifier must not authorize a lexical escape in either case.
    handoff['request_id'] = '../../../../escaped-diagnostic'
    with pytest.raises(ValueError):
        workflow._production_publish_quiet_response(revision, handoff, stdout)
    assert not list(tmp_path.glob('escaped-diagnostic*'))
