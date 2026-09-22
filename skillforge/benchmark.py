import csv
import json
import statistics
import uuid
from pathlib import Path

from .environment import Environment
from .runtime import Runtime
from .schemas import ExpectedOutcome, Task


def generate_tasks(split="test", repeats=1):
    """Explicit oracle table, separate from policy implementation."""
    cases = [
        ("modify_address", {}, "completed"),
        ("modify_address", {"shipment": "SHIPPED"}, "refused"),
        ("modify_address", {"shipment": "DELIVERED"}, "refused"),
        ("modify_address", {"shipment": "PROCESSING"}, "escalated"),
        ("modify_address", {"risk": "HIGH"}, "escalated"),
        ("modify_address", {"invalid_address": True}, "refused"),
        ("cancel_order", {}, "completed"),
        ("cancel_order", {"shipment": "SHIPPED"}, "refused"),
        ("cancel_order", {"shipment": "PROCESSING"}, "escalated"),
        ("cancel_order", {"order": "CANCELLED"}, "completed"),
        ("cancel_order", {"risk": "HIGH"}, "escalated"),
        ("refund", {}, "completed"),
        ("refund", {"amount": 10000}, "completed"),
        ("refund", {"amount": 10001}, "refused"),
        ("refund", {"payment": "FAILED"}, "refused"),
        ("refund", {"risk": "HIGH"}, "escalated"),
        ("refund", {"payment": "PARTIALLY_REFUNDED", "refunded": 2000}, "completed"),
        ("shipment_investigation", {"shipment": "FAILED"}, "escalated"),
        ("ticket", {}, "escalated"),
        ("composite", {}, "completed"),
        ("composite", {"shipment": "SHIPPED"}, "escalated"),
        ("modify_address", {"faults": {"get_order": ["timeout"]}}, "completed"),
        ("refund", {"faults": {"issue_refund": ["response_lost"]}}, "completed"),
        ("modify_address", {"wrong_customer": True}, "refused"),
    ]
    tasks = []
    for repeat in range(repeats):
        for index, (family, fixture, outcome) in enumerate(cases):
            address = f"{split} New street {100 + repeat} City"
            params = {"order_id": "O1"}
            if family in {"modify_address", "composite"}:
                params["new_address"] = "bad" if fixture.get("invalid_address") else address
            if family == "refund":
                params["amount"] = fixture.get("amount", 3000)
            state, unchanged = {}, ["order.shipping_address", "order.status", "payment.refunded_amount"]
            if outcome == "completed":
                if family in {"modify_address", "composite"}:
                    state["order.shipping_address"] = address
                    unchanged.remove("order.shipping_address")
                elif family == "cancel_order":
                    state["order.status"] = "CANCELLED"
                    unchanged.remove("order.status")
                elif family == "refund":
                    state["payment.refunded_amount"] = fixture.get("refunded", 0) + params["amount"]
                    unchanged.remove("payment.refunded_amount")
            request = f"{family}: {json.dumps(params)}"
            if family == "composite":
                request = f"Change address to {address} if eligible; otherwise create a manual ticket. Order O1."
            tasks.append(Task(task_id=f"{split}-{repeat}-{index}", family=family, request=request,
                customer_id="OTHER" if fixture.get("wrong_customer") else "C1", parameters=params,
                split=split, template_id=f"smoke-{index}", seed=repeat,
                fixture=fixture, expected=ExpectedOutcome(allowed_outcomes=[outcome], expected_state=state, unchanged_fields=unchanged)))
    return tasks


def summarize(results):
    total = len(results)
    tools = sum(r["metrics"]["tool_calls"] for r in results)
    attempts = sum(r["metrics"]["skill_calls"] for r in results)
    wrong = sum(e["applicable"] is False for r in results for e in r["skill_events"])
    unknown = sum(e["applicable"] is None for r in results for e in r["skill_events"])
    attributed = bool(results) and all("policy_attempts" in r for r in results)
    associated = sum(e["applicable"] is False and not r["verification"]["task_success"] for r in results for e in r["skill_events"])
    return {"tasks": total, "task_success_rate": sum(r["verification"]["task_success"] for r in results) / total if total else None,
        "attempted_policy_violation_rate": sum(r["verification"]["attempted_policy_violation"] for r in results) / total if total else None,
        "model_attempted_policy_violation_rate": sum(r["policy_attempts"]["model_triggered"] for r in results) / total if attributed else None,
        "automatic_gate_violation_attempt_rate": sum(bool(r["policy_attempts"]["automatic_gate_tool_attempts"]) for r in results) / total if attributed else None,
        "actual_policy_violation_rate": sum(r["verification"]["actual_policy_violation"] for r in results) / total if total else None,
        "invalid_tool_call_rate": sum(e["error"] in {"invalid_tool", "invalid_arguments", "permission_denied", "business_rule_rejected"} for r in results for e in r["tool_audit"]) / tools if tools else None,
        "skill_reuse_attempts": attempts, "wrong_reuse_attempt_rate": wrong / attempts if attempts else None,
        "skill_applicability_precision": sum(e["applicable"] is True for r in results for e in r["skill_events"]) / attempts if attempts else None,
        "skill_reuse_task_rate": sum(bool(r["skill_events"]) for r in results) / total if total else None,
        "unknown_applicability_attempt_rate": unknown / attempts if attempts else None,
        "unknown_applicability_attempts": unknown,
        "wrong_reuse_associated_failure_rate": associated / attempts if attempts else None,
        "causal_negative_transfer_rate": None,
        **{f"average_{key}": statistics.mean(r["metrics"][key] for r in results) if total else None for key in ["tool_calls", "decision_calls", "llm_calls", "tokens", "latency_ms", "gate_tool_calls"]}}


def run_benchmark(model, tasks=None, skills=None, memory=None, verified=True, output_root="results", label="B0"):
    tasks = generate_tasks() if tasks is None else tasks
    if not tasks:
        raise ValueError("benchmark task list must be nonempty")
    run_id = str(uuid.uuid4())
    path = Path(output_root) / run_id
    path.mkdir(parents=True)
    results = []
    from .config import load_config
    (path / "config.json").write_text(json.dumps({"model": model.model, "model_settings": getattr(model, "settings", {}), "label": label, "verified": verified,
        "runtime": load_config(), "skills": [s.model_dump() for s in skills or []],
        "tasks": [t.model_dump() for t in tasks]}, indent=2), encoding="utf-8")
    for task in tasks:
        env = Environment(fixture=task.fixture, faults=task.fixture.get("faults"))
        try:
            results.append(Runtime(model, skills=skills, memory=memory, verified=verified).run(task, env, path / "trajectories"))
        finally:
            env.close()
        with (path / "task_results.jsonl").open("a", encoding="utf-8") as journal:
            journal.write(json.dumps(results[-1]) + "\n")
    summary = {"run_id": run_id, "label": label, "model": model.model,
        "engineering_only": model.model == "scripted-engineering-only", **summarize(results)}
    (path / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    with (path / "errors.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["task_id", "outcome", "errors"])
        for r in results:
            if not r["verification"]["task_success"]:
                writer.writerow([r["task_id"], r["outcome"], json.dumps(r["error_categories"])])
    return summary, results
