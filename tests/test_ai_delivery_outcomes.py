"""Honest terminal Desktop handoff; adapters do not establish live timing or judgment."""
import json
from pathlib import Path
import pytest
import workflow
from test_review_output import _candidate_run


def operation(run_dir, **kwargs):
    return workflow.run_desktop_operation(
        run_dir, handoff_runner=lambda *_: None, opener=lambda path: Path(path).read_bytes(),
        budget_seconds=30, runtime_identity={'executable': '/test/python', 'implementation': 'CPython', 'version': '3.11'},
        release_identity={'package_fingerprint': 'test-release'}, **kwargs)


def test_deadline_delivers_complete_review_only_with_unresolved_and_incomplete_notice(tmp_path, monkeypatch):
    run, _ = _candidate_run(tmp_path, monkeypatch, 'Retrospective')
    now = [100.0]
    def pending(*args, **kwargs):
        now[0] = 131.0
        return {'status': 'awaiting_hermes', 'stage': 'independent_verification',
                'findings': [{'issue': 'Visit timing remains disputed.', 'material': True}], 'client_outputs': []}
    monkeypatch.setattr(workflow, 'generate', pending)
    result = operation(run, clock=lambda: now[0], wall_clock=lambda: now[0])
    assert result['status'] == 'review_required', result
    assert result['terminal_cause'] == 'timeout'
    assert result['deadline_at_epoch'] == 130.0
    assert result['review_delivery']['confirmed'] is True
    assert result['client_outputs'] == []
    assert len(result['review_outputs']) == 1
    item = result['review_outputs'][0]
    assert item['link'] == f"[{item['filename']}](<{item['absolute_path']}>)"
    report = json.loads((run / result['review_findings']).read_text())
    assert any('Visit timing' in finding['issue'] for finding in report['findings'])
    assert report['incomplete_assessments']
    assert 'NOT CLIENT READY' in (run / result['review_notice']).read_text()


def test_review_only_terminal_replay_rechecks_hashes_without_regeneration(tmp_path, monkeypatch):
    run, _ = _candidate_run(tmp_path, monkeypatch, 'Retrospective')
    monkeypatch.setattr(workflow, 'generate', lambda *_args, **_kw: {
        'status': 'blocked', 'stage': 'document_repair_unresolved',
        'findings': [{'issue': 'Substantive concern remains.'}], 'client_outputs': []})
    first = operation(run)
    assert first['status'] == 'review_required'
    monkeypatch.setattr(workflow, 'generate', lambda *_args, **_kw: pytest.fail('terminal replay regenerated'))
    assert operation(run)['review_outputs'] == first['review_outputs']
    assert operation(run)['deadline_at_epoch'] == first['deadline_at_epoch']
    Path(first['review_outputs'][0]['absolute_path']).write_bytes(b'corrupted')
    replay = operation(run)
    assert replay['status'] == 'blocked'
    assert replay['stage'] == 'terminal_delivery_validation'
    assert not replay.get('review_outputs')


def test_normal_target_is_under_twenty_five_minutes_not_a_review_waiver(tmp_path, monkeypatch):
    run, _ = _candidate_run(tmp_path, monkeypatch, 'Retrospective')
    now = [100.0]
    def fail(*args, **kwargs):
        now[0] += 1450.0
        return {'status': 'blocked', 'stage': 'document_repair_no_progress', 'client_outputs': []}
    monkeypatch.setattr(workflow, 'generate', fail)
    result = workflow.run_desktop_operation(run, handoff_runner=lambda *_: None,
        opener=lambda path: Path(path).read_bytes(), clock=lambda: now[0], wall_clock=lambda: now[0],
        runtime_identity={'executable': '/test/python', 'implementation': 'CPython', 'version': '3.11'},
        release_identity={'package_fingerprint': 'test-release'})
    assert result['status'] == 'review_required'
    assert result['under_25_minutes'] is True
    assert result['performance_classification'] == 'target_window'
    assert result['deadline_at_epoch'] == 2800
    assert result['stage_timings']['desktop_delivery']['invocations'] == 1
    assert workflow.performance_classification(1500) == 'above_target_within_deadline'


@pytest.mark.parametrize('branch,template', [('Retrospective','Advarra'), ('Prospective','Advarra'),
    ('Prospective','Sterling'), ('Ambispective','Advarra'), ('Ambispective','Sterling')])
