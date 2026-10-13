import json

import pytest

from skillforge.evolution_schemas import fingerprint
from skillforge.skill_evolution_workbench.stage2 import stage2_status


def save(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    value = {**body, "hash": fingerprint(body)}
    path.write_text(json.dumps(value), encoding="utf-8")
    return value


def test_stage2_view_is_readonly_and_live_fee_is_not_finalized(tmp_path):
    folder = tmp_path / "development/p6-real-runtime-smoke-20261012"
    save(folder / "protocol.json", {"cases": [{"task_id": "one"}], "prior_tokens": 100, "phase_tokens": 20000})
    arm = folder / "0"
    (arm / "initial-state.json").parent.mkdir(parents=True)
    (arm / "initial-state.json").write_text("{}")
    body = {"runtime": {"model_requests": [{"status": "pending", "reserved_tokens": 16384}]}}
    path = arm / "checkpoints/0/snapshot.json"; path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"body": body, "hash": fingerprint(body)}))
    (arm / "admissions").mkdir(); (arm / "admissions/0.json").write_text('{"approved":true}')
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    result = stage2_status(tmp_path)
    live = result["stages"]["real_h0_smoke"]
    assert live["state"] == "RUNNING" and live["pending_requests"] == 1
    assert live["observed_tokens"] == 16384 and live["shared_observed_tokens"] == 16484
    assert not result["formal_stage2_started"] and not result["activated"]
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


def test_stage2_rejects_unbound_audit(tmp_path):
    folder = tmp_path / "development/p6-controlled-tools-20261012-r2"
    save(folder / "report.json", {"checkpoint_replays": 11, "actual_tool_calls": 56})
    save(folder / "independent-audit.json", {"passed": True, "report_hash": "unrelated"})
    with pytest.raises(ValueError, match="binding mismatch"): stage2_status(tmp_path)
