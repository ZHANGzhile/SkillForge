import json
from pathlib import Path

from .environment import ToolError
from .policies import POLICY_VERSION, TOOLS, MUTATIONS, valid_address
from .schemas import Condition, GateResult, SkillContract, SkillStep


def matches(condition, state):
    value = state.get(condition.field)
    return value == condition.value if condition.op == "eq" else value in condition.value


def refund_facts(state, inputs):
    """Finite domain predicates, not a general expression language."""
    facts = dict(state)
    facts.pop("refund.amount_valid", None)
    facts.pop("refund.expected_total", None)
    if inputs is None or "amount" not in inputs:
        return facts
    amount = inputs["amount"]
    if type(amount) is not int or amount <= 0:
        facts["refund.amount_valid"] = False
        return facts
    captured, refunded = facts.get("payment.captured_amount"), facts.get("payment.refunded_amount")
    if type(captured) is int and type(refunded) is int:
        facts["refund.amount_valid"] = 0 <= refunded <= captured and amount <= captured - refunded
        facts["refund.expected_total"] = refunded + amount
    return facts


def gate(skill, state, inputs=None):
    state = refund_facts(state, inputs) if skill.family == "refund" else state
    missing = set()
    for condition in skill.forbidden_conditions:
        if condition.field not in state:
            missing.add(condition.field)
        elif matches(condition, state):
            return GateResult(status="INAPPLICABLE", reason=f"forbidden:{condition.field}")
    for condition in skill.preconditions:
        if condition.field not in state:
            missing.add(condition.field)
        elif not matches(condition, state):
            return GateResult(status="INAPPLICABLE", reason=f"precondition:{condition.field}")
    if missing:
        return GateResult(status="UNKNOWN", missing_fields=sorted(missing), reason="missing_observation")
    return GateResult(status="APPLICABLE")


def hydrate(skill, state, params, call, key):
    """Fixed read mapping, at most one call per tool; gate itself never performs I/O."""
    missing = gate(skill, state, params).missing_fields
    mapping = {"order": "get_order", "shipment": "get_shipment", "customer": "get_customer", "payment": "get_payment", "address": "validate_address", "refund": "get_payment"}
    tools = sorted({mapping[f.split(".")[0]] for f in missing if f.split(".")[0] in mapping})
    for tool in tools:
        args = {"order_id": params["order_id"]}
        if tool == "validate_address":
            args["new_address"] = params.get("new_address")
        state.update(call(tool, args, f"{key}:{tool}"))


def bind(value, inputs, state):
    if isinstance(value, str) and value.startswith("$input."):
        key = value[7:]
        if key not in inputs:
            raise ToolError("missing_skill_input", key)
        return inputs[key]
    if isinstance(value, str) and value.startswith("$state."):
        key = value[7:]
        if key not in state:
            raise ToolError("missing_skill_observation", key)
        return state[key]
    if isinstance(value, dict):
        return {k: bind(v, inputs, state) for k, v in value.items()}
    return value


def execute(skill, inputs, state, call, key, enforce_gate=True):
    decision = gate(skill, state, inputs)
    event = {"skill_id": skill.skill_id, "skill_version": skill.version, "input_binding": inputs,
        "applicable": None if decision.status == "UNKNOWN" else decision.status == "APPLICABLE",
        "gate_status": decision.status, "success": False, "internal_steps": []}
    if enforce_gate and decision.status != "APPLICABLE":
        event["error"] = "precondition_failed"
        return event
    try:
        before_mutation = dict(state)
        expected = None
        if any(k not in inputs for k in skill.inputs):
            raise ToolError("missing_skill_input")
        for index, step in enumerate(skill.procedure):
            if step.kind == "call":
                if step.tool not in TOOLS:
                    raise ToolError("invalid_skill_tool")
                args = bind(step.arguments, inputs, state)
                if step.tool in MUTATIONS and expected is None:
                    expected = bind(skill.postconditions, inputs, refund_facts(before_mutation, inputs))
                result = call(step.tool, args, f"{key}:{index}")
                state.update({k: v for k, v in result.items() if "." in k})
                if expected is None:
                    before_mutation.update({k: v for k, v in result.items() if "." in k})
                event["internal_steps"].append({"tool": step.tool, "arguments": args, "result": result})
            elif step.kind == "assert":
                if step.condition is None or step.condition.field not in state or not matches(step.condition, state):
                    raise ToolError("skill_assertion_failed")
            elif step.kind == "finish":
                break
        if expected is None:
            expected = bind(skill.postconditions, inputs, refund_facts(before_mutation, inputs))
        if any(state.get(k) != value for k, value in expected.items()):
            raise ToolError("skill_postcondition_failed")
        event["success"] = True
        event["verification"] = {"expected": expected, "matched": True}
    except ToolError as exc:
        event["error"] = exc.code
    return event


