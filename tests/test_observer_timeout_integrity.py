"""Independent public short-process controls; no model or clinical acceptance."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path
import pytest
import workflow
import tui_visual_callback as callback
import owned_observer_runtime as runtime
from visual_review import create_visual_review_unit
from test_visual_units import parent_fixture

HERE = Path(__file__).parent  # Observations retained in each disposable test fixture

@pytest.mark.parametrize('fault', ['none','request-bytes','request-content','provenance-request','provenance-command','cleanup-content','cleanup-hash','cleanup-missing','poisoned-ledger','returncode-null','returncode-string','other-failure'])
def test_real_timeout_integrity_transport(tmp_path, monkeypatch, fault):
    revision, parent_path, parent = parent_fixture(tmp_path, 'retrospective')
    path = create_visual_review_unit(revision, parent_path, parent['visual_review_plan']['targets'][:1], 1, observer_evidence_required=True)
    profile = tmp_path/'profile'; profile.mkdir()
    (profile/'config.yaml').write_text('controlled local timeout')
    launcher = tmp_path/'short.py'; launcher.write_text('import time\ntime.sleep(30)\n')
    monkeypatch.setattr(workflow, '_managed_hermes_pair', lambda:(launcher,Path(sys.executable)))
    monkeypatch.setattr(workflow, '_managed_hermes_identity', lambda:{'local_control':True})
    original_run = runtime.run_owned_observer
    def run(*args, **kwargs):
        owned = original_run(*args, **kwargs)
        assert isinstance(owned['failure'], subprocess.TimeoutExpired)
        assert not Path('/proc',str(owned['cleanup']['owner_pid'])).exists()
        if fault.startswith('returncode-'):
            # Inject a malformed runtime return/proof at its boundary, with current exact hash.
            value = None if fault.endswith('null') else 'bogus'
            proof_path=kwargs['state']/'owned-descendant-cleanup.json'
            proof=json.loads(proof_path.read_text());proof['returncode']=value
            proof_path.write_text(json.dumps(proof))
            owned.update(returncode=value,cleanup=proof,cleanup_sha256=hashlib.sha256(proof_path.read_bytes()).hexdigest())
        if fault=='other-failure': owned['failure']=RuntimeError('Controlled runtime integrity rejection')
        return owned
    monkeypatch.setattr(runtime,'run_owned_observer',run)
    original_result=callback.visual_review_unit_result
    def result(*args, **kwargs):
        state=next((revision/'hermes/visual-review-observers').iterdir())
        proof=state/'owned-descendant-cleanup.json'
        if fault=='request-bytes': path.write_text(path.read_text()+' ')
        if fault=='request-content':
            value=json.loads(path.read_text());value['visual_scope']=[];path.write_text(json.dumps(value))
        if fault.startswith('provenance-'):
            target=state/'provenance.json';value=json.loads(target.read_text())
            value['request_sha256' if fault.endswith('request') else 'command_sha256']='forged'
            target.write_text(json.dumps(value))
        if fault=='cleanup-content':
            value=json.loads(proof.read_text());value['descendants_reaped']=False;proof.write_text(json.dumps(value))
        if fault=='cleanup-hash': proof.write_text(proof.read_text()+' ')
        if fault=='cleanup-missing': proof.unlink()
        if fault=='poisoned-ledger':
            target=revision/f"hermes/visual-review-ledgers/{json.loads(path.read_text())['request_id']}.json"
            value=json.loads(target.read_text());value['integrity_rejection']={'reason':'Controlled fatal rejection'};target.write_text(json.dumps(value))
        return original_result(*args,**kwargs)
    monkeypatch.setattr(callback,'visual_review_unit_result',result)
    caught=None
    try:
        callback.observe_unit(revision,{'request_path':path.relative_to(revision).as_posix()},0.3,{'profile_path':str(profile),'configuration':{'source':'fixture','max_turns':1}})
    except Exception as exc: caught=exc
    state=next((revision/'hermes/visual-review-observers').iterdir())
    observation={'fault':fault,'exception':type(caught).__name__,'error':str(caught),'diagnostic':json.loads((state/'diagnostic.json').read_text()),'response_exists':(revision/json.loads(path.read_text())['response_path']).exists(),'credit':original_result(revision,path)}
    (tmp_path/(fault+'-observation.json')).write_text(json.dumps(observation,indent=2,default=str))
    assert caught is not None
    assert not observation['response_exists']
    if fault=='none': assert isinstance(caught,subprocess.TimeoutExpired)
    else: assert not isinstance(caught,(TimeoutError,subprocess.TimeoutExpired)), 'Fatal malformed/changed integrity was transported as ordinary timeout'
