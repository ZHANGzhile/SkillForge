"""Public acquisition contracts; no gold labels or efficacy assertions."""
from skillforge.active_learning import rank_candidates
from skillforge.belief import BeliefState
from skillforge.evolution_schemas import Hypothesis, Predicate, Candidate, EvidenceView, fingerprint
from skillforge.boundary_evolution.acquisition import select, deep_requests, supported_stop


def belief():
    return BeliefState([Hypothesis(hypothesis_id="H0", kind="no_change"),
        Hypothesis(hypothesis_id="small", kind="restrict", predicates=(Predicate(field="request.amount", op="gt", value=1000),)),
        Hypothesis(hypothesis_id="large", kind="restrict", predicates=(Predicate(field="request.amount", op="gt", value=3000),)),
        Hypothesis(hypothesis_id="OTHER", kind="other")], "public", accuracy=.8)


def candidates():
    return [Candidate(candidate_id=f"c{i}", member_hash=f"m{i}",
        observations={"request.amount": value, "refund.amount_valid": True, "payment.remaining_amount": 10000,
            "payment.captured_amount": 10000, "payment.refunded_amount": 0, "customer.risk_level": "LOW"},
        baseline_prediction=True, guard_prediction=True, cost=1, mutation_probability=1)
        for i, value in enumerate([500, 2000, 4000])]


def evidence(candidate, label="not_executable", ident="e"):
    payload = dict(trajectory_id=ident, member_hash=candidate.member_hash, split="seed", policy_epoch="public",
        family="refund", observations=candidate.observations, baseline_prediction=True, guard_prediction=True,
        label=label, origin="controlled_procedure", tool_calls=6)
    return EvidenceView(evidence_id=fingerprint(payload), **payload)


def test_original_eig_rank_is_unchanged_and_broad_is_lexicographic():
    b, pool = belief(), candidates()
    selected, ranked, phase = select(b, pool, set(), "OriginalActive")
    assert ranked == rank_candidates(b, pool) and selected == ranked[0] and phase == "EIG"
    selected, ranked, phase = select(b, pool, {"c0"}, "BroadOnly")
    assert phase == "BROAD" and selected["candidate_id"] != "c0"
    assert all("uncovered_public_factors" in row for row in ranked)


def test_deep_requires_public_conflict_and_declares_unobserved_consistent_requests():
    b, pool = belief(), candidates()
    assert deep_requests(b, pool) == []
    b.update(evidence(pool[2]))
    proposals = deep_requests(b, pool)
    assert 0 < len(proposals) <= 8
    assert all(row["label"] == "UNOBSERVED" for row in proposals)
    assert all(row["factors"]["payment.remaining_amount"] == row["factors"]["payment.captured_amount"] -
               row["factors"]["payment.refunded_amount"] for row in proposals)
    assert len({fingerprint(row["factors"]) for row in proposals}) == len(proposals)


def test_unknown_cannot_become_negative_or_supported_boundary():
    b, pool = belief(), candidates()
    b.update(evidence(pool[0], "unknown"))
    reason, result = supported_stop(b, pool, 1)
    assert reason == "UNKNOWN_OBSERVATIONS" and not result["converged"]


def test_domain_mismatch_abstains_instead_of_forcing_top_patch():
    b, pool = belief(), candidates()
    b.update(evidence(pool[2], "executable", "first-source"))
    b.update(evidence(pool[2], "not_executable", "independent-source"))
    reason, result = supported_stop(b, pool, 2)
    assert reason == "DOMAIN_INSUFFICIENT"
