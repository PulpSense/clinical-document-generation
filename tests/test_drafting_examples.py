"""Worked examples reach authors without becoming approved study evidence."""
import json
import shutil

import pytest

import drafting
import quality
from contracts import batch_plan
from test_clean_delivery import CASES, ROOT


@pytest.mark.parametrize('case', [case for case in CASES if case['descriptor']['profile'].startswith('sparse')],
                         ids=lambda case: case['descriptor']['fixture_id'])
def test_scoped_examples_preserve_actual_source_and_response_contract(tmp_path, case):
    source = quality.branch_acceptance_source(ROOT, case)
    original = json.loads(json.dumps(source))
    batch = batch_plan(source['meta']['study_type'], source['meta'].get('icf_template', 'Advarra'))[0]
    path = drafting.create_drafting_request(
        repo_root=ROOT, revision_dir=tmp_path, revision_id='r-examples', reference=source,
        batch=batch, target_ids=['subjects.population'], attempts={'subjects.population': 1}, wave='initial')
    request = json.loads(path.read_text())

    assert [example['section_id'] for example in request['writing_examples']] == ['subjects.population']
    assert request['approved_source']['population'] == original['population']
    assert source == original
    assert json.loads((tmp_path / 'approved-reference.json').read_text()) == original
    assert request['writing_examples'][0]['source']['population.sample_size'] != source['population']['sample_size']
    accepted, findings = drafting.validate_response(request, drafting.recorded_acceptance_response(request))
    assert accepted and not findings
    request['writing_examples'][0]['prose'] = 'Changed after request authentication.'
    assert not drafting.request_hash_valid(request)


def test_example_edit_changes_authority_and_creates_fresh_request_identity(tmp_path):
    # Copy only mutable prompt resources; templates and implementation are read-only here.
    repo = tmp_path / 'skill'
    repo.mkdir()
    for name in ('assets', 'scripts'):
        (repo / name).symlink_to(ROOT / name, target_is_directory=True)
    (repo / 'references').mkdir()
    for name in ('fixed-clinical-boilerplate.json', 'drafting-examples.json'):
        shutil.copy2(ROOT / 'references' / name, repo / 'references' / name)
    case = next(case for case in CASES if case['descriptor']['study_type'] == 'Retrospective')
    source = quality.branch_acceptance_source(ROOT, case)
    options = dict(repo_root=repo, revision_dir=tmp_path / 'revision', revision_id='r-examples',
                   reference=source, batch=batch_plan('Retrospective')[0],
                   target_ids=['introduction'], attempts={'introduction': 1}, wave='initial')
    first = drafting.create_drafting_request(**options)
    first_request = json.loads(first.read_text())
    library_path = repo / 'references/drafting-examples.json'
    library = json.loads(library_path.read_text())
    library['examples'][0]['prose'] = 'A revised illustrative paragraph.'
    library_path.write_text(json.dumps(library))
    second = drafting.create_drafting_request(**options)
    second_request = json.loads(second.read_text())

    assert first != second
    assert first_request['governing_resources'] != second_request['governing_resources']
    assert first_request['request_sha256'] != second_request['request_sha256']
    assert first_request['writing_examples'] != second_request['writing_examples']
