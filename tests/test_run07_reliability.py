"""Run 07 regressions: visible Sterling headings and section-owned source facts."""

from contracts import batch_plan, icf_contract, protocol_contract


def _section(sections, section_id):
    return next(section for section in sections if section.section_id == section_id)


def test_bias_draft_receives_approved_operational_controls():
    section = _section(protocol_contract('Prospective'), 'study-design.bias')
    assert 'statistics.bias_minimization' in section.evidence
    batch = next(item for item in batch_plan('Prospective') if item.batch_id == 'protocol-foundations')
    assert 'statistics' in batch.field_families
    assert 'supplied' in ' '.join(section.content_expectations).lower()


def test_icf_procedures_receives_continuous_safety_reporting_fact():
    for template in ('Sterling', 'Advarra'):
        section = _section(icf_contract('Prospective', template), 'icf.procedures')
        assert 'procedures.adverse_events' in section.evidence
        expectations = ' '.join(section.content_expectations).lower()
        assert 'between scheduled visits' in expectations


def test_optional_bias_and_event_reporting_are_not_invented_when_absent():
    import json
    from pathlib import Path
    import drafting
    root = Path(__file__).resolve().parents[1]
    source = json.loads((root / 'tests/fixtures/prospective-acceptance-source.json').read_text())
    for batch_id, target, optional_path in (
        ('protocol-foundations', 'study-design.bias', 'statistics.bias_minimization'),
        ('icf-narrative', 'icf.procedures', 'procedures.adverse_events'),
    ):
        batch = next(item for item in batch_plan('Prospective', source['meta']['icf_template'])
                     if item.batch_id == batch_id)
        payload = drafting._expected_section_contracts(root, source, batch, [target])[0]
        assert optional_path not in payload['minimum_evidence']


def test_draft_requests_expose_each_supplied_fact_to_its_section(tmp_path):
    import json
    from pathlib import Path
    import drafting
    root = Path(__file__).resolve().parents[1]
    source = json.loads((root / 'tests/fixtures/prospective-acceptance-source.json').read_text())
    source['statistics']['bias_minimization'] = (
        'Use common testing conditions and predefine the outcomes before results are reviewed.'
    )
    source['procedures']['adverse_events'] = (
        'Collect health and device problems from consent through final contact; '
        'participants may report them between scheduled visits.'
    )
    for index, (batch_id, target, path) in enumerate((
        ('protocol-foundations', 'study-design.bias', 'statistics.bias_minimization'),
        ('icf-narrative', 'icf.procedures', 'procedures.adverse_events'),
    )):
        batch = next(item for item in batch_plan('Prospective', source['meta']['icf_template'])
                     if item.batch_id == batch_id)
        request_path = drafting.create_drafting_request(
            repo_root=root, revision_dir=tmp_path, revision_id='r-run07-contract',
            reference=source, batch=batch, target_ids=[target],
            attempts={target: 1}, wave=f'probe-{index}',
        )
        request = json.loads(request_path.read_text())
        assert path in request['evidence_checklist'][0]['required_source_paths']
        assert request['evidence_checklist'][0]['approved_values'][path]
        assert any(item['path'] == path and item['value'] == request['evidence_checklist'][0]['approved_values'][path]
                   for item in request['approved_input'])


def test_icf_event_evidence_does_not_force_duplicate_scheduled_months():
    from drafting import section_evidence_value, source_evidence_diagnostics
    source = (
        'Adverse events and device deficiencies will be collected from consent through the final study contact. '
        'Scheduled review at Months 1, 3, and 6 is not the only time an event may be reported.'
    )
    patient_text = (
        'The study team will collect health problems (adverse events) and problems with the implanted '
        'lenses (device deficiencies) from consent through the final study contact. '
        'You may report problems between scheduled visits.'
    )
    scoped = section_evidence_value('icf.procedures', 'procedures.adverse_events', source)
    assert '1, 3, and 6' not in scoped
    assert source_evidence_diagnostics(patient_text, 'procedures.adverse_events', scoped)['passed']
