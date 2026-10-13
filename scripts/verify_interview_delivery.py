"""Repeat saved-response audits into a fresh receipt without overwriting evidence."""
import argparse
import json
from pathlib import Path
from datetime import datetime, timezone
import uuid

from scripts import audit_interview_sprint as main_auditor
from scripts import audit_interview_availability as diagnostic_auditor
from scripts.run_interview_sprint import read, publish
from scripts.run_skill_evolution import digest_file
from skillforge.interview_sprint.adapters import bind


def verify(main, diagnostic, output):
    checks=[]
    for module,root in [(main_auditor,main),(diagnostic_auditor,diagnostic)]:
        saved=read(root/'final-independent-audit.json')
        if digest_file(module.__file__)!=saved['auditor_sha256']:raise ValueError('saved auditor source identity changed')
        captured=[]
        def capture(path,value):
            if Path(path).name!='final-independent-audit.json':raise ValueError('unexpected auditor publication')
            captured.append(value)
        replay=bind(module.audit,{'publish':capture})(root)
        if len(captured)!=1 or captured[0]!=replay:raise ValueError('audit did not produce one receipt')
        if {k:v for k,v in replay.items() if k!='wall_seconds'}!={k:v for k,v in saved.items() if k!='wall_seconds'}:
            raise ValueError('new replay differs from original immutable audit')
        checks.append(replay)
    result={'passed':True,'created_utc':datetime.now(timezone.utc).isoformat(),'model_calls':0,'tokens':0,
        'generator_sha256':digest_file(__file__),'original_receipts_preserved':True,'checks':checks}
    publish(output,result)
    return {'passed':True,'receipt':str(output.resolve()),'model_calls':0,'tokens':0}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--main',type=Path,default=Path('results/interview-sprint/20261013-v4'))
    parser.add_argument('--diagnostic',type=Path,default=Path('results/interview-sprint/availability-dev-20261013-v2'))
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    output=args.output or args.main/'audit-reruns'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex+'.json')
    print(json.dumps(verify(args.main,args.diagnostic,output),ensure_ascii=False))
