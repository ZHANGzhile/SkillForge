"""Finite-domain and parent isolation failures; engineering, no real-model claim."""
import copy

import pytest

from scripts.run_skill_evolution import static_catalog
from skillforge.belief import BeliefState
from skillforge.evolution_schemas import Hypothesis, Candidate, EvidenceView, fingerprint
from skillforge.boundary_runtime.catalog import BoundaryCatalog, h0_bindings
from skillforge.boundary_lineage.proposal import certify, propose, candidate_catalog, hashed, parent_key
from skillforge.boundary_lineage.evidence import VersionedReceiptAdapter
from skillforge.boundary_lineage.validation import declare_boundary_validation, boundary_gate, agent_gate
from skillforge.boundary_lineage.controller import LineageController
from test_boundary_public_receipts import collected


def parent():
    base = static_catalog({"static_bundle": "results/real-v2-frozen/frozen.json"})
    return BoundaryCatalog(base.entries(), h0_bindings(base))


def learning(*, h0=False, unknown=False, mismatch=False):
    hypotheses = [Hypothesis(hypothesis_id="H0", kind="no_change"),
        Hypothesis(hypothesis_id="R", kind="restrict", predicates=[{"field": "shipment.status", "op": "eq", "value": "PROCESSING"}]),
        Hypothesis(hypothesis_id="OTHER", kind="other")]
    belief = BeliefState(hypotheses, "public-learning")
    pool, queries = [], []
    for i in range(12):
        c = Candidate(candidate_id=str(i), member_hash=fingerprint(i), observations={"shipment.status": "PROCESSING"},
            baseline_prediction=True, guard_prediction=True, cost=1, mutation_probability=1)
        # H0 challenge needs two distinct factor points, not aliased retries.
        if i % 2: c = c.model_copy(update={"observations": {"shipment.status": "PROCESSING", "request.amount": 100}})
        e = EvidenceView(evidence_id=fingerprint(["e", i]), trajectory_id=str(i), member_hash=c.member_hash,
            split="explore", policy_epoch="public-learning", family="refund", observations=c.observations,
            baseline_prediction=True, guard_prediction=True, label="unknown" if unknown else
            "executable" if (h0 or mismatch and i % 2) else "not_executable", origin="controlled_procedure", tool_calls=1)
        belief.update(e); pool.append(c)
        queries.append(hashed({"candidate_id": c.candidate_id, "evidence": e.model_dump(mode="json")}))
    return {"belief": belief.snapshot(), "queries": queries, "final_support": [c.model_dump(mode="json") for c in pool]}


def test_domain_mismatch_unknown_and_support_abstain_without_executable_other():
    assert certify(learning(unknown=True))["status"] == "UNKNOWN_OBSERVATIONS"
    assert certify(learning(mismatch=True))["status"] == "DOMAIN_INSUFFICIENT"
    raw = learning(); raw["final_support"] = []
    # A query cannot survive removal of its registered pool member.
    with pytest.raises(ValueError, match="support"): certify(raw)
    p = propose(parent(), "refund_captured_payment", learning(unknown=True))
    assert not p["executable"] and p["schema"] == "boundary-proposal-abstention-v1"


def test_h0_restoration_and_noop_are_relative_to_actual_parent():
    old = parent(); p = propose(old, "refund_captured_payment", learning())
    assert p["decision"] == "PROPOSE_BOUNDARY"
    new = candidate_catalog(old, p)
    assert new.entries() == old.entries() and new.bundle_hash != old.bundle_hash
    restored = propose(new, "refund_captured_payment", learning(h0=True))
    assert restored["decision"] == "PROPOSE_BOUNDARY" and restored["patch"]["kind"] == "no_change"
    assert candidate_catalog(new, restored).bundle_hash == old.bundle_hash
    assert propose(old, "refund_captured_payment", learning(h0=True))["decision"] == "RETAIN_PARENT"
    with pytest.raises(ValueError, match="stale"): candidate_catalog(new, p)


def test_h0_insufficient_distinct_challenges_cannot_certify():
    raw = learning(h0=True)
    for c in raw["final_support"]: c["observations"] = {"shipment.status": "PROCESSING"}
    # Rebuild matching evidence to represent actual independent repeats of one point.
    b = BeliefState([Hypothesis.model_validate(h) for h in raw["belief"]["hypotheses"]], "public-learning")
    for q in raw["queries"]:
        q["evidence"]["observations"] = {"shipment.status": "PROCESSING"}
        b.update(q["evidence"]); q.update(hash=fingerprint({k: v for k, v in q.items() if k != "hash"}))
    raw["belief"] = b.snapshot()
    assert certify(raw)["status"] == "H0_CHALLENGE_INSUFFICIENT"


