"""Reference random/passive acquisition; original Bayes and stopping rules."""
import random

from ..belief import BeliefState
from ..active_learning import stopping_reason, rank_candidates
from ..evolution_schemas import EvidenceView, fingerprint


def learn_reference(method, hypotheses, seeds, pool, probe, *, learning, random_seed):
    if method not in {"random", "passive", "no_adapt"}: raise ValueError("registered reference only")
    b = BeliefState(hypotheses, seeds[0].policy_epoch, learning.accuracy, learning.other_prior, learning.complexity_lambda)
    for e in seeds: b.update(e)
    order = [c.candidate_id for c in pool]
    if method == "random":
        order.sort(); random.Random(random_seed).shuffle(order)
    queries, used = [], set()
    while method != "no_adapt":
        reason = stopping_reason(b, pool, len(queries), learning.max_queries,
            [q["max_available_eig"] for q in queries], learning.patience, learning.min_information_gain, **learning.convergence_args())
        if reason: break
        ranked = rank_candidates(b, pool, used, learning.cost_lambda, learning.risk_lambda)
        if not ranked: reason = "pool_exhausted"; break
        key = next(k for k in order if k not in used)
        c = next(c for c in pool if c.candidate_id == key)
        e = EvidenceView.model_validate(probe(key))
        if (e.split != "explore" or e.policy_epoch != b.policy_epoch or e.member_hash != c.member_hash or
                e.baseline_prediction != c.baseline_prediction or e.guard_prediction != c.guard_prediction or
                any(e.observations.get(k) != v for k, v in c.observations.items())):
            raise ValueError("query evidence not bound to public candidate")
        learned = method != "passive" or e.label == "not_executable"
        if learned: b.update(e)
        body = {"candidate_id": key, "evidence": e.model_dump(mode="json"), "learned": learned,
            "ranked": ranked, "max_available_eig": max(r["eig"] for r in ranked)}
        queries.append({**body, "hash": fingerprint(body)}); used.add(key)
    raw = b.convergence(pool, **learning.convergence_args())
    top = next(h for h in hypotheses if h.hypothesis_id == raw["hypothesis_id"])
    return {"method": method, "queries": queries, "belief": b.snapshot(), "final_support": [c.model_dump(mode="json") for c in pool],
        "stop_reason": "no_adaptation" if method == "no_adapt" else reason,
        "belief_supported": raw["converged"] and method != "no_adapt", "diagnostic_hypothesis": top.model_dump(mode="json"),
        "queries_to_convergence": len(queries) if raw["converged"] and method != "no_adapt" else None,
        "scope": "legacy reference acquisition; passive learns negative business outcomes only; no activation"}
