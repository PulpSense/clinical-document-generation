"""Prompt handoffs and retained local writing trials; no document generation."""
import copy
import json
import re
from pathlib import Path

import pytest

import drafting
from contracts import batch_plan

ROOT = Path(__file__).resolve().parents[1]
TRIALS = json.loads((ROOT / 'docs/experiments/citations-form-trials/trials.json').read_text())
SOURCES = {
    'puresee': 'docs/experiments/puresee-local-trial/source.json',
    'near': 'tests/fixtures/prospective-acceptance-source.json',
    'caps': 'docs/experiments/retrospective-method-trials/caps.source.json',
}


@pytest.mark.parametrize('branch,family', [
    ('Prospective', 'Advarra'), ('Prospective', 'Sterling'),
    ('Ambispective', 'Advarra'), ('Ambispective', 'Sterling'),
    ('Retrospective', 'Sterling'),
])
def test_editorial_ownership_reaches_each_active_drafting_batch(branch, family, tmp_path):
    source = json.loads((ROOT / SOURCES['puresee' if branch != 'Retrospective' else 'caps']).read_text())
    source['meta'].update(study_type=branch, icf_template=family)
    original = copy.deepcopy(source)
    (tmp_path / 'generation-only.json').write_text('{}')
    for batch in batch_plan(branch, family):
        path = drafting.create_drafting_request(
            repo_root=ROOT, revision_dir=tmp_path, revision_id='r-editorial',
            reference=source, batch=batch, attempts={target: 1 for target in batch.section_ids},
            wave='generation-only')
        request = json.loads(path.read_text())
        constraints = '\n'.join(request['constraints'])
        assert 'assembler owns the single final Protocol REFERENCES section' in constraints
        assert 'citation numbers beside the claims they support' in constraints
        assert 'official form name' in constraints
        assert 'ambiguous trailing numeral' in constraints
        assert 'without renaming source-owned table labels' in constraints
        assert request['prompt_version'] == drafting.PROMPT_VERSION
        assert request['generation_only_prompts']['profile'] == 'n8n-with-brad-corrections/v1'
        assert drafting.request_hash_valid(request)
    assert source == original
    assert json.loads((tmp_path / 'approved-reference.json').read_text()) == original


def _texts(trial):
    response = trial['response']
    if 'narrative' in response:
        return '\n'.join(value['text'] for value in response['narrative'].values())
    return '\n'.join(p['text'] for section in response['section_results'] for p in section['paragraphs'])


def test_past_input_introductions_keep_citations_without_embedded_bibliographies():
    intros = [t for t in TRIALS['trials'] if t['targets'] == ['introduction']]
    assert {t['case'] for t in intros} == {'puresee', 'near', 'comfort', 'break', 'glide', 'record', 'caps'}
    assert {t['study_type'] for t in intros} == {'Prospective', 'Ambispective', 'Retrospective'}
    for trial in intros:
        text = _texts(trial)
        assert not re.search(r'(?im)^\s*references?\b|doi:|https?://', text)
        if trial['case'] == 'puresee':
            assert '[1,2]' in text and '[3]' in text
            assert 'dominant eye' in text and 'non-dominant eye' in text
        else:
            assert not re.search(r'\[\d', text)
    assert all(r['transport_passed'] and not r['findings'] for r in TRIALS['receipts'])


def test_source_form_instruction_is_natural_across_protocol_icf_and_prs():
    trials = [t for t in TRIALS['trials'] if t['case'] == 'puresee' and t['targets'] != ['introduction']]
    assert len(trials) == 3
    for trial in trials:
        text = _texts(trial)
        assert 'complete the Exit Form1' in text
        assert not re.search(r'complete\s+Complete|called Complete Exit', text, re.I)
        assert '66' in text and '40' in text and '+1.0 D' in text and '-2.50 D' in text
        assert 'AIOLIS' in text


def test_explicit_official_form_title_and_identifier_are_preserved():
    official = next(t for t in TRIALS['trials'] if t['case'] == 'official-title')
    instruction = next(t for t in TRIALS['trials'] if t['case'] == 'instruction')
    assert 'form titled Complete Exit Form (EF-12)' in _texts(official)
    assert _texts(instruction) == 'Complete the Exit Form at the final visit.'
