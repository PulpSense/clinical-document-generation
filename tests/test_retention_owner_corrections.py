"""Focused owner corrections: immutable cleanup anchors and sequential boundary."""
import json
import pytest
import storage_retention as storage
import run_tui_acceptance as runner


def test_completed_cleanup_never_retires_previous_proof_anchors(tmp_path):
    run=tmp_path/'run';run.mkdir()
    state=run/'operation.json';state.write_text('{"status":"passed"}')
    def worker(name):
        p=run/'.hermes-cache'/name;(p/'bin').mkdir(parents=True)
        (p/'bin/tool').write_bytes(b'actual duplicate')
        (p/'models_dev_cache.json').write_bytes(b'actual duplicate catalog')
        (p/'state.db').write_bytes(name.encode())
        return p
    one=worker('one');worker('two')
    storage.completed_operation_cleanup(run,state)
    original=storage.inventory(one/'bin')
    catalog=storage.entry(one/'models_dev_cache.json','.')
    aaa=worker('aaa')
    storage.completed_operation_cleanup(run,state)
    assert storage.inventory(one/'bin')==original
    assert storage.entry(one/'models_dev_cache.json','.')==catalog
    assert not (aaa/'bin').exists()
    assert not (aaa/'models_dev_cache.json').exists()
    assert (aaa/'state.db').read_bytes()==b'aaa'


def test_owner_next_case_requires_previous_complete_audit(tmp_path):
    selected=[{'planned_operation_id':'one'},{'planned_operation_id':'two'}]
    (tmp_path/'one').mkdir()
    with pytest.raises(ValueError,match='audit'):
        runner.owner_next_operation(selected,tmp_path,lambda key:False)
    assert runner.owner_next_operation(selected,tmp_path,lambda key:True)==selected[1]


def test_storage_forecast_rejects_unrelated_hash_evidence(tmp_path):
    p=tmp_path/'unrelated';p.write_bytes(b'unrelated')
    forecast={'schema_version':'sequential-storage-forecast/v1','candidate_identity':{},
        'cases':[dict(case_id='one',retained_bytes=0,worker_peak_bytes=0,scratch_peak_bytes=0)],
        'margin_bytes':0,'evidence_inventory':[{'path':str(p),'sha256':storage.sha(p)}]}
    path=tmp_path/'forecast.json';path.write_text(json.dumps(forecast))
    with pytest.raises(ValueError,match='observation|component|margin'):
        runner.admit_storage(path,tmp_path,{},['one'])


def measured_forecast(tmp_path):
    import hashlib
    import time
    source=tmp_path/'observed';source.mkdir();(source/'native').write_bytes(b'known allocation')
    (source/'nested').mkdir()
    rows=storage.inventory(source)
    observation={'schema_version':'storage-allocation-observation/v1','root':str(source),
        'measured_at_epoch':time.time(),'scope':'temporary actual allocated fixture',
        'inventory':rows,'allocated_bytes':sum(r['allocated_bytes'] for r in rows),
        'inventory_sha256':hashlib.sha256(storage.canonical(rows)).hexdigest()}
    p=tmp_path/'observation.json';p.write_text(json.dumps(observation));digest=storage.sha(p)
    terms={}
    case={'case_id':'one','component_terms':terms}
    for key in ('retained_bytes','worker_peak_bytes','scratch_peak_bytes'):
        case[key]=observation['allocated_bytes']
        terms[key]=[{'observation_sha256':digest,'paths':[r['path'] for r in rows],
            'copies':1,'population':key,'rationale':'Independent future fixture population based on actual allocation'}]
    margin_terms=[dict(terms['scratch_peak_bytes'][0],population='margin')]
    return {'schema_version':'sequential-storage-forecast/v1','candidate_identity':{},'cases':[case],
        'evidence_inventory':[{'path':str(p),'sha256':digest}],
        'comparability':'Known small fixture versus one identically scoped future fixture; allocations are estimates.',
        'margin_bytes':observation['allocated_bytes'],
        'margin_basis':{'terms':margin_terms,'rounding_quantum_bytes':1,
            'rationale':'One additional actual fixture allocation for temporary uncertainty; no existing allocations charged.'}}


def test_valid_forecast_uses_actual_allocations_and_explained_populations(tmp_path):
    forecast=measured_forecast(tmp_path)
    storage.validate_storage_forecast(forecast)
    p=tmp_path/'forecast.json';p.write_text(json.dumps(forecast))
    report=runner.admit_storage(p,tmp_path,{},['one'])
    assert report['required_available_bytes']==4*forecast['cases'][0]['retained_bytes']


@pytest.mark.parametrize('mutation', ['double','amount','margin','source'])
def test_unsupported_forecast_cannot_pass_on_outer_hashes(tmp_path,mutation):
    forecast=measured_forecast(tmp_path)
    case=forecast['cases'][0]
    if mutation=='double':
        term=dict(case['component_terms']['retained_bytes'][0])
        case['component_terms']['scratch_peak_bytes']=[term]
    elif mutation=='amount':case['retained_bytes']+=1
    elif mutation=='margin':forecast['margin_bytes']+=1
    else:(tmp_path/'observed/native').write_bytes(b'changed allocation source')
    with pytest.raises(ValueError):storage.validate_storage_forecast(forecast)


@pytest.mark.parametrize('nested', [False, True])
def test_same_allocation_in_two_observation_snapshots_is_not_disjoint(tmp_path,nested):
    import hashlib
    forecast=measured_forecast(tmp_path)
    original=json.loads((tmp_path/'observation.json').read_text())
    original['measured_at_epoch']+=1
    if nested:
        original['root']=str(tmp_path/'observed/nested')
        original['inventory']=storage.inventory(tmp_path/'observed/nested')
        original['inventory_sha256']=hashlib.sha256(storage.canonical(original['inventory'])).hexdigest()
        original['allocated_bytes']=sum(r['allocated_bytes'] for r in original['inventory'])
    p=tmp_path/'second-observation.json';p.write_text(json.dumps(original))
    digest=storage.sha(p)
    forecast['evidence_inventory'].append({'path':str(p),'sha256':digest})
    term=dict(forecast['cases'][0]['component_terms']['retained_bytes'][0],observation_sha256=digest,
        paths=[r['path'] for r in original['inventory']])
    forecast['cases'][0]['component_terms']['retained_bytes'].append(term)
    forecast['cases'][0]['retained_bytes']+=original['allocated_bytes']
    with pytest.raises(ValueError,match='Double-counted'):storage.validate_storage_forecast(forecast)
