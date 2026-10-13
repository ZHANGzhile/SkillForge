"""Separate predeclared dev diagnostic: same catalog, exact Skill preload only.

This cannot change main candidate, validation threshold, held-out data or Agent
admission. A positive result is conditional execution after supplied availability,
NOT autonomous retrieval or a rescue of the main experiment's effect estimate.
"""
import argparse
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from types import SimpleNamespace
import json
import time

from skillforge.evolution_common.artifacts import SplitLedger
from skillforge.evolution_schemas import fingerprint
from skillforge.skill_evolution.catalog import Catalog
from skillforge.interview_sprint import adapters as api
from skillforge.interview_sprint.workflows import make_case, WorkflowCase
from scripts.run_interview_sprint import ROOT, read, publish, SprintSession, collect_one, audit_arm, check_sources
from scripts.run_skill_evolution import digest_file


def declare(root, main):
    root, main = root.resolve(), main.resolve(); root.mkdir(parents=True,exist_ok=False)
    protocol = read(main/'protocol.json'); check_sources(protocol)
    admission = read(main/'program-admission.json')
    if admission['decision'] != 'ADMITTED': raise ValueError('a validated real-trace candidate is required')
    catalog = Catalog(read(main/'candidate-catalog.json')); old = {e['revision'] for e in protocol['static_catalog']}
    candidate = [e for e in catalog.entries() if e['revision'] not in old]
    if len(candidate)!=1: raise ValueError('exactly one unchanged candidate required')
    cases = [make_case(136001+i,'dev',variant).model_dump() for i,variant in enumerate(['instance','paraphrase','boundary'])]
    ledger = SplitLedger(root/'source-ledger')
    for data in cases:
        case = WorkflowCase.model_validate(data)
        ledger.claim(case.source_group,'dev',related_groups=[case.task_id,case.parameters['order_id'],case.fixture['customer_id']])
    body = {'schema':'interview-availability-diagnostic-v1','created_utc':datetime.now(timezone.utc).isoformat(),
        'main_run':main.relative_to(ROOT).as_posix(),'main_protocol_hash':protocol['hash'],
        'candidate_revision':candidate[0]['revision'],'candidate_skill_id':candidate[0]['skill_id'],
        'program_admission_sha256':digest_file(main/'program-admission.json'),'catalog':catalog.entries(),'catalog_hash':catalog.hash,
        'cases':cases,'limits':protocol['config']['limits'],'sources':protocol['sources'],
        'diagnostic_source_sha256':digest_file(__file__),'deadline_utc':protocol['deadline_utc'],
        'contrast':'WITHHELD versus PRELOADED exact new Skill; same complete catalog, model, public task, tools, initial DB and budgets',
        'hypothesis':'If natural retrieval is absent, supplied availability may reveal whether fixed main-v3 can execute the learned program',
        'discovery':'Both retain identical discovery budgets; no model call is counted for explicit experimenter preload',
        'scope':'three new dev sources, diagnostic only; cannot rescue main Agent admission or establish autonomous retrieval efficacy',
        'no_candidate_or_prompt_changes':True,'no_activation':True}
    value={**body,'hash':fingerprint(body)};publish(root/'protocol.json',value)
    return value


class AvailabilitySession:
    def __init__(self,session,start):self.session,self.start,self.settings=session,start,session.settings
    def send(self,packet):
        if packet['type']=='run': packet={**packet,'public_start':self.start}
        return self.session.send(packet)
    def receive(self,timeout=120):return self.session.receive(timeout)


