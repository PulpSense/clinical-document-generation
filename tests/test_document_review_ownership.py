"""Shared document-scope review transport, deterministic adapters, no live judgments."""
import json

import pytest

from test_visual_units import FAMILIES, parent_fixture, response_for
from visual_review import run_visual_review


@pytest.mark.parametrize('family', FAMILIES)
def test_whole_document_native_concern_survives_nonanchor_location(tmp_path, family):
    revision, parent_path, parent = parent_fixture(tmp_path, family, count=5)
    observed = []

    def dispatch(handoffs, budget):
        assert 0 < budget <= 240
        for handoff in handoffs:
            unit = json.loads((revision / handoff['request_path']).read_text())
            response = response_for(unit)
            for target in unit['visual_scope']:
                if target['kind'] != 'document':
                    continue
                anchors = {p['page'] for p in target['pages']}
                location = next(p['page'] for p in parent['artifacts'][0]['pages']
                    if p['page'] not in anchors)
                observed.append((location, anchors))
                response['visual_assessments'][0]['status'] = 'blocked'
                response['findings'] = [{
                    'finding_id': 'native-template-language-loss',
                    'target_id': target['target_id'], 'artifact': target['artifact'],
                    'page': location, 'check': 'template_preservation',
                    'evidence_basis': 'native',
                    'element': 'Fixed authorization provisions',
                    'issue': 'Native clauses present in the assigned template were removed.',
                    'recommended_action': 'Restore applicable fixed clauses without altering approved facts.'}]
            path = revision / unit['response_path']
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(response))

    result = run_visual_review(revision, parent_path, dispatch, 240)
    assert observed and all(page not in anchors for page, anchors in observed)
    assert any(f['finding_id'] == 'native-template-language-loss' for f in result['findings'])
    assert next(r for r in result['assessments'] if r['kind'] == 'document')['status'] == 'blocked'
    assert result['complete']  # Complete assessment coverage is not approval.
    published = json.loads((revision / parent['response_path']).read_text())
    assert published['status'] == 'blocked'
