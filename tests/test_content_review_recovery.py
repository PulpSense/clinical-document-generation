"""Review transport recovery at public request and Desktop operation boundaries."""
import copy
import hashlib
import json

import pytest

import quality
import workflow
from test_clean_delivery import ROOT, CASES, controlled_render
from test_handoff_quality import acceptance_verification
from rendering import render_documents

FAMILIES = [('Prospective', 'Advarra'), ('Prospective', 'Sterling'),
            ('Ambispective', 'Advarra'), ('Ambispective', 'Sterling'), ('Retrospective', None)]


def candidate(tmp_path, family):
    case = next(c for c in CASES if c['descriptor']['study_type'] == family[0]
                and (family[1] is None or c['descriptor'].get('icf_template') == family[1]))
    source = quality.branch_acceptance_source(ROOT, case)
    source['study']['background'] = 'Long approved rationale: μg, \"quoted\" and\nnew line ' * 700 + 'UNIQUE END OF SOURCE'
    render_documents(ROOT, tmp_path, source, {'protocol': [], 'icf': {}, 'prs': {}})
    paths = quality.create_verification_requests(tmp_path, source, {'artifacts': []})
    path = paths[0]
    return path, json.loads(path.read_text()), source


@pytest.mark.parametrize('family', FAMILIES)
def test_complete_review_evidence_has_bounded_lossless_reading_route(tmp_path, family):
    path, request, source = candidate(tmp_path, family)
    transport = request['review_transport']
    assert transport['progress_path'].startswith('hermes/review-progress/')
    recovered = {}
    for view in transport['views']:
        content = ''
        for packet in view['packets']:
            data = (tmp_path / packet['path']).read_bytes()
            assert len(data) <= 12000
            assert max(map(len, data.decode().splitlines())) <= 400
            assert hashlib.sha256(data).hexdigest() == packet['sha256']
            content += ''.join(json.loads(data)['text_chunks'])
        recovered[view['name']] = json.loads(content)
    assert recovered['request']['approved_source'] == source
    assert recovered['request']['instructions'].endswith(request['instructions'][-100:])
    for native in request['native_inspection']:
        assert recovered[native['path']] == json.loads((tmp_path / native['path']).read_text())
    response = acceptance_verification(request)
    (tmp_path / request['response_path']).write_text(json.dumps(response))
    assert quality.verification_response_is_complete(tmp_path, path)


def operation(tmp_path, monkeypatch, family, primary_review, fallback_review, *, clock=None):
    import drafting
    from pathlib import Path
    monkeypatch.setattr(workflow, 'render_assurance', controlled_render)
    case = next(c for c in CASES if c['descriptor']['study_type'] == family[0]
                and (family[1] is None or c['descriptor'].get('icf_template') == family[1]))
    source = quality.branch_acceptance_source(ROOT, case)
    reference = tmp_path / 'reference/study.reference.json'
    reference.parent.mkdir(parents=True)
    reference.write_text(json.dumps(source))
    workflow.prepare(tmp_path)
    approval = workflow.approve(tmp_path, approved_by='fixture-owner')
    revision = tmp_path / 'revisions' / approval['revision_id']
    original_source = (revision / 'approved-reference.json').read_bytes()
    fallback_scopes = []

    def dispatch(items, remaining, fallback=False):
        for handoff in items:
            request = json.loads((revision / handoff['request_path']).read_text())
            if request['task'] in {'section_drafting', 'prs_narrative_drafting'}:
                response = drafting.recorded_acceptance_response(request)
            else:
                response = acceptance_verification(request)
                if request['task'] == 'clinical_content_verification':
                    if handoff.get('reviewer_owner') == 'replacement':
                        fallback_scopes.append(handoff['review_resume'])
                        response = fallback_review(request, response, revision, handoff)
                    else:
                        response = primary_review(request, response, revision)
            if response is not None:
                path = revision / request['response_path']
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(response))

    result = workflow.run_desktop_operation(tmp_path, handoff_runner=dispatch,
        fallback_handoff_runner=lambda items, remaining: dispatch(items, remaining, True),
        opener=lambda path: Path(path).read_bytes(), budget_seconds=180,
        require_promoted_runtime=False, clock=clock)
    assert (revision / 'approved-reference.json').read_bytes() == original_source
    return result, revision, fallback_scopes


