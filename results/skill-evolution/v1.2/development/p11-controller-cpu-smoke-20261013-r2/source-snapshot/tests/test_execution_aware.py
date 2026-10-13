import copy
from dataclasses import FrozenInstanceError
import json
import subprocess
import sys

import pytest

from skillforge.environment import Environment, ToolError
from skillforge.evolution_schemas import Hypothesis
from skillforge.execution_aware.contracts import ExecutionContract
from skillforge.execution_aware.runtime import run_agent
from skillforge.execution_aware.metrics import paired_execution_metrics
from skillforge.schemas import Action
from test_evolution_execution import parent


PARAMS = {"order_id": "O1", "amount": 1000}
TASK = {"task_id": "execution-dev", "family": "refund", "request": "Refund 1000", "parameters": PARAMS}
H0 = Hypothesis(hypothesis_id="H0", kind="no_change").model_dump()


@pytest.fixture
def case():
    env = Environment()
    tracker = ExecutionContract("test")
    call = lambda name, args, key: env.call(name, args, "C1", key)
    tracker.call(call, "get_payment", {"order_id": "O1"}, "hydrate")
    try:
        yield env, tracker, call
    finally:
        env.close()


def write(tracker, call, params=PARAMS):
    return tracker.call(call, "issue_refund", params, "ignored-step-id")


def test_fresh_receipt_and_no_duplicate_refund(case):
    env, tracker, call = case
    write(tracker, call)
    assert tracker.pending() and not tracker.receipts
    tracker.verify_pending(call)
    r = tracker.receipts[0]
    assert r.status == "VERIFIED" and r.source == "runtime"
    with pytest.raises(FrozenInstanceError):
        r.status = "FAILED"
    exported = r.to_dict(); exported["observed_value"]["payment.refunded_amount"] = 999
    assert r.to_dict()["observed_value"]["payment.refunded_amount"] == 1000
    write(tracker, call)
    assert env.snapshot()["payment.refunded_amount"] == 1000
    assert len([e for e in env.audit if e["tool_name"] == "issue_refund"]) == 1
    assert tracker.terminal_ready(PARAMS, "refund", True)
    assert not tracker.terminal_ready(PARAMS, "refund", False)


@pytest.mark.parametrize("value", [{"payment.order_id": "OTHER", "payment.refunded_amount": 1000},
                                    {"payment.order_id": "O1", "payment.refunded_amount": 0},
                                    {"payment.refunded_amount": 1000}])
def test_wrong_object_old_value_or_missing_identity_never_verifies(case, value):
    _, tracker, call = case
    write(tracker, call)
    with pytest.raises(ToolError):
        tracker.verify_pending(lambda *_: value)
    assert not tracker.terminal_ready(PARAMS, "refund", True)


def test_pending_blocks_other_write_and_retains_failed_read(case):
    _, tracker, call = case
    write(tracker, call)
    with pytest.raises(ToolError, match="verification_required"):
        write(tracker, call, {**PARAMS, "amount": 500})
    def fail(*_):
        raise ToolError("timeout")
    with pytest.raises(ToolError, match="timeout"):
        tracker.verify_pending(fail)
    assert tracker.pending()[0]["verification"] == "VERIFY_FAILED"
    restored = ExecutionContract.restore(tracker.checkpoint(), "test")
    restored.verify_pending(call)
    assert restored.terminal_ready(PARAMS, "refund", True)


def test_second_mutation_invalidates_terminal_evidence(case):
    _, tracker, call = case
    write(tracker, call); tracker.verify_pending(call)
    first = tracker.receipts[0]
    write(tracker, call, {**PARAMS, "amount": 500})
    assert not tracker.terminal_ready(PARAMS, "refund", True)
    tracker.verify_pending(call)
    assert tracker.receipts[0] == first
    assert not tracker.terminal_ready(PARAMS, "refund", True)
    assert tracker.terminal_ready({**PARAMS, "amount": 500}, "refund", True)


def test_response_loss_does_not_infer_commit_from_aggregate_balance(case):
    env, tracker, call = case
    env.faults["issue_refund"] = ["response_lost"]
    with pytest.raises(ToolError) as error:
        write(tracker, call)
    assert error.value.code == "timeout"
    rid = tracker.request_id("issue_refund", PARAMS)
    assert env.snapshot()["payment.refunded_amount"] == 1000
    restored = ExecutionContract.restore(tracker.checkpoint(), "test")
    assert restored.reconcile(rid) == "STILL_UNKNOWN"
    assert restored.reconcile(rid, lambda _: {"status": "NOT_COMMITTED", "request_id": rid}) == "STILL_UNKNOWN"
    with pytest.raises(ToolError, match="commit_unknown"):
        write(restored, call)
    assert restored.reconcile(rid, lambda _: {"status": "COMMITTED", "request_id": rid, "authoritative": True,
                                            "evidence_id": "test-adapter-request-log"}) == "COMMITTED"
    restored.verify_pending(call)
    assert restored.terminal_ready(PARAMS, "refund", True)
    assert env.snapshot()["payment.refunded_amount"] == 1000


