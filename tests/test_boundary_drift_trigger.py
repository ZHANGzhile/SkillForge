"""CPU contracts only; synthetic public streams are not autonomous Agent evidence."""
import copy

import pytest

from skillforge.evolution_schemas import EvidenceView, fingerprint
from skillforge.boundary_evolution.trigger import Interaction, DriftController


def item(index=0, *, source=None, obj=None, parent="parent", feedback="business",
         label="not_executable", baseline=True, guard=True, origin="daily", epoch="ignored"):
    payload = dict(trajectory_id=f"t{index}", member_hash=f"m{index}", split="seed",
        policy_epoch=epoch, family="refund", observations={"customer.risk_level": "LOW", "shipment.status": "PROCESSING"},
        baseline_prediction=baseline, guard_prediction=guard, label=label, origin="model_tool", tool_calls=5)
    return Interaction(receipt_id=f"r{index}", source_group=source or f"s{index}",
        object_id=obj or f"O{index}", parent_revision=parent,
        evidence=EvidenceView(evidence_id=fingerprint(payload), **payload), feedback=feedback,
        probe_origin=origin, sandbox_id="isolated-test" if origin == "authorized_sandbox" else None,
        query_receipt_hash=f"query{index}")


def test_three_independent_objects_trigger_without_world_epoch():
    ctl = DriftController()
    assert [ctl.observe(item(i, epoch=f"unrelated{i}"))["state"] for i in range(3)] == [
        "INCONCLUSIVE", "INCONCLUSIVE", "SUSPECTED_DRIFT"]
    assert ctl.events[-1]["decision"]["belief_update_allowed"] is False
    assert DriftController.restore(ctl.checkpoint()).checkpoint() == ctl.checkpoint()
    assert ctl.observe(item(4, parent="new-parent"))["independent_sources"] == 1


@pytest.mark.parametrize("same", ["source", "object"])
def test_retry_aliases_are_not_independent(same):
    ctl = DriftController()
    for i in range(4):
        decision = ctl.observe(item(i, source="one" if same == "source" else None,
                                    obj="one" if same == "object" else None))
    assert decision["state"] == "INCONCLUSIVE"
    assert decision["independent_sources"] == 1


def test_window_expiry_and_no_epoch_trigger():
    ctl = DriftController({"window_events": 3})
    ctl.observe(item(0))
    for i in range(1, 4):
        assert ctl.observe(item(i, label="executable", epoch=f"epoch{i}"))["state"] == "NO_CHANGE"
    assert ctl.observe(item(4))["independent_sources"] == 1


@pytest.mark.parametrize("feedback,state", [("infrastructure", "INFRASTRUCTURE"),
    ("permission", "NO_CHANGE"), ("arguments", "MODEL_OR_PROGRAM_ERROR"),
    ("program", "MODEL_OR_PROGRAM_ERROR"), ("verification", "MODEL_OR_PROGRAM_ERROR"),
    ("termination", "MODEL_OR_PROGRAM_ERROR"), ("unknown", "INCONCLUSIVE")])
def test_excluded_errors_never_create_false_block(feedback, state):
    ctl = DriftController()
    for i in range(3):
        decision = ctl.observe(item(i, feedback=feedback, label="unknown", baseline=False))
    assert decision["state"] == state
    assert decision["conflict_type"] is None and decision["gap_ids"] == []
    assert decision["belief_update_allowed"] is False


def test_immutable_guard_can_pause_but_never_relax():
    ctl = DriftController()
    decision = ctl.observe(item(0, feedback="immutable_guard", label="executable", baseline=False, guard=False))
    assert decision["pause_related_skill"] and not decision["boundary_update_allowed"]
    with pytest.raises(ValueError, match="supported suspicion"):
        ctl.begin_exploration(decision["trigger_key"], sandbox_id="sandbox")


def test_repeated_unexplained_unknown_can_suspect_but_never_supply_labels():
    ctl = DriftController()
    for i in range(3):
        decision = ctl.observe(item(i, feedback="unknown", label="unknown", baseline=True))
    assert decision["state"] == "SUSPECTED_DRIFT"
    assert decision["conflict_type"] == "unknown_applicability"
    assert not decision["belief_update_allowed"]


def test_exploration_receipts_budget_and_recovery_are_separate_from_trigger():
    ctl = DriftController({"probe_budget": 2})
    for i in range(3): decision = ctl.observe(item(i))
    key = decision["trigger_key"]
    ctl.begin_exploration(key, sandbox_id="isolated-test")
    with pytest.raises(ValueError, match="exact sandbox"):
        ctl.charge_probe(key, item(10))
    assert ctl.charge_probe(key, item(10, origin="authorized_sandbox")).label == "not_executable"
    assert ctl.charge_probe(key, item(11, origin="authorized_sandbox", feedback="unknown", label="unknown")) is None
    restored = DriftController.restore(ctl.checkpoint())
    assert restored.checkpoint() == ctl.checkpoint()
    with pytest.raises(ValueError, match="already consumed"):
        restored.charge_probe(key, item(10, origin="authorized_sandbox"))
    with pytest.raises(ValueError, match="budget exhausted"):
        restored.charge_probe(key, item(12, origin="authorized_sandbox"))
    assert restored.observe(item(4))["state"] == "EXPLORING"
    assert DriftController.restore(restored.checkpoint()).checkpoint() == restored.checkpoint()


def test_conflicting_replay_and_rehashed_accounting_tamper_rejected():
    ctl = DriftController()
    original = item(0)
    ctl.observe(original)
    assert ctl.observe(original) == ctl.events[0]["decision"]
    with pytest.raises(ValueError, match="conflicting receipt"):
        ctl.observe(original.model_copy(update={"source_group": "forged"}))
    changed = copy.deepcopy(ctl.checkpoint())
    changed["events"][0]["decision"]["state"] = "SUSPECTED_DRIFT"
    changed["hash"] = fingerprint({k: v for k, v in changed.items() if k != "hash"})
    with pytest.raises(ValueError, match="replay mismatch"):
        DriftController.restore(changed)
