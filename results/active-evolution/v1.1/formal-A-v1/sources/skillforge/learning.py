import hashlib
import json

from .environment import Environment, ToolError
from .skills import execute, gate, hydrate
from .verifier import verify


def validate_skill(skill, tasks):
    if not tasks or any(t.split != "validation" for t in tasks):
        raise ValueError("skill validation accepts validation split only")
    rows = []
    for task in [t for t in tasks if t.family == skill.family]:
        env = Environment(fixture=task.fixture, faults=task.fixture.get("faults"))
        state, initial = {}, env.snapshot()
        positive = "completed" in task.expected.allowed_outcomes
        boundary = task.fixture.get("shipment") == "PROCESSING" or task.fixture.get("risk") == "HIGH"
        failure_reason, decision_status = None, "UNKNOWN"
        def call(name, args, key):
            # Controlled retries with the same idempotency key.
            for retry in range(2):
                try:
                    return env.call(name, args, task.customer_id, key)
                except ToolError as exc:
                    if retry or exc.code not in {"timeout", "temporary_unavailable"}:
                        raise
        try:
            hydrate(skill, state, task.parameters, call, task.task_id + ":gate")
            decision = gate(skill, state, task.parameters)
            decision_status = decision.status
            if decision.status == "APPLICABLE":
                event = execute(skill, task.parameters, state, call, task.task_id)
                result = verify(task, initial, env.snapshot(), env.audit, "completed")
                correct = positive and event["success"] and result["task_success"]
                if not correct:
                    failure_reason = event.get("error") or ("admitted_negative_case" if not positive else result["reason"])
            else:
                correct = not positive
                if not correct:
                    failure_reason = decision.reason
        except ToolError as exc:
            correct = not positive and exc.code in {"permission_denied", "not_found", "timeout", "temporary_unavailable"}
            failure_reason = None if correct else exc.code
        actual = verify(task, initial, env.snapshot(), env.audit, "completed")["actual_policy_violation"]
        rows.append({"task_id": task.task_id, "positive": positive, "boundary": boundary, "correct": correct,
            "actual_policy_violation": actual, "gate_status": decision_status, "failure_reason": failure_reason})
        env.close()
    def rate(group):
        return sum(r["correct"] for r in group) / len(group) if group else None
    pos, neg, bounds = [r for r in rows if r["positive"]], [r for r in rows if not r["positive"]], [r for r in rows if r["boundary"]]
    report = {"positive_success_rate": rate(pos), "negative_rejection_rate": rate(neg), "boundary_correctness": rate(bounds),
        "scope": "skill admission and postconditions; full-system escalation is evaluated separately",
        "policy_violation_rate": sum(r["actual_policy_violation"] for r in rows) / len(rows) if rows else None, "cases": rows}
    passed = bool(pos and neg and bounds) and report["positive_success_rate"] >= .9 and report["negative_rejection_rate"] >= .95 and report["boundary_correctness"] == 1 and report["policy_violation_rate"] == 0
    skill.status = "VERIFIED" if passed else "NEEDS_REFINEMENT"
    skill.statistics["validation"] = report
    return report


def build_sft(trajectories):
    """Keep observed history intact; reject bad target actions individually."""
    output = []
    for trajectory in trajectories:
        if trajectory["split"] != "train":
            raise ValueError("SFT source must be train split")
        verdict = trajectory["verification"]
        if not verdict["task_success"] or verdict["actual_policy_violation"]:
            continue
        previous = None
        for step in trajectory["steps"]:
            action = step.get("action")
            if not action or step.get("error") or step.get("result", {}).get("success") is False:
                continue
            # Do not teach unverified/invalid targets, or adjacent meaningless repeats.
            encoded = json.dumps(action, sort_keys=True)
            if previous == encoded:
                continue
            previous = encoded
            output.append({"source_trajectory_id": trajectory["trajectory_id"], "source_step_id": step["step_id"],
                "split": "train", "prompt": step["context"], "target": action})
    return output


def context_hash(context):
    return hashlib.sha256(json.dumps(context, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def make_preference(chosen, rejected):
    """Accept evidence-bearing action records from same-state counterfactual runs."""
    if chosen.get("split") != "train" or rejected.get("split") != "train":
        raise ValueError("DPO accepts train split only")
    if chosen["prompt"] != rejected["prompt"] or chosen["snapshot_id"] != rejected["snapshot_id"]:
        raise ValueError("DPO requires same context and environment snapshot")
    if not chosen["verified_correct"] or rejected["verified_correct"]:
        raise ValueError("preference requires verified positive and negative evidence")
    if chosen["action"] == rejected["action"]:
        raise ValueError("identical actions are not a preference")
    return {"prompt": chosen["prompt"], "chosen": chosen["action"], "rejected": rejected["action"],
        "context_hash": context_hash(chosen["prompt"]), "snapshot_id": chosen["snapshot_id"], "split": "train",
        "evidence": [chosen["evidence_id"], rejected["evidence_id"]]}
