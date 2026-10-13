"""Deterministic gap clustering; causal diagnoses require explicit evidence.

Terminal diagnostic flags are consumed only by the secondary lane. Main boundary
clustering uses EvidenceViews; it cannot inspect fixtures or terminal oracles.
"""
from collections import defaultdict

from .evolution_schemas import EvidenceView, fingerprint

GAP_TYPES = {"wrong_terminal", "premature_refusal", "premature_escalation", "read_loop",
    "missing_verification", "blocked_mutation", "gate_false_allow", "gate_false_block",
    "unknown_applicability", "skill_execution_failure", "policy_disagreement", "repeated_failure_cluster"}
PATTERN_FIELDS = ("customer.risk_level", "order.status", "shipment.status", "payment.status", "address.valid", "refund.amount_valid")


def detect_gaps(evidence, diagnostics=(), lane="boundary"):
    if lane not in {"boundary", "secondary"}:
        raise ValueError("unknown diagnostic lane")
    if lane == "boundary" and diagnostics:
        raise ValueError("terminal diagnostic feedback is forbidden in the boundary lane")
    buckets = defaultdict(dict)
    def add(view, kind, confirmed=True):
        pattern = {k: view.observations[k] for k in PATTERN_FIELDS if k in view.observations}
        key = (view.family, view.policy_epoch, kind, fingerprint(pattern), confirmed)
        buckets[key][view.trajectory_id] = (view, pattern)
    views = {}
    for item in evidence:
        view = EvidenceView.model_validate(item)
        if view.trajectory_id in views and views[view.trajectory_id] != view:
            raise ValueError("conflicting source evidence")
        views[view.trajectory_id] = view
        if view.label == "unknown":
            add(view, "unknown_applicability", False)
        elif view.label == "not_executable":
            add(view, "blocked_mutation")
            if view.baseline_prediction is True:
                add(view, "gate_false_allow")
                add(view, "policy_disagreement")
        elif view.baseline_prediction is False:
            add(view, "gate_false_block")
            add(view, "policy_disagreement")
    for diagnostic in diagnostics:
        view = views[diagnostic["trajectory_id"]]
        flags = set(diagnostic.get("verified_flags", []))
        if not flags <= GAP_TYPES:
            raise ValueError("unsupported diagnostic type")
        for flag in flags:
            add(view, flag, bool(diagnostic.get("confirmed", False)))
    output = []
    for key, members in sorted(buckets.items()):
        family, epoch, kind, _, confirmed = key
        ids = sorted(members)
        pattern = members[ids[0]][1]
        row = {"gap_id": fingerprint(list(key)), "family": family, "policy_epoch": epoch,
            "gap_type": kind, "evidence_trajectory_ids": ids, "observed_states": pattern,
            "candidate_fields": sorted(set().union(*(v.observations for v, _ in members.values()))),
            "confidence": "confirmed_by_interaction" if confirmed else "suspected",
            "severity": "high" if kind == "gate_false_allow" else "medium",
            "lane": lane, "expected_outcomes": [], "failed_actions": [],
            "revision_supported": kind in {"gate_false_allow", "gate_false_block", "policy_disagreement"}}
        output.append(row)
        if len(ids) >= 2 and kind in {"gate_false_allow", "gate_false_block", "blocked_mutation"}:
            output.append({**row, "gap_id": fingerprint([list(key), "cluster"]),
                "gap_type": "repeated_failure_cluster", "source_gap_type": kind})
    return sorted(output, key=lambda row: row["gap_id"])


def trajectory_diagnostics(trajectory):
    """Secondary, trusted telemetry diagnosis; does not infer unknown EOC labels."""
    flags = set()
    verification = trajectory.get("verification", {})
    reasons = verification.get("reason", [])
    if "unexpected_outcome" in reasons and trajectory.get("outcome") in {"refused", "escalated"}:
        flags.add("wrong_terminal")
        flags.add("premature_refusal" if trajectory["outcome"] == "refused" else "premature_escalation")
    if "missing_verification" in reasons:
        flags.add("missing_verification")
    streak, previous = 0, None
    for step in trajectory.get("steps", []):
        action = step.get("action") or {}
        # Errors/retries and different visible observations reset the loop streak.
        if action.get("type") == "tool" and action.get("name", "").startswith("get_") and not step.get("error"):
            key = fingerprint([action, step.get("context", {}).get("observations", {}), step.get("result")])
            streak = streak + 1 if key == previous else 1
            previous = key
            if streak >= 3:
                flags.add("read_loop")
        else:
            streak, previous = 0, None
    if any(not e.get("success") and not e.get("blocked") for e in trajectory.get("skill_events", [])):
        flags.add("skill_execution_failure")
    return {"trajectory_id": trajectory["trajectory_id"], "verified_flags": sorted(flags), "confirmed": True}
