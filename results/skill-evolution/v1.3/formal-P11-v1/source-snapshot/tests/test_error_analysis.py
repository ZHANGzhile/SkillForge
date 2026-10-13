from scripts.error_analysis import diagnose, summarize_diagnostics


def test_diagnostics_separate_recovery_format_errors_and_association():
    row = {"task_family": "refund", "outcome": "escalated", "skill_events": [],
        "verification": {"task_success": True, "actual_policy_violation": False, "reason": []},
        "error_categories": ["tool_error_not_recovered"], "steps": [{"error": "timeout"}]}
    assert "tool_error_not_recovered" not in diagnose(row)
    row["verification"].update(task_success=False, reason=["unexpected_outcome"])
    row["steps"].append({"error": "model_or_runtime_error", "error_detail": "1 validation error for Action: json_invalid"})
    row["skill_events"] = [{"applicable": False, "gate_status": "INAPPLICABLE"}]
    assert {"tool_error_not_recovered", "model_format_error", "wrong_outcome", "wrong_reuse_associated_failure"} <= set(diagnose(row))
    assert summarize_diagnostics([row])["negative_transfer"] is None


def test_verified_primitive_skill_followed_by_exhaustion_is_failure_to_stop():
    row = {"task_family": "refund", "outcome": "max_steps_exceeded", "skill_events": [], "error_categories": ["max_steps_exceeded"],
        "verification": {"task_success": False, "actual_policy_violation": False, "reason": ["unexpected_outcome"]},
        "steps": [{"action": {"type": "skill"}, "result": {"success": True}}, {"action": {"type": "tool"}}]}
    assert "failure_to_stop" in diagnose(row)
    row["task_family"] = "composite"
    assert "failure_to_stop" not in diagnose(row)
