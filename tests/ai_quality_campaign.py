#!/usr/bin/env python3
"""Fixed owner-run campaign manifest and transparent operation timing summary; no live execution."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import quality


def plan():
    cases = []
    for case in quality.branch_acceptance_inventory(ROOT):
        descriptor = case['descriptor']
        source = quality.branch_acceptance_source(ROOT, case)
        rich = descriptor['profile'].startswith('rich')
        encoded = json.dumps(source, sort_keys=True, separators=(',', ':')).encode()
        cases.append({'case_id': descriptor['fixture_id'],
                      'family': descriptor['study_type'] + '/' + descriptor.get('icf_template', 'none'),
                      'profile': descriptor['profile'],
                      'scenario': 'deliberate_prose_repair' if rich else 'clean',
                      'source_sha256': hashlib.sha256(encoded).hexdigest(), 'source': source,
                      'injection': 'Participants receive an unsupported experimental drug.' if rich else None})
    return {'schema_version': 'owner-ai-quality-plan/v1', 'live_execution': False,
            'quality_and_speed_readiness': 'unproven', 'cases': cases}


def summarize(operations):
    groups = {name: {'denominator': 0, 'client_ready_under_25_minutes': 0} for name in
              ('clean', 'changed_native_repairs', 'dispute_only')}
    seen = set()
    for row in operations:
        identity = row.get('operation_id')
        if not isinstance(identity, str) or not identity.strip():
            raise ValueError('Every operation requires an operation_id, including failed attempts.')
        if identity in seen:
            raise ValueError(f'Duplicate operation ID: {identity}; combine resumes, retain retries separately.')
        seen.add(identity)
        group = ('changed_native_repairs' if row.get('changed_native_repairs', 0) else
                 'dispute_only' if row.get('dispute_cycles', 0) else 'clean')
        groups[group]['denominator'] += 1
        if (row.get('status') == 'passed' and row.get('delivery_confirmed') is True
                and isinstance(row.get('elapsed_seconds'), (int, float))
                and 0 <= row['elapsed_seconds'] < 1500):
            groups[group]['client_ready_under_25_minutes'] += 1
    for group in groups.values():
        count = group['denominator']
        group['proportion'] = group['client_ready_under_25_minutes'] / count if count else None
    return {'operations': len(operations), 'groups': groups, 'operation_records': operations,
            'limitations': 'Timing counts do not establish independent clinical or visual quality.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--operations', type=Path, help='JSON array containing every operation, including failures and retries')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = summarize(json.loads(args.operations.read_text())) if args.operations else plan()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
