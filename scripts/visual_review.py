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

class IncompleteVisualReview(RuntimeError):
    """A reaped, postchecked production wave lacks complete bound judgments."""


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
    baseline = parent.get('contracted_template_bundle', {}).get('layout_preservation_baseline', {}).get('artifacts')
    rows = parent.get('template_baseline_evidence', [])
    expected_baselines = []
    if baseline:
        for artifact in parent.get('artifacts', []):
            for role in ('contracted_template', 'client_template_authority'):
                binding = baseline[artifact['artifact']][role]
                expected_baselines.append({'artifact': artifact['artifact'], 'role': role,
                    'package_path': binding['path'], 'sha256': binding['sha256'],
                    'path': f"hermes/template-baselines/{binding['sha256']}/{Path(binding['path']).name}"})
    if rows != expected_baselines:
        raise ValueError('Visual template baseline bindings are incomplete or changed')
    for row in rows:
        evidence = revision / row['path']
        if not _owned(revision, evidence) or quality.sha256_file(evidence) != row['sha256']:
            raise ValueError('Visual template baseline evidence changed or unavailable')
    if parent.get('visual_review_plan') != visual_review_plan(parent):
        raise ValueError('Visual coverage plan is incomplete or changed')
    if not parent['visual_review_plan']['targets']:
        raise ValueError('Visual parent has no page evidence')
    return parent


def _finding_followup_targets(parent: Mapping, finding: Mapping) -> list[dict]:
    """Bind pixel follow-up to the location and both adjoining boundaries."""
    return [t for t in parent['visual_review_plan']['targets']
        if t['artifact'] == finding['artifact'] and t['kind'] != 'document'
        and finding['page'] in {p['page'] for p in t['pages']}]


def _unit_scope_identity(scope: Sequence[Mapping], followup: Sequence[Mapping]) -> str:
    return sha256_value({'scope': list(scope), 'finding_followup': list(followup)} if followup else list(scope))[:16]


