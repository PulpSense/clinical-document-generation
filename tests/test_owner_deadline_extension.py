import json, hashlib
import pytest
import storage_retention as storage

@pytest.mark.parametrize('mutation', ['valid', 'missing_extension', 'changed_cap', 'unsupported_deadline'])
def test_explicit_owner_cutoff_extension_preserves_fixed_caps(tmp_path, monkeypatch, mutation):
    authority = {'deadline_utc':'2026-10-14T16:12:25.124854+00:00',
        'original_started_at_utc':'2026-10-14T01:12:25.124854+00:00',
        'study_operation_limit':20, 'additional_probe_limit':6,
        'counts_are_cumulative_across_all_coordinators':True,
        'operation_deadline_seconds':2700, 'delegated_visual_cap_seconds':240,
        'parent_visual_cap_seconds':480,
        'deadline_extension_authority':{'owner_decision':'Extend the campaign cutoff to 16:12 UTC',
            'prior_deadline_utc':'2026-10-14T13:12:25.124854+00:00',
            'study_seconds':2700, 'cumulative_caps_unchanged':True, 'sequential_studies_only':True}}
    if mutation == 'missing_extension': authority.pop('deadline_extension_authority')
    if mutation == 'changed_cap': authority['additional_probe_limit']=7
    if mutation == 'unsupported_deadline': authority['deadline_utc']='2026-10-14T18:12:25.124854+00:00'
    p=tmp_path/'limits.json';p.write_text(json.dumps(authority))
    monkeypatch.setattr(storage, 'OWNER_LIMITS_AUTHORITY',p)
    ledger={'limits':{'study_operations':20,'capability_probes':6},
        'deadline_utc':authority['deadline_utc'],
        'limits_authority':{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}}
    if mutation == 'valid': assert storage.owner_limits(ledger)['deadline_utc']==authority['deadline_utc']
    else:
        with pytest.raises(ValueError):storage.owner_limits(ledger)
