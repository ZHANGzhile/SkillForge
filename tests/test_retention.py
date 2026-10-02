import pytest

from skillforge.evolution_config import LearningOptions
from skillforge.evolution_metrics import retention, sensitivity
from skillforge.evolution_schemas import Candidate
from test_belief import evidence, hypotheses


def test_paired_retention_does_not_hide_regression_with_net_improvement():
    triples=[(True,True,False),(True,False,True),(False,True,False),(True,True,True)]
    cases=[{"task_id":str(i),"split":"stable_test","truth":t,"baseline_prediction":b,"prediction":a}
           for i,(t,b,a) in enumerate(triples)]
    result=retention(cases)
    assert result["before_correct"]==2 and result["after_correct"]==3
    assert result["regression_count"]==1
    assert result["retention_rate"]==.5
    assert result["forgetting"]==-.25
    with pytest.raises(ValueError,match="stable"):
        retention([{**cases[0],"split":"test"}])


def test_sensitivity_is_read_only_fixed_evidence_reweighting():
    candidates=[Candidate(candidate_id=str(i),observations={"shipment.status":"PROCESSING"},baseline_prediction=True,cost=1,mutation_probability=1) for i in range(2)]
    seeds=[evidence(99,split="seed")]
    queries=[{"candidate_id":"0","evidence":evidence(0).model_dump(),"learned":True}]
    options=LearningOptions()
    result=sensitivity(hypotheses(),"p",seeds,queries,candidates,options)
    assert [r["accuracy"] for r in result["runs"]]==[.9,.95,.99]
    assert len(queries)==1 and options.accuracy==.99
    assert all(len(r["steps"])==1 for r in result["runs"])
    assert result["runs"][0]["final"]["class_posterior"]!=result["runs"][2]["final"]["class_posterior"]
