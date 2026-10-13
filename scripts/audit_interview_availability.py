"""Independently audit conditional availability; do not change main admission."""
import argparse
from functools import partial
from pathlib import Path
from types import SimpleNamespace
import json
import time

from scripts.run_interview_sprint import ROOT, read, publish, check_sources, audit_arm
from scripts.audit_interview_sprint import actual_database
from scripts.run_skill_evolution import digest_file
from skillforge.interview_sprint import adapters as api
from skillforge.interview_sprint.workflows import WorkflowCase
from skillforge.evolution_schemas import fingerprint
from skillforge.evolution_common.artifacts import clone, SplitLedger
from skillforge.skill_evolution.agent_evidence import semantic
from skillforge.skill_evolution.catalog import Catalog


def audit(root):
    started=time.perf_counter();root=Path(root).resolve();p,r,reg=read(root/'protocol.json'),read(root/'report.json'),read(root/'run-registration.json')
    if fingerprint({k:v for k,v in p.items() if k!='hash'})!=p['hash'] or r['protocol_hash']!=p['hash'] or not r['complete']:
        raise ValueError('complete matching diagnostic required')
    if digest_file(ROOT/'scripts/run_interview_availability.py')!=p['diagnostic_source_sha256']:raise ValueError('diagnostic controller changed')
    main=ROOT/p['main_run'];mainp,mainr,mainaudit=read(main/'protocol.json'),read(main/'report.json'),read(main/'final-independent-audit.json')
    check_sources(mainp)
    if not mainaudit['passed'] or mainaudit['report_sha256']!=digest_file(main/'report.json') or mainp['hash']!=p['main_protocol_hash']:
        raise ValueError('main provenance audit differs')
    if digest_file(main/'program-admission.json')!=p['program_admission_sha256']:raise ValueError('program admission changed')
    if reg['main_report_sha256']!=digest_file(main/'report.json') or reg['prior_charged_tokens']!=mainr['costs']['charged_tokens']:
        raise ValueError('diagnostic inherited cost differs')
    settings=read(root/'model-identity.json')
    if settings!=read(main/'model-identity.json'):raise ValueError('model changed')
    catalog=Catalog(p['catalog']);ledger=SplitLedger(root/'source-ledger');planned={c['task_id']:c for c in p['cases']}
    if catalog.hash!=p['catalog_hash'] or p['candidate_revision'] not in {e['revision'] for e in catalog.entries()}:raise ValueError('catalog changed')
    charges=reg['prior_charged_tokens'];rows=[];checkpoints=0;tools=0
    for status in r['statuses']:
        case=WorkflowCase.model_validate(planned[status['task_id']]);folder=root/case.task_id/status['method']
        if ledger.owners.get(case.source_group)!='dev':raise ValueError('diagnostic source is not dev')
        if not status['completed']:raise ValueError('incomplete diagnostic arm')
        start={'observations':{},'loaded_refs':({p['candidate_skill_id']:{'revision':p['candidate_revision'],'content_hash':p['candidate_revision']}} if status['method']=='PRELOADED' else {})}
        receipt=api.bind(audit_arm,{'api':SimpleNamespace(run_agent=partial(api.run_agent,public_start=start))})(folder,case,catalog,settings,p['limits'],
            (charges,reg['max_combined_tokens'],0,reg['config']['budget']['project_max_wall_seconds']))
        row=read(folder/'result.json');initial,items,dump=actual_database(folder/'initial-snapshot/environment.sqlite',case)
        if initial!=row['initial_state'] or items!=row['initial_items']:raise ValueError('initial facts differ')
        for path in (folder/'checkpoints').glob('*/snapshot.json'):
            snap=read(path);body=snap['body'];state,observed,sql=actual_database(path.parent/'environment.sqlite',case)
            if digest_file(path.parent/'environment.sqlite')!=body['database_sha256'] or fingerprint(body)!=snap['hash']:
                raise ValueError('checkpoint identity differs')
            if sql!=dump or state!=initial or observed!=items:raise ValueError('read-only diagnostic changed SQLite state')
            if semantic(body['audit'])!=semantic(row['tool_audit'][:len(body['audit'])]):raise ValueError('checkpoint audit prefix differs')
            checkpoints+=1
        final,final_items,final_dump=actual_database(folder/'live.sqlite',case)
        if final_dump!=dump or final!=row['final_state'] or final_items!=row['final_items']:raise ValueError('final DB differs')
        if receipt['charged_tokens']!=status['charged_tokens']:raise ValueError('actual fee differs')
        charges+=status['charged_tokens'];tools+=receipt['replay_tool_calls'];rows.append({'method':status['method'],'row':row})
    if len(rows)!=6 or charges!=r['combined_tokens'] or charges>reg['max_combined_tokens']:
        raise ValueError('diagnostic arm count or cumulative budget differs')
    metrics=[]
    for method in ['WITHHELD','PRELOADED']:
        values=[v['row'] for v in rows if v['method']==method];steps=[s for v in values for s in v['agent']['steps']]
        metrics.append({'method':method,'n':len(values),'eoc':sum(v['verification']['task_success'] for v in values),
            'autonomous_eoc':sum(v['verification']['task_success'] and v['agent']['termination_source']=='model' and v['agent']['interventions']['runtime_intervention_count']==0 for v in values),
            'model_calls':sum(v['agent']['metrics']['llm_calls'] for v in values),'tokens':sum(v['agent']['metrics']['tokens'] for v in values),
            'search':sum(v['agent']['metrics']['search_calls'] for v in values),'load':sum(v['agent']['metrics']['load_calls'] for v in values),
            'skill_action_attempts':sum(s.get('action',{}).get('type')=='skill' for s in steps if s.get('action')),
            'accepted_skill_events':sum(len(v['agent']['skill_events']) for v in values),
            'successful_skill_executions':sum(e['success'] for v in values for e in v['agent']['skill_events']),
            'skill_not_loaded_errors':sum(s.get('error')=='skill_not_loaded' for s in steps),
            'runtime_interventions':sum(v['agent']['interventions']['runtime_intervention_count'] for v in values)})
    pair_checks=[]
    for task in planned:
        pair={x['method']:x['row'] for x in rows if x['row']['case']['task_id']==task}
        a,b=clone(pair['WITHHELD']['agent']['steps'][0]['context']),clone(pair['PRELOADED']['agent']['steps'][0]['context'])
        empty=a['catalog'].pop('loaded_skills');loaded=b['catalog'].pop('loaded_skills')
        if a!=b or empty or len(loaded)!=1 or loaded[0]['revision']!=p['candidate_revision']:raise ValueError('undeclared context intervention')
        pair_checks.append({'task_id':task,'context_equal_except_loaded':True,'withheld_eoc':pair['WITHHELD']['verification']['task_success'],
            'preloaded_eoc':pair['PRELOADED']['verification']['task_success'],'model_call_saving':pair['WITHHELD']['agent']['metrics']['llm_calls']-pair['PRELOADED']['agent']['metrics']['llm_calls']})
    result={'passed':True,'protocol_hash':p['hash'],'report_sha256':digest_file(root/'report.json'),'auditor_sha256':digest_file(__file__),
        'completed_arms':len(rows),'checkpoints':checkpoints,'actual_replay_tool_calls':tools,'model_calls':0,'tokens':0,
        'metrics':metrics,'pairs':pair_checks,'wall_seconds':time.perf_counter()-started,
        'main_agent_admission_unchanged':mainr['agent_admitted'],'scope':'conditional dev availability only; no autonomous retrieval or primary benefit claim'}
    publish(root/'final-independent-audit.json',result);return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run',type=Path,required=True)
    print(json.dumps(audit(parser.parse_args().run),ensure_ascii=False))
