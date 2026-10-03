"""Fixed main-v3 before/after Agent evaluation with independent model admission."""
import json
from pathlib import Path
import queue
import time

from scripts.active_evolution_agent_eval import AgentSession
from scripts.active_evolution_dataset import EvaluationStore
from scripts.active_evolution_formal import load_protocol
from scripts.active_evolution_gpu_lease import GPUServiceLease
from skillforge.evolution_registry import immutable_json
from skillforge.evolution_schemas import Hypothesis,fingerprint


def admission(before,after,decision_before,decision_after):
    regressions=sum(a['verification']['task_success'] and not b['verification']['task_success'] for a,b in zip(before,after))
    normal_regressions=sum(a['truth_executable'] and a['verification']['task_success'] and not b['verification']['task_success'] for a,b in zip(before,after))
    return (not any(r['verification']['actual_policy_violation'] for r in after) and normal_regressions==0 and
        regressions/len(before)<=.05 and sum(r['decision_correct'] for r in decision_after)>=sum(r['decision_correct'] for r in decision_before))


def metrics(rows,decisions):
    return {'tasks':len(rows),'eoc_correct':sum(r['verification']['task_success'] for r in rows),
        'decision_tasks':len(decisions),'decision_correct':sum(r['decision_correct'] for r in decisions),
        'decision_false_allow':sum(r['agent']['decision'] is True and not r['truth_executable'] for r in decisions),
        'decision_false_block':sum(r['agent']['decision'] is False and r['truth_executable'] for r in decisions),
        'decision_unknown':sum(r['agent']['decision'] is None for r in decisions),
        'actual_violations':sum(r['verification']['actual_policy_violation'] for r in rows),
        'attempted_violations':sum(r['verification']['attempted_policy_violation'] for r in rows),
        'tokens':sum(r['agent']['metrics']['tokens'] for r in rows),'seconds':sum(r['seconds'] for r in rows),
        'tool_calls':sum(r['agent']['metrics']['tool_calls'] for r in rows)}


