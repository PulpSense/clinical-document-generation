"""Accepted native concerns preempt unrelated review retries at Desktop boundary."""
import json
import time

import test_repair_with_incomplete_visual as existing
from visual_review import IncompleteVisualReview


def test_accepted_content_concern_preempts_another_parent_attempt(tmp_path, monkeypatch):
    original = existing.operation
    first_set_calls = []

    def intercepted(*args, **kwargs):
        visual = kwargs['visual_review']

        def parent(request, response, revision, fallback):
            if request['review_set'] == 1 and fallback:
                # Wait on public persisted evidence, not thread scheduling or a
                # fabricated accepted finding. The actual content scheduler owns it.
                expires = time.monotonic() + 15
                while time.monotonic() < expires:
                    saved = []
                    for path in (revision / 'hermes/verification-requests').glob('*.verify.content.json'):
                        assignment = json.loads(path.read_text())
                        result = revision / assignment['response_path']
                        if result.is_file():
                            try:
                                saved.extend(json.loads(result.read_text()).get('findings', []))
                            except json.JSONDecodeError:
                                # Controlled dispatch writes the public file in
                                # place; an in-flight write is not completed evidence.
                                continue
                    if any(str(f.get('finding_id', '')).endswith('cover-title') for f in saved):
                        break
                    time.sleep(.01)
                else:
                    raise AssertionError('No authentic substantive content concern was retained')
                first_set_calls.append(request['request_id'])
                raise IncompleteVisualReview('Clean parent retained no additional scope')
            return visual(request, response, revision, fallback)

        kwargs['visual_review'] = parent
        return original(*args, **kwargs)

    monkeypatch.setattr(existing, 'operation', intercepted)
    existing.test_content_defect_reaches_repair_despite_missing_visual_response(
        tmp_path, monkeypatch, ('Retrospective', None), 'initial-missing')
    assert len(first_set_calls) == 1, 'Unrelated missing coverage consumed another parent allocation before native repair'
