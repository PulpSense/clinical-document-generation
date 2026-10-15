"""Mixed repair must not launder rejected complete-scope review bindings."""
import json
import pytest
import quality
import workflow
from test_desktop_delivery import _visual_handoff_fixture


@pytest.mark.parametrize('artifact,page', [('protocol', 1), ('protocol', 999), ('icf', 1)])
def test_rejected_complete_visual_finding_stops_partial_native_repair(tmp_path, artifact, page):
    handoff, request, response = _visual_handoff_fixture(tmp_path, 'protocol')
    revision = tmp_path / 'revisions/r1'
    response['status'] = response['page_assessments'][0]['status'] = 'blocked'
    response['findings'] = [{'artifact': artifact, 'page': page,
        'check': 'template_preservation', 'element': 'Controlled cover',
        'issue': 'Controlled reported native concern'}]
    path = revision / handoff['response_path']
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(response))
    findings, evidence = quality.validate_verifications(revision)
    assert evidence
    valid = (artifact, page) == ('protocol', 1)
    assert any(f.get('recovery_class') == 'verifier_transient' for f in findings) is not valid
    assert quality.verification_response_is_terminal(revision, revision / handoff['request_path']) is valid
    partial = {'partial_review': True, 'recovery_class': 'drafting_defect',
        'verification_source_finding': {'finding_id': 'partial-1', 'check': 'source_supported',
            'issue': 'Controlled supported native concern'}}
    coverage = {'code': 'review_coverage_incomplete', 'recovery_class': 'verifier_transient'}
    chosen = workflow._accepted_partial_repair_findings(revision, findings=[partial, coverage, *findings])
    if valid:
        assert chosen == [partial, *findings]
    else:
        assert chosen == []