@pytest.mark.parametrize('family', FAMILIES)
def test_context_loss_resumes_saved_review_without_redrafting_documents(tmp_path, monkeypatch, family):
    saved = []
    def primary(request, response, revision):
        checkpoint = copy.deepcopy(response)
        checkpoint['section_assessments'] = response['section_assessments'][:3]
        checkpoint['cross_document_assessments'] = []
        checkpoint['status'] = 'in_progress'
        path = revision / request['review_transport']['progress_path']
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(checkpoint))
        saved.extend((r['artifact'], r['section_id']) for r in checkpoint['section_assessments'])
        response.update(status='blocked', error={'type': 'native_inspection_incomplete',
            'message': 'read_file truncated the long instruction; context compaction lost inspection.'},
            section_assessments=[], cross_document_assessments=[])
        return response

    def fallback(request, response, revision, handoff):
        assert handoff['review_resume']['reading_strategy'] == 'bounded_packets'
        assert not set(saved) & {(r['artifact'], r['section_id'])
                                for r in handoff['review_resume']['remaining_sections']}
        response['producer']['reviewer_id'] = 'fresh-independent-reviewer'
        response['section_assessments'] = [r for r in response['section_assessments']
                                          if (r['artifact'], r['section_id']) not in saved]
        return response

    result, revision, scopes = operation(tmp_path, monkeypatch, family, primary, fallback)
    assert result['status'] == 'passed', result
    assert len(scopes) == 1
    assert not list((revision / 'hermes').glob('document-repair*'))
    assert list((revision / 'hermes/review-progress').glob('*/attempt-*.json'))


@pytest.mark.parametrize('failure', ['missing-response', 'partial-response', 'foreign-checkpoint', 'malformed-checkpoint', 'worker-exception'])
def test_failed_or_incomplete_worker_switches_to_fresh_review(tmp_path, monkeypatch, failure):
    def primary(request, response, revision):
        if failure == 'worker-exception':
            raise RuntimeError('worker exited after context compaction')
        if failure == 'partial-response':
            response['section_assessments'] = response['section_assessments'][:2]
            response['cross_document_assessments'] = []
            return response
        if failure in {'foreign-checkpoint', 'malformed-checkpoint'}:
            if failure == 'foreign-checkpoint':
                response['request_sha256'] = '0' * 64
            else:
                response['section_assessments'][0]['checks'] = []
            path = revision / request['review_transport']['progress_path']
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(response))
        return None
    def fallback(request, response, revision, handoff):
        response['producer']['reviewer_id'] = 'replacement-reviewer'
        assert handoff['review_resume']['completed_section_count'] == (2 if failure == 'partial-response' else 0)
        return response
    result, revision, scopes = operation(tmp_path, monkeypatch, FAMILIES[-1], primary, fallback)
    assert result['status'] == 'passed', result
    assert len(scopes) == 1


def test_replacement_failure_has_one_reserved_alternate_attempt(tmp_path, monkeypatch):
    calls = []
    def fallback(request, response, revision, handoff):
        calls.append(handoff['review_attempt'])
        if len(calls) == 1:
            raise RuntimeError('replacement provider temporarily unavailable')
        return response
    result, revision, scopes = operation(tmp_path, monkeypatch, FAMILIES[-1],
                                        lambda *args: None, fallback)
    assert result['status'] == 'passed', result
    assert calls == [1, 2]


def test_exhausted_replacements_deliver_review_only_without_restart(tmp_path, monkeypatch):
    result, revision, scopes = operation(tmp_path, monkeypatch, FAMILIES[-1],
                                        lambda *args: None, lambda *args: None)
    assert result['status'] == 'review_required', result
    assert result['stage'] == 'review_tooling'
    assert len(scopes) == 2
    assert (tmp_path / 'review-output/REVIEW-ONLY-protocol.docx').is_file()


