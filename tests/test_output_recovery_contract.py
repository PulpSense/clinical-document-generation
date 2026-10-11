"""Public recovery handoffs reject edits that lack exact approved authority."""
import copy
import json
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
import drafting
from output_recovery import apply_xml_repairs
from prs_xml import generate
from test_construction_reliability import source_for


def request_for(tmp_path):
    revision = tmp_path / 'r-fields'
    attempt = revision / 'attempts/quality-a01'
    path = attempt / 'candidate/study.xml'
    path.parent.mkdir(parents=True)
    source = source_for('Ambispective', 'Advarra')
    source['parties']['study_coordinator'].update(name='Casey Example', first_name='Casey', last_name='Example')
    (revision / 'approved-reference.json').write_text(json.dumps(source))
    generate(Path('assets/client-templates/prs/clinicaltrials_prs_full_placeholder_template.xml'), path,
             source, {'brief_summary': 'Summary.', 'detailed_description': 'Description.'})
    tree = ET.parse(path)
    node = tree.getroot().find('.//overall_contact')
    node.find('middle_name').text = 'Invented'
    tree.write(path, encoding='utf-8', xml_declaration=True)
    raw = {'artifact': 'study.xml', 'target_ids': ['prs.structured'], 'check': 'source_supported',
           'source_path': 'parties.study_coordinator', 'affected_passage': ET.tostring(node, encoding='unicode'),
           'issue': 'The middle name is invented.', 'material': True}
    finding = {**raw, 'verification_source_finding': raw, 'recovery_class': 'deterministic_structure_defect'}
    (attempt / 'attempt-manifest.json').write_text(json.dumps({
        'findings': [finding], 'files': {'candidate/study.xml': drafting.sha256_file(path)}}))
    governing = drafting.governing_resources(Path(__file__).resolve().parents[1], source)
    request = json.loads(drafting.create_construction_repair_request(
        revision, source, attempt_path='attempts/quality-a01', finding_index=0, attempt=1, governing=governing).read_text())
    response = drafting.response_template(request, model_id='Controlled field editor')
    field = next(r for r in request['construction_repair']['fields'] if '/middle_name[' in r['path'])
    response['field_edits'] = [{'path': field['path'], 'before': field['before'], 'after': '',
                               'source_path': 'parties.study_coordinator'}]
    return revision, path, source, governing, request, response


def test_scoped_removal_is_authenticated_and_preserves_other_native_values(tmp_path):
    revision, path, source, governing, request, response = request_for(tmp_path)
    before = ET.parse(path).getroot()
    response_path = revision / request['response_path']
    response_path.parent.mkdir(parents=True, exist_ok=True)
    response_path.write_text(json.dumps(response))
    assert not drafting.ingest_responses(revision, governing)
    record = next((revision / 'hermes/accepted').glob('construction-*.json'))
    accepted = json.loads(record.read_text())
    apply_xml_repairs(path, [accepted])
    after = ET.parse(path).getroot()
    assert after.findtext('.//overall_contact/middle_name') == ''
    assert after.findtext('.//overall_contact/first_name') == 'Casey'
    assert after.findtext('.//overall_contact/email') == before.findtext('.//overall_contact/email')
    assert json.loads((revision / 'approved-reference.json').read_text()) == source
    # An accepted record is never authority independently of its bound response.
    accepted['after'][0]['after'] = 'Injected'
    record.write_text(json.dumps(accepted))
    assert any(r['category'] == 'request-integrity' for r in drafting.ingest_responses(revision, governing))


@pytest.mark.parametrize('mutation', ['invented', 'out-of-scope', 'unknown-node', 'identifier', 'stale',
    'duplicate', 'unchanged', 'wrong-type', 'markup', 'source-deletion', 'malformed-envelope'])
def test_recovery_handoff_rejects_ungrounded_or_unbounded_edits(tmp_path, mutation):
    revision, path, source, governing, request, response = request_for(tmp_path)
    edit = response['field_edits'][0]
    if mutation == 'invented': edit['after'] = 'Invented new name'
    elif mutation == 'out-of-scope': edit['source_path'] = 'parties.principal_investigator'
    elif mutation == 'unknown-node': edit['path'] = '../../source.json'
    elif mutation == 'identifier': edit['path'] = 'clinical_study/uid[1]'
    elif mutation == 'stale': edit['before'] = 'Old candidate'
    elif mutation == 'duplicate': response['field_edits'].append(copy.deepcopy(edit))
    elif mutation == 'unchanged': edit['after'] = edit['before']
    elif mutation == 'wrong-type': edit['after'] = None
    elif mutation == 'markup': edit['after'] = '<script/>'
    elif mutation == 'source-deletion':
        field = next(r for r in request['construction_repair']['fields'] if '/first_name[' in r['path'])
        edit.update(path=field['path'], before=field['before'])
    else: response['request_sha256'] = 'stale'
    accepted, findings = drafting.validate_response(request, response)
    assert accepted is None and findings


