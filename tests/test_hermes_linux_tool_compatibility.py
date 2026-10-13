"""Bounded host/tool regressions; no model calls or clinical approval claims."""
import json
import os
import platform
from pathlib import Path

import pytest
import workflow
import hermes_tui_host_checks as host_checks


def test_installed_tools_write_precreated_checkpoint_after_read(tmp_path, monkeypatch):
    if platform.system() != 'Linux' or not Path('/opt/hermes/.venv/bin/hermes').is_file():
        pytest.skip('Requires the actual managed Linux Hermes tools')
    root = tmp_path / 'profile/skills/clinical-document-generation'
    root.mkdir(parents=True)
    (root / workflow.RELEASE_MANIFEST).write_text('{}')
    monkeypatch.setattr(workflow, '_installed_release_identity', lambda _: {'package_fingerprint': 'test'})
    monkeypatch.setattr(workflow, '_worker_capability_identity', lambda _: {'test': 'identity'})
    monkeypatch.setattr(workflow, '_production_worker_readiness', lambda *a, **k: {'status': 'passed'})
    monkeypatch.setattr(workflow, '_production_subprocess_environment', lambda _: {
        **os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
    monkeypatch.setenv('CLINICAL_PYTHON', '/opt/data/clinical-document-runtime/bin/python')
    monkeypatch.setenv('HERMES_PYTHON', '/opt/hermes/.venv/bin/python')
    # Stop at the rendering seam: this test exercises only real file tools,
    # native subprocess execution and worker-descendant cleanup.
    monkeypatch.setattr(workflow, 'render_assurance', lambda *a, **k: {'status': 'blocked'})
    evidence = tmp_path / 'evidence'
    report = host_checks.collect(workflow, root, evidence)
    assert 'bounded_reads_checkpoint_and_native_tools' in report['checks'], report
    result = report['checks']['bounded_reads_checkpoint_and_native_tools']
    assert result['checkpoint_readback'] is True
    assert result['bounded_read_calls'] == 16
    assert report['checks']['worker_descendant_cleanup']['status'] == 'passed'
    checkpoint = json.loads((evidence / 'checkpoint.json').read_text())
    assert checkpoint['completed_lines'] == 2048
    assert checkpoint['nonce'] in (evidence / 'bounded-evidence.txt').read_text()
    assert report['status'] == 'blocked'  # No fake rendering or visual pass.
    assert report['paid_model_calls'] == 0
    assert report['recipient_delivery_verified'] is False


def test_reviewer_prompt_requires_current_checkpoint_read_before_overwrite(tmp_path):
    root = tmp_path / 'skill'
    revision = tmp_path / 'run/revisions/r1'
    request = revision / 'hermes/request.json'
    request.parent.mkdir(parents=True)
    request.write_text(json.dumps({'review_transport': {
        'index_path': 'hermes/index.json', 'progress_path': 'hermes/progress.json'}}))
    prompt = workflow._production_agent_prompt(root, revision, {
        'task': 'clinical_content_verification', 'request_path': 'hermes/request.json',
        'response_path': 'hermes/response.json'}, {}, workspace_root=tmp_path / 'run')
    assert 'Before each checkpoint overwrite, read its full current contents with read_file' in prompt
    assert 'check the write_file result' in prompt
    assert 'only writable review file' in prompt
    assert 'Do not call write_file, patch, or terminal to publish the response' in prompt
