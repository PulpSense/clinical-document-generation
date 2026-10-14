import hashlib,json,os,sys,time
from pathlib import Path
import pytest
from owned_observer_runtime import run_owned_observer,OwnedObserverLifetimeUnresolved

def test_real_owned_observer_reaps_detached_descendant(tmp_path):
 state=tmp_path/'state';state.mkdir();pidfile=state/'escaped.pid'
 code="import os,subprocess,sys; subprocess.Popen([sys.executable,'-c',\"import os,time;os.setsid();open(sys.argv[1],'w').write(str(os.getpid()));time.sleep(30)\",sys.argv[1]]); import time; time.sleep(.3)"
 # Include sys in detached child's independently executed source.
 code=code.replace('import os,time;','import os,time,sys;')
 result=run_owned_observer([sys.executable,'-B','-c',code,str(pidfile)],cwd=tmp_path,env=dict(os.environ),state=state,budget=12,
  write_launch=lambda row:(state/'launch.json').write_text(json.dumps(row)))
 assert result['cleanup']['descendants_reaped'] is True
 pid=int(pidfile.read_text());assert not Path('/proc',str(pid)).exists()
 assert pid in result['cleanup']['reaped_pids']

@pytest.mark.parametrize('malformed', [[], None, 'not-a-certificate'])
def test_wrong_type_cleanup_proof_is_explicitly_unresolved(tmp_path, malformed):
 import owned_observer_runtime as runtime
 state=tmp_path/'state';state.mkdir()
 (state/'launch.json').write_text('{}');(state/'provenance.json').write_text('{}')
 (state/'owned-descendant-cleanup.json').write_text(json.dumps(malformed))
 with pytest.raises(OwnedObserverLifetimeUnresolved):runtime.validate_owned_observer_cleanup(state)


def test_unresolved_observer_proof_rejects_metadata(tmp_path):
 import owned_observer_runtime as runtime
 state=tmp_path/'state';state.mkdir();(state/'launch.json').write_text('{}');(state/'provenance.json').write_text('{}')
 (state/'owned-descendant-cleanup.json').write_text(json.dumps({'descendants_reaped':False,'errors':['unresolved']}))
 with pytest.raises(OwnedObserverLifetimeUnresolved):runtime.validate_owned_observer_cleanup(state)

def test_real_malformed_observer_handshake_never_leaves_running_child(tmp_path,monkeypatch):
 import owned_observer_runtime as runtime
 state=tmp_path/'state';state.mkdir();launch=[]
 monkeypatch.setattr(runtime.select,'select',lambda *a:([],[],[]))
 try:
  result=run_owned_observer([sys.executable,'-B','-c','import time;time.sleep(30)'],cwd=tmp_path,env=dict(os.environ),state=state,budget=10,write_launch=launch.append)
 except OwnedObserverLifetimeUnresolved:result=None
 assert launch and not Path('/proc',str(launch[0]['pid'])).exists()
 if result:assert result['cleanup']['descendants_reaped'] is True
