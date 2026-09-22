import pytest

from skillforge.environment import Environment
from skillforge.schemas import Condition, SkillContract, SkillStep
from skillforge.skills import SkillRegistry, execute, gate, hydrate


def address_skill():
    return SkillContract(skill_id="address", family="modify_address", inputs=["order_id", "new_address"],
        preconditions=[Condition(field="shipment.status", value="NOT_STARTED", evidence=["policy:v1.1"])],
        forbidden_conditions=[], procedure=[
            SkillStep(kind="call", tool="update_shipping_address", arguments={"order_id": "$input.order_id", "new_address": "$input.new_address"}),
            SkillStep(kind="call", tool="get_order", arguments={"order_id": "$input.order_id"})],
        postconditions={"order.shipping_address": "$input.new_address"}, source_trajectory_ids=["t1", "t2", "t3"], policy_version="v1.1", status="VERIFIED")


def test_gate_three_states_and_bounded_hydration():
    skill = address_skill()
    state, e = {}, Environment()
    assert gate(skill, state).status == "UNKNOWN"
    hydrate(skill, state, {"order_id": "O1"}, lambda tool, args, key: e.call(tool, args, request_id=key), "gate")
    assert len(e.audit) == 1
    assert gate(skill, state).status == "APPLICABLE"
    state["shipment.status"] = "SHIPPED"
    assert gate(skill, state).status == "INAPPLICABLE"
    e.close()


def test_skill_rechecks_policy_in_tool():
    e = Environment(fixture={"shipment": "SHIPPED"})
    result = execute(address_skill(), {"order_id": "O1", "new_address": "New address 200"}, {"shipment.status": "NOT_STARTED"},
        lambda tool, args, key: e.call(tool, args, request_id=key), "skill")
    assert not result["success"]
    assert result["error"] == "business_rule_rejected"
    assert e.snapshot()["order.shipping_address"] == "Original address 100"
    e.close()


def test_registry_version_immutable(tmp_path):
    registry, skill = SkillRegistry(tmp_path), address_skill()
    registry.save(skill)
    skill.status = "DEPRECATED"
    with pytest.raises(ValueError, match="immutable"):
        registry.save(skill)


def test_dsl_no_arbitrary_nodes():
    with pytest.raises(ValueError):
        SkillStep(kind="python", tool="exec")
