#!/usr/bin/env python3
"""Unpaid installed Linux/TUI probes. Never certifies clinical quality or delivery."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import uuid


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def collect(workflow, root, evidence):
    if evidence.resolve().is_relative_to(root.resolve()):
        raise ValueError('Evidence must remain outside installed code')
    evidence.mkdir(parents=True)  # Never overwrite evidence from an earlier host.
    report = {'schema_version': 'hermes-tui-host-checks/v1', 'status': 'blocked',
              'host_mode': 'hermes-tui', 'checks': {}, 'recipient_delivery_verified': False,
              'os_isolation_verified': False, 'paid_model_calls': 0,
              'limitations': 'Tool/runtime checks only. Actual model launch, page interpretation, clinical quality and repair acceptance require the synthetic campaign.'}
    process = None
    stdout = stderr = None
    try:
        if platform.system() != 'Linux':
            raise ValueError('Run host checks on the actual Linux Hermes host')
        if evidence.resolve().is_relative_to(root.resolve()):
            raise ValueError('Evidence must remain outside installed code')
        identity = workflow._installed_release_identity(root)
        before = workflow._worker_capability_identity(root)
        report['candidate_identity'] = {**identity,
            'package_manifest_sha256': hashlib.sha256((root / workflow.RELEASE_MANIFEST).read_bytes()).hexdigest(),
            'installed_worker_identity': before}
        readiness = workflow._production_worker_readiness(root, host_mode='hermes-tui')
        report['checks']['profile_login_and_installed_read_tool'] = readiness
        if readiness['status'] != 'passed':
            raise RuntimeError(readiness.get('issue') or 'Hermes profile/read tool unavailable')
        environment = workflow._production_subprocess_environment(root)
        launcher, interpreter = workflow._managed_hermes_pair()
        runtime = workflow.resolve_python_runtime(environment=os.environ)
        checkpoint = workflow._prepare_worker_checkpoint(evidence, 'checkpoint.json')
        nonce = uuid.uuid4().hex
        source = evidence / 'bounded-evidence.txt'
        source.write_text(''.join(f'{i:04d} {nonce} approved passage\n' for i in range(2048)))
        native = evidence / 'native'
        native.mkdir()
        # This uses the installed file tools and the same explicit Python/env as
        # workers. No model, namespace, protected-write or recipient claim.
        native_code = """from docx import Document
from lxml import etree as E
from pathlib import Path
import sys
p=Path(sys.argv[1]); d=Document(); d.add_paragraph('Before native repair'); d.add_table(rows=1,cols=2).cell(0,0).text='Visit'; d.save(p/'probe.docx')
E.ElementTree(E.Element('probe', value='before')).write(str(p/'probe.xml'))
"""
        script = """import json,subprocess,sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from tools.file_tools import read_file_tool,write_file_tool
source,checkpoint,native,nonce,runtime,code=sys.argv[2:]
for start in range(1,2049,128):
 value=read_file_tool(source,offset=start,limit=128)
 for i in range(start-1,start+127): assert f'{i:04d} {nonce}' in value
