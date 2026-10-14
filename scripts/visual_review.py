"""Bounded visual assignments and authenticated, durable partial judgments.

Code owns coverage and bytes, never the meaning of a visual judgment. Pages,
inter-page boundaries and whole-document usability each have an explicit owner.
"""
from __future__ import annotations

import copy
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Mapping, Sequence

import quality
from drafting import sha256_value

BOUNDARY_CHECKS = ['table_flow', 'heading_continuity', 'header_footer_continuity']
DOCUMENT_CHECKS = ['toc_destinations', 'toc_mismatch', 'document_continuity', 'template_preservation']
PAGE_CHECKS = [check for check in quality.VISUAL_CHECKS if check != 'toc_mismatch']


def _read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('Visual evidence must be an object')
    return value


def _owned(revision: Path, path: Path) -> bool:
    return quality._revision_owned_nonsymlink_path(revision, path)


def _write(revision: Path, path: Path, value: Mapping) -> None:
    quality._assert_safe_mutation_path(path, directory=False)
    if not _owned(revision, path):
        raise ValueError('Visual evidence escapes revision')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.' + path.name + f'.{os.getpid()}.tmp')
    quality._assert_safe_mutation_path(temporary, directory=False)
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    os.replace(temporary, path)


def visual_review_plan(parent: Mapping) -> dict:
    targets = []
    for artifact in parent.get('artifacts', []):
        name, pages = artifact['artifact'], artifact.get('pages', [])
        for page in pages:
            targets.append({'target_id': f"{name}:page:{page['page']}", 'kind': 'page',
                'artifact': name, 'pages': [copy.deepcopy(page)], 'checks': list(PAGE_CHECKS)})
        for left, right in zip(pages, pages[1:]):
            targets.append({'target_id': f"{name}:boundary:{left['page']}-{right['page']}",
                'kind': 'boundary', 'artifact': name, 'pages': [copy.deepcopy(left), copy.deepcopy(right)],
                'checks': list(BOUNDARY_CHECKS)})
        if pages:
            # Document observer combines exact independent page/boundary notes
            # with native structure and actual title/TOC/end images. This is
            # additional global review, never a substitute for every-page QA.
            anchors = [p for i, p in enumerate(pages) if i in {0, 1, len(pages) - 1}]
            targets.append({'target_id': f'{name}:document', 'kind': 'document',
                'artifact': name, 'pages': copy.deepcopy(anchors), 'checks': list(DOCUMENT_CHECKS)})
    return {'schema_version': 'visual-review-plan/v1', 'max_images': 3,
        'max_parallel_units': 3, 'unit_budget_seconds': 240,
        'targets': targets}


def _parent(revision: Path, path: Path) -> dict:
    parent = _read(path)
    canonical = revision / f"hermes/verification-requests/{parent['request_id']}.json"
    if path != canonical or not _owned(revision, path) or parent.get('revision_id') != revision.name:
        raise ValueError('Visual parent identity is foreign')
    if quality.verification_request_authentication_findings(revision, path, parent,
            request_id_counts={parent['request_id']: 1}):
        raise ValueError('Visual parent is stale or unbound')
    for artifact in parent.get('artifacts', []):
        bindings = [(artifact[k], artifact[k + '_sha256']) for k in ('docx', 'pdf')]
        bindings.extend((p['path'], p['sha256']) for p in artifact.get('pages', []))
        for relative, digest in bindings:
            evidence = revision / relative
            if not _owned(revision, evidence) or quality.sha256_file(evidence) != digest:
                raise ValueError('Visual native/PDF/page evidence is stale or foreign')
    if parent.get('visual_review_plan') != visual_review_plan(parent):
        raise ValueError('Visual coverage plan is incomplete or changed')
    if not parent['visual_review_plan']['targets']:
        raise ValueError('Visual parent has no page evidence')
    return parent


