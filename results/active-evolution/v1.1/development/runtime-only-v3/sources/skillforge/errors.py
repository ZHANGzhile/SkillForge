def classify_errors(result):
    categories = set()
    mapping = {"invalid_tool": "wrong_tool", "invalid_arguments": "wrong_arguments",
        "retry_budget_exhausted": "tool_error_not_recovered",
        "skill_not_executable": "wrong_skill", "skill_input_binding_mismatch": "wrong_arguments",
        "timeout": "tool_error_not_recovered", "temporary_unavailable": "tool_error_not_recovered",
        "permission_denied": "policy_violation_attempt", "business_rule_rejected": "policy_violation_attempt",
        "model_or_runtime_error": "model_or_runtime_error"}
    for step in result["steps"]:
        if step.get("error"):
            categories.add(mapping.get(step["error"], step["error"]))
    if result["outcome"] == "max_steps_exceeded":
        categories.add("max_steps_exceeded")
    reasons = result["verification"]["reason"]
    if "missing_verification" in reasons:
        categories.add("missing_verification")
    if not result["verification"]["task_success"] and result["outcome"] == "completed":
        categories.add("premature_stop")
    if result["verification"]["actual_policy_violation"]:
        categories.add("actual_policy_violation")
    return sorted(categories)
