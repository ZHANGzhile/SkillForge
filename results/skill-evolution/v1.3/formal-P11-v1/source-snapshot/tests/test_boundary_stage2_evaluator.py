"""Actual policies must be identical across arms, including legitimate relax."""
from scripts.boundary_stage2_evaluator import expected_task, private_policy
from skillforge.environment import Environment
from skillforge.schemas import Task
from skillforge.verifier import verify


def test_private_relaxation_allows_actual_tools_and_independent_eoc():
    fixture = {"order_id": "O-new", "customer_id": "C-new", "risk": "LOW", "shipment": "PROCESSING"}
    params = {"order_id": "O-new", "new_address": "Delivery lane 204"}
    task = Task.model_validate(expected_task("new", "modify_address", fixture, params, "W6"))
    env = Environment(fixture=fixture)
    try:
        initial = env.snapshot("O-new")
        with private_policy("W6"):
            env.call("update_shipping_address", params, "C-new", "actual-write")
            env.call("get_order", {"order_id": "O-new"}, "C-new", "actual-verify")
            result = verify(task, initial, env.snapshot("O-new"), env.audit, "completed")
        assert result["task_success"] and not result["actual_policy_violation"]
        # Leaving the context restores the original policy, without modifying
        # the immutable old verifier or the deployed environment.
        assert not verify(task, initial, env.snapshot("O-new"), env.audit, "completed")["task_success"]
    finally: env.close()


def test_restriction_terminal_expectation_does_not_become_binary_label():
    fixture = {"order_id": "O-new", "customer_id": "C-new", "risk": "LOW", "shipment": "PROCESSING"}
    task = Task.model_validate(expected_task("new", "refund", fixture, {"order_id": "O-new", "amount": 100}, "W1"))
    assert task.expected.allowed_outcomes == ["escalated"]
    assert not task.expected.expected_state and "payment.refunded_amount" in task.expected.unchanged_fields
