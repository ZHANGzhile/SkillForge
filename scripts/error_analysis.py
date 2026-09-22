"""Post-hoc task diagnostics; never change execution verdicts or training data."""
from collections import Counter


TAXONOMY = ("wrong_tool", "wrong_arguments", "wrong_skill", "policy_violation",
    "premature_stop", "failure_to_stop", "missing_verification", "tool_error_not_recovered",
    "insufficient_information", "max_steps_exceeded", "model_format_error",
    "wrong_outcome", "wrong_reuse_associated_failure", "unnecessary_continuation")


def diagnose(record):
    labels = set(record["error_categories"])
    failed = not record["verification"]["task_success"]
    # The legacy category describes the failed tool. The supplementary count
    # distinguishes whether the task subsequently recovered under its EOC.
    labels.discard("tool_error_not_recovered")
    if failed and any(s.get("error") in {"timeout", "temporary_unavailable", "retry_budget_exhausted"}
            or s.get("result", {}).get("error") in {"timeout", "temporary_unavailable", "retry_budget_exhausted"} for s in record["steps"]):
        labels.add("tool_error_not_recovered")
    if record["verification"]["actual_policy_violation"]:
        labels.add("policy_violation")
    if "unexpected_outcome" in record["verification"]["reason"]:
        labels.add("wrong_outcome")
    if any(event.get("gate_status") == "UNKNOWN" for event in record["skill_events"]):
        labels.add("insufficient_information")
    if failed and any(event.get("applicable") is False for event in record["skill_events"]):
        labels.add("wrong_reuse_associated_failure")
    for step in record["steps"]:
        detail = step.get("error_detail", "")
        if step.get("error") == "model_or_runtime_error" and any(marker in detail for marker in
                ("Invalid JSON", "json_invalid", "validation error for Action", "validation errors for Action")):
            labels.add("model_format_error")
    if record["task_family"] != "composite":
        for index, step in enumerate(record["steps"]):
            if (step.get("action") or {}).get("type") == "skill" and step.get("result", {}).get("success"):
                unnecessary = any((later.get("action") or {}).get("type") in {"tool", "skill"} for later in record["steps"][index + 1:])
                if unnecessary:
                    labels.add("unnecessary_continuation")
                    if record["outcome"] == "max_steps_exceeded":
                        labels.add("failure_to_stop")
                break
    return sorted(labels)


def summarize_diagnostics(records):
    counted = Counter(label for record in records for label in diagnose(record))
    return {"task_counts": {label: counted[label] for label in TAXONOMY},
        "tasks": len(records), "negative_transfer": None,
        "scope": "supplementary task-level evidence labels; nonexclusive; causal negative transfer is not identified",
        "rules": {"failure_to_stop": "primitive task exhausted budget after verified Skill and further tool/Skill actions",
            "tool_error_not_recovered": "tool error present AND final Expected Outcome Contract failed",
            "wrong_reuse_associated_failure": "known-inapplicable Skill attempt in a failed task; association only"}}
