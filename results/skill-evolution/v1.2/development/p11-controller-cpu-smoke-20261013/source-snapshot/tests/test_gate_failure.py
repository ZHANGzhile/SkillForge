from skillforge.benchmark import generate_tasks
from skillforge.environment import Environment
from skillforge.model import ScriptedPolicy
from skillforge.runtime import Runtime
from skillforge.schemas import Action, Condition, SkillContract, SkillStep


def test_gate_errors_are_visible_and_cannot_reset_retry_budget():
    task = generate_tasks()[0]
    task.expected.allowed_outcomes = ["escalated"]
    task.expected.expected_state = {}
    task.expected.unchanged_fields = ["order.shipping_address"]
    skill = SkillContract(skill_id="read_guard", family="modify_address", inputs=["order_id"],
        preconditions=[Condition(field="order.status", value="CONFIRMED", evidence=["policy:v1.1"])],
        forbidden_conditions=[], procedure=[SkillStep(kind="finish")], postconditions={},
        source_trajectory_ids=["t1"], policy_version="v1.1", status="VERIFIED")
    env = Environment(faults={"get_order": ["timeout", "timeout"]})
    result = Runtime(ScriptedPolicy(), skills=[skill]).run(task, env)
    assert result["verification"]["task_success"]
    assert result["steps"][0]["context"]["gate_observations"][0]["retry_exhausted"]
    assert sum(e["tool_name"] == "get_order" for e in result["tool_audit"]) == 2
    env.close()


def test_duplicate_refund_across_model_steps_keeps_operation_identity():
    class RepeatingPolicy(ScriptedPolicy):
        def decide(self, context):
            if len(context["history"]) < 2:
                return Action(type="tool", name="issue_refund", arguments=context["parameters"])
            if len(context["history"]) == 2:
                return Action(type="tool", name="get_payment", arguments={"order_id": "O1"})
            return Action(type="stop")
    task = generate_tasks()[11]
    env = Environment()
    result = Runtime(RepeatingPolicy()).run(task, env)
    assert result["verification"]["task_success"]
    assert len(result["final_state"]["refunds"]) == 1
    assert result["tool_audit"][0]["request_id"] == result["tool_audit"][1]["request_id"]
    env.close()
