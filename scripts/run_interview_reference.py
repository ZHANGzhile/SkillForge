"""One bounded metadata/prompt follow-up; original results and criteria retained."""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from types import SimpleNamespace
import json
import subprocess
import time

from skillforge.environment import Environment
from skillforge.evolution_common.artifacts import clone, SplitLedger, record
from skillforge.evolution_schemas import fingerprint
from skillforge.skill_evolution.catalog import Catalog, revision
from skillforge.skill_evolution.registry import verified_publication
from skillforge.skill_evolution.governance import governed_revision, identities, RevisionMemory
from skillforge.skill_evolution.admission import declare_paired_protocol, paired_gate
from skillforge.interview_sprint import adapters as old_api
from skillforge.interview_sprint.workflows import WorkflowCase, GOAL, make_case, private_items, verify_workflow
from skillforge.interview_reference import runtime as new_api
from skillforge.interview_reference.model import SYSTEM_PROMPT
from scripts import run_interview_sprint as base
from scripts.continue_interview_sprint import safe_coverage
from scripts.run_skill_evolution import digest_file

ROOT=base.ROOT
DEFAULT=ROOT/'results/interview-sprint/reference-followup-20261013-v1'
PARENT=ROOT/'results/interview-sprint/20261013-v4'
PRIOR_DEV=ROOT/'results/interview-sprint/availability-dev-20261013-v2'
METHODS=['PrimitiveOnly','StaticLibrary','ExperienceEvolution']


class WorkerSubstitution:
    """Only substitute the known worker module; preserve original process flags."""
    def __getattr__(self,name):return getattr(subprocess,name)
    def Popen(self,args,**kwargs):
        if args[1:]!=['-m','skillforge.interview_sprint.worker']:raise ValueError('unexpected worker launch')
        return subprocess.Popen([args[0],'-m','skillforge.interview_reference.worker'],**kwargs)


class ReferenceSession(base.SprintSession):
    __init__=old_api.bind(base.SprintSession.__init__,{'subprocess':WorkerSubstitution()})


class StartSession:
    def __init__(self,session,start):self.session,self.start,self.settings=session,start,session.settings
    def send(self,packet):
        if packet['type']=='run' and self.start is not None:packet={**packet,'public_start':self.start}
        self.session.send(packet)
    def receive(self,timeout=120):return self.session.receive(timeout)


def parent_metadata():
    proof=base.read(PARENT/'final-independent-audit.json');report=base.read(PARENT/'report.json')
    if not proof['passed'] or proof['report_sha256']!=digest_file(PARENT/'report.json') or not report['program_admitted']:
        raise ValueError('audited real-trace parent required')
    candidate=next(r['candidate'] for r in base.read(PARENT/'candidate-screen.json')['results'] if r['candidate'])
    parent=next(e for e in base.read(PARENT/'candidate-catalog.json') if e['skill_id']==candidate['skill']['skill_id'])
    contract=clone(parent['contract']);contract['version']+=1;contract['status']='CANDIDATE'
    entry=revision(contract,name=contract['skill_id'],description=parent['description'],support_domain=parent['support_domain'],parent_revision=parent['revision'])
    governance=governed_revision(entry,goal_hash=GOAL.identity,revision_kind='metadata_revision',parent=parent)
    publication=verified_publication(entry)
    for key,value in parent['contract'].items():
        if key not in {'version','status'} and contract[key]!=value:raise ValueError('metadata changed executable contract')
    if identities(publication['contract'],GOAL.identity)!=identities(parent['contract'],GOAL.identity):
        raise ValueError('metadata revision changed program/boundary semantics')
    return parent,entry,publication,governance


def now():return datetime.now(timezone.utc)


