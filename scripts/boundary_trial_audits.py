"""Independent saved DSL/public-probe projection for the continuous study."""
from scripts.boundary_trial_worlds import policy
from skillforge.evolution_execution import execute_frozen
from skillforge.environment import ToolError
from skillforge.skill_evolution.agent_evidence import semantic


def replay_probe(raw, spec, contract, world):
    cursor, result = 0, None
    def call(name, args, key):
        nonlocal cursor
        if cursor >= len(raw["tool_audit"]): raise ValueError("missing actual probe tool response")
        event = raw["tool_audit"][cursor]; cursor += 1
        if (event["tool_name"], event["arguments"], event["request_id"]) != (name, args, key):
            raise ValueError("probe request differs from frozen program")
        if event["error"]: raise ToolError(event["error"])
        return event["result"]
    try: result = execute_frozen(contract, spec["parameters"], call, spec["task_id"], force_probe=True)
    except ToolError: pass
    violations = sum(bool(e["state_diff"]) and e["committed"] and e["tool_name"] in
        {"issue_refund", "update_shipping_address", "cancel_order"} and
        policy(world, e["tool_name"], e["before_state"], e["arguments"]) != "allow" for e in raw["tool_audit"])
    if (cursor != len(raw["tool_audit"]) or semantic(result) != semantic(raw["execution"]) or
            bool(result and result["success"]) != raw["procedure_success"] or violations != raw["actual_violations"]):
        raise ValueError("actual probe/DSL/postcondition/safety replay differs")
