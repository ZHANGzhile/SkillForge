"""Read-only evidence audit, separate from frozen A inference and admission code."""
import argparse
from collections import Counter
from dataclasses import asdict
from pathlib import Path
import uuid

from scripts.active_evolution_dataset import EvaluationStore
from scripts.active_evolution_worlds import policy
from scripts.execution_aware_formal import H0, agent_admission, different, load, read
from scripts.prepare_active_evolution import file_hash
from skillforge.evolution_registry import immutable_json
from skillforge.evolution_schemas import fingerprint
from skillforge.execution_aware.contracts import VerificationReceipt
from skillforge.schemas import Task, ExpectedOutcome
import skillforge.verifier as verifier


def require(condition, message):
    if not condition:
        raise ValueError(message)


def audit_result(result, spec, world, runtime):
    """Recheck private outcomes and bind immutable receipts to raw tool evidence."""
    require(result['spec_hash'] == fingerprint(spec), 'task identity mismatch')
    agent, audit = result['agent'], result['tool_audit']
    require(agent['metrics']['tool_calls'] == len(audit), 'tool-call accounting mismatch')
    require(agent['metrics']['llm_calls'] == len(agent['steps']), 'model-call accounting mismatch')
    tool = 'update_shipping_address' if spec['family'] == 'modify_address' else 'issue_refund'
    initial, final = result['initial_state'], result['final_state']
    disposition = policy(world, tool, initial, spec['parameters'])
    require(result['truth_executable'] is (disposition == 'allow'), 'truth mismatch')
    require(result['decision_correct'] == (agent['decision'] is (disposition == 'allow')), 'decision scoring mismatch')
    expected = {}
    if disposition == 'allow':
        expected = ({'order.shipping_address': spec['parameters']['new_address']} if spec['family'] == 'modify_address'
                    else {'payment.refunded_amount': initial['payment.refunded_amount']+spec['parameters']['amount']})
    task = Task(task_id=spec['task_id'], family=spec['family'], request=spec['request'],
                parameters=spec['parameters'], customer_id=spec['fixture']['customer_id'], split='validation',
                template_id=spec['template'], seed=0, expected=ExpectedOutcome(
                    allowed_outcomes=[{'allow': 'completed', 'refuse': 'refused', 'escalate': 'escalated'}[disposition]],
                    expected_state=expected))
    prior = verifier.eligibility
    try:
        verifier.eligibility = lambda name, state, args: policy(world, name, state, args)
        recomputed = verifier.verify(task, initial, final, audit, agent['outcome'])
    finally:
        verifier.eligibility = prior
    require(recomputed == result['verification'], 'private verifier differs')
    if runtime == 'old':
        return {'receipts': 0, 'interventions': 0}
    checkpoint = agent['execution_contract']; body = checkpoint['body']
    require(checkpoint['hash'] == fingerprint(body), 'checkpoint hash mismatch')
    require(body['task_id'] == spec['task_id'], 'checkpoint task mismatch')
    events = body['events']
    require([e['sequence'] for e in events] == list(range(1, body['sequence']+1)), 'noncontiguous execution events')
    interventions = [e for e in events if e['kind'] == 'intervention']
    counts = {'runtime_intervention_count': len(interventions),
              'forced_readback_count': sum(e['action'] == 'forced_readback' for e in interventions),
              'auto_termination_count': sum(e['action'] == 'auto_termination' for e in interventions)}
    require(agent['interventions'] == counts, 'intervention accounting mismatch')
    require((agent['termination_source'] == 'runtime') == bool(counts['auto_termination_count']), 'termination source mismatch')
    receipts = [VerificationReceipt(**r) for r in body['receipts']]
    require([r.to_dict() for r in receipts] == agent['verification_receipts'], 'receipt export mismatch')
    for receipt in receipts:
        exported = receipt.to_dict(); op = body['operations'][receipt.request_id]
        require(receipt.receipt_id == fingerprint(asdict(receipt)), 'receipt identity mismatch')
        require(receipt.mutation_id == op['mutation_id'] and receipt.object_id == op['object_id']
                and receipt.mutation_tool == op['tool'] and exported['expected_postcondition'] == op['expected'],
                'receipt operation binding mismatch')
        require(any(e['kind'] == 'verification' and e['receipt_id'] == receipt.receipt_id for e in events), 'unrecorded receipt')
        if receipt.status != 'VERIFIED':
            continue
        observed = exported['observed_value']; args = {'order_id': receipt.object_id}
        event = events[receipt.event_sequence-1]
        require(event['kind'] == 'observation' and event['tool'] == receipt.verification_tool
                and event['object_id'] == receipt.object_id and event['result'] == observed, 'receipt observation missing')
        require(receipt.evidence_hash == fingerprint([receipt.mutation_id, receipt.event_sequence,
                receipt.verification_tool, args, observed]), 'receipt evidence hash mismatch')
        require(all(k in observed and type(observed[k]) is type(v) and observed[k] == v
                    for k, v in op['expected'].items()), 'verified postcondition false')
        writes = [i for i, row in enumerate(audit) if row['request_id'] == receipt.request_id
                  and row['tool_name'] == receipt.mutation_tool and row['arguments'] == op['arguments']
                  and row['committed'] and not row['error']]
        require(bool(writes), 'receipt lacks authoritative committed write')
        require(any(row['tool_name'] == receipt.verification_tool and row['arguments'] == args
                    and not row['error'] and row['result'] == observed for row in audit[max(writes)+1:]),
                'receipt lacks matching fresh raw read-back')
    return {'receipts': len(receipts), 'interventions': len(interventions)}


