"""Ordinary Linux worker isolation and its sole provider transport bridge.

Bubblewrap is an existing Linux host prerequisite. No provisioning happens here.
The worker has a private network/PID namespace and a read-only filesystem;
only explicit audit/native work areas and private runtime state are writable.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import select
import socket
import socketserver
import subprocess
import sys
import threading


def linux_prefix(policy_path: Path) -> list[str]:
    policy = json.loads(policy_path.read_text())
    executable = next((str(p) for p in (Path('/usr/bin/bwrap'), Path('/bin/bwrap'))
                       if p.is_file() and not p.is_symlink()), None)
    if not executable:
        raise RuntimeError('Ordinary Linux workers require the existing Bubblewrap host prerequisite; verify installation and user namespace permission before admission.')
    path = Path(executable)
    if not path.is_absolute() or path.is_symlink() or not path.is_file() or not os.access(path, os.X_OK):
        raise RuntimeError('The Linux Bubblewrap executable is not a trusted executable file.')
    command = [str(path), '--die-with-parent', '--unshare-all', '--new-session',
               '--ro-bind', '/', '/', '--proc', '/proc', '--dev', '/dev']
    for hidden in ('/tmp', '/run', '/home', '/root'):
        if Path(hidden).is_dir():
            command += ['--tmpfs', hidden]
    for area in dict.fromkeys([str(Path(__file__).resolve().parents[1]), *policy['readable']]):
        command += ['--ro-bind', area, area]
    for area in policy['writable']:
        command += ['--bind', area, area]
    # Bind exact files after runtime directories, so credentials/code stay read-only.
    for area in policy['protected']:
        command += ['--ro-bind', area, area]
    command += ['--ro-bind', policy['proxy_socket'], policy['proxy_socket'],
                '--chdir', policy['cwd'], '--', sys.executable, str(Path(__file__).resolve()),
                policy['proxy_socket'], str(policy['proxy_port']), '--']
    return command


class Bridge(socketserver.BaseRequestHandler):
    def handle(self):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as upstream:
            upstream.connect(self.server.proxy_socket)
            peers = (self.request, upstream)
            while True:
                readable, _, _ = select.select(peers, (), (), 1)
                for source in readable:
                    payload = source.recv(65536)
                    if not payload:
                        return
                    (upstream if source is self.request else self.request).sendall(payload)


class BridgeServer(socketserver.ThreadingTCPServer):
    daemon_threads = True


def main():
    proxy_socket, port, separator, *command = sys.argv[1:]
    if separator != '--' or not command:
        raise ValueError('Missing isolated worker command.')
    with BridgeServer(('127.0.0.1', int(port)), Bridge) as server:
        server.proxy_socket = proxy_socket
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return subprocess.call(command)


if __name__ == '__main__':
    raise SystemExit(main())
