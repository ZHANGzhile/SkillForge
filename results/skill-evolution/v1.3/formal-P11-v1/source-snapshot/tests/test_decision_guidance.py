import copy
import json

import pytest

from scripts.decision_guidance import GuidedClient, augment, worksheet
from scripts import evaluate_decision_guidance as evaluation
from skillforge.dataset import generate_experiment
from skillforge.model import ScriptedPolicy


def test_visible_arithmetic_missing_boolean_and_no_oracle_dependency():
    context = {"family": "refund", "parameters": {"amount": 101}, "observations": {}, "history": []}
    assert "refund_arithmetic" not in worksheet(context, 0)
    context["observations"] = {"payment.captured_amount": 100, "payment.refunded_amount": 20}
    expected = worksheet(context, 0)
    assert expected["refund_arithmetic"] == {"remaining": 80, "requested_is_integer": True,
        "requested": 101, "positive": True, "exceeds_remaining": True}
    context["expected"] = {"allowed_outcomes": ["completed"]}
    context["hidden_state"] = {"payment.captured_amount": 1000}
    assert worksheet(context, 0) == expected
    context["parameters"]["amount"] = True
    assert worksheet(context, 0)["refund_arithmetic"] == {"remaining": 80, "requested_is_integer": False}


def test_guidance_preserves_context_and_respects_workflow_authority():
    context = {"family": "composite", "workflow": "address_else_escalate", "history": []}
    original = copy.deepcopy(context)
    guided = augment(context, 15)
    assert context == original
    assert guided["decision_guidance"]["remaining_decisions"] == 1
    assert "does not authorize cancellation" in guided["decision_guidance"]["workflow"]
    context["workflow"] = "address_else_cancel_else_escalate"
    assert "order_id only" in worksheet(context, 0)["workflow"]
    assert "HIGH customer risk" in worksheet(context, 0)["priority_order"][1]


def test_no_action_replacement_and_exact_model_input():
    class Base:
        model, tokens, fatal_error, settings = "explicit-double", 0, None, {}
        def decide(self, context):
            self.received = copy.deepcopy(context)
            return object_token
    object_token = object()
    base = Base()
    client = GuidedClient(base, True, "test-hash")
    context = {"family": "refund", "observations": {}, "history": []}
    assert client.decide(context) is object_token
    assert client.inputs[0] == base.received == augment(context, 0)
    evaluation.validate_inputs({"steps": [{"context": context, "model_input_context": client.inputs[0]}]}, True)
    corrupted = copy.deepcopy(client.inputs[0])
    corrupted["decision_guidance"]["remaining_decisions"] = 999
    with pytest.raises(ValueError, match="actual model input"):
        evaluation.validate_inputs({"steps": [{"context": context, "model_input_context": corrupted}]}, True)


def test_strict_validation_gate_does_not_ignore_attempts_or_decisions():
    report = {"full_system": {"tasks": 69, "task_success_rate": 1,
        "model_attempted_policy_violation_rate": 0, "actual_policy_violation_rate": 0},
        "decision_level": {"correct": 41}}
    gate = {"minimum_successes": 69, "maximum_model_attempts": 0, "maximum_actual_violations": 0, "minimum_correct_decisions": 41}
    assert evaluation.admitted(report, gate)
    report["full_system"]["model_attempted_policy_violation_rate"] = 1 / 69
    assert not evaluation.admitted(report, gate)
    report["full_system"]["model_attempted_policy_violation_rate"] = 0
    report["decision_level"]["correct"] = 40
    assert not evaluation.admitted(report, gate)


def test_stage_resume_reaudits_without_calling_service(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs").mkdir()
    class TestPolicy(ScriptedPolicy):
        model, fatal_error = "explicit-test-double", None
        settings = {"server_identity": {"model": "test"}}
    monkeypatch.setattr(evaluation, "create_client", lambda *_: TestPolicy())
    task = next(t for t in generate_experiment(instances=1) if t.split == "validation" and t.family == "refund")
    root = tmp_path / "evidence"
    root.mkdir()
    identity = {"model_settings": {"model": "test"}, "guidance_hash": "test-only"}
    report = evaluation.run_stage(root, "validation", [task], [], identity, "unused", True, root)
    assert report["full_system"]["task_success_rate"] == 1
    from scripts.report_decision_guidance import audit_stage
    assert audit_stage(root / "validation", [task], [], identity, True)[0] == report
    def forbidden(*_):
        raise AssertionError("completed resume must not call a model")
    monkeypatch.setattr(evaluation, "create_client", forbidden)
    assert evaluation.run_stage(root, "validation", [task], [], identity, "unused", True, root) == report
    path = root / "validation/evaluation.json"
    changed = json.loads(path.read_text(encoding="utf-8"))
    changed["full_system"]["task_success_rate"] = 0
    path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="summary differs"):
        evaluation.run_stage(root, "validation", [task], [], identity, "unused", True, root)
    with pytest.raises(ValueError, match="summary does not match"):
        audit_stage(root / "validation", [task], [], identity, True)