def create_visual_review_unit(revision: Path, parent_path: Path,
                              targets: Sequence[Mapping], attempt: int,
                              *, observer_evidence_required: bool = False) -> Path:
    """Create immutable bounded assignments; overlap in image access is not scope overlap."""
    parent = _parent(revision, parent_path)
    expected = parent['visual_review_plan']['targets']
    images = {p['path'] for t in targets for p in t['pages']}
    ids = [t['target_id'] for t in targets]
    if (not targets or len(ids) != len(set(ids)) or any(t not in expected for t in targets)
            or len(images) > parent['visual_review_plan']['max_images']
            or (any(t['kind'] == 'document' for t in targets) and len(targets) != 1)
            or type(attempt) is not int or attempt < 1):
        raise ValueError('Visual unit exceeds authenticated scope or image capacity')
    scope = copy.deepcopy(list(targets))
    request_id = parent['request_id'] + '.visual-unit-' + sha256_value(scope)[:16] + ('.callback' if observer_evidence_required else '') + f'.a{attempt}'
    prefix = f'hermes/visual-review'
    unit = {k: copy.deepcopy(parent[k]) for k in (
        'schema_version', 'task', 'revision_id', 'review_set', 'artifacts')}
    unit['checks'] = list(dict.fromkeys(check for target in scope for check in target['checks']))
    for key in ('source_identity_sha256', 'generation_authority_sha256', 'renderer',
                'page_renderer', 'review_context', 'template_preservation', 'contracted_template_bundle',
                'callback_release_binding'):
        if key in parent:
            unit[key] = copy.deepcopy(parent[key])
    # Keep full native/PDF binding but restrict images to exactly assigned access.
    for artifact in unit['artifacts']:
        artifact['pages'] = [p for p in artifact['pages'] if p['path'] in images]
    unit.update(request_id=request_id, parent_request_id=parent['request_id'],
        observer_evidence_required=observer_evidence_required,
        parent_request_sha256=parent['request_sha256'],
        parent_request_path=parent_path.relative_to(revision).as_posix(), visual_scope=scope,
        response_path=f'{prefix}-responses/{request_id}.json',
        review_transport={'progress_path': f'{prefix}-progress/{request_id}.json'},
        instructions='Independently inspect ONLY assigned visual_scope. Open every assigned PNG with vision tools; '
        'no text-only or file-existence approval. Explicitly judge each target and each check. '
        'For document scope, read parent native DOCX plus accepted page/boundary assessments at document_evidence; '
        'inspect title/TOC/end images and verify TOC destinations using bound per-page observations/native headings. '
        'Never infer absent page or boundary judgments. Return visual_assessments with exact target_id, kind, artifact, '
        'pages (path/page/sha256), checks, status and specific visible notes. Include substantive findings with '
        'target_id, artifact, page, check, element, issue and recommended_action. A nonpassing target requires a finding. '
        'Return bound response JSON, genuine producer identity and status passed/blocked/in_progress. Save completed '
        'judgments immediately to review_transport.progress_path using write_file; read before overwrite and preserve '
        'all completed judgments. Response finalization and cleanup are part of your allocation. '
        + str(parent.get('instructions', ''))
        + ' For this unit, the exact visual_scope and unit checks govern applicability over package-wide instructions. '
        'Page scope judges visible local layout, including TOC legibility where present, not destinations on unassigned pages. '
        'Whole-document TOC destinations and toc_mismatch remain mandatory for the later document observer, '
        'using completed bound page/boundary evidence and native headings; do not invent or waive those judgments.')
    if any(t['kind'] == 'document' for t in targets):
        snapshot = visual_review_result(revision, parent_path, publish=False)
        non_document = [t for t in expected if t['kind'] != 'document']
        if {r['target_id'] for r in snapshot['assessments']} != {t['target_id'] for t in non_document}:
            raise ValueError('Document scope requires completed every-page and boundary evidence')
        evidence_path = revision / f'{prefix}-document-evidence/{request_id}.json'
        _write(revision, evidence_path, snapshot)
        unit['document_evidence'] = {'path': evidence_path.relative_to(revision).as_posix(),
            'sha256': quality.sha256_file(evidence_path)}
    unit['request_sha256'] = quality.verification_request_sha256(unit)
    path = revision / f'{prefix}-requests/{request_id}.json'
    ledger = revision / f'{prefix}-ledgers/{request_id}.json'
    if path.exists():
        if _read(path) != unit:
            raise ValueError('Visual assignment identity collision')
        return path  # Never overwrite an integrity rejection on resume.
    _write(revision, path, unit)
    _write(revision, ledger, {'request_sha256': unit['request_sha256'],
        'request_file_sha256': quality.sha256_file(path)})
    return path


