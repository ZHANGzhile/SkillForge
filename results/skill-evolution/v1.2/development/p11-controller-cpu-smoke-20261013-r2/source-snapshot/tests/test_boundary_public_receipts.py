"""Real isolated SQLite and receipt adapter; no model or research claim."""
import copy

import pytest

from scripts.run_skill_evolution import static_catalog
from skillforge.environment import Environment
from skillforge.evolution_execution import execute_frozen
from skillforge.evolution_schemas import fingerprint
from skillforge.execution_aware.contracts import ExecutionContract
from skillforge.boundary_evolution.evidence import PublicReceiptAdapter


def collected(monkeypatch, *, reject=False):
    catalog = static_catalog({"static_bundle": "results/real-v2-frozen/frozen.json"})
    entry = next(row for row in catalog.entries() if row["contract"]["family"] == "refund")
    if reject:
        from skillforge import environment
        original = environment.eligibility
        monkeypatch.setattr(environment, "eligibility", lambda name, state, args:
                            "refuse" if name == "issue_refund" else original(name, state, args))
    task = {"task_id": "public-task", "family": "refund", "request": "Refund 100 minor units",
            "parameters": {"order_id": "O-public", "amount": 100}}
    env = Environment(fixture={"order_id": "O-public"})
    tracker = ExecutionContract(task["task_id"])
    def dispatch(name, args, key): return env.call(name, args, "C1", key)
    def call(name, args, key): return tracker.call(dispatch, name, args, key, source="skill")
    try:
        execute_frozen(entry["contract"], task["parameters"], call, task["task_id"])
        raw = {"task_id": task["task_id"], "trajectory_id": "receipt-source",
               "tool_audit": copy.deepcopy(env.audit), "execution_contract": tracker.checkpoint(),
               "private_gold": "DO NOT EXPORT", "verification": {"expected_outcome": "private"}}
    finally: env.close()
    member = {"task_hash": fingerprint(task), "raw_hash": fingerprint(raw), "skill_id": entry["skill_id"],
        "parent_revision": entry["revision"], "source_group": "actual-source", "probe_origin": "daily",
        "evidence_origin": "controlled_procedure"}
    return catalog, task, raw, member


def test_positive_requires_matching_immutable_receipt_and_hides_private_fields(monkeypatch):
    catalog, task, raw, member = collected(monkeypatch)
    item = PublicReceiptAdapter({task["task_id"]: member}, catalog).export(raw, task)
    assert item.feedback == "business" and item.evidence.label == "executable"
    assert item.evidence.baseline_prediction is True and item.evidence.guard_prediction is True
    assert "private" not in item.model_dump_json() and "gold" not in item.model_dump_json()
    assert item.evidence.observations["payment.refunded_amount"] == 0  # pre-mutation facts only
    raw.pop("execution_contract")
    member["raw_hash"] = fingerprint(raw)
    item = PublicReceiptAdapter({task["task_id"]: member}, catalog).export(raw, task)
    assert item.feedback == "verification" and item.evidence.label == "unknown"


def test_actual_business_rejection_not_terminal_label(monkeypatch):
    catalog, task, raw, member = collected(monkeypatch, reject=True)
    item = PublicReceiptAdapter({task["task_id"]: member}, catalog).export(raw, task)
    assert item.feedback == "business" and item.evidence.label == "not_executable"


def test_pinned_raw_and_task_cannot_be_forged(monkeypatch):
    catalog, task, raw, member = collected(monkeypatch)
    adapter = PublicReceiptAdapter({task["task_id"]: member}, catalog)
    raw["tool_audit"][0]["result"]["customer.risk_level"] = "HIGH"
    with pytest.raises(ValueError, match="exact pinned"):
        adapter.export(raw, task)


def test_other_object_verification_does_not_certify_this_mutation(monkeypatch):
    catalog, task, raw, member = collected(monkeypatch)
    raw["execution_contract"]["body"]["receipts"][0]["object_id"] = "other-object"
    body = raw["execution_contract"]["body"]
    raw["execution_contract"]["hash"] = fingerprint(body)
    member["raw_hash"] = fingerprint(raw)
    item = PublicReceiptAdapter({task["task_id"]: member}, catalog).export(raw, task)
    assert item.evidence.label == "unknown" and item.feedback == "verification"