def declare(root):
    root=root.resolve();root.mkdir(parents=True,exist_ok=False)
    parent,entry,publication,governance=parent_metadata();prior=base.read(PRIOR_DEV/'report.json')
    if not prior['complete'] or prior['combined_tokens']!=1042947:raise ValueError('closed prior model ledger required')
    old_api.validation_functions()['audit_program_admission'](base.read(PARENT/'program-admission.json'))
    source_ids=new_api.sources()
    cases={
        'metadata_dev':[make_case(137001+i,'dev',v).model_dump() for i,v in enumerate(['instance','paraphrase','boundary'])],
        'discovery_dev':[make_case(138001+i,'dev',v).model_dump() for i,v in enumerate(['instance','paraphrase','boundary'])],
        'validation':[make_case(141001+i,'validation',v).model_dump() for i,v in enumerate(['instance','instance','paraphrase','paraphrase','boundary','partial_payment'])],
        'stable_validation':[make_case(141101+i,'validation',workflow_id=w).model_dump() for i,w in enumerate(['shipment_summary','logistics_investigation'])],
        'test':[make_case(142001+i,'test',v).model_dump() for i,v in enumerate(['instance','instance','instance','paraphrase','paraphrase','boundary','partial_payment','unauthorized','missing'])],
        'stable_test':[make_case(142101+i,'test',workflow_id=w).model_dump() for i,w in enumerate(['shipment_summary','logistics_investigation'])]}
    program=[]
    for i,category in enumerate(['positive','positive','boundary','boundary','negative','negative','fault','fault']):
        case=make_case(140001+i,'dev','boundary' if category=='boundary' else 'instance')
        item={'case':case.model_dump(),'category':category,'stable':i==1}
        if category=='negative':
            item.update(expected_error='permission_denied' if i==4 else 'not_found')
            if i==4:item['authenticated_customer_id']='IR13-OTHER'
            else:item['parameters']={'order_id':'IR13-MISSING'}
        if category=='fault':item.update(expected_error='timeout',faults={'get_payment' if i==6 else 'get_shipment':['timeout']})
        program.append(item)
    ledger=SplitLedger(root/'source-ledger')
    for split,items in cases.items():
        for data in items:
            partition='dev' if split.endswith('_dev') else split
            ledger.claim(data['source_group'],partition,related_groups=[data['task_id'],data['parameters']['order_id'],data['fixture']['customer_id']])
    for item in program:
        c=item['case'];ledger.claim(c['source_group'],'dev',related_groups=[c['task_id'],c['parameters']['order_id'],c['fixture']['customer_id']])
    # Only the prior explicitly dev feedback may enter revision memory.
    for c in base.read(PRIOR_DEV/'protocol.json')['cases']:
        ledger.claim(c['source_group'],'dev',related_groups=[c['task_id'],c['parameters']['order_id'],c['fixture']['customer_id']])
    body={'schema':'interview-reference-followup-plan-v1','created_utc':now().isoformat(),
        'deadline_utc':'2026-10-13T16:06:38+00:00','original_sprint_start_utc':'2026-10-13T09:06:38+00:00',
        'prior_charged_tokens':prior['combined_tokens'],'max_combined_tokens':4000000,
        'parent_main_report_sha256':digest_file(PARENT/'report.json'),'parent_program_admission_sha256':digest_file(PARENT/'program-admission.json'),
        'optimizer_feedback_dev_report_sha256':digest_file(PRIOR_DEV/'report.json'),'optimizer_feedback_scope':'prior dev availability only; no main validation/test feedback used for revision selection',
        'parent_entry':parent,'metadata_entry':entry,'published_entry':publication,'governance':governance,
        'sources':source_ids,'config':base.read(PARENT/'protocol.json')['config'],'static_catalog':base.read(PARENT/'protocol.json')['static_catalog'],
        'cases':cases,'program_cases':program,'common_prompt':SYSTEM_PROMPT,
        'metadata_dev_gate':{'all_three_sources_eoc_and_correct_skill':True,'min_call_saving_each':1,'zero_violations':True},
        'discovery_dev_gate':{'all_nine_eoc':True,'all_three_C_search_load_execute':True,'min_C_vs_B_call_saving_each':1,'zero_violations':True},
        'agent_gate':{'metric':'model_calls','min_group_gain':1,'min_groups':6,'alpha':0.05},
        'max_metadata_variants':1,'max_prompt_variants':1,'no_alias_resolution_or_action_repair':True,
        'candidate_count_remains':1,'program_change':False,'new_training':False,'activated':False,
        'study_scale':'EXPLORATORY; conditional on one common instructed discovery policy; no statistical significance claim',
        'scope':'metadata-reference dev, then common-prompt discovery dev, then independent frozen three-arm validation/test only if both dev gates pass'}
    protocol={**body,'hash':fingerprint(body)}
    for name,h in source_ids.items():
        target=root/'source-snapshot'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((ROOT/name).read_bytes())
        if digest_file(target)!=h:raise ValueError('source archive differs')
    base.publish(root/'plan.json',protocol)
    for name,value in [('candidate-metadata.json',entry),('published-metadata.json',publication),('metadata-governance.json',governance)]:base.publish(root/name,value)
    return protocol


