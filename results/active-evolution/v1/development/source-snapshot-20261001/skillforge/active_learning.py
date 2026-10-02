"""Selection operates only on public Candidate objects and a finite belief."""
import math

from .belief import entropy
from .evolution_schemas import Candidate


def expected_information_gain(belief, candidate):
    candidate = Candidate.model_validate(candidate)
    prior = belief.posterior
    predicted = belief.predictions(candidate.observations, candidate.baseline_prediction)
    expected = 0.
    for outcome in (False, True):
        weights = [p * belief.likelihood(h, outcome) for p, h in zip(prior, predicted)]
        probability = sum(weights)
        expected += probability * entropy([w / probability for w in weights])
    return max(0., entropy(prior) - expected)


def rank_candidates(belief, candidates, used=(), cost_lambda=.01, risk_lambda=.01):
    if any(not math.isfinite(v) or v < 0 for v in (cost_lambda, risk_lambda)):
        raise ValueError("nonnegative finite penalties required")
    if len({c.candidate_id for c in candidates}) != len(candidates):
        raise ValueError("duplicate candidate IDs")
    rows = []
    for candidate in candidates:
        if candidate.candidate_id in used:
            continue
        eig = expected_information_gain(belief, candidate)
        rows.append({"candidate_id": candidate.candidate_id, "eig": eig,
            "cost": candidate.cost, "mutation_probability": candidate.mutation_probability,
            "score": eig - cost_lambda*candidate.cost - risk_lambda*candidate.mutation_probability})
    return sorted(rows, key=lambda row: (-row["score"], row["candidate_id"]))


def stopping_reason(belief, candidates, queries, max_queries=20, gains=(), patience=3, min_gain=.01):
    result = belief.convergence(candidates)
    if result["converged"]:
        return "converged"
    if queries >= max_queries:
        return "budget_exhausted"
    if len(gains) >= patience and all(g < min_gain for g in gains[-patience:]):
        return "no_information_gain"
    return None


def convergence_metrics(runs, cap=20):
    if not runs or type(cap) is not int or cap < 1:
        raise ValueError("nonempty runs and positive cap required")
    if any(r.get("status") == "incomplete" for r in runs):
        raise ValueError("incomplete infrastructure runs cannot enter final metrics")
    times = [r["queries_to_convergence"] for r in runs]
    if any(t is not None and (type(t) is not int or not 0 <= t <= cap) for t in times):
        raise ValueError("invalid convergence time")
    return {"cap": cap, "runs": len(runs),
        "convergence_rate_within_budget": sum(t is not None for t in times)/len(times),
        "restricted_mean_queries_to_convergence": sum(cap if t is None else t for t in times)/len(times),
        "censored_count": sum(t is None for t in times)}
