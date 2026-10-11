"""Condition-level authority for migrated checks; legacy producers remain explicit gaps.

A registered semantic condition supplies review evidence, not an objective veto.
Only production producers attach these records. Reviewer findings never acquire
waiver authority by copying a rule ID into a response.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


RULES: dict[str, dict[str, Any]] = {
    'protocol.source-coverage.lexical': {
        'rule_id': 'protocol.source-coverage.lexical',
        'version': 1,
        'producer': 'scripts/quality.py::deterministic_content_check',
        'condition': 'Rendered narrative source coverage has only lexical uncertainty; quantity mismatches are excluded.',
        'code': 'protocol-source-coverage-proxy',
        'authority': 'semantic_evidence',
        'applicability': {'study_types': ['Prospective', 'Ambispective', 'Retrospective'],
                          'artifacts': ['protocol'], 'templates': ['all']},
        'evidence': ['approved source paths and diagnostics', 'current native section passage'],
        'repair_route': 'section_drafting',
        'adjudication_route': 'clinical_content_verification',
        'verification': ['source-grounded explicit disposition', 'current exact-artifact content review',
                         'every-page visual review', 'complete exact-byte Desktop delivery'],
        'behavioral_coverage': {
            'status': 'controlled_public_lifecycle',
            'tests': [
                'tests/test_rule_adjudication.py::test_registered_protocol_proxy_delivers_unchanged_with_rule_bound_decision',
                'tests/test_rule_adjudication.py::test_registered_decision_rejects_unbound_or_fabricated_authority',
                'tests/test_rule_adjudication.py::test_registered_faithful_decision_does_not_clear_companion_defect',
            ],
            'live_evidence': 'owner-run; not claimed by local tests',
        },
    },
}


def rule_contract(rule_id: str) -> dict[str, Any]:
    """Return a copy, so callers cannot mutate authority for another finding."""
    return json.loads(json.dumps(RULES[rule_id]))


def rule_contract_sha256(rule_id: str) -> str:
    return hashlib.sha256(json.dumps(rule_contract(rule_id), sort_keys=True,
                                     ensure_ascii=False).encode()).hexdigest()


def attach_rule(finding: Mapping[str, Any], rule_id: str) -> dict[str, Any]:
    """Bind a production condition to its registered authority, independently of severity."""
    rule = rule_contract(rule_id)
    return {**dict(finding), 'code': rule['code'], 'rule_id': rule_id,
            'rule_version': rule['version'], 'rule_contract_sha256': rule_contract_sha256(rule_id)}


def semantic_rule(finding: Mapping[str, Any]) -> dict[str, Any] | None:
    """Recognize only exact current contracts; unknown or stale IDs grant no waiver."""
    rule_id = finding.get('rule_id')
    if not isinstance(rule_id, str) or rule_id not in RULES:
        return None
    rule = rule_contract(rule_id)
    if (rule['authority'] != 'semantic_evidence'
            or finding.get('code') != rule['code']
            or finding.get('rule_version') != rule['version']
            or finding.get('rule_contract_sha256') != rule_contract_sha256(rule_id)):
        return None
    return rule
