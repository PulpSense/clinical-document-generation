"""The shared planning handoff coordinates prose; assembly remains literal."""
import json
from pathlib import Path

import pytest

import content_plan
import contracts
import drafting
from test_ai_content_plan import plan_response

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('branch,family', [
    ('Prospective', 'Advarra'), ('Prospective', 'Sterling'),
    ('Ambispective', 'Advarra'), ('Ambispective', 'Sterling'),
    ('Retrospective', 'Sterling'),
])
def test_shared_ownership_guidance_reaches_planner_and_every_batch(tmp_path, branch, family):
    source = json.loads((ROOT / f'tests/fixtures/{branch.lower()}-acceptance-source.json').read_text())
    source['meta']['icf_template'] = family
    bundle = contracts.contracted_template_bundle(ROOT, source)
    request = content_plan.request_payload(ROOT, source, bundle, {})
    guidance = request['guidance']['ai-content-plan.md']
    assert 'one owning section per operational concept' in guidance
    assert 'distinct source-grounded policy' in guidance
    assert 'Self-contained consent' in guidance
    assert 'contact cells contain names, roles and contact details' in guidance
    plan = plan_response(request)['plan']
    plan['decisions'] = [{'topic': 'Concept ownership', 'decision': 'Patient Discontinuation owns the withdrawal policy; Confidentiality owns retained data.'}]
    planned = content_plan.with_plan(source, plan)
    (tmp_path / 'generation-only.json').write_text('{}')
    for batch in contracts.batch_plan(branch, family):
        path = drafting.create_drafting_request(
            repo_root=ROOT, revision_dir=tmp_path, revision_id='r-ownership',
            reference=planned, batch=batch, attempts={sid: 1 for sid in batch.section_ids},
            wave='generation-only')
        draft_request = json.loads(path.read_text())
        assert 'Read the shared content_plan decisions' in '\n'.join(draft_request['constraints'])
        assert draft_request['content_plan'] == plan
        assert draft_request['approved_source'] == source
        assert drafting.request_hash_valid(draft_request)
