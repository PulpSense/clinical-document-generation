"""Spec #114 recovery through authenticated request and Desktop boundaries."""
import copy
import json

import pytest
import quality
from test_content_review_recovery import candidate, operation, FAMILIES
from test_handoff_quality import acceptance_verification


@pytest.mark.parametrize('broken', [b'{', b'\xff', b'[]'])
@pytest.mark.parametrize('malformed_final', [True, False])
def test_malformed_sibling_keeps_authenticated_concern(tmp_path, broken, malformed_final):
    parent_path, parent, _ = candidate(tmp_path, FAMILIES[-1])
    unit_path = quality.create_content_review_unit(tmp_path, parent_path, parent['sections'][:2], [], 1)
    unit = json.loads(unit_path.read_text())
    response = acceptance_verification(unit)
    response['status'] = 'blocked'
    response['section_assessments'][0]['status'] = 'blocked'
    response['findings'] = [{'finding_id': 'saved-fact', 'artifact': 'protocol',
        'target_ids': [unit['sections'][0]['section_id']], 'material': True,
        'issue': 'Saved substantive concern'}]
    checkpoint = tmp_path / unit['review_transport']['progress_path']
    final = tmp_path / unit['response_path']
    final.parent.mkdir(parents=True, exist_ok=True)
    valid, malformed = (checkpoint, final) if malformed_final else (final, checkpoint)
    valid.write_text(json.dumps(response))
    malformed.write_bytes(broken)
    result = quality.content_review_unit_result(tmp_path, unit_path)
    assert result and len(result['findings']) == 1
    assert result['section_assessments'][0]['status'] == 'blocked'
    assert malformed.read_bytes() == broken


@pytest.mark.parametrize('family', FAMILIES)
@pytest.mark.parametrize('location', ['section', 'cross', 'unknown'])
def test_retained_concern_identity_survives_units_and_parent_validation(tmp_path, family, location):
    _, _, source = candidate(tmp_path, family)
    concern = {'finding_id': 'prior-fact', 'issue': 'Unresolved source concern', 'material': True,
               'artifact': 'protocol', 'target_ids': ['title-page']}
    if location == 'cross':
        concern.update(check='cross_document_consistency', target_ids=[])
    elif location == 'unknown':
        concern['target_ids'] = ['unknown-native-location']
    parent_path = quality.create_verification_requests(tmp_path, source, {'artifacts': []}, review_set=2,
        review_context={'prior_findings': [concern]})[0]
    parent = json.loads(parent_path.read_text())
    units = []
    scopes = [([row], []) for row in parent['sections']]
    scopes += [([], [check]) for check in parent['cross_document_checks']]
    for sections, checks in scopes:
        path = quality.create_content_review_unit(tmp_path, parent_path, sections, checks, 1)
        units.append(path)
        unit = json.loads(path.read_text())
        response = acceptance_verification(unit)
        if unit['review_context']['prior_findings']:
            response['findings'] = [concern]
            response['status'] = 'blocked'
            row = (response['section_assessments'] or response['cross_document_assessments'])[0]
            row.update(status='blocked', notes=['prior-fact'] if location != 'section' else [])
        destination = tmp_path / unit['response_path']
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(response))
    result = quality.content_review_schedule_result(tmp_path, parent_path, units)
    assert result['complete']
    assert {row['finding_id'] for row in result['findings']} == {'prior-fact'}
    findings, _ = quality.validate_verifications(tmp_path, request_paths=[parent_path])
    assert not [f for f in findings if f.get('recovery_class') == 'verifier_transient'], findings


@pytest.mark.parametrize('kind', ['uncovered-section', 'uncovered-cross', 'contradictory-section', 'contradictory-cross'])
def test_invalid_assessment_is_retried_with_specific_feedback(tmp_path, monkeypatch, kind):
    damaged = []
    retried = []
    def worker(request, response, revision, handoff=None):
        rows = response['cross_document_assessments'] if kind.endswith('cross') else response['section_assessments']
        if rows and not damaged:
            row = rows[0]
            scope = row.get('section_id', row.get('check'))
            damaged.append(scope)
            if kind.startswith('uncovered'):
                row['status'] = 'blocked'
                response['status'] = 'blocked'
            else:
                response['findings'] = [{'finding_id': 'contradiction', 'artifact': 'protocol',
                    'target_ids': [scope] if 'section_id' in row else [],
                    'check': row.get('check', 'source_supported'), 'material': True,
                    'issue': 'Finding contradicts the passing assessment'}]
                if 'check' in row:
                    row['notes'] = ['contradiction']
        elif damaged and any(r.get('section_id', r.get('check')) == damaged[0] for r in rows):
            retried.append(handoff)
        return response
    result, revision, _ = operation(tmp_path, monkeypatch, FAMILIES[0] if kind.endswith('cross') else FAMILIES[-1], worker, worker)
    assert result['status'] == 'passed', result
    assert retried and retried[0]['response_repair_feedback']
    assert any('passing' in str(f) if kind.startswith('contradictory') else 'covered' in str(f)
               for f in retried[0]['response_repair_feedback'])


def test_generic_pass_cannot_erase_checkpoint_concern(tmp_path):
    parent_path, parent, _ = candidate(tmp_path, FAMILIES[-1])
    path = quality.create_content_review_unit(tmp_path, parent_path, parent['sections'][:1], [], 1)
    unit = json.loads(path.read_text())
    response = acceptance_verification(unit)
    checkpoint = copy.deepcopy(response)
    checkpoint['status'] = 'in_progress'
    checkpoint['section_assessments'][0]['status'] = 'blocked'
    checkpoint['findings'] = [{'finding_id': 'saved-fact', 'artifact': 'protocol',
        'target_ids': [unit['sections'][0]['section_id']], 'issue': 'Saved concern', 'material': True}]
    (tmp_path / unit['review_transport']['progress_path']).write_text(json.dumps(checkpoint))
    final = tmp_path / unit['response_path']
    final.parent.mkdir(parents=True, exist_ok=True)
    final.write_bytes(b'{')
    assert quality.content_review_unit_result(tmp_path, path)['findings']
    final.write_text(json.dumps(response))
    result = quality.content_review_unit_result(tmp_path, path)
    assert result['findings'] and result['section_assessments'][0]['status'] == 'blocked'