def create_visual_review_unit(revision: Path, parent_path: Path,
                              targets: Sequence[Mapping], attempt: int,
                              *, observer_evidence_required: bool = False,
                              finding_followup: Sequence[Mapping] = (),
                              validation_feedback: Sequence[Mapping] = ()) -> Path:
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
    request_id = parent['request_id'] + '.visual-unit-' + _unit_scope_identity(scope, finding_followup) + ('.callback' if observer_evidence_required else '') + f'.a{attempt}'
    prefix = f'hermes/visual-review'
    unit = {k: copy.deepcopy(parent[k]) for k in (
        'schema_version', 'task', 'revision_id', 'review_set', 'artifacts')}
    unit['checks'] = list(dict.fromkeys(check for target in scope for check in target['checks']))
    for key in ('source_identity_sha256', 'generation_authority_sha256', 'renderer',
                'page_renderer', 'review_context', 'template_preservation', 'contracted_template_bundle',
                'template_baseline_evidence', 'callback_release_binding'):
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
    if finding_followup:
        unit['finding_followup'] = copy.deepcopy(list(finding_followup))
        unit['instructions'] += (
            ' TARGETED FOLLOW-UP: investigate every original finding in finding_followup, preserving its identity and context. '
            'Inspect each assigned exact page/boundary; do not repeat unrelated completed scope. '
            'Return finding_resolutions rows with finding_id, status confirmed/dismissed, exact target_ids and substantive notes. '
            'Generic passing judgments do not resolve an earlier concern. Resolution must be independent of its original observer.')
    if validation_feedback:
        unit['validation_feedback'] = copy.deepcopy(list(validation_feedback))
        unit['instructions'] += (' RETRY FEEDBACK: address the precise validation_feedback for this assigned scope; '
            'it describes rejected transport/judgments, not a new visual finding or permission to repeat accepted scope.')
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
        'request_file_sha256': quality.sha256_file(path),
        'assignment_validation_feedback': copy.deepcopy(unit.get('validation_feedback', []))})
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
    if unit.get('template_baseline_evidence') != parent.get('template_baseline_evidence'):
        raise ValueError('Visual unit template baseline assignment changed')
    for key in ('schema_version', 'task', 'revision_id', 'review_set',
            'source_identity_sha256', 'generation_authority_sha256', 'renderer', 'page_renderer',
            'review_context', 'template_preservation', 'contracted_template_bundle', 'callback_release_binding'):
        if unit.get(key) != parent.get(key):
            raise ValueError('Visual unit canonical parent metadata changed: ' + key)
    scope = unit['visual_scope']
    feedback = unit.get('validation_feedback', [])
    if (not isinstance(feedback, list)
            or feedback != ledger.get('assignment_validation_feedback', [])
            or any(not isinstance(f, dict)
                or set(f) != {'category', 'issue', 'target_ids', 'channel'}
                or any(not isinstance(f.get(k), str) or not f[k].strip()
                    for k in ('category', 'issue', 'channel'))
                or not isinstance(f.get('target_ids'), list) or not f['target_ids']
                or any(not isinstance(k, str) for k in f['target_ids'])
                or not set(f['target_ids']) <= {t['target_id'] for t in scope}
                for f in feedback)):
        raise ValueError('Visual unit canonical retry feedback changed or escapes scope')
    images = {p['path'] for t in scope for p in t['pages']}
    artifacts = copy.deepcopy(parent['artifacts'])
    for artifact in artifacts:
        artifact['pages'] = [p for p in artifact['pages'] if p['path'] in images]
    if (unit.get('artifacts') != artifacts or not scope
            or len({t['target_id'] for t in scope}) != len(scope)
            or len(images) > parent['visual_review_plan']['max_images']
            or any(t['kind'] == 'document' for t in scope) and len(scope) != 1
            or unit.get('checks') != list(dict.fromkeys(c for t in scope for c in t['checks']))
            or type(unit.get('observer_evidence_required')) is not bool):
        raise ValueError('Visual unit canonical scope or artifact metadata changed')
    prefix = parent['request_id'] + '.visual-unit-' + _unit_scope_identity(scope, unit.get('finding_followup', []))
    prefix += '.callback' if unit['observer_evidence_required'] else ''
    suffix = unit['request_id'].removeprefix(prefix + '.a')
    if not suffix.isdigit() or suffix.startswith('0') or unit['request_id'] != prefix + '.a' + suffix:
        raise ValueError('Visual unit canonical assignment identity changed')
    if (unit.get('response_path') != f"hermes/visual-review-responses/{unit['request_id']}.json"
            or unit.get('review_transport') != {'progress_path': f"hermes/visual-review-progress/{unit['request_id']}.json"}):
        raise ValueError('Visual unit canonical mutation paths changed')
    for context in unit.get('finding_followup', []):
        proof = context['proof']
        source_path = revision / proof['request_path']
        source = _read(source_path)
        if (source.get('finding_followup') or source.get('parent_request_sha256') != parent['request_sha256']
                or not _owned(revision, source_path) or quality.sha256_file(source_path) != proof['request_sha256']):
            raise ValueError('Visual follow-up source identity changed')
        source_result = visual_review_unit_result(revision, source_path)
        if (not source_result or context['finding'] not in source_result['findings']
                or proof != context['finding'].get('proof')
                or context['finding'].get('evidence_status') != 'needs_visual_followup'
                or context['target_ids'] != [t['target_id'] for t in _finding_followup_targets(parent, context['finding'])]
                or not set(context['target_ids']) & {t['target_id'] for t in scope}):
            raise ValueError('Visual follow-up concern or exact evidence changed')
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
        accepted, findings, proofs, feedback, resolutions = {}, [], [], [], []
        coverage = set()
        expected = {t['target_id']: t for t in unit['visual_scope']}

        def report(category, issue, target_ids, channel):
            feedback.append({'category': category, 'issue': issue,
                'target_ids': list(target_ids), 'channel': channel})
        # Transport diagnostics may be the only retained output of a clean,
        # incomplete observer. Keep them in the result sent to missing-scope
        # replacements, not just in the local ledger overwritten below.
        for entry in ledger.get('observer_transport_feedback', []):
            if (isinstance(entry, dict) and isinstance(entry.get('target_ids'), list)
                    and all(isinstance(entry.get(k), str) for k in ('category', 'issue', 'channel'))):
                ids = [k for k in entry['target_ids'] if isinstance(k, str) and k in expected]
                if ids:
                    report(entry['category'], entry['issue'], ids, entry['channel'])
        channels = [unit['review_transport']['progress_path'], unit['response_path']]
        extras = ledger.get('observer_final_channels', [])

        def revoke(reason, relative):
            ledger['integrity_rejection'] = {'reason': reason, 'response_path': relative}
            _write(revision, ledger_path, ledger)
            return None

        if not isinstance(extras, list) or any(not isinstance(r, str) for r in extras):
            return revoke('Authenticated observer final channel inventory rejected', '')
        if unit.get('observer_evidence_required'):
            channels.extend(r for r in extras if r not in channels)
        for relative in dict.fromkeys(channels):
            response_path = revision / relative
            attestation = (ledger.get('observer_attestations') or {}).get(relative) or {}
            if not response_path.is_file() or not _owned(revision, response_path):
                if attestation or relative in extras:
                    return revoke('Authenticated observer response missing or path rejected', relative)
                continue
            if unit.get('observer_evidence_required') and (attestation or relative in extras):
                if (not isinstance(attestation, dict) or not attestation
                        or attestation.get('response_sha256') != quality.sha256_file(response_path)):
                    return revoke('Authenticated observer response bytes or attestation rejected', relative)
            try:
                response = _read(response_path)
            except (OSError, ValueError, UnicodeError):
                if attestation:
                    return revoke('Authenticated observer response no longer parses', relative)
                continue
            try:
                allowed = set(expected)
                if unit.get('observer_evidence_required'):
                    if (attestation.get('producer') != response.get('producer')
                            or attestation.get('observer_evidence') != response.get('observer_evidence')):
                        if attestation:
                            return revoke('Authenticated observer producer or evidence changed', relative)
                        continue
                    from tui_visual_callback import observer_metadata
                    retained = response['observer_evidence']
                    state = Path(retained['state_path'])
                    if relative not in (unit['review_transport']['progress_path'], unit['response_path']):
                        # A ledger entry alone cannot authorize arbitrary revision files.
                        # Filenames retain the original raw hash; authentication adds
                        # host metadata, so the attestation binds the resulting bytes.
                        name = response_path.name
                        if (response_path.parent != state / 'authenticated-finals'
                                or relative != response_path.relative_to(revision).as_posix()
                                or len(name) != 69 or not name.endswith('.json')
                                or any(c not in '0123456789abcdef' for c in name[:-5])):
                            return revoke('Authenticated observer final path rejected', relative)
                    database = state / 'state.db'
                    if (not _owned(revision, state) or state.parent != revision / 'hermes/visual-review-observers'
                            or not _owned(revision, database) or not database.is_file()
                            or retained.get('database_sha256') != quality.sha256_file(database)):
                        return revoke('Authenticated observer runtime evidence changed', relative)
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
                        return revoke('Authenticated observer identity or provenance changed', relative)
                    allowed = {t['target_id'] for t in unit['visual_scope']
                        if all(p['path'] in observed['inspected_paths'] for p in t['pages'])
                        and (t['kind'] != 'document' or observed['native_inspection_complete'])}
                if (response.get('schema_version') != quality.RESPONSE_SCHEMA
                        or any(response.get(k) != unit[k] for k in ('request_id', 'request_sha256', 'task', 'revision_id'))):
                    if attestation:
                        return revoke('Authenticated observer response identity rejected', relative)
                    continue
                status_valid = (isinstance(response.get('status'), str)
                    and response['status'] in {'passed', 'blocked', 'failed', 'in_progress'})
                if not status_valid:
                    report('malformed_response_status', 'Response status must be passed, blocked, failed or in_progress; bound concerns are retained without assessment credit.', expected, relative)
                producer = response.get('producer')
                authors = (parent.get('review_context') or {}).get('repair_authors', [])
                if (not isinstance(producer, dict) or any(not isinstance(producer.get(k), str)
                        or not producer[k].strip() for k in ('model_id', 'reviewer_id'))
                        or any(a.get('reviewer_id') == producer['reviewer_id'] for a in authors)):
                    continue
                rows, issues = response.get('visual_assessments'), response.get('findings')
                finding_channel_valid = isinstance(issues, list)
                if not isinstance(rows, list):
                    report('malformed_assessments', 'visual_assessments must be a list.', expected, relative)
                    rows = []
                if not isinstance(issues, list):
                    report('malformed_findings', 'findings must be a list; return explicit findings or an empty list.', expected, relative)
                    issues = []
                valid_issues, invalid_targets = [], set()
                for f in issues:
                    target = expected.get(f.get('target_id')) if isinstance(f, dict) and isinstance(f.get('target_id'), str) else None
                    affected = [target['target_id']] if target else list(expected)
                    if (not target or any(not isinstance(f.get(k), str) or not f[k].strip()
                            for k in ('issue', 'check', 'element', 'recommended_action'))):
                        report('malformed_finding', 'Finding requires an assigned target and nonempty issue/check/element/recommended_action.', affected, relative)
                        if target:
                            invalid_targets.add(target['target_id'])
                        else:
                            finding_channel_valid = False
                        continue
                    pages = [p for a in parent['artifacts'] if a['artifact'] == target['artifact']
                        for p in a['pages']] if target['kind'] == 'document' else target['pages']
                    if (f.get('artifact') != target['artifact'] or type(f.get('page')) is not int
                            or f['page'] not in {p['page'] for p in pages}):
                        report('finding_location', 'Finding artifact/page is outside the authenticated target artifact.', affected, relative)
                        invalid_targets.update(affected)
                        continue
                    # Page/boundary assignments are pixel judgments even when a
                    # model omits its basis. Only the supported document-native
                    # bases can use authenticated whole-document inspection.
                    pixel_claim = (target['kind'] != 'document'
                        or f.get('evidence_basis') not in (None, 'native', 'source', 'template', 'document', 'page_observation')
                        or f.get('requires_additional_pixels') is True)
                    native_claim = target['kind'] == 'document' and not pixel_claim
                    if (unit.get('observer_evidence_required') and native_claim
                            and not observed['native_inspection_complete']):
                        report('unsupported_native_claim', 'Document/native finding requires authenticated native inspection.', affected, relative)
                        invalid_targets.add(target['target_id'])
                        continue
                    if pixel_claim and (f['page'] not in {p['page'] for p in target['pages']}
                            or target['target_id'] not in allowed):
                        f = {**f, 'evidence_status': 'needs_visual_followup'}
                        invalid_targets.add(target['target_id'])
                        report('unsupported_visual_claim', 'Concern retained; inspect the bound location page and adjoining boundaries before crediting its pixel judgment.', affected, relative)
                    valid_issues.append(f)
                issues = valid_issues
                counts = {}
                for row in rows:
                    if isinstance(row, dict) and isinstance(row.get('target_id'), str):
                        counts[row['target_id']] = counts.get(row['target_id'], 0) + 1
                credited = []
                for row in rows:
                    target = expected.get(row.get('target_id')) if isinstance(row, dict) and isinstance(row.get('target_id'), str) else None
                    if not target:
                        report('malformed_assessment', 'Assessment must name an assigned target.', expected, relative)
                        continue
                    if counts[row['target_id']] != 1 or row['target_id'] in invalid_targets:
                        report('malformed_assessment', 'Duplicate assessment or invalid associated finding; provide one bound judgment.', [row['target_id']], relative)
                        continue
                    if row['target_id'] not in allowed:
                        report('unsupported_coverage', 'Assigned images/native evidence were not independently inspected.', [row['target_id']], relative)
                        continue
                    if (not status_valid or any(row.get(k) != v for k, v in target.items())
                            or not isinstance(row.get('status'), str)
                            or row['status'] not in {'passed', 'blocked', 'failed'}
                            or not (isinstance(row.get('notes'), str) and row['notes'].strip()
                                or isinstance(row.get('notes'), dict) and row['notes']
                                and all(isinstance(k, str) and isinstance(v, str) and v.strip()
                                        for k, v in row['notes'].items()))):
                        report('malformed_assessment', 'Assessment requires exact scope, checks, status and substantive notes.', [row['target_id']], relative)
                        continue
                    covering = [f for f in issues if f['target_id'] == row['target_id']]
                    if ((row['status'] == 'passed') == bool(covering)
                            or response['status'] == 'passed' and row['status'] != 'passed'):
                        report('contradictory_assessment', 'A nonpassing target requires a finding; a passing target cannot carry one.', [row['target_id']], relative)
                        continue
                    credited.append({**row, 'producer': producer})
                proof = {'request_path': path.relative_to(revision).as_posix(),
                    'request_sha256': quality.sha256_file(path), 'response_path': relative,
                    'response_sha256': quality.sha256_file(response_path), 'producer': producer,
                    'observer_evidence': response.get('observer_evidence')}
                if credited or issues:
                    proofs.append(proof)
                    findings.extend({**f, 'producer': producer, 'proof': proof,
                        'finding_id': f.get('finding_id') or sha256_value({
                            'parent': parent['request_sha256'], 'target_id': f['target_id'], 'issue': f['issue']})[:24]}
                        for f in issues)
                if unit.get('finding_followup'):
                    candidates = response.get('finding_resolutions', [])
                    if not isinstance(candidates, list):
                        report('malformed_resolution', 'finding_resolutions must be a list.', expected, relative)
                        candidates = []
                    for context in unit['finding_followup']:
                        original = context['finding']
                        matching = [r for r in candidates if isinstance(r, dict)
                            and r.get('finding_id') == original['finding_id']]
                        if not matching:
                            report('missing_resolution', 'Explicit independent resolution of original concern required; generic passes do not resolve it.', expected, relative)
                        for resolution in matching:
                            ids = resolution.get('target_ids')
                            if (len(matching) != 1 or not isinstance(ids, list) or not ids
                                    or any(not isinstance(k, str) for k in ids)
                                    or len(set(ids)) != len(ids) or not set(ids) <= set(expected)
                                    or not set(ids) <= {r['target_id'] for r in credited}
                                    or not isinstance(resolution.get('status'), str)
                                    or resolution['status'] not in {'confirmed', 'dismissed'}
                                    or not isinstance(resolution.get('notes'), str) or not resolution['notes'].strip()
                                    or producer['reviewer_id'] == original['producer']['reviewer_id']
                                    or (resolution['status'] == 'dismissed' and any(
                                        r['status'] != 'passed' for r in credited if r['target_id'] in ids))):
                                report('unsupported_resolution', 'Resolution requires independent identity, exact completed scope, disposition and substantive notes.', expected, relative)
                                continue
                            resolutions.append({**resolution, 'producer': producer, 'proof': proof,
                                'source_proof': context['proof']})
                for key in expected.keys() - {r['target_id'] for r in credited}:
                    report('missing_coverage', 'No authenticated completed assessment for this target in this channel.', [key], relative)
                for row in credited:
                    key = row['target_id']
                    clean = finding_channel_valid or row['status'] != 'passed'
                    if key not in accepted or row['status'] != 'passed' or clean and key not in coverage:
                        accepted[key] = {**row, 'proof': proof}
                    if clean:
                        coverage.add(key)
            except (OSError, ValueError, KeyError, TypeError, sqlite3.DatabaseError):
                continue
        if ledger.get('validation_feedback') != feedback:
            ledger['validation_feedback'] = feedback
            _write(revision, ledger_path, ledger)
        if not accepted and not findings and not feedback:
            return None
        return {'assessments': list(accepted.values()), 'findings': findings, 'proofs': proofs,
            'finding_resolutions': resolutions,
            'coverage_target_ids': sorted(coverage),
            'validation_feedback': feedback, 'complete': coverage == set(expected)}
    except (OSError, ValueError, KeyError, TypeError, sqlite3.DatabaseError):
        return None


