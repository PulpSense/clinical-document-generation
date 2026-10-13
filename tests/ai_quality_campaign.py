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


SUPPLEMENTS = (
    ('Q1', 'Retrospective/none', ['alter_quantity', 'lose_negation', 'misassociate_table_row'], 'passed'),
    ('Q2', 'Prospective/Sterling', ['omit_consent_safeguard', 'alter_valid_prs_value'], 'passed'),
    ('Q3', 'Ambispective/Advarra', ['omit_operational_detail', 'alter_header_footer_or_textbox'], 'passed'),
    ('Q4', 'Ambispective/Sterling', ['material_table_clipping_or_flow'], 'passed'),
    ('F1', 'Prospective/Advarra', ['limit_read', 'truncate_final_after_checkpoint', 'interrupt_resume_parent'], 'passed'),
    ('F2', 'Retrospective/none', ['delegate_visual_unavailable', 'transient_recipient_retrieval'], 'passed'),
    ('F3', 'Ambispective/Sterling', ['unresolved_substantive_concern', 'no_productive_safe_correction'], 'review_required'),
    ('D1', 'Prospective/Sterling', ['seeded_prior_paraphrase_hypothesis_with_distinct_author'], 'passed'),
)


def readiness_plan(candidate_identity):
    """Predeclare denominators, independent fact ledgers and every supplemental seed."""
    baseline = plan()
    operations = []
    for repetition in (1, 2):
        for case in baseline['cases']:
            operations.append({'planned_operation_id': f"{case['case_id']}.r{repetition}",
                'case_id': case['case_id'], 'cohort': case['scenario'], 'repetition': repetition,
                'expected_status': 'passed', 'source_sha256': case['source_sha256']})
    supplements = []
    for case_id, family, seeds, outcome in SUPPLEMENTS:
        source_case = next(c for c in baseline['cases'] if c['family'] == family and c['scenario'] == 'deliberate_prose_repair')
        supplements.append({'planned_operation_id': case_id, 'case_id': case_id, 'family': family,
            'source_case_id': source_case['case_id'], 'source_sha256': source_case['source_sha256'],
            'cohort': 'supplemental', 'expected_status': outcome,
            'seeds': [{'seed_id': f'{case_id}.{index}', 'challenge': seed,
                       'expected': 'independent_resolution_without_needless_edit' if case_id == 'D1'
                       else 'honest_confirmed_review_only' if case_id == 'F3' else 'detected_recovered_fresh_review_and_retrieval'}
                      for index, seed in enumerate(seeds, 1)],
            'injection_boundary': 'before_review_request_binding' if case_id == 'D1'
                else 'run_local_construction_before_render_and_review_hashes' if case_id.startswith('Q')
                else 'ordinary_worker_or_recipient_transport'})
    facts = {c['case_id']: {'source_sha256': c['source_sha256'], 'expected_source_facts': c['source'],
        'audit_rule': 'Compare final native/XML meaning and relationships against every approved fact; inspect every final rendered page independently of drafting and repair.'}
        for c in baseline['cases']}
    manifest = {'schema_version': 'hermes-readiness-campaign/v1', 'candidate_identity': candidate_identity,
        'cases': baseline['cases'], 'baseline_operations': operations, 'supplemental_operations': supplements,
        'expected_fact_ledgers': facts, 'baseline_denominator': 20, 'supplemental_denominator': 8,
        'clean_denominator': 10, 'repair_denominator': 10, 'deadline_seconds': 2700,
        'target_seconds_exclusive': 1500, 'minimum_under_target_per_cohort': 8,
        'live_execution': False, 'readiness': 'incomplete',
        'execution_prerequisites': ['owner_authorization', 'exact_installed_candidate',
            'reviewed_linux_injection_adapter', 'predeclared_native_seed_locations_and_values',
            'actual_worker_capabilities', 'independent_artifact_auditor'],
        'unexecuted_cases_remain_visible': True}
    manifest['manifest_sha256'] = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return manifest


def summarize_readiness(manifest, operations):
    """Reconcile first operations separately from retries and resumes; no invented observations."""
    report = summarize(operations)
    planned = manifest['baseline_operations'] + manifest['supplemental_operations']
    first = {}
    for row in operations:
        planned_id = row.get('planned_operation_id')
        if planned_id not in {p['planned_operation_id'] for p in planned}:
            raise ValueError('Unmatched operation must be reconciled with the campaign ledger.')
        if not row.get('retry_of'):
            if planned_id in first:
                raise ValueError('Multiple first operations for a planned case; declare retry_of.')
            first[planned_id] = row
    groups = {}
    for cohort, denominator in [('clean', 10), ('deliberate_prose_repair', 10), ('supplemental', 8)]:
        plans = [p for p in planned if p['cohort'] == cohort]
        observed = [first[p['planned_operation_id']] for p in plans if p['planned_operation_id'] in first]
        succeeded, under = 0, 0
        for p in plans:
            row = first.get(p['planned_operation_id'], {})
            confirmed = row.get('review_delivery_confirmed') if p['expected_status'] == 'review_required' else row.get('delivery_confirmed')
            ok = row.get('status') == p['expected_status'] and confirmed is True and row.get('independent_audit_passed') is True
            elapsed = row.get('elapsed_seconds')
            succeeded += bool(ok and isinstance(elapsed, (int, float)) and 0 <= elapsed <= 2700)
            under += bool(ok and isinstance(elapsed, (int, float)) and 0 <= elapsed < 1500)
        groups[cohort] = {'planned_denominator': denominator, 'observed_first_operations': len(observed),
            'expected_outcomes_with_audit_and_retrieval': succeeded, 'under_target': under,
            'rate': succeeded / denominator if observed else None,
            'missing': [p['planned_operation_id'] for p in plans if p['planned_operation_id'] not in first]}
    return {**report, 'planned_groups': groups, 'readiness': 'incomplete',
        'limitations': 'Observations require exact candidate/manifest/evidence reconciliation, every seed audit and installed capability gates before a readiness verdict. Timing alone never establishes readiness.'}


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
    parser.add_argument('--candidate-identity', type=Path, help='Freeze the 20+8 readiness plan with exact candidate identity JSON; no live execution')
    parser.add_argument('--readiness-manifest', type=Path, help='Reconcile observations against a frozen 20+8 plan')
    args = parser.parse_args()
    if args.readiness_manifest:
        result = summarize_readiness(json.loads(args.readiness_manifest.read_text()),
                                     json.loads(args.operations.read_text()) if args.operations else [])
    elif args.candidate_identity:
        result = readiness_plan(json.loads(args.candidate_identity.read_text()))
    else:
        result = summarize(json.loads(args.operations.read_text())) if args.operations else plan()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
