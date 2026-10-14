"""Latest owner reduced pilot: all branches, both consent families, no expansion."""
import hashlib,json
import pytest
import ai_quality_campaign as campaign
import run_tui_acceptance as runner

THREE=['retrospective-sparse-complete.r1','prospective-sterling-sparse-complete.r1','ambispective-advarra-sparse-complete.r1']

def test_owner_three_freezes_exact_scope_and_refuses_expansion():
    default=campaign.readiness_plan({'git_commit':'synthetic-unit-test'},'hermes-tui')
    manifest=campaign.readiness_plan({'git_commit':'synthetic-unit-test'},'hermes-tui',pilot_scope='owner-three-only')
    campaign.validate_readiness_manifest(manifest)
    assert manifest['execution_scope']=='owner-three-pilot-only'
    assert manifest['pilot_operation_ids']==THREE
    assert [p['planned_operation_id'] for p in runner.select_phase_operations(manifest,'pilot')]==THREE
    for key in ('baseline_denominator','supplemental_denominator','deadline_seconds','target_seconds_exclusive'):
        assert manifest[key]==default[key]
    with pytest.raises(ValueError,match='owner-three'):
        runner.select_phase_operations(manifest,'remaining')
    manifest['pilot_operation_ids'][-1]='prospective-advarra-sparse-complete.r1'
    unsigned={k:v for k,v in manifest.items() if k!='manifest_sha256'}
    manifest['manifest_sha256']=hashlib.sha256(json.dumps(unsigned,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    with pytest.raises(ValueError,match='owner-three'):
        campaign.validate_readiness_manifest(manifest)