def visual_review_result(revision: Path, parent_path: Path, *, publish: bool = True) -> dict:
    """Recombine real judgments only; unchanged bytes cannot unpoison a rejected wave."""
    parent = _parent(revision, parent_path)
    expected = parent['visual_review_plan']['targets']
    rows, findings, proofs = {}, [], []
    resolutions, followup_rows, feedback, coverage = [], [], [], set()
    integrity_rejections = []
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
        ledger_path = revision / f"hermes/visual-review-ledgers/{unit['request_id']}.json"
        if _owned(revision, ledger_path) and ledger_path.is_file():
            ledger = _read(ledger_path)
            if 'integrity_rejection' in ledger:
                integrity_rejections.append({'request_id': unit['request_id'],
                    'ledger_path': ledger_path.relative_to(revision).as_posix(),
                    'rejection': ledger['integrity_rejection']})
        if not result:
            continue
        findings.extend(result['findings'])
        proofs.extend(result['proofs'])
        feedback.extend(result['validation_feedback'])
        resolutions.extend(result['finding_resolutions'])
        if unit.get('finding_followup'):
            followup_rows.extend({'context': c, 'assessment': r}
                for c in unit['finding_followup'] for r in result['assessments']
                if r['target_id'] in result['coverage_target_ids'])
            continue  # New applicable concerns own fresh evidence, not duplicate baseline coverage.
        for row in result['assessments']:
            key = row['target_id']
            # Replacement scope should not overlap. Historical partial/final
            # checkpoints may; a substantive negative always dominates.
            clean = key in result['coverage_target_ids']
            if key in coverage and clean and row['status'] == 'passed' and rows[key]['status'] == 'passed':
                if (row['proof']['request_path'] != rows[key]['proof']['request_path']
                        or {k: v for k, v in row.items() if k != 'proof'} != {k: v for k, v in rows[key].items() if k != 'proof'}):
                    raise ValueError('Overlapping independent visual judgments')
            if key not in rows or row['status'] != 'passed' or clean and key not in coverage:
                rows[key] = row
            if clean:
                coverage.add(key)
    findings = list({sha256_value(f): f for f in findings}.values())
    followup_missing, followup_context, resolved_findings = {}, [], []
    retained = []
    for finding in findings:
        if finding.get('evidence_status') != 'needs_visual_followup':
            retained.append(finding)
            continue
        needed = _finding_followup_targets(parent, finding)
        context = {'finding': finding, 'proof': finding['proof'],
            'target_ids': [t['target_id'] for t in needed]}
        scoped = [r for r in followup_rows if r['context'] == context]
        completed = {r['assessment']['target_id'] for r in scoped}
        matching = [r for r in resolutions if r['finding_id'] == finding['finding_id']
            and r['source_proof'] == finding['proof']]
        dismissed = {k for r in matching if r['status'] == 'dismissed' for k in r['target_ids']}
        confirmed = {k for r in matching if r['status'] == 'confirmed' for k in r['target_ids']}
        required = set(context['target_ids'])
        if required <= completed and required <= dismissed and not confirmed:
            resolved_findings.append({'finding': finding, 'resolutions': matching})
            continue
        retained.append(finding)
        followup_context.append(context)
        for target in needed:
            if target['target_id'] not in completed:
                followup_missing[target['target_id']] = target
    findings = retained
    missing = [t for t in expected if t['target_id'] not in coverage]
    result = {'assessments': list(rows.values()), 'missing': missing, 'findings': findings,
        'proofs': proofs, 'complete': not missing and not followup_missing and not integrity_rejections,
        'integrity_rejections': integrity_rejections,
        'validation_feedback': feedback, 'finding_resolutions': resolved_findings,
        'followup_missing': list(followup_missing.values()), 'finding_followup': followup_context,
        'followup_assessments': followup_rows}
    if publish and (result['complete'] or findings or resolved_findings) and rows:
        assessments = list(rows.values())
        producer = assessments[0]['producer']  # actual observer, not fictional orchestrator
        response = {'schema_version': quality.RESPONSE_SCHEMA,
            **{k: parent[k] for k in ('request_id', 'request_sha256', 'task', 'revision_id')},
            'producer': producer, 'status': 'blocked' if not result['complete'] or findings or any(r['status'] != 'passed' for r in assessments) else 'passed',
            'findings': findings, 'visual_assessments': assessments, 'unit_proofs': proofs,
            'finding_resolutions': resolved_findings, 'followup_assessments': followup_rows,
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
        if assembled['integrity_rejections']:
            return ['Visual review contains an authenticated integrity rejection; retained siblings are diagnostic progress only.']
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
        if result['integrity_rejections']:
            raise ValueError('Visual review integrity rejected; retained ledger evidence: ' +
                ', '.join(r['ledger_path'] for r in result['integrity_rejections']))
        repair_ready = any(f.get('evidence_status') != 'needs_visual_followup' for f in result['findings'])
        if (repair_ready or (result['complete'] or result['findings'] or result['finding_resolutions'])
                and not result['followup_missing']):
            return {**result, 'dispatch_errors': errors}
        available = deadline - clock()
        reserve = min(15.0, max(5.0, remaining_seconds / 10))
        if available <= reserve or no_progress >= 2:
            return {**result, 'dispatch_errors': errors}
        missing = result['followup_missing'] or result['missing']
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
            followup = [c for c in result['finding_followup']
                if set(c['target_ids']) & {t['target_id'] for t in group}] if result['followup_missing'] else []
            prefix = parent['request_id'] + '.visual-unit-' + _unit_scope_identity(group, followup) + ('.callback' if observer_evidence_required else '') + '.a'
            historical = list((revision / 'hermes/visual-review-requests').glob(prefix + '*.json'))
            attempt = max([int(p.stem.rsplit('.a', 1)[1]) for p in historical] or [0]) + 1
            paths.append(create_visual_review_unit(revision, parent_path, group, attempt,
                observer_evidence_required=observer_evidence_required, finding_followup=followup,
                validation_feedback=[{**f, 'target_ids': [k for k in f['target_ids']
                    if k in {t['target_id'] for t in group}]}
                    for f in result['validation_feedback']
                    if set(f['target_ids']) & {t['target_id'] for t in group}]))
        handoffs = []
        for path in paths:
            unit = _read(path)
            handoffs.append({'task': unit['task'], 'request_path': path.relative_to(revision).as_posix(),
                'response_path': unit['response_path'], 'request_id': unit['request_id'],
                'request_sha256': unit['request_sha256'], 'visual_unit': True,
                'validation_feedback': copy.deepcopy(unit.get('validation_feedback', []))})
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
            import subprocess
            if integrity or not isinstance(exc, (IncompleteVisualReview, TimeoutError, subprocess.TimeoutExpired)):
                raise  # Unknown execution failures cannot become missing coverage.
        for path in paths:
            validate_visual_review_unit_request(revision, path)
        updated = visual_review_result(revision, parent_path)
        before = len(result['assessments']) + len(result['followup_assessments']) + len(result['findings'])
        after = len(updated['assessments']) + len(updated['followup_assessments']) + len(updated['findings'])
        no_progress = no_progress + 1 if after <= before else 0


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
