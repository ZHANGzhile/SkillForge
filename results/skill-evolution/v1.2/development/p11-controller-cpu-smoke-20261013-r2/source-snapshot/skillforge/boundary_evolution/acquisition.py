"""Two-layer public acquisition with original Bayes/EIG and explicit abstention.

Development candidates only. No policy, fixture, terminal oracle or heldout
imports. A caller must authorize and execute every generated sandbox query.
"""
from pydantic import Field

from ..active_learning import rank_candidates
from ..evolution_schemas import Record, Candidate, fingerprint
from ..execution_aware.acquisition import factors


METHODS = ("OriginalActive", "ExistingActiveV2", "BroadOnly", "DeepOnly", "BroadThenDeep")


class ProbeOptions(Record):
    broad_queries: int = Field(default=3, ge=0, le=20)
    max_generated_candidates: int = Field(default=8, ge=0, le=64)
    # One independent repeat per discriminating factor point, never source replay.
    max_replicates_per_point: int = Field(default=1, ge=0, le=1)
    relative_alternative_mass: float = Field(default=.1, gt=0, le=1, allow_inf_nan=False)


def has_public_conflict(belief):
    return any(row["evidence"]["label"] != "unknown" and
        row["evidence"]["baseline_prediction"] is not None and
        row["evidence"].get("guard_prediction", True) is True and
        (row["evidence"]["label"] == "executable") != row["evidence"]["baseline_prediction"]
        for row in belief.history)


def competing_classes(belief, support, relative_mass=.1):
    """Do not spend Deep budget distinguishing syntactic aliases of one class."""
    groups = {}
    columns = [belief.predictions(c.observations, c.baseline_prediction, c.guard_prediction) for c in support]
    posterior = belief.posterior
    for i, hypothesis in enumerate(belief.hypotheses):
        if hypothesis.kind == "other": continue
        key = tuple(column[i] for column in columns)
        groups.setdefault(key, []).append(i)
    rows = []
    for key, indices in groups.items():
        best = min(indices, key=lambda i: (len(belief.hypotheses[i].predicates), belief.hypotheses[i].hypothesis_id))
        rows.append({"representative": best, "mass": sum(posterior[i] for i in indices), "predictions": key})
    rows.sort(key=lambda r: (-r["mass"], belief.hypotheses[r["representative"]].hypothesis_id))
    if not rows: return []
    return [row for row in rows if row["mass"] >= rows[0]["mass"] * relative_mass]


def deep_requests(belief, candidates, options=None):
    """Generate bounded minimal single-factor controls as public factor requests.

    The actual object/task IDs and baseline/guard predictions must be assigned
    by the trusted sandbox designer. These are proposals, never observations.
    No new hypothesis predicates or thresholds are introduced.
    """
    options = ProbeOptions.model_validate(options or {})
    if not has_public_conflict(belief): return []
    classes = competing_classes(belief, candidates, options.relative_alternative_mass)
    if len(classes) < 2: return []
    hypotheses = [belief.hypotheses[row["representative"]] for row in classes[:2]]
    distinguishing = []
    for candidate in candidates:
        predictions = [h.predict(candidate.observations, candidate.baseline_prediction, candidate.guard_prediction) for h in hypotheses]
        if None not in predictions and predictions[0] != predictions[1] and candidate.guard_prediction is True:
            distinguishing.append(candidate)
    proposals = {}
    def add(facts, source, kind):
        facts = dict(facts)
        if "payment.remaining_amount" in facts and "payment.refunded_amount" in facts:
            facts["payment.captured_amount"] = facts["payment.remaining_amount"] + facts["payment.refunded_amount"]
        if "request.amount" in facts and "payment.remaining_amount" in facts:
            facts["refund.amount_valid"] = 0 < facts["request.amount"] <= facts["payment.remaining_amount"]
        key = fingerprint(facts)
        if key not in proposals and len(proposals) < options.max_generated_candidates:
            proposals[key] = {"request_id": fingerprint(["public-deep-v1", facts]), "factors": dict(facts),
                "origin_candidate": source, "generation_kind": kind, "label": "UNOBSERVED",
                "scope": "sandbox query proposal; not tool evidence or a new predicate"}
    for candidate in sorted(distinguishing, key=lambda c: c.candidate_id):
        for hypothesis in hypotheses:
            for predicate in hypothesis.predicates:
                current = candidate.observations.get(predicate.field)
                # Numeric threshold neighbours come from existing public hypotheses.
                if type(predicate.value) is int and predicate.op in {"lt", "lte", "gt", "gte"}:
                    for value in (predicate.value - 1, predicate.value, predicate.value + 1):
                        if value >= 0 and value != current:
                            add({**candidate.observations, predicate.field: value}, candidate.candidate_id, "threshold_neighbour")
                elif predicate.op in {"eq", "neq"} and type(current) is type(predicate.value) and current != predicate.value:
                    add({**candidate.observations, predicate.field: predicate.value}, candidate.candidate_id, "single_factor_control")
        if options.max_replicates_per_point:
            add(candidate.observations, candidate.candidate_id, "independent_replicate")
        if len(proposals) >= options.max_generated_candidates: break
    return list(proposals.values())


