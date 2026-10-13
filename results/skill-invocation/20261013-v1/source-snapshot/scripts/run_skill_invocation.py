"""Frozen nine-arm dev comparison; no training, prompt edits or activation."""
import argparse
from contextlib import ExitStack
from datetime import datetime,timezone
from pathlib import Path
import json
import subprocess
import time

from scripts import run_interview_sprint as base
from scripts.continue_interview_sprint import safe_coverage
from scripts.run_skill_evolution import digest_file
from skillforge.interview_sprint import adapters as old
from skillforge.interview_sprint.workflows import make_case,WorkflowCase,GOAL,verify_workflow
from skillforge.skill_evolution.catalog import Catalog
from skillforge.evolution_common.artifacts import clone,SplitLedger
from skillforge.evolution_schemas import fingerprint
from skillforge.skill_invocation import runtime

ROOT=base.ROOT
DEFAULT=ROOT/'results/skill-invocation/20261013-v1'
PARENT=ROOT/'results/interview-sprint/20261013-v4'
PREVIOUS=ROOT/'results/interview-sprint/binding-followup-20261013-v1'
START='2026-10-13T12:41:40+00:00'
DEADLINE='2026-10-13T14:41:40+00:00'
METHODS=['A','B','C']


def now():return datetime.now(timezone.utc)


def learned_entry():
    proof=base.read(PARENT/'final-independent-audit.json')
    if not proof['passed'] or proof['report_sha256']!=digest_file(PARENT/'report.json'):raise ValueError('audited parent required')
    screen=base.read(PARENT/'candidate-screen.json')
    sid=next(x['candidate']['skill']['skill_id'] for x in screen['results'] if x['candidate'])
    entry=next(e for e in base.read(PARENT/'candidate-catalog.json') if e['skill_id']==sid)
    if entry['contract']['status']!='VERIFIED':raise ValueError('reuse only VERIFIED original program')
    return entry


class Substitution:
    def __getattr__(self,name):return getattr(subprocess,name)
    def Popen(self,args,**kwargs):
        if args[1:]!=['-m','skillforge.interview_sprint.worker']:raise ValueError('unexpected worker')
        return subprocess.Popen([args[0],'-m','skillforge.skill_invocation.worker'],**kwargs)


class Session(base.SprintSession):
    __init__=old.bind(base.SprintSession.__init__,{'subprocess':Substitution()})


class Condition:
    def __init__(self,session,method,entry):self.session,self.method,self.entry,self.settings=session,method,entry,session.settings
    def send(self,packet):
        if packet['type']=='run':
            refs={} if self.method=='C' else {self.entry['skill_id']:{'revision':self.entry['revision'],'content_hash':self.entry['revision']}}
            packet={**packet,'public_start':{'observations':{},'loaded_refs':refs},'limits':{**packet['limits'],'mode':self.method}}
        self.session.send(packet)
    def receive(self,timeout=120):return self.session.receive(timeout)


def declare(root):
    root=root.resolve();root.mkdir(parents=True,exist_ok=False);entry=learned_entry()
    previous=base.read(PREVIOUS/'closeout-manifest.json')
    if previous['cumulative_model_tokens']!=1425483 or not previous['gpu_lease_released']:raise ValueError('closed prior cost ledger required')
    cases=[make_case(161001+i,'dev',v).model_dump() for i,v in enumerate(['instance','paraphrase','boundary'])]
    old_keys=set()
    for p in (ROOT/'results/interview-sprint').glob('*/source-ledger'):old_keys.update(SplitLedger(p).owners)
    ledger=SplitLedger(root/'source-ledger')
    for c in cases:
        keys=[c['source_group'],c['task_id'],c['parameters']['order_id'],c['fixture']['customer_id']]
        if old_keys.intersection(keys):raise ValueError('old source reused')
        ledger.claim(keys[0],'dev',related_groups=keys[1:])
    config=clone(base.read(PARENT/'protocol.json')['config'])
    sources=runtime.sources()
    historical={}
    for p in [PARENT/'report.json',PARENT/'candidate-catalog.json',PARENT/'program-admission.json',
              PREVIOUS/'closeout-manifest.json',ROOT/'docs/INTERVIEW_SPRINT_CLOSEOUT.md',
              ROOT/'docs/BOUNDARY_EVOLUTION_FORMAL_ENGINEERING.md']:
        historical[p.relative_to(ROOT).as_posix()]=digest_file(p)
    body={'schema':'contract-guided-invocation-protocol-v1','created_utc':now().isoformat(),'sprint_start_utc':START,'deadline_utc':DEADLINE,
        'max_hours':2,'prior_tokens':1425483,'max_combined_tokens':4000000,'prior_model_calls':476,'prior_real_arms':84,
        'parent_entry':entry,'catalog':base.read(PARENT/'candidate-catalog.json'),'config':config,'sources':sources,
        'historical_hashes':historical,'cases':cases,'methods':METHODS,
        'conditions':{'A':'original exact preloaded VERIFIED v1; original interface',
                      'B':'same exact preloaded VERIFIED v1; dynamic typed invocation tool',
                      'C':'public-request lexical recommendation and assisted preload; same typed tool'},
        'common_prompt':'unchanged CatalogModel original system prompt in all three arms; zero appended instructions',
        'order':[METHODS[i:]+METHODS[:i] for i in range(3)],
        'positive_dev':{'all_nine_eoc':True,'zero_actual_or_unexpected_attempted_violations':True,
            'B_all_three_structured_success':True,'B_vs_A_min_model_call_saving_each':1},
        'claim_policy':'EXPLORATORY DEV ONLY; no formal statistical significance, Agent Admission or activation',
        'prompt_variants':0,'candidate_variants':0,'new_training':False,'activated':False,
        'scope':'test interface and assisted candidate discovery, not new Skill generation or autonomous discovery'}
    p={**body,'hash':fingerprint(body)}
    for name,h in sources.items():
        dest=root/'source-snapshot'/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes((ROOT/name).read_bytes())
        if digest_file(dest)!=h:raise ValueError('source archive differs')
    base.publish(root/'protocol.json',p)
    return p


