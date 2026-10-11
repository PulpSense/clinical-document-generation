"""Rule-bound adjudication exercised through controlled public generation/delivery."""
import json
from pathlib import Path

import pytest
from docx import Document

import drafting
import quality
import workflow
from test_clean_delivery import deliver, reminder_source, CASES, ROOT
from test_handoff_quality import acceptance_verification


@pytest.mark.parametrize('branch', ['Prospective', 'Ambispective', 'Retrospective'])
def test_registered_protocol_proxy_delivers_unchanged_with_rule_bound_decision(tmp_path, monkeypatch, branch):
    source = quality.branch_acceptance_source(ROOT, next(
        case for case in CASES if case['descriptor']['study_type'] == branch))
    if branch == 'Retrospective':
        source['meta']['icf_template'] = ''
    source['statistics']['analysis_populations'] = (
        'The analysis population consists of all eligible participants with complete baseline and follow-up assessments.')
    source['statistics']['analysis_plan'] = source['statistics']['analysis_populations']
    text = 'We will analyze people who qualify and have observations from both their initial and later measurements.'

    def draft(request):
        response = drafting.recorded_acceptance_response(request)
        for row in response.get('section_results', []):
            if row['section_id'] == 'analysis-plan.datasets':
                for paragraph in row['paragraphs']:
                    if any(ref in paragraph['evidence_refs'] for ref in (
                            'source:statistics.analysis_populations', 'source:statistics.analysis_plan')):
                        paragraph['text'] = text
        return response

    def review(request):
        response = acceptance_verification(request)
        for decision in response.get('uncertainty_resolutions', []):
            caution = next(row for row in request['lexical_review_cautions']
                           if row['caution_sha256'] == decision['caution_sha256'])
            if caution['caution'].get('rule_id') == 'protocol.source-coverage.lexical':
                decision.update(affected_passage=text,
                                source_excerpt=source['statistics']['analysis_populations'],
                                rationale='The passage preserves eligibility and availability of both initial and later measurements.')
        return response

    result, revision = deliver(tmp_path, monkeypatch, source, review=review,
                               draft=draft)
    assert result['status'] == 'passed', result
    assert result['warnings'] == []
    manifest = json.loads((tmp_path / result['manifest']).read_text())
    decisions = manifest['quality']['resolved_evidence_cautions']
    decision = next(row for row in decisions if row['section_id'] == 'analysis-plan.datasets'
                    and row['caution'].get('rule_id') == 'protocol.source-coverage.lexical')
    assert decision['rule_id'] == 'protocol.source-coverage.lexical'
    assert decision['rule_version'] == 1 and decision['rule_contract_sha256']
    assert decision['revision_id'] == revision.name
    assert decision['generation_authority_sha256']
    assert decision['caution']['publication_disposition'] == 'blocking'
    assert decision['artifact_sha256'] == quality.sha256_file(tmp_path / 'output/protocol.docx')
    assert text in '\n'.join(p.text for p in Document(tmp_path / 'output/protocol.docx').paragraphs)
    assert workflow.confirm_desktop_delivery(manifest, result['desktop_reply'],
                                            lambda path: Path(path).read_bytes())['confirmed']


@pytest.fixture(scope='module')
def rule_review_seed(tmp_path_factory):
    """Create one genuinely passing public operation; clone bound evidence for negatives."""
    run = tmp_path_factory.mktemp('registered-review-seed')
    source = reminder_source()
    source['statistics']['analysis_populations'] = (
        'The analysis population consists of all eligible participants with complete baseline and follow-up assessments.')
    source['statistics']['analysis_plan'] = source['statistics']['analysis_populations']
    text = 'We will analyze people who qualify and have observations from both their initial and later measurements.'
    def draft(request):
        response = drafting.recorded_acceptance_response(request)
        for row in response.get('section_results', []):
            if row['section_id'] == 'analysis-plan.datasets':
                for paragraph in row['paragraphs']:
                    paragraph['text'] = text
        return response
    def review(request):
        response = acceptance_verification(request)
        for decision in response.get('uncertainty_resolutions', []):
            caution = next(row for row in request['lexical_review_cautions']
                           if row['caution_sha256'] == decision['caution_sha256'])
            if caution['section_id'] == 'analysis-plan.datasets':
                decision.update(affected_passage=text,
                                source_excerpt=source['statistics']['analysis_populations'],
                                rationale='Eligibility and both initial and later observations are retained.')
        return response
    with pytest.MonkeyPatch.context() as patch:
        result, revision = deliver(run, patch, source, review=review, draft=draft)
    assert result['status'] == 'passed', result
    return revision


