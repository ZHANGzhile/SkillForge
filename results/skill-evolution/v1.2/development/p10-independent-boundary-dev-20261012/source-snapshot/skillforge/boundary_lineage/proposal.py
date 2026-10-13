"""Finite-support certification and absolute business Boundary proposals.

No world, evaluator, task fixture, heldout outcome or tool capability is used.
H0 restores the frozen original business rule, not necessarily today's parent.
"""
from ..belief import BeliefState
from ..evolution_schemas import Candidate, Hypothesis, fingerprint
from ..evolution_common.artifacts import clone
from ..execution_aware.challenge import ChallengeOptions, challenge_gate
from ..boundary_runtime.catalog import BoundaryCatalog


def hashed(body): return {**body, "hash": fingerprint(body)}


def checked(value):
    if value.get("hash") != fingerprint({k: v for k, v in value.items() if k != "hash"}):
        raise ValueError("content identity mismatch")
    return value


def semantic_patch(raw):
    patch = Hypothesis.model_validate(raw)
    return {"kind": patch.kind, "predicates": sorted(
        [p.model_dump(mode="json") for p in patch.predicates], key=fingerprint)}


def parent_key(catalog, skill_id):
    binding = catalog.boundaries()[skill_id]
    entry = catalog.get(skill_id, binding["parent_revision"])
    return fingerprint({"skill_id": skill_id, "program_revision": entry["revision"],
        "boundary_revision": catalog.public_boundary(skill_id)["revision"]})


def certify(result, *, max_queries=20, threshold=.95, entropy_threshold=.15, other_threshold=.05,
            max_unknown_fraction=.5, challenge_k=2):
    """Recompute support from exact Bayes history; never trust result flags.

    The support is the finite registered candidate pool, not the full Cartesian
    schema. UNKNOWN is neither negative evidence nor a completed challenge.
    The adoption gate applies uniformly; it does not alter acquisition rankings.
    """
    if type(max_queries) is not int or not 1 <= max_queries <= 20:
        raise ValueError("original bounded query budget required")
    if not 0 <= max_unknown_fraction <= 1 or not 1 <= challenge_k <= max_queries:
        raise ValueError("invalid predeclared support thresholds")
    belief = BeliefState.restore(result["belief"])
    pool = [Candidate.model_validate(row) for row in result["final_support"]]
    if len({c.candidate_id for c in pool}) != len(pool): raise ValueError("duplicate support identity")
    queries = result["queries"]
    if len(queries) > max_queries or len({q["candidate_id"] for q in queries}) != len(queries):
        raise ValueError("query budget or unique source identity violated")
    history = {r["evidence"]["evidence_id"]: r["evidence"] for r in belief.history}
    evidence = {}
    by_id = {c.candidate_id: c for c in pool}
    for query in queries:
        checked(query)
        ev = query["evidence"]
        if ev["split"] != "explore" or history.get(ev["evidence_id"]) != ev:
            raise ValueError("query is not an actual Bayes explore receipt")
        c = by_id.get(query["candidate_id"])
        if (c is None or not c.member_hash or ev["member_hash"] != c.member_hash or
                ev["baseline_prediction"] != c.baseline_prediction or ev["guard_prediction"] != c.guard_prediction or
                any(ev["observations"].get(k) != v for k, v in c.observations.items())):
            raise ValueError("query not bound to declared public support")
        evidence[query["candidate_id"]] = ev
    if {r["evidence"]["evidence_id"] for r in belief.history if r["evidence"]["split"] == "explore"} != {
            q["evidence"]["evidence_id"] for q in queries}:
        raise ValueError("unaccounted exploration evidence")
    raw = belief.convergence(pool, threshold, entropy_threshold, other_threshold)
    valid = [r["evidence"] for r in belief.history if r["evidence"]["label"] != "unknown"]
    unknown = len(belief.history) - len(valid)
    fits = [h for h in belief.hypotheses if h.kind != "other" and valid and all(
        h.predict(e["observations"], e["baseline_prediction"], e["guard_prediction"]) ==
        (e["label"] == "executable") for e in valid)]
    top = next((h for h in belief.hypotheses if h.hypothesis_id == raw.get("hypothesis_id")), None)
    gate = None
    if top is not None and top.kind == "no_change" and pool:
        gate = challenge_gate(belief, pool, evidence, ChallengeOptions(k=challenge_k, max_queries=max_queries))
    remaining = [c for c in pool if c.candidate_id not in evidence and
        len({p for p in belief.predictions(c.observations, c.baseline_prediction, c.guard_prediction)
             if p is not None}) >= 2]
    if not pool: status = "NO_DECLARED_SUPPORT"
    elif belief.history and unknown / len(belief.history) > max_unknown_fraction: status = "UNKNOWN_OBSERVATIONS"
    elif valid and not fits: status = "DOMAIN_INSUFFICIENT"
    elif raw.get("converged") and gate and (not gate["passed"] or gate["coverage_shortfall"]):
        status = "H0_CHALLENGE_INSUFFICIENT"
    elif raw.get("converged") and top and top.kind != "other": status = "SUPPORTED_CANDIDATE"
    elif len(queries) >= max_queries: status = "BUDGET_EXHAUSTED"
    elif raw.get("other_posterior", 1) > .5: status = "DOMAIN_INSUFFICIENT"
    elif not remaining: status = "NO_DISCRIMINATING_PROBE"
    else: status = "INCONCLUSIVE"
    return hashed({"schema": "finite-boundary-support-certificate-v1", "status": status,
        "belief_hash": fingerprint(result["belief"]), "pool_hash": fingerprint(result["final_support"]),
        "query_hashes": [q["hash"] for q in queries], "charged_queries": len(queries),
        "unknown_observations": unknown, "known_observations": len(valid), "raw_convergence": raw,
        "hypothesis": top.model_dump(mode="json") if top else None, "h0_challenge": gate,
        "limits": {"max_queries": max_queries, "threshold": threshold, "entropy_threshold": entropy_threshold,
            "other_threshold": other_threshold, "max_unknown_fraction": max_unknown_fraction, "challenge_k": challenge_k},
        "scope": "equivalence only on the declared finite pool; independent Boundary and Agent gates still required"})


