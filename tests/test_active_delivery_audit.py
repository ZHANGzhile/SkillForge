import json

import pytest

from scripts.audit_active_evolution_delivery import checked_cache
from skillforge.evolution_schemas import fingerprint


def evidence(tmp_path, decision=None, truth=True):
    identity = {"task_hash": "task-A", "decision_only": True, "patch": {"kind": "no_change"}}
    result = {"spec_hash": "task-A", "decision_only": True, "agent": {"decision": decision},
              "truth_executable": truth, "decision_correct": decision is truth}
    key = fingerprint(identity)
    record = {"identity": identity, "result": result, "result_hash": fingerprint(result)}
    path = tmp_path / (key + ".json")
    path.write_text(json.dumps(record), encoding="utf-8")
    return key, identity, record, path


def test_unknown_decision_stays_failure_in_delivery_audit(tmp_path):
    key, identity, _, _ = evidence(tmp_path)
    assert not checked_cache(tmp_path, key, identity)["decision_correct"]


def test_same_task_cannot_reuse_a_different_bundle_result(tmp_path):
    key, identity, _, _ = evidence(tmp_path)
    with pytest.raises(ValueError, match="pairing"):
        checked_cache(tmp_path, key, {**identity, "patch": {"kind": "tighten"}})


def test_tampered_cached_result_rejected(tmp_path):
    key, identity, record, path = evidence(tmp_path)
    record["result"]["decision_correct"] = True
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        checked_cache(tmp_path, key, identity)


def test_rehashed_unknown_decision_cannot_be_reported_correct(tmp_path):
    key, identity, record, path = evidence(tmp_path)
    record["result"]["decision_correct"] = True
    record["result_hash"] = fingerprint(record["result"])
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match="Decision"):
        checked_cache(tmp_path, key, identity)