def invalidate_visual_review_units(revision: Path, paths: Sequence[Path], finding: Mapping) -> None:
    """Parent-owned poison persists even after renderer bytes are restored."""
    for path in paths:
        if path.parent != revision / 'hermes/visual-review-requests':
            continue
        unit = _read(path)
        ledger = revision / f"hermes/visual-review-ledgers/{unit['request_id']}.json"
        if not _owned(revision, ledger) or not _owned(revision, path):
            raise ValueError('Visual rejection ledger escapes revision')
        value = _read(ledger)
        if (value.get('request_sha256') != unit.get('request_sha256')
                or value.get('request_file_sha256') != quality.sha256_file(path)
                or not quality.verification_request_hash_valid(unit)):
            raise ValueError('Visual rejection identity changed')
        value.setdefault('integrity_rejection', dict(finding))
        _write(revision, ledger, value)


def validate_visual_review_unit_request(revision: Path, path: Path) -> tuple[dict, dict, dict]:
    """Validate canonical assignment independently of absent reviewer judgments."""
    unit = _read(path)
    if path != revision / f"hermes/visual-review-requests/{unit['request_id']}.json" or not _owned(revision, path):
        raise ValueError('Visual unit request escapes canonical identity')
    ledger_path = revision / f"hermes/visual-review-ledgers/{unit['request_id']}.json"
    if not _owned(revision, ledger_path):
        raise ValueError('Visual unit ledger escapes revision')
    ledger = _read(ledger_path)
    if ('integrity_rejection' in ledger or not quality.verification_request_hash_valid(unit)
            or ledger.get('request_sha256') != unit['request_sha256']
            or ledger.get('request_file_sha256') != quality.sha256_file(path)):
        raise ValueError('Visual unit identity rejected')
    parent = _parent(revision, revision / unit['parent_request_path'])
    if (unit['parent_request_id'] != parent['request_id']
            or unit['parent_request_sha256'] != parent['request_sha256']
            or any(t not in parent['visual_review_plan']['targets'] for t in unit['visual_scope'])):
        raise ValueError('Visual unit parent or scope changed')
    if unit.get('document_evidence'):
        bound = unit['document_evidence']
        evidence_path = revision / bound['path']
        if not _owned(revision, evidence_path) or quality.sha256_file(evidence_path) != bound['sha256']:
            raise ValueError('Visual unit document evidence changed')
    return unit, parent, ledger


