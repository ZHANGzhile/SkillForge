"""Frozen-study continuation: correct expected-denial CPU coverage only.

Reuse every complete real arm/charge byte-for-byte. No prompt, Runtime, model,
candidate, EOC, task, threshold or held-out changes; no budget refill.
"""
import argparse
from pathlib import Path
import shutil
import time

from skillforge.environment import Environment, ToolError
from skillforge.execution_aware.contracts import ExecutionContract
from skillforge.schemas import SkillContract
from skillforge.skills import hydrate, gate, execute
from skillforge.evolution_schemas import fingerprint
from skillforge.skill_evolution.validation import without_latency
from skillforge.interview_sprint import adapters as api
from skillforge.interview_sprint.workflows import private_items, verify_workflow, make_case
from scripts import run_interview_sprint as base
from scripts.run_skill_evolution import digest_file


def safe_coverage(case, catalog):
    if case.variant not in {'unauthorized','missing'}:
        return base.coverage(case,catalog)
    evidence=[]
    for entry in catalog.entries():
        skill=SkillContract.model_validate(entry['contract'])
        if skill.status!='VERIFIED':continue
        env=Environment(fixture=case.fixture);tracker=ExecutionContract(case.task_id+':coverage:'+skill.skill_id)
        state={};initial,items=env.snapshot(),private_items(env);event,verdict,status=None,None,'INPUT_NOT_AVAILABLE'
        def dispatch(name,args,key):
            try:return env.call(name,args,case.authenticated_customer_id,key)
            finally:
                if env.audit:env.audit[-1]['decision_origin']='scripted:static-coverage'
        def call(name,args,key):return tracker.call(dispatch,name,args,key,source='skill')
        try:
            if all(name in case.parameters for name in skill.inputs):
                try:
                    hydrate(skill,state,case.parameters,call,case.task_id)
                    status=gate(skill,state,case.parameters).status
                    if status=='APPLICABLE':
                        event=execute(skill,case.parameters,state,call,case.task_id)
                        verdict=verify_workflow(case,initial,env.snapshot(),env.audit,'completed' if event['success'] else 'error',items,private_items(env))
                except ToolError as exc:
                    if exc.code not in {'permission_denied','not_found'}:raise
                    status='ENVIRONMENT_DENIED';event={'success':False,'error':exc.code}
            evidence.append({'skill_id':entry['skill_id'],'revision':entry['revision'],'status':status,
                'program_structure_hash':fingerprint({'inputs':sorted(skill.inputs),'calls':
                    [{'tool':n.tool,'arguments':n.arguments} for n in skill.procedure if n.kind=='call']}),
                # A refused/missing object is never positive full-goal coverage.
                'covers_goal':False,'event':event,'verification':verdict,'tool_audit':list(env.audit)})
        finally:env.close()
    return evidence


