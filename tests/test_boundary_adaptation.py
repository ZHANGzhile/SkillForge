import copy

import pytest

from scripts.bounded_boundary_adapter import adapt
from scripts.evaluate_boundary_adaptation import changed_policy, generate, learning_examples, probe
from scripts.boundary_learning import procedure_hash
from skillforge.environment import Environment, ToolError
import skillforge.environment as environment_module
from skillforge.schemas import Condition
from skillforge.skills import compile_skill
from test_refund_skill import refund_data


def plan():
    return {"version": "test-adaptation", "worlds": {"w1": {"field": "shipment.status", "value": "PROCESSING"},
            "w2": {"field": "order.status", "value": "PENDING"}}, "feature_domains": {
        "customer.risk_level": ["LOW", "MEDIUM", "HIGH"], "payment.status": ["CAPTURED", "PARTIALLY_REFUNDED", "FAILED", "REFUNDED"],
        "order.status": ["CONFIRMED", "PENDING", "CANCELLED"], "shipment.status": ["NOT_STARTED", "PROCESSING", "SHIPPED", "DELIVERED"]}}


def test_same_learner_discovers_distinct_fields_without_policy_argument(refund_data):
    config = plan()
    base = compile_skill(refund_data[0], "refund")
    for world, rule in config["worlds"].items():
        specs = [s for s in generate(config) if s["world"] == world and s["split"] == "train"]
        examples = learning_examples([probe(s, base, rule) for s in specs], config["feature_domains"])
        assert len(examples) == 12 and all("world" not in e and "result" not in e for e in examples)
        learned, trace = adapt(base, examples, config["feature_domains"])
        assert len(trace["steps"]) == 1
        assert trace["steps"][0]["condition"] == {**rule, "op": "eq", "forbidden": True}
        assert procedure_hash(learned) == procedure_hash(base)
        wrong = copy.deepcopy(examples)
        wrong[0]["split"] = "test"
        with pytest.raises(ValueError, match="train"):
            adapt(base, wrong, config["feature_domains"])
        wrong = copy.deepcopy(examples)
        wrong[0]["policy_version"] = "stale"
        with pytest.raises(ValueError, match="versions"):
            adapt(base, wrong, config["feature_domains"])


def test_changed_rule_is_transactional_preserves_idempotency_and_restores():
    original = environment_module.eligibility
    env = Environment(fixture={"shipment": "PROCESSING"})
    try:
        with changed_policy({"field": "shipment.status", "value": "PROCESSING"}):
            with pytest.raises(ToolError, match="refuse"):
                env.call("issue_refund", {"order_id": "O1", "amount": 100}, request_id="r1")
            assert env.snapshot()["payment.refunded_amount"] == 0
            assert env.audit[-1]["error"] == "business_rule_rejected" and not env.audit[-1]["committed"]
        assert environment_module.eligibility is original
        env.call("issue_refund", {"order_id": "O1", "amount": 100}, request_id="r1")
        with changed_policy({"field": "shipment.status", "value": "PROCESSING"}):
            env.call("issue_refund", {"order_id": "O1", "amount": 100}, request_id="r1")
        assert env.snapshot()["payment.refunded_amount"] == 100
        assert len(env.snapshot()["refunds"]) == 1
    finally:
        env.close()
    assert environment_module.eligibility is original


def test_split_combinations_are_disjoint_and_held_out_payment_not_fitted():
    config = plan()
    specs = [s for s in generate(config) if s["world"] == "w1"]
    sets = {split: {tuple(s["fixture"][f] for f in ("risk", "payment", "order", "shipment")) for s in specs if s["split"] == split}
            for split in ("train", "validation", "test")}
    assert [len(sets[s]) for s in sets] == [12, 12, 72]
    assert not sets["train"] & sets["validation"] and not sets["test"] & (sets["train"] | sets["validation"])
    assert all(s["fixture"]["payment"] == "CAPTURED" for s in specs if s["split"] == "train")
