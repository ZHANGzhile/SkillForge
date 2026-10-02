import math

import pytest

from skillforge.active_learning import convergence_metrics, expected_information_gain, rank_candidates, stopping_reason
from skillforge.belief import BeliefState, entropy
from skillforge.evolution_schemas import Candidate
from test_belief import hypotheses


def test_eig_matches_independent_binary_mutual_information():
    belief=BeliefState(hypotheses(),"p",complexity_lambda=0)
    c=Candidate(candidate_id="c",observations={"shipment.status":"PROCESSING"},baseline_prediction=True,cost=1,mutation_probability=1)
    # Prior .45/.45/.10 gives predictive P(y)=.5; conditional entropy known by hand.
    expected=math.log(2)-(.9*entropy([.99,.01])+.1*math.log(2))
    assert expected_information_gain(belief,c)==pytest.approx(expected)
    assert expected_information_gain(belief,c)>=0
    expensive=c.model_copy(update={"candidate_id":"expensive","cost":10})
    assert rank_candidates(belief,[expensive,c])[0]["candidate_id"]=="c"
    assert rank_candidates(belief,[c],used=["c"])==[]
    assert stopping_reason(belief,[c],20)=="budget_exhausted"


def test_restricted_mean_includes_failure_not_only_successful_runs():
    rows=[{"queries_to_convergence":t} for t in (0,10,20,None)]
    result=convergence_metrics(rows)
    assert result["restricted_mean_queries_to_convergence"]==12.5
    assert result["convergence_rate_within_budget"]==.75
    assert result["censored_count"]==1
    with pytest.raises(ValueError,match="incomplete"):
        convergence_metrics([{"queries_to_convergence":None,"status":"incomplete"}])