def continue_run(old, new):
    old,new=old.resolve(),new.resolve();report=base.read(old/'report.json');protocol=base.read(old/'protocol.json')
    base.check_sources(protocol)
    if report['failure']!='ToolError: permission_denied' or report['status']!='FAILED_OR_INCOMPLETE':
        raise ValueError('only diagnosed pre-model expected-denial CPU coverage interruption is eligible')
    if any(not s['completed'] for s in report['arm_statuses']):raise ValueError('unknown pending model work cannot be replayed')
    if sum(s['charged_tokens'] for s in report['arm_statuses'])!=report['costs']['charged_tokens']:raise ValueError('old charge ledger differs')
    failed=old/'heldout/is13-133008/ExperienceEvolution'
    if any(failed.glob('admissions/*.json')) or any(failed.glob('checkpoints/*/snapshot.json')):
        raise ValueError('failed task had an inference reservation; cannot retry automatically')
    # Original loop order may encounter the unauthorized arm under another
    # method; all failed task folders must have zero checkpoints/approvals.
    for folder in (old/'heldout/is13-133008').glob('*'):
        if any(folder.glob('admissions/*.json')) or any(folder.glob('checkpoints/*/snapshot.json')):
            raise ValueError('unauthorized task already reached model')
    new.mkdir(parents=True,exist_ok=False)
    for name in ['protocol.json','catalog.json']:
        shutil.copy2(old/name,new/name)
    shutil.copytree(old/'source-snapshot',new/'source-snapshot');shutil.copytree(old/'source-ledger',new/'source-ledger')
    reused={};file_index={}
    for status in report['arm_statuses']:
        relative=status['folder'];folder=old/relative
        receipt=base.read(folder/'independent-audit.json')
        if not receipt['passed'] or receipt['result_sha256']!=digest_file(folder/'result.json'):raise ValueError('old arm not audited')
        for file in folder.rglob('*'):
            if file.is_file():file_index[file.relative_to(old).as_posix()]=digest_file(file)
        shutil.copytree(folder,new/relative)
        reused[relative]=status
    body={'schema':'interview-cpu-coverage-continuation-v1','base_protocol_hash':protocol['hash'],
        'old_run':old.relative_to(base.ROOT).as_posix(),'original_partial_report_sha256':digest_file(old/'report.json'),
        'original_registration_sha256':digest_file(old/'run-registration.json'),
        'extension_source_sha256':digest_file(__file__),'extension':'expected permission_denied/not_found in static CPU coverage produces a negative coverage result',
        'reused_arm_count':len(reused),'reused_files':file_index,'prior_charged_tokens':report['costs']['charged_tokens'],
        'prior_wall_seconds':report['costs']['wall_seconds'],'runtime_changed':False,'eoc_changed':False,
        'candidate_changed':False,'task_or_gate_changed':False,'budget_refill':False,
        'incomplete_cpu_diagnostic_tools':'at least one denial; original helper did not persist a receipt before raising; exact count unavailable',
        'failed_task_model_requests':0}
    manifest={**body,'hash':fingerprint(body)};base.publish(new/'continuation-manifest.json',manifest)
    repaired=api.bind(base.old_collection.collect_one,{'verify_workflow':verify_workflow,
        'evaluate_static':safe_coverage,'prepare_snapshot':base.prepare})
    def collect(session,case,catalog,folder,config,prior_tokens,prior_wall,started):
        relative=folder.relative_to(new).as_posix()
        if relative in reused:
            row,status=base.read(folder/'result.json'),base.read(folder/'collection-status.json')
            if row['case']!=case.model_dump() or row['agent']['catalog_hash']!=catalog.hash or row['model_identity_hash']!=fingerprint(session.settings):
                raise ValueError('reused raw evidence differs from frozen case/catalog/model')
            return row,status
        return repaired(session,case,catalog,folder,config,prior_tokens,prior_wall,started)
    historical_config=base.read(old/'run-registration.json')['config']
    def audit(folder,case,catalog,settings,limits,charge):
        if folder.relative_to(new).as_posix() in reused:
            charge=(charge[0],charge[1],charge[2],historical_config['budget']['project_max_wall_seconds'])
        return base.audit_arm(folder,case,catalog,settings,limits,charge)
    api.bind(base.run,{'collect_one':collect,'audit_arm':audit})(new)
    final=base.read(new/'report.json')
    if final['costs']['charged_tokens']<report['costs']['charged_tokens']:raise ValueError('old charges were lost')
    for name,expected in file_index.items():
        if digest_file(old/name)!=expected or digest_file(new/name)!=expected:raise ValueError('reused physical evidence changed')
    base.publish(new/'continuation-reconciliation.json',{'manifest_hash':manifest['hash'],
        'original_partial_report_sha256':digest_file(old/'report.json'),'final_report_sha256':digest_file(new/'report.json'),
        'reused_arms':len(reused),'reused_model_tokens':report['costs']['charged_tokens'],
        'new_model_tokens':final['costs']['charged_tokens']-report['costs']['charged_tokens'],
        'total_unique_charged_tokens':final['costs']['charged_tokens'],
        'combined_collection_wall_seconds':report['costs']['wall_seconds']+final['costs']['wall_seconds'],
        'budget_refill':False,'original_failure_retained':True})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--old',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();continue_run(args.old,args.output)
