import pytest

from skillforge.benchmark import generate_tasks
from skillforge.environment import Environment, ToolError
from skillforge.learning import build_sft, validate_skill
from skillforge.retrieval import retrieve_memory
from skillforge.skills import compile_address


def test_learning_rejects_test_contamination():
    with pytest.raises(ValueError, match="train"):
        compile_address([{"split": "test"}])
    with pytest.raises(ValueError, match="train"):
        build_sft([{"split": "test"}])
    with pytest.raises(ValueError, match="train"):
        retrieve_memory("hello", "modify_address", [{"split": "test"}])
    with pytest.raises(ValueError, match="validation"):
        validate_skill(None, generate_tasks("test"))


def test_action_filter_keeps_real_context_but_not_bad_targets():
    history = {"history": [{"action": "wrong", "error": "business_rule_rejected"}]}
    trace = {"split": "train", "trajectory_id": "t", "verification": {"task_success": True, "actual_policy_violation": False},
        "steps": [{"step_id": 0, "action": {"type": "tool", "name": "bad"}, "error": "business_rule_rejected", "context": {}},
                  {"step_id": 1, "action": {"type": "escalate"}, "context": history}]}
    records = build_sft([trace])
    assert len(records) == 1
    assert records[0]["prompt"] == history


def test_tool_schema_rejects_customer_override():
    e = Environment()
    with pytest.raises(ToolError, match="arguments do not match"):
        e.call("issue_refund", {"amount": 2000, "customer_id": "C1"}, request_id="a")
    assert not e.snapshot()["refunds"]
    assert e.call("get_order_items", {})["items"][0]["quantity"] == 1
    e.close()


def test_blocked_skill_attempt_is_counted():
    from skillforge.runtime import Runtime
    from skillforge.schemas import Action
    class BadPolicy:
        tokens = 0
        model = "bad-fixture"
        def decide(self, context):
            return Action(type="skill", name="nonexistent")
    e = Environment()
    result = Runtime(BadPolicy(), max_steps=1).run(generate_tasks()[0], e)
    assert result["metrics"]["skill_calls"] == 1
    assert result["skill_events"][0]["blocked"]
    assert "wrong_skill" in result["error_categories"]
    e.close()
