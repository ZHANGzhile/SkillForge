"""One separately preregistered common input-binding instruction experiment."""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import json
import subprocess
import time

from scripts import run_interview_sprint as base
from scripts import run_interview_reference as previous
from scripts.continue_interview_sprint import safe_coverage
from scripts.run_skill_evolution import digest_file
from skillforge.environment import Environment
from skillforge.evolution_common.artifacts import clone, SplitLedger
from skillforge.evolution_schemas import fingerprint
from skillforge.interview_sprint import adapters as old_api
from skillforge.interview_sprint.workflows import GOAL, WorkflowCase, make_case, private_items, verify_workflow
from skillforge.interview_binding import runtime as new_api
from skillforge.interview_binding.model import SYSTEM_PROMPT
from skillforge.skill_evolution.admission import declare_paired_protocol, paired_gate

ROOT=base.ROOT
PARENT=previous.PARENT
PRIOR_DEV=previous.DEFAULT
DEFAULT=ROOT/'results/interview-sprint/binding-followup-20261013-v1'
METHODS=previous.METHODS
parent_metadata=previous.parent_metadata
catalogs=previous.catalogs
skill_success=previous.skill_success
unsafe=previous.unsafe


class WorkerSubstitution:
    def __getattr__(self,name):return getattr(subprocess,name)
    def Popen(self,args,**kwargs):
        if args[1:]!=['-m','skillforge.interview_sprint.worker']:raise ValueError('unexpected worker launch')
        return subprocess.Popen([args[0],'-m','skillforge.interview_binding.worker'],**kwargs)


class BindingSession(base.SprintSession):
    __init__=old_api.bind(base.SprintSession.__init__,{'subprocess':WorkerSubstitution()})


def now():return datetime.now(timezone.utc)


def declare(root):
    root=root.resolve();root.mkdir(parents=True,exist_ok=False)
    prior=base.read(PRIOR_DEV/'delivery-manifest.json');audit=base.read(PRIOR_DEV/'final-independent-audit.json')
    if prior['status']!='STOPPED_DEV_GATE_FAILED' or not audit['passed'] or prior['combined_model_tokens']!=1263669:
        raise ValueError('closed audited original cost ledger required')
    parent,entry,published,governance=parent_metadata()
    cases={
        'discovery_dev':[make_case(151001+i,'dev',v).model_dump() for i,v in enumerate(['instance','paraphrase','boundary'])],
        'validation':[make_case(152001+i,'validation',v).model_dump() for i,v in enumerate(['instance','instance','paraphrase','paraphrase','boundary','partial_payment'])],
        'stable_validation':[make_case(152101+i,'validation',workflow_id=w).model_dump() for i,w in enumerate(['shipment_summary','logistics_investigation'])],
        'test':[make_case(153001+i,'test',v).model_dump() for i,v in enumerate(['instance','instance','instance','paraphrase','paraphrase','boundary','partial_payment','unauthorized','missing'])],
        'stable_test':[make_case(153101+i,'test',workflow_id=w).model_dump() for i,w in enumerate(['shipment_summary','logistics_investigation'])]}
    program=[]
    for i,category in enumerate(['positive','positive','boundary','boundary','negative','negative','fault','fault']):
        c=make_case(150001+i,'dev','boundary' if category=='boundary' else 'instance')
        item={'case':c.model_dump(),'category':category,'stable':i==1}
        if category=='negative':
            item['expected_error']='permission_denied' if i==4 else 'not_found'
            item.update({'authenticated_customer_id':'IB13-OTHER'} if i==4 else {'parameters':{'order_id':'IB13-MISSING'}})
        if category=='fault':item.update(expected_error='timeout',faults={'get_payment' if i==6 else 'get_shipment':['timeout']})
        program.append(item)
    historical={}
    old_keys=set()
    for ledger_path in (ROOT/'results/interview-sprint').glob('*/source-ledger'):
        if ledger_path.parent==root:continue
        old_keys.update(SplitLedger(ledger_path).owners)
    ledger=SplitLedger(root/'source-ledger')
    for split,data in [*((k,c) for k,items in cases.items() for c in items),*(('discovery_dev',p['case']) for p in program)]:
        keys=[data['source_group'],data['task_id'],data['parameters']['order_id'],data['fixture']['customer_id']]
        if old_keys.intersection(keys):raise ValueError('new source/entity overlaps old study')
        ledger.claim(keys[0],'dev' if split=='discovery_dev' else split,related_groups=keys[1:])
    for p in (ROOT/'results/interview-sprint').glob('*/report.json'):
        historical[p.relative_to(ROOT).as_posix()]=digest_file(p)
    historical[(PRIOR_DEV/'metadata_dev/report.json').relative_to(ROOT).as_posix()]=digest_file(PRIOR_DEV/'metadata_dev/report.json')
    body={'schema':'interview-binding-plan-v1','created_utc':now().isoformat(),
        'original_sprint_start_utc':'2026-10-13T09:06:38+00:00','deadline_utc':'2026-10-13T16:06:38+00:00',
        'prior_charged_tokens':prior['combined_model_tokens'],'max_combined_tokens':4000000,
        'parent_entry':parent,'metadata_entry':entry,'published_entry':published,'governance':governance,
        'parent_program_admission_sha256':digest_file(PARENT/'program-admission.json'),
        'parent_main_report_sha256':digest_file(PARENT/'report.json'),
        'optimizer_feedback_dev_report_sha256':digest_file(PRIOR_DEV/'metadata_dev/report.json'),
        'optimizer_feedback_scope':'independent metadata dev only; old main validation/test not optimizer feedback',
        'prior_delivery_manifest_sha256':digest_file(PRIOR_DEV/'delivery-manifest.json'),
        'historical_report_hashes':historical,'sources':new_api.sources(),
        'config':base.read(PARENT/'protocol.json')['config'],'static_catalog':base.read(PARENT/'protocol.json')['static_catalog'],
        'cases':cases,'program_cases':program,'common_prompt':SYSTEM_PROMPT,'max_prompt_variants':1,
        'discovery_dev_gate':{'all_nine_eoc':True,'all_three_C_search_load_execute':True,'min_C_vs_B_call_saving_each':1,'zero_violations':True},
        'agent_gate':{'metric':'model_calls','min_group_gain':1,'min_groups':6,'alpha':0.05},
        'runtime_action_repair':False,'automatic_search_load':False,'candidate_count':1,'new_program_induced':False,
        'study_scale':'EXPLORATORY conditional on common explicit discovery/input-binding instruction; no significance claim',
        'activated':False,'new_training':False,'original_stopped_protocol_reopened':False}
    plan={**body,'hash':fingerprint(body)}
    for name,h in plan['sources'].items():
        dest=root/'source-snapshot'/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes((ROOT/name).read_bytes())
        if digest_file(dest)!=h:raise ValueError('source archive differs')
    base.publish(root/'plan.json',plan)
    f=old_api.validation_functions();vp=f['declare_protocol'](entry,GOAL.identity,program,ledger,mode='engineering')
    validation=f['validate_program'](entry,vp);proof=f['audit_validation'](validation)
    base.publish(root/'metadata-preflight-validation.json',validation);base.publish(root/'program-preflight-audit.json',proof)
    if not validation['engineering_passed'] or not proof['passed']:raise ValueError('no model calls after program preflight failure')
    return plan