def visual_review_unit_result(revision: Path, path: Path) -> dict | None:
    """Credit authentic completed targets independently from malformed sibling files."""
    try:
        unit, parent, ledger = validate_visual_review_unit_request(revision, path)
        ledger_path = revision / f"hermes/visual-review-ledgers/{unit['request_id']}.json"
        accepted, findings, proofs = {}, [], []
        expected = {t['target_id']: t for t in unit['visual_scope']}
        for relative in (unit['review_transport']['progress_path'], unit['response_path']):
            response_path = revision / relative
            if not response_path.is_file() or not _owned(revision, response_path):
                continue
            try:
                response = _read(response_path)
                if unit.get('observer_evidence_required'):
                    attestation = (ledger.get('observer_attestations') or {}).get(relative) or {}
                    if (attestation.get('response_sha256') != quality.sha256_file(response_path)
                            or attestation.get('producer') != response.get('producer')
                            or attestation.get('observer_evidence') != response.get('observer_evidence')):
                        continue
                    from tui_visual_callback import observer_metadata
                    retained = response['observer_evidence']
                    state = Path(retained['state_path'])
                    if (not _owned(revision, state) or state.parent != revision / 'hermes/visual-review-observers'
                            or retained.get('database_sha256') != quality.sha256_file(state / 'state.db')):
                        continue
                    from owned_observer_runtime import validate_owned_observer_cleanup, OwnedObserverLifetimeUnresolved
                    try:
                        validate_owned_observer_cleanup(state)
                    except (OwnedObserverLifetimeUnresolved, OSError, ValueError, KeyError, TypeError):
                        ledger['integrity_rejection'] = {
                            'reason': 'Owned observer descendant cleanup proof missing or invalid',
                            'observer_state_path': state.relative_to(revision).as_posix()}
                        _write(revision, ledger_path, ledger)
                        return None  # Revoke this unit, including any earlier checkpoint credit.
                    observed = observer_metadata(state, revision, unit)
                    if (not observed['request_inspection_complete']
                            or not isinstance(response.get('producer'), dict)
                            or response.get('producer', {}).get('reviewer_id') != observed['session_id']
                            or response.get('producer', {}).get('model_id') != observed['model_id']
                            or any(observed[k] != retained.get(k) for k in ('session_id', 'model_id', 'image_tool_results'))
                            or observed.get('provenance_sha256') != retained.get('provenance_sha256')):
                        continue
                    allowed = {t['target_id'] for t in unit['visual_scope']
                        if all(p['path'] in observed['inspected_paths'] for p in t['pages'])
                        and (t['kind'] != 'document' or observed['native_inspection_complete'])}
                    if any(not isinstance(response.get(k), list)
                            or any(not isinstance(r, dict) for r in response[k])
                            for k in ('visual_assessments', 'findings')):
                        continue
                    if (any(r.get('target_id') not in allowed for r in response['visual_assessments'])
                            or any(f.get('target_id') not in allowed for f in response['findings'])):
                        continue
                if (response.get('schema_version') != quality.RESPONSE_SCHEMA
                        or any(response.get(k) != unit[k] for k in ('request_id', 'request_sha256', 'task', 'revision_id'))
                        or response.get('status') not in {'passed', 'blocked', 'failed', 'in_progress'}):
                    continue
                producer = response.get('producer')
                authors = (parent.get('review_context') or {}).get('repair_authors', [])
                if (not isinstance(producer, dict) or any(not isinstance(producer.get(k), str)
                        or not producer[k].strip() for k in ('model_id', 'reviewer_id'))
                        or any(a.get('reviewer_id') == producer['reviewer_id'] for a in authors)):
                    continue
                rows, issues = response.get('visual_assessments'), response.get('findings')
                if (not isinstance(rows, list) or not isinstance(issues, list)
                        or any(not isinstance(f, dict) or not isinstance(f.get('issue'), str)
                            or not f['issue'].strip() or f.get('target_id') not in expected
                            or f.get('artifact') != expected[f['target_id']]['artifact']
                            or type(f.get('page')) is not int
                            or f['page'] not in {p['page'] for p in expected[f['target_id']]['pages']}
                            or not isinstance(f.get('check'), str) or not isinstance(f.get('element'), str)
                            or not isinstance(f.get('recommended_action'), str) for f in issues)
                        or any(not isinstance(r, dict) or r.get('target_id') not in expected for r in rows)
                        or len({r['target_id'] for r in rows}) != len(rows)):
                    continue
                credited = []
                for row in rows:
                    target = expected[row['target_id']]
                    if (any(row.get(k) != v for k, v in target.items())
                            or row.get('status') not in {'passed', 'blocked', 'failed'}
                            or not (isinstance(row.get('notes'), str) and row['notes'].strip()
                                or isinstance(row.get('notes'), dict) and row['notes']
                                and all(isinstance(k, str) and isinstance(v, str) and v.strip()
                                        for k, v in row['notes'].items()))):
                        continue
                    covering = [f for f in issues if f['target_id'] == row['target_id']]
                    if (row['status'] == 'passed') == bool(covering):
                        continue  # contradictory pass or uncovered nonpass
                    if response['status'] == 'passed' and row['status'] != 'passed':
                        continue
                    credited.append({**row, 'producer': producer})
                proof = {'request_path': path.relative_to(revision).as_posix(),
                    'request_sha256': quality.sha256_file(path), 'response_path': relative,
                    'response_sha256': quality.sha256_file(response_path), 'producer': producer,
                    'observer_evidence': response.get('observer_evidence')}
                if credited or issues:
                    proofs.append(proof)
                    findings.extend({**f, 'producer': producer,
                        'finding_id': f.get('finding_id') or sha256_value({
                            'parent': parent['request_sha256'], 'target_id': f['target_id'], 'issue': f['issue']})[:24]}
                        for f in issues)
                for row in credited:
                    key = row['target_id']
                    if key not in accepted or row['status'] != 'passed':
                        accepted[key] = {**row, 'proof': proof}
            except (OSError, ValueError, KeyError, TypeError, sqlite3.DatabaseError):
                continue
        if not accepted and not findings:
            return None
        return {'assessments': list(accepted.values()), 'findings': findings, 'proofs': proofs,
            'complete': set(accepted) == set(expected)}
    except (OSError, ValueError, KeyError, TypeError, sqlite3.DatabaseError):
        return None


