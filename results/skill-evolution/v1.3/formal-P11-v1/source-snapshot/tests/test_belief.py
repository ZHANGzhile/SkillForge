import copy

import pytest

from skillforge.belief import BeliefState
from skillforge.evolution_schemas import Candidate, EvidenceView, Hypothesis, Predicate


def hypotheses():
    return [Hypothesis(hypothesis_id="H0",kind="no_change"),
        Hypothesis(hypothesis_id="H1",kind="restrict",predicates=(Predicate(field="shipment.status",op="eq",value="PROCESSING"),)),
        Hypothesis(hypothesis_id="OTHER",kind="other")]


def evidence(i=0, label="not_executable", **kw):
    value = dict(evidence_id=f"e{i}",trajectory_id=f"t{i}",member_hash="m",split="explore",policy_epoch="p",
        family="refund",observations={"shipment.status":"PROCESSING"},baseline_prediction=True,label=label,
        origin="controlled_procedure",tool_calls=3)
    value.update(kw)
    return EvidenceView(**value)


def test_update_replay_duplicate_and_unknown():
    b = BeliefState(hypotheses(),"p")
    initial = b.posterior
    b.update(evidence(label="unknown"))
    assert b.posterior == initial
    assert not b.update(evidence(label="unknown"))
    with pytest.raises(ValueError,match="conflicting"):
        b.update(evidence())
    for i in range(1,6):
        b.update(evidence(i))
    assert sum(b.posterior) == pytest.approx(1)
    assert b.posterior[1] > .95
    assert BeliefState.restore(b.snapshot()).snapshot() == b.snapshot()
    bad = copy.deepcopy(b.snapshot())
    bad["history"][0]["after"][0] = .3
    with pytest.raises(ValueError,match="replay"):
        BeliefState.restore(bad)
    with pytest.raises(ValueError,match="epochs"):
        b.update(evidence(10,policy_epoch="different"))


def test_other_detects_contradiction_and_never_converges_as_rule():
    b = BeliefState(hypotheses(),"p")
    for i in range(16):
        b.update(evidence(i,label="executable" if i%2 else "not_executable"))
    assert b.posterior[2] > .99
    candidates=[Candidate(candidate_id="c",observations={"shipment.status":"PROCESSING"},baseline_prediction=True,cost=1,mutation_probability=1)]
    assert not b.convergence(candidates)["converged"]


def test_holdout_not_accepted_as_evidence():
    with pytest.raises(ValueError):
        evidence(split="test")
