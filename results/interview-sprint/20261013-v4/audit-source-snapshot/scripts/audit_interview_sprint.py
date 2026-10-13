"""Post-freeze read-only full evidence audit; no model calls or candidate changes."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from skillforge.environment import Environment
from skillforge.evolution_schemas import fingerprint
from skillforge.evolution_common.artifacts import SplitLedger
from skillforge.skill_evolution.catalog import Catalog
from skillforge.skill_evolution.registry import verified_publication
from skillforge.skill_evolution.admission import paired_gate
from skillforge.interview_sprint import adapters as api
from skillforge.interview_sprint.workflows import WorkflowCase, private_items, verify_workflow
from scripts.run_interview_sprint import ROOT, read, publish, check_sources, forbidden_attempts
from scripts.run_skill_evolution import digest_file
from skillforge.skill_evolution.agent_evidence import semantic


def actual_database(path, case):
    env = Environment.__new__(Environment); env.order_id = case.fixture["order_id"]
    env.db = sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro", uri=True); env.db.row_factory = sqlite3.Row
    try: return env.snapshot(), private_items(env), list(env.db.iterdump())
    finally: env.close()


def audit(root):
    started = time.perf_counter(); root = Path(root).resolve()
    protocol, registration, report = read(root/'protocol.json'), read(root/'run-registration.json'), read(root/'report.json')
    if fingerprint({k:v for k,v in protocol.items() if k != 'hash'}) != protocol['hash'] or report['protocol_hash'] != protocol['hash']:
        raise ValueError('protocol/report identity mismatch')
    if registration['protocol_hash'] != protocol['hash']: raise ValueError('collection protocol differs')
    check_sources(protocol)
    continuation = None
    if (root/'continuation-manifest.json').exists():
        continuation = read(root/'continuation-manifest.json')
        if fingerprint({k:v for k,v in continuation.items() if k!='hash'}) != continuation['hash']:
            raise ValueError('continuation manifest differs')
        if continuation['base_protocol_hash'] != protocol['hash'] or continuation['budget_refill']:
            raise ValueError('continuation changed protocol or refilled budget')
        previous = ROOT/continuation['old_run']
        if digest_file(previous/'report.json') != continuation['original_partial_report_sha256'] or digest_file(previous/'run-registration.json') != continuation['original_registration_sha256']:
            raise ValueError('original partial report/registration changed')
        if digest_file(ROOT/'scripts/continue_interview_sprint.py') != continuation['extension_source_sha256']:
            raise ValueError('registered CPU continuation extension changed')
        for name,expected in continuation['reused_files'].items():
            if digest_file(previous/name)!=expected or digest_file(root/name)!=expected:
                raise ValueError('reused completed physical evidence changed')
    for name, expected in protocol['sources'].items():
        if digest_file(root/'source-snapshot'/name) != expected: raise ValueError('archived source differs')
    config = protocol['config']; settings = read(root/'model-identity.json')
    if settings.get('engineering_only') is not False or settings['adapter_sha256'] != config['adapter_sha256']:
        raise ValueError('real fixed main-v3 identity required')
    if digest_file(ROOT/config['adapter']/'adapter_model.safetensors') != config['adapter_sha256']:
        raise ValueError('main-v3 weights changed')
    if settings['system_prompt'] != api.runtime.SYSTEM_PROMPT: raise ValueError('model prompt changed')
    ledger = SplitLedger(root/'source-ledger')
    planned = {data['task_id']: data for split in ['train','validation','stable_validation','test','stable_test'] for data in protocol[split]}
    static = Catalog(protocol['static_catalog']); catalogs = {'PrimitiveOnly':Catalog([]),'StaticLibrary':static}
    if (root/'candidate-catalog.json').exists(): catalogs['ExperienceEvolution'] = Catalog(read(root/'candidate-catalog.json'))
    rows, learn, costs, tools, calls, cpu_coverage, replay_tools, checkpoints = [], [], 0, 0, 0, 0, 0, 0
    program_replay_tools = 0
    for status in report['arm_statuses']:
        folder = root/status['folder']; recorded_status = read(folder/'collection-status.json')
        if any(recorded_status[k] != v for k,v in status.items() if k in recorded_status): raise ValueError('status accounting differs')
        costs += status['charged_tokens']; cpu_coverage += status['static_evaluation_tool_calls']
        if not status['completed']: continue
        row, receipt = read(folder/'result.json'), read(folder/'independent-audit.json')
        case = WorkflowCase.model_validate(row['case'])
        if row['case'] != planned[case.task_id] or row['model_identity_hash'] != fingerprint(settings): raise ValueError('task or model mismatch')
        if row['agent']['catalog_hash'] != catalogs[status['method']].hash: raise ValueError('method catalog changed')
        phase_split = 'train' if status['phase']=='learn' else 'test' if status['phase']=='heldout' else 'validation'
        expected_split = ('stable_'+phase_split if row['case'] in protocol.get('stable_'+phase_split,[]) else phase_split)
        if any(ledger.owners.get(k) != expected_split for k in [case.source_group,case.task_id,case.parameters['order_id'],case.fixture['customer_id']]):
            raise ValueError('cross-split ownership')
        paths = sorted((folder/'checkpoints').glob('*/snapshot.json'),key=lambda p:int(p.parent.name))
        if [int(p.parent.name) for p in paths] != list(range(len(paths))): raise ValueError('noncontiguous checkpoints')
        initial = read(folder/'initial-snapshot/snapshot.json')
        if fingerprint(initial['body']) != initial['hash'] or initial['hash'] != row['snapshot_hash'] or initial['body']['audit']:
            raise ValueError('initial snapshot identity differs')
        if digest_file(folder/'initial-snapshot/environment.sqlite') != initial['body']['database_sha256']:
            raise ValueError('initial SQLite bytes differ')
        initial_state, initial_items, initial_dump = actual_database(folder/'initial-snapshot/environment.sqlite',case)
        if initial_state != row['initial_state'] or initial_items != row['initial_items']: raise ValueError('initial DB facts differ')
        env = Environment(fixture=case.fixture)
        try:
            if initial_dump != list(env.db.iterdump()): raise ValueError('initial DB is not declared fixture')
            replay_index = 0
            for path in paths:
                snap = read(path); body = snap['body']
                if fingerprint(body) != snap['hash'] or digest_file(path.parent/'environment.sqlite') != body['database_sha256']:
                    raise ValueError('checkpoint/SQLite integrity mismatch')
                prefix = body['audit']
                if semantic(prefix) != semantic(row['tool_audit'][:len(prefix)]) or len(prefix) < replay_index:
                    raise ValueError('checkpoint audit prefix is not actual tool history')
                while replay_index < len(prefix):
                    event = prefix[replay_index]
                    try: env.call(event['tool_name'],event['arguments'],event['authenticated_customer_id'],event['request_id'])
                    except Exception as exc:
                        if getattr(exc,'code',None) != event['error']: raise
                    if semantic(env.audit[-1]) != semantic({k:v for k,v in event.items() if k!='decision_origin'}):
                        raise ValueError('actual tool receipt differs')
                    replay_index += 1
                state, items, dump = actual_database(path.parent/'environment.sqlite',case)
                if dump != list(env.db.iterdump()) or state != env.snapshot() or items != private_items(env):
                    raise ValueError('checkpoint SQLite effects differ from actual replay')
                checkpoints += 1
            if replay_index != len(row['tool_audit']): raise ValueError('tools missing from checkpoints')
            final_state, final_items, final_dump = actual_database(folder/'live.sqlite',case)
            if final_dump != list(env.db.iterdump()) or final_state != row['final_state'] or final_items != row['final_items']:
                raise ValueError('final SQLite or row facts differ')
            if final_dump != initial_dump: raise ValueError('read-only task changed database')
            verdict = verify_workflow(case,initial_state,final_state,row['tool_audit'],row['agent']['outcome'],initial_items,final_items)
            if verdict != row['verification']: raise ValueError('independent final EOC differs')
        finally: env.close()
        if not receipt['passed'] or receipt['result_sha256'] != digest_file(folder/'result.json') or receipt['charged_tokens'] != status['charged_tokens']:
            raise ValueError('recorded-response audit receipt differs')
        if receipt['checkpoints'] != len(paths): raise ValueError('audit checkpoint count mismatch')
        if row['agent']['metrics']['tokens'] != status['charged_tokens'] or row['agent']['metrics']['tool_calls'] != len(row['tool_audit']):
            raise ValueError('arm cost totals differ')
        rows.append({'phase':status['phase'],'method':status['method'],'row':row}); tools += len(row['tool_audit'])
        calls += row['agent']['metrics']['llm_calls']; replay_tools += replay_index
        if status['phase']=='learn': learn.append(row)
    if report['costs']['charged_tokens'] != costs or report['costs']['model_calls'] != calls or report['costs']['tool_calls'] != tools or report['costs']['static_coverage_tool_calls'] != cpu_coverage:
        raise ValueError('aggregate collection costs differ')
    if (root/'opportunity-screen.json').exists():
        screen = api.mine_opportunities(learn,settings)
        if screen != read(root/'opportunity-screen.json'): raise ValueError('miner differs from saved actual train evidence')
        proposal = api.compile_screen(screen)
        if proposal != read(root/'candidate-screen.json'): raise ValueError('candidate/node provenance differs from recompiled train evidence')
        candidates = [x['candidate'] for x in proposal['results'] if x['candidate']]
        if report['candidate_count'] != len(candidates): raise ValueError('candidate count differs')
        if report['program_admitted']:
            receipt = read(root/'program-admission.json'); functions = api.validation_functions()
            program_audit = functions['audit_program_admission'](receipt)
            program_replay_tools = program_audit['replay_tool_calls']
            if receipt['report']['protocol']['learn_candidate'] not in candidates: raise ValueError('program admission not bound to real compiled candidate')
            if verified_publication(read(root/'candidate-entry.json')) not in catalogs['ExperienceEvolution'].entries():
                raise ValueError('publication changed candidate program')
    if (root/'agent-paired-gate.json').exists():
        gate = read(root/'agent-paired-gate.json')
        if paired_gate(read(root/'paired-validation-protocol.json'),gate['pairs']) != gate: raise ValueError('paired arithmetic differs')
        by_task = {(x['row']['case']['task_id'],x['method']): x['row'] for x in rows if x['phase']=='agent-validation'}
        for pair in gate['pairs']:
            for name,method in [('baseline','StaticLibrary'),('candidate','ExperienceEvolution')]:
                row = by_task[(pair['task_id'],method)]; arm = pair[name]; verdict = row['verification']
                if (pair['source_group'] != row['case']['source_group'] or pair['task_hash'] != fingerprint(row['case']) or
                    pair['initial_state_hash'] != fingerprint({'state':row['initial_state'],'items':row['initial_items'],
                        'auth':row['case']['authenticated_customer_id']})):
                    raise ValueError('paired task/source/initial-state is not independently bound')
                expected = {'eoc':verdict['task_success'],'model_calls':row['agent']['metrics']['llm_calls'],
                    'tokens':row['agent']['metrics']['tokens'],'evidence_hash':fingerprint(row),
                    'attempted_violations':int(verdict['attempted_policy_violation'])+forbidden_attempts(row),
                    'actual_violations':int(verdict['actual_policy_violation']),'workflow_violations':int(verdict['actual_workflow_violation'])}
                if any(arm[k] != v for k,v in expected.items()): raise ValueError('paired gate is not grounded in raw Agent arms')
        if report['agent_admitted'] != gate['statistical_gate_passed']: raise ValueError('Agent admission differs')
    for prior in protocol['prior_attempts']:
        if digest_file(ROOT/prior['run']/'report.json') != prior['report_sha256']: raise ValueError('old failed attempt changed')
    if report['status']=='COMPLETE':
        expected = len(protocol['train'])+3*sum(len(protocol[k]) for k in ['validation','stable_validation','test','stable_test'])
        if len(rows) != expected: raise ValueError('complete report is missing planned arms')
    if continuation:
        reconciliation=read(root/'continuation-reconciliation.json')
        if reconciliation['manifest_hash']!=continuation['hash'] or reconciliation['final_report_sha256']!=digest_file(root/'report.json'):
            raise ValueError('continuation reconciliation/report differs')
        if (reconciliation['total_unique_charged_tokens']!=costs or reconciliation['reused_model_tokens']!=continuation['prior_charged_tokens'] or
            reconciliation['new_model_tokens']!=costs-continuation['prior_charged_tokens'] or reconciliation['budget_refill']):
            raise ValueError('continued unique inference fees differ')
    body = {'passed':True,'status':report['status'],'protocol_hash':protocol['hash'],'report_sha256':digest_file(root/'report.json'),
        'auditor_sha256':digest_file(__file__),'model_calls':0,'tokens':0,'actual_sqlite_replay_tool_calls':replay_tools,
        'continuation_manifest_hash':continuation['hash'] if continuation else None,
        'program_validation_replay_tool_calls':program_replay_tools,
        'checkpoints':checkpoints,'completed_arms':len(rows),'independent_train_sources':len({r['case']['source_group'] for r in learn}),
        'wall_seconds':time.perf_counter()-started,'scope':'protocol/source archive, actual initial/every checkpoint/final SQLite, raw receipt causality, recompilation from real train, independent program replay, raw paired admission and fees'}
    publish(root/'final-independent-audit.json',body)
    return body


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--run',type=Path,required=True)
    print(json.dumps(audit(parser.parse_args().run),ensure_ascii=False))
