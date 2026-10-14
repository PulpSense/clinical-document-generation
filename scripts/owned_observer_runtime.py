"""Owned Linux observer launch; guard from Popen through ready and final reaping."""
import hashlib,json,os,select,signal,subprocess,sys,time
from pathlib import Path

class OwnedObserverLifetimeUnresolved(RuntimeError):
 pass

def validate_owned_observer_cleanup(state):
 state=Path(state)
 launch=json.loads((state/'launch.json').read_text());provenance=json.loads((state/'provenance.json').read_text())
 path=state/'owned-descendant-cleanup.json'
 if path.is_symlink() or not path.is_file():raise OwnedObserverLifetimeUnresolved('Missing owned cleanup proof')
 proof=json.loads(path.read_text())
 if not (isinstance(proof,dict) and isinstance(launch,dict) and isinstance(provenance,dict)
  and proof.get('descendants_reaped') is True and proof.get('errors')==[]
  and proof.get('owner_pid')==launch.get('pid') and proof.get('owner_start_ticks')==launch.get('start_ticks')
  and proof.get('command_sha256')==launch.get('owned_command_sha256')==provenance.get('command_sha256')
  and launch.get('supervisor_sha256')==hashlib.sha256(Path(__file__).with_name('owned_observer_process.py').read_bytes()).hexdigest()):
  raise OwnedObserverLifetimeUnresolved('Unbound owned observer cleanup proof')
 return proof

def run_owned_observer(command, *, cwd, env, state, budget, write_launch):
 state=Path(state);status=state/'owned-descendant-cleanup.json'
 supervisor=Path(__file__).with_name('owned_observer_process.py')
 encoded=json.dumps(command);expected_command=hashlib.sha256(encoded.encode()).hexdigest()
 read_fd,write_fd=os.pipe();process=None;start_ticks=None;failure=None
 started=time.monotonic()
 try:
  with (state/'stdout.log').open('x') as stdout,(state/'stderr.log').open('x') as stderr:
   process=subprocess.Popen([sys.executable,'-B',str(supervisor),str(write_fd),str(status),encoded],cwd=cwd,env=env,pass_fds=(write_fd,),stdout=stdout,stderr=stderr,text=True,start_new_session=True)
   os.close(write_fd);write_fd=None
   start_ticks=Path(f'/proc/{process.pid}/stat').read_text().rsplit(')',1)[1].split()[19]
   write_launch({'pid':process.pid,'start_ticks':start_ticks,'owned_command_sha256':expected_command,'owned_cleanup_path':status.name,'supervisor_sha256':hashlib.sha256(supervisor.read_bytes()).hexdigest()})
   ready,_,_=select.select([read_fd],[],[],min(3.0,max(0.01,budget-8.0)))
   if not ready or os.read(read_fd,6)!=b'ready\n':raise TimeoutError('Observer supervisor readiness failed')
   process.wait(timeout=max(0.01,budget-(time.monotonic()-started)-7.0))
 except BaseException as exc:failure=exc
 finally:
  os.close(read_fd)
  if write_fd is not None:os.close(write_fd)
  if process is not None and process.poll() is None:
   process.send_signal(signal.SIGTERM)
   try:process.wait(timeout=7)
   except subprocess.TimeoutExpired:
    process.kill();process.wait(timeout=1)
 if process is None:raise OwnedObserverLifetimeUnresolved('Observer supervisor did not launch') from failure
 try:
  proof=json.loads(status.read_text())
  if not (proof.get('descendants_reaped') is True and proof.get('errors')==[] and proof.get('owner_pid')==process.pid and proof.get('owner_start_ticks')==start_ticks and proof.get('command_sha256')==expected_command):raise ValueError('Unbound or unresolved observer cleanup')
 except (ValueError,OSError) as exc:raise OwnedObserverLifetimeUnresolved('Observer descendants not proven reaped; preserve all evidence and assets') from exc
 return {'returncode':proof.get('returncode'),'cleanup':proof,'cleanup_sha256':hashlib.sha256(status.read_bytes()).hexdigest(),'failure':failure,'elapsed_seconds':time.monotonic()-started}
