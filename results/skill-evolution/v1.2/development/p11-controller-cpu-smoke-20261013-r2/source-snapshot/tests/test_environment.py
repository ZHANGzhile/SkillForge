import pytest

from skillforge.environment import Environment, ToolError
from skillforge.schemas import ExpectedOutcome, Task
from skillforge.verifier import verify


@pytest.fixture
def env():
    e = Environment()
    yield e
    e.close()


def test_refund_idempotency_after_response_loss():
    e = Environment(faults={"issue_refund": ["response_lost"]})
    with pytest.raises(ToolError, match="response lost"):
        e.call("issue_refund", {"amount": 3000}, request_id="refund-1")
    result = e.call("issue_refund", {"amount": 3000}, request_id="refund-1")
    assert result["transaction_id"]
    assert e.snapshot()["payment.refunded_amount"] == 3000
    assert len(e.snapshot()["refunds"]) == 1
    with pytest.raises(ToolError, match="idempotency_conflict"):
        e.call("issue_refund", {"amount": 1000}, request_id="refund-1")
    e.close()


def test_policy_rechecked_after_state_changed(env):
    assert env.call("get_shipment", {})["shipment.status"] == "NOT_STARTED"
    env.db.execute("UPDATE shipments SET status='SHIPPED'")
    with pytest.raises(ToolError, match="refuse"):
        env.call("update_shipping_address", {"new_address": "New valid address 200"}, request_id="a")
    assert env.snapshot()["order.shipping_address"] == "Original address 100"
    assert env.audit[-1]["attempted_policy_violation"]


@pytest.mark.parametrize("name,args", [("get_order", {}), ("cancel_order", {}), ("issue_refund", {"amount": 10})])
def test_identity_cannot_be_overridden(env, name, args):
    with pytest.raises(ToolError, match="permission_denied"):
        env.call(name, args, customer_id="OTHER", request_id="a")


@pytest.mark.parametrize("amount", [0, -1, 10001, True, 1.5])
def test_invalid_refund_no_state_change(env, amount):
    initial = env.snapshot()
    with pytest.raises(ToolError):
        env.call("issue_refund", {"amount": amount}, request_id="a")
    assert env.snapshot() == initial


def test_expected_outcome_does_not_reward_universal_refusal(env):
    task = Task(task_id="t", family="modify_address", request="change address", split="test", template_id="a", seed=1,
        expected=ExpectedOutcome(allowed_outcomes=["completed"], expected_state={"order.shipping_address": "New address 200"}))
    result = verify(task, env.snapshot(), env.snapshot(), [], "refused")
    assert not result["task_success"]


def test_verification_required_after_mutation(env):
    task = Task(task_id="t", family="modify_address", request="change address", split="test", template_id="a", seed=1,
        expected=ExpectedOutcome(allowed_outcomes=["completed"], expected_state={"order.shipping_address": "New address 200"}))
    initial = env.snapshot()
    env.call("update_shipping_address", {"new_address": "New address 200"}, request_id="a")
    assert "missing_verification" in verify(task, initial, env.snapshot(), env.audit, "completed")["reason"]
    env.call("get_order", {})
    assert verify(task, initial, env.snapshot(), env.audit, "completed")["task_success"]
