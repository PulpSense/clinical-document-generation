#!/usr/bin/env python3
"""Fixed owner-run campaign manifest and transparent operation timing summary; no live execution."""
import argparse
import copy
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


def supplemental_seed_plan(case_id, source):
    w = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    def text_seed(seed_id, artifact, before, after, xpath=None, **extra):
        # XPath and source-owned substring are fixed before observing results.
        return {'seed_id': seed_id, 'artifact': artifact, 'part': 'word/document.xml',
            'namespaces': w, 'xpath': xpath or f'(//w:t[contains(., {json.dumps(before)})])[1]',
            'before': before, 'after': after, 'replace_substring': True, **extra}
    if case_id == 'Q1':
        return [text_seed('Q1.1', 'protocol.docx', source['population']['sample_size'], '800 participants'),
            text_seed('Q1.2', 'protocol.docx', 'No direct benefit', 'A direct benefit'),
            text_seed('Q1.3', 'protocol.docx', 'Month 3', 'Baseline',
                '(//w:tr[.//w:t[contains(., "Day 90")]]//w:t[contains(., "Month 3")])[1]')]
    if case_id == 'Q2':
        return [dict(seed_id='Q2.1', artifact='icf.docx', part='word/document.xml', namespaces=w,
                     xpath='(//w:p[.//w:t[contains(translate(., "VOLUNTARY", "voluntary"), "voluntary")]])[1]',
                     before=None, remove_node=True),
            dict(seed_id='Q2.2', artifact='study.xml', xpath='//enrollment', before='80', after='800')]
    if case_id == 'Q3':
        return [text_seed('Q3.1', 'protocol.docx', 'Reminder calls support follow-up.', ''),
            dict(seed_id='Q3.2', artifact='protocol.docx', part='word/header1.xml', namespaces=w,
                 xpath='(//w:p)[1]', operation='replace_paragraph',
                 after='Study title: Unsupported substituted clinical study', check_before=False,
                 source_path='study.title', approved_value=source['study']['title'])]
    if case_id == 'Q4':
        return [dict(seed_id='Q4.1', artifact='icf.docx', part='word/document.xml', namespaces=w,
                     xpath='(//w:tbl/w:tr)[1]', operation='exact_row_height', twips=1, check_before=False)]
    if case_id == 'D1':
        return [{'seed_id': 'D1.1', 'finding_id': 'D1-harmless-paraphrase', 'artifact': 'protocol',
            'target_ids': ['ethics'], 'check': 'source_supported', 'material': True,
            'issue': 'Test-owned hypothesis: question whether a harmless paraphrase of no guaranteed direct benefit changes the source meaning. Independently resolve against current native/source evidence; this is not a reviewer observation.',
            'source_path': 'risks_benefits.benefits', 'source_excerpt': source['risks_benefits']['benefits'],
            'affected_passage': 'Protocol ethics/benefits explanation',
            'seed_author': 'owner-campaign-hypothesis-author', 'provenance': 'test_owned_prior_hypothesis_before_binding'}]
    return []


def long_synthetic_source(source):
    value = copy.deepcopy(source)
    value['study']['background'] += '\n' + '\n'.join(
        f'Synthetic evidence group {i:04d}: existing follow-up records may describe the stated recovery outcome. '
        'This qualified descriptive association is not proof of treatment benefit. No additional intervention '
        'is assigned, and the supplied schedule relationships and consent safeguards remain applicable.'
        for i in range(600))
    return value


def readiness_plan(candidate_identity):
    """Predeclare denominators, independent fact ledgers and every supplemental seed."""
    baseline = plan()
    operations = []
    for repetition in (1, 2):
        for case in baseline['cases']:
            operations.append({'planned_operation_id': f"{case['case_id']}.r{repetition}",
                'case_id': case['case_id'], 'cohort': case['scenario'], 'repetition': repetition,
                'expected_status': 'passed', 'source_sha256': case['source_sha256']})
    pilot = ['retrospective-sparse-complete.r1', 'prospective-advarra-sparse-complete.r1', 'prospective-sterling-sparse-complete.r1']
    operations.sort(key=lambda row: (0, pilot.index(row['planned_operation_id'])) if row['planned_operation_id'] in pilot else (1, 0))
    supplements = []
    for case_id, family, seeds, outcome in SUPPLEMENTS:
        source_case = next(c for c in baseline['cases'] if c['family'] == family and c['scenario'] == 'deliberate_prose_repair')
        supplemental_source = long_synthetic_source(source_case['source']) if case_id in {'Q3', 'Q4'} else copy.deepcopy(source_case['source'])
        source_hash = hashlib.sha256(json.dumps(supplemental_source, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        supplements.append({'source': supplemental_source, 'native_seeds': supplemental_seed_plan(case_id, supplemental_source),
            'planned_operation_id': case_id, 'case_id': case_id, 'family': family,
            'source_case_id': source_case['case_id'], 'source_sha256': source_hash,
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
    facts.update({c['case_id']: {'source_sha256': c['source_sha256'], 'expected_source_facts': c['source'],
        'seed_ledger': c['native_seeds'], 'audit_rule': 'Audit every fixed seed and all source facts; inspect every final page independently.'} for c in supplements})
    manifest = {'schema_version': 'hermes-readiness-campaign/v1', 'candidate_identity': candidate_identity,
        'cases': baseline['cases'], 'pilot_operation_ids': pilot, 'baseline_operations': operations, 'supplemental_operations': supplements,
        'expected_fact_ledgers': facts, 'baseline_denominator': 20, 'supplemental_denominator': 8,
        'clean_denominator': 10, 'repair_denominator': 10, 'deadline_seconds': 2700,
        'target_seconds_exclusive': 1500, 'minimum_under_target_per_cohort': 8,
        'live_execution': False, 'readiness': 'incomplete',
        'execution_prerequisites': ['owner_authorization', 'exact_installed_candidate',
            'reviewed_linux_injection_adapter',
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