def compile_skill(trajectories, family, min_successes=3):
    """Bounded domain compilation; only business counterexamples teach boundaries."""
    if family not in {"modify_address", "cancel_order", "refund"}:
        raise ValueError("unsupported compiler family")
    if any(t["split"] != "train" for t in trajectories):
        raise ValueError("compiler accepts train trajectories only")
    if any(t.get("policy_version", POLICY_VERSION) != POLICY_VERSION for t in trajectories):
        raise ValueError("policy version mismatch")
    relevant = [t for t in trajectories if t["task_family"] == family]
    positive = [t for t in relevant if t["verification"]["task_success"] and t["outcome"] == "completed"
        and not t["verification"]["attempted_policy_violation"] and not t["verification"]["actual_policy_violation"]]
    # Successful refusals are counterexamples to the procedure, not successful executions.
    negative = [t for t in relevant if not t["verification"]["task_success"]
        and any(e.get("error") in {"business_rule_rejected", "permission_denied"} for e in t["tool_audit"])]
    if len({t["trajectory_id"] for t in positive}) < min_successes or not negative:
        raise ValueError("need >=3 unique successful trajectories AND failed trajectories")
    mutation = {"modify_address": "update_shipping_address", "cancel_order": "cancel_order", "refund": "issue_refund"}[family]
    read = "get_payment" if family == "refund" else "get_shipment"
    verify_read = "get_payment" if family == "refund" else "get_order"
    # Required partial order is checked on every episode, not just tool membership.
    for trajectory in positive:
        names = [e["tool_name"] for e in trajectory["tool_audit"] if not e["error"]]
        try:
            write = names.index(mutation)
            if "get_order" not in names[:write] or read not in names[:write] or verify_read not in names[write + 1:]:
                raise ValueError("missing ordered read/mutation/verification evidence")
        except ValueError as exc:
            raise ValueError("missing ordered read/mutation/verification evidence") from exc
    sources = [t["trajectory_id"] for t in positive + negative]
    def observation(t, field):
        if field.startswith("refund."):
            return refund_facts(t["initial_state"], t.get("parameters", {})).get(field)
        if field == "address.valid":
            params = t.get("parameters") or (t["steps"][0]["context"]["parameters"] if t.get("steps") else {})
            return valid_address(params.get("new_address"))
        return t["initial_state"].get(field)
    def condition(field, value, op="eq", forbidden=False):
        evidence = [f"policy:{POLICY_VERSION}:{field}"]
        def satisfied(t):
            observed = observation(t, field)
            return observed == value if op == "eq" else observed in value
        evidence += [f"success:{t['trajectory_id']}" for t in positive if satisfied(t) != forbidden]
        evidence += [f"failure:{t['trajectory_id']}" for t in negative if satisfied(t) == forbidden]
        return Condition(field=field, op=op, value=value, evidence=evidence)
    calls = [
        SkillStep(kind="call", tool="get_order", arguments={"order_id": "$input.order_id"}),
        SkillStep(kind="call", tool=read, arguments={"order_id": "$input.order_id"}),
    ]
    preconditions = [condition("order.status", "CONFIRMED"), condition("shipment.status", "NOT_STARTED")]
    arguments = {"order_id": "$input.order_id"}
    if family == "refund":
        arguments["amount"] = "$input.amount"
        preconditions = [condition("payment.status", ["CAPTURED", "PARTIALLY_REFUNDED"], "in"), condition("refund.amount_valid", True)]
    if family == "modify_address":
        arguments["new_address"] = "$input.new_address"
        calls.append(SkillStep(kind="call", tool="validate_address", arguments=arguments))
        preconditions.append(condition("address.valid", True))
    calls += [SkillStep(kind="call", tool=mutation, arguments=arguments),
        SkillStep(kind="call", tool=verify_read, arguments={"order_id": "$input.order_id"}), SkillStep(kind="finish")]
    forbidden = [condition("customer.risk_level", "HIGH", forbidden=True)]
    if family != "refund":
        forbidden.insert(0, condition("shipment.status", ["SHIPPED", "DELIVERED"], "in", True))
    postconditions = {"modify_address": {"order.shipping_address": "$input.new_address"}, "cancel_order": {"order.status": "CANCELLED"},
        "refund": {"payment.refunded_amount": "$state.refund.expected_total"}}[family]
    contract = SkillContract(skill_id={"modify_address": "modify_unfulfilled_order_address", "cancel_order": "cancel_unfulfilled_order", "refund": "refund_captured_payment"}[family],
        family=family, inputs=["order_id", "new_address"] if family == "modify_address" else ["order_id", "amount"] if family == "refund" else ["order_id"],
        preconditions=preconditions,
        forbidden_conditions=forbidden,
        procedure=calls, postconditions=postconditions,
        source_trajectory_ids=sources, policy_version=POLICY_VERSION,
        statistics={"compiler": {"type": "bounded_domain_v2", "positive_count": len(positive), "business_counterexamples": len(negative),
            "excluded_failures": len([t for t in relevant if not t["verification"]["task_success"]]) - len(negative)}})
    if not any(e.startswith("failure:") for c in contract.preconditions + contract.forbidden_conditions for e in c.evidence):
        raise ValueError("no failed trajectory supports an applicability boundary")
    return contract