def visual_review_result(revision: Path, parent_path: Path, *, publish: bool = True) -> dict:
    """Recombine real judgments only; unchanged bytes cannot unpoison a rejected wave."""
    parent = _parent(revision, parent_path)
    expected = parent['visual_review_plan']['targets']
    rows, findings, proofs = {}, [], []
    for path in sorted((revision / 'hermes/visual-review-requests').glob('*.json')):
        try:
            if not _owned(revision, path):
                continue
            unit = _read(path)
        except (OSError, ValueError):
            continue  # Malformed siblings cannot erase productive scope.
        if unit.get('parent_request_sha256') != parent['request_sha256']:
            continue
        result = visual_review_unit_result(revision, path)
        if not result:
            continue
        findings.extend(result['findings'])
        proofs.extend(result['proofs'])
        for row in result['assessments']:
            key = row['target_id']
            # Replacement scope should not overlap. Historical partial/final
            # checkpoints may; a substantive negative always dominates.
            if key in rows and row['status'] == 'passed' and rows[key]['status'] == 'passed':
                if (row['proof']['request_path'] != rows[key]['proof']['request_path']
                        or {k: v for k, v in row.items() if k != 'proof'} != {k: v for k, v in rows[key].items() if k != 'proof'}):
                    raise ValueError('Overlapping independent visual judgments')
            if key not in rows or row['status'] != 'passed':
                rows[key] = row
    findings = list({sha256_value(f): f for f in findings}.values())
    missing = [t for t in expected if t['target_id'] not in rows]
    result = {'assessments': list(rows.values()), 'missing': missing, 'findings': findings,
        'proofs': proofs, 'complete': not missing}
    if publish and (result['complete'] or findings) and rows:
        assessments = list(rows.values())
        producer = assessments[0]['producer']  # actual observer, not fictional orchestrator
        response = {'schema_version': quality.RESPONSE_SCHEMA,
            **{k: parent[k] for k in ('request_id', 'request_sha256', 'task', 'revision_id')},
            'producer': producer, 'status': 'blocked' if findings or any(r['status'] != 'passed' for r in assessments) else 'passed',
            'findings': findings, 'visual_assessments': assessments, 'unit_proofs': proofs,
            'visual_scheduler_partial': not result['complete'],
            'composition': 'authenticated independent visual units; each row retains its actual observer',
            'page_assessments': [{'artifact': r['artifact'], 'page': r['pages'][0]['page'],
                'sha256': r['pages'][0]['sha256'], 'checks': r['checks'], 'status': r['status'],
                'notes': r['notes'], 'producer': r['producer']} for r in assessments if r['kind'] == 'page']}
        _write(revision, revision / parent['response_path'], response)
    return result