def check(plan):
    if fingerprint({k:v for k,v in plan.items() if k!='hash'})!=plan['hash']:raise ValueError('plan hash differs')
    for name,h in plan['sources'].items():
        if digest_file(ROOT/name)!=h:raise ValueError('frozen follow-up source changed: '+name)
    if digest_file(PARENT/'report.json')!=plan['parent_main_report_sha256'] or digest_file(PRIOR_DEV/'report.json')!=plan['optimizer_feedback_dev_report_sha256']:
        raise ValueError('old original reports changed')
    if now()>=datetime.fromisoformat(plan['deadline_utc']):raise TimeoutError('original seven-hour deadline')


def prior_tokens(root,plan,phase):
    total=plan['prior_charged_tokens']
    for previous in ['metadata_dev','discovery_dev','formal']:
        if previous==phase:break
        value=base.read(root/previous/'report.json')
        if not value['complete']:raise ValueError('incomplete prior phase cannot refill/retry')
        total+=value['charged_tokens']
    return total


def catalogs(plan):
    return {'PrimitiveOnly':Catalog([]),'StaticLibrary':Catalog(plan['static_catalog']),
        'ExperienceEvolution':Catalog([*plan['static_catalog'],plan['published_entry']]),
        'OldName':Catalog([*plan['static_catalog'],plan['parent_entry']]),
        'ExactName':Catalog([*plan['static_catalog'],plan['published_entry']])}


def skill_success(row,skill_id):
    return any(e['skill_id']==skill_id and e['success'] for e in row['agent']['skill_events'])


def unsafe(row):
    v=row['verification']
    return bool(v['actual_policy_violation'] or v['actual_workflow_violation'] or base.forbidden_attempts(row))