def compile_address(trajectories, min_successes=3):
    return compile_skill(trajectories, "modify_address", min_successes)


def compile_naive_skill(trajectories, family, min_successes=3):
    """Success-only baseline: observed constant states, no policy boundary synthesis."""
    if family not in {"modify_address", "cancel_order", "refund"} or any(t["split"] != "train" for t in trajectories):
        raise ValueError("naive compiler requires supported family and train split")
    positive = [t for t in trajectories if t["task_family"] == family and t["outcome"] == "completed"
        and t["verification"]["task_success"] and not t["verification"]["attempted_policy_violation"]]
    if len({t["trajectory_id"] for t in positive}) < min_successes:
        raise ValueError("naive compiler needs >=3 successful instances")
    mutation = {"modify_address": "update_shipping_address", "cancel_order": "cancel_order", "refund": "issue_refund"}[family]
    if any(not any(e["tool_name"] == mutation and not e["error"] for e in t["tool_audit"]) for t in positive):
        raise ValueError("successful mutation evidence missing")
    preconditions = []
    for field in (["payment.status", "customer.risk_level"] if family == "refund" else ["order.status", "shipment.status", "customer.risk_level"]):
        values = {t["initial_state"].get(field) for t in positive}
        if len(values) == 1 and None not in values:
            preconditions.append(Condition(field=field, value=next(iter(values)), evidence=[f"success:{t['trajectory_id']}" for t in positive]))
    arguments = {"order_id": "$input.order_id"}
    if family == "modify_address":
        arguments["new_address"] = "$input.new_address"
    if family == "refund":
        arguments["amount"] = "$input.amount"
    steps = [SkillStep(kind="call", tool=name, arguments=arguments if name == mutation else {"order_id": "$input.order_id"})
        for name in (["get_order", "get_payment", mutation, "get_payment"] if family == "refund" else ["get_order", "get_shipment", mutation, "get_order"])]
    return SkillContract(skill_id="naive_" + family, family=family,
        inputs=["order_id", "new_address"] if family == "modify_address" else ["order_id", "amount"] if family == "refund" else ["order_id"],
        preconditions=preconditions, forbidden_conditions=[], procedure=steps,
        postconditions={"order.shipping_address": "$input.new_address"} if family == "modify_address" else {"payment.refunded_amount": "$state.refund.expected_total"} if family == "refund" else {"order.status": "CANCELLED"},
        source_trajectory_ids=[t["trajectory_id"] for t in positive], policy_version=POLICY_VERSION)


class SkillRegistry:
    def __init__(self, root="data/skills"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, skill):
        if not skill.skill_id.replace("_", "").isalnum():
            raise ValueError("invalid skill ID")
        path = self.root / f"{skill.skill_id}.v{skill.version}.json"
        payload = skill.model_dump_json(indent=2)
        if path.exists() and path.read_text(encoding="utf-8") != payload:
            raise ValueError("immutable skill version; increment version")
        path.write_text(payload, encoding="utf-8")
        return path

    def list(self):
        return [SkillContract.model_validate_json(p.read_text(encoding="utf-8")) for p in sorted(self.root.glob("*.json"))]
