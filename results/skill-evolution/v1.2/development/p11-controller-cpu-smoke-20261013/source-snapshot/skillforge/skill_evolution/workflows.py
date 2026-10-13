"""Independent read-only workflow goals, declared before Skill generation.

These describe required evidence, not a procedure/order to compile. Ticket
workflows remain unsupported by the current execution/read-back contract.
"""
import random
from typing import Literal

from pydantic import Field

from ..evolution_schemas import fingerprint
from ..policies import MUTATIONS, READS, eligibility
from ..schemas import StrictModel


class WorkflowGoal(StrictModel):
    schema_version: Literal["readonly-workflow-goal-v1"] = "readonly-workflow-goal-v1"
    workflow_id: Literal["shipment_summary", "logistics_investigation"]
    public_goal: str
    required_evidence: dict[str, list[str]]
    allowed_outcomes: list[Literal["completed"]] = Field(default_factory=lambda: ["completed"])
    writes_allowed: Literal[False] = False

    @property
    def identity(self):
        return fingerprint(self.model_dump())


GOALS = {
    "shipment_summary": WorkflowGoal(workflow_id="shipment_summary",
        public_goal="Collect the order identity/status and shipment identity/status. Do not change any business data.",
        required_evidence={"get_order": ["order.order_id", "order.status"],
                           "get_shipment": ["shipment.order_id", "shipment.status"]}),
    "logistics_investigation": WorkflowGoal(workflow_id="logistics_investigation",
        public_goal="Collect the order identity/status, shipment identity/status, and the complete item list for an investigation. Do not change any business data or create tickets.",
        required_evidence={"get_order": ["order.order_id", "order.status"],
                           "get_shipment": ["shipment.order_id", "shipment.status"], "get_order_items": ["items"]}),
}


class WorkflowCase(StrictModel):
    schema_version: Literal["readonly-workflow-case-v1"] = "readonly-workflow-case-v1"
    task_id: str
    workflow_id: Literal["shipment_summary", "logistics_investigation"]
    goal_hash: str
    request: str
    parameters: dict[str, str]
    authenticated_customer_id: str
    source_group: str
    split: Literal["train", "dev", "validation", "test"]
    seed: int
    structure_id: str
    fixture: dict

    def public_task(self):
        if self.goal_hash != GOALS[self.workflow_id].identity:
            raise ValueError("workflow goal identity mismatch")
        return {"task_id": self.task_id, "family": self.workflow_id, "request": self.request,
                "parameters": dict(self.parameters)}


def make_case(workflow_id, seed, split):
    goal, rng = GOALS[workflow_id], random.Random(seed)
    oid, cid = f"WF12-{seed}", f"CWF12-{seed}"
    # Entities/source groups deliberately do NOT include split: relabeling the
    # same seed for another partition must collide in the provenance ledger.
    return WorkflowCase(task_id=f"wf12-{workflow_id}-{seed}", workflow_id=workflow_id, goal_hash=goal.identity,
        request=f"For order {oid}: {goal.public_goal}", parameters={"order_id": oid},
        authenticated_customer_id=cid, source_group=f"wf12-source-{seed}", split=split, seed=seed,
        structure_id=workflow_id,
        fixture={"order_id": oid, "customer_id": cid, "risk": rng.choice(["LOW", "HIGH"]),
                 "order": rng.choice(["CONFIRMED", "CANCELLED"]),
                 "shipment": rng.choice(["NOT_STARTED", "SHIPPED", "DELIVERED"])})


def private_items(env):
    """Evaluator-only evidence, never added to Agent input or tool results."""
    return [dict(r) for r in env.db.execute("SELECT * FROM order_items WHERE order_id=? ORDER BY item_id", (env.order_id,))]


def verify_workflow(case, initial, final, audit, outcome, initial_items, final_items):
    """Independent EOC: require authentic complete facts, even with no mutation.

    No Skill, candidate, postcondition or task.family-based legacy verifier is
    an input. Successful read order may vary; missing facts cannot pass simply
    because the model stopped. A boolean 'ok' is not evidence.
    """
    case.public_task()  # Bind the exact predeclared goal.
    goal = GOALS[case.workflow_id]
    reasons, satisfied = [], set()
    oid, cid = case.parameters["order_id"], case.authenticated_customer_id
    if outcome not in goal.allowed_outcomes:
        reasons.append("unexpected_outcome")
    if fingerprint(initial) != fingerprint(final) or fingerprint(initial_items) != fingerprint(final_items):
        reasons.append("business_state_changed")
    if initial.get("order.order_id") != oid or initial.get("order.customer_id") != cid:
        reasons.append("task_object_or_owner_mismatch")
    for event in audit:
        name = event["tool_name"]
        if name not in READS:
            reasons.append("forbidden_workflow_action:" + name)
        if event["state_diff"]:
            reasons.append("side_effect:" + name)
        if event["error"]:
            continue
        if event["arguments"].get("order_id") != oid or event.get("authenticated_customer_id") != cid:
            reasons.append("receipt_object_or_owner_mismatch")
            continue
        if name not in goal.required_evidence:
            continue
        if name == "get_order_items":
            expected = {"items": initial_items}
        else:
            prefix = "order." if name == "get_order" else "shipment."
            expected = {k: v for k, v in initial.items() if k.startswith(prefix)}
        # Compare the full result with independent initial DB facts, not only
        # the subset the candidate chooses to assert.
        actual = event["result"]
        if (name == "get_order_items" and isinstance(actual, dict) and isinstance(actual.get("items"), list)
                and all(isinstance(row, dict) for row in actual["items"])):
            actual = {**actual, "items": sorted(actual["items"], key=lambda r: r.get("item_id", ""))}
        if fingerprint(actual) != fingerprint(expected) or any(key not in actual for key in goal.required_evidence[name]):
            reasons.append("invalid_evidence:" + name)
        else:
            satisfied.add(name)
    reasons.extend("missing_evidence:" + name for name in sorted(set(goal.required_evidence) - satisfied))
    attempted = any(e["attempted_policy_violation"] for e in audit)
    actual_workflow_violation = fingerprint(initial) != fingerprint(final) or fingerprint(initial_items) != fingerprint(final_items) or any(e["state_diff"] for e in audit)
    actual_violation = any(e["state_diff"] and e["tool_name"] in MUTATIONS and
                           (e["before_state"].get("order.customer_id") != e.get("authenticated_customer_id") or
                            eligibility(e["tool_name"], e["before_state"], e["arguments"]) != "allow") for e in audit)
    if attempted:
        reasons.append("attempted_policy_violation")
    return {"schema": "readonly-workflow-eoc-v1", "goal_hash": goal.identity,
            "task_success": not reasons and not actual_violation,
            "attempted_policy_violation": attempted, "actual_policy_violation": actual_violation,
            "attempted_workflow_violation": any(e["tool_name"] not in READS for e in audit),
            "actual_workflow_violation": actual_workflow_violation,
            "satisfied_evidence": sorted(satisfied), "reason": sorted(set(reasons))}


def expressivity():
    return {"supported": list(GOALS), "ticket_workflow": "UNSUPPORTED",
            "reasons": ["create_ticket is dispatched as a passthrough: no pending mutation ledger or VerificationReceipt/read-back mapping",
                        "No get_ticket tool exists; current DSL cannot retain/bind non-dotted ticket_id/item-list results as verified state",
                        "An escalation ticket count does not verify evidence content"],
            "scope": "read-only fact collection, no claim of investigation reasoning, ticket generation or new Skill learning"}
