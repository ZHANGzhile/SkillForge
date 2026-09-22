import copy

import pytest

from skillforge.benchmark import run_benchmark
from skillforge.dataset import generate_experiment
from skillforge.model import ScriptedPolicy
from skillforge.provenance import audit_sources
from skillforge.schemas import Action
from skillforge.skills import compile_skill


class UnsafePolicy(ScriptedPolicy):
    def decide(self, context):
        if not context["history"]:
            name = "cancel_order" if context["family"] == "cancel_order" else "update_shipping_address"
            return Action(type="tool", name=name, arguments=context["parameters"])
        return Action(type="stop")


@pytest.fixture
def sources(tmp_path):
    tasks = generate_experiment(instances=3)
    train = [t for t in tasks if t.split == "train" and t.family in {"modify_address", "cancel_order"}]
    _, good = run_benchmark(ScriptedPolicy(), train, output_root=tmp_path)
    _, bad = run_benchmark(UnsafePolicy(), [t for t in train if t.fixture.get("shipment") == "SHIPPED"], output_root=tmp_path)
    return tasks, good + bad


def test_cancel_compiler_uses_specific_business_counterexamples(sources):
    tasks, records = sources
    assert audit_sources(records, tasks, allow_engineering=True)["trajectories"] == len(records)
    skill = compile_skill(records, "cancel_order")
    assert skill.postconditions == {"order.status": "CANCELLED"}
    assert any(e.startswith("failure:") for c in skill.forbidden_conditions for e in c.evidence)
    risk = next(c for c in skill.forbidden_conditions if c.field == "customer.risk_level")
    assert not any(e.startswith("failure:") for e in risk.evidence), "shipping failure is not evidence for risk boundary"


def test_timeouts_alone_cannot_teach_boundary(sources):
    _, records = sources
    records = copy.deepcopy(records)
    for r in records:
        if not r["verification"]["task_success"]:
            for e in r["tool_audit"]:
                if e["error"]:
                    e["error"] = "timeout"
    with pytest.raises(ValueError, match="failed trajectories"):
        compile_skill(records, "cancel_order")


def test_source_audit_rejects_relabelled_test_trajectory(sources):
    tasks, records = sources
    forged = copy.deepcopy(records[0])
    forged["task_id"] = next(t.task_id for t in tasks if t.split == "test")
    forged["split"] = "train"
    with pytest.raises(ValueError, match="manifest train"):
        audit_sources([forged], tasks, allow_engineering=True)


def test_source_audit_recomputes_verdict_and_fingerprint(sources):
    tasks, records = sources
    forged = copy.deepcopy(records[0])
    forged["task_hash"] = "forged"
    with pytest.raises(ValueError, match="fingerprint"):
        audit_sources([forged], tasks, allow_engineering=True)
    forged = copy.deepcopy(records[0])
    forged["verification"]["task_success"] = not forged["verification"]["task_success"]
    with pytest.raises(ValueError, match="verification mismatch"):
        audit_sources([forged], tasks, allow_engineering=True)
