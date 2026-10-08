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
    'test_concept_reference_grounding.py',
    'test_owner_aware_recovery.py', 'test_cause_aware_recovery.py',
    'test_complete_delivery_policy.py', 'test_complete_delivery_replay.py',
    'test_complete_delivery_icf.py', 'test_complete_delivery_publication.py', 'test_complete_delivery_message.py',
    'test_editorial_publication.py', 'test_phase1_repetition.py',
)


def _functions(tree, prefix=""):
    """Discover methods and conditional/nested producers, using stable names."""
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        scope = []
        cursor = parents.get(node)
        while cursor is not None:
            if isinstance(cursor, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                scope.append(cursor.name)
            cursor = parents.get(cursor)
        yield prefix + ".".join([*reversed(scope), node.name]), node


def _policy_calls(node):
    return [item for item in ast.walk(node) if isinstance(item, ast.Call)
            and isinstance(item.func, ast.Name) and item.func.id in {"classify_finding", "declare_finding"}]


def policy_declarations(node):
    """Record each explicit producer reason separately from code fingerprints."""
    result = []
    for call in _policy_calls(node):
        values = {kw.arg: ast.unparse(kw.value) for kw in call.keywords}
        result.append({key: values.get(key) for key in ("classification", "reason", "repair_owner")})
    return sorted(result, key=lambda row: json.dumps(row, sort_keys=True))


def policy_findings(root: Path = ROOT) -> list[str]:
    """Developer-only contract checks; never imported by ordinary generation."""
    audit = json.loads((root / AUDIT.relative_to(ROOT)).read_text())
    declarations = {(row["file"], row["function"]): row for row in audit["checks"]}
    result = []
    for path in sorted((root / "scripts").glob("*.py")):
        tree = ast.parse(path.read_text())
        relative = path.relative_to(root).as_posix()
        for name, node in _functions(tree):
            record = declarations.get((relative, name))
            if record is None or record.get("scope") == "separate":
                continue
            location = f"{relative}:{name}"
            parents = {child: item for item in ast.walk(node) for child in ast.iter_child_nodes(item)}
            calls = _policy_calls(node)
            for call in calls:
                keys = {kw.arg for kw in call.keywords}
                if not {"classification", "reason", "repair_owner"} <= keys:
                    result.append(f"Incomplete finding policy: {location}")
            if "policy_declarations" in record and policy_declarations(node) != record["policy_declarations"]:
                result.append(f"Finding reason/classification/owner audit requires review: {location}")
            for item in ast.walk(node):
                if isinstance(item, ast.Dict):
                    keys = {k.value for k in item.keys if isinstance(k, ast.Constant)}
                    if "issue" not in keys:
                        continue
                    signature = hashlib.sha256(ast.unparse(item).encode()).hexdigest()
                    if signature in record.get("diagnostic_record_sites", {}):
                        continue
                    cursor = parents.get(item)
                    classified = any(isinstance(value, ast.Call) and value in calls for value in item.values)
                    while cursor is not None and not isinstance(cursor, (ast.Assign, ast.Return, ast.Expr)):
                        classified |= cursor in calls
                        cursor = parents.get(cursor)
                    if not classified and "finding_policy" not in keys:
                        result.append(f"Unclassified finding producer: {location}:{item.lineno}")
                if isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute) and item.func.attr == "get":
                    if item.args and isinstance(item.args[0], ast.Constant) and item.args[0].value == "publication_disposition":
                        result.append(f"Raw finding decision: {location}:{item.lineno}")
                if record.get("role") == "decision" and isinstance(item, (ast.If, ast.IfExp)):
                    inputs = set(record.get("decision_inputs", []))
                    test = item.test
                    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
                        test = test.operand
                    if isinstance(test, ast.Call) and isinstance(test.func, ast.Name) and test.func.id == "bool" and len(test.args) == 1:
                        test = test.args[0]
                    if isinstance(test, ast.Name) and test.id in inputs:
                        result.append(f"Raw finding decision: {location}:{item.lineno}")
    return sorted(set(result))


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
        for qualified_name, node in _functions(tree):
            strings = {item.value for item in ast.walk(node) if isinstance(item, ast.Constant) and isinstance(item.value, str)}
            shared_helpers = {
                'classify_finding', 'declare_finding', 'normalize_finding', 'recovery_finding',
                '_validate', 'finding_classification', 'blocks_construction', 'blocks_publication',
                '_leaf_texts', '_grounding_tokens', '_evidence_diagnostics',
                'evidence_grounded', 'source_evidence_diagnostics', 'source_evidence_grounded',
                'hypothesis_claim_issues', '_timeline_grounded', '_material_source',
                'section_evidence_value', 'semantic_evidence_contract', 'assessment_matrix',
                'normalized_visit_records', 'protocol_table_contracts', 'sterling_draft_word_budget',
                '_matrix_visit_alias', '_schedule_activity_identity', 'lexical_evidence_uncertainty',
                '_lexical_review_cautions', '_reviewed_lexical_warnings',
                'participant_followup_summary', 'computed_study_fields', 'protocol_section_snapshot', 'rendered_section_snapshot',
                '_rendered_heading_text', '_target_heading',
                '_recovery_action_observation', '_governed_editorial_warning', '_fidelity_evidence',
                '_accepted_drafting_warnings', '_render_warnings',
                'renderers',
                'normalized_day_quantity', '_approved_screening_interval',
                'screening_interval_requirement', 'screening_interval_in_text', 'prs_candidate_findings',
                '_validation_screening_interval_requirement', '_screening_interval_requirement_from_xml',
                'semantic_evidence_inventory', '_source_field_inventory', 'create_verification_requests',
            }
            if not {'issue', 'blocked', 'publication_disposition', 'finding_policy', 'terminal_status'} & strings and node.name not in shared_helpers:
                continue
            # AST dumps change when Python adds fields (for example, type_params in
            # 3.12). Hash the source instead so one audit works on every runtime.
            first_line = min([node.lineno, *(decorator.lineno for decorator in node.decorator_list)])
            function_source = ''.join(lines[first_line - 1:node.end_lineno])
            records.append({
                'file': path.relative_to(root).as_posix(), 'function': qualified_name,
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
    return findings + policy_findings(root)


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
