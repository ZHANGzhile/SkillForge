"""Public-only development learner; tool/expansion capabilities via audited RPC."""
from .acquisition import METHODS, ProbeOptions, select, deep_requests, has_public_conflict, supported_stop
from ..evolution_schemas import EvidenceView, fingerprint
from ..belief import BeliefState
from ..active_learning import stopping_reason
from ..execution_aware.challenge import ChallengeOptions, challenge_gate


def hashed(body):
    return {**body, "hash": fingerprint(body)}


def learn_public(method, hypotheses, seeds, initial, probe, expand, *, learning, probe_options):
    """No dataset/fixture/world/validation capability is passed into this function."""
    belief = BeliefState(hypotheses, seeds[0].policy_epoch, learning.accuracy,
        learning.other_prior, learning.complexity_lambda)
    for evidence in seeds: belief.update(evidence)
    pool, used, queries, generated = list(initial), set(), [], False
    improved = method not in {"OriginalActive", "ExistingActiveV2"}
    while True:
        if (method in {"DeepOnly", "BroadThenDeep"} and not generated and has_public_conflict(belief)
                and (method != "BroadThenDeep" or len(queries) >= probe_options.broad_queries)):
            requests = deep_requests(belief, pool, probe_options.model_dump())
            extra = expand(requests)
            if len(extra) > probe_options.max_generated_candidates:
                raise ValueError("generated candidate budget exceeded")
            if len({c.candidate_id for c in [*pool, *extra]}) != len(pool) + len(extra):
                raise ValueError("sandbox designer returned duplicate generated identities")
            pool.extend(extra); generated = True
        raw = belief.convergence(pool, **learning.convergence_args())
        top = next(h for h in hypotheses if h.hypothesis_id == raw["hypothesis_id"])
        gate = None
        if method != "OriginalActive" and raw["converged"] and top.kind == "no_change":
            gate = challenge_gate(belief, pool, {q["candidate_id"]: q["evidence"] for q in queries},
                                  ChallengeOptions(max_queries=learning.max_queries))
        reason = stopping_reason(belief, pool, len(queries), learning.max_queries,
            [q["max_available_eig"] for q in queries], learning.patience, learning.min_information_gain,
            **learning.convergence_args())
        if gate and not gate["passed"]:
            reason = None if gate["status"] == "challenge_required" else gate["status"]
        if improved:
            specific, _ = supported_stop(belief, pool, len(queries), max_queries=learning.max_queries,
                                         **learning.convergence_args())
            if specific in {"DOMAIN_INSUFFICIENT", "UNKNOWN_OBSERVATIONS"}: reason = specific
        if reason: break
        selected, ranked, phase = select(belief, pool, used, method, options=probe_options.model_dump(),
            cost_lambda=learning.cost_lambda, risk_lambda=learning.risk_lambda)
        if selected is None:
            reason = "NO_DISCRIMINATING_PROBE" if improved else "pool_exhausted"
            break
        if gate and not gate["passed"]:
            challenge = [r for r in ranked if r["candidate_id"] in gate["remaining_candidates"]]
            if challenge: selected, phase = challenge[0], "H0_CHALLENGE"
        candidate = next(c for c in pool if c.candidate_id == selected["candidate_id"])
        ev = EvidenceView.model_validate(probe(candidate.candidate_id))
        if (ev.split != "explore" or ev.policy_epoch != belief.policy_epoch or ev.member_hash != candidate.member_hash or
                ev.baseline_prediction != candidate.baseline_prediction or ev.guard_prediction != candidate.guard_prediction or
                any(ev.observations.get(key) != value for key, value in candidate.observations.items())):
            raise ValueError("actual query receipt disagrees with declared public factors/source")
        before = fingerprint(belief.snapshot())
        belief.update(ev)
        row = hashed({"index": len(queries), "candidate_id": candidate.candidate_id, "phase": phase,
            "ranked": ranked, "selected_eig": selected["eig"], "max_available_eig": max(r["eig"] for r in ranked),
            "evidence": ev.model_dump(mode="json"), "belief_before": before,
            "belief_after": fingerprint(belief.snapshot()), "h0_gate": gate})
        queries.append(row); used.add(candidate.candidate_id)
    raw = belief.convergence(pool, **learning.convergence_args())
    supported = raw["converged"] and not (gate and not gate["passed"])
    h0 = next(h for h in hypotheses if h.kind == "no_change")
    diagnostic = next(h for h in hypotheses if h.hypothesis_id == raw["hypothesis_id"])
    # Common historical H0 fallback isolates acquisition; conservative quarantine
    # is reported separately and cannot manufacture a learning-efficiency win.
    effective = diagnostic if supported else h0
    return {"method": method, "queries": queries, "belief": belief.snapshot(),
        "final_support": [c.model_dump(mode="json") for c in pool], "stop_reason": reason,
        "belief_supported": supported, "queries_to_convergence": len(queries) if supported else None,
        "diagnostic_hypothesis": diagnostic.model_dump(mode="json"), "effective_hypothesis": effective.model_dump(mode="json"),
        "h0_challenge": gate, "generated_candidates": len(pool) - len(initial),
        "fallback": "common H0 retention, not certified adaptation", "activated": False}

