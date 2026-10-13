"""Agent arithmetic with world-sequence clusters, never task pseudoreplication."""
from ..boundary_lineage.validation import agent_gate
from ..boundary_lineage.proposal import checked, hashed
from ..evolution_common.artifacts import clone


def clustered_agent_gate(boundary_report, pairs, *, cluster_id, min_groups=6, alpha=.05):
    if not cluster_id: raise ValueError("predeclared independent world-sequence identity required")
    checked(boundary_report)
    grouped = clone(boundary_report)
    for r in grouped["cases"]: r["source_group"] = cluster_id
    grouped = hashed({k: v for k, v in grouped.items() if k != "hash"})
    matched = clone(pairs)
    for r in matched: r["source_group"] = cluster_id
    gate = agent_gate(grouped, matched, min_groups=min_groups, alpha=alpha)
    return hashed({"schema": "world-sequence-agent-admission-v1", "boundary_report_hash": boundary_report["hash"],
        "proposal_hash": boundary_report["proposal_hash"], "parent_bundle_hash": boundary_report["parent_bundle_hash"],
        "candidate_bundle_hash": boundary_report["candidate_bundle_hash"], "pairs": clone(pairs),
        "cluster_id": cluster_id, "decision": gate["decision"], "cluster_gate": gate,
        "options": {"min_groups": min_groups, "alpha": alpha}, "agent_admitted": False, "activated": False,
        "scope": "one proposal in one sequence is one independent cluster, regardless of nested task count; underpowered evidence stays INCONCLUSIVE"})
