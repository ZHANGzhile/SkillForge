"""Toy public-posterior diagnostics only; not evidence of policy learning."""
import math

import pytest

from scripts.audit_boundary_evolution_history import state_diagnostic, check_rank
from skillforge.belief import BeliefState
from skillforge.evolution_config import LearningOptions
from skillforge.evolution_schemas import Candidate, EvidenceView, Hypothesis, Predicate
from skillforge.execution_aware.challenge import ChallengeOptions


def belief_and_pool(*, top="H0"):
    hypotheses = [Hypothesis(hypothesis_id="H0", kind="no_change"),
        Hypothesis(hypothesis_id="restrict-high", kind="restrict", predicates=(Predicate(field="customer.risk_level", op="eq", value="HIGH"),)),
        Hypothesis(hypothesis_id="OTHER", kind="other")]
    belief = BeliefState(hypotheses, "unit-epoch")
    belief.log_weights = [math.log(value) for value in ([.99, .009, .001] if top == "H0" else [.009, .99, .001])]
    candidate = Candidate(candidate_id="probe", observations={"customer.risk_level": "HIGH"}, baseline_prediction=True,
        member_hash="unit-member", cost=1, mutation_probability=1)
    evidence = EvidenceView(evidence_id="seed", trajectory_id="unit-source", member_hash="unit-seed-member",
        split="seed", policy_epoch="unit-epoch", family="refund", observations={"customer.risk_level": "LOW" if top == "H0" else "HIGH"},
        baseline_prediction=True, label="executable" if top == "H0" else "not_executable", origin="controlled_procedure", tool_calls=1)
    belief.update(evidence)
    return belief, [candidate]


def test_h0_ordinary_entry_and_unknown_probe_do_not_fabricate_challenge_completion():
    belief, pool = belief_and_pool()
    state = state_diagnostic(belief, pool, {}, LearningOptions(), ChallengeOptions())
    assert state["h0_gate_entry_eligible"] and state["actual_gate"]["status"] == "challenge_required"
    unknown = EvidenceView(evidence_id="unknown", trajectory_id="unit-other-source", member_hash="unit-member", split="explore",
        policy_epoch="unit-epoch", family="refund", observations=pool[0].observations, baseline_prediction=True,
        label="unknown", origin="controlled_procedure", tool_calls=1).model_dump()
    state = state_diagnostic(belief, pool, {"probe": unknown}, LearningOptions(), ChallengeOptions())
    assert state["unknown_query_count"] == 1 and state["counterfactual_H0_challenge"]["completed"] == 0
    assert state["actual_gate"]["status"] == "inconclusive_unknown_observations"


def test_non_h0_convergence_does_not_enter_h0_gate_even_with_distinguishing_pool():
    belief, pool = belief_and_pool(top="restrict-high")
    state = state_diagnostic(belief, pool, {}, LearningOptions(), ChallengeOptions())
    assert state["ordinary_convergence"]["converged"] and state["top_kind"] == "restrict"
    assert not state["h0_gate_entry_eligible"] and state["actual_gate"] is None
    assert state["counterfactual_H0_challenge"]["distinct_challenges"] == 1


def test_archived_rank_check_rejects_cost_and_selected_query_forgery():
    _, pool = belief_and_pool()
    row = {"ranked": [{"candidate_id": "probe", "cost": 1, "mutation_probability": 1, "eig": .1, "score": .08}],
        "candidate_id": "probe", "selected_eig": .1, "max_available_eig": .1}
    check_rank(row, pool, set(), LearningOptions(), None)
    row["ranked"][0]["score"] = .09
    with pytest.raises(ValueError, match="score"): check_rank(row, pool, set(), LearningOptions(), None)
