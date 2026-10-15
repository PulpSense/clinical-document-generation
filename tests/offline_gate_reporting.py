"""Pytest-side disjoint selection and crash-surviving evidence checkpoints."""
import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET

from offline_reliability_gate import shard_ids


def atomic_text(path, text):
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(text, encoding='utf-8')
    temporary.replace(path)


def write_junit(path, reports):
    suite = ET.Element('testsuite', name='offline-focused')
    for nodeid, phases in reports.items():
        case = ET.SubElement(suite, 'testcase', name=nodeid,
                             time=str(sum(p['duration'] for p in phases)))
        if phases[-1]['when'] != 'teardown' and all(p['outcome'] == 'passed' for p in phases):
            ET.SubElement(case, 'error', type='incomplete', message='Case has not finished teardown')
        for phase in phases:
            if phase['outcome'] in ('failed', 'skipped'):
                tag = 'skipped' if phase['outcome'] == 'skipped' else (
                    'failure' if phase['when'] == 'call' else 'error')
                ET.SubElement(case, tag, message=phase['when']).text = phase['detail']
    suite.set('tests', str(len(suite)))
    for tag, attribute in [('failure', 'failures'), ('error', 'errors'), ('skipped', 'skipped')]:
        suite.set(attribute, str(len(suite.findall('.//' + tag))))
    atomic_text(path, ET.tostring(suite, encoding='unicode') + '\n')


class Evidence:
    def __init__(self, config):
        self.path = Path(config['path'])
        self.index, self.count = config['index'], config['count']
        self.manifest = {'index': self.index, 'count': self.count,
                         'all': [], 'selected': [], 'completed': []}
        self.reports = {}
        self.save()

    def save(self):
        atomic_text(self.path.with_suffix('.cases.json'), json.dumps(self.manifest, indent=2) + '\n')
        write_junit(self.path.with_suffix('.xml'), self.reports)

    def pytest_collection_modifyitems(self, session, config, items):
        nodeids = [item.nodeid for item in items]
        selected = shard_ids(nodeids, self.index, self.count)
        self.manifest.update(all=sorted(nodeids), selected=selected)
        selected_set = set(selected)
        removed = [item for item in items if item.nodeid not in selected_set]
        items[:] = sorted((item for item in items if item.nodeid in selected_set), key=lambda item: item.nodeid)
        config.hook.pytest_deselected(items=removed)
        self.save()

    def pytest_runtest_logreport(self, report):
        self.reports.setdefault(report.nodeid, []).append({
            'when': report.when, 'outcome': report.outcome,
            'duration': getattr(report, 'duration', 0), 'detail': str(report.longrepr) if report.longrepr else ''})
        if report.when == 'teardown':
            self.manifest['completed'].append(report.nodeid)
        self.save()
        if report.failed:
            print(f'\nFAILURE {report.nodeid} ({report.when})\n{report.longrepr}', flush=True)

    def pytest_collectreport(self, report):
        if report.failed:
            self.pytest_runtest_logreport(report)


def pytest_configure(config):
    settings = os.environ.get('OFFLINE_GATE_EVIDENCE')
    if settings:
        config.pluginmanager.register(Evidence(json.loads(settings)), 'offline-gate-evidence')
