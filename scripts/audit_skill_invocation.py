"""Independent raw-output/SQL/checkpoint replay and typed-selection funnel."""
import argparse
from collections import Counter
from functools import partial
from pathlib import Path
from types import SimpleNamespace
import json
import time

from scripts import run_skill_invocation as study
from scripts import run_interview_sprint as base
from scripts.audit_interview_sprint import actual_database
from scripts.run_skill_evolution import digest_file
from skillforge.interview_sprint import adapters as old
from skillforge.interview_sprint.workflows import WorkflowCase
from skillforge.skill_evolution.catalog import Catalog
from skillforge.skill_evolution.agent_evidence import semantic
from skillforge.skill_invocation import runtime
from skillforge.skill_invocation.adapter import TOOL
from skillforge.evolution_schemas import fingerprint
from skillforge.evolution_common.artifacts import SplitLedger
from skillforge.environment import Environment
from skillforge.schemas import Action


def audit(root,*,output=None):
    started=time.perf_counter();root=Path(root).resolve();p=base.read(root/'protocol.json');study.check(p)
    report=base.read(root/'report.json');reg=base.read(root/'registration.json');settings=base.read(root/'model-identity.json')
    if not report['complete'] or report['failure'] or reg['protocol_hash']!=p['hash'] or report['protocol_hash']!=p['hash']:
        raise ValueError('complete matching dev run required')
    if settings!=base.read(study.PARENT/'model-identity.json'):raise ValueError('model weights, original prompt or decoding differs')
    if study.learned_entry()!=p['parent_entry']:raise ValueError('original verified program changed')
    for name,h in p['sources'].items():
        if digest_file(root/'source-snapshot'/name)!=h:raise ValueError('archived source differs')
    program_proof=old.validation_functions()['audit_program_admission'](base.read(study.PARENT/'program-admission.json'))
    catalog=Catalog(p['catalog']);ledger=SplitLedger(root/'source-ledger');cases={c['task_id']:c for c in p['cases']}
    expected=[(c['task_id'],m) for c,order in zip(p['cases'],p['order']) for m in order]
    if [(s['task_id'],s['method']) for s in report['statuses']]!=expected:raise ValueError('frozen nine-arm ordering/denominator differs')
    groups={m:Counter() for m in study.METHODS};rows={};proofs=[];charged=0;checkpoints=0
    for status in report['statuses']:
        case=WorkflowCase.model_validate(cases[status['task_id']]);method=status['method'];dest=root/status['folder'];row=base.read(dest/'result.json')
        if row['case']!=case.model_dump() or not status['completed']:raise ValueError('foreign or incomplete task')
        if any(ledger.owners.get(k)!='dev' for k in [case.task_id,case.source_group,case.parameters['order_id'],case.fixture['customer_id']]):raise ValueError('source/entity split differs')
        entry=p['parent_entry'];start={'observations':{},'loaded_refs':{} if method=='C' else {
            entry['skill_id']:{'revision':entry['revision'],'content_hash':entry['revision']}}}
        replay=old.bind(base.audit_arm,{'api':SimpleNamespace(run_agent=partial(runtime.run_agent,mode=method,public_start=start))})(
            dest,case,catalog,settings,p['config']['limits'],(p['prior_tokens']+charged,p['max_combined_tokens'],0,reg['config']['budget']['project_max_wall_seconds']))
        initial,items,sql=actual_database(dest/'initial-snapshot/environment.sqlite',case)
        env=Environment(fixture=case.fixture)
        try:
            if sql!=list(env.db.iterdump()) or initial!=row['initial_state'] or items!=row['initial_items']:raise ValueError('initial fixture differs')
        finally:env.close()
        for path in (dest/'checkpoints').glob('*/snapshot.json'):
            snap=base.read(path);state,observed,actual_sql=actual_database(path.parent/'environment.sqlite',case)
            if fingerprint(snap['body'])!=snap['hash'] or digest_file(path.parent/'environment.sqlite')!=snap['body']['database_sha256']:raise ValueError('checkpoint integrity differs')
            if actual_sql!=sql or state!=initial or observed!=items:raise ValueError('read-only DB changed')
            if semantic(snap['body']['audit'])!=semantic(row['tool_audit'][:len(snap['body']['audit'])]):raise ValueError('checkpoint causal audit prefix differs')
            checkpoints+=1
        final,final_items,final_sql=actual_database(dest/'live.sqlite',case)
        if final_sql!=sql or final!=row['final_state'] or final_items!=row['final_items']:raise ValueError('final SQL changed')
        for step in row['agent']['steps']:
            if any(k in step['context'] for k in ['fixture','gold','expected','source_group','split','validation']):raise ValueError('private evaluator input leaked')
        agent=row['agent'];v=row['verification'];g=groups[method];trace=agent['invocation_adapter']['trace']
        if agent['invocation_mode']!=method:raise ValueError('wrong interface condition')
        if any(step['action']!=Action.model_validate_json(step['model_response']).model_dump() for step in agent['steps'] if step.get('action')):raise ValueError('raw model action was repaired')
        g['n']+=1;g['visible']+=int(bool(agent['steps'][0]['context']['catalog']['loaded_skills']))
        g['selected_any']+=int(any(s.get('action') and (s['action']['type']=='skill' or s['action']['type']=='tool' and s['action']['name']==TOOL) for s in agent['steps']))
        g['selected_structured']+=int(bool(trace));g['inputs_valid_structured']+=int(any(t['validation']=='VALID' for t in trace))
        g['inputs_valid_any_interface']+=int(bool(agent['skill_events']) or any(t['validation']=='VALID' for t in trace))
        g['success_structured']+=int(any(t.get('success') for t in trace));g['success_any_skill']+=int(any(e['success'] for e in agent['skill_events']))
        g['eoc']+=int(v['task_success']);g['autonomous_eoc']+=int(v['task_success'] and agent['termination_source']=='model' and not agent['interventions']['runtime_intervention_count'])
        g['runtime_assisted_eoc']+=int(v['task_success'] and (agent['termination_source']!='model' or agent['interventions']['runtime_intervention_count']))
        g['runtime_interventions']+=agent['interventions']['runtime_intervention_count']
        g['model_calls']+=agent['metrics']['llm_calls'];g['tokens']+=agent['metrics']['tokens'];g['business_tools']+=len(row['tool_audit'])
        g['model_search']+=agent['metrics']['search_calls'];g['model_load']+=agent['metrics']['load_calls']
        g['structured_action_attempts']+=len(trace);g['legacy_action_attempts']+=sum(bool(s.get('action') and s['action']['type']=='skill') for s in agent['steps'])
        g['forbidden_intents']+=base.forbidden_attempts(row);g['raw_attempted_violations']+=int(v['attempted_policy_violation'])
        g['actual_violations']+=int(v['actual_policy_violation'] or v['actual_workflow_violation'])
        g['primitive_fallback_cases']+=int(not any(e['success'] for e in agent['skill_events']) and any(e['decision_origin']=='model' for e in row['tool_audit']))
        g['system_candidate_searches']+=int(method=='C');g['system_preloads']+=1
        rows[(case.task_id,method)]=row;proofs.append(replay);charged+=status['charged_tokens']
    if charged!=report['charged_tokens'] or report['combined_tokens']!=p['prior_tokens']+charged:raise ValueError('all-in cost differs')
    pairs=[]
    for c in p['cases']:
        arms={m:rows[(c['task_id'],m)] for m in study.METHODS}
        # Business/public task/initial state are shared. Catalog and tool-interface
        # descriptors are the only initial context interventions.
        contexts=[]
        for m,row in arms.items():
            context=dict(row['agent']['steps'][0]['context']);context.pop('available_tools');context.pop('protocol');contexts.append(context)
        if any(x!=contexts[0] for x in contexts):raise ValueError('unrelated initial public context differs')
        for baseline,candidate in [('A','B'),('A','C'),('B','C')]:
            a,b=arms[baseline],arms[candidate]
            pairs.append({'task_id':c['task_id'],'source_group':c['source_group'],'variant':c['variant'],
                'comparison':candidate+'-'+baseline,'eoc_delta':int(b['verification']['task_success'])-int(a['verification']['task_success']),
                'saved_model_calls':a['agent']['metrics']['llm_calls']-b['agent']['metrics']['llm_calls'],
                'saved_tokens':a['agent']['metrics']['tokens']-b['agent']['metrics']['tokens'],
                'structured_success':any(t.get('success') for t in b['agent']['invocation_adapter']['trace']),
                'regression':a['verification']['task_success'] and not b['verification']['task_success']})
    positive=all(g['eoc']==3 and not g['forbidden_intents'] and not g['raw_attempted_violations'] and not g['actual_violations'] for g in groups.values()) and groups['B']['success_structured']==3 and all(x['saved_model_calls']>=1 for x in pairs if x['comparison']=='B-A')
    if bool(positive)!=report['positive_dev']:raise ValueError('stop decision differs from raw data')
    proof={'passed':True,'protocol_hash':p['hash'],'auditor_sha256':digest_file(__file__),'report_sha256':digest_file(root/'report.json'),
        'completed_arms':len(rows),'checkpoints':checkpoints,'groups':{m:dict(g) for m,g in groups.items()},'pairs':pairs,
        'positive_dev':bool(positive),'agent_admitted':False,'activated':False,'charged_tokens':charged,'combined_tokens':p['prior_tokens']+charged,
        'cpu_response_replay_tools':sum(a['replay_tool_calls'] for a in proofs),'cpu_program_replay_tools':program_proof['replay_tool_calls'],
        'model_calls':0,'tokens':0,'wall_seconds':time.perf_counter()-started,'scope':'exploratory dev; raw JSON Action unchanged; original Gate/DSL/permissions and independent EOC'}
    base.publish(output or root/'independent-audit.json',proof);return proof


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run',type=Path,default=study.DEFAULT);parser.add_argument('--output',type=Path)
    args=parser.parse_args();print(json.dumps(audit(args.run,output=args.output),ensure_ascii=False))
