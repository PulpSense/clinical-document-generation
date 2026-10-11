#!/usr/bin/env python3
"""Developer release check using local fixtures; never a client activation gate."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / 'docs/reliability/blocking-checks.json'
# Explicit selection prevents accidental execution of live certification/corpora.
TEST_FILES = (
    'test_evidence_diagnostics.py', 'test_evidence_variations.py', 'test_offline_reliability_gate.py',
    'test_synopsis_recovery.py', 'test_layout_field_corrections.py', 'test_run07_reliability.py',
    'test_assessment_matrix.py', 'test_hypothesis_fidelity.py', 'test_sterling_rendered_scope.py',
    'test_visit_identifier_scope.py', 'test_bilateral_review_block.py', 'test_section_background_scope.py',
    'test_run04_background_regressions.py', 'test_phase2_sterling_fidelity.py', 'test_sterling_template_comments.py',
    'test_duration_reference_preservation.py', 'test_brad_editorial_feedback.py', 'test_contracts.py',
    'test_handoff_quality.py', 'test_visit_inventory_review.py', 'test_reliability_maintenance.py',
    'test_prs_quality_corrections.py', 'test_prs_xml.py', 'test_worker_readiness.py',
    'test_mixed_visit_representations.py', 'test_semantic_evidence_recovery.py',
    'test_concept_reference_grounding.py', 'test_review_contract_root_causes.py',
    'test_owner_aware_recovery.py', 'test_review_resolutions.py', 'test_shared_output_projection.py',
    'test_editorial_publication.py', 'test_phase1_repetition.py',
    'test_contextual_output_fixes.py',
    'test_bibliographic_evidence.py', 'test_clean_delivery.py', 'test_general_delivery_reliability.py',
    'test_source_routing.py',
    'test_reliability_campaign.py', 'test_reviewer_transport.py',
    'test_construction_reliability.py',
    'test_presentation_delivery.py',
)


def blocking_check_inventory(root: Path = ROOT) -> list[dict[str, str]]:
    """Index direct finding/block producers, including nested checks in each function.

    This is a source-change audit, not a proof that every conditional is correct.
    Boolean helper dependencies are covered by implementation fingerprints and tests.
    """
    records = []
    for path in sorted((root / 'scripts').glob('*.py')):
        source = path.read_text(encoding='utf-8')
        lines = source.splitlines(keepends=True)
        tree = ast.parse(source)
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            strings = {item.value for item in ast.walk(node) if isinstance(item, ast.Constant) and isinstance(item.value, str)}
            shared_helpers = {
                '_leaf_texts', '_grounding_tokens', '_evidence_diagnostics',
                'branch_acceptance_source', 'finding_requires_repair', 'evidence_coverage_finding',
                'evidence_grounded', 'source_evidence_diagnostics', 'source_evidence_grounded',
                'hypothesis_claim_issues', '_timeline_grounded', '_material_source',
                'section_evidence_value', '_clinical_evidence_text', 'bibliography_reference_ids',
                '_bibliography_text', 'protocol_bibliography',
                'bibliographic_citation_spans', 'semantic_evidence_contract', 'assessment_matrix',
                'normalized_visit_records', 'protocol_table_contracts', 'sterling_draft_word_budget',
                '_matrix_visit_alias', '_schedule_activity_identity', 'lexical_evidence_uncertainty',
                '_lexical_review_cautions', '_reviewed_lexical_warnings', '_review_evidence_text', '_quantity_claim_issues', '_uncertainty_rule_sha256',
                'study_short_title', 'sample_size_display', 'study_design_display',
                '_name', '_contact_fields', '_site_investigator', '_observational_cohorts',
                '_person_degrees', 'contextual_clinical_boilerplate',
                '_supplied_protocol_references', '_normalize_icf_source_displays',
                '_omit_empty_visit_window', '_assessment_matrix',
                'participant_followup_summary', 'computed_study_fields', 'protocol_section_snapshot', 'rendered_section_snapshot',
                '_rendered_heading_text', '_target_heading',
                '_recovery_action_observation', '_governed_editorial_warning', '_fidelity_evidence',
                '_unresolved_evidence_defects',
                '_accepted_drafting_warnings', '_render_warnings',
                'renderers',
                'semantic_evidence_inventory', '_source_field_inventory', 'create_verification_requests',
                'source_text_values', 'schedule_interpretation_contract', 'benefit_context_contract',
                'interpreted_schedule_reference', 'document_table_reference',
                'source_routing_obligations', '_bound_source_routing_obligations', 'source_routing_assessment_errors',
                '_format_value', '_parse_value',
                '_construction_finding_source', 'construction_repair_spec', 'construction_retry_spec',
                '_construction_request_payload', 'create_construction_repair_request',
                '_request_matches_approved_reference', '_template_document',
                '_apply_pending_recovery_plan',
                'canonical_review_surface', 'reviewed_presentation_only', 'internal_presentation_note',
                '_optional_construction_findings', '_study_descriptor',
                '_warning_findings',
            }
            if not {'issue', 'blocked', 'publication_disposition'} & strings and node.name not in shared_helpers:
                continue
            # AST dumps change when Python adds fields (for example, type_params in
            # 3.12). Hash the source instead so one audit works on every runtime.
            first_line = min([node.lineno, *(decorator.lineno for decorator in node.decorator_list)])
            function_source = ''.join(lines[first_line - 1:node.end_lineno])
            records.append({
                'file': path.relative_to(root).as_posix(), 'function': node.name,
                'code_sha256': hashlib.sha256(function_source.encode('utf-8')).hexdigest(),
            })
    return records


def audit_findings(root: Path = ROOT) -> list[str]:
    audit = json.loads((root / AUDIT.relative_to(ROOT)).read_text(encoding='utf-8'))
    expected = {(item['file'], item['function']): item['code_sha256'] for item in audit['checks']}
    actual = {(item['file'], item['function']): item['code_sha256'] for item in blocking_check_inventory(root)}
    findings = []
    for key in sorted(expected.keys() | actual.keys()):
        if expected.get(key) != actual.get(key):
            findings.append(f'Blocking-check audit requires review: {key[0]}:{key[1]}')
    for path in sorted((root / 'scripts').glob('*.py')):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Dict):
                continue
            values = {key.value: value.value for key, value in zip(node.keys, node.values)
                      if isinstance(key, ast.Constant) and isinstance(value, ast.Constant)}
            code = str(values.get('code') or '')
            if (any(token in code for token in ('lexical', 'repetition', 'word-goal'))
                    and values.get('publication_disposition', 'blocking') != 'warning'):
                findings.append(f'Unjustified lexical publication veto: {path.relative_to(root)}:{node.lineno}')
    for item in audit['checks']:
        family = audit.get('families', {}).get(item.get('family'), {})
        contract = {**family.get('authority_contract', {}), **item.get('authority_contract', {})}
        required = ('requirement', 'evidence', 'authority', 'resolution_authority', 'repair_owner')
        if (any(not contract.get(field) for field in required)
                or contract.get('authority') not in {'objective', 'uncertainty', 'mixed'}):
            findings.append(f"Blocking-check authority contract requires review: {item['file']}:{item['function']}")
        behavior = item.get('behavioral_evidence') or family.get('behavioral_evidence')
        if behavior is None:
            findings.append(f"Blocking-check paired behavioral evidence is missing: {item['function']}")
        else:
            for role in ('valid', 'invalid'):
                nodes = behavior.get(role, [])
                if not nodes:
                    findings.append(f"Blocking-check paired {role} evidence is missing: {item['function']}")
                for node in nodes:
                    filename, _, name = node.partition('::')
                    path = root / 'tests' / filename
                    if (not path.is_file() or not name or not any(
                            isinstance(test, ast.FunctionDef) and test.name == name
                            for test in ast.parse(path.read_text()).body)):
                        findings.append(f"Blocking-check behavioral evidence is invalid: {node}")
        if contract.get('authority') == 'uncertainty' and contract.get('resolution_authority') != 'independent_source_grounded_review':
            findings.append(f"Lexical publication veto is unjustified: {item['function']}")
    return findings


def test_command(python: str = sys.executable) -> list[str]:
    return [python, '-m', 'pytest', *[f'tests/{name}' for name in TEST_FILES], '-q']


def test_environment(office_alias_dir: Path) -> tuple[dict[str, str], str | None]:
    """Pass the office installation discoverable by an installation smoke to pytest.

    Hermes background workers need not source terminal shell init files, so their
    inherited PATH may omit the profile's already-installed LibreOffice.
    Resolve it through the same renderer discovery as the installation smoke.
    """
    scripts = str(ROOT / 'scripts')
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from quality import renderer

    environment = os.environ.copy()
    home = environment.get('HERMES_HOME')
    skill_root = Path(home) / 'skills/clinical-document-generation' if home else ROOT
    selected = renderer(environment=environment, skill_root=skill_root)
    if selected and selected['kind'] == 'LibreOffice':
        office = Path(selected['path'])
        # Tests look up either name; bind both to the smoke-selected executable,
        # even when another launcher is installed alongside it.
        if os.name == 'nt':
            directory = office.parent
        else:
            for name in ('libreoffice', 'soffice'):
                (office_alias_dir / name).symlink_to(office)
            directory = office_alias_dir
        environment['PATH'] = str(directory) + os.pathsep + environment.get('PATH', '')
        return environment, str(office)
    return environment, None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list', action='store_true', help='Show selected local tests without executing them')
    parser.add_argument('--report', type=Path, help='Retain the audit, command, elapsed time and test output')
    parser.add_argument('--timeout', type=float, default=300, help='Developer check budget; unrelated to generation deadline')
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
    command = test_command()
    if args.list:
        print(json.dumps({'command': command, 'paid_model_calls': 0, 'client_activation_gate': False}, indent=2))
        return 0
    started = time.monotonic()
    findings = audit_findings()
    result = {'scope': 'offline_focused_reliability', 'command': command, 'audit_findings': findings,
              'paid_model_calls': 0, 'client_activation_gate': False}
    code = 1
    if not findings:
        try:
            with tempfile.TemporaryDirectory(prefix='clinical-offline-office-') as directory:
                environment, office = test_environment(Path(directory))
                result['renderer_path_for_pytest'] = office
                completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=args.timeout, env=environment)
            code = completed.returncode
            result.update(stdout=completed.stdout, stderr=completed.stderr)
        except subprocess.TimeoutExpired as exc:
            result['error'] = f'Local developer check exceeded {args.timeout:g} seconds'
            # TimeoutExpired may contain bytes even when text=True.
            result['stdout'] = exc.stdout.decode(errors='replace') if isinstance(exc.stdout, bytes) else exc.stdout or ''
    result.update(status='passed' if code == 0 else 'failed', elapsed_seconds=time.monotonic()-started)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