def execution_partition(rows):
    """Descriptive success attribution within one complete FullSystem arm."""
    require(bool(rows) and len({r['spec_hash'] for r in rows}) == len(rows), 'unique nonempty FullSystem arm required')
    require(not any(r['decision_only'] for r in rows), 'Decision probes cannot enter EOC partition')
    success = sum(r['verification']['task_success'] for r in rows)
    helped = [r['agent'].get('interventions', {}).get('runtime_intervention_count', 0) > 0 for r in rows]
    assisted = sum(r['verification']['task_success'] and h for r, h in zip(rows, helped))
    counts = {'eoc': success, 'autonomous_eoc': success-assisted, 'runtime_assisted_eoc': assisted,
              'runtime_intervention_rate': sum(helped),
              'forced_readback_count': sum(r['agent'].get('interventions', {}).get('forced_readback_count', 0) for r in rows),
              'auto_termination_count': sum(r['agent'].get('interventions', {}).get('auto_termination_count', 0) for r in rows)}
    return {'n': len(rows), 'counts': counts,
            'rates': {k: v/len(rows) for k, v in counts.items() if not k.endswith('_count')},
            'actual_violations': sum(r['verification']['actual_policy_violation'] for r in rows),
            'tokens': sum(r['agent']['metrics']['tokens'] for r in rows),
            'tool_calls': sum(r['agent']['metrics']['tool_calls'] for r in rows),
            'llm_calls': sum(r['agent']['metrics']['llm_calls'] for r in rows)}


