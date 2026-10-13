import pytest

from skillforge.gap_detection import detect_gaps, trajectory_diagnostics
from test_belief import evidence


def test_gaps_cluster_deterministically_not_one_per_failure():
    rows=[evidence(i) for i in range(3)]
    a=detect_gaps(rows)
    assert a==detect_gaps(list(reversed(rows)))
    gap=next(g for g in a if g["gap_type"]=="gate_false_allow")
    assert len(gap["evidence_trajectory_ids"])==3
    assert any(g["gap_type"]=="repeated_failure_cluster" for g in a)
    with pytest.raises(ValueError,match="forbidden"):
        detect_gaps(rows,[{"expected":"escalate"}])


def test_false_block_requires_executed_positive():
    assert not any(g["gap_type"]=="gate_false_block" for g in detect_gaps([evidence(label="unknown",baseline_prediction=False)]))
    assert any(g["gap_type"]=="gate_false_block" for g in detect_gaps([evidence(label="executable",baseline_prediction=False)]))


def test_secondary_telemetry_does_not_confuse_retry_with_read_loop():
    step={"action":{"type":"tool","name":"get_order"},"context":{"observations":{"order.status":"PENDING"}},"result":{"order.status":"PENDING"}}
    t={"trajectory_id":"t0","outcome":"refused","verification":{"reason":["unexpected_outcome","missing_verification"]},
        "steps":[step,step,step],"skill_events":[{"success":False,"error":"postcondition_failed"}]}
    flags=trajectory_diagnostics(t)["verified_flags"]
    assert {"wrong_terminal","premature_refusal","missing_verification","read_loop","skill_execution_failure"}<=set(flags)
    t["steps"]=[step,{**step,"error":"timeout"},step]
    assert "read_loop" not in trajectory_diagnostics(t)["verified_flags"]
