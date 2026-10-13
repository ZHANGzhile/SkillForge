import copy

import pytest

from skillforge.environment import Environment
from skillforge.evolution_common.artifacts import SplitLedger
from skillforge.execution_aware.contracts import ExecutionContract
from skillforge.skill_evolution.workflows import GOALS, make_case, private_items, verify_workflow, expressivity


def collect(workflow="logistics_investigation", order=None):
    case = make_case(workflow, 13579, "train")
    env = Environment(fixture=case.fixture)
    initial, items = env.snapshot(), private_items(env)
    for name in (order or GOALS[workflow].required_evidence):
        env.call(name, case.parameters, case.authenticated_customer_id)
    return case, env, initial, items


def verdict(case, env, initial, items):
    return verify_workflow(case, initial, env.snapshot(), env.audit, "completed", items, private_items(env))


def test_goal_is_independent_of_program_and_read_order():
    for order in [("get_order", "get_shipment", "get_order_items"), ("get_order_items", "get_shipment", "get_order")]:
        case, env, initial, items = collect(order=order)
        try:
            assert verdict(case, env, initial, items)["task_success"]
        finally:
            env.close()


def test_stop_and_partial_facts_cannot_pass_eoc():
    case, env, initial, items = collect(order=["get_order"])
    try:
        result = verdict(case, env, initial, items)
        assert not result["task_success"] and "missing_evidence:get_order_items" in result["reason"]
    finally:
        env.close()


@pytest.mark.parametrize("tamper", ["owner", "shipment", "items"])
def test_forged_or_wrong_owner_evidence_is_rejected(tamper):
    case, env, initial, items = collect()
    try:
        if tamper == "owner":
            env.audit[0]["authenticated_customer_id"] = "someone-else"
        elif tamper == "shipment":
            env.audit[1]["result"]["shipment.status"] = "INVENTED"
        else:
            env.audit[2]["result"]["items"][0]["quantity"] += 1
        assert not verdict(case, env, initial, items)["task_success"]
        if tamper == "items":
            # Python True == 1 must not make forged typed evidence pass EOC.
            env.audit[2]["result"]["items"][0]["quantity"] = True
            assert not verdict(case, env, initial, items)["task_success"]
    finally:
        env.close()


def test_readonly_goal_rejects_real_ticket_side_effect():
    case, env, initial, items = collect()
    try:
        env.call("create_ticket", {**case.parameters, "reason": "unrequested"}, case.authenticated_customer_id, "ticket-test")
        result = verdict(case, env, initial, items)
        assert not result["task_success"] and result["actual_workflow_violation"]
        # Creating a ticket is allowed by the business policy, but violates
        # this independent no-write goal. Keep the two Safety labels separate.
        assert not result["actual_policy_violation"]
    finally:
        env.close()


def test_ticket_is_not_claimed_supported_by_current_contract():
    env = Environment()
    tracker = ExecutionContract("ticket-expressivity")
    try:
        tracker.call(lambda name, args, key: env.call(name, args, request_id=key),
                     "create_ticket", {"order_id": "O1", "reason": "investigate"}, "ticket")
        assert len(env.snapshot()["tickets"]) == 1
        assert not tracker.operations and not tracker.receipts
        assert expressivity()["ticket_workflow"] == "UNSUPPORTED"
    finally:
        env.close()


def test_partition_relabeling_collides_and_public_task_has_no_private_data(tmp_path):
    learn, test = make_case("shipment_summary", 13579, "train"), make_case("shipment_summary", 13579, "test")
    ledger = SplitLedger(tmp_path / "ledger")
    ledger.claim(learn.source_group, learn.split, related_groups=[learn.parameters["order_id"]])
    with pytest.raises(ValueError, match="cross splits"):
        ledger.claim(test.source_group, test.split, related_groups=[test.parameters["order_id"]])
    assert set(learn.public_task()) == {"task_id", "family", "request", "parameters"}
    invalid = copy.deepcopy(learn); invalid.goal_hash = "forged"
    with pytest.raises(ValueError, match="goal identity"):
        invalid.public_task()
