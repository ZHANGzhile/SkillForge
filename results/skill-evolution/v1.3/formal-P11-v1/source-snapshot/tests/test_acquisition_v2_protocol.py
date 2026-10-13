import pytest

from scripts.acquisition_v2_protocol import aggregate, design, select_variant
from skillforge.active_learning import rank_candidates
from skillforge.belief import BeliefState
from skillforge.evolution_schemas import Candidate
from skillforge.execution_aware.acquisition import AcquisitionOptions, augment_ranking, factors
from test_belief import hypotheses


def test_acquisition_uses_public_factors_and_preserves_zero_weight_baseline():
    belief = BeliefState(hypotheses(), 'p')
    a = Candidate(candidate_id='a', observations={'shipment.status':'PROCESSING','request.amount':100}, baseline_prediction=True, cost=1, mutation_probability=1)
    b = a.model_copy(update={'candidate_id':'b'})
    with pytest.raises(ValueError, match='public feature'):
        Candidate.model_validate({**a.model_dump(), 'observations':{**a.observations,'order.order_id':'SECRET'}})
    assert factors(a) == factors(b)
    ranked = rank_candidates(belief,[a,b])
    assert augment_ranking(belief,[a,b],set(),ranked,AcquisitionOptions(),.01,.01) is ranked
    enhanced = augment_ranking(belief,[a,b],{'a'},[r for r in ranked if r['candidate_id']=='b'],AcquisitionOptions(.25,.25),.01,.01)
    assert enhanced[0]['coverage_bonus'] == 0
    assert 0 <= enhanced[0]['h0_disagreement'] <= 1


def test_selection_requires_complete_development_and_has_explicit_tiebreak():
    config = design()
    rows = [{'world':w,'variant':v,'top_diagnostic':{'errors':0},'raw_h0_false_convergence':False,
             'queries_to_convergence':3,'queries':3} for w in config['worlds'] for v in config['variants']]
    assert select_variant(rows,config)['selected'] == 'gate'
    with pytest.raises(ValueError,match='complete'):
        select_variant(rows[:-1],config)


def test_censoring_false_h0_does_not_pass_joint_efficiency():
    config = design(); rows = []
    for w in config['worlds']:
        for s in config['paired_seeds']:
            for m in config['methods']:
                rows.append({'world':w,'seed':s,'method':m,'status':'INCONCLUSIVE' if m=='active_v2' else 'UNCHANGED',
                    'queries_to_convergence':None if m in {'active_v2','no_adapt'} else 3,'queries':20 if m=='active_v2' else 3,
                    'raw_false_convergence':m=='active','false_convergence':m=='active','raw_h0_false_convergence':m=='active',
                    'h0_false_convergence':m=='active','boundary_admitted':False,'h0_challenge':None,
                    'effective_test':{'false_allow':0,'false_block':0,'actual_violations':0,'stable_regressions':0}})
    result = aggregate(rows,config)
    assert result['h0_false_convergence_reduced'] and result['heldout_safety_passed']
    assert not result['joint_efficiency_passed'] and not result['v2_research_claim_passed']
    with pytest.raises(ValueError,match='complete unique'):
        aggregate(rows[:-1],config)
