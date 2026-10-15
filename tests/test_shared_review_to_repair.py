"""Public Desktop review-to-repair interaction; controlled adapters only."""
import json

import pytest

import test_repair_with_incomplete_visual as existing
from visual_review import IncompleteVisualReview


@pytest.mark.parametrize('family', existing.FAMILIES)
def test_clean_partial_parent_preserves_content_concerns_for_repair(tmp_path, monkeypatch, family):
    original = existing.operation
    calls = []

    def intercepted(*args, **kwargs):
        visual = kwargs['visual_review']

        def partial_parent(request, response, revision, fallback):
            calls.append((request['review_set'], fallback, request['request_id']))
            if request['review_set'] == 1 and fallback:
                raise IncompleteVisualReview('Clean authenticated parent retained incomplete scope')
            return visual(request, response, revision, fallback)

        kwargs['visual_review'] = partial_parent
        return original(*args, **kwargs)

    monkeypatch.setattr(existing, 'operation', intercepted)
    existing.test_content_defect_reaches_repair_despite_missing_visual_response(
        tmp_path, monkeypatch, family, 'initial-missing')
    assert any(review_set == 1 and fallback for review_set, fallback, _ in calls)
    assert any(review_set == 2 for review_set, _, _ in calls)
    state = json.loads((tmp_path / 'logs/desktop-operation.json').read_text())
    assert state['budget_seconds'] == 180
    assert state['deadline_at_epoch'] - state['started_at_epoch'] == 180