def test_authoritative_noncommit_retry_keeps_original_baseline_and_request_id(case):
    env, tracker, call = case
    env.faults["issue_refund"] = ["timeout"]
    with pytest.raises(ToolError):
        write(tracker, call)
    rid = tracker.request_id("issue_refund", PARAMS)
    tracker.reconcile(rid, lambda _: {"status": "NOT_COMMITTED", "request_id": rid, "authoritative": True,
                                     "evidence_id": "test-adapter-transaction-log"})
    write(tracker, call); tracker.verify_pending(call)
    assert env.snapshot()["payment.refunded_amount"] == 1000
    assert {e["request_id"] for e in env.audit if e["tool_name"] == "issue_refund"} == {rid}


def test_crash_prepared_state_is_unknown_not_safe_to_replay(case):
    _, tracker, call = case
    snapshots = []
    tracker.persist = snapshots.append
    write(tracker, call)
    prepared = next(s for s in snapshots if s["body"]["events"][-1]["kind"] == "mutation_prepared")
    restored = ExecutionContract.restore(prepared, "test")
    assert restored.pending()[0]["commit"] == "COMMIT_UNKNOWN"
    with pytest.raises(ToolError, match="commit_unknown"):
        write(restored, call)
    altered = copy.deepcopy(prepared); altered["body"]["task_id"] = "other"
    with pytest.raises(ValueError):
        ExecutionContract.restore(altered, "test")


class Scripted:
    tokens = 0
    settings = {"model": "scripted-test-only"}
    def __init__(self, actions):
        self.actions = iter(actions)
    def decide(self, context):
        assert not ({"fixture", "expected", "gold", "initial_state"} & set(context))
        self.tokens += 1
        return next(self.actions)


def run(actions, env, **kwargs):
    return run_agent(Scripted(actions), TASK, parent("refund"), H0, "epoch", lambda n, a, k: env.call(n, a, "C1", k), **kwargs)


def test_primitive_forced_read_and_termination_are_explicit(case):
    env, _, _ = case
    result = run([Action(type="tool", name="issue_refund", arguments=PARAMS)], env, single_goal=True)
    assert result["outcome"] == "completed" and result["termination_source"] == "runtime"
    assert result["interventions"] == {"runtime_intervention_count": 2, "forced_readback_count": 1, "auto_termination_count": 1}
    assert result["metrics"]["llm_calls"] == 1
    assert result["metrics"]["tool_calls"] == 6
    assert result["verification_receipts"][0]["source"] == "runtime"


def test_skill_reuses_receipt_and_model_stops_autonomously(case):
    env, _, _ = case
    result = run([Action(type="skill", name="test-parent", arguments=PARAMS), Action(type="stop")], env, single_goal=True)
    assert result["outcome"] == "completed" and result["termination_source"] == "model"
    assert result["interventions"]["runtime_intervention_count"] == 0
    assert len(result["verification_receipts"]) == 1
    assert result["verification_receipts"][0]["source"] == "skill"


def test_unfinished_composite_is_not_auto_completed(case):
    env, _, _ = case
    result = run([Action(type="tool", name="issue_refund", arguments=PARAMS)], env, single_goal=False, max_steps=1)
    assert result["outcome"] == "max_steps_exceeded"
    assert result["interventions"]["auto_termination_count"] == 0


def test_no_write_stop_and_first_decision_have_no_intervention(case):
    env, _, _ = case
    result = run([Action(type="stop")], env, single_goal=True)
    assert result["interventions"]["runtime_intervention_count"] == 0
    decision = run([Action(type="tool", name="issue_refund", arguments=PARAMS)], env, single_goal=True, decision_only=True)
    assert decision["decision"] and not decision["verification_receipts"]
    assert env.snapshot()["payment.refunded_amount"] == 0


def test_runtime_read_failure_cannot_be_completed(case):
    env, _, _ = case
    env.faults["get_payment"] = [None, "timeout"]
    result = run([Action(type="tool", name="issue_refund", arguments=PARAMS), Action(type="stop")], env, single_goal=True)
    assert result["outcome"] == "verification_failed"


