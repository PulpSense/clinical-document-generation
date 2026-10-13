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
from tui_campaign_contract import validate_tui_host_checks


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
                 xpath=f'(//w:t[text()={json.dumps(source["study"]["short_title"])}])[1]',
                 before=source['study']['short_title'], after='Unsupported substituted clinical study',
                 source_path='study.short_title')]
    if case_id == 'Q4':
        return [dict(seed_id='Q4.1', artifact='protocol.docx', part='word/document.xml', namespaces=w,
                     xpath='(//w:tbl/w:tr[.//w:t[contains(., "Month 3")]])[1]',
                     required_text='Month 3', source_path='procedures.visit_schedule_table',
                     operation='exact_row_height', twips=1, check_before=False)]
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


def readiness_plan(candidate_identity, host_mode="isolated", host_checks=None):
    if host_mode not in {"isolated", "hermes-tui"}:
        raise ValueError("Unknown campaign host mode")
    """Predeclare denominators, independent fact ledgers and every supplemental seed."""
    baseline = plan()
    operations = []
    for repetition in (1, 2):
        for case in baseline['cases']:
            operations.append({'planned_operation_id': f"{case['case_id']}.r{repetition}",
                'case_id': case['case_id'], 'cohort': case['scenario'], 'repetition': repetition,
                'expected_status': 'passed', 'source_sha256': case['source_sha256'],
                'seed_ids': [case['case_id'] + '.unsupported-drug'] if case['injection'] else []})
    pilot = ['retrospective-sparse-complete.r1', 'prospective-advarra-sparse-complete.r1', 'prospective-sterling-sparse-complete.r1']
    operations.sort(key=lambda row: (0, pilot.index(row['planned_operation_id'])) if row['planned_operation_id'] in pilot else (1, 0))
    supplements = []
    for case_id, family, seeds, outcome in SUPPLEMENTS:
        if host_mode == 'hermes-tui':
            seeds = ([s.replace('recipient', 'local_output') for s in seeds] if case_id == 'F2'
                     else ['unresolved_substantive_seed', 'repair_author_unavailable'] if case_id == 'F3' else seeds)
        source_case = next(c for c in baseline['cases'] if c['family'] == family and c['scenario'] == 'deliberate_prose_repair')
        supplemental_source = long_synthetic_source(source_case['source']) if case_id in {'Q3', 'Q4'} else copy.deepcopy(source_case['source'])
        source_hash = hashlib.sha256(json.dumps(supplemental_source, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        supplements.append({'source': supplemental_source, 'native_seeds': supplemental_seed_plan(case_id, supplemental_source),
            'planned_operation_id': case_id, 'case_id': case_id, 'family': family,
            'source_case_id': source_case['case_id'], 'source_sha256': source_hash,
            'cohort': 'supplemental', 'expected_status': outcome, 'host_mode': host_mode,
            'seeds': [{'seed_id': f'{case_id}.{index}', 'challenge': seed,
                       'expected': 'independent_resolution_without_needless_edit' if case_id == 'D1'
                       else ('honest_local_review_only' if host_mode == 'hermes-tui' else 'honest_confirmed_review_only') if case_id == 'F3' else 'detected_recovered_fresh_review_and_retrieval'}
                      for index, seed in enumerate(seeds, 1)],
            'injection_boundary': 'before_review_request_binding' if case_id == 'D1'
                else 'run_local_construction_before_render_and_review_hashes' if case_id.startswith('Q')
                else 'ordinary_worker_or_recipient_transport'})
    facts = {c['case_id']: {'source_sha256': c['source_sha256'], 'expected_source_facts': c['source'],
        'audit_rule': 'Compare final native/XML meaning and relationships against every approved fact; inspect every final rendered page independently of drafting and repair.'}
        for c in baseline['cases']}
    facts.update({c['case_id']: {'source_sha256': c['source_sha256'], 'expected_source_facts': c['source'],
        'seed_ledger': c['native_seeds'], 'audit_rule': 'Audit every fixed seed and all source facts; inspect every final page independently.'} for c in supplements})
    manifest = {'schema_version': 'hermes-readiness-campaign/v1', 'candidate_identity': candidate_identity, 'host_mode': host_mode,
        'cases': baseline['cases'], 'pilot_operation_ids': pilot, 'baseline_operations': operations, 'supplemental_operations': supplements,
        'expected_fact_ledgers': facts, 'baseline_denominator': 20, 'supplemental_denominator': 8,
        'clean_denominator': 10, 'repair_denominator': 10, 'deadline_seconds': 2700,
        'target_seconds_exclusive': 1500, 'minimum_under_target_per_cohort': 8,
        'live_execution': False, 'readiness': 'incomplete',
        'execution_prerequisites': ['owner_authorization', 'exact_installed_candidate',
            'reviewed_linux_injection_adapter',
            'tui_host_checks' if host_mode == 'hermes-tui' else 'actual_worker_capabilities', 'independent_artifact_auditor'],
        'unexecuted_cases_remain_visible': True}
    if host_mode == 'hermes-tui' and host_checks is not None:
        validate_tui_host_checks(host_checks, candidate_identity)
        manifest['host_checks_sha256'] = hashlib.sha256(json.dumps(host_checks, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    manifest['manifest_sha256'] = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return manifest


def validate_readiness_manifest(manifest):
    unsigned = {k: v for k, v in manifest.items() if k != 'manifest_sha256'}
    actual = hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if actual != manifest.get('manifest_sha256'):
        raise ValueError('Frozen readiness manifest bytes/identity changed')
    planned = manifest['baseline_operations'] + manifest['supplemental_operations']
    if len(planned) != 28 or len({p['planned_operation_id'] for p in planned}) != 28:
        raise ValueError('Frozen readiness denominator must contain all 28 distinct operations')


def summarize_readiness(manifest, operations):
    """Reconcile first operations separately from retries and resumes; no invented observations."""
    validate_readiness_manifest(manifest)
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
            confirmed = (row.get('local_bytes_verified') if manifest.get('host_mode') == 'hermes-tui'
                         else row.get('review_delivery_confirmed') if p['expected_status'] == 'review_required' else row.get('delivery_confirmed'))
            ok = row.get('status') == p['expected_status'] and confirmed is True and row.get('independent_audit_passed') is True
            elapsed = row.get('elapsed_seconds')
            succeeded += bool(ok and isinstance(elapsed, (int, float)) and 0 <= elapsed <= 2700)
            under += bool(ok and isinstance(elapsed, (int, float)) and 0 <= elapsed < 1500)
        groups[cohort] = {'planned_denominator': denominator, 'observed_first_operations': len(observed),
            'expected_outcomes_with_audit_and_retrieval': succeeded, 'under_target': under,
            'rate': succeeded / denominator if len(observed) == denominator else None,
            'missing': [p['planned_operation_id'] for p in plans if p['planned_operation_id'] not in first]}
    return {**report, 'planned_groups': groups, 'readiness': 'incomplete',
        'limitations': 'Observations require exact candidate/manifest/evidence reconciliation, every seed audit and installed capability gates before a readiness verdict. Timing alone never establishes readiness.'}



def verify_local_receipt(receipt):
    if ((receipt.get('status') != 'locally_available' and receipt.get('delivery_status') != 'review_only_locally_available') or receipt.get('bytes_verified') is not True
            or receipt.get('confirmed') is not False or receipt.get('recipient_delivery_verified') is not False):
        raise ValueError('TUI outcome requires honest verified local bytes without recipient confirmation')


def verified_local_outputs(run, result, inventory):
    from reliability_campaign import confined_file, digest
    verify_local_receipt(result.get('delivery', {}))
    manifest = json.loads(confined_file(run, result['manifest']).read_text())
    if manifest.get('status') != 'passed' or manifest.get('quality', {}).get('status') != 'passed':
        raise ValueError('Local publication has no passing quality manifest')
    rows = manifest['client_outputs']
    if sorted(result['client_outputs']) != sorted(row['path'] for row in rows):
        raise ValueError('Local result and publication manifest differ')
    if sorted(p.name for p in (run / 'output').iterdir()) != sorted(inventory):
        raise ValueError('Local publication contains unexpected or missing outputs')
    if {Path(row['path']).name for row in rows} != set(inventory) or len(rows) != len(inventory):
        raise ValueError('Local native document inventory is incomplete')
    outputs = {}
    for row in rows:
        file = confined_file(run, row['path'])
        if digest(file) != row['sha256'] or file.stat().st_size != row['bytes']:
            raise ValueError('Local native bytes changed')
        outputs[file.name] = row['sha256']
    return outputs


def collect_readiness_runs(manifest, runs_root, host_checks=None):
    """Read-only reconciliation of every retained operation and exact file inventory."""
    from reliability_campaign import confined_file, digest, verified_delivery
    validate_readiness_manifest(manifest)
    planned = {p['planned_operation_id']: p for p in manifest['baseline_operations'] + manifest['supplemental_operations']}
    records, errors, matched_states = [], [], set()
    for metadata_path in sorted(runs_root.rglob('campaign-case.json')):
        run = metadata_path.parent
        try:
            metadata = json.loads(confined_file(run, metadata_path.name).read_text())
            assignment = planned[metadata['planned_operation_id']]
            if metadata['manifest_sha256'] != manifest['manifest_sha256'] or metadata['source_sha256'] != assignment['source_sha256']:
                raise ValueError('Case/source/manifest binding differs from the frozen campaign')
            if metadata['candidate_identity'] != manifest['candidate_identity']:
                raise ValueError('Operation belongs to another candidate campaign')
            source = json.loads(confined_file(run, 'campaign-source.json').read_text())
            expected_source = assignment.get('source') or next(c['source'] for c in manifest['cases'] if c['case_id'] == assignment['case_id'])
            if source != expected_source:
                raise ValueError('Retained synthetic source differs from predeclared facts')
            states = list((run / 'logs').glob('desktop-operation*.json'))
            if len(states) != 1:
                raise ValueError('Expected exactly one original Desktop operation; preserve separate retry directories')
            state_path = states[0]
            matched_states.add(state_path.resolve())
            state = json.loads(confined_file(run, str(state_path.relative_to(run))).read_text())
            if state['operation_id'] != metadata['operation_id']:
                raise ValueError('Desktop operation identity changed')
            expected_fingerprint = manifest['candidate_identity'].get('package_fingerprint')
            release = state.get('release_identity', {})
            if manifest.get('host_mode') == 'hermes-tui' and release.get('host_mode') != 'hermes-tui':
                raise ValueError('Retained operation was not executed in the frozen TUI mode')
            if not expected_fingerprint or release.get('package_fingerprint') != expected_fingerprint:
                raise ValueError('Installed candidate fingerprint differs')
            if release.get('git_commit') != manifest['candidate_identity'].get('git_commit'):
                raise ValueError('Installed candidate commit differs')
            result = state.get('result', {})
            study_type = expected_source['meta']['study_type']
            inventory = ['protocol.docx'] if study_type == 'Retrospective' else ['protocol.docx', 'icf.docx', 'study.xml']
            tui = manifest.get('host_mode') == 'hermes-tui'
            delivered = {}
            local_verified = False
            if result.get('status') == 'passed':
                if tui:
                    delivered = verified_local_outputs(run, result, inventory)
                    local_verified = True
                else:
                    delivered = verified_delivery(run, result, inventory)
            review_confirmed = False
            if result.get('status') == 'review_required':
                rows = result.get('review_outputs', [])
                if {Path(row['path']).name for row in rows} != {'REVIEW-ONLY-' + name for name in inventory}:
                    raise ValueError('Review-only document inventory is incomplete')
                for row in rows:
                    file = confined_file(run, row['path'])
                    if digest(file) != row['sha256'] or file.stat().st_size != row['bytes']:
                        raise ValueError('Review-only native bytes changed')
                    delivered[file.name] = row['sha256']
                for field in ('review_findings', 'review_notice'):
                    if digest(confined_file(run, result[field])) != result[field + '_sha256']:
                        raise ValueError('Review-only notice/findings bytes changed')
                review_confirmed = result.get('review_delivery', {}).get('confirmed') is True
                if tui:
                    verify_local_receipt(result.get('review_delivery', {}))
                    local_verified = True

            evidence = {str(p.relative_to(run)): {'sha256': digest(p), 'bytes': p.stat().st_size}
                for p in sorted(run.rglob('*')) if p.is_file() and not p.is_symlink()
                and '.hermes-cache' not in p.parts and p.name not in {'auth.json', '.env'}}
            audits = list(run.glob('independent-artifact-audit.json'))
            authors = set()
            for file in run.rglob('*.json'):
                if '.hermes-cache' in file.parts or file.is_symlink():
                    continue
                try:
                    payload = json.loads(file.read_text())
                    if isinstance(payload, dict) and payload.get('task') in {'section_drafting', 'prs_narrative_drafting', 'document_repair'}:
                        author = payload.get('producer', {}).get('reviewer_id')
                        if author:
                            authors.add(author)
                except (OSError, ValueError, AttributeError):
                    pass
            audit = None
            audit_passed = False
            if audits:
                audit = json.loads(confined_file(run, audits[0].name).read_text())
                required_seeds = set(assignment.get('seed_ids', [])) | {s['seed_id'] for s in assignment.get('seeds', [])}
                seed_results = audit.get('seed_results', {})
                audit_passed = (audit.get('schema_version') == 'readiness-artifact-audit/v1'
                    and bool(audit.get('auditor_id')) and audit['auditor_id'] not in authors
                    and audit.get('independent_of_drafting_and_repair') is True
                    and audit.get('all_source_facts_reviewed') is True and audit.get('all_final_pages_inspected') is True
                    and (audit.get('material_defects_remaining') == 0 if assignment['expected_status'] == 'passed'
                         else audit.get('all_unresolved_concerns_reported') is True and audit.get('no_unreported_material_defects') is True)
                    and audit.get('collateral_loss') == 0
                    and required_seeds <= set(seed_results) and all(seed_results[s].get('expected_outcome_verified') is True for s in required_seeds)
                    and audit.get('delivered_artifact_sha256') == delivered and bool(delivered))
            records.append({'operation_id': state['operation_id'], 'planned_operation_id': assignment['planned_operation_id'],
                'retry_of': metadata.get('retry_of'), 'status': state['status'], 'elapsed_seconds': result.get('elapsed_seconds'),
                'delivery_confirmed': result.get('delivery', {}).get('confirmed') is True and bool(delivered),
                'review_delivery_confirmed': review_confirmed, 'local_bytes_verified': local_verified,
                'independent_audit_passed': audit_passed, 'candidate_identity': metadata['candidate_identity'],
                'source_sha256': assignment['source_sha256'], 'approval_identity': state.get('approval_identity'),
                'started_at_epoch': state.get('started_at_epoch'), 'deadline_at_epoch': state.get('deadline_at_epoch'),
                'stage_timings': state.get('stage_timings'), 'attempt_counters': state.get('attempt_counters'),
                'repair_cycles': result.get('repair_cycles', 0), 'changed_native_repairs': result.get('changed_native_repairs', 0),
                'dispute_cycles': result.get('dispute_cycles', 0), 'independent_audit': audit,
                'worker_events': [json.loads(line) for line in (run / 'logs/hermes-agent-events.jsonl').read_text().splitlines()]
                    if (run / 'logs/hermes-agent-events.jsonl').is_file() else [],
                'delivered_sha256': delivered, 'evidence_inventory': evidence, 'run_directory': str(run)})
        except (OSError, ValueError, KeyError, TypeError, StopIteration) as exc:
            errors.append({'run_directory': str(run), 'issue': str(exc)})
    unmatched = [str(p) for p in sorted(runs_root.rglob('desktop-operation*.json')) if p.resolve() not in matched_states]
    try:
        report = summarize_readiness(manifest, records)
    except ValueError as exc:
        # Conflicts cannot erase already collected failures or disappear from
        # the ledger. Keep every observation, with all rates unmeasured until
        # the owner reconciles the duplicate/first-operation identities.
        report = summarize_readiness(manifest, [])
        report.update(operation_records=records, operations=len(records), reconciliation_conflicted=True)
        errors.append({'scope': 'operation_reconciliation', 'issue': str(exc)})
    acceptance = 'incomplete'
    if manifest.get('host_mode') == 'hermes-tui':
        try:
            validate_tui_host_checks(host_checks, manifest['candidate_identity'], manifest)
            groups = report['planned_groups']
            complete = all(g['observed_first_operations'] == g['planned_denominator'] for g in groups.values())
            outcomes = all(g['expected_outcomes_with_audit_and_retrieval'] == g['planned_denominator'] for g in groups.values())
            speed = all(groups[name]['under_target'] >= 8 for name in ('clean', 'deliberate_prose_repair'))
            acceptance = ('passed' if complete and outcomes and speed and not errors and not unmatched
                          else 'failed' if complete else 'incomplete')
        except (ValueError, TypeError) as exc:
            errors.append({'scope': 'tui_host_checks', 'issue': str(exc)})
    return {**report, 'evidence_errors': errors, 'unmatched_operation_states': unmatched,
            'readiness': 'incomplete', 'tui_local_acceptance': acceptance,
            'recipient_delivery_verified': False if manifest.get('host_mode') == 'hermes-tui' else None,
            'collector_scope': 'TUI local acceptance is separate from isolated certification and recipient delivery.'}


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
    parser.add_argument('--host-checks', type=Path, help='Required TUI host-check evidence for freezing and collecting')
    parser.add_argument('--host-mode', choices=['isolated', 'hermes-tui'], default='isolated')
    parser.add_argument('--operations', type=Path, help='JSON array containing every operation, including failures and retries')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--runs-root', type=Path, help='Read-only reconcile retained campaign operation directories')
    parser.add_argument('--candidate-identity', type=Path, help='Freeze the 20+8 readiness plan with exact candidate identity JSON; no live execution')
    parser.add_argument('--readiness-manifest', type=Path, help='Reconcile observations against a frozen 20+8 plan')
    args = parser.parse_args()
    host_checks = json.loads(args.host_checks.read_text()) if args.host_checks else None
    if host_checks is not None:
        validate_tui_host_checks(host_checks, host_checks.get('candidate_identity'), evidence_root=args.host_checks.parent)
    if args.candidate_identity and args.host_mode == 'hermes-tui' and host_checks is None:
        parser.error('TUI plan freezing requires --host-checks')
    if args.readiness_manifest and args.runs_root:
        result = collect_readiness_runs(json.loads(args.readiness_manifest.read_text()), args.runs_root, host_checks)
    elif args.readiness_manifest:
        result = summarize_readiness(json.loads(args.readiness_manifest.read_text()),
                                     json.loads(args.operations.read_text()) if args.operations else [])
    elif args.candidate_identity:
        result = readiness_plan(json.loads(args.candidate_identity.read_text()), args.host_mode, host_checks)
    else:
        result = summarize(json.loads(args.operations.read_text())) if args.operations else plan()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
