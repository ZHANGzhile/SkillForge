import json
import time
import uuid
from pathlib import Path

from .environment import ToolError
from .policies import POLICY_VERSION, TOOLS, MUTATIONS
from .verifier import verify
from .tool_schemas import tool_definitions
from .retrieval import retrieve_memory
from .config import load_config
from .logging import event as log_event
from .errors import classify_errors
from .dataset import task_hash, digest

POLICY_TEXT = ("Identity is fixed by runtime. Missing observations must first be read with tools; missing is not an observed UNKNOWN state. "
    "All business mutations: customer.risk_level=HIGH requires escalation. "
    "Address/cancel only: shipment.status in SHIPPED/DELIVERED means refuse; otherwise require order.status=CONFIRMED AND shipment.status=NOT_STARTED. "
    "Other observed address/cancel states (including shipment.status=PROCESSING) require escalation. Already CANCELLED orders need no new cancellation, subject to risk/shipment checks. "
    "Address only: trimmed string length must be 8..300; otherwise refuse. "
    "Refund only: payment.status must be CAPTURED or PARTIALLY_REFUNDED, and amount must be a positive integer <= payment.captured_amount - payment.refunded_amount; otherwise refuse. "
    "Shipment status is NOT a refund eligibility condition. Cancellation does not authorize refund. "
    "After a successful mutation, read its resulting state to verify before stop. Do not repeat a successful mutation.")