def test_repeated_uncovered_assessments_stop_without_false_progress(tmp_path, monkeypatch):
    def invalid(request, response, revision, *args):
        response['status'] = 'blocked'
        for row in response['section_assessments']:
            row['status'] = 'blocked'
        return response
    result, revision, _ = operation(tmp_path, monkeypatch, FAMILIES[-1], invalid, invalid)
    assert result['status'] == 'review_required'
    ledger = json.loads(next((revision / 'hermes/review-schedules').glob('*.json')).read_text())
    assert ledger['no_progress'] == 2
    assert all(w['completed_assessments'] == 0 for w in ledger['waves'])


def test_interrupted_desktop_keeps_truncated_final_checkpoint_and_original_deadline(tmp_path, monkeypatch):
    from pathlib import Path
    import workflow
    from test_general_document_repair import repair_response
    class ParentInterrupted(BaseException):
        pass
    def interrupt(request, response, revision, *args):
        checkpoint = copy.deepcopy(response)
        checkpoint['status'] = 'in_progress'
        checkpoint['section_assessments'] = checkpoint['section_assessments'][:1]
        row = checkpoint['section_assessments'][0]
        row['status'] = 'blocked'
        checkpoint['findings'] = [{'finding_id': 'saved-fact', 'artifact': row['artifact'],
            'target_ids': [row['section_id']], 'material': True, 'issue': 'Saved substantive checkpoint concern',
            'affected_passage': 'Native title requires independent correction', 'source_path': 'study.title'}]
        (revision / request['review_transport']['progress_path']).write_text(json.dumps(checkpoint))
        final = revision / request['response_path']
        final.parent.mkdir(parents=True, exist_ok=True)
        final.write_bytes(b'{')
        raise ParentInterrupted()
    with pytest.raises(ParentInterrupted):
        operation(tmp_path, monkeypatch, FAMILIES[-1], interrupt, interrupt)
    state_path = tmp_path / 'logs/desktop-operation.json'
    original = json.loads(state_path.read_text())
    revision = next((tmp_path / 'revisions').iterdir())
    repairs = []
    def resume(handoffs, remaining):
        for handoff in handoffs:
            request = json.loads((revision / handoff['request_path']).read_text())
            if request['task'] == 'document_repair':
                repairs.extend(request['findings'])
                response = repair_response(request, status='needs_review')
            else:
                response = acceptance_verification(request)
            path = revision / request['response_path']
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(response))
    result = workflow.run_desktop_operation(tmp_path, handoff_runner=resume, fallback_handoff_runner=resume,
        opener=lambda path: Path(path).read_bytes(), budget_seconds=180, require_promoted_runtime=False)
    assert result['status'] == 'review_required', result
    assert any('Saved substantive' in f['issue'] for f in repairs), repairs
    final = json.loads(state_path.read_text())
    assert final['deadline_at_epoch'] == original['deadline_at_epoch']
    assert final['approval_identity'] == original['approval_identity']


@pytest.mark.parametrize('family', [FAMILIES[0], FAMILIES[1]])
def test_long_complete_package_has_lossless_staged_native_and_source_routes(tmp_path, family):
    parent_path, parent, source = candidate(tmp_path, family)
    assert len(parent['sections']) >= 62
    assert len(parent['cross_document_checks']) == 6
    # Exercise every assigned native passage and all cross-document scope;
    # approval is still supplied only by a controlled independent test adapter.
    units = []
    for artifact in dict.fromkeys(row['artifact'] for row in parent['sections']):
        rows = [row for row in parent['sections'] if row['artifact'] == artifact]
        for start in range(0, len(rows), 3):
            units.append(quality.create_content_review_unit(tmp_path, parent_path, rows[start:start+3], [], 1))
    for start in range(0, 6, 2):
        units.append(quality.create_content_review_unit(tmp_path, parent_path, [], parent['cross_document_checks'][start:start+2], 1))
    locations, cross_bytes = [], []
    for path in units:
        unit = json.loads(path.read_text())
        assert unit['workload']['serialized_request_bytes'] == path.stat().st_size
        for evidence in unit['readable_native_evidence']:
            passage = evidence.get('passage', {})
            staged = passage.get('staged_path') if isinstance(passage, dict) else evidence.get('path')
            if staged:
                native = json.loads((tmp_path / staged).read_text())
                assert native['records']
                locations.extend(row['location'] for row in native['records'])
            elif isinstance(passage, list):
                locations.extend(row['location'] for row in passage)
        if unit['cross_document_checks']:
            cross_bytes.append(path.stat().st_size)
        response = acceptance_verification(unit)
        destination = tmp_path / unit['response_path']
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(response))
    result = quality.content_review_schedule_result(tmp_path, parent_path, units)
    assert result['complete'] and result['completed'] >= 68
    assert locations and all(':' in location for location in locations)
    assert max(cross_bytes) < 35000
    canonical = json.loads((tmp_path / json.loads(units[-1].read_text())['canonical_source_evidence']['parent_request_path']).read_text())
    assert canonical['approved_source'] == source
    assert 'UNIQUE END OF SOURCE' in canonical['approved_source']['study']['background']