def propose(catalog, skill_id, result, *, certificate_options=None):
    if not isinstance(catalog, BoundaryCatalog): raise ValueError("versioned current parent required")
    certificate = certify(result, **(certificate_options or {}))
    if certificate["status"] != "SUPPORTED_CANDIDATE":
        return hashed({"schema": "boundary-proposal-abstention-v1", "parent_key": parent_key(catalog, skill_id),
            "certificate": certificate, "decision": certificate["status"], "executable": False})
    patch = Hypothesis.model_validate(certificate["hypothesis"])
    if patch.kind == "other": raise ValueError("OTHER is not executable")
    current = catalog.boundaries()[skill_id]
    bindings = catalog.boundaries(); bindings[skill_id]["patch"] = patch.model_dump(mode="json")
    candidate = BoundaryCatalog(catalog.entries(), bindings)
    unchanged = semantic_patch(current["patch"]) == semantic_patch(patch.model_dump(mode="json"))
    return hashed({"schema": "skill-bound-boundary-proposal-v1", "skill_id": skill_id,
        "program_revision": current["parent_revision"], "program_hash": current["program_hash"],
        "parent_key": parent_key(catalog, skill_id), "parent_boundary_revision": catalog.public_boundary(skill_id)["revision"],
        "parent_bundle_hash": catalog.bundle_hash, "candidate_bundle_hash": candidate.bundle_hash,
        "patch": patch.model_dump(mode="json"), "support_domain": clone(current["support_domain"]),
        "certificate": certificate, "decision": "RETAIN_PARENT" if unchanged else "PROPOSE_BOUNDARY",
        "semantics": "absolute replacement against the frozen original business rule; not incremental OR/AND composition",
        "terminal_policy": "inherited-terminal-rules-v1", "executable": True,
        "boundary_admitted": False, "agent_admitted": False, "activated": False})


def candidate_catalog(parent, proposal):
    checked(proposal)
    if (proposal.get("schema") != "skill-bound-boundary-proposal-v1" or not proposal["executable"] or
            proposal["parent_bundle_hash"] != parent.bundle_hash or
            proposal["parent_key"] != parent_key(parent, proposal["skill_id"])):
        raise ValueError("stale, unsupported or wrongly bound proposal")
    current = parent.boundaries()[proposal["skill_id"]]
    if any(proposal[k] != current[v] for k, v in (("program_revision", "parent_revision"), ("program_hash", "program_hash"),
                                                 ("support_domain", "support_domain"))):
        raise ValueError("program or declared support cannot change")
    bindings = parent.boundaries(); bindings[proposal["skill_id"]]["patch"] = clone(proposal["patch"])
    result = BoundaryCatalog(parent.entries(), bindings)
    if result.bundle_hash != proposal["candidate_bundle_hash"]: raise ValueError("candidate bundle mismatch")
    return result
