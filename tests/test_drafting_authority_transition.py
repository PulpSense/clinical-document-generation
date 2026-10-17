"""Exercise optional AI decisions through the public generation lifecycle."""
import json
from pathlib import Path

import pytest

import content_plan
import drafting
import workflow
from test_ai_content_plan import accept_plan

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('source_has_rule,plan_includes_rule', [(False, True), (True, False), (False, False), (True, True)])
def test_generation_uses_effective_authority_after_plan(tmp_path, monkeypatch, source_has_rule, plan_includes_rule):
    source = json.loads((ROOT / 'tests/fixtures/release-certification/ambispective-sterling/approved-reference.json').read_text())
    source.setdefault('procedures', {})['termination'] = 'The supplied termination policy.' if source_has_rule else None
    reference = tmp_path / 'reference/study.reference.json'
    reference.parent.mkdir(parents=True)
    reference.write_text(json.dumps(source))
    assert workflow.prepare(tmp_path)['status'] == 'awaiting_approval'
    assert workflow.approve(tmp_path, approved_by='controlled-test-owner')['status'] == 'passed'
    approved_bytes = reference.read_bytes()
    first = workflow.generate_only(tmp_path)
    assert first['stage'] == 'content_planning'
    workspace = Path(first['workspace'])

    def choose(plan):
        plan['source_sections']['endpoint-criteria.termination'] = {
            'include': plan_includes_rule,
            'blocks': [{'text': 'The AI-selected termination policy.', 'bullet': False}] if plan_includes_rule else [],
        }
    request, response = accept_plan(first, choose)
    base_authority = request['governing_resources']
    planned = content_plan.with_plan(request['approved_source'], response['plan'])
    effective_authority = drafting.governing_resources(ROOT, planned)
    assert (base_authority != effective_authority) == (source_has_rule != plan_includes_rule)
    assert workspace.name == drafting.sha256_value(base_authority)[:16]

    result = workflow.generate_only(tmp_path)
    assert result['status'] == 'awaiting_hermes', result
    assert result['stage'] == 'drafting'
    assert len(result['requests']) == 4
    assert result['workspace'] == str(workspace)
    saved_responses = []
    for relative in result['requests']:
        draft_request = json.loads((workspace / relative).read_text())
        assert draft_request['governing_resources'] == effective_authority
        assert drafting._trusted_request_valid(workspace, draft_request, effective_authority)
        answer = drafting.recorded_acceptance_response(draft_request)
        path = workspace / draft_request['response_path']
        path.write_text(json.dumps(answer))
        saved_responses.append((path, answer))

    # The effective identity must not weaken accepted-plan immutability.
    plan_path = workspace / request['response_path']
    original_plan_bytes = plan_path.read_bytes()
    changed_plan = json.loads(original_plan_bytes)
    changed_plan['plan']['source_sections']['endpoint-criteria.termination']['include'] = not plan_includes_rule
    plan_path.write_text(json.dumps(changed_plan))
    assert workflow.generate_only(tmp_path)['stage'] == 'content_plan_response'
    plan_path.write_bytes(original_plan_bytes)

    # A stale response remains a binding error even when the plan changes authority.
    path, answer = saved_responses[0]
    path.write_text(json.dumps({**answer, 'request_sha256': 'stale-request'}))
    assert workflow.generate_only(tmp_path)['stage'] == 'drafting_response'
    path.write_text(json.dumps(answer))
    result = workflow.generate_only(tmp_path)
    assert result['status'] == 'awaiting_hermes', result
    assert len(result['requests']) == 1
    prs = json.loads((workspace / result['requests'][0]).read_text())
    assert prs['task'] == 'prs_narrative_drafting'
    assert prs['governing_resources'] == effective_authority
    assert len(list((workspace / 'hermes/accepted').glob('*.json'))) > 0
    (workspace / prs['response_path']).write_text(json.dumps(drafting.recorded_acceptance_response(prs)))
    calls = []
    monkeypatch.setattr(workflow, 'refresh_protocol_fields', lambda path: calls.append(path) or {'status': 'passed', 'renderer': 'controlled-test-double'})
    result = workflow.generate_only(tmp_path)
    assert result['status'] == 'unreviewed', result
    assert {entry['path'] for entry in result['experimental_outputs']} == {'output/protocol.docx', 'output/icf.docx', 'output/study.xml'}
    assert len(calls) == 1
    assert reference.read_bytes() == approved_bytes
    assert workflow.generate_only(tmp_path) == result