def test_unresolved_general_repair_delivers_every_usable_branch_file(tmp_path, monkeypatch, branch, template):
    import drafting
    import quality
    from test_clean_delivery import controlled_render, ROOT, CASES
    from test_handoff_quality import acceptance_verification
    source = quality.branch_acceptance_source(ROOT, next(case for case in CASES
        if case['descriptor']['study_type'] == branch
        and (branch == 'Retrospective' or case['descriptor']['icf_template'] == template)))
    path = tmp_path / 'reference/study.reference.json'
    path.parent.mkdir()
    path.write_text(json.dumps(source))
    workflow.prepare(tmp_path)
    approved = workflow.approve(tmp_path)
    revision = tmp_path / 'revisions' / approved['revision_id']
    monkeypatch.setattr(workflow, 'render_assurance', controlled_render)
    def handoff(handoffs, _remaining):
        for item in handoffs:
            request = json.loads((revision / item['request_path']).read_text())
            if request['task'] == 'document_repair':
                from test_general_document_repair import repair_response
                response = repair_response(request, status='needs_review', summary='No safe correction without resolving the substantive concern.')
            elif request['task'] in {'section_drafting', 'prs_narrative_drafting'}:
                response = drafting.recorded_acceptance_response(request)
            else:
                response = acceptance_verification(request)
                if request['task'] == 'clinical_content_verification':
                    response['status'] = 'blocked'
                    response['findings'] = [{'finding_id':'visit-concern', 'artifact':'protocol',
                        'check':'source_supported', 'target_ids':['introduction'], 'material':True,
                        'issue':'The approved visit timing needs correction.'}]
                    next(row for row in response['section_assessments'] if row['section_id']=='introduction')['status']='blocked'
            response_path = revision / request['response_path']
            response_path.parent.mkdir(exist_ok=True, parents=True)
            response_path.write_text(json.dumps(response))
    result = workflow.run_desktop_operation(tmp_path, handoff_runner=handoff,
        opener=lambda path: Path(path).read_bytes(), require_promoted_runtime=False,
        runtime_identity={'executable':'/test/python', 'implementation':'CPython', 'version':'3.11'},
        release_identity={'package_fingerprint':'test-release'})
    assert result['status'] == 'review_required', result
    assert result['stage'] == 'document_repair_unresolved'
    assert result['review_delivery']['confirmed']
    assert len(result['review_outputs']) == (1 if branch == 'Retrospective' else 3)


@pytest.mark.parametrize('damage', ['incomplete', 'unreadable', 'source_untrusted', 'transport'])
def test_unusable_or_untrustworthy_package_is_unavailable(tmp_path, monkeypatch, damage):
    run, candidate = _candidate_run(tmp_path, monkeypatch, 'Retrospective')
    if damage == 'incomplete':
        (candidate / 'protocol.docx').unlink()
    elif damage == 'unreadable':
        path = candidate / 'protocol.docx'
        path.write_bytes(b'not a Word document')
        snapshot = candidate.parent / 'candidate-build.json'
        records = json.loads(snapshot.read_text())
        records['candidate_files'][0]['sha256'] = workflow.sha256_file(path)
        snapshot.write_text(json.dumps(records))
    elif damage == 'source_untrusted':
        monkeypatch.setattr(workflow, '_approval_valid', lambda *_args, **_kw: (False, 'changed source'))
    monkeypatch.setattr(workflow, 'generate', lambda *_args, **_kw: {
        'status':'blocked', 'stage':'document_repair_no_progress', 'client_outputs':[]})
    result = workflow.run_desktop_operation(run, handoff_runner=lambda *_: None,
        opener=lambda path: b'wrong bytes' if damage == 'transport' else Path(path).read_bytes(),
        runtime_identity={'executable':'/test/python','implementation':'CPython','version':'3.11'},
        release_identity={'package_fingerprint':'test-release'})
    assert result['status'] == 'blocked'
    assert not result.get('review_outputs')
    assert result['client_outputs'] == []


def test_review_only_notice_preserves_actual_native_finding_location(tmp_path, monkeypatch):
    run, _ = _candidate_run(tmp_path, monkeypatch, 'Retrospective')
    monkeypatch.setattr(workflow, 'generate', lambda *_args, **_kw: {
        'status': 'blocked', 'stage': 'document_repair_unresolved', 'client_outputs': [],
        'findings': [{'verification_source_finding': {'artifact': 'protocol',
            'target_ids': ['paragraph:17'], 'location': 'Protocol page 4, table 2, row 3',
            'element': 'Visit timing cell', 'issue': 'Unresolved timing discrepancy.', 'material': True}}]})
    result = operation(run)
    assert result['status'] == 'review_required'
    notice = (run / result['review_notice']).read_text()
    assert 'Protocol page 4, table 2, row 3' in notice
    assert 'Visit timing cell' in notice