def select(belief, candidates, used, method, *, options=None, cost_lambda=.01, risk_lambda=.01):
    if method not in METHODS: raise ValueError("unknown predeclared development method")
    options = ProbeOptions.model_validate(options or {})
    ranked = rank_candidates(belief, candidates, used, cost_lambda, risk_lambda)
    if not ranked: return None, [], "NO_DISCRIMINATING_PROBE"
    broad = method in {"BroadOnly", "BroadThenDeep"} and len(used) < options.broad_queries
    if broad:
        by_id = {c.candidate_id: c for c in candidates}
        covered = set().union(*(factors(by_id[cid]) for cid in used)) if used else set()
        scored = [{**row, "uncovered_public_factors": len(factors(by_id[row["candidate_id"]]) - covered)} for row in ranked]
        # No added EIG weight: predeclared coverage first, unchanged EIG-cost-risk second.
        scored.sort(key=lambda row: (-row["uncovered_public_factors"], -row["score"], row["candidate_id"]))
        return scored[0], scored, "BROAD"
    return ranked[0], ranked, "DEEP" if method in {"DeepOnly", "BroadThenDeep"} and has_public_conflict(belief) else "EIG"


def supported_stop(belief, candidates, queries, *, max_queries=20, unknown_fraction=.5,
                   threshold=.95, entropy_threshold=.15, other_threshold=.05):
    """No raw top posterior or exhausted-pool fallback is executable admission."""
    result = belief.convergence(candidates, threshold, entropy_threshold, other_threshold)
    valid = [row["evidence"] for row in belief.history if row["evidence"]["label"] != "unknown"]
    unknown = sum(row["evidence"]["label"] == "unknown" for row in belief.history)
    if belief.history and unknown / len(belief.history) > unknown_fraction:
        return "UNKNOWN_OBSERVATIONS", result
    other = result.get("other_posterior", 1.)
    if valid and (other > other_threshold or not result.get("fits_observed_evidence", False)):
        # Mismatch is a declared-domain limitation, never an executable OTHER patch.
        if not any(h.kind != "other" and all(h.predict(e["observations"], e["baseline_prediction"],
            e.get("guard_prediction", True)) ==
            (e["label"] == "executable") for e in valid) for h in belief.hypotheses):
            return "DOMAIN_INSUFFICIENT", result
    if result.get("converged"):
        hypothesis = next(h for h in belief.hypotheses if h.hypothesis_id == result["hypothesis_id"])
        return "SUPPORTED_H0" if hypothesis.kind == "no_change" else "SUPPORTED_CANDIDATE", result
    if queries >= max_queries: return "BUDGET_EXHAUSTED", result
    if other > .5: return "DOMAIN_INSUFFICIENT", result
    return None, result
