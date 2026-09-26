"""Successful server run is a regression baseline for targeted polish."""
import copy
import json
from pathlib import Path
import pytest
import drafting

FIXTURE = Path(__file__).parent / 'fixtures/reliability-replays/run26-success.json'
DATA = json.loads(FIXTURE.read_text())


def replay(case):
    request = copy.deepcopy(DATA['requests'][case['request_id']])
    response = copy.deepcopy(case['response'])
    request['section_contracts'] = [s for s in request['section_contracts'] if s['section_id'] == case['section_id']]
    response['section_results'] = [s for s in response['section_results'] if s['section_id'] == case['section_id']]
    return request, response


@pytest.mark.parametrize('case', [c for c in DATA['cases'] if not c.get('previously_rejected')], ids=lambda c:c['section_id'])
def test_successful_run_accepted_prose_remains_accepted(case):
    request, response = replay(case)
    accepted, findings = drafting.validate_response(request, response)
    assert not findings
    assert accepted['drafts']


def case_for(section):
    return next(c for c in DATA['cases'] if c['section_id']==section and c.get('previously_rejected'))


def test_accurate_patient_compensation_negation_passes_without_duplicate_source_sentence():
    request, response = replay(case_for('icf.payment'))
    assert not drafting.validate_response(request, response)[1]


@pytest.mark.parametrize('text', ['You will receive compensation and reimbursement for taking part.', 'You will not receive compensation for taking part.'])
def test_missing_or_reversed_compensation_fact_still_fails(text):
    request, response = replay(case_for('icf.payment'))
    response['section_results'][0]['paragraphs'][0]['text'] = text
    assert drafting.validate_response(request, response)[1]


def test_complete_visit_narrative_can_cite_the_schedule_without_duplicate_label_reference():
    request, response = replay(case_for('study-procedure.visits'))
    assert not drafting.validate_response(request, response)[1]


def test_visit_alias_coverage_does_not_hide_missing_postoperative_time():
    request, response = replay(case_for('study-procedure.visits'))
    response['section_results'][0]['paragraphs'].pop()
    assert drafting.validate_response(request, response)[1]


def test_worker_redispatch_preserves_each_attempt_log(tmp_path):
    import workflow
    first_out, first_err = workflow._open_production_worker_logs(tmp_path, 'review-content')
    first_out.write('first reviewer exited without a response')
    first_out.close(); first_err.close()
    second_out, second_err = workflow._open_production_worker_logs(tmp_path, 'review-content')
    second_out.write('second reviewer returned a response')
    second_out.close(); second_err.close()
    assert Path(first_out.name).read_text() == 'first reviewer exited without a response'
    assert first_out.name != second_out.name
    assert first_err.name != second_err.name


def test_new_icf_duration_contract_requires_timing_without_requiring_enrollment_repetition():
    import contracts
    duration = next(s for s in contracts.icf_contract('Prospective', 'Sterling') if s.section_id=='icf.duration')
    assert 'study.timeline' in duration.evidence
    assert 'population.sample_size' not in duration.evidence


def test_method_request_scopes_out_interpretation_owned_by_considerations():
    case = next(c for c in DATA['cases'] if c['section_id']=='analysis-plan.methodology' and not c.get('previously_rejected'))
    request, _ = replay(case)
    source = request['approved_source']
    import contracts
    section = next(s for s in contracts.protocol_contract('Prospective') if s.section_id=='analysis-plan.methodology')
    contract = drafting._section_payload(section, {}, source)
    scoped = next(x['value'] for x in contract['evidence_scopes'] if x['path']=='statistics.analysis_plan')
    assert 'No inferential hypothesis test' not in scoped
    assert 'standard deviation' in scoped


def test_sterling_defect_is_repaired_before_independent_review_requests(tmp_path):
    from docx import Document
    import workflow
    revision = tmp_path / 'revision'
    candidate = revision / 'candidate'
    candidate.mkdir(parents=True)
    document = Document(FIXTURE.parent / 'successful-run-documents/icf.docx')
    for p in document.paragraphs:
        if p.text.startswith("The purpose is to evaluate vision"):
            p.text = 'The purpose is to evaluate vision and patients experiences.'
    document.save(candidate / 'icf.docx')
    source = DATA['reference']
    pending, findings = workflow._begin_independent_review(revision, source, {}, {}, 1)
    assert not pending
    assert any(f.get('clause_id')=='sterling.purpose.study-purpose' for f in findings)
    assert not (revision / 'hermes/verification-requests').exists()


def test_successful_icf_has_no_new_pre_review_rejections():
    import quality
    source = DATA['reference']
    report = quality.validate_sterling_clause_contract(FIXTURE.parent/'successful-run-documents/icf.docx', source)
    assert not report['findings']
