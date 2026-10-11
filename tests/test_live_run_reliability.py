"""Regressions from observed Hermes runs; controlled evidence, not live certification."""
import json
import zipfile
from pathlib import Path
from lxml import etree as ET

import pytest

import quality
import workflow
from test_review_resolutions import review_candidate


def publish(tmp_path, path, request, response):
    log = tmp_path / f"{request['request_id']}.worker.log"
    log.write_text(json.dumps(response))
    return workflow._production_publish_quiet_response(tmp_path, {
        'task': request['task'], 'request_path': path.relative_to(tmp_path).as_posix(),
        'response_path': request['response_path'],
    }, log)


def test_native_review_has_readable_complete_package_evidence(tmp_path):
    path, request, response = review_candidate(tmp_path)
    inspection = request['native_inspection'][0]
    native = tmp_path / inspection['native_path']
    view = tmp_path / inspection['path']
    payload = json.loads(view.read_text())
    assert payload['native_sha256'] == quality.sha256_file(native)
    with zipfile.ZipFile(native) as archive:
        xml_names = {name for name in archive.namelist() if name.endswith(('.xml', '.rels'))}
        assert set(payload['xml_parts']) == xml_names
        for name in xml_names:
            parser = ET.XMLParser(remove_blank_text=True)
            original = ET.fromstring(archive.read(name), parser=parser)
            inspected = ET.fromstring('\n'.join(payload['xml_parts'][name]).encode(), parser=parser)
            assert ET.tostring(original) == ET.tostring(inspected)
    assert any(name.startswith('word/header') for name in payload['xml_parts'])
    assert 'word/_rels/document.xml.rels' in payload['xml_parts']
    assert publish(tmp_path, path, request, response)
    view.write_text('{}')
    assert not quality.verification_response_is_complete(tmp_path, path)
    findings, _ = quality.validate_verifications(tmp_path, request_paths=[path])
    assert any(row.get('code') == 'native_inspection_changed' for row in findings)


def test_inspection_failure_is_consumed_as_tooling_without_document_repair(tmp_path):
    path, request, response = review_candidate(tmp_path)
    response.update(status='blocked', error={
        'type': 'native_inspection_incomplete',
        'message': 'Read-only native inspection is denied in this worker session.',
    }, findings=[{'artifact': 'package', 'issue': 'Native inspection is unavailable.'}],
        section_assessments=[], cross_document_assessments=[])
    assert publish(tmp_path, path, request, response)
    assert not quality.verification_response_is_complete(tmp_path, path)
    findings, evidence = quality.validate_verifications(tmp_path, request_paths=[path])
    assert evidence
    assert len(findings) == 1
    assert findings[0]['recovery_class'] == 'capability_gap'
    assert findings[0]['code'] == 'native_inspection_incomplete'


def test_invalid_assessment_response_is_preserved_with_precise_feedback(tmp_path):
    path, request, response = review_candidate(tmp_path)
    response['section_assessments'] = []
    assert not publish(tmp_path, path, request, response)
    assert json.loads((tmp_path / request['response_path']).read_text()) == response
    findings, _ = quality.validate_verifications(tmp_path, request_paths=[path])
    assert any('Every contracted section' in row['issue'] for row in findings)
    assert not any(row.get('code') == 'verification_response_missing' for row in findings)
    retry = workflow._awaiting(tmp_path, stage='independent_verification', paths=[path])
    assert any('Every contracted section' in message
               for message in retry['handoffs'][0]['response_repair_feedback'])


def test_sterling_visual_review_shares_reserved_fields_authority(tmp_path):
    from test_desktop_delivery import _visual_handoff_fixture
    handoff, visual_request, _ = _visual_handoff_fixture(tmp_path, 'icf')
    revision = tmp_path / 'revisions/r1'
    (revision / 'candidate/icf.docx').unlink()
    path, request, _ = review_candidate(revision, template='Sterling')
    from rendering import render_documents
    render_documents(Path(__file__).resolve().parents[1], revision, request['approved_source'],
                     {'protocol': [], 'icf': {}, 'prs': {}}, artifact_names={'icf'})
    source = request['approved_source']
    paths = quality.create_verification_requests(path.parents[2], source, {
        'artifacts': visual_request['artifacts']}, review_set=2)
    requests = [json.loads(p.read_text()) for p in paths]
    content, visual = requests
    assert content['template_preservation'] == visual['template_preservation']
    assert '«Protocol_No»' in visual['template_preservation']
    assert 'repeated headers' in visual['template_preservation']
    assert 'bound page' in visual['instructions']


