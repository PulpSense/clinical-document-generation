"""Wave boundaries must reject real strict provisioned PDFium mutations."""
import os
import shutil
import sys
from pathlib import Path

import pytest
import workflow


@pytest.mark.parametrize('when', ['before', 'during'])
@pytest.mark.parametrize('mutation', ['changed', 'added-cache', 'missing', 'symlink'])
@pytest.mark.parametrize('host_mode', ['isolated', 'hermes-tui'])
def test_provisioned_runtime_is_checked_at_worker_wave_boundaries(tmp_path, governed_pdfium, monkeypatch, when, mutation, host_mode):
    assert workflow._pdfium_runtime_integrity(tmp_path)['status'] == 'passed'
    runtime = tmp_path / 'runtime/python'
    target = next(runtime.rglob('*.py'))
    def mutate():
        if mutation == 'changed':
            target.write_bytes(target.read_bytes() + b'\n# unauthorized change\n')
        elif mutation == 'added-cache':
            cache = runtime / '__pycache__/unexpected.pyc'
            cache.parent.mkdir()
            cache.write_bytes(b'unexpected cache')
        elif mutation == 'missing':
            shutil.rmtree(runtime)
        else:
            target.rename(target.with_suffix('.saved'))
            target.symlink_to(target.with_suffix('.saved'))
    if when == 'before':
        mutate()
    monkeypatch.setattr(workflow, '_manifest_integrity', lambda *a, **k: [])
    monkeypatch.setattr(workflow, '_managed_hermes_pair', lambda: (tmp_path / 'bin/hermes', Path(sys.executable)))
    def environment(_):
        if when == 'during':
            mutate()
        return {**os.environ, 'HERMES_HOME': str(tmp_path / 'home')}
    monkeypatch.setattr(workflow, '_production_subprocess_environment', environment)
    with pytest.raises(RuntimeError, match='runtime integrity|runtime changed'):
        workflow._production_dispatch_handoffs([], 10, tmp_path / 'run/revisions/r1', {},
            skill_root=tmp_path, run_dir=tmp_path / 'run', runtime_identity={'executable': sys.executable},
            host_mode=host_mode)