def run(root):
    from scripts.execution_aware_gpu_lease import GPUServiceLease
    root=root.resolve(); protocol=read(root/'protocol.json');main=ROOT/protocol['main_run']
    deadline=datetime.fromisoformat(protocol['deadline_utc'])
    while not (main/'report.json').exists() or (ROOT/'.runtime/active-evolution-gpu-lease.json').exists():
        if datetime.now(timezone.utc)>=deadline: raise TimeoutError('seven-hour deadline before diagnostic')
        time.sleep(15)
    main_report=read(main/'report.json')
    if main_report['status']!='COMPLETE':raise ValueError('main collection incomplete; no further inference')
    if digest_file(__file__)!=protocol['diagnostic_source_sha256']:raise ValueError('diagnostic source changed')
    check_sources(read(main/'protocol.json'))
    if (root/'run-registration.json').exists():raise ValueError('no implicit retry/refill')
    config=read(main/'protocol.json')['config'];config['budget']['project_max_wall_seconds']=(deadline-datetime.now(timezone.utc)).total_seconds()
    prior=main_report['costs']['charged_tokens'];catalog=Catalog(protocol['catalog']);rows=[];statuses=[];audits=[];failure=None
    publish(root/'run-registration.json',{'main_report_sha256':digest_file(main/'report.json'),'prior_charged_tokens':prior,
        'max_combined_tokens':config['budget']['project_max_tokens'],'protocol_hash':protocol['hash'],'config':config})
    started=time.perf_counter()
    try:
        with GPUServiceLease():
            session=SprintSession(config,root)
            try:
                publish(root/'model-identity.json',session.settings)
                if session.settings!=read(main/'model-identity.json'):raise ValueError('model/settings differ from main')
                for i,data in enumerate(protocol['cases']):
                    case=WorkflowCase.model_validate(data)
                    for method in (['WITHHELD','PRELOADED'] if i%2==0 else ['PRELOADED','WITHHELD']):
                        start={'observations':{},'loaded_refs':({protocol['candidate_skill_id']:{'revision':protocol['candidate_revision'],
                            'content_hash':protocol['candidate_revision']}} if method=='PRELOADED' else {})}
                        wrapped=AvailabilitySession(session,start);folder=root/case.task_id/method
                        previous=prior+sum(s['charged_tokens'] for s in statuses)
                        row,status=collect_one(wrapped,case,catalog,folder,config,previous,0,started)
                        statuses.append({**status,'method':method})
                        if not row:raise RuntimeError(status['failure'])
                        adapted=SimpleNamespace(run_agent=partial(api.run_agent,public_start=start))
                        receipt=api.bind(audit_arm,{'api':adapted})(folder,case,catalog,session.settings,config['limits'],
                            (previous,config['budget']['project_max_tokens'],0,config['budget']['project_max_wall_seconds']))
                        audits.append(receipt);rows.append({'method':method,'row':row})
                        print(json.dumps({'method':method,'task':case.task_id,'eoc':row['verification']['task_success'],
                            'calls':row['agent']['metrics']['llm_calls'],'skill_events':len(row['agent']['skill_events'])}),flush=True)
            finally:session.close()
    except Exception as exc:failure=type(exc).__name__+': '+str(exc)
    report={'schema':'interview-availability-result-v1','protocol_hash':protocol['hash'],'complete':len(rows)==6 and not failure,'failure':failure,
        'statuses':statuses,'audits':audits,'charged_tokens':sum(s['charged_tokens'] for s in statuses),
        'static_coverage_tool_calls':sum(s['static_evaluation_tool_calls'] for s in statuses),
        'recorded_response_audit_tool_calls':sum(a['replay_tool_calls'] for a in audits),
        'combined_tokens':prior+sum(s['charged_tokens'] for s in statuses),'wall_seconds':time.perf_counter()-started,
        'research_claim_passed':None,'main_agent_admission_unchanged':main_report['agent_admitted'],
        'scope':'conditional preload diagnostic only; not autonomous retrieval benefit or main Agent admission'}
    metrics=[]
    for method in ['WITHHELD','PRELOADED']:
        values=[x['row'] for x in rows if x['method']==method]
        metrics.append({'method':method,'n':len(values),'eoc':sum(v['verification']['task_success'] for v in values),
            'autonomous_eoc':sum(v['verification']['task_success'] and v['agent']['termination_source']=='model' and v['agent']['interventions']['runtime_intervention_count']==0 for v in values),
            'model_calls':sum(v['agent']['metrics']['llm_calls'] for v in values),'tokens':sum(v['agent']['metrics']['tokens'] for v in values),
            'tools':sum(v['agent']['metrics']['tool_calls'] for v in values),'search':sum(v['agent']['metrics']['search_calls'] for v in values),
            'load':sum(v['agent']['metrics']['load_calls'] for v in values),'skill_selected':sum(len(v['agent']['skill_events']) for v in values),
            'skill_success':sum(e['success'] for v in values for e in v['agent']['skill_events'])})
    pair_checks=[]
    for data in protocol['cases']:
        pair={x['method']:x['row'] for x in rows if x['row']['case']['task_id']==data['task_id']}
        if set(pair)!={'WITHHELD','PRELOADED'}:continue
        from skillforge.evolution_common.artifacts import clone
        left=clone(pair['WITHHELD']['agent']['steps'][0]['context']);right=clone(pair['PRELOADED']['agent']['steps'][0]['context'])
        empty=left['catalog'].pop('loaded_skills');loaded=right['catalog'].pop('loaded_skills')
        if left!=right or empty or len(loaded)!=1 or loaded[0]['revision']!=protocol['candidate_revision']:
            raise ValueError('initial contexts differ beyond predeclared preload')
        if pair['WITHHELD']['initial_state']!=pair['PRELOADED']['initial_state'] or pair['WITHHELD']['initial_items']!=pair['PRELOADED']['initial_items']:
            raise ValueError('initial facts differ across availability pair')
        pair_checks.append({'task_id':data['task_id'],'equal_context_except_loaded':True,
            'withheld_calls':pair['WITHHELD']['agent']['metrics']['llm_calls'],'preloaded_calls':pair['PRELOADED']['agent']['metrics']['llm_calls'],
            'joint_eoc':pair['WITHHELD']['verification']['task_success'] and pair['PRELOADED']['verification']['task_success']})
    report['pairs']=pair_checks;report['metrics']=metrics;publish(root/'report.json',report)
    print(json.dumps(report),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['declare','run'])
    parser.add_argument('--output',type=Path,default=Path('results/interview-sprint/availability-dev-20261013-v1'))
    parser.add_argument('--main',type=Path,default=Path('results/interview-sprint/20261013-v3'));args=parser.parse_args()
    if args.command=='declare':print(json.dumps({'protocol_hash':declare(args.output,args.main)['hash']}))
    else:run(args.output)
