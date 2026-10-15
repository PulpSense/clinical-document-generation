"""Revision-readable contracted baselines; controlled transport, not clinical credit."""
import json
import pytest
import quality
from rendering import render_documents
from test_clean_delivery import ROOT, CASES, controlled_render
from test_content_review_recovery import FAMILIES


def visual_requests(revision, family):
    case = next(c for c in CASES if c['descriptor']['study_type'] == family[0]
                and (family[1] is None or c['descriptor'].get('icf_template') == family[1]))
    source = quality.branch_acceptance_source(ROOT, case)
    render_documents(ROOT, revision, source, {'protocol': [], 'icf': {}, 'prs': {}})
    report = controlled_render(ROOT, revision)['render']
    paths = quality.create_verification_requests(revision, source, report, bounded_visual_review=True)
    return [(p, json.loads(p.read_text())) for p in paths
            if json.loads(p.read_text())['task'] == 'rendered_page_visual_verification']


@pytest.mark.parametrize('family', FAMILIES)
def test_selected_baselines_are_readable_and_bound_in_parent_and_unit(tmp_path, family):
    from visual_review import create_visual_review_unit
    revision = tmp_path / 'r1'
    for path, parent in visual_requests(revision, family):
        rows = parent.get('template_baseline_evidence')
        assert rows, 'Visual request lacks revision-readable contracted baselines'
        artifacts = {a['artifact'] for a in parent['artifacts']}
        assert {r['artifact'] for r in rows} == artifacts
        assert {r['role'] for r in rows} == {'contracted_template', 'client_template_authority'}
        for row in rows:
            expected = parent['contracted_template_bundle']['layout_preservation_baseline']['artifacts'][row['artifact']][row['role']]
            assert row['package_path'] == expected['path']
            assert row['sha256'] == expected['sha256']
            evidence = revision / row['path']
            assert evidence.is_file() and not evidence.is_symlink()
            assert quality.sha256_file(evidence) == row['sha256']
        target = next(t for t in parent['visual_review_plan']['targets'] if t['kind'] == 'page')
        unit_path = create_visual_review_unit(revision, path, [target], 1)
        unit = json.loads(unit_path.read_text())
        assert unit['template_baseline_evidence'] == rows


def test_changed_baseline_blocks_visual_dispatch(tmp_path):
    from visual_review import create_visual_review_unit
    revision = tmp_path / 'r1'
    path, parent = visual_requests(revision, ('Retrospective', None))[0]
    row = parent['template_baseline_evidence'][0]
    (revision / row['path']).write_bytes(b'changed baseline')
    target = next(t for t in parent['visual_review_plan']['targets'] if t['kind'] == 'page')
    with pytest.raises(ValueError, match='baseline'):
        create_visual_review_unit(revision, path, [target], 1)


def test_unit_cannot_drop_bound_parent_baselines(tmp_path):
    from visual_review import create_visual_review_unit, validate_visual_review_unit_request
    revision = tmp_path / 'r1'
    path, parent = visual_requests(revision, ('Retrospective', None))[0]
    target = next(t for t in parent['visual_review_plan']['targets'] if t['kind'] == 'page')
    unit_path = create_visual_review_unit(revision, path, [target], 1)
    unit = json.loads(unit_path.read_text())
    unit['template_baseline_evidence'] = []
    unit['request_sha256'] = quality.verification_request_sha256(unit)
    unit_path.write_text(json.dumps(unit))
    ledger_path = revision / f"hermes/visual-review-ledgers/{unit['request_id']}.json"
    ledger = json.loads(ledger_path.read_text())
    ledger.update(request_sha256=unit['request_sha256'], request_file_sha256=quality.sha256_file(unit_path))
    ledger_path.write_text(json.dumps(ledger))
    with pytest.raises(ValueError, match='baseline'):
        validate_visual_review_unit_request(revision, unit_path)
