"""Unpaid independent public-seam controls; no model or clinical evidence."""
import json, os, sys, time
from pathlib import Path
from datetime import datetime,timedelta,timezone
import pytest
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).resolve().parent)]

@pytest.mark.parametrize('malformed,cleanup_valid',[(False,True),(True,True),(True,False)])
def test_live_observer_independent_final_survives_bad_checkpoint(tmp_path,monkeypatch,malformed,cleanup_valid):
    import tui_visual_callback as callback,owned_observer_runtime as runtime,workflow,quality
    from test_visual_units import parent_fixture,response_for
    from visual_review import create_visual_review_unit,visual_review_result
    revision,parent_path,parent=parent_fixture(tmp_path,'retrospective')
    path=create_visual_review_unit(revision,parent_path,parent['visual_review_plan']['targets'][:1],1,observer_evidence_required=True)
    unit=json.loads(path.read_text())
    profile=tmp_path/'profile';profile.mkdir();(profile/'config.yaml').write_text('fixture only')
    monkeypatch.setattr(workflow,'_managed_hermes_pair',lambda:(Path('/fixture/launcher'),Path(sys.executable)))
    monkeypatch.setattr(workflow,'_managed_hermes_identity',lambda:{'fixture_only':True})
    progress=revision/unit['review_transport']['progress_path'];progress.parent.mkdir(parents=True,exist_ok=True)
    progress.write_text('{malformed interrupted checkpoint' if malformed else '')
    monkeypatch.setattr(workflow,'_prepare_worker_checkpoint',lambda *a:progress)
    def launch(command,*,state,write_launch,**kwargs):
        digest=quality.sha256_file(state/'provenance.json')
        command_hash=json.loads((state/'provenance.json').read_text())['command_sha256']
        fields={'pid':99999999,'start_ticks':'1','owned_command_sha256':command_hash,'supervisor_sha256':quality.sha256_file(Path(callback.__file__).with_name('owned_observer_process.py'))}
        write_launch(fields)
        proof={'fixture_only':True,'descendants_reaped':True,'errors':[],'owner_pid':fields['pid'],'owner_start_ticks':fields['start_ticks'],'command_sha256':command_hash}
        (state/'owned-descendant-cleanup.json').write_text(json.dumps(proof))
        (state/'stdout.log').write_text(json.dumps(response_for(unit)));(state/'stderr.log').write_text('');(state/'state.db').write_bytes(b'fixture')
        cleanup_hash=quality.sha256_file(state/'owned-descendant-cleanup.json')
        if not cleanup_valid:
            (state/'owned-descendant-cleanup.json').unlink()
        return {'returncode':0,'cleanup':proof,'cleanup_sha256':cleanup_hash,'failure':None}
    monkeypatch.setattr(runtime,'run_owned_observer',launch)
    def metadata(state,*a):
        return {'session_id':'fixture-session','model_id':'test-model','state_path':str(state),'database_sha256':quality.sha256_file(state/'state.db'),'request_inspection_complete':True,'native_inspection_complete':True,'inspected_paths':[p['path'] for t in unit['visual_scope'] for p in t['pages']],'image_tool_results':[{'tool':'vision_analyze','page_path':p['path'],'sha256':p['sha256'],'success':True} for t in unit['visual_scope'] for p in t['pages']]}
    monkeypatch.setattr(callback,'observer_metadata',metadata)
    if cleanup_valid:
        callback.observe_unit(revision,{'request_path':path.relative_to(revision).as_posix()},20,{'profile_path':str(profile),'configuration':{'source':'fixture','max_turns':1}})
        assert len(visual_review_result(revision,parent_path,publish=False)['assessments'])==1
    else:
        with pytest.raises(RuntimeError,match='incomplete authenticated visual scope'):
            callback.observe_unit(revision,{'request_path':path.relative_to(revision).as_posix()},20,{'profile_path':str(profile),'configuration':{'source':'fixture','max_turns':1}})
        assert visual_review_result(revision,parent_path,publish=False)['assessments']==[]
    if malformed:
        assert progress.read_text()=='{malformed interrupted checkpoint'

@pytest.mark.parametrize('timeout',[False,True])
def test_real_owner_case_productive_or_stops_detached_child(tmp_path,timeout):
    import run_tui_acceptance as runner
    seconds=9 if timeout else 12
    deadline=(datetime.now(timezone.utc)+timedelta(seconds=seconds)).isoformat()
    pidfile=tmp_path/'detached.pid'
    child="import os,sys,time;os.setsid();open(sys.argv[1],'w').write(str(os.getpid()));time.sleep(60)"
    code="import subprocess,sys,time;print('partial',flush=True);subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]]);time.sleep("+('60' if timeout else '.3')+")"
    started=time.monotonic()
    result=runner.run_owner_case([sys.executable,'-B','-c',code,child,str(pidfile)],deadline_utc=deadline,state=tmp_path/'launcher',cwd=tmp_path,env=dict(os.environ))
    assert time.monotonic()-started<seconds
    assert result['cleanup']['descendants_reaped'] is True
    pid=int(pidfile.read_text());assert not Path('/proc',str(pid)).exists()
    assert pid in result['cleanup']['reaped_pids']
    assert (result['returncode']!=0) if timeout else (result['returncode']==0)
    assert 'partial' in (tmp_path/'launcher/stdout.log').read_text()
    assert json.loads((tmp_path/'launcher/outcome.json').read_text())['deadline_utc']==deadline
