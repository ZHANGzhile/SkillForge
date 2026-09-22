from test_refund_skill import refund_data
from skillforge.environment import Environment
from skillforge.skills import compile_skill
from skillforge.learning import validate_skill
from skillforge.runtime import Runtime
from skillforge.model import ScriptedPolicy
from skillforge.schemas import Action
from skillforge.benchmark import summarize


def test_gate_permission_probe_is_not_a_model_policy_attempt(refund_data):
    records, tasks = refund_data
    skill = compile_skill(records, "modify_address")
    validate_skill(skill, [t for t in tasks if t.split == "validation"])
    task = next(t for t in tasks if t.split == "validation" and t.family == "modify_address" and t.fixture.get("wrong_customer"))
    env = Environment(fixture=task.fixture)
    try:
        result = Runtime(ScriptedPolicy(), skills=[skill]).run(task, env)
    finally:
        env.close()
    assert result["verification"]["task_success"]
    assert result["verification"]["attempted_policy_violation"]
    assert not result["policy_attempts"]["model_triggered"]
    assert result["policy_attempts"]["automatic_gate_tool_attempts"] > 0
    summary = summarize([result])
    assert summary["model_attempted_policy_violation_rate"] == 0
    assert summary["automatic_gate_violation_attempt_rate"] == 1


def test_model_selected_permission_probe_has_model_attribution(refund_data):
    _, tasks = refund_data
    task = next(t for t in tasks if t.fixture.get("wrong_customer"))
    env = Environment(fixture=task.fixture)
    try:
        result = Runtime(ScriptedPolicy()).run(task, env)
    finally:
        env.close()
    assert result["policy_attempts"]["model_triggered"]
    assert result["policy_attempts"]["automatic_gate_tool_attempts"] == 0
    assert not result["verification"]["actual_policy_violation"]


def test_blocked_inapplicable_skill_is_still_a_model_attempt(refund_data):
    records, tasks = refund_data
    skill = compile_skill(records, "refund")
    validate_skill(skill, [t for t in tasks if t.split == "validation"])
    task = next(t for t in tasks if t.family == "refund" and t.fixture.get("risk") == "HIGH")
    class UnsafeChoice(ScriptedPolicy):
        def decide(self, context):
            return Action(type="skill", name=skill.skill_id, arguments=task.parameters)
    env = Environment(fixture=task.fixture)
    try:
        result = Runtime(UnsafeChoice(), skills=[skill], max_steps=1).run(task, env)
    finally:
        env.close()
    assert result["policy_attempts"]["blocked_inapplicable_skill_calls"] == 1
    assert result["policy_attempts"]["model_triggered"]
    assert not result["verification"]["actual_policy_violation"]
    assert result["final_state"]["refunds"] == []
