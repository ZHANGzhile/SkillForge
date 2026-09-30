import copy
import json

import pytest

from scripts.boundary_learning import public_contract
from scripts.boundary_representation import ViewClient, equivalent_states, render
from scripts.boundary_runtime import BoundaryRuntime
from scripts.evaluate_boundary_representation import validate_row
from scripts.prepare_boundary_study import generate
from skillforge.environment import Environment
from skillforge.model import ScriptedPolicy
from skillforge.schemas import Condition
from skillforge.skills import compile_skill
from test_refund_skill import refund_data


@pytest.fixture
def base(refund_data):
    skill = compile_skill(refund_data[0], "refund")
    skill.preconditions = [c for c in skill.preconditions if c.field != "payment.status"]
    skill.forbidden_conditions.insert(0, Condition(field="payment.status", value="FAILED", evidence=["test-failure"]))
    skill.status = "VALIDATING"
    return skill


def test_partial_and_out_of_domain_applicability_is_preserved(base):
    proof = equivalent_states(base)
    assert proof["checked"] == 192 and proof["transformed"] == 96
    assert set(proof["states"]) == {"APPLICABLE", "INAPPLICABLE", "UNKNOWN"}


def test_renderer_preserves_source_and_refunded_or_missing_state(base):
    context = {"observations": {"payment.status": "CAPTURED"}, "executable_skills": [public_contract(base)]}
    original = copy.deepcopy(context)
    shown = render(context, "allowlist_view")
    assert context == original and shown != context
    for field in ("procedure", "inputs", "postconditions", "skill_id"):
        assert shown["executable_skills"][0][field] == context["executable_skills"][0][field]
    for state in ({}, {"payment.status": "REFUNDED"}, {"payment.status": "UNDECLARED"}):
        context["observations"] = state
        assert render(context, "allowlist_view") == context


@pytest.mark.parametrize("scenario", ["normal_low", "high_risk"])
def test_execution_stays_on_b_and_actual_sent_input_is_audited(base, scenario):
    task = next(t for t in generate({"version": "representation-test", "seed": 999})
                if t.family == "refund" and t.split == "test" and t.structure_id.endswith(":" + scenario))
    class Model(ScriptedPolicy):
        model = "explicit-test-double"
        settings = {"server_identity": {"model": "explicit-test-double"}}
        fatal_error = None
    results = []
    original = base.model_dump()
    for arm in ("original", "allowlist_view"):
        client, env = ViewClient(Model(), arm), Environment(fixture=task.fixture)
        try:
            row = BoundaryRuntime(client, skills=[base]).run(task, env)
        finally:
            env.close()
        row["boundary_experiment"]["actual_model_inputs"] = client.inputs
        row["representation"] = {"arm": arm, "actual_user_messages": client.messages}
        frozen = {"model_settings": Model.settings["server_identity"]}
        boundaries = {"groups": {"B": {"refund": base.model_dump()}}}
        item = {"kind": "system", "task": task.task_id, "arm": arm}
        validate_row(row, item, frozen, {}, {task.task_id: task}, boundaries)
        assert row["verification"]["task_success"]
        assert not row["verification"]["actual_policy_violation"]
        if arm == "allowlist_view" and scenario == "normal_low":
            assert row["steps"][0]["context"] != client.inputs[0]
            tampered = copy.deepcopy(row)
            tampered["representation"]["actual_user_messages"][0] = json.dumps(row["steps"][0]["context"], ensure_ascii=False)
            with pytest.raises(ValueError, match="model input"):
                validate_row(tampered, item, frozen, {}, {task.task_id: task}, boundaries)
        results.append(row)
    assert base.model_dump() == original
    assert [s["action"] for s in results[0]["steps"]] == [s["action"] for s in results[1]["steps"]]
    assert results[0]["metrics"]["tool_calls"] == results[1]["metrics"]["tool_calls"]
