"""Independent specification controls; synthetic reviewers/render, no clinical credit."""
import json
from pathlib import Path
import pytest
import workflow
import quality
import test_repair_with_incomplete_visual as existing

FAMILY = ('Retrospective', None)

@pytest.mark.parametrize('fault', ['runtime-parent', 'cleanup-parent-generic', 'cleanup-delegated', 'source-clarification'])
def test_fatal_visual_fault_must_not_reach_native_repair(tmp_path, monkeypatch, fault):
    original = existing.operation
    observed = {}
    def intercepted(*args, **kwargs):
        visual = kwargs['visual_review']
        repair = kwargs['repair']
        repairs = []
        def visual_fault(request, response, revision, fallback):
            if request['review_set'] == 1:
                if fault == 'runtime-parent' and fallback:
                    raise RuntimeError('Provisioned renderer runtime changed during worker dispatch; reject this worker result')
                if fault == 'cleanup-parent-generic' and fallback:
                    raise RuntimeError('Production worker process or resources could not be fully released.')
                if fault == 'cleanup-delegated' and not fallback:
                    from owned_observer_runtime import OwnedObserverLifetimeUnresolved
                    raise OwnedObserverLifetimeUnresolved('Independent control: delegated descendants unresolved')
            return visual(request, response, revision, fallback)
        def track_repair(request, revision):
            repairs.append(request['request_id'])
            return repair(request, revision)
        if fault == 'source-clarification':
            args = list(args)
            for index in (3, 4):
                worker = args[index]
                def source_review(request, response, revision, *extra, _worker=worker):
                    response = _worker(request, response, revision, *extra)
                    for finding in response.get('findings', []):
                        finding.update(source_clarification_required=True, disposition='source_clarification')
                    return response
                args[index] = source_review
        kwargs.update(visual_review=visual_fault, repair=track_repair)
        result = original(*args, **kwargs)
        observed.update(result=result[0], repairs=repairs)
        import os
        label = os.environ.get('SPEC_OBSERVATION_PREFIX', '')
        (tmp_path / (label + fault + '-observation.json')).write_text(json.dumps(observed, indent=2, default=str))
        return result
    monkeypatch.setattr(existing, 'operation', intercepted)
    try:
        existing.test_content_defect_reaches_repair_despite_missing_visual_response(tmp_path, monkeypatch, FAMILY, 'initial-missing')
    except AssertionError:
        # Its happy-path assertions are inapplicable when an injected stop is honored.
        if not observed:
            raise
    assert not observed['repairs'], 'Fatal integrity/cleanup/source fault was demoted to missing visual coverage and native repair ran'
    assert observed['result']['status'] != 'passed', 'Fatal integrity/cleanup fault was cleared'
