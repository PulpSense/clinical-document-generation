"""Malformed outer containers are not independent nested review responses."""
import json
import shlex

import pytest

import workflow
from test_desktop_delivery import _visual_handoff_fixture
from test_reviewer_transport import synthetic_managed_hermes_identity


@pytest.mark.parametrize('container', ['object', 'array', 'quoted'])
def test_public_parent_does_not_salvage_nested_final_from_malformed_outer(tmp_path, container):
    handoff, _, response = _visual_handoff_fixture(tmp_path, 'protocol')
    revision = tmp_path / 'revisions/r1'
    encoded = json.dumps(response)
    output = ('{"wrapper":' + encoded if container == 'object' else
              '[' + encoded if container == 'array' else json.dumps(encoded))
    command = tmp_path / 'callback'
    command.write_text('#!/bin/sh\nprintf "%s\\n" ' + shlex.quote(output) + '\n')
    command.chmod(0o755)
    with pytest.raises(RuntimeError):
        workflow.command_parent_visual_reviewer(command)([handoff], 10, revision, {})
    assert not (revision / handoff['response_path']).exists()


@pytest.mark.parametrize('parallel', [False, True])
def test_public_production_does_not_adopt_nested_malformed_final(tmp_path, monkeypatch, parallel):
    import ast
    import subprocess
    from test_production_visual_incomplete import test_production_missing_visual_scope_reaches_only_safe_fallback as exercise
    real = subprocess.Popen
    altered = []
    def launch(command, **options):
        if isinstance(command, list) and '-c' in command:
            command = list(command)
            index = command.index('-c') + 1
            tree = ast.parse(command[index])
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id == 'print' and node.args
                        and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[0].value, str)):
                    try:
                        payload = json.loads(node.args[0].value)
                    except ValueError:
                        continue
                    if isinstance(payload, dict) and 'visual_assessments' in payload:
                        node.args[0] = ast.Constant('{"wrapper":' + node.args[0].value)
                        altered.append(payload['request_id'])
            command[index] = ast.unparse(ast.fix_missing_locations(tree))
        return real(command, **options)
    monkeypatch.setattr(subprocess, 'Popen', launch)
    try:
        exercise(tmp_path, monkeypatch, parallel, 'valid_stdout')
    except AssertionError:
        # The reused positive harness expects adoption, deliberately changed by
        # this controlled stdout corruption. Assert the actual boundary below.
        if not (tmp_path / 'observation.json').exists():
            raise
    result = json.loads((tmp_path / 'observation.json').read_text())
    assert altered and set(result['returncodes']) == {0}
    assert result['callback_count'] > 0, 'Malformed outer stdout must not complete ordinary review'
    assert result['retained_assessments'] == 1
    assert result['result_stage'] == 'synthetic_probe_done'
    assert result['client_outputs'] == []