def check(plan, *, check_deadline=True):
    if fingerprint({k:v for k,v in plan.items() if k!='hash'})!=plan['hash']:raise ValueError('plan changed')
    for name,h in {**plan['sources'],**plan['historical_report_hashes']}.items():
        if digest_file(ROOT/name)!=h:raise ValueError('frozen/historical file changed: '+name)
    if digest_file(PRIOR_DEV/'delivery-manifest.json')!=plan['prior_delivery_manifest_sha256']:raise ValueError('prior ledger changed')
    if check_deadline and now()>=datetime.fromisoformat(plan['deadline_utc']):raise TimeoutError('original seven-hour deadline')


def prior_tokens(root,plan,phase):
    if phase=='discovery_dev':return plan['prior_charged_tokens']
    dev=base.read(root/'discovery_dev/report.json')
    if not dev['complete'] or not dev['dev_gate_passed']:raise ValueError('dev failed; no formal expansion')
    return dev['combined_tokens']


def run_phase(root,phase):
    from scripts.execution_aware_gpu_lease import GPUServiceLease
    root=root.resolve();plan=base.read(root/'plan.json');check(plan);inherited=prior_tokens(root,plan,phase)
    if phase=='formal':
        formal=base.read(root/'formal-protocol.json')
        if formal['plan_hash']!=plan['hash']:raise ValueError('formal freeze differs')
    folder=root/phase;folder.mkdir(parents=True,exist_ok=False)
    config=clone(plan['config']);config['budget']={'project_max_tokens':plan['max_combined_tokens'],
        'project_max_wall_seconds':(datetime.fromisoformat(plan['deadline_utc'])-now()).total_seconds()}
    started=time.perf_counter();statuses=[];rows=[];audits=[];failure=None;gate=None
    library=catalogs(plan)
    collection=old_api.bind(base.old_collection.collect_one,{'verify_workflow':verify_workflow,'evaluate_static':safe_coverage,
        'prepare_snapshot':old_api.bind(base.original_prepare,{'run_agent':new_api.run_agent})})
    base.publish(folder/'registration.json',{'plan_hash':plan['hash'],'phase':phase,'config':config,
        'prior_charged_tokens':inherited,'started_utc':now().isoformat(),'deadline_utc':plan['deadline_utc'],'no_budget_refill':True})
    def collect(session,case,method,split):
        check(plan);previous_tokens=inherited+sum(s['charged_tokens'] for s in statuses);dest=folder/split/case.task_id/method
        row,status=collection(session,case,library[method],dest,config,previous_tokens,0,started)
        statuses.append({**status,'phase':split,'method':method,'folder':dest.relative_to(root).as_posix()})
        if not row:raise RuntimeError(status['failure'])
        proof=old_api.bind(base.audit_arm,{'api':new_api})(dest,case,library[method],session.settings,config['limits'],
            (previous_tokens,plan['max_combined_tokens'],0,config['budget']['project_max_wall_seconds']))
        audits.append(proof);rows.append({'phase':split,'method':method,'row':row})
        print(json.dumps({'phase':phase,'task':case.task_id,'method':method,'eoc':row['verification']['task_success'],
            'calls':row['agent']['metrics']['llm_calls'],'skill_success':skill_success(row,plan['published_entry']['skill_id'])}),flush=True)
        return row
    try:
        with GPUServiceLease(),ExitStack() as stack:
            session=BindingSession(config,folder);stack.callback(session.close)
            if session.settings['adapter_sha256']!=config['adapter_sha256'] or session.settings.get('engineering_only') is not False or session.settings['system_prompt']!=SYSTEM_PROMPT:
                raise ValueError('fixed real weights/common prompt required')
            if phase=='formal' and session.settings!=base.read(root/'discovery_dev/model-identity.json'):raise ValueError('formal model differs')
            base.publish(folder/'model-identity.json',session.settings)
            splits=['discovery_dev'] if phase=='discovery_dev' else ['validation','stable_validation','test','stable_test']
            pairs=[];index=0
            for split in splits:
                for data in plan['cases'][split]:
                    case=WorkflowCase.model_validate(data);arms={};public_split='dev' if phase=='discovery_dev' else 'validation' if split in ['validation','stable_validation'] else 'heldout'
                    for method in METHODS[index%3:]+METHODS[:index%3]:arms[method]=collect(session,case,method,public_split)
                    if public_split=='validation':
                        expected=formal['paired_protocol']['cases'][len(pairs)]
                        def arm(method):
                            row=arms[method];v=row['verification'];m=row['agent']['metrics']
                            return {'eoc':v['task_success'],'attempted_violations':int(v['attempted_policy_violation'])+base.forbidden_attempts(row),
                                'actual_violations':int(v['actual_policy_violation']),'workflow_violations':int(v['actual_workflow_violation']),
                                'model_calls':m['llm_calls'],'tokens':m['tokens'],'cost_settled':True,'execution_identity':formal['execution_identity'],
                                'catalog_hash':library[method].hash,'evidence_hash':fingerprint(row)}
                        pairs.append({**{k:v for k,v in expected.items() if k not in {'split','critical'}},'baseline':arm('StaticLibrary'),'candidate':arm('ExperienceEvolution')})
                    index+=1
                if split=='stable_validation':
                    gate=paired_gate(formal['paired_protocol'],pairs);base.publish(folder/'agent-paired-gate.json',gate)
    except Exception as exc:failure=type(exc).__name__+': '+str(exc)
    complete=not failure and len(rows)==(9 if phase=='discovery_dev' else 57)
    passed=False
    if complete and phase=='discovery_dev':
        passed=all(x['row']['verification']['task_success'] and not unsafe(x['row']) for x in rows)
        for data in plan['cases']['discovery_dev']:
            group={x['method']:x['row'] for x in rows if x['row']['case']['task_id']==data['task_id']}
            b,c=group['StaticLibrary'],group['ExperienceEvolution']
            passed=passed and skill_success(c,plan['published_entry']['skill_id']) and bool(c['agent']['search_events']) and bool(c['agent']['load_events']) and b['agent']['metrics']['llm_calls']-c['agent']['metrics']['llm_calls']>=1
    result={'schema':'interview-binding-phase-report-v1','phase':phase,'plan_hash':plan['hash'],'complete':complete,'failure':failure,
        'dev_gate_passed':bool(passed),'agent_gate_passed':bool(gate and gate['statistical_gate_passed']),
        'agent_admitted':False,'activated':False,'charged_tokens':sum(s['charged_tokens'] for s in statuses),
        'inherited_charged_tokens':inherited,'combined_tokens':inherited+sum(s['charged_tokens'] for s in statuses),
        'model_calls':sum(x['row']['agent']['metrics']['llm_calls'] for x in rows),'tool_calls':sum(len(x['row']['tool_audit']) for x in rows),
        'static_coverage_tool_calls':sum(s['static_evaluation_tool_calls'] for s in statuses),
        'recorded_response_audit_tool_calls':sum(a['replay_tool_calls'] for a in audits),'wall_seconds':time.perf_counter()-started,
        'statuses':statuses,'audits':audits,'correct_skill_executions':sum(skill_success(x['row'],plan['published_entry']['skill_id']) for x in rows),
        'scope':plan['study_scale']}
    base.publish(folder/'report.json',result)
    base.summarize(folder,{'status':'COMPLETE' if complete else 'FAILED_OR_INCOMPLETE','candidate_count':1,'program_admitted':True,
        'agent_admitted':False,'failure':failure,'costs':{k:result[k] for k in ['charged_tokens','combined_tokens','model_calls','tool_calls','wall_seconds']}},rows)
    print(json.dumps({k:result[k] for k in ['phase','complete','failure','dev_gate_passed','agent_gate_passed','charged_tokens','combined_tokens','correct_skill_executions']}),flush=True)
    return result


