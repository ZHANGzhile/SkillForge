"""Independent, replayable validation for the first read-only program lane.

Program conformance, fail-closed probes and Agent EOC are separate. This module
cannot activate a bundle, and engineering suites can never admit a program.
"""
import hashlib
from pathlib import Path
from typing import Literal

from pydantic import Field

from ..environment import Environment, ToolError
from ..evolution_common.artifacts import clone
from ..evolution_schemas import fingerprint
from ..execution_aware.contracts import ExecutionContract
from ..policies import POLICY_VERSION, READS
from ..schemas import StrictModel, SkillContract
from ..skills import execute
from .workflows import GOALS, WorkflowCase, private_items, verify_workflow


class ValidationCase(StrictModel):
    case: WorkflowCase
    category: Literal["positive", "boundary", "negative", "fault"]
    stable: bool = False
    expected_error: str | None = None
    authenticated_customer_id: str | None = None
    parameters: dict[str, str] | None = None
    faults: dict[str, list[str]] = Field(default_factory=dict)


def validator_sources():
    root = Path(__file__).resolve().parents[2]
    names = ("environment.py", "policies.py", "tool_schemas.py", "schemas.py", "skills.py",
             "execution_aware/contracts.py", "skill_evolution/workflows.py", "skill_evolution/validation.py")
    return {name: hashlib.sha256((root / "skillforge" / name).read_bytes()).hexdigest() for name in names}


def checked_hash(value):
    if not isinstance(value, dict) or "hash" not in value or fingerprint({key: item for key, item in value.items() if key != "hash"}) != value["hash"]:
        raise ValueError("artifact content hash mismatch")


def declare_protocol(entry, goal_hash, cases, ledger, *, mode="engineering", learn_candidate=None, min_sources=6):
    if fingerprint({key: value for key, value in entry.items() if key != "revision"}) != entry["revision"]:
        raise ValueError("catalog revision mismatch")
    if mode not in {"engineering", "formal"} or type(min_sources) is not int or min_sources < 6:
        raise ValueError("explicit mode and at least six validation source groups required")
    cases = [ValidationCase.model_validate(item) for item in cases]
    if not cases or len({item.case.task_id for item in cases}) != len(cases):
        raise ValueError("unique validation tasks required")
    if mode == "formal":
        if learn_candidate is None: raise ValueError("formal validation requires a bound learn candidate")
        checked_hash(learn_candidate)
        if (learn_candidate.get("schema") != "trace-compiled-readonly-candidate-v1" or
                learn_candidate.get("compiler_version") != "readonly-trace-compiler-v1" or
                fingerprint(learn_candidate["skill"]) != fingerprint(entry["contract"]) or learn_candidate["goal_hash"] != goal_hash or
                len(set(learn_candidate["source_groups"])) < 3 or
                any(ledger.owners.get(group) != "train" for group in learn_candidate["source_groups"])):
            raise ValueError("candidate must be bound to independently owned learn evidence")
    ownership = {group: "train" for group in learn_candidate["source_groups"]} if mode == "formal" else {}
    for item in cases:
        item.case.public_task()
        if item.case.goal_hash != goal_hash or item.case.split != ("dev" if mode == "engineering" else "validation"):
            raise ValueError("validation goal or split mismatch")
        if item.category in {"positive", "boundary"}:
            if item.expected_error is not None or item.faults or item.parameters is not None or item.authenticated_customer_id is not None:
                raise ValueError("completion cases cannot inject a denial/fault")
        elif item.category == "negative":
            if item.expected_error not in {"permission_denied", "not_found", "invalid_arguments"} or item.faults:
                raise ValueError("negative probes need predeclared environment denial")
        elif (item.expected_error not in {"timeout", "temporary_unavailable"} or not item.faults or
              any(name not in READS or values not in [[item.expected_error], ["response_lost"]] for name, values in item.faults.items())):
            raise ValueError("fault probes support one declared read failure per tool")
        partition = "dev" if mode == "engineering" else "stable_validation" if item.stable else "validation"
        keys = [item.case.task_id, item.case.parameters["order_id"], item.case.fixture["customer_id"]]
        ledger.claim(item.case.source_group, partition, related_groups=keys)
        ownership.update({key: partition for key in [item.case.source_group, *keys]})
    body = {"schema": "readonly-program-validation-protocol-v1", "mode": mode, "goal_hash": goal_hash,
            "catalog_revision": entry["revision"], "contract_hash": fingerprint(entry["contract"]),
            "cases": [item.model_dump() for item in cases], "ownership": ownership,
            "min_sources": min_sources, "validator_sources": validator_sources(),
            "learn_candidate": clone(learn_candidate), "scope": "program validation only; no Agent admission or activation"}
    return {**body, "hash": fingerprint(body)}