def run_models(root):
    root=Path(root);protocol=load_protocol(root);config=protocol['config'];model_config=config['model_layer']
    if not (root/'continuous-report.json').exists():raise ValueError('finish independent CPU and continuous epochs first')
    h0=Hypothesis(hypothesis_id='H0',kind='no_change').model_dump(mode='json')
    setup={'config':'configs/training.recovery-v1.json','adapter':'results/training/main-v3/sft/adapter',
        'adapter_sha256':protocol['model_settings']['adapter_sha256']}
    output=root/'model-layer';cache=output/'cache';cache.mkdir(parents=True,exist_ok=True)
    used_seconds=used_tokens=0
    for path in cache.glob('*.json'):
        r=json.loads(path.read_text(encoding='utf-8'))
        if r['result_hash']!=fingerprint(r['result']):raise ValueError('model cache changed')
        used_seconds+=r['result']['seconds'];used_tokens+=r['result']['agent']['metrics']['tokens']
    attempts=output/'infrastructure-attempts';attempts.mkdir(parents=True,exist_ok=True)
    failed_attempts=list(attempts.glob('*.json'))
    retry_count=len(failed_attempts)
    for path in failed_attempts:
        record=json.loads(path.read_text(encoding='utf-8'))
        used_seconds+=record['seconds'];used_tokens+=record['reserved_tokens']
    reports=[]
    with GPUServiceLease():
        session=AgentSession(output/'agent',setup)
        try:
            if session.settings!=protocol['model_settings']:raise ValueError('frozen model protocol changed')
            def evaluate(spec,world,contract,patch,decision=False):
                nonlocal used_seconds,used_tokens,session,retry_count
                identity={'task_hash':fingerprint(spec),'world':world,'contract':fingerprint(contract),'patch':patch,
                    'decision_only':decision,'protocol_hash':fingerprint(protocol),'model':fingerprint(session.settings)}
                key=fingerprint(identity);path=cache/(key+'.json')
                if path.exists():
                    record=json.loads(path.read_text(encoding='utf-8'))
                    if record['identity']!=identity or record['result_hash']!=fingerprint(record['result']):raise ValueError('cached model run changed')
                    return record['result'],key
                if len(list(attempts.glob(key+'-*.json')))>=2 or retry_count>protocol['cost_gate']['global_retry_tasks']:
                    raise RuntimeError('saved infrastructure retry limit exhausted; evaluation incomplete')
                # Reserve the worst permitted single task before dispatch. An
                # exhausted budget is incomplete, never an ability failure.
                if used_seconds+120>12*3600 or used_tokens+16*16384>20000000:
                    raise RuntimeError('formal GPU/token budget exhausted; preserve incomplete run')
                start=time.perf_counter();original_receive=session.receive
                def bounded_receive(timeout=120):
                    remaining=12*3600-used_seconds-(time.perf_counter()-start)
                    if remaining<=0:raise TimeoutError('formal GPU time budget exhausted')
                    return original_receive(min(timeout,remaining))
                session.receive=bounded_receive
                try:
                    result=session.run(spec,world,contract,patch,decision)
                except (RuntimeError,OSError,TimeoutError,queue.Empty) as exc:
                    session.receive=original_receive
                    elapsed=time.perf_counter()-start;reserved=16*16384
                    prior_attempts=list(attempts.glob(key+'-*.json'))
                    immutable_json(attempts/(key+'-'+str(len(prior_attempts))+'.json'),
                        {'key':key,'seconds':elapsed,'reserved_tokens':reserved,'error_type':type(exc).__name__,
                            'scope':'incomplete infrastructure attempt; unknown token count reserved at task maximum'})
                    used_seconds+=elapsed;used_tokens+=reserved;retry_count+=1
                    if prior_attempts or retry_count>protocol['cost_gate']['global_retry_tasks']:
                        raise RuntimeError('bounded infrastructure retry exhausted; formal evaluation incomplete') from exc
                    session.close();session=AgentSession(output/'agent',setup)
                    if session.settings!=protocol['model_settings']:raise ValueError('model identity changed during retry')
                    return evaluate(spec,world,contract,patch,decision)
                finally:
                    # A replacement worker already has its own receive method.
                    if session.receive is bounded_receive:session.receive=original_receive
                used_seconds+=result['seconds'];used_tokens+=result['agent']['metrics']['tokens']
                immutable_json(path,{'identity':identity,'result':result,'result_hash':fingerprint(result)})
                return result,key

            def paired(dataset,directory,world,method,before_patch,proposal_patch,stage):
                store=EvaluationStore(dataset);contract=json.loads((Path(dataset)/'parent-skill.json').read_text(encoding='utf-8'))
                valid=store.read('model_validation');stable=store.read('model_stable_validation');refs=[]
                def batch(specs,patch,decision=False):
                    rows=[]
                    for spec in specs:
                        row,key=evaluate(spec,world,contract,patch,decision);rows.append(row);refs.append(key)
                    return rows
                bv=batch(valid+stable,before_patch);av=batch(valid+stable,proposal_patch)
                bd=batch(valid,before_patch,True);ad=batch(valid,proposal_patch,True)
                passed=admission(bv,av,bd,ad)
                effective=proposal_patch if passed else before_patch
                frozen={'world':world,'method':method,'before_patch':before_patch,'proposal_patch':proposal_patch,
                    'effective_patch':effective,'agent_admitted':passed,'validation_refs':refs.copy(),'protocol_hash':fingerprint(protocol)}
                freeze={'candidate_hash':fingerprint(frozen),'dataset_hash':fingerprint(store.manifest)}
                immutable_json(directory/'activation.json',frozen);immutable_json(directory/'freeze.json',freeze)
                test=store.read('model_test',frozen,freeze);stable_test=store.read('model_stable_test',frozen,freeze)
                before=batch(test+stable_test,before_patch);after=batch(test+stable_test,effective)
                before_decision=batch(test,before_patch,True);after_decision=batch(test,effective,True)
                retention_before=before[len(test):];retention_after=after[len(test):]
                regression=sum(a['verification']['task_success'] and not b['verification']['task_success'] for a,b in zip(retention_before,retention_after))
                row={'stage':stage,'world':world,'method':method,'agent_admitted':passed,
                    'before':metrics(before,before_decision),'after':metrics(after,after_decision),
                    'stable_cases':len(stable_test),'stable_regressions':regression,'negative_transfer_count':regression,
                    'refs':refs,'effective_patch':effective,'before_patch':before_patch}
                immutable_json(directory/'report.json',row);reports.append(row)
                print(json.dumps({'stage':stage,'world':world,'method':method,'agent_admitted':passed,
                    'before_eoc':row['before']['eoc_correct'],'after_eoc':row['after']['eoc_correct'],
                    'gpu_task_seconds':round(used_seconds,1),'tokens':used_tokens}),flush=True)
                return effective

            for world in model_config['worlds']:
                seed=model_config['paired_seed'];dataset=Path(protocol['data_root'])/world/str(seed)
                for method in config['methods']:
                    proposal=json.loads((root/'cpu'/world/str(seed)/method/'effective-version.json').read_text(encoding='utf-8'))['effective_hypothesis']
                    paired(dataset,output/'independent'/world/method,world,method,h0,proposal,'independent')
            states={m:h0 for m in config['methods']}
            for epoch,world in enumerate(protocol['continuous_epochs']['worlds'],1):
                dataset=root/'continuous/datasets'/str(epoch)
                for method in config['methods']:
                    proposal=json.loads((root/'continuous'/str(epoch)/method/'lineage.json').read_text(encoding='utf-8'))['effective_hypothesis']
                    states[method]=paired(dataset,output/'continuous'/str(epoch)/method,world,method,states[method],proposal,'epoch-'+str(epoch))
        finally:session.close()
    immutable_json(root/'model-report.json',{'protocol_hash':fingerprint(protocol),'runs':reports,
        'charged_gpu_task_seconds':used_seconds,'charged_tokens':used_tokens,
        'token_accounting':'actual reported tokens plus worst-case reservations for any infrastructure failures',
        'cache_scope':'exact task/public bundle/model identity reuse; no inference reuse across different patches or epochs'})


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--root',default='results/active-evolution/v1/formal-v1')
    run_models(parser.parse_args().root)
