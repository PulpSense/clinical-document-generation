"""Harmless denial probes against the ordinary production Linux prefix."""
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

import pytest
import workflow


@pytest.mark.skipif(platform.system() != 'Linux', reason='Actual Linux kernel enforcement requires Linux')
@pytest.mark.parametrize('role', ['reviewer', 'repair_author'])
def test_ordinary_linux_worker_can_only_write_declared_audit_and_native_areas(tmp_path, role):
    workspace = tmp_path / 'study'
    workspace.mkdir()
    audit = workspace / 'audit.json'
    audit.touch()
    repair = workspace / 'native-work'
    repair.mkdir()
    protected = [workspace / name for name in ('source', 'installed-code', 'other-review', 'earlier-run')]
    for path in protected:
        path.write_text('sentinel')
    policy = tmp_path / 'policy.json'
    proxy_socket = tmp_path / 'proxy.sock'
    # Real provider proxy, exercised with a denied arbitrary route. No provider/model calls.
    proxy = workflow._start_production_connect_proxy(unix_path=proxy_socket)
    script = '''import json,socket,sys
from pathlib import Path
paths=json.loads(sys.argv[1]); audit=Path(sys.argv[2]); repair=Path(sys.argv[3])
assert all(Path(p).read_text()=='sentinel' for p in paths)
for p in paths:
 try: Path(p).write_text('marker')
 except OSError: pass
 else: raise AssertionError('protected write succeeded: '+p)
role=sys.argv[4]
if role=='reviewer':
 audit.write_text('checkpoint')
 try: (repair/'native-marker').write_text('marker')
 except OSError: pass
 else: raise AssertionError('Reviewer edited native work')
else:
 (repair/'native-marker').write_text('marker')
 try: audit.write_text('marker')
 except OSError: pass
 else: raise AssertionError('Repair author edited another audit')
try: socket.create_connection(('1.1.1.1',443),timeout=0.2)
except OSError: pass
else: raise AssertionError('direct network escape')
s=socket.create_connection(('127.0.0.1',3128)); s.sendall(b'CONNECT example.org:443 HTTP/1.1\\r\\n\\r\\n'); assert b'403' in s.recv(1024)
'''
    policy.write_text(json.dumps({'readable': [str(tmp_path)], 'writable': [str(audit)] if role == 'reviewer' else [str(repair)],
        'protected': [], 'proxy_socket': str(proxy_socket), 'proxy_port': proxy.port, 'cwd': str(workspace)}))
    try:
        prefix = workflow._production_sandbox_prefix(policy)
        result = subprocess.run([*prefix, sys.executable, '-c', script,
            json.dumps([str(p) for p in protected]), str(audit), str(repair), role],
            capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, result.stderr
    finally:
        proxy.close()
    assert audit.read_text() == ('checkpoint' if role == 'reviewer' else '')
    assert all(p.read_text() == 'sentinel' for p in protected)


def test_linux_worker_rejects_admission_without_boundary(tmp_path, monkeypatch):
    import worker_boundary
    policy = tmp_path / 'policy.json'
    policy.write_text('{}')
    monkeypatch.setattr(Path, 'is_file', lambda p: False if str(p).endswith('/bwrap') else True)
    with pytest.raises(RuntimeError, match='Bubblewrap'):
        worker_boundary.linux_prefix(policy)
