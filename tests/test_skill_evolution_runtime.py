import copy
import random

import pytest

from skillforge.environment import Environment, ToolError
from skillforge.evolution_common.artifacts import SplitLedger, Budget
from skillforge.evolution_common.snapshot import save_snapshot, restore_snapshot
from skillforge.schemas import Action
from skillforge.skill_evolution.catalog import Catalog
from skillforge.skill_evolution.runtime import run_agent
from test_skill_evolution_catalog import entry


TASK = {"task_id": "p1-test", "family": "cancel_order", "request": "Cancel order O1", "parameters": {"order_id": "O1"}}


class Model:
    settings = {"model": "scripted-engineering-only", "engineering_only": True}
    tokens = 0
    def __init__(self, actions): self.actions = iter(actions); self.contexts = []
    def decide(self, context):
        self.contexts.append(copy.deepcopy(context))
        assert not {"expected", "fixture", "gold", "validation"} & set(context)
        return next(self.actions)


def call(env):
    def dispatch(name, args, key, source):
        result = env.call(name, args, "C1", key)
        env.audit[-1]["decision_origin"] = source
        return result
    return dispatch


def actions(e):
    return [Action(type="tool", name="search_skills", arguments={"query": "cancel order"}),
            Action(type="tool", name="load_skill", arguments={"skill_id": e["skill_id"], "revision": e["revision"]}),
            Action(type="skill", name=e["skill_id"], arguments=TASK["parameters"]), Action(type="stop")]


def test_search_load_use_is_real_dispatch_and_autonomous_stop():
    e = entry(); env = Environment(); model = Model(actions(e))
    result = run_agent(model, TASK, Catalog([e]), call(env))
    assert result["outcome"] == "completed" and result["termination_source"] == "model"
    assert result["skill_events"][0]["success"]
    assert result["verification_receipts"][0]["source"] == "skill"
    assert result["interventions"]["runtime_intervention_count"] == 0
    assert result["metrics"]["llm_calls"] == result["metrics"]["tokens"] == 0
    assert result["metrics"]["decision_calls"] == 4
    assert model.contexts[0]["catalog"]["loaded_skills"] == []
    assert "program" not in str(model.contexts[0])
    assert "FAILED" in str(model.contexts[0]["policy_view"])
    assert all(e["tool_name"] not in {"search_skills", "load_skill"} for e in env.audit)
    env.close()


def test_unknown_load_does_not_establish_permission_and_high_risk_is_blocked():
    e = entry(); env = Environment(fixture={"risk": "HIGH"}); model = Model(actions(e))
    result = run_agent(model, TASK, Catalog([e]), call(env))
    assert model.contexts[2]["catalog"]["loaded_skills"][0]["gate"]["status"] == "UNKNOWN"
    assert result["skill_events"][0]["gate_status"] == "INAPPLICABLE"
    assert not result["skill_events"][0]["success"]
    assert env.snapshot()["order.status"] == "CONFIRMED"
    env.close()


def test_unloaded_call_and_search_budget_failures_are_explicit():
    e = entry(); env = Environment()
    model = Model([Action(type="skill", name=e["skill_id"], arguments=TASK["parameters"]),
                   Action(type="tool", name="search_skills", arguments={"query": "cancel"})])
    result = run_agent(model, TASK, Catalog([e]), call(env), max_search=0)
    assert result["steps"][0]["error"] == "skill_not_loaded"
    assert result["outcome"] == "budget_exhausted"
    assert env.audit == []
    env.close()


def test_primitive_success_keeps_explicit_runtime_assistance():
    env = Environment(); model = Model([Action(type="tool", name="cancel_order", arguments=TASK["parameters"])])
    result = run_agent(model, TASK, Catalog([]), call(env))
    assert result["outcome"] == "completed" and result["termination_source"] == "runtime"
    assert result["interventions"]["forced_readback_count"] == 1
    assert result["interventions"]["auto_termination_count"] == 1
    assert not result["skill_events"]
    env.close()


def test_response_loss_snapshot_preserves_unknown_commit_fault_and_independent_fork(tmp_path):
    env = Environment(faults={"cancel_order": ["response_lost"]})
    saved = []
    model = Model([Action(type="tool", name="cancel_order", arguments=TASK["parameters"])])
    result = run_agent(model, TASK, Catalog([]), call(env), persist=lambda s: saved.append(copy.deepcopy(s)))
    assert result["outcome"] == "commit_unknown"
    assert saved[-1]["steps"][0]["action"]["name"] == "cancel_order"
    rng = random.Random(42); save_snapshot(tmp_path / "saved", env, saved[-1], rng)
    fork, restored, fork_rng = restore_snapshot(tmp_path / "saved", tmp_path / "fork.sqlite", saved[-1]["identity"])
    assert fork.faults["cancel_order"] == [] and fork.audit == env.audit
    assert fork_rng.random() == rng.random()
    assert fork.db.execute("SELECT count(*) FROM idempotency").fetchone()[0] == 1
    assert fork.snapshot()["order.status"] == "CANCELLED"
    # No request reconciliation capability means no second mutation is replayed.
    retry = run_agent(Model([]), TASK, Catalog([]), call(fork), checkpoint=restored)
    assert retry["outcome"] == "commit_unknown"
    assert len([e for e in fork.audit if e["tool_name"] == "cancel_order"]) == 1
    fork.db.execute("UPDATE orders SET status='CONFIRMED'")
    assert env.snapshot()["order.status"] == "CANCELLED"
    with pytest.raises(ValueError): restore_snapshot(tmp_path / "saved", tmp_path / "bad.sqlite", "wrong")
    fork.close(); env.close()


def test_cross_round_fork_provenance_never_changes_split(tmp_path):
    ledger = SplitLedger(tmp_path / "ledger")
    ledger.claim("source-a", "test", related_groups=["entity-a", "structure-a"])
    with pytest.raises(ValueError, match="cross splits"):
        SplitLedger(tmp_path / "ledger").claim("fork-of-a", "train", related_groups=["source-a"])
    with pytest.raises(ValueError): Budget({"tokens": 10}, {"tokens": 11})


def test_public_task_extra_private_fields_and_changed_resume_identity_rejected():
    with pytest.raises(ValueError, match="public"):
        run_agent(Model([]), {**TASK, "expected": "secret"}, Catalog([]), lambda *_: {})
    with pytest.raises(ValueError, match="identity"):
        run_agent(Model([]), TASK, Catalog([]), lambda *_: {}, checkpoint={"identity": "wrong", "status": "interrupted"})


def test_unknown_model_failure_retains_full_token_reservation():
    class Failed:
        settings = {"model": "transport-failure-fixture", "engineering_only": False}
        tokens = 0
        def decide(self, context): raise TimeoutError("response unavailable")
    result = run_agent(Failed(), TASK, Catalog([]), lambda *_: {})
    assert result["outcome"] == "error"
    assert result["metrics"]["tokens"] == 16384
    assert result["model_requests"][0]["usage_known"] is False
    assert result["budget"]["used"]["decisions"] == 1
