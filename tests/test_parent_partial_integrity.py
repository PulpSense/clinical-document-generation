"""A recoverable primary transport cannot hide a failed post-execution guard."""
import json

import pytest

import test_repair_with_incomplete_visual as existing
import workflow
from visual_review import IncompleteVisualReview
from test_visual_units import parent_fixture


def test_parent_partial_with_integrity_stop_cannot_enter_native_repair(tmp_path, monkeypatch):
    original = existing.operation
    observed = {}

    def intercepted(*args, **kwargs):
        visual, repair = kwargs['visual_review'], kwargs['repair']
        repairs = []
        def guarded(request, response, revision, fallback):
            if request['review_set'] == 1 and fallback:
                failure = IncompleteVisualReview('Clean primary incomplete response')
                failure.worker_integrity_failure = {'issue': 'Controlled post-callback runtime changed'}
                raise failure
            return visual(request, response, revision, fallback)
        def track(request, revision):
            repairs.append(request['request_id'])
            return repair(request, revision)
        kwargs.update(visual_review=guarded, repair=track)
        result = original(*args, **kwargs)
        observed.update(result=result[0], repairs=repairs)
        return result

    monkeypatch.setattr(existing, 'operation', intercepted)
    try:
        existing.test_content_defect_reaches_repair_despite_missing_visual_response(
            tmp_path, monkeypatch, ('Retrospective', None), 'initial-missing')
    except AssertionError:
        if not observed:
            raise
    assert observed['repairs'] == []
    assert observed['result']['stage'] == 'parent_visual_integrity'
    assert observed['result']['status'] != 'passed'


def test_public_production_fallback_preserves_post_guard_as_machine_stop(tmp_path, monkeypatch):
    run = tmp_path / 'run'
    revision, path, parent = parent_fixture(run, 'retrospective')
    reference = run / workflow.REFERENCE
    reference.parent.mkdir(parents=True)
    reference.write_text(json.dumps({'approval': {'revision_id': 'r1'}}))
    root = tmp_path / 'skill'
    root.mkdir()
    def reject_installed_launcher_lookup():
        pytest.fail('Synthetic fallback fixture must not discover installed Hermes')
    monkeypatch.setattr(workflow, '_managed_hermes_pair', reject_installed_launcher_lookup)
    identity = {'kind': 'synthetic-managed-hermes-identity',
                'fixture': 'production-fallback-post-guard/v1'}
    monkeypatch.setattr(workflow, '_managed_hermes_identity', lambda: dict(identity))
    intact = [True]
    monkeypatch.setattr(workflow, '_pdfium_runtime_integrity', lambda *a, **k:
        {'status': 'passed' if intact[0] else 'blocked'})
    monkeypatch.setattr(workflow, '_installed_release_identity', lambda *a:
        {'package_fingerprint': 'fixture', 'git_commit': 'fixture'})
    monkeypatch.setattr(workflow, '_production_worker_readiness', lambda *a, **k: {'status': 'passed'})
    def callback(*_args):
        intact[0] = False
        raise IncompleteVisualReview('Preserved primary partial response')
    handoff = {'task': parent['task'], 'request_path': path.relative_to(revision).as_posix(),
        'response_path': parent['response_path']}
    def operation(_run, **options):
        options['fallback_handoff_runner']([handoff], 20)
    monkeypatch.setattr(workflow, 'run_desktop_operation', operation)
    with pytest.raises(IncompleteVisualReview) as caught:
        workflow.run_production_desktop_operation(run, skill_root=root,
            opener=lambda _: b'unused', parent_visual_reviewer=callback)
    assert caught.value.worker_integrity_failure['boundary'] == 'post_parent_callback_renderer_or_package'
