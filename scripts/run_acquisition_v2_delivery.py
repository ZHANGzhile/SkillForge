"""Own one CPU B invocation through freeze, completion and independent audit."""
from contextlib import nullcontext
import json
import os
from pathlib import Path
import time
import uuid

from scripts.acquisition_v2_protocol import DEV, ROOT, freeze, run_cpu
from scripts.audit_acquisition_v2 import audit
from scripts.execution_aware_formal import read
from scripts.prepare_active_evolution import file_hash
from scripts.resume_execution_after_sleep import PreventIdleSleep
from skillforge.evolution_registry import immutable_json
from skillforge.evolution_schemas import fingerprint


def main():
    evidence = read(DEV/'audits/evidence.json')
    if not evidence['passed'] or len(evidence['runs']) != 24 or evidence['report_hash'] != file_hash(DEV/'report.json'):
        raise ValueError('complete verified development required')
    lock = Path('.runtime/acquisition-B.lock'); lock.parent.mkdir(parents=True,exist_ok=True)
    with lock.open('x',encoding='utf-8') as stream:
        json.dump({'pid':os.getpid(),'scope':'B CPU only'},stream)
    started = time.perf_counter(); invocation = uuid.uuid4().hex; status='incomplete'; error=None
    try:
        with PreventIdleSleep() if os.name=='nt' else nullcontext():
            protocol = freeze()
            immutable_json(ROOT/'invocations'/(invocation+'.start.json'),{
                'protocol_hash':fingerprint(protocol),'cpu_only':True,'development_audit_hash':file_hash(DEV/'audits/evidence.json'),
                'reporting_sources':{p:file_hash(p) for p in (__file__,'scripts/audit_acquisition_v2.py')},
                'idle_sleep_prevention':os.name=='nt'})
            print(json.dumps({'stage':'B-frozen','protocol_hash':fingerprint(protocol),'invocation':invocation}),flush=True)
            run_cpu()
            audit()
            status='complete'
    except BaseException as exc:
        error=type(exc).__name__+': '+str(exc)
        raise
    finally:
        immutable_json(ROOT/'invocations'/(invocation+'.final.json'),{'status':status,'error':error,
            'cpu_wall_seconds':time.perf_counter()-started,'gpu_seconds':0,'model_tokens':0})
        lock.unlink()


if __name__=='__main__':
    main()
