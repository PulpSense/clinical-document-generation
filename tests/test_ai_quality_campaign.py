import ai_quality_campaign as campaign


def test_fixed_plan_has_clean_sparse_and_actual_repair_rich_for_each_family():
    plan = campaign.plan()
    assert len(plan['cases']) == 10
    assert len({row['family'] for row in plan['cases']}) == 5
    for family in {row['family'] for row in plan['cases']}:
        pair = [row for row in plan['cases'] if row['family'] == family]
        assert {row['scenario'] for row in pair} == {'clean', 'deliberate_prose_repair'}
        assert all(row['source_sha256'] and row['source'] for row in pair)


def test_timing_denominators_include_failures_and_separate_disputes():
    rows = [dict(operation_id='a', status='passed', elapsed_seconds=1200, changed_native_repairs=0, dispute_cycles=0, delivery_confirmed=True),
            dict(operation_id='b', status='failed', elapsed_seconds=20, changed_native_repairs=0, dispute_cycles=0),
            dict(operation_id='c', status='passed', elapsed_seconds=1510, changed_native_repairs=1, dispute_cycles=2, delivery_confirmed=True),
            dict(operation_id='d', status='passed', elapsed_seconds=100, changed_native_repairs=0, dispute_cycles=1, delivery_confirmed=True)]
    report = campaign.summarize(rows)
    assert report['operations'] == 4
    assert report['groups']['clean']['denominator'] == 2
    assert report['groups']['clean']['client_ready_under_25_minutes'] == 1
    assert report['groups']['clean']['proportion'] == 0.5
    assert report['groups']['changed_native_repairs']['denominator'] == 1
    assert report['groups']['changed_native_repairs']['client_ready_under_25_minutes'] == 0
    assert report['groups']['dispute_only']['denominator'] == 1


def test_report_rejects_duplicate_operation_ids_instead_of_double_counting_resumes():
    import pytest
    with pytest.raises(ValueError, match='Duplicate operation'):
        campaign.summarize([{'operation_id': 'same'}, {'operation_id': 'same'}])


def test_readiness_plan_preserves_all_twenty_baselines_and_eight_supplements():
    manifest = campaign.readiness_plan({'commit': 'controlled-candidate'})
    assert len(manifest['baseline_operations']) == 20
    assert len(manifest['supplemental_operations']) == 8
    assert len({p['planned_operation_id'] for p in manifest['baseline_operations']}) == 20
    assert {p['case_id'] for p in manifest['supplemental_operations']} == {'Q1', 'Q2', 'Q3', 'Q4', 'F1', 'F2', 'F3', 'D1'}
    empty = campaign.summarize_readiness(manifest, [])
    assert empty['readiness'] == 'incomplete'
    assert empty['planned_groups']['clean']['rate'] is None
    assert len(empty['planned_groups']['clean']['missing']) == 10


def test_later_success_never_replaces_failed_first_operation_in_readiness_denominator():
    manifest = campaign.readiness_plan({'commit': 'controlled-candidate'})
    planned = manifest['baseline_operations'][0]['planned_operation_id']
    rows = [dict(operation_id='first', planned_operation_id=planned, status='failed', elapsed_seconds=20),
            dict(operation_id='retry', planned_operation_id=planned, retry_of='first', status='passed',
                 elapsed_seconds=100, independent_audit_passed=True, delivery_confirmed=True)]
    report = campaign.summarize_readiness(manifest, rows)
    assert report['planned_groups']['clean']['planned_denominator'] == 10
    assert report['planned_groups']['clean']['expected_outcomes_with_audit_and_retrieval'] == 0
    assert report['operations'] == 2
