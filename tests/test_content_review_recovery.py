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


def operation(tmp_path, monkeypatch, family, primary_review, fallback_review, *, clock=None, visual_review=None, repair=None, render=None):
    import drafting
    from pathlib import Path
    monkeypatch.setattr(workflow, 'render_assurance', render or controlled_render)
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
            if request['task'] == 'document_repair' and repair:
                response = repair(request, revision)
            elif request['task'] in {'section_drafting', 'prs_narrative_drafting'}:
                response = drafting.recorded_acceptance_response(request)
            else:
                response = acceptance_verification(request)
                if request['task'] == 'clinical_content_verification':
                    if handoff.get('reviewer_owner') == 'replacement':
                        fallback_scopes.append(handoff['review_resume'])
                        response = fallback_review(request, response, revision, handoff)
                    else:
                        response = primary_review(request, response, revision)
                if request['task'] == 'rendered_page_visual_verification' and visual_review:
                    response = visual_review(request, response, revision, fallback)
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
