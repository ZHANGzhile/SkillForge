import copy
import json

import pytest

from scripts import evaluate_refund_priority as original_evaluator
from scripts.evaluate_refund_priority_scoped import configured
from scripts.refund_priority import CLARIFICATION, render as original_render
from scripts.refund_priority_scoped import ScopedPriorityClient, activation_proof, render
from skillforge.schemas import Action


def test_scoped_activation_is_exhaustive_within_declared_domains():
    assert activation_proof() == {"checked": 175, "activated": 5, "byte_identical": 170}


@pytest.mark.parametrize("risk", [None, "LOW", "MEDIUM", "HIGH", "UNKNOWN"])
def test_actual_messages_keep_low_failed_and_missing_risk_unchanged(risk):
    class Model:
        model, settings, tokens, fatal_error = "test-only", {}, 0, None
        def decide(self, context):
            self.seen = copy.deepcopy(context)
            return Action(type="refuse")
    context = {"family": "refund", "policy": "policy", "parameters": {"amount": 100},
        "observations": {"payment.status": "FAILED"}, "executable_skills": [], "history": [{"error": "example"}]}
    if risk is not None:
        context["observations"]["customer.risk_level"] = risk
    original = copy.deepcopy(context)
    model, client = Model(), None
    client = ScopedPriorityClient(model, "priority")
    action = client.decide(context)
    assert action.type == "refuse"  # Wrong model actions are never silently repaired.
    assert context == original
    assert client.messages == [json.dumps(model.seen, ensure_ascii=False)]
    if risk == "HIGH":
        assert model.seen == original_render(context, "priority")
        assert model.seen["policy"] == "policy" + CLARIFICATION
    else:
        assert client.messages[0] == json.dumps(original_render(context, "control"), ensure_ascii=False)
    context["family"] = "modify_address"
    assert render(context, "priority") == original_render(context, "control")


def test_v2_evaluator_bindings_restore_even_on_failure():
    keys = ("PLAN", "render", "PriorityClient", "prepare", "progress")
    before = {key: getattr(original_evaluator, key) for key in keys}
    with pytest.raises(RuntimeError):
        with configured():
            assert original_evaluator.PLAN.endswith("refund-priority-scoped.json")
            assert original_evaluator.render is render
            raise RuntimeError("simulate interruption")
    assert {key: getattr(original_evaluator, key) for key in keys} == before