def static_check(contract, goal_hash):
    errors = []
    try: skill = SkillContract.model_validate(contract)
    except ValueError:
        return {"passed": False, "errors": ["invalid_contract_schema"]}
    goal = GOALS.get(skill.family)
    if goal is None or goal.identity != goal_hash:
        return {"passed": False, "errors": ["unsupported_or_mismatched_public_goal"]}
    if skill.policy_version != POLICY_VERSION: errors.append("policy_version_changed")
    if skill.inputs != ["order_id"]: errors.append("unsupported_inputs")
    if skill.preconditions or skill.forbidden_conditions: errors.append("readonly_goal_has_unjustified_boundary")
    if skill.procedure[-1].kind != "finish" or sum(node.kind == "finish" for node in skill.procedure) != 1:
        errors.append("exactly_one_final_finish_required")
    produced, called = set(), set()
    for node in skill.procedure:
        if node.kind == "call":
            if node.tool not in READS - {"validate_address"}: errors.append("tool_outside_readonly_whitelist")
            if node.arguments != {"order_id": "$input.order_id"} or node.condition is not None:
                errors.append("invalid_or_instance_specific_call_binding")
            called.add(node.tool)
            produced.update(goal.required_evidence.get(node.tool, []))
        elif node.kind == "assert":
            if (node.tool or node.arguments or node.condition is None or node.condition.field not in produced):
                errors.append("assert_before_observation_or_invalid_node")
            elif node.condition.field not in {"order.status", "shipment.status"}:
                errors.append("assert_value_binding_not_supported")
            elif (node.condition.op == "eq" and not isinstance(node.condition.value, str)) or (
                    node.condition.op == "in" and (not isinstance(node.condition.value, list) or
                                                   not all(isinstance(value, str) for value in node.condition.value))):
                errors.append("invalid_assert_value_type")
        elif node.tool or node.arguments or node.condition is not None:
            errors.append("finish_has_unexpected_payload")
    if not set(goal.required_evidence).issubset(called): errors.append("missing_required_goal_read")
    expected = {field: "$input.order_id" for fields in goal.required_evidence.values() for field in fields if field.endswith(".order_id")}
    if fingerprint(skill.postconditions) != fingerprint(expected): errors.append("postconditions_do_not_match_public_goal_identity")
    return {"passed": not errors, "errors": sorted(set(errors))}


def database_hash(env):
    return fingerprint(list(env.db.iterdump()))


def run_case(contract, item):
    item = ValidationCase.model_validate(item)
    case, skill = item.case, SkillContract.model_validate(contract)
    env = Environment(fixture=case.fixture, faults=item.faults)
    tracker = ExecutionContract(case.task_id + ":program-validation")
    initial, items, before = env.snapshot(), private_items(env), database_hash(env)
    try:
        def dispatch(name, args, key):
            if name not in READS: raise ToolError("readonly_validation_blocked_write")
            try: return env.call(name, args, item.authenticated_customer_id or case.authenticated_customer_id, key)
            finally:
                if env.audit: env.audit[-1]["decision_origin"] = "scripted:program-validation"
        event = execute(skill, item.parameters if item.parameters is not None else case.parameters, {},
                        lambda name, args, key: tracker.call(dispatch, name, args, key, source="skill"), case.task_id)
        outcome = "completed" if event["success"] else "error"
        verdict = verify_workflow(case, initial, env.snapshot(), env.audit, outcome, items, private_items(env))
        unchanged, pending = database_hash(env) == before, tracker.pending()
        expected_denial = item.category == "negative" and event.get("error") == item.expected_error
        expected_fault = item.category == "fault" and event.get("error") == item.expected_error
        negative_allow = item.category == "negative" and (event["success"] or any(e["error"] is None for e in env.audit))
        unexpected_attempts = sum(e["attempted_policy_violation"] and not (
            item.category == "negative" and e["error"] == item.expected_error) for e in env.audit)
        behavior = bool((verdict["task_success"] if item.expected_error is None else
                         (expected_denial or expected_fault) and not event["success"]) and
                        unchanged and not pending and not negative_allow and not unexpected_attempts)
        return {"task_id": case.task_id, "source_group": case.source_group, "category": item.category, "stable": item.stable,
                "initial_database_hash": before, "final_database_hash": database_hash(env), "database_unchanged": unchanged,
                "execution": event, "eoc": verdict, "behavior_conformant": behavior,
                "expected_probe_denial": expected_denial, "expected_fault_exit": expected_fault,
                "false_allow": bool(negative_allow), "unexpected_attempted_violations": unexpected_attempts,
                "raw_attempted_policy_violations": sum(e["attempted_policy_violation"] for e in env.audit),
                "actual_violation": not unchanged or bool(pending) or verdict["actual_workflow_violation"],
                "tool_calls": len(env.audit), "tool_audit": clone(env.audit), "execution_contract": tracker.checkpoint(),
                "pending_obligations": clone(pending)}
    finally: env.close()


