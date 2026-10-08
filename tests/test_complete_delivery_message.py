"""Hermes message expresses exact publication and review status without clinical edits."""
import workflow
import pytest
from test_desktop_delivery import _manifest


def test_prepared_message_distinguishes_editorial_and_review_resolved_cautions():
    manifest = _manifest()
    manifest['delivery_warnings'] = [
        {'issue': 'A sentence repeats.', 'document_locations': ['Protocol §10.3 — General Statistical Considerations']},
        {'issue': 'Lexical overlap was insufficient.', 'resolution': 'independent_content_review_passed',
         'verification_request_id': 'final-content', 'document_locations': ['ICF §PURPOSE']},
    ]
    reply = workflow.desktop_attachment_reply(manifest)
    assert reply['delivery_status'] == 'prepared_unconfirmed'
    assert 'Delivery confirmation pending' in reply['message']
    assert 'Editorial warning — Protocol §10.3' in reply['message']
    assert 'Reviewer-resolved wording uncertainty — ICF §PURPOSE' in reply['message']
    assert 'Lexical overlap was insufficient' not in reply['message']
    assert reply['cautions'] == manifest['delivery_warnings']


@pytest.mark.parametrize("classification,owner", [("essential_defect", "drafting"),
    ("technical_failure", "integrity"), ("semantic_uncertainty", "independent_review")])
def test_explicit_unresolved_policy_cannot_publish_under_a_warning_label(tmp_path, monkeypatch, classification, owner):
    import json
    import pytest
    import quality
    from test_atomic_delivery import _publish_fixture, _passing_quality
    # Publication sentinels supplement the real all-family Desktop acceptance.
    monkeypatch.setattr(quality, 'deterministic_content_check', lambda *_args: [])
    run, revision, source = _publish_fixture(tmp_path)
    accepted = revision / 'hermes/accepted'
    accepted.mkdir(parents=True)
    (accepted / 'draft.json').write_text(json.dumps({'warnings': [{
        'issue': 'Required clinical statement is absent.',
        'publication_disposition': 'warning',
        'finding_policy': {'classification': classification, 'reason': 'unresolved required evidence',
                           'repair_owner': owner},
    }]}))
    report = _passing_quality(revision, source)
    with pytest.raises(RuntimeError, match='final verification is incomplete'):
        workflow._publish(run, revision, source, report)
    assert (run / 'output/protocol.docx').read_bytes() == b'old protocol'


def test_explicit_editorial_policy_survives_without_legacy_warning_label(tmp_path, monkeypatch):
    import json
    import quality
    from test_atomic_delivery import _publish_fixture, _passing_quality
    monkeypatch.setattr(quality, 'deterministic_content_check', lambda *_args: [])
    run, revision, source = _publish_fixture(tmp_path)
    _passing_quality(revision, source)
    build = json.loads((revision / 'candidate-build.json').read_text())
    build['render_report']['findings'] = [{
        'issue': 'A sentence repeats.', 'artifact': 'protocol', 'page': 1,
        'finding_policy': {'classification': 'editorial_warning', 'reason': 'harmless repetition', 'repair_owner': 'none'},
    }]
    (revision / 'candidate-build.json').write_text(json.dumps(build))
    report = quality.quality_report(revision, source, build['render_report'], None)
    assert report['status'] == 'passed'
    assert report['warnings'][0]['issue'] == 'A sentence repeats.'
    result = workflow._publish(run, revision, source, report)
    assert result['warnings'][0]['issue'] == 'A sentence repeats.'
    assert 'Editorial warning — Protocol p.1' in result['desktop_reply']['message']


def test_missing_new_document_preserves_the_previous_complete_set(tmp_path, monkeypatch):
    import quality
    import pytest
    from test_atomic_delivery import _publish_fixture, _passing_quality
    monkeypatch.setattr(quality, 'deterministic_content_check', lambda *_args: [])
    run, revision, source = _publish_fixture(tmp_path)
    report = _passing_quality(revision, source)
    workflow._publish(run, revision, source, report)
    before = {p.name: p.read_bytes() for p in (run / 'output').iterdir()}
    assert sorted(before) == ['icf.docx', 'protocol.docx', 'study.xml']
    (revision / 'candidate/icf.docx').unlink()
    with pytest.raises(RuntimeError, match='stale publication evidence'):
        workflow._publish(run, revision, source, report)
    assert {p.name: p.read_bytes() for p in (run / 'output').iterdir()} == before


def test_interrupted_output_swap_restores_the_previous_complete_set(tmp_path, monkeypatch):
    import quality
    import pytest
    from test_atomic_delivery import _publish_fixture, _passing_quality
    monkeypatch.setattr(quality, 'deterministic_content_check', lambda *_args: [])
    run, revision, source = _publish_fixture(tmp_path)
    report = _passing_quality(revision, source)
    workflow._publish(run, revision, source, report)
    before = {p.name: p.read_bytes() for p in (run / 'output').iterdir()}
    replace = workflow.os.replace

    def interrupted(source_path, target_path):
        if '.output-staging-' in str(source_path):
            raise OSError('interrupted atomic publication')
        return replace(source_path, target_path)

    monkeypatch.setattr(workflow.os, 'replace', interrupted)
    with pytest.raises(OSError, match='interrupted atomic publication'):
        workflow._publish(run, revision, source, report)
    assert {p.name: p.read_bytes() for p in (run / 'output').iterdir()} == before
    assert not list(run.glob('.output-staging-*'))