def freeze(root):
    root=root.resolve();plan=base.read(root/'plan.json');check(plan);prior=prior_tokens(root,plan,'formal')
    dev_proof=base.read(root/'dev-independent-audit.json')
    if not dev_proof['passed'] or dev_proof['plan_hash']!=plan['hash'] or dev_proof['completed_arms']!=9 or dev_proof['phases'][0]['report_sha256']!=digest_file(root/'discovery_dev/report.json'):
        raise ValueError('independent dev audit required before formal freeze')
    f=old_api.validation_functions();validation=base.read(root/'metadata-preflight-validation.json');audit=f['audit_validation'](validation)
    if not validation['engineering_passed'] or not audit['passed']:raise ValueError('program checks failed')
    inheritance={'parent_admission_sha256':plan['parent_program_admission_sha256'],'child_entry':plan['published_entry'],
        'independent_new_program_checks':validation,'checks_audit':audit,'decision':'INHERITS_UNCHANGED_PROGRAM_ADMISSION'}
    base.publish(root/'metadata-program-admission.json',{**inheritance,'hash':fingerprint(inheritance)})
    settings=base.read(root/'discovery_dev/model-identity.json');execution=fingerprint({'model':settings,'sources':plan['sources'],'limits':plan['config']['limits']})
    cases=[]
    for split in ['validation','stable_validation']:
        for data in plan['cases'][split]:
            c=WorkflowCase.model_validate(data);env=Environment(fixture=c.fixture)
            try:initial=fingerprint({'state':env.snapshot(),'items':private_items(env),'auth':c.authenticated_customer_id})
            finally:env.close()
            cases.append({'task_id':c.task_id,'source_group':c.source_group,'task_hash':fingerprint(data),'initial_state_hash':initial,'split':split})
    library=catalogs(plan);paired=declare_paired_protocol(cases,baseline_catalog_hash=library['StaticLibrary'].hash,
        candidate_catalog_hash=library['ExperienceEvolution'].hash,execution_identity=execution,**plan['agent_gate'])
    body={'schema':'interview-binding-formal-protocol-v1','plan_hash':plan['hash'],'sources':plan['sources'],
        'execution_identity':execution,'paired_protocol':paired,'methods':METHODS,
        'all_cases':{k:plan['cases'][k] for k in ['validation','stable_validation','test','stable_test']},
        'discovery_dev_report_sha256':digest_file(root/'discovery_dev/report.json'),'prior_charged_tokens':prior,
        'dev_independent_audit_sha256':digest_file(root/'dev-independent-audit.json'),
        'max_combined_tokens':plan['max_combined_tokens'],'deadline_utc':plan['deadline_utc'],
        'study_scale':plan['study_scale'],'model_prompt':SYSTEM_PROMPT,'automatic_runtime_search_load':False,'activated':False}
    formal={**body,'hash':fingerprint(body)};base.publish(root/'formal-protocol.json',formal);return formal


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['declare','discovery_dev','freeze','formal']);parser.add_argument('--output',type=Path,default=DEFAULT)
    args=parser.parse_args()
    if args.command=='declare':print(json.dumps({'plan_hash':declare(args.output)['hash']}))
    elif args.command=='freeze':print(json.dumps({'protocol_hash':freeze(args.output)['hash']}))
    else:run_phase(args.output,args.command)