def test_versioned_daily_receipt_uses_effective_parent_but_learning_uses_original(monkeypatch):
    base, task, raw, member = collected(monkeypatch)
    bindings = h0_bindings(base)
    bindings[member["skill_id"]]["patch"] = {"hypothesis_id": "R", "kind": "restrict",
        "predicates": [{"field": "request.amount", "op": "gt", "value": 50}]}
    catalog = BoundaryCatalog(base.entries(), bindings)
    member.update(boundary_bundle_hash=catalog.bundle_hash, boundary_revision=catalog.public_boundary(member["skill_id"])["revision"])
    result = VersionedReceiptAdapter({task["task_id"]: member}, catalog).export(raw, task)
    assert result["drift_interaction"]["evidence"]["baseline_prediction"] is False
    assert result["absolute_learning_evidence"]["baseline_prediction"] is True
    assert result["drift_interaction"]["parent_revision"] == parent_key(catalog, member["skill_id"])
    h0 = BoundaryCatalog(base.entries(), h0_bindings(base))
    with pytest.raises(ValueError, match="current Boundary"):
        VersionedReceiptAdapter({task["task_id"]: member}, h0).export(raw, task)
    assert "private_gold" not in str(result)


def validation_fixture():
    old = parent(); result = learning(); p = propose(old, "refund_captured_payment", result)
    members = [{"task_id": str(i), "task_hash": fingerprint(i), "source_group": str(i),
        "split": "validation" if i < 8 else "stable_validation"} for i in range(9)]
    plan = declare_boundary_validation(old, p, members)
    rows = [{**m, "truth": i == 7, "parent": True if i < 7 else i == 7, "candidate": i == 7,
        "probe_hash": fingerprint(["actual", i]), "actual_violations": 0, "agent_planned": True} for i, m in enumerate(members)]
    br = boundary_gate(plan, rows)
    pairs = []
    for i, m in enumerate(members):
        arm = {"execution_identity": "same-runtime-and-model", "tokens": 10, "model_calls": 1,
            "actual_violations": 0, "attempted_violations": 0, "cost_settled": True}
        pairs.append({**m, "initial_state_hash": fingerprint(["state", i]),
            "parent": {**arm, "bundle_hash": old.bundle_hash, "evidence_hash": fingerprint(["old", i]), "eoc": i >= 7},
            "candidate": {**arm, "bundle_hash": p["candidate_bundle_hash"], "evidence_hash": fingerprint(["new", i]), "eoc": True}})
    ar = agent_gate(br, pairs)
    return old, {"parent_bundle_hash": old.bundle_hash, "skill_id": p["skill_id"], "proposal": p,
        "learner_result": result, "boundary_plan": plan, "boundary_report": br, "agent_report": ar}


def test_layered_gates_preserve_stable_regressions_and_never_accept_test():
    old, data = validation_fixture()
    assert data["agent_report"]["decision"] == "AGENT_GATE_PASSED"
    cases = copy.deepcopy(data["boundary_report"]["cases"]); cases[-1]["candidate"] = True
    assert boundary_gate(data["boundary_plan"], cases)["decision"] == "REJECTED"
    pairs = copy.deepcopy(data["agent_report"]["pairs"]); pairs[-1]["candidate"]["eoc"] = False
    assert agent_gate(data["boundary_report"], pairs)["decision"] == "REJECTED"
    members = copy.deepcopy(data["boundary_plan"]["members"]); members[0]["split"] = "test"
    with pytest.raises(ValueError, match="never test"): declare_boundary_validation(old, data["proposal"], members)


def test_lineage_needs_independent_audit_and_replays_retained_parent(tmp_path):
    old, data = validation_fixture()
    def auditor(d, previous, candidate):
        return hashed({"schema": "boundary-lineage-independent-evidence-audit-v1", "passed": True, "mode": "engineering",
            "proposal_hash": d["proposal"]["hash"], "boundary_report_hash": d["boundary_report"]["hash"],
            "agent_report_hash": d["agent_report"]["hash"], "raw_evidence_index_hash": fingerprint("engineering fixture only")})
    ctrl = LineageController(tmp_path, old, protocol_hash="dev", evidence_auditor=auditor)
    one = ctrl.finish(data)
    assert one["decision"] == "ENGINEERING_ACTIVATED" and not one["agent_admitted"]
    ctrl.finish({"parent_bundle_hash": ctrl.current.bundle_hash, "reason": "NO_CHANGE"})
    assert LineageController(tmp_path, old, protocol_hash="dev", evidence_auditor=auditor).checkpoint() == ctrl.checkpoint()
    with pytest.raises(ValueError, match="stale"): ctrl.finish(data)
    broken = LineageController(tmp_path / "broken", old, protocol_hash="dev", evidence_auditor=lambda *args: {"passed": True})
    with pytest.raises(ValueError): broken.finish(data)
    assert broken.current.bundle_hash == old.bundle_hash and not broken.history
