"""Learn-only public event abstraction and conservative opportunity screening.

No fixture/before_state/after_state/hidden expected values enter a pattern.
This first version supports straight read-only sequences; it never converts
faults into business boundaries or exports a program as VERIFIED.
"""
from collections import defaultdict

from ..evolution_schemas import fingerprint
from ..policies import READS
from .workflows import WorkflowCase, GOALS


def normalize_calls(parameters, audit, trajectory_id):
    events = []
    for index, event in enumerate(audit):
        arguments = {}
        for key, value in event["arguments"].items():
            matches = [name for name, supplied in parameters.items() if fingerprint(value) == fingerprint(supplied)]
            if len(matches) != 1:
                raise ValueError("argument has no unique public input binding")
            arguments[key] = "$input." + matches[0]
        origin = event.get("decision_origin")
        if origin not in {"model", "skill", "runtime", "gate/hydrate"}:
            raise ValueError("unknown or scripted event origin")
        events.append({"tool": event["tool_name"], "arguments": arguments, "origin": origin,
                       "error": event["error"], "observed_fields": sorted((event.get("result") or {}).keys()),
                       "source": {"trajectory_id": trajectory_id, "audit_index": index},
                       "result_hash": fingerprint(event.get("result"))})
    return events


def normalize_trajectory(row, model_identity):
    case = WorkflowCase.model_validate(row["case"])
    if case.split != "train":
        raise ValueError("experience abstraction accepts learn/train only")
    agent = row["agent"]
    if (model_identity.get("engineering_only") is not False or agent["metrics"]["llm_calls"] <= 0 or
            agent["metrics"]["llm_calls"] != len(agent["model_requests"])):
        raise ValueError("real model evidence required; scripted trajectories cannot teach")
    if row["model_identity_hash"] != fingerprint(model_identity) or row["verification"]["goal_hash"] != case.goal_hash:
        raise ValueError("experience identity mismatch")
    for step in agent["steps"]:
        if len(step.get("messages", [])) != 2 or step["messages"][0]["content"] != model_identity["system_prompt"]:
            raise ValueError("missing exact model messages")
        import json
        context = step["context"]
        if json.loads(step["messages"][1]["content"]) != context or {k: context[k] for k in case.public_task()} != case.public_task():
            raise ValueError("model public task mismatch")
        if set(context) & {"fixture", "expected", "verification", "gold", "source_group", "split"}:
            raise ValueError("private evidence in model context")
    normalization_error = None
    try:
        events = normalize_calls(case.parameters, row["tool_audit"], case.task_id)
    except ValueError as exc:
        events, normalization_error = [], str(exc)
    verdict = row["verification"]
    usable = bool(verdict["task_success"] and agent["outcome"] == "completed" and
                  not any(verdict[k] for k in ("attempted_policy_violation", "actual_policy_violation",
                                               "attempted_workflow_violation", "actual_workflow_violation")) and
                  events and all(not e["error"] and e["tool"] in READS for e in events))
    calls = [{"tool": e["tool"], "arguments": e["arguments"]} for e in events]
    pattern = {"goal_hash": case.goal_hash, "inputs": sorted(case.parameters), "calls": calls}
    return {"schema": "normalized-readonly-experience-v1", "trajectory_id": case.task_id,
            "source_group": case.source_group, "split": "train", "workflow_id": case.workflow_id,
            "normalization_error": normalization_error,
            "goal_hash": case.goal_hash, "pattern_id": fingerprint(pattern), "pattern": pattern, "events": events,
            "usable_success": usable, "model_calls": agent["metrics"]["llm_calls"],
            "tokens": agent["metrics"]["tokens"], "verification": {k: verdict[k] for k in
             ("task_success", "attempted_policy_violation", "actual_policy_violation", "attempted_workflow_violation", "actual_workflow_violation")},
            "raw_trajectory_hash": fingerprint(row), "static_coverage": row["static_coverage"],
            "scope": "read-only sequence abstraction; no write-boundary induction or formal generalization proof"}


def mine_opportunities(rows, model_identity, *, min_sources=3, min_model_call_saving=1):
    normalized = [normalize_trajectory(row, model_identity) for row in rows]
    groups = defaultdict(list)
    for trajectory in normalized:
        if trajectory["usable_success"]:
            groups[trajectory["pattern_id"]].append(trajectory)
    records = []
    for identity, support in sorted(groups.items()):
        sources = sorted({row["source_group"] for row in support})
        calls = support[0]["pattern"]["calls"]
        # Count search + load + Skill execution + stop. A two-read procedure
        # does not become useful just because execution can be scripted.
        expected_skill_decisions = 4
        expected_saving = sum(row["model_calls"] for row in support) / len(support) - expected_skill_decisions
        covered = any(any(item["covers_goal"] for item in row["static_coverage"]) for row in support)
        structure = fingerprint({"inputs": support[0]["pattern"]["inputs"], "calls": calls})
        duplicate_structure = any(any(item.get("program_structure_hash") == structure for item in row["static_coverage"]) for row in support)
        checks = {"novel_program_structure": not duplicate_structure, "independent_sources": len(sources) >= min_sources,
                  "valid_generalization_target": support[0]["goal_hash"] == GOALS[support[0]["workflow_id"]].identity,
                  "expected_incremental_utility": expected_saving >= min_model_call_saving}
        records.append({"schema": "readonly-opportunity-v1", "pattern_id": identity, "pattern": support[0]["pattern"],
                        "source_groups": sources, "trajectory_ids": [row["trajectory_id"] for row in support],
                        "checks": checks, "status": "OPPORTUNITY" if all(checks.values()) else "NO_USEFUL_OPPORTUNITY",
                        "reasons": [key for key, value in checks.items() if not value],
                        "static_goal_covered": covered, "program_structure_hash": structure,
                        "expected_model_call_saving": expected_saving, "expected_skill_decisions": expected_skill_decisions,
                        "nodes": [{**call, "sources": [row["events"][i]["source"] for row in support]}
                                  for i, call in enumerate(calls)],
                        "utility_is_estimate": True, "program_admitted": False, "agent_admitted": False,
                        "scope": "source units are independent entity/seed groups, shared task template; heldout efficacy untested"})
    return {"schema": "readonly-opportunity-screen-v1", "normalized": normalized, "records": records,
            "status": "OPPORTUNITIES_FOUND" if any(r["status"] == "OPPORTUNITY" for r in records) else "NO_USEFUL_OPPORTUNITY",
            "min_sources": min_sources, "min_model_call_saving": min_model_call_saving,
            "excluded_unsuccessful_trajectories": [r["trajectory_id"] for r in normalized if not r["usable_success"]],
            "program_admitted": False, "research_claim_passed": None}
