"""Actual public packaging must ship both owned observer dependencies."""
import hashlib
import json
from pathlib import Path
import zipfile
import io
import shutil
import subprocess
import tarfile
import workflow


def test_public_release_packages_owned_observer_dependencies(tmp_path):
    checkout = Path(workflow.__file__).resolve().parents[1]
    root = tmp_path / 'fixture'
    root.mkdir()
    payload = subprocess.check_output(['git', '-C', str(checkout), 'archive', 'HEAD'])
    with tarfile.open(fileobj=io.BytesIO(payload)) as committed:
        committed.extractall(root, filter='data')
    # Commit current packaging implementation into an isolated actual Git fixture.
    shutil.copy2(checkout / 'scripts/workflow.py', root / 'scripts/workflow.py')
    def git(*args):
        subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True)
    git('init')
    git('add', '.')
    git('-c', 'user.name=Unpaid test fixture', '-c', 'user.email=fixture@example.invalid',
        'commit', '-m', 'Unpaid packaging regression fixture')
    archive = tmp_path / 'candidate.zip'
    workflow.package_release(root, archive)
    with zipfile.ZipFile(archive) as bundle:
        manifest = json.loads(bundle.read('clinical-document-generation/RELEASE-MANIFEST.json'))
        files = {row['path']: row for row in manifest['files']}
        for name in ('owned_observer_process.py', 'owned_observer_runtime.py'):
            path = 'scripts/' + name
            assert path in manifest['inventory']['implementation']
            payload = bundle.read('clinical-document-generation/' + path)
            assert payload == (root / path).read_bytes()
            assert hashlib.sha256(payload).hexdigest() == files[path]['sha256']
