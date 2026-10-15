"""Public reviewer adapter regressions; no clinical or visual approval is simulated as live proof."""
import json
import shlex
from pathlib import Path

import pytest

import quality
import workflow
from test_desktop_delivery import _visual_handoff_fixture


@pytest.fixture(autouse=True)
def synthetic_managed_hermes_identity(monkeypatch):
    # These tests execute a shell callback, not a managed Hermes installation.
    identity = {'kind': 'synthetic-managed-hermes-identity',
                'fixture': 'reviewer-transport-shell-callback/v1'}
    def reject_installed_launcher_lookup():
        pytest.fail('Controlled shell callbacks must not discover installed Hermes')
    monkeypatch.setattr(workflow, '_managed_hermes_pair', reject_installed_launcher_lookup)
    monkeypatch.setattr(workflow, '_managed_hermes_identity', lambda: dict(identity))
    return identity


def reviewer_command(tmp_path, payload):
    output = tmp_path / 'review.json'
    output.write_text(json.dumps(payload))
    command = tmp_path / 'reviewer'
    command.write_text('#!/bin/sh\ncat ' + shlex.quote(str(output)) + '\n')
    command.chmod(0o700)
    return workflow.command_parent_visual_reviewer(command)


def test_request_schema_label_is_normalized_without_changing_visual_judgment(tmp_path, synthetic_managed_hermes_identity):
    handoff, request, response = _visual_handoff_fixture(tmp_path, 'protocol')
    revision = tmp_path / 'revisions/r1'
    request_path = revision / handoff['request_path']
    response_path = revision / handoff['response_path']
    response['schema_version'] = request['schema_version']
    callback = reviewer_command(tmp_path, response)
    callback([handoff], 10, revision, {})
    accepted = json.loads(response_path.read_text())
    assert accepted['schema_version'] == quality.RESPONSE_SCHEMA
    assert accepted['page_assessments'] == response['page_assessments']
    assert accepted['producer'] == response['producer']
    assert accepted['workflow_binding']['normalized_fields'] == ['schema_version']
    assert quality.verification_response_is_terminal(revision, request_path)
    diagnostics = list((tmp_path / 'logs/parent-visual-reviewer').glob('*.json'))
    assert json.loads(json.loads(diagnostics[0].read_text())['stdout']) == response
    parent_request = json.loads((revision / 'hermes/desktop-parent-visual-review-request.json').read_text())
    assert parent_request['response_schema_version'] == quality.RESPONSE_SCHEMA
    assert parent_request['managed_hermes_identity'] == synthetic_managed_hermes_identity


@pytest.mark.parametrize('defect', [
    'unknown-schema', 'request-id', 'hash', 'revision', 'task',
    'missing-revision', 'missing-page', 'stale-page',
])
def test_normalization_does_not_accept_foreign_or_incomplete_review(tmp_path, defect):
    handoff, request, response = _visual_handoff_fixture(tmp_path, 'protocol')
    revision = tmp_path / 'revisions/r1'
    response['schema_version'] = request['schema_version']
    identity_defects = {'unknown-schema': 'schema_version', 'request-id': 'request_id',
                       'hash': 'request_sha256', 'revision': 'revision_id', 'task': 'task'}
    if defect in identity_defects:
        response[identity_defects[defect]] = 'foreign-value'
    elif defect == 'missing-revision':
        response.pop('revision_id')
    elif defect == 'missing-page':
        response['page_assessments'] = []
    else:
        response['page_assessments'][0]['sha256'] = '0' * 64
    with pytest.raises(RuntimeError, match='did not produce one bound terminal response'):
        reviewer_command(tmp_path, response)([handoff], 10, revision, {})
    assert not (revision / handoff['response_path']).exists()


def test_schema_normalization_retains_a_real_visual_blocker(tmp_path):
    handoff, request, response = _visual_handoff_fixture(tmp_path, 'protocol')
    revision = tmp_path / 'revisions/r1'
    response['schema_version'] = request['schema_version']
    response['status'] = response['page_assessments'][0]['status'] = 'blocked'
    response['findings'] = [{'artifact': 'protocol', 'page': 1, 'check': 'bad_table_split',
                             'element': 'Study procedures', 'issue': 'The table label is separated from its first row.'}]
    reviewer_command(tmp_path, response)([handoff], 10, revision, {})
    accepted = json.loads((revision / handoff['response_path']).read_text())
    assert accepted['status'] == 'blocked'
    assert accepted['findings'] == response['findings']
    assert quality.verification_response_is_terminal(revision, revision / handoff['request_path'])
    assert not quality.verification_response_is_complete(revision, revision / handoff['request_path'])