def visual_response_coverage_errors(revision: Path, request: Mapping, response: Mapping) -> list[str]:
    if not request.get('visual_review_plan'):
        return []  # Retained pre-plan review requests keep their original contract.
    expected = request['visual_review_plan']['targets']
    rows = response.get('visual_assessments')
    partial = response.get('visual_scheduler_partial') is True and response.get('status') == 'blocked'
    if (not isinstance(rows, list) or any(not isinstance(r, dict) or not isinstance(r.get('target_id'), str) for r in rows)
            or len({r['target_id'] for r in rows}) != len(rows)
            or not {r['target_id'] for r in rows} <= {t['target_id'] for t in expected}
            or (not partial and len(rows) != len(expected))):
        return ['Every page, boundary and document target must have one authenticated judgment.']
    for row in rows:
        if not isinstance(row, dict):
            return ['Malformed visual target judgment.']
        target = next(t for t in expected if t['target_id'] == row['target_id'])
        if any(row.get(k) != v for k, v in target.items()):
            return ['Visual target scope or exact page binding changed.']
        proof = row.get('proof') or {}
        try:
            path = revision / proof['request_path']
            result = visual_review_unit_result(revision, path)
            if not result or row not in result['assessments']:
                return ['Visual judgment has missing, stale or rejected unit evidence.']
        except (KeyError, TypeError):
            return ['Visual judgment lacks authenticated observer evidence.']
    try:
        assembled = visual_review_result(revision,
            revision / f"hermes/verification-requests/{request['request_id']}.json", publish=False)
        if response.get('findings') != assembled['findings'] or response.get('unit_proofs') != assembled['proofs']:
            return ['Final visual findings or proofs differ from authenticated completed judgments.']
        pages = [{'artifact': r['artifact'], 'page': r['pages'][0]['page'],
            'sha256': r['pages'][0]['sha256'], 'checks': r['checks'], 'status': r['status'],
            'notes': r['notes'], 'producer': r['producer']} for r in rows if r['kind'] == 'page']
        if response.get('page_assessments') != pages:
            return ['Final page judgments differ from authenticated visual targets.']
        if response.get('status') == 'passed' and (assembled['findings'] or any(r['status'] != 'passed' for r in rows)):
            return ['A passing response contradicts a substantive visual judgment.']
        if partial:
            if rows != assembled['assessments'] or not assembled['findings'] or assembled['complete']:
                return ['Malformed partial visual finding transport.']
            return ['Visual scope incomplete; authenticated substantive findings are ready for repair.']
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return ['Cannot authenticate complete visual recombination: ' + str(exc)]
    return []


def run_visual_review(revision: Path, parent_path: Path, dispatch, remaining_seconds: float,
                      *, clock=None, observer_evidence_required: bool = False) -> dict:
    """Schedule bounded waves inside one caller allocation; retain partial progress on errors."""
    import time
    clock = clock or time.monotonic
    deadline = clock() + max(0.0, remaining_seconds)
    parent = _parent(revision, parent_path)
    plan = parent['visual_review_plan']
    no_progress = 0
    errors = []
    while True:
        result = visual_review_result(revision, parent_path)
        if result['complete'] or result['findings']:
            return {**result, 'dispatch_errors': errors}
        available = deadline - clock()
        reserve = min(15.0, max(5.0, remaining_seconds / 10))
        if available <= reserve or no_progress >= 2:
            return {**result, 'dispatch_errors': errors}
        missing = result['missing']
        ordinary = [t for t in missing if t['kind'] != 'document']
        pending = ordinary or missing
        groups = []
        image_capacity = min(2, plan['max_images']) if no_progress else plan['max_images']
        for target in pending:
            compatible = next((group for group in groups
                if target['kind'] != 'document' and group[0]['kind'] != 'document'
                and len({p['path'] for t in [*group, target] for p in t['pages']}) <= image_capacity), None)
            if compatible is not None:
                compatible.append(target)
            else:
                groups.append([target])
        paths = []
        for group in groups[:plan['max_parallel_units']]:
            prefix = parent['request_id'] + '.visual-unit-' + sha256_value(group)[:16] + ('.callback' if observer_evidence_required else '') + '.a'
            historical = list((revision / 'hermes/visual-review-requests').glob(prefix + '*.json'))
            attempt = max([int(p.stem.rsplit('.a', 1)[1]) for p in historical] or [0]) + 1
            paths.append(create_visual_review_unit(revision, parent_path, group, attempt,
                observer_evidence_required=observer_evidence_required))
        handoffs = []
        for path in paths:
            unit = _read(path)
            handoffs.append({'task': unit['task'], 'request_path': path.relative_to(revision).as_posix(),
                'response_path': unit['response_path'], 'request_id': unit['request_id'],
                'request_sha256': unit['request_sha256'], 'visual_unit': True})
        # Reserve a follow-up wave only when unassigned groups remain.
        # Halving the final scope's allocation starves document review even
        # though there is no later scope to fund.
        waves_left = (len(groups) + plan['max_parallel_units'] - 1) // plan['max_parallel_units']
        if ordinary and any(t['kind'] == 'document' for t in missing):
            waves_left += 1  # document evidence depends on completed local scopes
        budget = min(float(plan['unit_budget_seconds']), (available - reserve) / max(1, waves_left))
        try:
            dispatch(handoffs, budget)
        except Exception as exc:
            if getattr(exc, 'storage_reclamation_deferred', False):
                # Completed authenticated scope remains partial unless all
                # required judgments really completed. Allocate no new wave.
                updated = visual_review_result(revision, parent_path)
                return {**updated, 'dispatch_errors': [*errors, type(exc).__name__ + ': ' + str(exc)],
                    'resource_deferred': getattr(exc, 'diagnostics', {})}
            if getattr(exc, 'storage_retention_failure', False):
                # Storage eligibility failure is not renderer poisoning or a
                # visual judgment. Preserve authenticated completed work, but
                # do not allocate another observer wave on a failed budget premise.
                raise
            integrity = getattr(exc, 'worker_integrity_failure', None)
            if integrity:
                invalidate_visual_review_units(revision, paths, integrity)
            errors.append(type(exc).__name__ + ': ' + str(exc))
            if integrity:
                raise  # Do not retry a poisoned renderer in the same wave.
        updated = visual_review_result(revision, parent_path)
        no_progress = no_progress + 1 if len(updated['assessments']) <= len(result['assessments']) else 0