def check(protocol,*,inference=False):
    if fingerprint({k:v for k,v in protocol.items() if k!='hash'})!=protocol['hash']:raise ValueError('protocol changed')
    for name,h in {**protocol['sources'],**protocol['historical_hashes']}.items():
        if digest_file(ROOT/name)!=h:raise ValueError('frozen/historical source differs: '+name)
    if inference and now()>=datetime.fromisoformat(protocol['deadline_utc']):raise TimeoutError('two-hour hard deadline')


def run(root):
    from scripts.execution_aware_gpu_lease import GPUServiceLease
    root=root.resolve();p=base.read(root/'protocol.json');check(p,inference=True)
    config=clone(p['config']);config['budget']={'project_max_tokens':p['max_combined_tokens'],
        'project_max_wall_seconds':(datetime.fromisoformat(p['deadline_utc'])-now()).total_seconds()}
    if not base.read(root/'cpu-tests.json')['passed']:raise ValueError('CPU contract tests must pass first')
    base.publish(root/'registration.json',{'protocol_hash':p['hash'],'config':config,'prior_tokens':p['prior_tokens'],
        'started_utc':now().isoformat(),'no_budget_refill':True})
    catalog=Catalog(p['catalog']);statuses=[];rows=[];failure=None;started=time.perf_counter()
    collection=old.bind(base.old_collection.collect_one,{'verify_workflow':verify_workflow,'evaluate_static':safe_coverage,
        'prepare_snapshot':old.bind(base.original_prepare,{'run_agent':runtime.run_agent})})
    try:
        with GPUServiceLease(),ExitStack() as stack:
            session=Session(config,root);stack.callback(session.close)
            if session.settings!=base.read(PARENT/'model-identity.json'):raise ValueError('fixed original weights/prompt/settings required')
            base.publish(root/'model-identity.json',session.settings)
            for data,order in zip(p['cases'],p['order']):
                case=WorkflowCase.model_validate(data)
                for method in order:
                    check(p,inference=True);dest=root/'dev'/case.task_id/method
                    previous=p['prior_tokens']+sum(s['charged_tokens'] for s in statuses)
                    row,status=collection(Condition(session,method,p['parent_entry']),case,catalog,dest,config,previous,0,started)
                    statuses.append({**status,'method':method,'folder':dest.relative_to(root).as_posix()})
                    if row:rows.append({'method':method,'row':row})
                    print(json.dumps({'task':case.task_id,'method':method,'completed':status['completed'],
                        'eoc':row['verification']['task_success'] if row else None,'tokens':status['charged_tokens'],
                        'structured_success':sum(bool(t.get('success')) for t in row['agent']['invocation_adapter']['trace']) if row else 0}),flush=True)
                    if not status['completed']:raise RuntimeError(status['failure'])
    except Exception as exc:failure=type(exc).__name__+': '+str(exc)
    complete=not failure and len(rows)==9
    positive=complete and all(x['row']['verification']['task_success'] and not x['row']['verification']['actual_policy_violation'] and
        not x['row']['verification']['actual_workflow_violation'] and not x['row']['verification']['attempted_policy_violation'] and
        not base.forbidden_attempts(x['row']) for x in rows)
    if complete:
        for case in p['cases']:
            arms={x['method']:x['row'] for x in rows if x['row']['case']['task_id']==case['task_id']}
            positive=positive and any(t.get('success') for t in arms['B']['agent']['invocation_adapter']['trace']) and arms['A']['agent']['metrics']['llm_calls']-arms['B']['agent']['metrics']['llm_calls']>=1
    report={'schema':'contract-guided-invocation-report-v1','protocol_hash':p['hash'],'complete':complete,'failure':failure,
        'positive_dev':bool(positive),'candidate_count':1,'program_admission_inherited':True,'agent_admitted':False,'activated':False,
        'statuses':statuses,'charged_tokens':sum(s['charged_tokens'] for s in statuses),'prior_tokens':p['prior_tokens'],
        'combined_tokens':p['prior_tokens']+sum(s['charged_tokens'] for s in statuses),
        'model_calls':sum(x['row']['agent']['metrics']['llm_calls'] for x in rows),
        'business_tool_calls':sum(len(x['row']['tool_audit']) for x in rows),
        'static_coverage_tool_calls':sum(s['static_evaluation_tool_calls'] for s in statuses),
        'wall_seconds':time.perf_counter()-started,'gpu_utilization_hours':'UNMEASURED',
        'stop':'SAVE_EXPLORATORY_DEV_ONLY' if positive else 'STOP_NO_STRUCTURED_SUCCESS_OR_NO_COST_GAIN',
        'scope':p['scope']}
    base.publish(root/'report.json',report)
    print(json.dumps({k:report[k] for k in ['complete','failure','positive_dev','charged_tokens','combined_tokens','stop']}),flush=True)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['declare','run']);parser.add_argument('--output',type=Path,default=DEFAULT)
    args=parser.parse_args()
    if args.command=='declare':print(json.dumps({'protocol_hash':declare(args.output)['hash']}))
    else:run(args.output)
