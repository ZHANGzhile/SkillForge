"""Complete frozen Agent workload, counting full tasks and Decision separately."""
import math


def formal_cost_plan(config,full,decision):
    m=config['model_layer'];worlds=len(m['worlds']);methods=len(config['methods']);epochs=2
    full_n=m['model_validation']+m['model_stable_validation']+m['model_test']+m['model_stable_test']
    decision_n=m['model_validation']+m['model_test']
    # Exact cache identity guarantees reuse for No Adaptation, and all methods
    # start continuous epoch 1 from the same H0 bundle. No result-based savings.
    independent_groups=worlds*methods
    continuous_groups=epochs*(2*methods-1)-(methods-1)
    counts={'independent_full':independent_groups*full_n,'independent_decision':independent_groups*decision_n,
        'continuous_full':continuous_groups*full_n,'continuous_decision':continuous_groups*decision_n}
    full_tasks=counts['independent_full']+counts['continuous_full']
    decision_tasks=counts['independent_decision']+counts['continuous_decision']
    rf=math.ceil(full_tasks*m['global_retry_fraction']);rd=math.ceil(decision_tasks*m['global_retry_fraction'])
    seconds=(full_tasks+rf)*full['p95_seconds']+(decision_tasks+rd)*decision['p95_seconds']+600
    tokens=(full_tasks+rf)*full['mean_tokens']+(decision_tasks+rd)*decision['mean_tokens']
    within=seconds<=m['max_gpu_hours']*3600 and tokens<=m['max_tokens']
    return {'status':'measured_development_cost_gate','stages':counts,'total_tasks':full_tasks+decision_tasks,
        'full_tasks':full_tasks,'decision_tasks':decision_tasks,'global_retry_tasks':rf+rd,'startup_seconds_reserved':600,
        'estimates':{'hours_with_retry_reserve':seconds/3600,'tokens_with_retry_reserve':tokens},
        'within_budget':within,'cost_gate_passed':within,'formal_model_execution_enabled':False,
        'scope':'all independent and two continuous-epoch before/after EOC plus separate first-decision probes; exact identity cache only',
        'quality_note':'malformed model actions remain task failures; no EOC improvement required to pass a resource gate'}
