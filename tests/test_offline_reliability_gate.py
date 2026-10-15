import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
import pytest
import offline_reliability_gate as gate




def test_release_check_is_explicit_and_excludes_live_suites():
    command = gate.test_command('python')
    assert command[:3] == ['python', '-m', 'pytest']
    assert len(gate.TEST_FILES) < len(list((gate.ROOT / 'tests').glob('test_*.py')))
    assert all((gate.ROOT / 'tests' / filename).is_file() for filename in gate.TEST_FILES)
    assert {'test_ai_quality_boundary.py', 'test_ai_review_handoff.py',
            'test_general_document_repair.py', 'test_ai_delivery_outcomes.py'} <= set(gate.TEST_FILES)
    assert {'test_content_review_recovery.py', 'test_review_scheduler.py'} <= set(gate.TEST_FILES)
    assert {'test_observer_clean_partial.py', 'test_production_visual_transport.py',
            'test_production_visual_incomplete.py'} <= set(gate.TEST_FILES)
    assert 'test_review_resolutions.py' not in gate.TEST_FILES
    assert 'test_hypothesis_fidelity.py' not in gate.TEST_FILES
    assert not any('e2e' in node or 'certification' in node or 'corpus' in node for node in command)










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