def test_runtime_metrics_partition_success_and_require_pairing():
    def row(key, success, count):
        return {"spec_hash": key, "verification": {"task_success": success}, "agent": {"interventions": {
            "runtime_intervention_count": count, "forced_readback_count": int(count > 0), "auto_termination_count": int(count > 1)}}}
    result = paired_execution_metrics([row("a", False, 0), row("b", True, 0)], [row("a", True, 2), row("b", True, 0)])
    assert result["rates"]["autonomous_eoc"] == result["rates"]["runtime_assisted_eoc"] == .5
    assert result["counts"]["rescued_by_runtime"] == 1
    with pytest.raises(ValueError):
        paired_execution_metrics([row("a", False, 0)], [row("b", True, 2)])


def test_arbitrary_postcondition_cannot_trigger_runtime_completion(case):
    env, _, _ = case
    contract = parent("refund")
    contract["postconditions"]["payment.status"] = "UNSUPPORTED_EXPECTATION"
    result = run_agent(Scripted([Action(type="tool", name="issue_refund", arguments=PARAMS)]), TASK,
                       contract, H0, "epoch", lambda n, a, k: env.call(n, a, "C1", k), max_steps=1, single_goal=True)
    assert result["outcome"] == "max_steps_exceeded"
    assert result["interventions"]["auto_termination_count"] == 0


def test_no_mutation_baseline_from_wrong_object(case):
    _, tracker, _ = case
    with pytest.raises(ToolError, match="read_object_mismatch"):
        tracker.call(lambda *_: {"payment.order_id": "O2", "payment.refunded_amount": 8000},
                     "get_payment", {"order_id": "O1"}, "bad")
    assert tracker.observations["O1"]["payment.refunded_amount"] == 0


def test_reconcile_ambiguous_and_different_request_are_bounded(case):
    env, tracker, call = case
    env.faults["issue_refund"] = ["timeout"]
    with pytest.raises(ToolError):
        write(tracker, call)
    rid = tracker.request_id("issue_refund", PARAMS)
    calls = []
    def lookup(key):
        calls.append(key)
        return {"request_id": "other", "status": "NOT_COMMITTED", "authoritative": True, "evidence_id": "unrelated"}
    for _ in range(3):
        assert tracker.reconcile(rid, lookup) == "STILL_UNKNOWN"
    assert calls == [rid, rid]
    with pytest.raises(ToolError):
        write(tracker, call)


@pytest.mark.parametrize("mode", ["file", "module"])
def test_execution_worker_cannot_read_gold(tmp_path, mode):
    private = tmp_path / "gold.json"; private.write_text("SECRET")
    output = tmp_path / "agent"; output.mkdir()
    request = {"guard_test": True, "output": str(output)}
    if mode == "file":
        request["path"] = str(private)
    completed = subprocess.run([sys.executable, "-m", "skillforge.execution_aware.worker"],
        input=json.dumps(request)+"\n", capture_output=True, text=True, timeout=15)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {"type": "denied"}


@pytest.mark.parametrize("tool,args,field,wanted", [
    ("update_shipping_address", {"order_id": "O1", "new_address": "New delivery avenue 400"}, "order.shipping_address", "New delivery avenue 400"),
    ("cancel_order", {"order_id": "O1"}, "order.status", "CANCELLED"),
])
def test_address_and_cancel_require_matching_order_receipt(case, tool, args, field, wanted):
    env, tracker, call = case
    tracker.call(call, tool, args, "mutation")
    assert tracker.pending()
    tracker.verify_pending(call)
    assert tracker.receipts[-1].verification_tool == "get_order"
    assert tracker.receipts[-1].to_dict()["expected_postcondition"] == {field: wanted}
    assert env.snapshot()[field] == wanted


def test_refund_uses_observed_total_not_zero_assumption():
    env = Environment(fixture={"refunded": 1000, "payment": "PARTIALLY_REFUNDED"})
    try:
        tracker = ExecutionContract("already-refunded")
        call = lambda n, a, k: env.call(n, a, "C1", k)
        tracker.call(call, "get_payment", {"order_id": "O1"}, "baseline")
        write(tracker, call); tracker.verify_pending(call)
        assert tracker.receipts[0].to_dict()["expected_postcondition"] == {"payment.refunded_amount": 2000}
    finally:
        env.close()


def test_known_business_rejection_is_not_pending_verification(case):
    env, _, _ = case
    env.faults["issue_refund"] = ["business_rule_rejected"]
    result = run([Action(type="tool", name="issue_refund", arguments=PARAMS)]*16, env, single_goal=True)
    assert result["outcome"] == "repeated_rejected_mutation"
    assert len(result["steps"]) == 2
    assert not result["verification_receipts"]
    assert result["metrics"]["tool_calls"] == 5
    assert env.snapshot()["payment.refunded_amount"] == 0