def registered_review_candidate(tmp_path, rule_review_seed):
    import shutil
    revision = tmp_path / rule_review_seed.name
    shutil.copytree(rule_review_seed, revision)
    request_path = next((revision / 'hermes/verification-requests').glob('*content.json'))
    request = json.loads(request_path.read_text())
    response = json.loads((revision / request['response_path']).read_text())
    assert quality.verification_response_is_complete(revision, request_path)
    return revision, request_path, request, response


@pytest.mark.parametrize('corruption', ['bare-pass', 'fabricated-passage', 'fabricated-source',
                                      'rule-id', 'rule-version', 'rule-contract', 'revision', 'generation',
                                      'target', 'artifact-hash', 'source-hash'])
def test_registered_decision_rejects_unbound_or_fabricated_authority(tmp_path, corruption, rule_review_seed):
    revision, path, request, response = registered_review_candidate(tmp_path, rule_review_seed)
    if corruption == 'bare-pass':
        response['uncertainty_resolutions'] = []
    else:
        caution = next(row for row in request['lexical_review_cautions']
                       if row['caution'].get('rule_id') == 'protocol.source-coverage.lexical')
        decision = next(row for row in response['uncertainty_resolutions']
                        if row['caution_sha256'] == caution['caution_sha256'])
        field, value = {
            'fabricated-passage': ('affected_passage', 'A nonexistent passage.'),
            'fabricated-source': ('source_excerpt', 'A nonexistent approved fact.'),
            'rule-id': ('rule_id', 'another.condition'),
            'rule-version': ('rule_version', 999),
            'rule-contract': ('rule_contract_sha256', '0' * 64),
            'revision': ('revision_id', 'stale-source-revision'),
            'generation': ('generation_authority_sha256', '0' * 64),
            'target': ('section_id', 'introduction'),
            'artifact-hash': ('artifact_sha256', '0' * 64),
            'source-hash': ('approved_source_sha256', '0' * 64),
        }[corruption]
        decision[field] = value
    (revision / request['response_path']).write_text(json.dumps(response))
    assert not quality.verification_response_is_complete(revision, path)
    findings, _ = quality.validate_verifications(revision, request_paths=[path])
    assert any(row.get('code') == 'uncertainty_resolution_invalid' for row in findings)


def test_registered_faithful_decision_does_not_clear_companion_defect(tmp_path, rule_review_seed):
    revision, path, request, response = registered_review_candidate(tmp_path, rule_review_seed)
    response['status'] = 'blocked'
    response['findings'].append({
        'finding_id': 'unsupported-treatment', 'category': 'content', 'artifact': 'protocol', 'target_ids': ['introduction'],
        'check': 'no_invention', 'issue': 'The introduction introduces an unsupported treatment.',
        'material': True, 'contradiction': True,
    })
    for row in response['section_assessments']:
        if row['section_id'] == 'introduction':
            row['status'] = 'blocked'
    (revision / request['response_path']).write_text(json.dumps(response))
    findings, evidence = quality.validate_verifications(revision, request_paths=[path])
    assert any(row.get('check') == 'no_invention' for row in findings)
    assert any(row.get('rule_id') == 'protocol.source-coverage.lexical'
               and row['disposition'] == 'faithful'
               for row in evidence['clinical_content_verification']['uncertainty_resolutions'])