def validate_program(entry, protocol):
    checked_hash(protocol)
    class SavedOwnership:
        owners = protocol["ownership"]
        def claim(self, group, split, *, related_groups=()):
            if any(self.owners.get(key) != split for key in [group, *related_groups]):
                raise ValueError("saved validation source ownership mismatch")
    replay_protocol = declare_protocol(entry, protocol["goal_hash"], protocol["cases"], SavedOwnership(),
        mode=protocol["mode"], learn_candidate=protocol["learn_candidate"], min_sources=protocol["min_sources"])
    if replay_protocol != protocol:
        raise ValueError("validation protocol content mismatch")
    if (protocol["validator_sources"] != validator_sources() or entry["revision"] != protocol["catalog_revision"] or
            fingerprint(entry["contract"]) != protocol["contract_hash"] or
            fingerprint({key: value for key, value in entry.items() if key != "revision"}) != entry["revision"]):
        raise ValueError("validation execution identity differs from declared protocol")
    static = static_check(entry["contract"], protocol["goal_hash"])
    if entry["dependencies"]:
        static = {"passed": False, "errors": sorted(set(static["errors"] + ["dependency_composition_not_supported"]))}
    rows = [run_case(entry["contract"], item) for item in protocol["cases"]] if static["passed"] else []
    categories = {category: sum(row["category"] == category for row in rows) for category in ("positive", "boundary", "negative", "fault")}
    groups = len({row["source_group"] for row in rows})
    safety = all(not row["actual_violation"] and not row["false_allow"] and not row["unexpected_attempted_violations"] for row in rows)
    conformant = bool(rows) and all(row["behavior_conformant"] for row in rows)
    enough = all(categories.values()) and groups >= protocol["min_sources"] and any(row["stable"] for row in rows)
    decision = "REJECTED" if not static["passed"] or not safety or not conformant else (
        "ADMITTED" if protocol["mode"] == "formal" and enough else "INCONCLUSIVE")
    body = {"schema": "readonly-program-validation-report-v1", "protocol": clone(protocol), "entry": clone(entry),
            "static": static, "cases": rows, "category_counts": categories, "independent_sources": groups,
            "safety_passed": safety, "behavior_conformant": conformant, "sufficient_coverage": bool(enough),
            "decision": decision, "program_admitted": decision == "ADMITTED", "agent_admitted": False,
            "engineering_passed": static["passed"] and safety and conformant and bool(enough),
            "tool_calls": sum(row["tool_calls"] for row in rows), "model_calls": 0,
            "research_claim_passed": None, "isolated_activated": False, "deployed": False}
    return {**body, "hash": fingerprint(body)}


def without_latency(report):
    value = clone(report); value.pop("hash", None)
    for row in value["cases"]:
        for event in row["tool_audit"]: event.pop("latency_ms", None)
    return value


def audit_validation(report):
    checked_hash(report)
    replay = validate_program(report["entry"], report["protocol"])
    if fingerprint(without_latency(replay)) != fingerprint(without_latency(report)):
        raise ValueError("independent program validation replay mismatch")
    return {"passed": True, "report_hash": report["hash"], "sources": validator_sources(), "replay_tool_calls": replay["tool_calls"]}


def program_admission(report):
    audit = audit_validation(report)
    body = {"schema": "program-admission-receipt-v1", "catalog_revision": report["entry"]["revision"],
            "decision": report["decision"], "report": clone(report), "audit": audit,
            "agent_admitted": False, "isolated_activated": False, "deployed": False}
    return {**body, "hash": fingerprint(body)}


def audit_program_admission(receipt):
    checked_hash(receipt)
    audit = audit_validation(receipt["report"])
    if (receipt["audit"] != audit or receipt["decision"] != receipt["report"]["decision"] or
            receipt["catalog_revision"] != receipt["report"]["entry"]["revision"] or
            receipt["agent_admitted"] or receipt["isolated_activated"] or receipt["deployed"]):
        raise ValueError("program admission receipt mismatch")
    return audit
