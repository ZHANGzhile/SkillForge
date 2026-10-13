from scripts.attribute_execution_regressions import diagnose


def test_read_before_mutation_or_wrong_object_is_not_verification():
    def tool(name, oid="O1"):
        return {"tool_name": name, "arguments": {"order_id": oid}, "committed": True, "error": None}
    row = {"tool_audit": [tool("get_payment"), tool("issue_refund"), tool("get_payment", "O2")],
           "agent": {"steps": [], "outcome": "completed"}, "verification": {"task_success": False, "reason": []}}
    d = diagnose(row)
    assert d["primary"] == "missing_post_write_verification"
    assert d["evidence"] == ["/result/tool_audit/1"]
    row["tool_audit"].append(tool("get_payment"))
    row["agent"]["steps"] = [{"error": "model_error", "error_type": "ValidationError"}]
    row["agent"]["outcome"] = "error"
    assert diagnose(row)["primary"] == "invalid_action_schema"
