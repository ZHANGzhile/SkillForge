import copy
import json

import pytest

from scripts.boundary_runtime import BoundaryRuntime, POLICY_TEXT
from scripts.evaluate_refund_priority import admission, decision_context, decision_score, summary, validate_row
from scripts.prepare_boundary_study import generate
from scripts.refund_priority import CLARIFICATION, PriorityClient, render
from skillforge.environment import Environment
from skillforge.model import ScriptedPolicy
from skillforge.schemas import Condition
from skillforge.skills import compile_skill
from test_refund_skill import refund_data


@pytest.fixture
def base(refund_data):
    skill = compile_skill(refund_data[0], "refund")
    skill.preconditions = [c for c in skill.preconditions if c.field != "payment.status"]
    skill.forbidden_conditions.insert(0, Condition(field="payment.status", value="FAILED", evidence=["test-only"]))
    skill.status = "VALIDATING"
    return skill


def test_priority_clarification_has_no_hidden_state_or_action_replacement():
    context = {"family": "refund", "policy": POLICY_TEXT, "observations": {}, "executable_skills": [], "parameters": {}}
    original = copy.deepcopy(context)
    assert render(context, "priority")["policy"] == POLICY_TEXT + CLARIFICATION
    assert context == original
    assert render(context, "control") == context
    context["family"] = "modify_address"
    assert render(context, "priority") == context
    with pytest.raises(ValueError):
        render(context, "unknown")


@pytest.mark.parametrize("scenario", ["partial_payment", "risk_failed"])
def test_task_outcome_and_sent_input_are_independently_audited(base, scenario):
    task = next(t for t in generate({"version": "priority-test", "seed": 901})
                if t.family == "refund" and t.split == "test" and t.structure_id.endswith(":" + scenario))
    class Model(ScriptedPolicy):
        model = "explicit-test-double"
        settings = {"server_identity": {"model": "explicit-test-double"}}
        fatal_error = None
    frozen = {"model_settings": Model.settings["server_identity"], "jobs": {}}
    boundaries = {"groups": {"B": {"refund": base.model_dump()}}}
    tasks, rows = {task.task_id: task}, {}
    for arm in ("control", "priority"):
        client, env = PriorityClient(Model(), arm), Environment(fixture=task.fixture)
        try:
            row = BoundaryRuntime(client, skills=[base]).run(task, env)
        finally:
            env.close()
        row["boundary_experiment"]["actual_model_inputs"] = client.inputs
        row["priority_view"] = {"arm": arm, "actual_user_messages": client.messages}
        job = {"kind": "system", "task": task.task_id, "arm": arm}
        validate_row(row, job, frozen, {}, tasks, boundaries)
        assert row["verification"]["task_success"]
        assert row["outcome"] == ("escalated" if scenario == "risk_failed" else "completed")
        broken = copy.deepcopy(row)
        broken["priority_view"]["actual_user_messages"][0] = json.dumps(client.inputs[0], ensure_ascii=False, sort_keys=True)
        with pytest.raises(ValueError, match="model input"):
            validate_row(broken, job, frozen, {}, tasks, boundaries)
        if scenario == "risk_failed":
            broken = copy.deepcopy(row)
            broken["outcome"] = "refused"
            with pytest.raises(ValueError, match="verdict"):
                validate_row(broken, job, frozen, {}, tasks, boundaries)
        rows[arm] = row
        frozen["jobs"][arm] = job
    # Fixed candidate setup only supplies authorized reads, no EOC label.
    context, audit = decision_context(task, base)
    assert len(audit) == 3 and "expected" not in context
    assert context["executable_skills"]
    expected_type = "escalate" if scenario == "risk_failed" else "skill"
    action = {"type": expected_type, "name": base.skill_id, "arguments": task.parameters}
    assert decision_score(action, task, base)["correct"]
    assert not decision_score({"type": "refuse", "name": "", "arguments": {}}, task, base)["correct"]


@pytest.mark.parametrize("metric", ["success", "normal_success", "correct", "actual_violations", "model_attempts"])
def test_validation_requires_both_evaluations_and_safety(metric):
    baseline = {"success": 20, "normal_success": 8, "correct": 19, "actual_violations": 0, "model_attempts": 0}
    report = {"totals": {"control": copy.deepcopy(baseline), "priority": copy.deepcopy(baseline)}}
    assert admission(report)["admitted"]
    report["totals"]["priority"][metric] += 1 if metric in {"actual_violations", "model_attempts"} else -1
    assert not admission(report)["admitted"]