def test_partial_substantive_finding_is_not_discarded_by_replacement_pass(tmp_path, monkeypatch):
    def primary(request, response, revision):
        response['section_assessments'] = response['section_assessments'][:1]
        response['cross_document_assessments'] = []
        response['section_assessments'][0]['status'] = 'blocked'
        response['status'] = 'blocked'
        response['error'] = {'type': 'native_inspection_incomplete', 'message': 'Remaining inspection lost.'}
        row = response['section_assessments'][0]
        response['findings'] = [{'finding_id': 'source-defect', 'artifact': row['artifact'],
            'target_ids': [row['section_id']], 'check': 'source_supported',
            'issue': 'The reported quantity contradicts the approved source.', 'material': True}]
        return response
    def fallback(request, response, revision, handoff):
        return response  # A generic complete pass must not erase the saved defect.
    # Stop at the resulting native repair handoff: no repair author is supplied.
    # Public generation must still see the saved substantive finding.
    import drafting
    from pathlib import Path
    monkeypatch.setattr(workflow, 'render_assurance', controlled_render)
    source = quality.branch_acceptance_source(ROOT, next(c for c in CASES if c['descriptor']['study_type'] == 'Retrospective'))
    reference = tmp_path / 'reference/study.reference.json'
    reference.parent.mkdir(parents=True); reference.write_text(json.dumps(source))
    workflow.prepare(tmp_path); approved = workflow.approve(tmp_path, approved_by='fixture-owner')
    revision = tmp_path / 'revisions' / approved['revision_id']
    def dispatch(items, remaining):
        for item in items:
            request = json.loads((revision / item['request_path']).read_text())
            if request['task'] == 'document_repair':
                raise workflow.WorkerAuthenticationError('Controlled stop before authoring repair.')
            response = drafting.recorded_acceptance_response(request) if request['task'] == 'section_drafting' else acceptance_verification(request)
            if request['task'] == 'clinical_content_verification':
                response = fallback(request, response, revision, item) if item.get('reviewer_owner') else primary(request, response, revision)
            (revision / request['response_path']).write_text(json.dumps(response))
    result = workflow.run_desktop_operation(tmp_path, handoff_runner=dispatch,
        fallback_handoff_runner=dispatch, opener=lambda path: Path(path).read_bytes(),
        budget_seconds=180, require_promoted_runtime=False)
    assert result['status'] != 'passed'
    responses = list((revision / 'hermes/verification-responses').glob('*content.json'))
    assert any(row['finding_id'] == 'source-defect' for path in responses
               for row in json.loads(path.read_text()).get('findings', []))
    assert not (tmp_path / 'output/protocol.docx').exists()


@pytest.mark.parametrize('target', ['packet', 'index', 'native'])
def test_changed_reading_evidence_cannot_approve_documents(tmp_path, target):
    path, request, source = candidate(tmp_path, FAMILIES[-1])
    response = acceptance_verification(request)
    (tmp_path / request['response_path']).write_text(json.dumps(response))
    assert quality.verification_response_is_complete(tmp_path, path)
    if target == 'packet':
        changed = tmp_path / request['review_transport']['views'][0]['packets'][0]['path']
    elif target == 'index':
        changed = tmp_path / request['review_transport']['index_path']
    else:
        changed = tmp_path / request['artifacts'][0]['path']
    changed.write_bytes(changed.read_bytes() + b'changed')
    assert not quality.verification_response_is_complete(tmp_path, path)



def test_expired_operation_never_starts_replacement_review(tmp_path, monkeypatch):
    now = [0.0]
    def primary(request, response, revision):
        now[0] = 181.0
        return None
    def forbidden(*args):
        pytest.fail("Replacement started after the persisted operation deadline")
    result, revision, scopes = operation(tmp_path, monkeypatch, FAMILIES[-1], primary, forbidden,
                                        clock=lambda: now[0])
    assert result['status'] in {'review_required', 'timeout'}, result
    assert not scopes


def test_changed_checkpoint_invalidates_previously_completed_review(tmp_path, monkeypatch):
    def primary(request, response, revision):
        response['section_assessments'] = response['section_assessments'][:2]
        response['cross_document_assessments'] = []
        return response
    result, revision, scopes = operation(tmp_path, monkeypatch, FAMILIES[-1], primary,
                                        lambda request, response, revision, handoff: response)
    assert result['status'] == 'passed', result
    request_path = next((revision / 'hermes/verification-requests').glob('*content.json'))
    request = json.loads(request_path.read_text())
    response = json.loads((revision / request['response_path']).read_text())
    checkpoint = revision / response['review_progress_evidence'][0]['path']
    checkpoint.write_bytes(checkpoint.read_bytes() + b' ')
    assert not quality.verification_response_is_complete(revision, request_path)



def test_bare_blocked_judgment_is_not_promoted_from_complete_rows(tmp_path, monkeypatch):
    def blocked(request, response, revision, *args):
        response['status'] = 'blocked'
        return response
    result, revision, scopes = operation(tmp_path, monkeypatch, FAMILIES[-1], blocked, blocked)
    assert result['status'] == 'review_required', result
    assert len(scopes) == 2