def run_phase(root,phase):
    from scripts.execution_aware_gpu_lease import GPUServiceLease
    root=root.resolve();plan=base.read(root/'plan.json');check(plan)
    if phase!='metadata_dev':
        previous='metadata_dev' if phase=='discovery_dev' else 'discovery_dev'
        if not base.read(root/previous/'report.json')['dev_gate_passed']:raise ValueError('previous dev gate did not pass; stop without further variants')
    folder=root/phase;folder.mkdir(parents=True,exist_ok=False)
    if phase=='formal':
        formal=base.read(root/'formal-protocol.json')
        if formal['plan_hash']!=plan['hash']:raise ValueError('formal protocol differs')
    config=clone(plan['config']);config['budget']={'project_max_tokens':plan['max_combined_tokens'],
        'project_max_wall_seconds':(datetime.fromisoformat(plan['deadline_utc'])-now()).total_seconds()}
    inherited=prior_tokens(root,plan,phase);started=time.perf_counter();statuses=[];rows=[];audits=[];failure=None
    mode=old_api if phase=='metadata_dev' else new_api
    runtime_fn=mode.run_agent;collection=old_api.bind(base.old_collection.collect_one,{'verify_workflow':verify_workflow,
        'evaluate_static':safe_coverage,'prepare_snapshot':old_api.bind(base.original_prepare,{'run_agent':runtime_fn})})
    library=catalogs(plan)
    base.publish(folder/'registration.json',{'plan_hash':plan['hash'],'phase':phase,'prior_charged_tokens':inherited,'config':config,
        'deadline_utc':plan['deadline_utc'],'no_budget_refill':True,'started_utc':now().isoformat()})
    def collect(session,case,method,split):
        check(plan);cat=library[method];start=None
        if phase=='metadata_dev':
            entry=plan['parent_entry'] if method=='OldName' else plan['published_entry']
            start={'observations':{},'loaded_refs':{entry['skill_id']:{'revision':entry['revision'],'content_hash':entry['revision']}}}
        previous=inherited+sum(s['charged_tokens'] for s in statuses);dest=folder/split/case.task_id/method
        row,status=collection(StartSession(session,start),case,cat,dest,config,previous,0,started)
        statuses.append({**status,'phase':split,'method':method,'folder':dest.relative_to(root).as_posix()})
        if not row:raise RuntimeError(status['failure'])
        verifier=old_api.bind(base.audit_arm,{'api':SimpleNamespace(run_agent=partial(runtime_fn,public_start=start))})
        receipt=verifier(dest,case,cat,session.settings,config['limits'],
            (previous,plan['max_combined_tokens'],0,config['budget']['project_max_wall_seconds']))
        audits.append(receipt);rows.append({'phase':split,'method':method,'row':row})
        print(json.dumps({'phase':phase,'split':split,'task':case.task_id,'method':method,'eoc':row['verification']['task_success'],
            'calls':row['agent']['metrics']['llm_calls'],'skill_success':skill_success(row,plan['published_entry']['skill_id'])}),flush=True)
        return row
    gate=None
    try:
        with GPUServiceLease(),ExitStack() as stack:
            session=(base.SprintSession if phase=='metadata_dev' else ReferenceSession)(config,folder);stack.callback(session.close)
            if session.settings['adapter_sha256']!=config['adapter_sha256'] or session.settings.get('engineering_only') is not False:
                raise ValueError('fixed real main-v3 required')
            if phase=='metadata_dev' and session.settings!=base.read(PARENT/'model-identity.json'):
                raise ValueError('metadata-only comparison changed model or prompt')
            if phase!='metadata_dev' and session.settings['system_prompt']!=SYSTEM_PROMPT:
                raise ValueError('common discovery prompt differs')
            if phase=='formal' and session.settings!=base.read(root/'discovery_dev/model-identity.json'):
                raise ValueError('formal model settings differ from frozen dev selection')
            base.publish(folder/'model-identity.json',session.settings)
            if phase=='metadata_dev':
                for i,data in enumerate(plan['cases'][phase]):
                    for method in (['OldName','ExactName'] if i%2==0 else ['ExactName','OldName']):collect(session,WorkflowCase.model_validate(data),method,'dev')
            elif phase=='discovery_dev':
                for i,data in enumerate(plan['cases'][phase]):
                    for method in METHODS[i%3:]+METHODS[:i%3]:collect(session,WorkflowCase.model_validate(data),method,'dev')
            else:
                pairs=[]
                for i,data in enumerate(plan['cases']['validation']+plan['cases']['stable_validation']):
                    case=WorkflowCase.model_validate(data);arms={}
                    for method in METHODS[i%3:]+METHODS[:i%3]:arms[method]=collect(session,case,method,'validation')
                    expected=formal['paired_protocol']['cases'][i]
                    def arm(method):
                        row=arms[method];v=row['verification'];m=row['agent']['metrics']
                        return {'eoc':v['task_success'],'attempted_violations':int(v['attempted_policy_violation'])+base.forbidden_attempts(row),
                            'actual_violations':int(v['actual_policy_violation']),'workflow_violations':int(v['actual_workflow_violation']),
                            'model_calls':m['llm_calls'],'tokens':m['tokens'],'cost_settled':True,'execution_identity':formal['execution_identity'],
                            'catalog_hash':library[method].hash,'evidence_hash':fingerprint(row)}
                    pairs.append({**{k:v for k,v in expected.items() if k not in {'split','critical'}},'baseline':arm('StaticLibrary'),'candidate':arm('ExperienceEvolution')})
                gate=paired_gate(formal['paired_protocol'],pairs);base.publish(folder/'agent-paired-gate.json',gate)
                for i,data in enumerate(plan['cases']['test']+plan['cases']['stable_test']):
                    for method in METHODS[i%3:]+METHODS[:i%3]:collect(session,WorkflowCase.model_validate(data),method,'heldout')
    except Exception as exc:failure=type(exc).__name__+': '+str(exc)
    planned=6 if phase=='metadata_dev' else 9 if phase=='discovery_dev' else 57
    complete=not failure and len(rows)==planned
    dev_passed=False
    if complete and phase!='formal':
        by_task={}
        for item in rows:by_task.setdefault(item['row']['case']['task_id'],{})[item['method']]=item['row']
        dev_passed=all(r['row']['verification']['task_success'] and not unsafe(r['row']) for r in rows)
        for group in by_task.values():
            a,b=(group['OldName'],group['ExactName']) if phase=='metadata_dev' else (group['StaticLibrary'],group['ExperienceEvolution'])
            dev_passed=dev_passed and skill_success(b,plan['published_entry']['skill_id']) and a['agent']['metrics']['llm_calls']-b['agent']['metrics']['llm_calls']>=1
            if phase=='discovery_dev':dev_passed=dev_passed and bool(b['agent']['search_events']) and bool(b['agent']['load_events'])
    result={'schema':'interview-reference-phase-report-v1','phase':phase,'plan_hash':plan['hash'],'complete':complete,'failure':failure,
        'dev_gate_passed':bool(dev_passed),'agent_gate_passed':bool(gate and gate['statistical_gate_passed']),
        'agent_admitted':False,'activated':False,'research_claim_passed':None,'charged_tokens':sum(s['charged_tokens'] for s in statuses),
        'inherited_charged_tokens':inherited,'combined_tokens':inherited+sum(s['charged_tokens'] for s in statuses),
        'model_calls':sum(x['row']['agent']['metrics']['llm_calls'] for x in rows),'tool_calls':sum(len(x['row']['tool_audit']) for x in rows),
        'static_coverage_tool_calls':sum(s['static_evaluation_tool_calls'] for s in statuses),
        'recorded_response_audit_tool_calls':sum(a['replay_tool_calls'] for a in audits),'wall_seconds':time.perf_counter()-started,
        'statuses':statuses,'audits':audits,'correct_skill_executions':sum(skill_success(x['row'],plan['published_entry']['skill_id']) for x in rows),
        'scope':'metadata-only inherited real program; conditional common discovery instruction; exploratory, no automatic activation'}
    base.publish(folder/'report.json',result)
    base.summarize(folder,{'status':'COMPLETE' if complete else 'FAILED_OR_INCOMPLETE','candidate_count':1,'program_admitted':True,
        'agent_admitted':False,'failure':failure,'costs':{k:result[k] for k in ['charged_tokens','combined_tokens','model_calls','tool_calls','wall_seconds']}},rows)
    if phase=='metadata_dev' and complete:
        pairs=[]
        for data in plan['cases']['metadata_dev']:
            values={x['method']:x['row'] for x in rows if x['row']['case']['task_id']==data['task_id']}
            saving=values['OldName']['agent']['metrics']['llm_calls']-values['ExactName']['agent']['metrics']['llm_calls']
            pairs.append({'task_id':data['task_id'],'source_group':data['source_group'],'split':'dev','outcome':'win' if saving>=1 else 'loss' if saving<=-1 else 'tie'})
        RevisionMemory(root/'revision-memory',SplitLedger(root/'source-ledger')).append(candidate_revision=plan['metadata_entry']['revision'],
            parent_revision=plan['parent_entry']['revision'],trigger_gap='prior dev display-name/skill_id confusion',changed_nodes=[],
            support_domain=plan['metadata_entry']['support_domain'],pairs=pairs,accepted_in_dev=bool(dev_passed),
            reason='one preregistered metadata-only variant; executable program and safety unchanged',
            evidence_hashes=[plan['optimizer_feedback_dev_report_sha256'],digest_file(folder/'report.json')])
    print(json.dumps({k:result[k] for k in ['phase','complete','failure','dev_gate_passed','agent_gate_passed','charged_tokens','combined_tokens','correct_skill_executions']}),flush=True)
    return result


