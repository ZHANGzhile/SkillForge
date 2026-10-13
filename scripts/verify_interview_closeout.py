"""Replay all four delivered studies without overwriting any original receipt."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import json
import uuid

from scripts import run_interview_sprint as base
from scripts import run_interview_reference as reference
from scripts import run_interview_binding as binding
from scripts import audit_interview_sprint, audit_interview_availability, audit_interview_reference, audit_interview_binding
from scripts.run_skill_evolution import digest_file
from skillforge.interview_sprint.adapters import bind
from skillforge.evolution_schemas import fingerprint


def reference_replay_check(plan):
    """Original identity checks; an expired inference deadline cannot ban CPU review."""
    if fingerprint({k:v for k,v in plan.items() if k!='hash'})!=plan['hash']:raise ValueError('reference plan differs')
    for name,h in plan['sources'].items():
        if digest_file(base.ROOT/name)!=h:raise ValueError('reference source differs: '+name)
    if digest_file(reference.PARENT/'report.json')!=plan['parent_main_report_sha256'] or digest_file(reference.PRIOR_DEV/'report.json')!=plan['optimizer_feedback_dev_report_sha256']:
        raise ValueError('reference parent/dev evidence differs')


def verify(output):
    output=Path(output).resolve()
    if output.exists():raise ValueError('fresh verification output required')
    checks=[];root=base.ROOT/'results/interview-sprint'
    modules=[(audit_interview_sprint,root/'20261013-v4'),
        (audit_interview_availability,root/'availability-dev-20261013-v2'),
        (audit_interview_reference,reference.DEFAULT),(audit_interview_binding,binding.DEFAULT)]
    # Hash every original audit/admission receipt before and after. Per-arm
    # publications are checked against existing bytes, never rewritten.
    preserved={p:digest_file(p) for _,folder in modules for p in folder.rglob('*.json')
        if 'audit' in p.name or 'admission' in p.name or p.name in {'report.json','plan.json','protocol.json'}}
    for module,folder in modules:
        saved=base.read(folder/'final-independent-audit.json')
        if digest_file(module.__file__)!=saved['auditor_sha256']:raise ValueError('auditor source changed')
        captured=[]
        def existing(path,value):
            if not Path(path).exists() or base.read(path)!=value:raise ValueError('per-arm audit differs; original evidence retained')
        def capture(path,value):
            if Path(path).name=='final-independent-audit.json':captured.append(value)
            else:existing(path,value)
        arm=bind(base.audit_arm,{'publish':existing})
        namespace=SimpleNamespace(**{**vars(base),'publish':capture,'audit_arm':arm})
        overrides={'base':namespace,'publish':capture,'audit_arm':arm}
        if module is audit_interview_reference:
            overrides['study']=SimpleNamespace(**{**vars(reference),'check':reference_replay_check})
        proof=bind(module.audit,overrides)(folder)
        if len(captured)!=1 or captured[0]!=proof:raise ValueError('one independent receipt expected')
        if {k:v for k,v in proof.items() if k!='wall_seconds'}!={k:v for k,v in saved.items() if k!='wall_seconds'}:
            raise ValueError('replay result differs from delivered audit')
        checks.append({'run':folder.relative_to(base.ROOT).as_posix(),'original_audit_sha256':digest_file(folder/'final-independent-audit.json'),
            'new_cpu_audit':proof})
    if any(digest_file(p)!=h for p,h in preserved.items()):raise ValueError('original receipt changed during review')
    summary=base.read(binding.DEFAULT/'delivery-summary.json')
    registration=base.read(binding.DEFAULT/'audit-registration.json')
    for name,h in registration['sources'].items():
        if digest_file(base.ROOT/name)!=h or digest_file(binding.DEFAULT/'audit-source-snapshot'/name)!=h:
            raise ValueError('registered audit/summary source differs')
    if (sum(c['new_cpu_audit']['completed_arms'] for c in checks)!=summary['cumulative_real_arms'] or
        summary['cumulative_sprint_tokens']!=1425483 or summary['cumulative_sprint_model_calls']!=476 or
        summary['agent_admitted'] or summary['activated']):raise ValueError('closeout totals or disposition differ')
    p11=base.read(base.ROOT/'results/skill-evolution/v1.3/formal-P11-v1/protocol.json')
    if any(digest_file(base.ROOT/n)!=h for n,h in p11['sources'].items()):raise ValueError('P11 frozen source changed')
    body={'passed':True,'created_utc':datetime.now(timezone.utc).isoformat(),'generator_sha256':digest_file(__file__),
        'model_calls':0,'tokens':0,'original_receipts_preserved':True,'preserved_receipts':len(preserved),
        'p11_unchanged_sources':len(p11['sources']),'studies':checks,
        'completed_real_arms':sum(c['new_cpu_audit']['completed_arms'] for c in checks),
        'checkpoints':sum(c['new_cpu_audit']['checkpoints'] for c in checks),
        'cumulative_sprint_tokens':summary['cumulative_sprint_tokens'],'agent_admitted':False,'activated':False,
        'cpu_response_replay_tools':sum(c['new_cpu_audit'].get('actual_sqlite_replay_tool_calls',
            c['new_cpu_audit'].get('actual_replay_tool_calls',c['new_cpu_audit'].get('actual_sqlite_response_replay_tools',0))) for c in checks),
        'cpu_program_replay_tools':sum(c['new_cpu_audit'].get('program_validation_replay_tool_calls',c['new_cpu_audit'].get('program_replay_tools',0)) for c in checks),
        'new_cpu_wall_seconds':sum(c['new_cpu_audit']['wall_seconds'] for c in checks),
        'summary_sha256':digest_file(binding.DEFAULT/'delivery-summary.json')}
    base.publish(output,body)
    return {'passed':True,'receipt':str(output),'model_calls':0,'tokens':0,'arms':body['completed_real_arms'],'checkpoints':body['checkpoints'],
        'cpu_response_tools':body['cpu_response_replay_tools'],'cpu_program_tools':body['cpu_program_replay_tools']}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path)
    args=parser.parse_args();dest=args.output or binding.DEFAULT/'audit-reruns'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex+'.json')
    print(json.dumps(verify(dest),ensure_ascii=False))
