"""Admission must gate inference, not merely label an overrun afterwards."""
import copy

import pytest

from scripts.evolution_budget import CheckpointAdmission
from skillforge.environment import Environment
from skillforge.schemas import Action
from skillforge.skill_evolution.catalog import Catalog
from skillforge.skill_evolution.runtime import run_agent
from test_skill_evolution_runtime import Model, TASK, call


def checkpoint(requests, used=None):
    total = sum(r.get("charged_tokens", r["reserved_tokens"]) for r in requests)
    return {"identity": "frozen-runtime", "model_requests": copy.deepcopy(requests),
            "budget": {"used": {"tokens": total if used is None else used}}}


PENDING = {"status": "pending", "reserved_tokens": 16384, "context_hash": "context"}


def test_request_can_start_when_whole_arm_ceiling_does_not_fit():
    budget = CheckpointAdmission(457995, 500000, 1677.4, 1800)
    assert 457995 + 45056 > 500000
    first = budget.inspect(checkpoint([PENDING]), 20)
    assert first["approved"] and budget.charged_tokens() == 0
    budget.record_approval(first)
    assert budget.charged_tokens() == 16384  # Approval -> crash is unknown.
    settled = {**PENDING, "status": "completed", "charged_tokens": 5100}
    second = budget.inspect(checkpoint([settled, PENDING]), 35)
    assert second["approved"] and second["project_tokens_with_reservation"] == 479479
    budget.record_approval(second)
    budget.inspect(checkpoint([settled, {**settled, "charged_tokens": 5166}]), 45)
    assert budget.charged_tokens() == 10266


def test_denied_request_is_not_an_unknown_acknowledged_request():
    budget = CheckpointAdmission(490000, 500000, 0, 1800)
    denied = budget.inspect(checkpoint([PENDING]), 1)
    assert not denied["approved"] and denied["reason"] == "token_budget"
    assert budget.charged_tokens() == 0
    with pytest.raises(ValueError, match="approval"):
        budget.record_approval(denied)


def test_wall_grace_and_foreign_settlement_are_rejected():
    budget = CheckpointAdmission(0, 500000, 1785, 1800)
    denied = budget.inspect(checkpoint([PENDING]), 6)
    assert not denied["approved"] and denied["reason"] == "wall_budget"
    with pytest.raises(ValueError, match="unapproved"):
        budget.inspect(checkpoint([{**PENDING, "status": "completed", "charged_tokens": 5000}]), 6)
    with pytest.raises(ValueError, match="disagree"):
        budget.inspect(checkpoint([PENDING], used=1), 0)


class BeforeInferenceDenied(Exception):
    pass


def test_frozen_runtime_barrier_prevents_inference_and_effects():
    env = Environment()
    model = Model([Action(type="tool", name="cancel_order", arguments=TASK["parameters"])])
    budget = CheckpointAdmission(490000, 500000, 0, 1800)
    def persist(value):
        receipt = budget.inspect(value, 0)
        if receipt is not None:
            assert not receipt["approved"]
            raise BeforeInferenceDenied()
    try:
        with pytest.raises(BeforeInferenceDenied):
            run_agent(model, TASK, Catalog([]), call(env), persist=persist)
        assert model.contexts == [] and env.audit == []
        assert env.snapshot()["order.status"] == "CONFIRMED"
        assert budget.charged_tokens() == 0
    finally:
        env.close()
