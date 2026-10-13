"""Explicit clinical interpreter binding, without modifying host settings."""
import os
from pathlib import Path
import subprocess

import pytest
import workflow


@pytest.mark.skipif(not Path('/opt/data/clinical-document-runtime/bin/python').is_file(), reason='host runtime probe')
def test_clinical_runtime_wins_over_managed_hermes_runtime():
    clinical = '/opt/data/clinical-document-runtime/bin/python'
    runtime = workflow.resolve_python_runtime(environment={
        **os.environ, 'CLINICAL_PYTHON': clinical, 'HERMES_PYTHON': '/opt/hermes/.venv/bin/python'})
    assert runtime['executable'] == clinical
    completed = subprocess.run([runtime['executable'], '-B', '-c',
        'from docx import Document; from lxml import etree; print("native imports passed")'],
        capture_output=True, text=True, timeout=5, check=True)
    assert completed.stdout.strip() == 'native imports passed'


def test_invalid_explicit_clinical_runtime_does_not_silently_select_other_python(tmp_path):
    with pytest.raises(RuntimeError, match='No supported Python'):
        workflow.resolve_python_runtime(environment={**os.environ, 'CLINICAL_PYTHON': str(tmp_path / 'missing')})
