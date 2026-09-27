#!/usr/bin/env python3
"""Developer release check using local fixtures; never a client activation gate."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / 'docs/reliability/blocking-checks.json'
# Explicit selection prevents accidental execution of live certification/corpora.
TEST_FILES = (
    'test_evidence_diagnostics.py', 'test_evidence_variations.py', 'test_offline_reliability_gate.py',
    'test_assessment_matrix.py', 'test_hypothesis_fidelity.py', 'test_sterling_rendered_scope.py',
    'test_visit_identifier_scope.py', 'test_bilateral_review_block.py', 'test_section_background_scope.py',
    'test_run04_background_regressions.py', 'test_phase2_sterling_fidelity.py', 'test_sterling_template_comments.py',
    'test_duration_reference_preservation.py', 'test_brad_editorial_feedback.py', 'test_contracts.py',
    'test_handoff_quality.py', 'test_visit_inventory_review.py', 'test_reliability_maintenance.py',
    'test_prs_quality_corrections.py', 'test_prs_xml.py', 'test_worker_readiness.py',
)


def blocking_check_inventory(root: Path = ROOT) -> list[dict[str, str]]:
    """Index direct finding/block producers, including nested checks in each function.

    This is a source-change audit, not a proof that every conditional is correct.
    Boolean helper dependencies are covered by implementation fingerprints and tests.
    """
    records = []
    for path in sorted((root / 'scripts').glob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            strings = {item.value for item in ast.walk(node) if isinstance(item, ast.Constant) and isinstance(item.value, str)}
            shared_helpers = {
                '_leaf_texts', '_grounding_tokens', '_evidence_diagnostics',
                'evidence_grounded', 'source_evidence_diagnostics', 'source_evidence_grounded',
                'hypothesis_claim_issues', '_timeline_grounded', '_material_source',
                'section_evidence_value', 'semantic_evidence_contract', 'assessment_matrix',
                'normalized_visit_records', 'protocol_table_contracts', 'sterling_draft_word_budget',
                'semantic_evidence_inventory', '_source_field_inventory',
            }
            if not {'issue', 'blocked', 'publication_disposition'} & strings and node.name not in shared_helpers:
                continue
            records.append({
                'file': path.relative_to(root).as_posix(), 'function': node.name,
                'code_sha256': hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest(),
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
    return findings


def test_command(python: str = sys.executable) -> list[str]:
    return [python, '-m', 'pytest', *[f'tests/{name}' for name in TEST_FILES], '-q']


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
            completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=args.timeout)
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
