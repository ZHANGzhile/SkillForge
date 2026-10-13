"""Independent post-freeze audits of separately registered common input-binding study."""
import argparse
from functools import partial
from pathlib import Path
from types import SimpleNamespace
import json
import time

from scripts import run_interview_binding as study
from scripts import run_interview_sprint as base
from scripts.audit_interview_sprint import actual_database
from scripts.run_skill_evolution import digest_file
from skillforge.interview_sprint import adapters as old
from skillforge.interview_binding import runtime as new
from skillforge.interview_sprint.workflows import WorkflowCase, GOAL
from skillforge.evolution_common.artifacts import clone, SplitLedger
from skillforge.evolution_schemas import fingerprint
from skillforge.skill_evolution.agent_evidence import semantic
from skillforge.skill_evolution.admission import paired_gate


def audit(root, *, label='final'):
    if label not in {'dev','final'}:raise ValueError('unknown receipt label')
    started=time.perf_counter();root=Path(root).resolve();plan=base.read(root/'plan.json');study.check(plan, check_deadline=False)
    for name,h in plan['sources'].items():
        if digest_file(root/'source-snapshot'/name)!=h:raise ValueError('archived source differs')
    parent,entry,published,governance=study.parent_metadata()
    if any(a!=b for a,b in [(parent,plan['parent_entry']),(entry,plan['metadata_entry']),
            (published,plan['published_entry']),(governance,plan['governance'])]):
        raise ValueError('metadata changed parent program or deviated from preregistration')
    parent_admission=base.read(study.PARENT/'program-admission.json')
    parent_proof=old.validation_functions()['audit_program_admission'](parent_admission)
    # Ground unchanged child procedure in the ORIGINAL real train evidence.
    learn=[base.read(p) for p in sorted((study.PARENT/'learn').glob('*/*/result.json'))]
    settings_parent=base.read(study.PARENT/'model-identity.json')
    screen=old.mine_opportunities(learn,settings_parent);compiled=old.compile_screen(screen)
    if compiled!=base.read(study.PARENT/'candidate-screen.json') or len(learn)!=6:
        raise ValueError('original real-trace program provenance changed')
    candidate=next(x['candidate'] for x in compiled['results'] if x['candidate'])
    if candidate['skill']['procedure']!=entry['contract']['procedure']:
        raise ValueError('metadata child contains unobserved program steps')
    functions=old.validation_functions();child_check=base.read(root/'metadata-preflight-validation.json')
    child_audit=functions['audit_validation'](child_check)
    if not child_check['engineering_passed'] or child_check['entry']!=entry:
        raise ValueError('independent child program preflight failed')
    ledger=SplitLedger(root/'source-ledger');libraries=study.catalogs(plan);prior=plan['prior_charged_tokens']
    phase_proofs=[];all_rows=[];checkpoint_count=0;replay_tools=0;program_replay_tools=parent_proof['replay_tool_calls']+child_audit['replay_tool_calls']
    for phase,expected in [('discovery_dev',9),('formal',57)]:
        folder=root/phase
        if not (folder/'report.json').exists():continue
        report,reg,settings=base.read(folder/'report.json'),base.read(folder/'registration.json'),base.read(folder/'model-identity.json')
        if not report['complete'] or report['failure']:raise ValueError('incomplete phase cannot certify')
        if report['plan_hash']!=plan['hash'] or reg['plan_hash']!=plan['hash'] or reg['prior_charged_tokens']!=prior:
            raise ValueError('phase identity or inherited charge differs')
        if reg['config']['budget']['project_max_tokens']!=plan['max_combined_tokens']:raise ValueError('token budget changed')
        allowed_changes={'system_prompt','prompt_version','prompt_sha256','decision_protocol','catalog_serving_code_hash'}
        if {k:v for k,v in settings.items() if k not in allowed_changes}!={k:v for k,v in settings_parent.items() if k not in allowed_changes}:
            raise ValueError('fixed model, tokenizer or decoding settings changed')
        if settings['prompt_sha256']!=fingerprint(plan['common_prompt']) or settings['catalog_serving_code_hash']!=plan['sources']['skillforge/interview_binding/model.py']:
            raise ValueError('model prompt or serving source identity differs')
        if phase=='metadata_dev':
            if settings!=settings_parent:raise ValueError('metadata-only phase changed model or prompt')
            planned={x['task_id']:x for x in plan['cases'][phase]};runtime=old.run_agent
        elif phase=='discovery_dev':
            if settings['system_prompt']!=plan['common_prompt']:raise ValueError('dev common prompt differs')
            planned={x['task_id']:x for x in plan['cases'][phase]};runtime=new.run_agent
        else:
            if settings!=base.read(root/'discovery_dev/model-identity.json'):raise ValueError('formal model differs')
            planned={x['task_id']:x for split in ['validation','stable_validation','test','stable_test'] for x in plan['cases'][split]};runtime=new.run_agent
        charged=0;rows=[]
        for status in report['statuses']:
            case=WorkflowCase.model_validate(planned[status['task_id']]);dest=root/status['folder'];row=base.read(dest/'result.json')
            if row['case']!=case.model_dump() or not status['completed']:raise ValueError('foreign/incomplete raw arm')
            partition='dev' if phase!='formal' else ('stable_validation' if row['case'] in plan['cases']['stable_validation'] else
                'stable_test' if row['case'] in plan['cases']['stable_test'] else case.split)
            if any(ledger.owners.get(k)!=partition for k in [case.source_group,case.task_id,case.parameters['order_id'],case.fixture['customer_id']]):
                raise ValueError('source/entity partition overlap')
            start=None
            if phase=='metadata_dev':
                e=plan['parent_entry'] if status['method']=='OldName' else plan['published_entry']
                start={'observations':{},'loaded_refs':{e['skill_id']:{'revision':e['revision'],'content_hash':e['revision']}}}
            replay=old.bind(base.audit_arm,{'api':SimpleNamespace(run_agent=partial(runtime,public_start=start))})(dest,case,libraries[status['method']],settings,plan['config']['limits'],
                (prior+charged,plan['max_combined_tokens'],0,reg['config']['budget']['project_max_wall_seconds']))
            initial,items,dump=actual_database(dest/'initial-snapshot/environment.sqlite',case)
            if initial!=row['initial_state'] or items!=row['initial_items']:raise ValueError('initial DB differs')
            # All writes remain forbidden: every actual SQLite checkpoint must
            # equal independently generated initial fixture data.
            from skillforge.environment import Environment
            env=Environment(fixture=case.fixture)
            try:
                if dump!=list(env.db.iterdump()):raise ValueError('undeclared initial DB fixture')
            finally:env.close()
            for path in (dest/'checkpoints').glob('*/snapshot.json'):
                snap=base.read(path);body=snap['body'];state,rows_items,sql=actual_database(path.parent/'environment.sqlite',case)
                if fingerprint(body)!=snap['hash'] or digest_file(path.parent/'environment.sqlite')!=body['database_sha256']:
                    raise ValueError('checkpoint bytes differ')
                if sql!=dump or state!=initial or rows_items!=items:raise ValueError('read-only checkpoint mutated DB')
                if semantic(body['audit'])!=semantic(row['tool_audit'][:len(body['audit'])]):raise ValueError('checkpoint audit prefix differs')
                checkpoint_count+=1
            final,final_items,final_dump=actual_database(dest/'live.sqlite',case)
            if final_dump!=dump or final!=row['final_state'] or final_items!=row['final_items']:raise ValueError('final DB facts differ')
            for step in row['agent']['steps']:
                context=step['context']
                if any(k in context for k in ['fixture','source_group','split','expected','gold','validation','admission']):
                    raise ValueError('private evaluator data in public model context')
                if any('selection_trace' in old_step for old_step in context['history']):raise ValueError('private selection trace in history')
                if {k:context[k] for k in case.public_task()}!=case.public_task():raise ValueError('public task mismatch')
            if row['agent']['steps'][0]['context']['catalog']['loaded_skills']:
                raise ValueError('discovery experiment must start without preloading')
            if status['charged_tokens']!=replay['charged_tokens']:raise ValueError('settled charge differs')
            charged+=status['charged_tokens'];replay_tools+=replay['replay_tool_calls'];rows.append({'phase':status['phase'],'method':status['method'],'row':row})
        if len(rows)!=expected or charged!=report['charged_tokens'] or report['combined_tokens']!=prior+charged:
            raise ValueError('planned denominator or fees differ')
        if report['model_calls']!=sum(x['row']['agent']['metrics']['llm_calls'] for x in rows):raise ValueError('model calls differ')
        matched={}
        for x in rows:matched.setdefault(x['row']['case']['task_id'],{})[x['method']]=x['row']
        if any(set(arms)!=set(study.METHODS) for arms in matched.values()):raise ValueError('missing or duplicated method in a paired source')
        for arms in matched.values():
            contexts=[]
            for row in arms.values():
                context=clone(row['agent']['steps'][0]['context']);context.pop('catalog');contexts.append(context)
            if any(c!=contexts[0] for c in contexts):raise ValueError('unrelated noncatalog initial context changed between arms')
        if phase!='formal':
            by_task={}
            for x in rows:by_task.setdefault(x['row']['case']['task_id'],{})[x['method']]=x['row']
            passed=all(x['row']['verification']['task_success'] and not study.unsafe(x['row']) for x in rows)
            for arms in by_task.values():
                a,b=(arms['OldName'],arms['ExactName']) if phase=='metadata_dev' else (arms['StaticLibrary'],arms['ExperienceEvolution'])
                passed=passed and study.skill_success(b,published['skill_id']) and a['agent']['metrics']['llm_calls']-b['agent']['metrics']['llm_calls']>=1
                if phase=='discovery_dev':passed=passed and bool(b['agent']['search_events']) and bool(b['agent']['load_events'])
            if bool(passed)!=report['dev_gate_passed']:raise ValueError('dev gate differs from raw rows')
        if phase=='metadata_dev':
            for task,arms in by_task.items():
                # Version/revision/name are the declared metadata intervention;
                # all noncatalog initial public context stays identical.
                a,b=clone(arms['OldName']['agent']['steps'][0]['context']),clone(arms['ExactName']['agent']['steps'][0]['context'])
                a.pop('catalog');b.pop('catalog')
                if a!=b:raise ValueError('metadata comparison has unrelated public-context differences')
        phase_proofs.append({'phase':phase,'report_sha256':digest_file(folder/'report.json'),'arms':len(rows),'tokens':charged,
            'correct_skill_executions':sum(study.skill_success(x['row'],published['skill_id']) for x in rows)})
        all_rows.extend(rows);prior+=charged
    if prior>plan['max_combined_tokens']:raise ValueError('cumulative budget exceeded')
    gate=None
    if (root/'formal/report.json').exists():
        formal=base.read(root/'formal-protocol.json')
        if fingerprint({k:v for k,v in formal.items() if k!='hash'})!=formal['hash'] or formal['plan_hash']!=plan['hash']:
            raise ValueError('formal freeze differs')
        for phase in ['discovery_dev']:
            if not base.read(root/phase/'report.json')['dev_gate_passed'] or digest_file(root/phase/'report.json')!=formal[phase+'_report_sha256']:
                raise ValueError('formal proceeded without frozen dev pass')
        inheritance=base.read(root/'metadata-program-admission.json')
        if fingerprint({k:v for k,v in inheritance.items() if k!='hash'})!=inheritance['hash'] or inheritance['child_entry']!=published:
            raise ValueError('inherited program certificate differs')
        extra=functions['audit_validation'](inheritance['independent_new_program_checks']);program_replay_tools+=extra['replay_tool_calls']
        gate=base.read(root/'formal/agent-paired-gate.json')
        if paired_gate(formal['paired_protocol'],gate['pairs'])!=gate:raise ValueError('Agent gate arithmetic differs')
        raw={(x['row']['case']['task_id'],x['method']):x['row'] for x in all_rows if x['phase']=='validation'}
        for pair in gate['pairs']:
            for arm_name,method in [('baseline','StaticLibrary'),('candidate','ExperienceEvolution')]:
                row=raw[(pair['task_id'],method)];v=row['verification'];m=row['agent']['metrics'];arm=pair[arm_name]
                expected={'eoc':v['task_success'],'model_calls':m['llm_calls'],'tokens':m['tokens'],'evidence_hash':fingerprint(row),
                    'attempted_violations':int(v['attempted_policy_violation'])+base.forbidden_attempts(row),'actual_violations':int(v['actual_policy_violation']),
                    'workflow_violations':int(v['actual_workflow_violation']),'catalog_hash':libraries[method].hash,'execution_identity':formal['execution_identity']}
                if any(arm[k]!=value for k,value in expected.items()):raise ValueError('Agent gate is not grounded in actual paired arms')
                if pair['task_hash']!=fingerprint(row['case']) or pair['source_group']!=row['case']['source_group']:
                    raise ValueError('paired task/source binding differs')
                if pair['initial_state_hash']!=fingerprint({'state':row['initial_state'],'items':row['initial_items'],'auth':row['case']['authenticated_customer_id']}):
                    raise ValueError('paired initial state differs')
        if base.read(root/'formal/report.json')['agent_gate_passed']!=gate['statistical_gate_passed']:raise ValueError('Agent gate outcome differs')
    proof={'passed':True,'plan_hash':plan['hash'],'auditor_sha256':digest_file(__file__),'phases':phase_proofs,'completed_arms':sum(p['arms'] for p in phase_proofs),
        'checkpoints':checkpoint_count,'actual_sqlite_response_replay_tools':replay_tools,'program_replay_tools':program_replay_tools,
        'combined_tokens':prior,'model_calls':0,'tokens':0,'wall_seconds':time.perf_counter()-started,
        'agent_admitted':bool(gate and gate['statistical_gate_passed']),'activated':False,
        'scope':'new metadata/program inheritance, actual raw model outputs/checkpoints/SQLite, independent source ownership, all fees and paired gates; conditional common prompt'}
    base.publish(root/(label+'-independent-audit.json'),proof)
    admission={'agent_admitted':proof['agent_admitted'],'audit_sha256':digest_file(root/(label+'-independent-audit.json')),
        'gate_hash':gate['hash'] if gate else None,'activated':False,'deployed':False,'research_claim_passed':None,
        'scope':'exploratory admission under common explicit discovery instruction; original prompt study remains negative'}
    base.publish(root/(label+'-agent-admission.json' if label=='dev' else 'agent-admission.json'),admission)
    return proof


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run',type=Path,default=study.DEFAULT)
    parser.add_argument('--label',choices=['dev','final'],default='final');args=parser.parse_args()
    print(json.dumps(audit(args.run,label=args.label),ensure_ascii=False))
