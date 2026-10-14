"""Single-purpose Linux subreaper; never adopts unrelated caller children."""
import ctypes,hashlib,json,os,signal,subprocess,sys,time
from pathlib import Path

ready_fd=int(sys.argv[1]);status_path=Path(sys.argv[2]);command=json.loads(sys.argv[3])
child=None;returncode=None;errors=[];reaped=[]
owner_pid=os.getpid();owner_start_ticks=Path(f'/proc/{owner_pid}/stat').read_text().rsplit(')',1)[1].split()[19]
def interrupted(signum,frame):raise TimeoutError('Owned process interrupted')
try:
    children_path=Path(f'/proc/self/task/{os.getpid()}/children')
    children_path.read_text()
    libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(36,1,0,0,0)!=0:raise OSError(ctypes.get_errno(),'Cannot own descendants')
    signal.signal(signal.SIGTERM,interrupted)
    os.write(ready_fd,b'ready\n');os.close(ready_fd);ready_fd=None
    child=subprocess.Popen(command)
    returncode=child.wait()
except TimeoutError:pass
except BaseException as exc:errors.append(type(exc).__name__+': '+str(exc))
finally:
    signal.signal(signal.SIGTERM,signal.SIG_IGN)
    end=time.monotonic()+5
    try:
        while True:
            while True:
                try:
                    pid,status=os.waitpid(-1,os.WNOHANG)
                    if child is not None and pid==child.pid:returncode=os.waitstatus_to_exitcode(status)
                    if pid:reaped.append(pid)
                except ChildProcessError:pid=0
                if not pid:break
            children=[int(p) for p in children_path.read_text().split()]
            if not children:break
            for pid in children:
                try:os.kill(pid,signal.SIGKILL)
                except ProcessLookupError:pass
            if time.monotonic()>=end:raise RuntimeError('Owned descendants remain after cleanup bound')
            time.sleep(.005)
    except BaseException as exc:errors.append(type(exc).__name__+': '+str(exc))
    if ready_fd is not None:os.close(ready_fd)
    record={'returncode':returncode,'errors':errors,'reaped_pids':reaped,'descendants_reaped':not errors,
        'owner_pid':owner_pid,'owner_start_ticks':owner_start_ticks,'command_sha256':hashlib.sha256(sys.argv[3].encode()).hexdigest()}
    fd=os.open(status_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:json.dump(record,f);f.flush();os.fsync(f.fileno())
sys.exit(0 if not errors else 1)
