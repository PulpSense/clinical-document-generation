"""Drafting handoffs route detail to sections present in the selected template."""
import json
from pathlib import Path

import pytest
import contracts
import drafting

ROOT = Path(__file__).resolve().parents[1]


def request(tmp_path, branch='Retrospective', batch_id='protocol-operations'):
    ref = json.loads((ROOT / 'tests/fixtures/release-certification/retrospective/approved-reference.json').read_text())
    ref['meta'].update(study_type=branch, icf_template='Advarra')
    ref['procedures'].update(methods='Select the closest score; ties use the earlier date.',
        assessment_details={'counting': 'A refill is not a care change.'},
        staff_work_plan='Abstraction ends in March.', completion='Finish after query resolution.',
        study_termination='Suspend access if permission is withdrawn; resume only after authorization.')
    ref['study']['completion'] = 'Complete planned analyses before administrative archiving.'
    batch = next(b for b in contracts.batch_plan(branch, 'Advarra') if b.batch_id == batch_id)
    path = drafting.create_drafting_request(repo_root=ROOT, revision_dir=tmp_path,
        revision_id='local-method-test', reference=ref, batch=batch,
        attempts={s: 1 for s in batch.section_ids}, wave='draft')
    return json.loads(path.read_text()), ref


def test_retrospective_active_procedure_section_receives_all_supplied_method_and_closeout_evidence(tmp_path):
    handoff, ref = request(tmp_path)
    section = next(s for s in handoff['section_contracts'] if s['section_id'] == 'study-procedure.enrollment')
    required = {'procedures.methods', 'procedures.assessment_details', 'procedures.staff_work_plan',
                'procedures.completion', 'study.completion', 'procedures.study_termination'}
    assert required <= set(section['minimum_evidence'])
    values = next(s['approved_values'] for s in handoff['evidence_checklist'] if s['section_id'] == section['section_id'])
    assert values['procedures.methods'] == ref['procedures']['methods']
    assert values['procedures.assessment_details'] == {'counting': 'A refill is not a care change.'}
    assert values['procedures.study_termination'] == ref['procedures']['study_termination']


@pytest.mark.parametrize('branch,method_owner,completion_owner', [
    ('Retrospective', 'study-procedure.enrollment', 'study-procedure.enrollment'),
    ('Prospective', 'study-procedure.measurements', 'endpoint-criteria.study-completion'),
    ('Ambispective', 'study-procedure.measurements', 'endpoint-criteria.study-completion'),
])
@pytest.mark.parametrize('batch_id', ['protocol-foundations', 'protocol-operations', 'protocol-analysis-and-oversight'])
def test_every_protocol_batch_gets_actual_headings_and_branch_owners(tmp_path, branch, method_owner, completion_owner, batch_id):
    handoff, _ = request(tmp_path, branch, batch_id)
    plan = handoff['protocol_writing_plan']
    headings = {s['section_id']: s for s in plan['sections']}
    assert plan['methods_owner'] == method_owner
    assert plan['completion_owner'] == completion_owner
    assert method_owner in headings and completion_owner in headings
    if branch == 'Retrospective':
        assert headings[method_owner] == {'section_id': 'study-procedure.enrollment', 'number': '8.1.', 'title': 'Informed Consent / Subject Enrollment'}
        assert 'study-procedure.measurements' not in headings
        assert 'evaluation-procedures' not in headings
        assert plan['assessment_table_owner'] is None
    else:
        assert headings[method_owner]['title'] == 'Study Methods and Measurements'
        assert plan['assessment_table_owner'] == 'evaluation-procedures'