class Runtime:
    def __init__(self, model, max_steps=None, retry_budget=None, skills=None, memory=None, verified=True):
        config = load_config()
        self.model = model
        self.max_steps = config["max_steps"] if max_steps is None else max_steps
        self.retry_budget = config["retry_budget"] if retry_budget is None else retry_budget
        self.top_k = config.get("retrieval_top_k", 3)
        self.skills, self.memory, self.verified = skills or [], memory or [], verified

    def run(self, task, env, output_dir=None, on_event=None, cancelled=None):
        start = time.perf_counter()
        trajectory_id = str(uuid.uuid4())
        log_event("task_started", trajectory_id=trajectory_id, task_id=task.task_id, model_version=self.model.model)
        initial = env.snapshot(task.parameters.get("order_id", "O1"))
        state, steps, skill_events = {}, [], []
        gate_observations, exhausted = [], set()
        outcome = "max_steps_exceeded"
        llm_calls, gate_calls = 0, 0
        audit_origin, blocked_policy_attempts = "gate", 0
        tokens_before = self.model.tokens
        emit = on_event or (lambda kind, payload: None)
        is_cancelled = cancelled or (lambda: False)
        emit("started", {"trajectory_id": trajectory_id, "initial_state": initial})

        def call(name, args, key):
            logical = digest([name, args])
            if logical in exhausted:
                raise ToolError("retry_budget_exhausted")
            # A single task authorizes one occurrence of the same mutation payload.
            # Skill fallback and primitive retries must reuse that operation identity.
            if name in MUTATIONS:
                key = f"{trajectory_id}:mutation:{logical}"
            for retry in range(self.retry_budget + 1):
                if is_cancelled():
                    raise ToolError("run_cancelled")
                before_audit = len(env.audit)
                try:
                    result = env.call(name, args, task.customer_id, key)
                    state.update({k: v for k, v in result.items() if "." in k})
                    return result
                except ToolError as exc:
                    if exc.code not in {"timeout", "temporary_unavailable"} or retry == self.retry_budget:
                        if exc.code in {"timeout", "temporary_unavailable"}:
                            exhausted.add(logical)
                        raise
                finally:
                    for entry in env.audit[before_audit:]:
                        entry["decision_origin"] = audit_origin
                        emit("tool", entry)

        for step_id in range(self.max_steps):
            if is_cancelled():
                outcome = "cancelled"
                break
            executable = []
            if self.skills:
                from .skills import gate, hydrate
                for skill in [s for s in self.skills if s.family == task.family][:self.top_k]:
                    if self.verified and skill.status != "VERIFIED":
                        continue
                    if self.verified:
                        audit_origin = "gate"
                        before_calls = len(env.audit)
                        try:
                            hydrate(skill, state, task.parameters, call, f"{trajectory_id}:gate:{step_id}")
                        except ToolError as exc:
                            gate_observations.append({"skill_id": skill.skill_id, "error": exc.code,
                                "stage": "applicability_state_read", "retry_exhausted": exc.code in {"timeout", "temporary_unavailable", "retry_budget_exhausted"}})
                        gate_calls += len(env.audit) - before_calls
                        decision = gate(skill, state, task.parameters)
                        if decision.status != "APPLICABLE":
                            continue
                    executable.append(skill.model_dump(exclude={"statistics", "source_trajectory_ids"}))
            context = {"request": task.request, "family": task.family, "parameters": task.parameters,
                "workflow": task.workflow,
                "gate_observations": gate_observations[-8:],
                "policy": POLICY_TEXT, "observations": dict(state), "history": [{k: v for k, v in s.items() if k != "context"} for s in steps[-8:]],
                "available_tools": tool_definitions(), "executable_skills": executable,
                "retrieved_memory": retrieve_memory(task.request, task.family, self.memory) if self.memory else []}
            # Persist exact model-visible context separately from environment snapshots.
            step = {"step_id": step_id, "context": json.loads(json.dumps(context)), "action": None}
            if is_cancelled():
                outcome = "cancelled"
                break
            llm_calls += 1
            emit("decision_started", {"step_id": step_id})
            try:
                action = self.model.decide(context)
                audit_origin = "model_tool"
                step["action"] = action.model_dump()
                if is_cancelled():
                    raise ToolError("run_cancelled")
                if action.type == "stop":
                    outcome = "completed"
                elif action.type == "refuse":
                    outcome = "refused"
                elif action.type == "escalate":
                    step["result"] = call("escalate_to_human", {**action.arguments, "order_id": task.parameters.get("order_id", "O1")}, f"{trajectory_id}:{step_id}")
                    outcome = "escalated"
                elif action.type == "tool":
                    step["result"] = call(action.name, action.arguments, f"{trajectory_id}:{step_id}")
                elif action.type == "skill":
                    audit_origin = "model_skill"
                    from .skills import execute
                    selected = next((s for s in self.skills if s.skill_id == action.name and any(e["skill_id"] == s.skill_id for e in executable)), None)
                    if selected is None:
                        known = next((s for s in self.skills if s.skill_id == action.name), None)
                        from .skills import gate
                        disposition = gate(known, state, action.arguments).status if known else "INAPPLICABLE"
                        if known is not None and disposition == "INAPPLICABLE":
                            blocked_policy_attempts += 1
                        skill_events.append({"skill_id": action.name, "skill_version": known.version if known else None,
                            "applicable": None if disposition == "UNKNOWN" else disposition == "APPLICABLE",
                            "gate_status": disposition, "blocked": True, "success": False, "internal_steps": []})
                        raise ToolError("skill_not_executable")
                    if any(action.arguments.get(k) != task.parameters.get(k) for k in selected.inputs):
                        raise ToolError("skill_input_binding_mismatch")
                    event = execute(selected, action.arguments, state, call, f"{trajectory_id}:skill:{step_id}", self.verified)
                    skill_events.append(event)
                    step["result"] = event
                steps.append(step)
                emit("step", step)
                if action.type in {"stop", "refuse", "escalate"}:
                    break
            except ToolError as exc:
                step["error"] = exc.code
                steps.append(step)
                emit("step", step)
                if exc.code == "run_cancelled":
                    outcome = "cancelled"
                    break
            except Exception as exc:
                step["error"] = "model_or_runtime_error"
                step["error_detail"] = str(exc)[:500]
                steps.append(step)
                emit("step", step)
                outcome = "error"
                break
        final = env.snapshot(task.parameters.get("order_id", "O1"))
        verification = verify(task, initial, final, env.audit, outcome)
        model_tool_attempts = sum(bool(e["attempted_policy_violation"]) for e in env.audit if e.get("decision_origin") in {"model_tool", "model_skill"})
        gate_attempts = sum(bool(e["attempted_policy_violation"]) for e in env.audit if e.get("decision_origin") == "gate")
        result = {"trajectory_id": trajectory_id, "task_id": task.task_id, "task_family": task.family,
            "split": task.split, "template_id": task.template_id, "seed": task.seed,
            "dataset_id": task.dataset_id, "task_hash": task_hash(task), "instance_id": task.instance_id,
            "structure_id": task.structure_id, "level": task.level, "parameters": task.parameters,
            "policy_version": POLICY_VERSION, "model": self.model.model, "user_request": task.request,
            "model_settings": getattr(self.model, "settings", {}),
            "initial_state": initial, "steps": steps, "tool_audit": env.audit, "skill_events": skill_events,
            "gate_observations": gate_observations,
            "final_state": final, "outcome": outcome, "verification": verification,
            "policy_attempts": {"model_triggered": bool(model_tool_attempts or blocked_policy_attempts),
                "model_triggered_tool_attempts": model_tool_attempts, "blocked_inapplicable_skill_calls": blocked_policy_attempts,
                "automatic_gate_tool_attempts": gate_attempts,
                "scope": "agent-selected tools/skills separated from automatic gate reads; legacy verifier includes all tool failures"},
            "metrics": {"tool_calls": len(env.audit), "skill_calls": len(skill_events), "decision_calls": llm_calls,
                "llm_calls": 0 if self.model.model == "scripted-engineering-only" else llm_calls,
                "gate_tool_calls": gate_calls, "tokens": self.model.tokens - tokens_before,
                "latency_ms": (time.perf_counter() - start) * 1000}}
        result["error_categories"] = classify_errors(result)
        emit("finished", {"outcome": outcome, "verification": verification, "metrics": result["metrics"]})
        if output_dir:
            path = Path(output_dir)
            path.mkdir(parents=True, exist_ok=True)
            (path / f"{trajectory_id}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        log_event("task_finished", trajectory_id=trajectory_id, task_id=task.task_id,
            model_version=self.model.model, outcome=outcome, task_success=verification["task_success"])
        return result