write_file_tool(checkpoint,json.dumps({'nonce':nonce,'completed_lines':2048}))
assert nonce in read_file_tool(checkpoint,offset=1,limit=20)
tool=Path(native)/'native-probe.py'; write_file_tool(str(tool),code)
subprocess.run([runtime,'-B',str(tool),native],check=True)
child=subprocess.Popen([runtime,'-B','-c','import time;time.sleep(600)',nonce])
print(json.dumps({'status':'passed','child_pid':child.pid,'bounded_read_calls':16,'checkpoint_readback':True}),flush=True)
time.sleep(600)
"""
        stdout = (evidence / 'tools.stdout.log').open('x')
        stderr = (evidence / 'tools.stderr.log').open('x')
        process = subprocess.Popen([str(interpreter), '-B', '-c', script,
            str(launcher.parent.parent.parent), str(source), str(checkpoint), str(native),
            nonce, runtime['executable'], native_code], cwd=evidence, env=environment,
            stdout=stdout, stderr=stderr, text=True, start_new_session=True)
        deadline = time.monotonic() + 45
        result = None
        while time.monotonic() < deadline:
            lines = (evidence / 'tools.stdout.log').read_text().splitlines()
            for line in reversed(lines):
                try:
                    value = json.loads(line)
                    if isinstance(value, dict) and value.get('status') == 'passed':
                        result = value
                        break
                except ValueError:
                    continue
            if result or process.poll() is not None:
                break
            time.sleep(.1)
        if result is None:
            raise RuntimeError('Installed tool/checkpoint/native subprocess failed; see retained stdout/stderr')
        report['checks']['bounded_reads_checkpoint_and_native_tools'] = result
        workflow._reap_production_worker(process, stdout, stderr, None, None)
        process = None
        child_stat = Path('/proc') / str(result['child_pid']) / 'stat'
        child_alive = child_stat.exists() and child_stat.read_text().split(') ', 1)[1][0] != 'Z'
        if child_alive:
            raise RuntimeError('Worker descendant survived process-group cleanup')
        report['checks']['worker_descendant_cleanup'] = {'status': 'passed'}
        # Render actual native bytes, repair using a real subprocess, then render
        # fresh bytes again. Strict inventories run before/after both exports.
        for label in ('before', 'after'):
            revision = evidence / label
            candidate = revision / 'candidate'
            candidate.mkdir(parents=True)
            if label == 'after':
                repair = "from docx import Document; from lxml import etree as E; import sys; from pathlib import Path; p=Path(sys.argv[1]); d=Document(p/'probe.docx'); d.paragraphs[0].text='After native repair'; d.save(p/'probe.docx'); t=E.parse(str(p/'probe.xml')); t.getroot().set('value','after'); t.write(str(p/'probe.xml'))"
                subprocess.run([runtime['executable'], '-B', '-c', repair, str(native)],
                    check=True, capture_output=True, text=True, timeout=30, env=environment)
            path = candidate / 'probe.docx'
            path.write_bytes((native / 'probe.docx').read_bytes())
            assurance = workflow.render_assurance(root, revision,
                {'meta': {'study_type': 'Prospective', 'icf_template': 'Advarra'}},
                structural_validation={'status': 'structurally_valid', 'expected_files': [path.name],
                    'candidate_files': [{'path': 'candidate/probe.docx',
                        'sha256': workflow.sha256_file(path), 'bytes': path.stat().st_size}]},
                deadline_seconds=120, require_promoted_runtime=False)
            write(revision / 'render-assurance.json', assurance)
            report['checks']['render_' + label + '_native_repair'] = {'status': assurance['status'],
                'native_sha256': workflow.sha256_file(path)}
            if assurance['status'] != 'passed':
                raise RuntimeError(f'{label} repair rendering blocked; see render-assurance.json')
            pages = list(revision.rglob('*.png'))
            if not pages or any(p.read_bytes()[:8] != b'\x89PNG\r\n\x1a\n' for p in pages):
                raise RuntimeError('Rendered page images missing or unreadable')
            report['checks']['render_' + label + '_native_repair']['page_images'] = len(pages)
            if workflow._worker_capability_identity(root) != before:
                raise RuntimeError('Installed runtime changed after native tool use or rendering')
        if report['checks']['render_before_native_repair']['native_sha256'] == report['checks']['render_after_native_repair']['native_sha256']:
            raise RuntimeError('Native repair did not change the rendered input')
        reply = workflow.local_output_reader(evidence)(str(native / 'probe.docx'))
        if reply != (native / 'probe.docx').read_bytes():
            raise RuntimeError('Local output bytes differ')
        report['checks']['local_exact_bytes'] = {'status': 'passed'}
        report['status'] = 'passed'
    except Exception as exc:
        report['issue'] = str(exc)
    finally:
        if process is not None:
            try:
                workflow._reap_production_worker(process, stdout, stderr, None, None)
            except Exception as exc:
                report['status'] = 'blocked'
                report['cleanup_issue'] = str(exc)
        report['evidence_inventory'] = {str(path.relative_to(evidence)): {
            'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in sorted(evidence.rglob('*')) if path.is_file() and not path.is_symlink()}
        write(evidence / 'host-checks.json', report)
        if report['status'] == 'passed':
            write(evidence / 'candidate-identity.json', report['candidate_identity'])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release-root', type=Path, required=True)
    parser.add_argument('--evidence-root', type=Path, required=True)
    args = parser.parse_args()
    root = args.release_root.absolute()
    from tui_campaign_contract import load_installed_workflow
    workflow = load_installed_workflow(root)
    report = collect(workflow, root, args.evidence_root.absolute())
    print(json.dumps(report, indent=2))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
