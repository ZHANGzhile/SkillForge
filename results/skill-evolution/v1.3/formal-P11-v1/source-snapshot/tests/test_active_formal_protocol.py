import json

import pytest

from scripts.active_evolution_formal import aggregate,freeze
from scripts.active_evolution_continual import prepare_epoch
from scripts.active_evolution_dataset import EvaluationStore,state_for_policy
from scripts.active_evolution_worlds import policy
from scripts.active_evolution_model_benchmark import admission
from scripts.active_evolution_cost import formal_cost_plan
from test_evolution_execution import parent


def test_formal_freeze_rejects_failed_cost_gate_before_data_access(tmp_path):
    cost=tmp_path/'cost';cost.mkdir()
    (cost/'cost-gate.json').write_text(json.dumps({'cost_gate_passed':False}))
    with pytest.raises(ValueError,match='cost gate'):
        freeze(tmp_path/'formal',tmp_path/'missing-data',cost)
    assert not (tmp_path/'formal/protocol.json').exists()


def test_adjacent_epoch_retention_excludes_changed_old_rule_labels(tmp_path):
    prepare_epoch(tmp_path,'W5','W3',1701,{'seed':12,'explore':80,'validation':40,'stable_validation':40},parent('refund'))
    store=EvaluationStore(tmp_path)
    stable=store.read('stable_validation')
    assert len(stable)==40
    for row in stable:
        state=state_for_policy(row)
        assert (policy('W3','issue_refund',state,row['parameters'])=='allow')==(policy('W5','issue_refund',state,row['parameters'])=='allow')


def test_agent_admission_rejects_normal_regression_despite_net_gain():
    def row(truth,success):return {'truth_executable':truth,'verification':{'task_success':success,'actual_policy_violation':False}}
    before=[row(True,True),row(True,False)]
    after=[row(True,False),row(True,True)]
    decision=[{'decision_correct':True}]
    assert not admission(before,after,decision,decision)


def test_joint_metrics_count_early_failure_as_cap_and_preserve_pairs():
    rows=[]
    for seed in (1,2):
        for method in ('no_adapt','passive','random','active'):
            rows.append({'world':'W1','seed':seed,'method':method,'queries_to_convergence':10 if method=='random' else 5 if method=='active' else None,
                'queries':3,'status':'VERIFIED' if method in ('random','active') else 'INCONCLUSIVE',
                'false_allow':0,'false_block':0,'actual_violations':0,'retention':{'regression_count':0}})
    result=aggregate(rows,{'methods':['no_adapt','passive','random','active'],'learning':{'max_queries':20}})
    assert result['methods']['passive']['restricted_mean_queries_to_convergence']==20
    assert result['joint_point_estimate_passed'] and result['relative_rmq_reduction']==.5


def test_complete_gpu_manifest_counts_all_before_after_decisions_and_epochs():
    config={'methods':['no_adapt','passive','random','active'],'model_layer':{'worlds':['W3','W5','W6'],
        'model_validation':8,'model_stable_validation':4,'model_test':8,'model_stable_test':8,
        'global_retry_fraction':.1,'max_gpu_hours':12,'max_tokens':20000000}}
    plan=formal_cost_plan(config,{'p95_seconds':30,'mean_tokens':5000},{'p95_seconds':10,'mean_tokens':2500})
    assert plan['full_tasks']==644 and plan['decision_tasks']==368
    assert plan['total_tasks']==1012 and plan['global_retry_tasks']==102
    assert plan['cost_gate_passed']
    assert not formal_cost_plan(config,{'p95_seconds':90,'mean_tokens':5000},{'p95_seconds':30,'mean_tokens':2500})['cost_gate_passed']