@pytest.mark.parametrize('branch', ['Prospective', 'Ambispective', 'Retrospective'])
def test_oversight_and_citation_facts_reach_their_drafting_sections(tmp_path, branch):
    import contracts
    import drafting
    root = Path(__file__).resolve().parents[1]
    source = json.loads((root / f'tests/fixtures/{branch.lower()}-acceptance-source.json').read_text())
    source['parties']['irb']['status'] = 'Not submitted; no approval, exemption or consent waiver has been granted.'
    source['ethics'] = {'approval_status': source['parties']['irb']['status']}
    source['study']['background'] = 'Existing evidence is limited [1].'
    source['study']['references'] = ['1. Fictional reference supplied for testing.']
    for section_id in ('ethics', 'introduction', 'subjects.population'):
        batch = next(batch for batch in contracts.batch_plan(branch) if section_id in batch.section_ids)
        path = drafting.create_drafting_request(repo_root=root, revision_dir=tmp_path,
            revision_id=tmp_path.name, reference=source, batch=batch,
            target_ids=[section_id], attempts={section_id: 1}, wave='initial')
        request = json.loads(path.read_text())
        fields = request['section_contracts'][0]['minimum_evidence']
        if section_id == 'ethics':
            assert 'parties.irb' in fields and 'ethics' in fields
            assert request['approved_source']['parties']['irb']['status'] == source['parties']['irb']['status']
        elif section_id == 'introduction':
            assert 'study.references' in fields
            assert request['approved_source']['study']['references'] == source['study']['references']
        else:
            assert 'population.inclusion_criteria' in fields
        assert 'citation' in ' '.join(request['constraints']).lower()


def test_incomplete_native_review_stops_once_without_a_repair_handoff(tmp_path, monkeypatch):
    from test_clean_delivery import deliver, reminder_source
    from test_handoff_quality import acceptance_verification
    reviews = []
    def review(request):
        response = acceptance_verification(request)
        if request['task'] == 'clinical_content_verification':
            reviews.append(request['request_id'])
            response.update(status='blocked', error={
                'type': 'native_inspection_incomplete', 'message': 'read_file is denied for the complete native evidence.'},
                findings=[{'artifact': 'package', 'issue': 'Tooling is unavailable.'}],
                section_assessments=[], cross_document_assessments=[])
        return response
    result, revision = deliver(tmp_path, monkeypatch, reminder_source(), review=review)
    assert result['status'] == 'blocked', result
    assert result['stage'] == 'review_tooling'
    assert len(reviews) == 1
    assert not list((revision / 'hermes/repair-requests').glob('*.json'))
    assert not result['client_outputs']
    assert result['candidate_outputs']


def test_incomplete_response_gets_feedback_and_recovers_in_public_desktop_operation(tmp_path, monkeypatch):
    import drafting
    from test_clean_delivery import controlled_render, reminder_source
    from test_handoff_quality import acceptance_verification
    monkeypatch.setattr(workflow, 'render_assurance', controlled_render)
    source_path = tmp_path / 'reference/study.reference.json'
    source_path.parent.mkdir()
    source_path.write_text(json.dumps(reminder_source()))
    assert workflow.prepare(tmp_path)['status'] == 'awaiting_approval'
    approval = workflow.approve(tmp_path, approved_by='controlled-fixture-owner')
    revision = tmp_path / 'revisions' / approval['revision_id']
    feedback = []
    def dispatch(handoffs, _remaining):
        for handoff in handoffs:
            path = revision / handoff['request_path']
            request = json.loads(path.read_text())
            if request['task'] in {'section_drafting', 'prs_narrative_drafting'}:
                response = drafting.recorded_acceptance_response(request)
                target = revision / request['response_path']
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(response))
                continue
            response = acceptance_verification(request)
            if request['task'] == 'clinical_content_verification':
                feedback.append(handoff.get('response_repair_feedback', []))
                if len(feedback) == 1:
                    response['section_assessments'] = []
                    assert not publish(revision, path, request, response)
                    continue
            assert publish(revision, path, request, response)
    result = workflow.run_desktop_operation(tmp_path, handoff_runner=dispatch,
        opener=lambda path: Path(path).read_bytes(), budget_seconds=2700, require_promoted_runtime=False)
    assert result['status'] == 'passed', result
    assert len(feedback) == 2 and not feedback[0]
    assert any('Every contracted section' in message for message in feedback[1]), feedback
    assert result['changed_native_repairs'] == 0
    retained = list((revision / 'hermes/verification-rejections').glob('*.json'))
    assert len(retained) == 1
    assert json.loads(retained[0].read_text())['section_assessments'] == []
