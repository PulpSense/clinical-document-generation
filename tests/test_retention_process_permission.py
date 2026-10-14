import json,os,subprocess,sys
from pathlib import Path
import pytest
import storage_retention as storage

def test_real_host_nondumpable_owned_child_never_authorizes_deletion(tmp_path):
 target=tmp_path/'asset';target.mkdir();(target/'keep').write_text('closed-worker assets cannot be removed while a same-user process is uninspectable')
 code="import ctypes,time; assert ctypes.CDLL(None).prctl(4,0,0,0,0)==0; print('ready',flush=True); time.sleep(20)"
 child=subprocess.Popen([sys.executable,'-B','-c',code,str(target)],stdout=subprocess.PIPE,text=True)
 try:
  assert child.stdout.readline().strip()=='ready'
  with pytest.raises(storage.OwnedProcessProofUnavailable) as caught:storage.stopped_references(target)
  assert caught.value.diagnostics['pid']==child.pid
  assert os.getuid() in caught.value.diagnostics['uids']
  assert (target/'keep').read_text().startswith('closed-worker')
 finally:
  child.terminate();child.wait(timeout=5)
 assert child.pid not in storage.stopped_references(target)['owned_pids_checked']

def test_permission_diagnostic_is_not_a_cleanup_or_worker_integrity_pass():
 error=storage.OwnedProcessProofUnavailable({'pid':42,'uids':[10000],'state':'S'})
 assert error.storage_reclamation_deferred is True
 assert not getattr(error,'worker_integrity_failure',None)
 assert '42' in str(error)


def test_stable_kernel_zombie_is_not_a_live_reference(tmp_path):
 import time
 child=subprocess.Popen([sys.executable,'-B','-c','pass'])
 try:
  deadline=time.monotonic()+5
  while storage.public_process_identity(Path('/proc')/str(child.pid))['state']!='Z':
   assert time.monotonic()<deadline;time.sleep(.01)
  proof=storage.stopped_references(tmp_path)
  assert any(p['pid']==child.pid and p['state']=='Z' for p in proof['kernel_ended_pids'])
 finally:child.wait(timeout=5)


def test_reclamation_wait_logs_and_never_waives_permission(tmp_path):
 now=[0.0];calls=[]
 def busy(revision):
  calls.append(1);raise storage.OwnedProcessProofUnavailable({'pid':42,'uids':[10000],'state':'S'})
 with pytest.raises(storage.OwnedProcessProofUnavailable):
  storage.await_observer_reclamation(tmp_path,2,cleanup=busy,clock=lambda:now[0],sleep=lambda value:now.__setitem__(0,now[0]+value))
 assert len(calls)==3
 rows=[json.loads(line) for line in (tmp_path/'hermes/observer-reclamation-wait.jsonl').read_text().splitlines()]
 assert all(row['no_new_observer_allocated'] and row['no_deletion_proof_waiver'] for row in rows)
 assert now[0]==2


def test_unavailable_reclamation_preserves_partial_no_false_pass(tmp_path):
 from test_visual_units import parent_fixture,response_for
 from visual_review import run_visual_review
 revision,parent,_=parent_fixture(tmp_path,'retrospective');calls=[]
 def dispatch(handoffs,budget):
  calls.append(1);unit=json.loads((revision/handoffs[0]['request_path']).read_text())
  checkpoint=revision/unit['review_transport']['progress_path'];checkpoint.parent.mkdir(parents=True,exist_ok=True)
  checkpoint.write_text(json.dumps(response_for(unit,unit['visual_scope'][:1])))
  raise storage.OwnedProcessProofUnavailable({'pid':42,'uids':[10000],'state':'S'})
 result=run_visual_review(revision,parent,dispatch,30)
 assert len(calls)==1 and not result['complete'] and len(result['assessments'])==1
 assert result['resource_deferred']['pid']==42


def test_identity_integrity_errors_are_not_retried(tmp_path):
 calls=[]
 def bad(revision):calls.append(1);raise ValueError('Foreign catalog worker')
 with pytest.raises(ValueError,match='Foreign'):
  storage.await_observer_reclamation(tmp_path,100,cleanup=bad)
 assert calls==[1]