def test_recovery_rejects_changed_archive_or_request(tmp_path):
    revision, path, source, governing, request, response = request_for(tmp_path)
    request['approved_source']['parties']['study_coordinator']['name'] = 'Injected'
    request['request_sha256'] = drafting.request_sha256(request)
    (revision / 'hermes/requests' / f"{request['request_id']}.json").write_text(json.dumps(request))
    assert any(r['category'] == 'request-integrity' for r in drafting.ingest_responses(revision, governing))


def test_exact_indexed_location_disambiguates_repeated_native_values(tmp_path):
    from output_recovery import xml_repair_spec
    path = tmp_path / 'study.xml'
    path.write_text('<root><clinical_study><location><contact><first_name>Wrong</first_name></contact></location>'
                    '<location><contact><first_name>Wrong</first_name></contact></location></clinical_study></root>')
    reference = {'sites': [{'contact': {'first_name': 'Alex'}}, {'contact': {'first_name': 'Casey'}}]}
    spec = xml_repair_spec(path, reference, {'source_path': 'sites[1].contact.first_name',
        'affected_passage': '<first_name>Wrong</first_name>',
        'document_locations': ['study.xml — clinical_study/location[2]/contact[1]/first_name[1]']})
    assert spec and spec['fields'][0]['path'] == 'clinical_study/location[2]/contact[1]/first_name[1]'


def test_material_generated_prose_can_correct_a_number_from_scoped_source(tmp_path):
    revision, path, source, governing, request, _ = request_for(tmp_path)
    spec = request['construction_repair']
    spec.pop('kind')
    spec.update(artifact='icf', section_id='icf.shell', before='The study will include 49 participants.',
                source_paths=['population.sample_size'])
    request['approved_source'] = {'population': {'sample_size': '40 participants'}}
    request['section_contracts'] = [{'section_id': 'icf.shell', 'minimum_evidence': ['population.sample_size'],
                                     'allowed_modes': ['agent_draft'], 'fixed_boilerplate': []}]
    request['attempts'] = {'icf.shell': 1}
    request['request_sha256'] = drafting.request_sha256(request)
    response = drafting.response_template(request, model_id='Controlled source editor')
    response['section_results'][0]['paragraphs'] = [{'text': 'The study will include 40 participants.',
        'evidence_refs': ['source:population.sample_size']}]
    accepted, findings = drafting.validate_response(request, response)
    assert accepted and not findings
    response['section_results'][0]['paragraphs'][0]['text'] = 'The study will include 41 participants.'
    accepted, findings = drafting.validate_response(request, response)
    assert accepted is None and findings


def test_grounded_value_in_wrong_xml_field_is_rejected_before_acceptance(tmp_path):
    revision, path, source, governing, request, response = request_for(tmp_path)
    field = next(r for r in request['construction_repair']['fields'] if '/email[' in r['path'])
    response['field_edits'] = [{'path': field['path'], 'before': field['before'],
        'after': source['parties']['study_coordinator']['business_phone'], 'source_path': 'parties.study_coordinator'}]
    response_path = revision / request['response_path']
    response_path.parent.mkdir(parents=True, exist_ok=True)
    response_path.write_text(json.dumps(response))
    findings = drafting.ingest_responses(revision, governing)
    assert findings and not list((revision / 'hermes/accepted').glob('construction-*.json'))
    assert findings[0].get('construction_request_id') == request['request_id']


def test_overlapping_native_edits_replay_in_archived_chronological_order(tmp_path):
    path = tmp_path / 'study.xml'
    path.write_text('<root><clinical_study><overall_contact><middle_name>Wrong</middle_name>'
                    '</overall_contact></clinical_study></root>')
    field = 'clinical_study/overall_contact[1]/middle_name[1]'
    first = {'repair_kind': 'xml_fields', 'sequence': 1, 'attempt': 2, 'after': [
        {'path': field, 'before': 'Wrong', 'after': 'Intermediate'}]}
    second = {'repair_kind': 'xml_fields', 'sequence': 2, 'attempt': 1, 'after': [
        {'path': field, 'before': 'Intermediate', 'after': 'Correct'}]}
    apply_xml_repairs(path, [second, first])
    assert ET.parse(path).getroot().findtext('.//middle_name') == 'Correct'


def test_secondary_study_identifiers_are_outside_field_editor_authority(tmp_path):
    from output_recovery import xml_repair_spec
    path = tmp_path / 'study.xml'
    path.write_text('<root><clinical_study><id_info><secondary_id>Original</secondary_id>'
                    '</id_info></clinical_study></root>')
    assert xml_repair_spec(path, {'meta': {'protocol_number': 'Approved'}}, {
        'source_path': 'meta.protocol_number', 'affected_passage': '<secondary_id>Original</secondary_id>'}) is None
