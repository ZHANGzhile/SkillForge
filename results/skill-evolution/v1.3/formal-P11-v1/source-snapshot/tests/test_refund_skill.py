import copy
import json

import pytest

from skillforge.dataset import load_dataset, write_dataset
from skillforge.environment import Environment
from skillforge.experiment import collect, read_sources
from skillforge.learning import validate_skill
from skillforge.model import ScriptedPolicy
from skillforge.refinement import validate_and_refine
from skillforge.runtime import Runtime
from skillforge.skills import compile_skill, gate
from skillforge.decision_eval import evaluate_decisions


@pytest.fixture(scope="module")
def refund_data(tmp_path_factory):
    root = tmp_path_factory.mktemp("refund")
    write_dataset(root / "dataset", instances=3)
    _, tasks = load_dataset(root / "dataset")
    report = collect(root / "dataset", ScriptedPolicy, root / "sources", engineering=True, failure_fixtures=True)
    records = read_sources(report["source_path"])
    return records, tasks


def test_refund_compilation_admission_and_full_system(refund_data):
    records, tasks = refund_data
    skill = compile_skill(records, "refund")
    report = validate_skill(skill, [t for t in tasks if t.split == "validation"])
    assert skill.status == "VERIFIED", report
    assert gate(skill, {}).status == "UNKNOWN"
    state = {"payment.status": "CAPTURED", "payment.captured_amount": 100, "payment.refunded_amount": 20, "customer.risk_level": "LOW"}
    for amount in [0, -1, 81, True, 1.2]:
        assert gate(skill, state, {"amount": amount}).status == "INAPPLICABLE"
    assert gate(skill, state, {"amount": 80}).status == "APPLICABLE"
    assert gate(skill, state, {}).status == "UNKNOWN"
    for task in [t for t in tasks if t.split == "test" and t.family == "refund"]:
        env = Environment(fixture=task.fixture, faults=task.fixture.get("faults"))
        result = Runtime(ScriptedPolicy(), skills=[skill]).run(task, env)
        assert result["verification"]["task_success"], result["verification"]
        env.close()


def test_refund_decision_probe_needs_no_shipment_observation(refund_data):
    records, tasks = refund_data
    skill = compile_skill(records, "refund")
    report = evaluate_decisions(ScriptedPolicy(), skill, [t for t in tasks if t.split == "test"])
    assert report["evaluated"] == 15 and report["skipped"] == 3
    assert report["accuracy"] == 1, report


def test_two_repairs_preserve_versions_and_evidence(refund_data, tmp_path):
    records, tasks = refund_data
    candidate = compile_skill(records, "refund")
    candidate.forbidden_conditions = []
    candidate.postconditions = {"payment.refunded_amount": -999}
    original = candidate.model_dump()
    skill, report = validate_and_refine(candidate, records, [t for t in tasks if t.split == "validation"], output_dir=tmp_path)
    assert skill.status == "VERIFIED", report
    assert report["refinements"] == 2 and report["validation_runs"] == 3
    assert [r["version"] for r in report["history"]] == [1, 2, 3]
    assert candidate.model_dump() == original
    assert len(list(tmp_path.glob("attempt-*.json"))) == 3
    assert report["history"][0]["feedback_task_ids"]
    assert not any(t.task_id in json.dumps(report) for t in tasks if t.split == "test")


def test_repair_budget_and_split_are_enforced(refund_data):
    records, tasks = refund_data
    candidate = compile_skill(records, "refund")
    candidate.forbidden_conditions = []
    candidate.postconditions = {"payment.refunded_amount": -999}
    validation = [t for t in tasks if t.split == "validation"]
    skill, report = validate_and_refine(candidate, records, validation, max_refinements=1)
    assert skill.status == "REJECTED" and report["validation_runs"] == 2
    with pytest.raises(ValueError, match="0 to 2"):
        validate_and_refine(candidate, records, validation, max_refinements=3)
    with pytest.raises(ValueError, match="validation feedback"):
        validate_and_refine(candidate, records, [t for t in tasks if t.split == "test"])
    with pytest.raises(ValueError, match="train only"):
        validate_and_refine(candidate, [{**records[0], "split": "test"}], validation)


def test_partial_prior_refund_uses_before_value(refund_data):
    records, tasks = refund_data
    skill = compile_skill(records, "refund")
    skill.status = "VERIFIED"
    task = next(t.model_copy(deep=True) for t in tasks if t.family == "refund" and t.split == "test" and t.expected.allowed_outcomes == ["completed"])
    task.fixture.update({"payment": "PARTIALLY_REFUNDED", "refunded": 700})
    task.expected.expected_state["payment.refunded_amount"] = 700 + task.parameters["amount"]
    env = Environment(fixture=task.fixture)
    result = Runtime(ScriptedPolicy(), skills=[skill]).run(task, env)
    assert result["verification"]["task_success"]
    assert result["skill_events"][0]["verification"]["expected"]["payment.refunded_amount"] == 700 + task.parameters["amount"]
    env.close()


def test_refund_skill_exhausted_retry_escalates_without_write(refund_data):
    records, tasks = refund_data
    skill = compile_skill(records, "refund")
    skill.status = "VERIFIED"
    task = next(t.model_copy(deep=True) for t in tasks if t.family == "refund" and t.split == "test" and t.expected.allowed_outcomes == ["completed"])
    task.expected.allowed_outcomes = ["escalated"]
    task.expected.expected_state = {}
    task.expected.unchanged_fields.append("payment.refunded_amount")
    env = Environment(fixture=task.fixture, faults={"issue_refund": ["timeout", "timeout"]})
    result = Runtime(ScriptedPolicy(), skills=[skill]).run(task, env)
    assert result["verification"]["task_success"]
    assert len(result["final_state"]["refunds"]) == 0
    assert sum(e["tool_name"] == "issue_refund" for e in result["tool_audit"]) == 2
    env.close()


def test_no_supported_repair_stops_and_zero_budget_preserves_candidate(refund_data):
    records, tasks = refund_data
    candidate = compile_skill(records, "refund")
    validation = [t.model_copy(deep=True) for t in tasks if t.split == "validation" and t.family == "refund"]
    # Unsupported persistent infrastructure failure cannot be repaired by changing a contract.
    for task in validation:
        if task.expected.allowed_outcomes == ["completed"]:
            task.fixture["faults"] = {"get_payment": ["timeout", "timeout"]}
    skill, report = validate_and_refine(candidate, records, validation)
    assert skill.status == "REJECTED" and report["stop_reason"] == "no_supported_repair"
    assert report["validation_runs"] == 1
    candidate.forbidden_conditions = []
    skill, report = validate_and_refine(candidate, records, [t for t in tasks if t.split == "validation"], max_refinements=0)
    assert skill.status == "REJECTED" and report["refinements"] == 0
