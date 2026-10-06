"""Offline end-to-end report checks using scripted public-context actions."""
from contextlib import closing
from copy import deepcopy
import json

import pytest

from scripts.active_evolution_worlds import policy
from scripts.audit_execution_aware import audit, execution_partition
from scripts.execution_aware_formal import H0, evaluate_group
from scripts.execution_aware_protocol import write_split_dataset
from scripts.finalize_execution_aware import finalize
from skillforge.active_agent.runtime import run_agent as old_run
from skillforge.execution_aware.runtime import run_agent as new_run
from skillforge.execution_aware.admission import AdmissionEvidence, admission_funnel
from skillforge.execution_aware.factorial import paired_factorial
from skillforge.evolution_registry import immutable_json
from skillforge.evolution_schemas import Hypothesis, Predicate, fingerprint
from skillforge.schemas import Action, ExpectedOutcome, Task
import skillforge.environment as environment
import skillforge.verifier as verifier
from test_evolution_execution import parent


def test_complete_offline_matrix_can_be_audited_and_rendered_without_model_calls(tmp_path, monkeypatch):
    root = tmp_path/'formal'; dataset = tmp_path/'datasets/W3/411'; contract = parent('refund')
    write_split_dataset(dataset, 'W3', 411, {'explore': 80, 'model_validation': 8,
        'model_stable_validation': 4, 'model_test': 8, 'model_stable_test': 8}, contract)
    protocol = {'sources': {}, 'datasets': {}, 'data_root': str(dataset.parent.parent),
        'config': {'worlds': ['W3'], 'paired_seeds': [411], 'continual': {'worlds': [], 'seed': 999},
                   'limits': {'shared_gpu_seconds': 43200}},
        'model_settings': {'model': 'scripted-report-test'}, 'prior_charged_tokens': 100, 'prior_invocation_seconds': 2,
        'bootstrap': {'seed': 12, 'replicates': 100}}
    ph = fingerprint(protocol)
    immutable_json(root/'protocol.json', {'protocol': protocol, 'protocol_hash': ph})
    monkeypatch.setattr(environment, 'eligibility', lambda n,s,a: policy('W3', n,s,a))
    monkeypatch.setattr(verifier, 'eligibility', lambda n,s,a: policy('W3', n,s,a))

    class Scripted:
        tokens = 0
        settings = protocol['model_settings']
        def decide(self, context):
            self.tokens += 10
            if context['policy_view']['effective_gate'] != 'APPLICABLE':
                return Action(type='escalate')
            if context['history']:
                return Action(type='stop')
            return Action(type='tool', name='issue_refund', arguments=context['parameters'])

    class Ledger:
        protocol_hash = ph
        def evaluate(self, spec, world, contract, patch, runtime, decision):
            identity = {'task_hash': fingerprint(spec), 'world': world, 'contract': fingerprint(contract), 'patch': patch,
                'runtime': runtime, 'decision_only': decision, 'protocol_hash': ph, 'model': fingerprint(protocol['model_settings'])}
            key = fingerprint(identity); target = root/'model-layer/cache'/(key+'.json')
            if target.exists():
                return json.loads(target.read_text(encoding='utf-8'))['result'], key
            with closing(environment.Environment(fixture=spec['fixture'])) as env:
                initial = env.snapshot()
                fields = {k: spec[k] for k in ('task_id', 'family', 'request', 'parameters')}
                fn = old_run if runtime == 'old' else new_run
                agent = fn(Scripted(), fields, contract, patch, spec['policy_epoch'],
                    lambda n,a,k: env.call(n,a,spec['fixture']['customer_id'],k),
                    decision_only=decision, **({'single_goal': True} if runtime == 'new' else {}))
                gold = policy(world, 'issue_refund', initial, spec['parameters'])
                task = Task(**fields, customer_id=spec['fixture']['customer_id'], template_id=spec['template'], seed=0,
                    split='validation', expected=ExpectedOutcome(
                        allowed_outcomes=[{'allow':'completed','refuse':'refused','escalate':'escalated'}[gold]],
                        expected_state={'payment.refunded_amount': initial['payment.refunded_amount']+spec['parameters']['amount']} if gold=='allow' else {}))
                result = {'agent': agent, 'spec_hash': fingerprint(spec), 'truth_executable': gold=='allow',
                    'decision_correct': agent['decision'] is (gold=='allow'), 'decision_only': decision,
                    'verification': verifier.verify(task, initial, env.snapshot(), env.audit, agent['outcome']),
                    'tool_audit': env.audit, 'initial_state': initial, 'final_state': env.snapshot(), 'seconds': .01}
            immutable_json(target, {'identity': identity, 'result': result, 'result_hash': fingerprint(result)})
            return result, key

    patch = Hypothesis(hypothesis_id='test-patch', kind='restrict', predicates=(Predicate(field='request.amount',op='gt',value=3000),)).model_dump(mode='json')
    boundary = {'before': H0, 'effective': patch, 'belief_converged': True, 'nontrivial': True,
                'boundary_admitted': True, 'boundary_validation_passed': True}
    directory = root/'model-layer/independent/W3/411'
    row = evaluate_group(Ledger(), dataset, directory, 'W3', 411, boundary, {'old': H0, 'new': H0})
    immutable_json(root/'cpu-report.json', {'protocol_hash': ph, 'independent': [{'world': 'W3', 'seed': 411, **boundary}], 'continuous': []})
    funnels = {runtime: admission_funnel([AdmissionEvidence('W3/411', 'active', True, True, True, True, True,
        row['runtime_results'][runtime]['agent_admitted'], row['runtime_results'][runtime]['agent_admitted'])]) for runtime in ('old','new')}
    totals = sum(json.loads(p.read_text(encoding='utf-8'))['result']['agent']['metrics']['tokens'] for p in (root/'model-layer/cache').glob('*.json'))+100
    immutable_json(root/'model-report.json', {'protocol_hash': ph, 'independent': [row], 'continuous': [], 'funnel': funnels,
        'factorial': {scope: paired_factorial([{**row, 'bundle_scope': scope, 'arms': row[scope+'_arms']}],seed=12,replicates=100) for scope in ('candidate','effective')},
        'charged_tokens_all_v11': totals})
    immutable_json(root/'model-layer/invocations/test.start.json', {'protocol_hash': ph})
    immutable_json(root/'model-layer/invocations/test.final.json', {'status': 'complete', 'seconds': 1})
    checked = audit(root)
    assert checked['complete'] and len(checked['per_group_execution_attribution']) == 1
    metrics = checked['per_group_execution_attribution'][0]['candidate']['new_old']['changed']
    assert metrics['counts']['runtime_assisted_eoc'] > 0
    assert metrics['counts']['autonomous_eoc']+metrics['counts']['runtime_assisted_eoc'] == metrics['counts']['eoc']
    assert finalize(root, 'test')['status'] == 'complete'
    assert 'runtime_assisted_eoc' in (root/'execution-attribution.json').read_text(encoding='utf-8')
    text = (root/'REPORT.md').read_text(encoding='utf-8')
    assert '自主' in text and '逐臂归因' in text
    corrupt = deepcopy(row); corrupt['runtime_results']['new']['stable_regressions'] += 1
    (directory/'report.json').write_text(json.dumps(corrupt), encoding='utf-8')
    with pytest.raises(ValueError, match='stable retention'):
        audit(root)


def test_partition_rejects_decision_probes_and_duplicate_pseudoreplication():
    row = {'spec_hash': 'same', 'decision_only': True}
    with pytest.raises(ValueError, match='Decision probes'):
        execution_partition([row])
    with pytest.raises(ValueError, match='unique'):
        execution_partition([row, row])
