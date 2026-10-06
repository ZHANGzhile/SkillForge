"""Public-only H0 falsification gate. Development primitive, not frozen acquisition."""
from dataclasses import dataclass
import math

from ..evolution_schemas import Candidate, EvidenceView, fingerprint


@dataclass(frozen=True)
class ChallengeOptions:
    k: int = 2
    relative_alternative_posterior: float = .1
    max_queries: int = 20

    def __post_init__(self):
        if type(self.k) is not int or self.k < 1 or type(self.max_queries) is not int or self.max_queries < self.k:
            raise ValueError("positive K within original query budget required")
        if not math.isfinite(self.relative_alternative_posterior) or not 0 < self.relative_alternative_posterior <= 1:
            raise ValueError("invalid relative alternative posterior cutoff")


def challenge_gate(belief, candidates, query_evidence, options=ChallengeOptions()):
    """Gate certification is necessary, not sufficient, for H0 convergence.

    query_evidence maps actually executed pool IDs to public explore EvidenceView.
    Seed observations do not satisfy challenge obligations. Alternatives are
    selected relative to the strongest non-H0 posterior, so a confident H0 does
    not erase the obligation by lowering all alternatives below an absolute floor.
    """
    candidates = [Candidate.model_validate(c) for c in candidates]
    by_id = {c.candidate_id: c for c in candidates}
    if len(by_id) != len(candidates) or len(query_evidence) > options.max_queries:
        raise ValueError("duplicate candidates or exceeded original budget")
    h0 = [i for i, h in enumerate(belief.hypotheses) if h.kind == "no_change"]
    if len(h0) != 1:
        raise ValueError("exactly one H0 required")
    observed = set()
    for cid, raw in query_evidence.items():
        evidence = EvidenceView.model_validate(raw)
        c = by_id.get(cid)
        if c is None or evidence.split != "explore" or evidence.policy_epoch != belief.policy_epoch:
            raise ValueError("challenge evidence must belong to exploration pool and epoch")
        if not c.member_hash or c.member_hash != evidence.member_hash:
            raise ValueError("challenge member identity mismatch")
        if (evidence.baseline_prediction != c.baseline_prediction or evidence.guard_prediction != c.guard_prediction
                or any(evidence.observations.get(k) != v for k, v in c.observations.items())):
            raise ValueError("challenge observation identity mismatch")
        if evidence.label != "unknown":
            observed.add(cid)
    alternatives = [i for i, h in enumerate(belief.hypotheses) if h.kind not in {"no_change", "other"}]
    posterior = belief.posterior
    strongest = max((posterior[i] for i in alternatives), default=0)
    alternatives = [i for i in alternatives if posterior[i] >= strongest * options.relative_alternative_posterior]
    distinct = {}
    for c in candidates:
        predictions = belief.predictions(c.observations, c.baseline_prediction, c.guard_prediction)
        if predictions[h0[0]] is None or not any(predictions[i] is not None and predictions[i] != predictions[h0[0]] for i in alternatives):
            continue
        key = fingerprint([c.observations, c.baseline_prediction, c.guard_prediction])
        distinct.setdefault(key, []).append(c.candidate_id)
    tested = [key for key, ids in distinct.items() if any(cid in observed for cid in ids)]
    needed = min(options.k, len(distinct))
    passed = bool(distinct) and len(tested) >= needed
    remaining = sorted(min(cid for cid in ids if cid not in query_evidence)
                       for key, ids in distinct.items() if key not in tested and any(cid not in query_evidence for cid in ids))
    if not distinct:
        status = "no_discriminating_probe"
    elif passed:
        status = "challenge_passed"
    elif len(query_evidence) >= options.max_queries:
        status = "inconclusive_budget_exhausted"
    elif not remaining:
        status = "inconclusive_unknown_observations"
    else:
        status = "challenge_required"
    return {"status": status, "passed": passed, "required": needed, "configured_k": options.k,
            "distinct_challenges": len(distinct), "completed": len(tested), "queries_charged": len(query_evidence),
            "coverage_shortfall": len(distinct) < options.k, "remaining_candidates": remaining,
            "alternative_ids": [belief.hypotheses[i].hypothesis_id for i in alternatives],
            "scope": "challenge certification only; ordinary posterior convergence must also pass"}