def freeze(root):
    root=root.resolve();plan=base.read(root/'plan.json');check(plan)
    for phase in ['metadata_dev','discovery_dev']:
        if not base.read(root/phase/'report.json')['dev_gate_passed']:raise ValueError('dev did not pass; no formal expansion')
    # New independent probes exercise the unchanged executable program. The
    # formal program certificate is inherited by exact semantics, not a fake
    # freshly compiled candidate with modified version numbers.
    functions=old_api.validation_functions();ledger=SplitLedger(root/'source-ledger')
    vp=functions['declare_protocol'](plan['metadata_entry'],GOAL.identity,plan['program_cases'],ledger,mode='engineering')
    validation=functions['validate_program'](plan['metadata_entry'],vp);audit=functions['audit_validation'](validation)
    if not validation['engineering_passed'] or not audit['passed']:raise ValueError('metadata program sandbox failed')
    inheritance={'parent_admission_sha256':plan['parent_program_admission_sha256'],'parent_entry':plan['parent_entry'],
        'child_entry':plan['published_entry'],'governance_hash':plan['governance']['hash'],'program_fingerprint':identities(plan['published_entry']['contract'],GOAL.identity)['program_fingerprint'],
        'independent_new_program_checks':validation,'checks_audit':audit,'candidate_count':1,
        'decision':'INHERITS_UNCHANGED_PROGRAM_ADMISSION','new_program_induced':False,'agent_admitted':False,'activated':False}
    base.publish(root/'metadata-program-admission.json',{**inheritance,'hash':fingerprint(inheritance)})
    settings=base.read(root/'discovery_dev/model-identity.json')
    execution=fingerprint({'model':settings,'sources':plan['sources'],'limits':plan['config']['limits']})
    cases=[]
    for split in ['validation','stable_validation']:
        for data in plan['cases'][split]:
            case=WorkflowCase.model_validate(data);env=Environment(fixture=case.fixture)
            try:initial=fingerprint({'state':env.snapshot(),'items':private_items(env),'auth':case.authenticated_customer_id})
            finally:env.close()
            cases.append({'task_id':case.task_id,'source_group':case.source_group,'task_hash':fingerprint(data),'initial_state_hash':initial,'split':split})
    library=catalogs(plan)
    paired=declare_paired_protocol(cases,baseline_catalog_hash=library['StaticLibrary'].hash,candidate_catalog_hash=library['ExperienceEvolution'].hash,
        execution_identity=execution,**plan['agent_gate'])
    body={'schema':'interview-reference-formal-protocol-v1','plan_hash':plan['hash'],'sources':plan['sources'],
        'execution_identity':execution,'paired_protocol':paired,'methods':METHODS,'all_cases':{k:plan['cases'][k] for k in ['validation','stable_validation','test','stable_test']},
        'metadata_dev_report_sha256':digest_file(root/'metadata_dev/report.json'),'discovery_dev_report_sha256':digest_file(root/'discovery_dev/report.json'),
        'prior_charged_tokens':prior_tokens(root,plan,'formal'),'max_combined_tokens':plan['max_combined_tokens'],'deadline_utc':plan['deadline_utc'],
        'study_scale':plan['study_scale'],'model_prompt':SYSTEM_PROMPT,'automatic_runtime_search_load':False,'activated':False}
    protocol={**body,'hash':fingerprint(body)};base.publish(root/'formal-protocol.json',protocol);return protocol


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['declare','metadata_dev','discovery_dev','freeze','formal','pipeline']);parser.add_argument('--output',type=Path,default=DEFAULT)
    args=parser.parse_args();root=args.output
    if args.command=='declare':print(json.dumps({'plan_hash':declare(root)['hash']}))
    elif args.command=='freeze':print(json.dumps({'protocol_hash':freeze(root)['hash']}))
    elif args.command=='pipeline':
        first=run_phase(root,'metadata_dev')
        if first['dev_gate_passed']:
            second=run_phase(root,'discovery_dev')
            if second['dev_gate_passed']:freeze(root);run_phase(root,'formal')
    else:run_phase(root,args.command)
