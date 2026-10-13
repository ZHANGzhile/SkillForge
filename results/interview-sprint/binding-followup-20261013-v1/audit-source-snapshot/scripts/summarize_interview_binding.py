"""Derived, source-group paired metrics; does not run models or alter evidence."""
import argparse
from collections import Counter
from pathlib import Path
import json

from scripts import run_interview_binding as study
from scripts import run_interview_sprint as base
from scripts.run_skill_evolution import digest_file


def summarize(root):
    root=Path(root).resolve();plan=base.read(root/'plan.json');study.check(plan,check_deadline=False)
    phases=[];pairs=[];prior=plan['prior_charged_tokens'];calls=422;arms=75
    for phase in ['discovery_dev','formal']:
        folder=root/phase
        if not (folder/'report.json').exists():continue
        report=base.read(folder/'report.json');groups={};by_task={}
        for status in report['statuses']:
            if not status['completed']:continue
            row=base.read(root/status['folder']/'result.json');agent=row['agent'];v=row['verification']
            steps=agent['steps'];key=(status['phase'],status['method'])
            g=groups.setdefault(key,Counter());g['n']+=1;g['eoc']+=int(v['task_success'])
            interventions=agent['interventions'].get('runtime_intervention_count',0)
            autonomous=v['task_success'] and not interventions and agent['termination_source']=='model'
            g['autonomous_eoc']+=int(autonomous);g['runtime_assisted_eoc']+=int(v['task_success'] and not autonomous)
            g['runtime_interventions']+=interventions
            for metric in ['llm_calls','tokens','tool_calls','search_calls','load_calls']:g[metric]+=agent['metrics'][metric]
            g['skill_action_attempts']+=sum(s.get('action',{}).get('type')=='skill' for s in steps)
            g['accepted_skill_calls']+=len(agent['skill_events']);g['successful_skill_calls']+=sum(e['success'] for e in agent['skill_events'])
            g['raw_attempted_policy_violations']+=int(v['attempted_policy_violation'])
            g['expected_denial_observed']+=int(v.get('expected_denial_observed',False))
            g['forbidden_action_intents']+=base.forbidden_attempts(row)
            g['actual_violations']+=int(v['actual_policy_violation'] or v['actual_workflow_violation'])
            g['errored_actions']+=sum(bool(s.get('error')) for s in steps)
            by_task.setdefault(row['case']['task_id'],{})[status['method']]=row
        for task,methods in by_task.items():
            for baseline in ['PrimitiveOnly','StaticLibrary']:
                if baseline not in methods or 'ExperienceEvolution' not in methods:continue
                a,c=methods[baseline],methods['ExperienceEvolution'];case=c['case']
                pairs.append({'phase':phase,'split':case['split'],'task_id':task,'source_group':case['source_group'],
                    'workflow_id':case['workflow_id'],'variant':case['variant'],'comparison':'ExperienceEvolution-'+baseline,
                    'baseline_eoc':a['verification']['task_success'],'candidate_eoc':c['verification']['task_success'],
                    'eoc_delta':int(c['verification']['task_success'])-int(a['verification']['task_success']),
                    'saved_model_calls':a['agent']['metrics']['llm_calls']-c['agent']['metrics']['llm_calls'],
                    'saved_tokens':a['agent']['metrics']['tokens']-c['agent']['metrics']['tokens'],
                    'candidate_skill_success':study.skill_success(c,plan['published_entry']['skill_id']),
                    'candidate_errors':dict(Counter(s['error'] for s in c['agent']['steps'] if s.get('error'))),
                    'regression':a['verification']['task_success'] and not c['verification']['task_success']})
        phases.append({'phase':phase,'report_sha256':digest_file(folder/'report.json'),
            'methods':[{'split':k[0],'method':k[1],**dict(v)} for k,v in groups.items()],
            'new_tokens':report['charged_tokens'],'new_model_calls':report['model_calls'],
            'new_business_tools':report['tool_calls'],'static_coverage_tools':report['static_coverage_tool_calls'],
            'collection_response_replay_tools':report['recorded_response_audit_tool_calls'],
            'collection_wall_seconds':report['wall_seconds'],'gpu_utilization_hours':'UNMEASURED',
            'dev_gate_passed':report['dev_gate_passed'] if phase=='discovery_dev' else None})
        prior+=report['charged_tokens'];calls+=report['model_calls'];arms+=len(report['statuses'])
    audit=base.read(root/'final-independent-audit.json');admission=base.read(root/'agent-admission.json')
    body={'schema':'interview-binding-delivery-v1','plan_hash':plan['hash'],'phases':phases,'paired_effects':pairs,
        'cumulative_sprint_tokens':prior,'cumulative_sprint_model_calls':calls,'cumulative_real_arms':arms,
        'candidate_programs':1,'new_programs_this_followup':0,'program_admitted':True,
        'agent_admitted':admission['agent_admitted'],'activated':False,
        'independent_audit_sha256':digest_file(root/'final-independent-audit.json'),
        'audited_checkpoints':audit['checkpoints'],'independent_audit_response_tools':audit['actual_sqlite_response_replay_tools'],
        'independent_audit_program_tools':audit['program_replay_tools'],'independent_audit_seconds':audit['wall_seconds'],
        'scope':'exploratory conditional common prompt; source-group units; original zero-benefit result retained; no statistical significance claim',
        'status':'AUDITED_FORMAL_COMPLETE' if (root/'formal/report.json').exists() else 'AUDITED_STOPPED_DEV_GATE_FAILED'}
    base.publish(root/'delivery-summary.json',body)
    return body


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run',type=Path,default=study.DEFAULT)
    args=parser.parse_args();result=summarize(args.run)
    print(json.dumps({k:result[k] for k in ['status','cumulative_sprint_tokens','cumulative_sprint_model_calls','cumulative_real_arms','agent_admitted','activated']}))