def audit_group(root, protocol, dataset, directory, boundary, breakdown=None):
    """Rebuild validation gates and held-out arm assignments from referenced tasks."""
    activation = read(directory/'activation.json'); report = read(directory/'report.json')
    store = EvaluationStore(dataset); contract = read(dataset/'parent-skill.json')
    freeze_record = read(directory/'evaluation-freeze.json'); refs = []
    def rows(split, runtime, patch, decision=False):
        out = []
        for spec in store.read(split, activation, freeze_record):
            identity = {'task_hash': fingerprint(spec), 'world': activation['world'], 'contract': fingerprint(contract),
                        'patch': patch, 'runtime': runtime, 'decision_only': decision,
                        'protocol_hash': fingerprint(protocol), 'model': fingerprint(protocol['model_settings'])}
            key = fingerprint(identity); record = read(root/'model-layer/cache'/(key+'.json'))
            require(record['identity'] == identity, 'arm assignment mismatch')
            refs.append(key); out.append(record['result'])
        return out
    for runtime in ('old', 'new'):
        parent = activation['actual_agent_parents'][runtime]; proposal = activation['proposal']
        a = rows('model_validation', runtime, parent)+rows('model_stable_validation', runtime, parent)
        b = rows('model_validation', runtime, proposal)+rows('model_stable_validation', runtime, proposal)
        da = rows('model_validation', runtime, parent, True); db = rows('model_validation', runtime, proposal, True)
        gate = agent_admission(a, b, da, db, len(da))
        nontrivial = different(contract, parent, proposal, store.read('explore'))
        admitted = boundary['boundary_admitted'] and nontrivial and gate['passed']
        expected = {**gate, 'nontrivial': nontrivial, 'agent_admitted': admitted,
                    'effective_patch': proposal if admitted else parent}
        require(activation['runtime_admission'][runtime] == expected, 'validation admission mismatch')
    require(refs == activation['validation_refs'], 'validation provenance mismatch')
    ntest = len(store.read('model_test', activation, freeze_record)); tests = {}; decisions = {}
    for runtime in ('old', 'new'):
        patches = {'old': activation['canonical_parent'], 'proposal': activation['proposal'],
                   'agent_parent': activation['actual_agent_parents'][runtime]}
        tests[runtime] = {phase: rows('model_test', runtime, patch)+rows('model_stable_test', runtime, patch)
                          for phase, patch in patches.items()}
        decisions[runtime] = {phase: rows('model_test', runtime, patch, True) for phase, patch in patches.items()}
    require(refs == report['refs'], 'complete group provenance mismatch')
    eoc = lambda cases: sum(r['verification']['task_success'] for r in cases)/len(cases)
    for runtime in ('old', 'new'):
        gate = activation['runtime_admission'][runtime]
        effective = 'proposal' if gate['agent_admitted'] else 'agent_parent'
        for phase in ('old', 'proposal'):
            key = runtime+'_'+phase
            require(report['candidate_arms'][key] == eoc(tests[runtime][phase][:ntest]), 'candidate arm EOC mismatch')
            require(report['effective_arms'][key] == eoc(tests[runtime][effective if phase == 'proposal' else 'agent_parent'][:ntest]), 'effective arm EOC mismatch')
        result = report['runtime_results'][runtime]
        require(result['effective_patch'] == gate['effective_patch'] and result['agent_admitted'] == gate['agent_admitted'], 'test changed frozen activation')
        for label, phase in (('before', 'agent_parent'), ('after', effective)):
            full = tests[runtime][phase]; decision = decisions[runtime][phase]
            require(result[label+'_new_eoc'] == eoc(full[:ntest]), 'effective EOC mismatch')
            require(result['decision_tasks'] == len(decision), 'Decision denominator mismatch')
            metrics = {'correct': sum(r['decision_correct'] for r in decision),
                       'false_allow': sum(r['agent']['decision'] is True and not r['truth_executable'] for r in decision),
                       'false_block': sum(r['agent']['decision'] is False and r['truth_executable'] for r in decision),
                       'unknown': sum(r['agent']['decision'] is None for r in decision)}
            for key, value in metrics.items():
                require(result[label+'_decision_'+key] == value, 'effective Decision '+key+' mismatch')
            for key in ('tokens', 'tool_calls', 'llm_calls'):
                require(result[label+'_'+key] == sum(r['agent']['metrics'][key] for r in full), 'effective cost mismatch')
            require(result[label+'_seconds'] == sum(r['seconds'] for r in full), 'effective wall time mismatch')
        a, b = tests[runtime]['agent_parent'], tests[runtime][effective]
        require(result['actual_violations'] == sum(r['verification']['actual_policy_violation'] for r in b), 'effective actual violation mismatch')
        require(result['attempted_violations'] == sum(r['verification']['attempted_policy_violation'] for r in b), 'effective attempted violation mismatch')
        require(result['stable_regressions'] == sum(x['verification']['task_success'] and not y['verification']['task_success'] for x,y in zip(a[ntest:],b[ntest:])), 'stable retention mismatch')
        require(result['normal_regressions'] == sum(x['truth_executable'] and x['verification']['task_success'] and not y['verification']['task_success'] for x,y in zip(a,b)), 'normal retention mismatch')
    from skillforge.execution_aware.metrics import paired_execution_metrics
    require(report['runtime_assistance'] == paired_execution_metrics(tests['old']['old'], tests['new']['old']), 'Runtime assistance mismatch')
    require(report['boundary'] == activation['boundary'], 'Boundary provenance mismatch')
    if breakdown is not None:
        for scope in ('candidate', 'effective'):
            breakdown[scope] = {}
            for runtime in ('old', 'new'):
                for arm in ('old', 'proposal'):
                    phase = arm if scope == 'candidate' else ('proposal' if arm == 'proposal' and activation['runtime_admission'][runtime]['agent_admitted'] else 'agent_parent')
                    full = tests[runtime][phase]
                    breakdown[scope][runtime+'_'+arm] = {'changed': execution_partition(full[:ntest]),
                        'stable': execution_partition(full[ntest:]), 'all_test': execution_partition(full)}
        breakdown['matched_candidate_bundle_rescue'] = {phase: paired_execution_metrics(tests['old'][phase], tests['new'][phase]) for phase in ('old', 'proposal')}
        breakdown['scope'] = 'descriptive per-arm partition; candidate is CPU-admitted effective proposal; effective rescue across different bundles is not attributed solely to Runtime'
    return report


