import time

import pytest

from scripts.execution_aware_formal import H0, ModelLedger, agent_admission, evaluate_group
from scripts.execution_aware_protocol import design, write_split_dataset
from skillforge.evolution_schemas import Hypothesis, Predicate, fingerprint
from test_evolution_execution import parent


def result(key, success=True, normal=True, violation=False, runtime="new"):
    return {"spec_hash": key, "truth_executable": normal, "decision_correct": True,
            "verification": {"task_success": success, "actual_policy_violation": violation, "attempted_policy_violation": False},
            "seconds": .01, "agent": {"decision": normal, "metrics": {"tokens": 100, "tool_calls": 2, "llm_calls": 1}, "interventions": {
                "runtime_intervention_count": int(runtime == "new"), "forced_readback_count": int(runtime == "new"), "auto_termination_count": 0}}}


def test_strict_agent_validation_keeps_stable_negative_cases_and_decision_requirements():
    a = [result("changed"), result("stable", normal=False)]
    b = [result("changed"), result("stable", False, normal=False)]
    assert not agent_admission(a, b, a[:1], b[:1], 1)["passed"]
    assert agent_admission(a, a, a[:1], a[:1], 1)["passed"]
    with pytest.raises(ValueError, match="complete"):
        agent_admission(a, a, [], [], 1)
    with pytest.raises(ValueError, match="pairing"):
        agent_admission(a, [result("other"), a[1]], a[:1], a[:1], 1)


def test_candidate_diagnostic_and_runtime_specific_fallback_are_distinct(tmp_path):
    dataset = tmp_path/"data"
    manifest = write_split_dataset(dataset, "W3", 411, {"explore": 80, "model_validation": 8,
        "model_stable_validation": 4, "model_test": 8, "model_stable_test": 4}, parent("refund"))
    valid_id = next(k for k,v in manifest["members"].items() if v["split"] == "model_validation")
    test_id = next(k for k,v in manifest["members"].items() if v["split"] == "model_test")
    patch = Hypothesis(hypothesis_id="learned", kind="restrict", predicates=(Predicate(field="request.amount",op="gt",value=3000),)).model_dump(mode="json")
    class Ledger:
        protocol_hash = "unit-test"
        def evaluate(self, spec, world, contract, patch, runtime, decision):
            success = not (spec["task_id"] == test_id and patch["kind"] == "no_change")
            if runtime == "old" and patch["kind"] != "no_change" and spec["task_id"] == valid_id:
                success = False
            return result(fingerprint(spec), success, runtime=runtime), fingerprint([spec,patch,runtime,decision])
    boundary = {"before": H0, "effective": patch, "belief_converged": True, "nontrivial": True,
                "boundary_validation_passed": True, "boundary_admitted": True}
    report = evaluate_group(Ledger(), dataset, tmp_path/"evaluation", "W3", 411, boundary, {"old": H0, "new": H0})
    assert not report["runtime_results"]["old"]["agent_admitted"]
    assert report["runtime_results"]["new"]["agent_admitted"]
    assert report["candidate_arms"]["old_proposal"] == 1
    assert report["effective_arms"]["old_proposal"] == 7/8
    assert report["effective_arms"]["new_proposal"] == 1


def test_failed_model_attempts_are_reserved_and_retry_is_bounded(tmp_path):
    protocol = {"config": {"limits": design()["limits"]}, "prior_charged_tokens": 0,
                "prior_invocation_seconds": 0, "model_settings": {}}
    ledger = ModelLedger(tmp_path, protocol)
    class Broken:
        receive = lambda self, timeout=120: None
        def run(self, *args):
            raise RuntimeError("infrastructure failure")
        def close(self):
            pass
    ledger.open = lambda: setattr(ledger, "session", Broken())
    ledger.open(); ledger.invocation_start = time.perf_counter()
    with pytest.raises(RuntimeError, match="infrastructure"):
        ledger.evaluate({"task_id": "t"}, "W3", {}, H0, "new")
    assert ledger.charged_tokens == 2*16*16384
    assert len(list((ledger.root/"failures").glob("*.json"))) == 2
    with pytest.raises(RuntimeError, match="retry limit"):
        ledger.evaluate({"task_id": "t"}, "W3", {}, H0, "new")
