"""Public subprocess recovery report transport; deterministic unpaid callbacks."""
import json
import shlex
import sys

import pytest

import workflow
from test_desktop_delivery import _visual_handoff_fixture
from test_reviewer_transport import synthetic_managed_hermes_identity, reviewer_command
from visual_review import IncompleteVisualReview


def invoke(tmp_path, fault=None):
    handoff, request, response = _visual_handoff_fixture(tmp_path, 'protocol')
    revision = tmp_path / 'revisions/r1'
    script = tmp_path / 'controlled-callback.py'
    (tmp_path / 'response-fixture.json').write_text(json.dumps(response))
    if fault == 'approved-source':
        (revision / 'approved-reference.json').write_text('{"approved":true}')
    script.write_text('''import hashlib,json,sys
from pathlib import Path
path=Path(sys.argv[1]); fault=sys.argv[2]; envelope=json.loads(path.read_text())
report={'schema_version':'tui-visual-callback-recovery/v1',
'outcome':'incomplete_authenticated_visual_scope','exit_code':75,
'invocation_path':str(path),'invocation_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
'revision_id':envelope['revision_id'],'revision_path':envelope['revision_path'],
'managed_hermes_identity':envelope['managed_hermes_identity'],
'callback_release_binding':envelope.get('callback_release_binding'),
'callback_command':envelope.get('callback_command'),'handoffs':envelope['handoffs'],
'missing_target_ids':['protocol:document'],'validation_feedback':[],
'dispatch_errors':['Controlled safely incomplete observer']}
if fault=='hash': report['invocation_sha256']='0'*64
if fault=='revision': report['revision_id']='foreign'
if fault=='runtime': report['managed_hermes_identity']={'foreign':True}
if fault=='source': report['callback_release_binding']={'foreign':True}
if fault=='handoff': report['handoffs'][0]['request_id']='foreign'
if fault=='boolean-exit': report['exit_code']=True
out=path.with_suffix('.recovery.json')
if fault=='symlink':
 target=path.parent/'external-report.json'; target.write_text(json.dumps(report)); out.symlink_to(target)
elif fault!='missing': out.write_text(json.dumps(report))
if fault=='malformed': out.write_text('{"schema_version":')
if fault=='approved-source': (path.parent.parent.parent/'approved-reference.json').write_text('{"approved":false}')
if fault=='command-change': Path(sys.argv[3]).write_text('#!/bin/sh\\nexit 0\\n')
if fault in ('foreign-stdout','missing-stdout-identity','normal-foreign'):
 valid=json.loads((Path(__file__).parent/'response-fixture.json').read_text())
 invalid=dict(valid)
 if fault=='missing-stdout-identity': invalid.pop('request_sha256')
 else: invalid['request_id']='foreign-response'
 print(json.dumps(invalid)); print(json.dumps(valid))
sys.exit(0 if fault=='normal-foreign' else 1 if fault=='execution' else 75)
''')
    command = tmp_path / 'callback'
    command.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' -B ' +
        shlex.quote(str(script)) + ' "$1" ' + shlex.quote(fault or '') + ' ' + shlex.quote(str(command)) + '\n')
    command.chmod(0o700)
    callback = workflow.command_parent_visual_reviewer(command)
    callback([handoff], 10, revision, {})


def test_clean_bound_recovery_report_uses_typed_incomplete_not_generic_fatal(tmp_path):
    with pytest.raises(IncompleteVisualReview):
        invoke(tmp_path)
    diagnostics = list((tmp_path / 'logs/parent-visual-reviewer').glob('*.json'))
    assert len(diagnostics) == 1
    diagnostic = json.loads(diagnostics[0].read_text())
    assert diagnostic['returncode'] == 75
    assert diagnostic['cleanup_complete'] is True
    assert not diagnostic['cleanup_errors']
    assert not list((tmp_path / 'revisions/r1/hermes/verification-responses').glob('*.json'))


@pytest.mark.parametrize('fault', ['missing', 'malformed', 'hash', 'revision', 'runtime', 'source',
    'handoff', 'boolean-exit', 'symlink', 'execution', 'command-change', 'approved-source',
    'foreign-stdout', 'missing-stdout-identity', 'normal-foreign'])
def test_recovery_signal_does_not_demote_invalid_binding_or_execution(tmp_path, fault):
    with pytest.raises((RuntimeError, ValueError)) as caught:
        invoke(tmp_path, fault)
    assert not isinstance(caught.value, IncompleteVisualReview)


@pytest.mark.parametrize('enveloped', [False, True])
def test_parent_semantic_final_owns_its_reviewer_metadata(tmp_path, enveloped):
    handoff, _, response = _visual_handoff_fixture(tmp_path, 'protocol')
    revision = tmp_path / 'revisions/r1'
    response['producer']['metadata'] = {'task': 'audit', 'request_id': 'metadata-only',
        'findings': [{'request_sha256': 'metadata-only'}]}
    payload = {'data': {'responses': [response]}} if enveloped else response
    reviewer_command(tmp_path, payload)([handoff], 10, revision, {})
    accepted = json.loads((revision / handoff['response_path']).read_text())
    assert accepted['producer'] == response['producer']
    assert accepted['page_assessments'] == response['page_assessments']
