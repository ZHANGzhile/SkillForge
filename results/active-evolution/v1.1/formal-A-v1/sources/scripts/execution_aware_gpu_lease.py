"""Temporarily release only verified owned services; restore on context exit."""
import json
from pathlib import Path
import subprocess
import time
import urllib.request


def get(url):
    with urllib.request.urlopen(url,timeout=5) as response:return json.load(response)


class GPUServiceLease:
    def __init__(self):self.saved=[];self.root=Path.cwd();self.lock=self.root/'.runtime/active-evolution-gpu-lease.json'
    def __enter__(self):
        import psutil
        if self.lock.exists():raise RuntimeError("another GPU lease exists; inspect before recovery")
        deployment=json.loads(Path('configs/deployment.local.json').read_text(encoding='utf-8'))
        try:student=get('http://127.0.0.1:8002/health')
        except OSError:student=None
        if student and student['settings']['adapter_sha256']!=deployment['adapter_sha256']:raise RuntimeError('unverified GPU model service')
        try:web=get('http://127.0.0.1:8080/api/v1/health')
        except OSError:web=None
        if web:
            offset=0
            while True:
                rows=get('http://127.0.0.1:8080/api/v1/runs?limit=100&offset='+str(offset))['runs']
                if any(r['status'] in ('queued','running') for r in rows):raise RuntimeError('workbench has live tasks')
                if len(rows)<100:break
                offset+=100
        plans=[]
        for exists,pidfile,module in [(web,'project-web.pid',('skillforge.api:app','skillforge.evolution_workbench.app:app')),(student,'trained-student.pid',('skillforge.hf_server:app',))]:
            if not exists:continue
            owner=psutil.Process(int((self.root/'.runtime'/pidfile).read_text().strip()))
            children=owner.children(recursive=True)
            if any(p.name().lower() not in {'python.exe','conhost.exe'} for p in children):raise RuntimeError('unexpected service descendant')
            processes=[owner]+[p for p in children if p.name().lower()=='python.exe']
            for p in processes:
                if not any(allowed in p.cmdline() for allowed in module) or Path(p.cwd()).resolve()!=self.root:raise RuntimeError('unverified owned service')
            plans.append({'pidfile':pidfile,'command':owner.cmdline(),'env':processes[-1].environ(),'processes':processes})
        with self.lock.open('x',encoding='utf-8') as stream:json.dump({'services':[p['pidfile'] for p in plans],'scope':'serial active-evolution GPU evaluation'},stream)
        try:
            for plan in plans:
                self.saved.append(plan)
                for p in reversed(plan['processes']):
                    try:p.terminate()
                    except psutil.NoSuchProcess:pass
                _,alive=psutil.wait_procs(plan['processes'],timeout=5)
                if alive:raise RuntimeError('owned service failed to stop')
            return self
        except BaseException:self.__exit__(None,None,None);raise

    def __exit__(self,*args):
        for plan in reversed(self.saved):
            prefix=self.root/'.runtime'/('active-restore-'+plan['pidfile'])
            with Path(str(prefix)+'.stdout.log').open('ab') as out,Path(str(prefix)+'.stderr.log').open('ab') as err:
                p=subprocess.Popen(plan['command'],cwd=self.root,env=plan['env'],stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW)
            (self.root/'.runtime'/plan['pidfile']).write_text(str(p.pid),encoding='utf-8')
        self.lock.unlink(missing_ok=True)
