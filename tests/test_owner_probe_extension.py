import json, hashlib
import pytest
import storage_retention as storage

PROBE_DECISION="do as many tests as yo need for this to work, extend the limit to 50 if you ned, i don' care"
PROBE_AUTH={'owner_decision':PROBE_DECISION,'prior_probe_limit':6,'additional_probe_limit':50,
    'study_operation_limit':20,'operation_deadline_seconds':2700,'sequential_studies_only':True}
DEADLINE_AUTH={'owner_decision':'Extend the cutoff to 18:12 UTC',
    'prior_deadline_utc':'2026-10-14T16:12:25.124854+00:00','study_seconds':2700,
    'study_operation_limit':20,'additional_probe_limit':50,'sequential_studies_only':True}

@pytest.mark.parametrize('mutation',['valid','missing_probe_authority','missing_deadline_authority',
    'probe51','probe_bool','study21','deadline_changed','seconds_changed','ledger_cap_changed','bad_hash',
    'probe_sequential_int','deadline_sequential_int','probe_seconds_float','deadline_studies_float'])
def test_owner_approved_probe_and_cutoff_extensions_are_exact(tmp_path,monkeypatch,mutation):
    authority={'deadline_utc':'2026-10-14T18:12:25.124854+00:00',
        'original_started_at_utc':'2026-10-14T01:12:25.124854+00:00',
        'study_operation_limit':20,'additional_probe_limit':50,
        'counts_are_cumulative_across_all_coordinators':True,'operation_deadline_seconds':2700,
        'delegated_visual_cap_seconds':240,'parent_visual_cap_seconds':480,
        'probe_extension_authority':dict(PROBE_AUTH),'deadline_extension_authority':dict(DEADLINE_AUTH)}
    if mutation=='missing_probe_authority':authority.pop('probe_extension_authority')
    if mutation=='missing_deadline_authority':authority.pop('deadline_extension_authority')
    if mutation=='probe51':authority['additional_probe_limit']=51
    if mutation=='probe_bool':authority['additional_probe_limit']=True
    if mutation=='study21':authority['study_operation_limit']=21
    if mutation=='deadline_changed':authority['deadline_utc']='2026-10-14T19:12:25.124854+00:00'
    if mutation=='seconds_changed':authority['operation_deadline_seconds']=2701
    if mutation=='probe_sequential_int':authority['probe_extension_authority']['sequential_studies_only']=1
    if mutation=='deadline_sequential_int':authority['deadline_extension_authority']['sequential_studies_only']=1
    if mutation=='probe_seconds_float':authority['probe_extension_authority']['operation_deadline_seconds']=2700.0
    if mutation=='deadline_studies_float':authority['deadline_extension_authority']['study_operation_limit']=20.0
    path=tmp_path/'limits.json';path.write_text(json.dumps(authority));monkeypatch.setattr(storage,'OWNER_LIMITS_AUTHORITY',path)
    ledger={'limits':{'study_operations':20,'capability_probes':50},'deadline_utc':authority['deadline_utc'],
        'limits_authority':{'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}}
    if mutation=='ledger_cap_changed':ledger['limits']['capability_probes']=51
    if mutation=='bad_hash':ledger['limits_authority']['sha256']='0'*64
    if mutation=='valid':assert storage.owner_limits(ledger)=={**ledger['limits'],'deadline_utc':authority['deadline_utc']}
    else:
        with pytest.raises(ValueError):storage.owner_limits(ledger)
