from copy import deepcopy
from contextlib import closing

import pytest

from scripts.active_evolution_dataset import generate
from scripts.audit_execution_aware import audit_result
from skillforge.environment import Environment
from skillforge.evolution_schemas import fingerprint
from skillforge.execution_aware.runtime import run_agent
from skillforge.schemas import Action, ExpectedOutcome, Task
from skillforge.verifier import verify
from test_execution_aware import H0, Scripted
from test_evolution_execution import parent


def evidence(decision_only=False):
    spec = generate('W3', 791, {'model_validation': 8})[0]
    task_fields = {k: spec[k] for k in ('task_id', 'family', 'request', 'parameters')}
    with closing(Environment(fixture=spec['fixture'])) as env:
        initial = env.snapshot()
        agent = run_agent(Scripted([Action(type='tool', name='issue_refund', arguments=spec['parameters'])]),
                          task_fields, parent('refund'), H0, spec['policy_epoch'],
                          lambda n, a, k: env.call(n, a, spec['fixture']['customer_id'], k),
                          single_goal=True, decision_only=decision_only)
        final = env.snapshot()
        task = Task(**task_fields, customer_id=spec['fixture']['customer_id'], split='validation',
                    template_id=spec['template'], seed=0, expected=ExpectedOutcome(allowed_outcomes=['completed'],
                    expected_state={'payment.refunded_amount': initial['payment.refunded_amount']+spec['parameters']['amount']}))
        result = {'agent': agent, 'initial_state': initial, 'final_state': final, 'tool_audit': env.audit,
                  'spec_hash': fingerprint(spec), 'truth_executable': True, 'decision_correct': True,
                  'verification': verify(task, initial, final, env.audit, agent['outcome'])}
    return spec, result


def test_raw_evidence_audit_and_decision_are_separate():
    spec, result = evidence()
    assert audit_result(result, spec, 'W3', 'new') == {'receipts': 1, 'interventions': 2}
    spec, result = evidence(True)
    assert not result['verification']['task_success'] and result['decision_correct']
    assert audit_result(result, spec, 'W3', 'new') == {'receipts': 0, 'interventions': 0}


def test_audit_catches_forged_matching_readback_even_if_verifier_still_passes():
    spec, result = evidence()
    result['tool_audit'][-1]['result']['payment.order_id'] = 'OTHER'
    # Original verifier only sees a get_payment after a write. The independent
    # receipt binding also checks actual response object and observed values.
    with pytest.raises(ValueError, match='matching fresh raw read-back'):
        audit_result(result, spec, 'W3', 'new')


def test_audit_rejects_assistance_hidden_as_autonomous():
    spec, result = evidence()
    result['agent']['interventions']['runtime_intervention_count'] = 0
    with pytest.raises(ValueError, match='intervention accounting'):
        audit_result(result, spec, 'W3', 'new')


def test_audit_rejects_task_or_outcome_relabeling():
    spec, result = evidence()
    wrong = deepcopy(spec); wrong['task_id'] = 'unpaired'
    with pytest.raises(ValueError, match='task identity'):
        audit_result(result, wrong, 'W3', 'new')
    result['verification']['task_success'] = False
    with pytest.raises(ValueError, match='private verifier'):
        audit_result(result, spec, 'W3', 'new')
