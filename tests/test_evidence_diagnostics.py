"""Shared diagnostics must explain a failed check without erasing supplied facts."""
import pytest
import drafting


@pytest.mark.parametrize('value,text', [(0, 'zero'), (0.0, '0.0'), ('0 mg', 'zero mg')])
def test_zero_remains_material_and_accepts_equivalent_numbers(value, text):
    assert drafting.evidence_grounded(text, value)
    assert not drafting.evidence_grounded('unrelated prose', value)


def test_missing_quantity_diagnostic_identifies_the_source_value():
    detail = drafting.source_evidence_diagnostics('Blood sample at Week 2.', 'procedures.assessments', ['Blood sample at 5 mL'])
    assert detail['passed'] is False
    assert detail['source_path'] == 'procedures.assessments'
    assert detail['unobserved_values'][0]['source_excerpt'] == 'Blood sample at 5 mL'
    assert detail['unobserved_values'][0]['missing_numbers'] == ['5']


def test_hypothesis_diagnostic_does_not_claim_lexical_failure():
    detail = drafting.source_evidence_diagnostics('The researchers compare outcomes.', 'study.hypothesis', 'Outcomes may differ between two groups.')
    assert detail['passed'] is True
    assert detail['validation_mode'] == 'independent_content_review'
    assert detail['release_acceptance'] is False


def test_all_items_reports_the_missing_item_only():
    detail = drafting.source_evidence_diagnostics('Blood draw at 5 mL', 'procedures.assessments', ['Blood draw at 5 mL', 'Vision measured at 66 cm'], all_items=True)
    assert detail['passed'] is False
    assert len(detail['unobserved_values']) == 1
    assert detail['unobserved_values'][0]['missing_numbers'] == ['66']


def test_public_drafting_rejection_carries_concrete_retry_diagnostics():
    import copy
    import json
    from pathlib import Path
    cases = json.loads((Path(__file__).parent / 'fixtures/reliability-replays/matrix-visits-block.json').read_text())
    case = copy.deepcopy(cases[-1])
    for paragraph in case['response']['section_results'][0]['paragraphs']:
        paragraph['text'] = paragraph['text'].replace('66 cm', 'far away')
    accepted, findings = drafting.validate_response(case['request'], case['response'])
    assert not accepted['drafts']
    details = [detail for item in findings for detail in item.get('evidence_diagnostics', [])]
    assert any('66' in value.get('missing_numbers', []) for detail in details for value in detail['unobserved_values'])


def test_rendered_rejection_carries_the_same_missing_quantity():
    import json
    from pathlib import Path
    from docx import Document
    import quality
    fixture = Path(__file__).parent / 'fixtures/reliability-replays/sterling-rendered-scope'
    doc = Document(fixture / 'candidate-3.docx')
    for paragraph in doc.paragraphs:
        paragraph.text = paragraph.text.replace('66 cm', 'far away')
    findings = quality.validate_sterling_clause_contract(doc, json.loads((fixture / 'source.json').read_text()))['findings']
    details = [detail for item in findings for detail in item.get('evidence_diagnostics', [])]
    assert any('66' in value.get('missing_numbers', []) for detail in details for value in detail['unobserved_values'])


def test_explicit_false_is_a_negative_answer_not_missing_evidence():
    assert drafting.evidence_grounded('No unscheduled visits are planned.', False)
    assert not drafting.evidence_grounded('Unscheduled visits are planned.', False)


def test_explicit_true_remains_a_positive_answer():
    assert drafting.evidence_grounded('Yes, unscheduled visits are planned.', True)
    assert not drafting.evidence_grounded('No unscheduled visits are planned.', True)
