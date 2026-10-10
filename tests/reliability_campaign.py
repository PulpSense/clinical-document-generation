#!/usr/bin/env python3
"""Build a synthetic Hermes pilot and variations; measure every retained operation.

Developer tooling only. This does not invoke models, approve sources, run the
acceptance corpus, install a release, or certify clinical or visual correctness.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import workflow

STUDIES = Path(__file__).parent / 'fixtures/reliability-campaign/studies.json'


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def campaign_cases() -> list[dict[str, Any]]:
    cases = []
    for study in json.loads(STUDIES.read_text(encoding='utf-8')):
        for representation in ('narrative', 'structured'):
            reference = study_reference(study, representation)
            cases.append({
                'id': study['id'] + '-' + representation,
                'pair': study['id'], 'study_type': study['study_type'],
                'icf_template': study['icf_template'],
                'pilot': study['pilot'] and representation == 'narrative',
                'representation': representation, 'reference': reference,
                'oracle': study_expectations(study),
            })
    return cases


def study_reference(study: dict[str, Any], representation: str) -> dict[str, Any]:
    """Materialize authored synthetic facts, independently of production projections."""
    sites = [{
        'facility': {'name': f'Example Research Site {i}',
                     'address': f'{i} Example Way, Example City, GA 00000, United States',
                     'city': 'Example City', 'state': 'GA', 'postal_code': '00000', 'country': 'United States'},
        'contact': {'name': f'Casey Example {i}', 'phone': '+1 202-555-0101', 'email': f'site{i}@example.org'},
        'investigator': {'name': f'Jordan Example {i}', 'title': 'MD, Site Investigator'},
    } for i in range(1, study['sites'] + 1)]
    assessments = study.get('assessments') or ' '.join(
        f"At {v['visit']} ({v['timing']}): {'; '.join(v['procedures'])}." for v in study['visits'])
    prospective = study['study_type'] != 'Retrospective'
    procedures = {'assessments': assessments}
    if prospective:
        procedures['minimum_days_before_screening_without_participation'] = study['washout']
        procedures['visit_schedule'] = (
            [v['visit'] for v in study['visits']] if representation == 'narrative'
            else copy.deepcopy(study['visits']))
    reference = {
        'meta': {'study_type': study['study_type'], 'icf_template': study['icf_template'],
                 'protocol_number': 'SYN-' + study['id'].upper(), 'date': '10 Oct 2026'},
        'study': {'title': study['title'], 'short_title': study['short_title'],
                  'background': study['background'], 'hypothesis': study['hypothesis'],
                  'timeline': study['timeline'], **({'unmet_need': study['unmet_need']} if not prospective else {})},
        'objectives': {'primary': study['objective']},
        'design': {'study_design': study['study_type'] + ', observational study of routine care.',
                   'number_of_sites': study['sites'], 'intervention_name': study['short_title'],
                   'intervention_type': 'Other', 'control_arm': 'None'},
        'population': {'description': study['population'], 'sample_size': f"{study['sample']} participants" if prospective else f"{study['sample']} records",
                       'sample_justification': 'A descriptive convenience sample from the participating sites; no power calculation or inferential comparison is planned.',
                       'inclusion_criteria': [study['population']], 'exclusion_criteria': [study['exclusion']]},
        'endpoints': {'primary': [{'label': study['primary'][0], 'time_frame': study['primary'][1]}],
                      'secondary': [{'label': e[0], 'time_frame': e[1]} for e in study['secondary']]},
        'procedures': procedures, 'statistics': {'analysis_plan': study['analysis']},
        'parties': {'sponsor': {'name': 'Example Synthetic Research Group', 'address': '100 Example Way, Example City, GA 00000, United States'},
                    'principal_investigator': {'name': 'Jordan Example', 'title': 'MD, Principal Investigator'},
                    'study_coordinator': {'name': 'Casey Example', 'title': 'Study Coordinator', 'business_phone': '+1 202-555-0101', 'office_phone': '+1 202-555-0101', 'email': 'coordinator@example.org'},
                    'irb': {'name': 'Example Research Ethics Board', 'affiliation': 'Independent synthetic board',
                            'phone': '+1 202-555-0103', 'email': 'ethics@example.org',
                            'address': '200 Example Way, Example City, GA 00000, United States',
                            'status': 'Not submitted; no approval, exemption or consent waiver has been granted.'}},
        'sites': sites, 'confidentiality': {'data_handling': study['privacy']},
        'risks_benefits': {'compensation_or_reimbursement': study['compensation']},
        **({'regulatory': {'prs': {'study_type': 'Observational'}}} if prospective else {}),
    }
    return reference


def study_expectations(study: dict[str, Any]) -> dict[str, Any]:
    """Literal study expectations are shared by equivalent input representations."""
    prospective = study['study_type'] != 'Retrospective'
    facts = [
        {'id': 'objective', 'meaning': study['objective'], 'artifacts': ['protocol.docx'] + (['icf.docx', 'study.xml'] if prospective else [])},
        {'id': 'population', 'meaning': study['population'], 'artifacts': ['protocol.docx'] + (['icf.docx', 'study.xml'] if prospective else [])},
        {'id': 'exclusions', 'meaning': study['exclusion'], 'artifacts': ['protocol.docx'] + (['study.xml'] if prospective else [])},
        {'id': 'sample-and-sites', 'meaning': f"{study['sample']} {'participants' if prospective else 'records'} across {study['sites']} sites", 'artifacts': ['protocol.docx'] + (['icf.docx', 'study.xml'] if prospective else [])},
        {'id': 'endpoint-timing', 'meaning': {'primary': study['primary'], 'secondary': study['secondary']}, 'artifacts': ['protocol.docx'] + (['study.xml'] if prospective else [])},
        {'id': 'analysis', 'meaning': study['analysis'], 'artifacts': ['protocol.docx']},
        {'id': 'timeline', 'meaning': study['timeline'], 'artifacts': ['protocol.docx'] + (['icf.docx'] if prospective else [])},
        {'id': 'qualified-benefit', 'meaning': study['background'], 'artifacts': ['protocol.docx'] + (['icf.docx'] if prospective else [])},
    ]
    if prospective:
        facts.extend([
            {'id': 'schedule', 'meaning': study['visits'], 'artifacts': ['protocol.docx', 'icf.docx']},
            {'id': 'eligibility-interval', 'meaning': f"At least {study['washout']} days without participation in another study before screening", 'artifacts': ['protocol.docx', 'icf.docx', 'study.xml']},
            {'id': 'compensation', 'meaning': study['compensation'], 'artifacts': ['protocol.docx', 'icf.docx']},
        ])
    else:
        facts.append({'id': 'record-review-only', 'meaning': study['assessments'], 'artifacts': ['protocol.docx']})
    if study['privacy']:
        facts.append({'id': 'privacy', 'meaning': study['privacy'], 'artifacts': ['protocol.docx'] + (['icf.docx'] if prospective else [])})
    return {'required_facts': facts, 'forbidden_claims': study['forbidden'],
            'document_set': ['protocol.docx', 'icf.docx', 'study.xml'] if prospective else ['protocol.docx']}


def raw_packet(case: dict[str, Any]) -> str:
    source = case['reference']
    lines = ['# SYNTHETIC STUDY INPUT — testing only', '',
             'All people, facilities and oversight details below are fictional. No real IRB approval is asserted.', '']
    sections = list(source.items())
    if case['representation'] == 'structured':
        sections.reverse()
    for name, value in sections:
        lines.extend(['## ' + name.replace('_', ' ').title(), ''])
        if name == 'procedures' and case['representation'] == 'structured' and value.get('visit_schedule'):
            lines.extend(['| Visit | Timing | Activities |', '| --- | --- | --- |'])
            for v in value['visit_schedule']:
                lines.append(f"| {v['visit']} | {v['timing']} | {'; '.join(v['procedures'])} |")
            value = {k: v for k, v in value.items() if k not in {'assessments', 'visit_schedule'}}
        lines.extend(human_fields(value))
        lines.append('')
    return '\n'.join(lines)


def human_fields(value: Any, prefix: str = '') -> list[str]:
    """Render source facts for an ordinary intake, without internal JSON syntax."""
    if isinstance(value, dict):
        return [line for key, item in value.items()
                for line in human_fields(item, prefix + key.replace('_', ' ').title() + ' / ')]
    if isinstance(value, list):
        return [line for index, item in enumerate(value, 1)
                for line in human_fields(item, prefix + str(index) + ' / ')]
    return [f"{prefix.removesuffix(' / ')}: {value if value is not None else 'Not applicable'}"]


def confined_file(root: Path, relative: str) -> Path:
    path = root / relative
    if Path(relative).is_absolute() or '..' in Path(relative).parts:
        raise ValueError(f'Unsafe evidence path: {relative}')
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError(f'Symlinked evidence path: {path}')
    path.resolve().relative_to(root.resolve())
    if not path.is_file():
        raise ValueError(f'Missing evidence file: {path}')
    return path


def verified_delivery(run: Path, result: dict, expected: list[str]) -> dict[str, str]:
    """Verify reported delivery bytes; this does not assess clinical correctness."""
    delivery = result.get('delivery', {})
    if not isinstance(delivery, dict):
        raise ValueError('Delivery metadata must be an object')
    if result.get('status') != 'passed' or delivery.get('confirmed') is not True:
        return {}
    manifest = json.loads(confined_file(run, result['manifest']).read_text())
    if not isinstance(manifest, dict):
        raise ValueError('Publication manifest must be an object')
    quality = manifest.get('quality', {})
    if not isinstance(quality, dict):
        raise ValueError('Publication quality must be an object')
    if manifest.get('status') != 'passed' or quality.get('status') != 'passed':
        raise ValueError('Reported delivery has no passing publication manifest')
    outputs = manifest['client_outputs']
    if (sorted(row['path'] for row in outputs) != sorted('output/' + name for name in expected)
            or sorted(result['client_outputs']) != sorted(row['path'] for row in outputs)
            or sorted(p.name for p in (run / 'output').iterdir()) != sorted(expected)):
        raise ValueError('Reported delivery does not have the exact contracted document set')
    hashes = {}
    for row in outputs:
        path = confined_file(run, row['path'])
        if digest(path) != row['sha256']:
            raise ValueError(f'Delivered bytes changed: {row["path"]}')
        hashes[path.name] = row['sha256']
    return hashes


def report_campaign(pack: Path, runs_root: Path, evidence_kind: str) -> dict[str, Any]:
    """Count every persisted operation, including failures preceding a restart.

    External audits remain separately reported pending evidence. The collector
    verifies file identities, not model judgments, and never certifies a release.
    """
    manifest = json.loads(confined_file(pack, 'campaign.json').read_text())
    if manifest.get('schema_version') != 'hermes-reliability-campaign/v1':
        raise ValueError('Unsupported campaign manifest')
    cases = manifest['cases']
    lookup = {}
    for case in cases:
        for key in ('input', 'oracle'):
            if digest(confined_file(pack, case[key])) != case[key + '_sha256']:
                raise ValueError(f'Campaign {key} changed: {case["id"]}')
        if case['input_sha256'] in lookup:
            raise ValueError('Ambiguous campaign input identity')
        lookup[case['input_sha256']] = case
    if not runs_root.is_dir() or runs_root.is_symlink():
        raise ValueError('Use an existing dedicated campaign run directory')
    operations, errors = [], []
    for path in sorted(runs_root.glob('**/logs/desktop-operation*.json')):
        run = path.parent.parent
        operation = {'state_path': str(path), 'case_id': None, 'delivered': False,
                     'elapsed_seconds': None, 'status': 'unreadable'}
        try:
            state = json.loads(confined_file(runs_root, path.relative_to(runs_root).as_posix()).read_text())
            if not isinstance(state, dict):
                raise ValueError('Operation state must be an object')
            result = state.get('result') or {}
            if not isinstance(result, dict):
                raise ValueError('Operation result must be an object')
            operation.update(operation_id=state.get('operation_id'), status=state.get('status'),
                             started_at_epoch=state.get('started_at_epoch'),
                             release_identity=state.get('release_identity'),
                             approval_identity=state.get('approval_identity'))
            duration = result.get('elapsed_seconds')
            if isinstance(duration, (int, float)) and not isinstance(duration, bool) and math.isfinite(duration) and duration >= 0:
                operation['elapsed_seconds'] = duration
            matching = {lookup[digest(confined_file(run, p.relative_to(run).as_posix()))]['id']
                        for p in (run / 'input').rglob('*') if p.is_file()
                        and digest(confined_file(run, p.relative_to(run).as_posix())) in lookup}
            if len(matching) != 1:
                raise ValueError('Operation must retain exactly one matching campaign raw input')
            case_id = matching.pop()
            operation['case_id'] = case_id
            counters = state.get('attempt_counters', {})
            if not isinstance(counters, dict):
                raise ValueError('Operation attempt counters must be an object')
            for key in ('parent_visual_callbacks', 'handoff_dispatches', 'generation', 'verification', 'drafting'):
                counts = counters.get(key, {})
                if not isinstance(counts, dict) or any(
                    not isinstance(count, int) or isinstance(count, bool) or count < 0 for count in counts.values()
                ):
                    raise ValueError(f'Invalid per-target attempt counters: {key}')
            operation['attempt_counters'] = counters
            case = next(c for c in cases if c['id'] == case_id)
            expected = json.loads((pack / case['oracle']).read_text())['document_set']
            hashes = verified_delivery(run, result, expected)
            operation['delivered'] = state.get('status') == 'passed' and bool(hashes)
            operation['artifact_sha256'] = hashes
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append({'state_path': str(path), 'error': str(exc)})
        operations.append(operation)
    grouped = {case['id']: [op for op in operations if op['case_id'] == case['id']] for case in cases}
    executed = [rows for rows in grouped.values() if rows]
    first_pass = 0
    for rows in executed:
        starts = [row.get('started_at_epoch') for row in rows]
        if all(isinstance(t, (int, float)) and not isinstance(t, bool) and math.isfinite(t) for t in starts) and len(starts) == len(set(starts)):
            first_pass += min(rows, key=lambda row: row['started_at_epoch'])['delivered']
        else:
            errors.append({'case_id': rows[0]['case_id'], 'error': 'First operation order is unverified'})
    ratio = lambda numerator, denominator: {'numerator': numerator, 'denominator': denominator}
    terminal = {'passed', 'blocked', 'review_required', 'timeout', 'failed', 'cancelled'}
    recovered = sum(op['delivered'] and operation_recovered(op) for op in operations)
    return {
        'schema_version': 'hermes-reliability-campaign-report/v1',
        'evidence_kind': evidence_kind, 'certification': False,
        'first_operation_delivery': ratio(first_pass, len(executed)),
        'eventual_delivery': ratio(sum(any(op['delivered'] for op in rows) for rows in executed), len(executed)),
        'terminal_failures': ratio(sum(op['status'] in terminal and not op['delivered'] for op in operations), len(operations)),
        'same_operation_recovery': ratio(recovered, len(operations)),
        'external_audit_complete': ratio(0, len(executed)),
        'external_audit_status': 'Separate independent artifact audit required; not collected by this CLI',
        'total_elapsed_seconds': sum(op['elapsed_seconds'] for op in operations if op['elapsed_seconds'] is not None),
        'unmeasured_operations': [op['state_path'] for op in operations if op['elapsed_seconds'] is None],
        'unrun_cases': [key for key, rows in grouped.items() if not rows],
        'operations': operations, 'evidence_errors': errors,
    }


def operation_recovered(operation: dict) -> bool:
    counters = operation.get('attempt_counters', {})
    # These persisted generation counters are per-target repair attempts, not
    # ordinary invocations. Parent callbacks also expose delegated-review fallback.
    return any(isinstance(count, int) and count >= threshold
               for key, threshold in (('parent_visual_callbacks', 1), ('handoff_dispatches', 2),
                                      ('generation', 2), ('verification', 2), ('drafting', 2))
               for count in (counters.get(key) or {}).values())


def build_pack(output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=False)
    records = []
    for case in campaign_cases():
        raw = output / 'inputs' / (case['id'] + '.md')
        oracle = output / 'reviewer-only' / (case['id'] + '.json')
        raw.parent.mkdir(exist_ok=True)
        raw.write_text(raw_packet(case), encoding='utf-8')
        write_json(oracle, case['oracle'])
        record = {k: v for k, v in case.items() if k not in {'reference', 'oracle'}}
        record.update(input=raw.relative_to(output).as_posix(), input_sha256=digest(raw),
                      oracle=oracle.relative_to(output).as_posix(), oracle_sha256=digest(oracle))
        records.append(record)
    manifest = {'schema_version': 'hermes-reliability-campaign/v1', 'cases': records,
                'paid_runs_started': 0, 'certification': False}
    write_json(output / 'campaign.json', manifest)
    guide = ROOT / 'docs/reliability/hermes-campaign-instructions.md'
    (output / 'README.md').write_text(guide.read_text(encoding='utf-8'), encoding='utf-8')
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    build = commands.add_parser('build')
    build.add_argument('--output', required=True, type=Path)
    report = commands.add_parser('report')
    report.add_argument('--pack', required=True, type=Path)
    report.add_argument('--runs-root', required=True, type=Path)
    report.add_argument('--evidence-kind', required=True, choices=('controlled_fixture', 'live_hermes'))
    args = parser.parse_args()
    try:
        result = build_pack(args.output) if args.command == 'build' else report_campaign(args.pack, args.runs_root, args.evidence_kind)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f'{exc}\n')
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