def callback_release_binding(root: Path) -> dict:
    """Bind the installed manifest and actual implementation at callback launch."""
    import workflow
    root = root.absolute()
    identity = workflow._installed_release_identity(root)
    paths = ['scripts/tui_visual_callback', 'scripts/tui_visual_callback.py',
             'scripts/visual_review.py', 'scripts/workflow.py', 'scripts/quality.py', 'scripts/storage_retention.py',
             'scripts/owned_observer_process.py', 'scripts/owned_observer_runtime.py']
    return {'release_root': str(root), 'release_identity': identity,
        'manifest_sha256': quality.sha256_file(root / workflow.RELEASE_MANIFEST),
        'source_sha256': {p: quality.sha256_file(root / p) for p in paths}}


def validate_callback_probe(command: Path, evidence: Path, identity: dict) -> dict:
    """Admit only retained genuine exact-candidate image/fallback evidence."""
    try:
        import workflow
        report = json.loads(evidence.read_text())
        revision = Path(report['revision_path'])
        run = revision.parent.parent
        # The outer report is an index, never identity or success authority.
        operation = _read(run / 'logs/desktop-operation.json')
        persisted_identity = operation['release_identity']
        if (report.get('scope') != 'synthetic callback transport; no clinical approval'
                or report.get('exception') is not None
                or any(persisted_identity.get(k) != identity.get(k) for k in ('package_fingerprint', 'git_commit'))
                or persisted_identity.get('host_mode') != 'hermes-tui'
                or persisted_identity.get('probe_scope')
                or report.get('operation') != operation.get('result')):
            raise ValueError('Contradictory or development-only persisted operation identity')
        binding = callback_release_binding(command.parent.parent)
        if (persisted_identity.get('callback_release_binding') != binding
                or persisted_identity.get('parent_visual_callback') != {'path': str(command), 'sha256': quality.sha256_file(command)}
                or report.get('callback_path') != str(command)):
            raise ValueError('Persisted operation did not launch this installed callback binding')
        if any(binding['release_identity'].get(k) != identity.get(k) for k in ('package_fingerprint', 'git_commit')):
            raise ValueError('Probe identity differs from intact installed candidate')
        parent_path = revision / report['parent_request_path']
        parent = _parent(revision, parent_path)
        if parent.get('callback_release_binding') != binding:
            raise ValueError('Parent request lacks exact installed callback binding')
        if (report.get('request_path') != str(parent_path)
                or report.get('request_sha256') != quality.sha256_file(parent_path)
                or report.get('response_path') != str(revision / parent['response_path'])
                or report.get('response_sha256') != quality.sha256_file(revision / parent['response_path'])
                or not quality.verification_response_is_complete(revision, parent_path)):
            raise ValueError('Final accepted response/request bytes differ from probe index')
        invocations = []
        for path in (run / 'logs/parent-visual-reviewer').glob('*.json'):
            diagnostic = _read(path)
            if 'request_path' not in diagnostic:
                continue
            invocation_path = Path(diagnostic['request_path'])
            if (not _owned(revision, invocation_path)
                    or diagnostic.get('request_sha256') != quality.sha256_file(invocation_path)):
                raise ValueError('Stale callback invocation evidence')
            invocation = _read(invocation_path)
            if (invocation.get('callback_release_binding') != binding
                    or invocation.get('callback_command') != {'path': str(command), 'sha256': quality.sha256_file(command)}
                    or invocation.get('managed_hermes_identity') != workflow._managed_hermes_identity()):
                raise ValueError('Callback invocation used a different installed implementation/runtime')
            if any(h.get('request_sha256') == parent['request_sha256'] for h in invocation.get('handoffs', [])):
                if diagnostic.get('returncode') != 0 or diagnostic.get('error_type') or diagnostic.get('timed_out'):
                    raise ValueError('Callback invocation did not complete successfully')
                invocations.append(invocation_path)
        if len(invocations) != 1:
            raise ValueError('Expected exactly one retained successful fallback invocation')
        result = visual_review_result(revision, parent_path, publish=False)
        diagnostics = []
        for path in (revision / 'hermes/visual-review-observers').glob('*/diagnostic.json'):
            diagnostic = _read(path)
            unit_path = revision / diagnostic['request_path']
            unit = _read(unit_path)
            if unit.get('parent_request_sha256') != parent['request_sha256']:
                continue
            provenance = _read(path.parent / 'provenance.json')
            if (unit.get('callback_release_binding') != binding
                    or provenance.get('callback_release_binding') != binding
                    or provenance.get('request_path') != diagnostic['request_path']
                    or provenance.get('request_sha256') != quality.sha256_file(unit_path)
                    or provenance.get('managed_hermes_identity') != workflow._managed_hermes_identity()):
                raise ValueError('Observer launch provenance differs from installed request/runtime')
            if diagnostic.get('returncode') == 0:
                invocation_path = Path(provenance['invocation_path'])
                if (invocation_path not in invocations
                        or provenance.get('invocation_sha256') != quality.sha256_file(invocation_path)):
                    raise ValueError('Successful observer is not linked to actual callback invocation')
            diagnostics.append(diagnostic)
        if (not any(d.get('error_type') == 'TimeoutExpired' for d in diagnostics)
                or not any(d.get('returncode') == 0 and (d.get('observer_evidence') or {}).get('image_tool_results') for d in diagnostics)
                or report.get('callback_module_sha256') != quality.sha256_file(command.parent / 'tui_visual_callback.py')
                or report.get('transport_module_sha256') != quality.sha256_file(command.parent / 'visual_review.py')):
            raise ValueError('Missing actual timeout/image diagnostics or changed callback implementation')
        if (report.get('schema_version') != 'tui-visual-callback-probe/v1'
                or report.get('candidate_identity') != identity
                or report.get('callback_sha256') != quality.sha256_file(command)
                or command.is_symlink() or not command.is_file()
                or not report.get('delegated_timeout_observed')
                or not report.get('fallback_callback_completed')
                or not result['complete'] or result['findings']):
            raise ValueError('Incomplete exact-candidate callback/fallback evidence')
        for row in result['assessments']:
            unit_path = revision / row['proof']['request_path']
            unit = json.loads(unit_path.read_text())
            observed = row['proof']['observer_evidence']
            state = Path(observed['state_path'])
            provenance = _read(state / 'provenance.json')
            if (observed.get('provenance_sha256') != quality.sha256_file(state / 'provenance.json')
                    or provenance.get('callback_release_binding') != binding
                    or Path(provenance['invocation_path']) not in invocations
                    or provenance.get('invocation_sha256') != quality.sha256_file(Path(provenance['invocation_path']))):
                raise ValueError('Accepted observer proof lacks durable callback launch binding')
            if not unit.get('observer_evidence_required'):
                raise ValueError('Unattested callback observer')
        return report
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError('callback_image_capability_unproven: ' + str(exc)) from exc
