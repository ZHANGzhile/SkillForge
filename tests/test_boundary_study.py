import copy

import pytest

from scripts.boundary_learning import boundary_signature, fit_groups, oracle, procedure_hash, public_contract
from scripts.boundary_runtime import BoundaryRuntime
from scripts.evaluate_boundary_gate import clustered_interval, measure
from scripts.prepare_boundary_study import generate, probe
from skillforge.environment import Environment
from skillforge.model import ScriptedPolicy
from skillforge.runtime import Runtime
from skillforge.schemas import Condition
from skillforge.skills import gate
from test_skills import address_skill


@pytest.fixture
def study():
    plan = {"version": "test-boundary-only", "seed": 999}
    tasks = [t for t in generate(plan) if t.family == "modify_address"]
    base = address_skill()
    base.preconditions += [Condition(field="order.status", value="CONFIRMED", evidence=["test-policy"]),
                           Condition(field="address.valid", value=True, evidence=["test-policy"])]
    base.forbidden_conditions = [Condition(field="customer.risk_level", value="HIGH", evidence=["test-policy"])]
    training = [probe(t, base) for t in tasks if t.split == "train"]
    groups, traces = fit_groups(base, training)
    return tasks, base, training, groups, traces


def test_failure_changes_boundary_not_procedure_and_preserves_positives(study):
    tasks, base, training, groups, traces = study
    assert {procedure_hash(s) for s in groups.values()} == {procedure_hash(base)}
    assert boundary_signature(groups["A"]) != boundary_signature(groups["B"])
    high = next(t for t in tasks if t.split == "test" and t.structure_id.endswith(":high_risk"))
    assert measure(high, groups["A"], "full", 1)["initial_prediction"]["status"] == "APPLICABLE"
    assert measure(high, groups["B"], "full", 1)["initial_prediction"]["status"] == "INAPPLICABLE"
    for p in training:
        if p["label"] == "positive":
            assert all(gate(s, {**p["state"], **p["features"]}, p["parameters"]).status == "APPLICABLE" for s in groups.values())
    assert traces["B"]["steps"]
    assert not traces["D"]["steps"]


def test_no_test_fit_or_provenance_leakage(study):
    _, base, training, groups, _ = study
    changed = copy.deepcopy(training)
    changed[0]["split"] = "test"
    with pytest.raises(ValueError, match="train"):
        fit_groups(base, changed)
    contract = public_contract(groups["B"])
    assert "source_trajectory_ids" not in contract and "statistics" not in contract
    assert all("evidence" not in c for k in ("preconditions", "forbidden_conditions") for c in contract[k])
    assert contract["status"] == "VALIDATING"


def test_unknown_sufficient_rejection_and_hydration_cost(study):
    tasks, _, _, groups, _ = study
    task = next(t for t in tasks if t.split == "test" and t.structure_id.endswith(":normal_low"))
    row = measure(task, groups["B"], "empty", 1)
    assert row["initial_prediction"]["status"] == row["partial_truth"] == "UNKNOWN"
    assert row["final_prediction"]["status"] == "APPLICABLE" and row["queries"] > 0
    assert oracle("modify_address", {"customer.risk_level": "HIGH"}, task.parameters) == "INAPPLICABLE"
    assert oracle("refund", {}, {"amount": 0}) == "INAPPLICABLE"
    assert clustered_interval([])["ci95"] is None


class ExplicitTestModel(ScriptedPolicy):
    model = "explicit-test-double"


def test_forced_gate_vs_bypass_keeps_tool_safety_and_origin(study):
    tasks, _, _, groups, _ = study
    task = next(t for t in tasks if t.split == "test" and t.structure_id.endswith(":high_risk"))
    rows = []
    for mode in ("gate", "bypass"):
        env = Environment(fixture=task.fixture)
        try:
            rows.append(BoundaryRuntime(ExplicitTestModel(), skills=[groups["B"]], intervention=mode).run(task, env))
        finally:
            env.close()
    assert rows[0]["boundary_experiment"]["fork"] == rows[1]["boundary_experiment"]["fork"]
    assert rows[0]["boundary_experiment"]["forced_tool_policy_attempts"] == 0
    assert rows[1]["boundary_experiment"]["forced_tool_policy_attempts"] == 1
    for row in rows:
        assert not row["verification"]["actual_policy_violation"]
        assert row["metrics"]["llm_calls"] == len(row["boundary_experiment"]["actual_model_inputs"])
        assert row["metrics"]["decision_calls"] == row["metrics"]["llm_calls"] + 1
        assert not row["policy_attempts"]["model_triggered"]
        assert row["verification"]["task_success"]


def test_autonomous_runtime_preserves_core_action_semantics(study):
    tasks, base, _, groups, _ = study
    task = next(t for t in tasks if t.split == "test" and t.structure_id.endswith(":normal_low"))
    results = []
    for cls, skill in ((Runtime, base), (BoundaryRuntime, groups["C"])):
        env = Environment(fixture=task.fixture)
        try:
            results.append(cls(ExplicitTestModel(), skills=[skill]).run(task, env))
        finally:
            env.close()
    assert [s["action"] for s in results[0]["steps"]] == [s["action"] for s in results[1]["steps"]]
    assert results[0]["verification"]["task_success"] == results[1]["verification"]["task_success"] == True
    assert results[0]["metrics"]["tool_calls"] == results[1]["metrics"]["tool_calls"]


def test_system_resume_audit_and_tamper_fail_closed(study, tmp_path, monkeypatch):
    import json
    from scripts import evaluate_boundary_system as evaluator
    tasks, _, _, groups, _ = study
    task = next(t for t in tasks if t.split == "test" and t.structure_id.endswith(":normal_low"))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs").mkdir()
    root = tmp_path / "system"
    boundaries = {"groups": {g: {task.family: s.model_dump()} for g, s in groups.items()}}
    keys = {task.task_id + "-" + g + "-" + m: (task, g, m) for g in "ABCD" for m in evaluator.MODES}
    identity = {"model_settings": {"model": "explicit-test-double"}, "aliases": {}}
    plan = {"seed": 999, "client_profile": "unused", "max_steps": 16, "retry_budget": 1}
    monkeypatch.setattr(evaluator, "prepared", lambda _: (plan, root, [task], boundaries, identity, keys))
    def client(*_):
        model = ExplicitTestModel()
        model.settings = {"server_identity": identity["model_settings"]}
        model.fatal_error = None
        return model
    monkeypatch.setattr(evaluator, "create_client", client)
    rows, completed = evaluator.run()
    assert completed["actual_runs"] == 12
    def no_model(*_):
        raise AssertionError("audit/resume must not call model")
    monkeypatch.setattr(evaluator, "create_client", no_model)
    assert evaluator.run(resume=True)[1] == evaluator.run(audit_only=True)[1] == completed
    path = root / "completed.json"
    data = json.loads(path.read_text())
    data["actual_runs"] = 999
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="summary"):
        evaluator.run(audit_only=True)


def test_probe_replay_uuid_normalization_preserves_identity_links():
    import uuid
    from scripts.audit_boundary_preparation import semantic
    a, b, c = (str(uuid.uuid4()) for _ in range(3))
    first = {"result": {"transaction_id": a}, "ledger": [{"transaction_id": a}], "amount": 100}
    replay = {"result": {"transaction_id": b}, "ledger": [{"transaction_id": b}], "amount": 100}
    assert semantic(first) == semantic(replay)
    replay["ledger"][0]["transaction_id"] = c
    assert semantic(first) != semantic(replay)
    with pytest.raises(ValueError):
        semantic({"transaction_id": "missing"})