def audit(root):
    root = Path(root); protocol = load(root); protocol_hash = fingerprint(protocol)
    specs, memberships, contract_hashes = {}, {}, {}
    config = protocol['config']
    groups = [(world, seed, Path(protocol['data_root'])/world/str(seed), root/'model-layer/independent'/world/str(seed))
              for world in config['worlds'] for seed in config['paired_seeds']]
    groups += [(world, config['continual']['seed'], root/'continuous/datasets'/str(epoch), root/'model-layer/continuous'/str(epoch))
               for epoch, world in enumerate(config['continual']['worlds'], 1)]
    completed_groups = []
    for world, seed, dataset, output in groups:
        store = EvaluationStore(dataset)
        contract = fingerprint(read(dataset/'parent-skill.json'))
        splits = ['model_validation', 'model_stable_validation']
        activation, freeze_record = None, None
        if (output/'evaluation-freeze.json').exists():
            activation = read(output/'activation.json'); freeze_record = read(output/'evaluation-freeze.json')
            require(activation['protocol_hash'] == protocol_hash, 'activation protocol mismatch')
            splits += ['model_test', 'model_stable_test']
        for split in splits:
            for spec in store.read(split, activation, freeze_record):
                key = fingerprint(spec); specs[key] = spec
                memberships[key] = (world, split); contract_hashes[key] = contract
        if (output/'report.json').exists():
            report = read(output/'report.json')
            require(report['complete'], 'incomplete group published')
            require(report['test_freeze'] == freeze_record, 'group freeze mismatch')
            for key in report['refs']:
                require((root/'model-layer/cache'/(key+'.json')).exists(), 'missing referenced evaluation')
            completed_groups.append({'world': world, 'seed': seed, 'path': output.as_posix(), 'hash': fingerprint(report)})
    totals = Counter(); result_hashes = {}
    for path in sorted((root/'model-layer/cache').glob('*.json')):
        record = read(path); identity = record['identity']; result = record['result']
        require(path.stem == fingerprint(identity) and record['result_hash'] == fingerprint(result), 'cache integrity mismatch')
        require(identity['protocol_hash'] == protocol_hash and identity['model'] == fingerprint(protocol['model_settings']), 'cache protocol/model mismatch')
        key = identity['task_hash']; require(key in specs, 'task outside admitted public splits')
        require(identity['contract'] == contract_hashes[key] and identity['world'] == memberships[key][0], 'contract/world mismatch')
        require(identity['decision_only'] == result['decision_only'], 'mode mismatch')
        require(result['agent']['model_settings'] == protocol['model_settings'], 'actual model settings mismatch')
        require(result['agent']['policy_view']['patch'] == identity['patch'], 'actual policy patch mismatch')
        detail = audit_result(result, specs[key], identity['world'], identity['runtime'])
        totals.update(detail); totals['tokens'] += result['agent']['metrics']['tokens']; totals['executions'] += 1
        totals['decision_executions' if result['decision_only'] else 'full_executions'] += 1
        result_hashes[path.name] = file_hash(path)
    failures = list((root/'model-layer/failures').glob('*.json'))
    reserved = sum(read(p)['reserved_tokens'] for p in failures)
    invocation_finals = list((root/'model-layer/invocations').glob('*.final.json'))
    running = [p.name for p in (root/'model-layer/invocations').glob('*.start.json')
               if not p.with_name(p.name.replace('.start.json', '.final.json')).exists()]
    report = {'protocol_hash': protocol_hash, 'passed': True, 'totals': dict(totals),
              'completed_groups': completed_groups, 'cache_file_hashes': result_hashes,
              'infrastructure_failures': len(failures), 'reserved_failure_tokens': reserved,
              'charged_tokens_all_v11': protocol['prior_charged_tokens']+totals['tokens']+reserved,
              'closed_invocation_seconds_all_v11': protocol['prior_invocation_seconds']+sum(read(p)['seconds'] for p in invocation_finals),
              'open_invocations': running, 'complete': (root/'model-report.json').exists() and not running,
              'scope': 'read-only snapshot; in-flight tasks and open invocation time are not final resource totals',
              'auditor_sha256': file_hash(__file__)}
    from scripts.execution_resource_accounting import sleep_accounting
    report['resource_accounting'] = sleep_accounting(root, protocol)
    for binding in (root/'recovery/sleep-20261005').glob('binding-*.json'):
        value = read(binding)
        require(value['amendment_hash'] == report['resource_accounting']['amendment_hash'], 'continuation amendment mismatch')
        require(read(root/'model-layer/invocations'/(value['invocation']+'.start.json'))['protocol_hash'] == protocol_hash,
                'continuation invocation mismatch')
    if report['complete']:
        final = read(root/'model-report.json')
        require(final['charged_tokens_all_v11'] == report['charged_tokens_all_v11'], 'final token accounting mismatch')
        require(len(final['independent']) == len(config['worlds'])*len(config['paired_seeds']), 'incomplete independent matrix')
        require(len(final['continuous']) == len(config['continual']['worlds']), 'incomplete continual chain')
        from skillforge.execution_aware.admission import AdmissionEvidence, admission_funnel
        from skillforge.execution_aware.factorial import paired_factorial
        for runtime in ('old', 'new'):
            evidence = [AdmissionEvidence(f"{r['world']}/{r['seed']}", 'active', True,
                r['boundary']['nontrivial'], r['boundary']['belief_converged'], r['boundary']['boundary_validation_passed'],
                True, r['runtime_results'][runtime]['agent_admitted'], r['runtime_results'][runtime]['agent_admitted'])
                for r in final['independent']]
            require(final['funnel'][runtime] == admission_funnel(evidence), 'aggregate funnel mismatch')
        for scope in ('candidate', 'effective'):
            effects = paired_factorial([{**r, 'bundle_scope': scope, 'arms': r[scope+'_arms']} for r in final['independent']],
                seed=protocol['bootstrap']['seed'], replicates=protocol['bootstrap']['replicates'])
            require(final['factorial'][scope] == effects, 'aggregate factorial mismatch')
        cpu = read(root/'cpu-report.json'); parents = {'old': H0, 'new': H0}; nodes = {'old': None, 'new': None}
        report['per_group_execution_attribution'] = []
        for index, (world, seed, dataset, directory) in enumerate(groups):
            independent = index < len(cpu['independent'])
            offset = index if independent else index-len(cpu['independent'])
            boundary = cpu['independent' if independent else 'continuous'][offset]
            breakdown = {}
            checked = audit_group(root, protocol, dataset, directory, boundary, breakdown)
            report['per_group_execution_attribution'].append({'world': world, 'seed': seed, 'independent': independent,
                'epoch': None if independent else offset+1, **breakdown})
            aggregate = final['independent' if independent else 'continuous'][offset]
            require(checked == {k: v for k, v in aggregate.items() if k != 'epoch'}, 'aggregate group differs')
            if not independent:
                activation = read(directory/'activation.json'); lineage = read(directory/'lineage.json')
                require(activation['actual_agent_parents'] == parents, 'continual Agent parent mismatch')
                for runtime in ('old', 'new'):
                    node = lineage[runtime]
                    require(node['parent_node'] == nodes[runtime] and node['before_patch'] == parents[runtime]
                            and node['effective_patch'] == checked['runtime_results'][runtime]['effective_patch']
                            and node['cpu_node_hash'] == fingerprint(boundary), 'continual lineage mismatch')
                    parents[runtime] = node['effective_patch']; nodes[runtime] = fingerprint(node)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path('results/active-evolution/v1.1/formal-A-v2'))
    args = parser.parse_args(); report = audit(args.root)
    output = args.root/'audits'/('evidence-'+uuid.uuid4().hex+'.json')
    immutable_json(output, report)
    print({k: v for k, v in report.items() if k not in {'cache_file_hashes', 'completed_groups'}})
    print(output)


if __name__ == '__main__':
    main()
