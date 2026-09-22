from .environment import Environment, ToolError
from .runtime import POLICY_TEXT
from .tool_schemas import tool_definitions


def evaluate_decisions(model, skill, tasks):
    """Fixed candidates include inapplicable skills: gate cannot hide policy errors.

    This probe asks for skill/refusal/escalation after fixed authorized reads;
    it does not claim to measure unrestricted tool-planning correctness.
    """
    rows = []
    for task in [t for t in tasks if t.family == skill.family]:
        if task.level == "D" and task.dataset_id != "smoke-v1":
            rows.append({"task_id": task.task_id, "skipped": True, "reason": "fault_case_requires_full_system"})
            continue
        env, observations = Environment(fixture=task.fixture), {}
        try:
            reads = ["get_order", "get_shipment", "get_customer"]
            if skill.family == "refund":
                reads = ["get_order", "get_payment", "get_customer"]
            if skill.family == "modify_address":
                reads.append("validate_address")
            for tool in reads:
                args = {"order_id": task.parameters["order_id"]}
                if tool == "validate_address":
                    args["new_address"] = task.parameters["new_address"]
                observations.update(env.call(tool, args, task.customer_id))
            context = {"request": task.request, "family": task.family, "parameters": task.parameters,
                "observations": observations, "history": [], "policy": POLICY_TEXT,
                "workflow": task.workflow,
                "available_tools": tool_definitions(), "executable_skills": [skill.model_dump(exclude={"statistics", "source_trajectory_ids"})], "retrieved_memory": [],
                "evaluation_instruction": "This is a fixed-candidate decision probe. Choose the listed skill, refuse, or escalate. Candidate presence does not imply eligibility."}
            action = model.decide(context)
            target = {"completed": "skill", "refused": "refuse", "escalated": "escalate"}[task.expected.allowed_outcomes[0]]
            correct = action.type == target and (target != "skill" or action.name == skill.skill_id and action.arguments == task.parameters)
            rows.append({"task_id": task.task_id, "correct": correct, "target": target, "action": action.model_dump(), "context": context,
                "setup_tool_calls": len(env.audit)})
        except ToolError as exc:
            rows.append({"task_id": task.task_id, "skipped": True, "reason": exc.code})
        except Exception as exc:
            rows.append({"task_id": task.task_id, "correct": False, "error": type(exc).__name__})
        finally:
            env.close()
    evaluated = [r for r in rows if not r.get("skipped")]
    return {"model": model.model, "engineering_only": model.model == "scripted-engineering-only",
        "scope": f"{skill.family} skill/refusal/escalation fixed-candidate probe", "evaluated": len(evaluated),
        "skipped": len(rows) - len(evaluated), "accuracy": sum(r["correct"] for r in evaluated) / len(evaluated) if evaluated else None, "cases": rows}
