import pytest

from skillforge.belief import BeliefState
from skillforge.evolution_schemas import Candidate
from skillforge.execution_aware.challenge import ChallengeOptions, challenge_gate
from test_belief import evidence, hypotheses


def candidate(cid, risk="LOW"):
    return Candidate(candidate_id=cid, member_hash=cid, observations={"shipment.status": "PROCESSING", "customer.risk_level": risk},
                     baseline_prediction=True, cost=1, mutation_probability=1)


def observation(c, **kw):
    return evidence(c.candidate_id, member_hash=c.member_hash, observations=c.observations, label="executable", **kw)


def test_confident_h0_still_needs_distinct_exploration_challenges():
    belief = BeliefState(hypotheses(), "p")
    a, b = candidate("a"), candidate("b", "MEDIUM")
    for i in range(8):
        belief.update(evidence(i, label="executable", split="seed"))
    assert belief.convergence([a, b])["converged"]
    assert challenge_gate(belief, [a, b], {})["status"] == "challenge_required"
    assert not challenge_gate(belief, [a, b], {"a": observation(a)})["passed"]
    assert challenge_gate(belief, [a, b], {"a": observation(a), "b": observation(b)})["passed"]


def test_duplicate_public_probe_does_not_inflate_k():
    belief = BeliefState(hypotheses(), "p")
    a, b, c = candidate("a"), candidate("b"), candidate("c", "MEDIUM")
    result = challenge_gate(belief, [a, b, c], {"a": observation(a), "b": observation(b)}, ChallengeOptions(max_queries=2))
    assert result["completed"] == 1 and result["status"] == "inconclusive_budget_exhausted"


def test_seed_evidence_cannot_satisfy_challenge_and_empty_support_not_certified():
    belief = BeliefState(hypotheses(), "p")
    c = candidate("a")
    with pytest.raises(ValueError, match="exploration"):
        challenge_gate(belief, [c], {"a": observation(c, split="seed")})
    identical = c.model_copy(update={"observations": {"shipment.status": "NOT_STARTED"}})
    assert challenge_gate(belief, [identical], {})["status"] == "no_discriminating_probe"
