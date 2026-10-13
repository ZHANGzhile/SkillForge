"""Private full-task opportunity oracle, executed only in isolated SQLite forks.

Independent Task.expected precedes candidates. No family/name relevance labels.
This first P1 protocol evaluates opportunities at the declared initial snapshot,
not arbitrary partial workflow subgoals. Nothing here enters the model worker.
"""
from pathlib import Path

from skillforge.environment import ToolError
from skillforge.evolution_common.artifacts import clone
from skillforge.evolution_common.snapshot import restore_snapshot
from skillforge.evolution_schemas import fingerprint
from skillforge.execution_aware.contracts import ExecutionContract
from skillforge.schemas import SkillContract
from skillforge.skills import execute, hydrate, gate
from skillforge.verifier import verify


def evaluate_opportunities(task, catalog, snapshot, output, identity):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    results = []
    for index, entry in enumerate(catalog.entries()):
        if entry["contract"]["status"] != "VERIFIED":
            continue
        ref = {"skill_id": entry["skill_id"], "revision": entry["revision"]}
        row = {**ref, "eligible": False, "status": None, "snapshot_ref": str(Path(snapshot).resolve()),
               "provenance": "private_independent_goal_and_sandbox_execution", "scope": "initial_full_task_completion"}
        skill = SkillContract.model_validate(entry["contract"])
        # The goal comes from a separately declared task, never from the candidate.
        if ("completed" not in task.expected.allowed_outcomes or not task.expected.expected_state
                or not set(task.expected.expected_state) <= set(skill.postconditions)):
            row["status"] = "GOAL_NOT_COVERED"
            results.append(row)
            continue
        if any(k not in task.parameters for k in skill.inputs):
            row["status"] = "INPUTS_UNAVAILABLE"
            results.append(row)
            continue
        env, saved, _ = restore_snapshot(snapshot, output / f"{index}.sqlite", identity)
        try:
            prior = ExecutionContract.restore(saved["execution_contract"], task.task_id)
            if prior.pending():
                row["status"] = "PENDING_COMMIT_OR_VERIFICATION"
                results.append(row)
                continue
            initial, state = env.snapshot(), clone(saved["state"])
            if all(initial.get(k) == v for k, v in task.expected.expected_state.items()):
                row["status"] = "GOAL_ALREADY_SATISFIED"
                results.append(row)
                continue
            audit_start = len(env.audit)
            tracker = ExecutionContract(task.task_id)
            def dispatch(name, args, key):
                return env.call(name, args, task.customer_id, key)
            def call(name, args, key):
                return tracker.call(dispatch, name, args, key, source="skill")
            inputs = {k: task.parameters[k] for k in skill.inputs}
            row["gate_before_reads"] = gate(skill, state, inputs).model_dump()
            try:
                hydrate(skill, state, inputs, call, "opportunity:hydrate")
                row["gate_after_reads"] = gate(skill, state, inputs).model_dump()
                event = execute(skill, inputs, state, call, "opportunity:execute")
                verdict = verify(task, initial, env.snapshot(), env.audit[audit_start:], "completed")
                row.update(execution=event, verification=verdict,
                           verification_receipts=[r.to_dict() for r in tracker.receipts],
                           tool_audit=clone(env.audit[audit_start:]))
                row["eligible"] = bool(event["success"] and verdict["task_success"] and
                                       not verdict["attempted_policy_violation"] and not tracker.pending())
                row["status"] = ("ELIGIBLE" if row["eligible"] else
                                 "GATE_" + event["gate_status"] if event["gate_status"] != "APPLICABLE" else
                                 "EXECUTION_OR_GOAL_FAILED")
                if event.get("error") in {"timeout", "temporary_unavailable"} or tracker.pending():
                    row.update(status="INCONCLUSIVE_EXECUTION", eligible=False)
            except ToolError as exc:
                row.update(status="INCONCLUSIVE_EXECUTION", error=exc.code,
                           tool_audit=clone(env.audit[audit_start:]))
        finally:
            env.close()
        results.append(row)
    return {"schema": "independent-opportunities-v1", "task_id": task.task_id,
            "task_spec_hash": fingerprint(task.model_dump()), "catalog_hash": catalog.hash,
            "scope": "fixed initial snapshot; complete independently declared task goal only; no family relevance",
            "opportunities": results, "eligible_count": sum(r["eligible"] for r in results)}


def selection_funnel(agent, opportunities, verdict):
    """Task/revision counts, not step counts; preserve both subsets and all-task EOC."""
    traces = [s["selection_trace"] for s in agent["steps"]]
    def contains(values, ref):
        return any(v["skill_id"] == ref["skill_id"] and v["revision"] == ref["revision"] for v in values)
    eligible = [r for r in opportunities["opportunities"] if r["eligible"]]
    rows = []
    for ref in eligible:
        searched = bool(agent["search_events"])
        retrieved = any(contains(e["results"], ref) for e in agent["search_events"])
        loaded = (any(contains(t["loaded"], ref) for t in traces) or
                  any(e["arguments"] == {"skill_id": ref["skill_id"], "revision": ref["revision"]} for e in agent["load_events"]))
        applicable = any(contains([v for v in t["gate_status"] if v["status"] == "APPLICABLE"], ref) or
                         (t["executed_skill"] and contains([t["executed_skill"]], ref) and
                          t["executed_skill"]["gate_status"] == "APPLICABLE") for t in traces)
        offered = any(contains(t["offered_to_model"], ref) for t in traces)
        selected = any(t["selected_action"].get("type") == "skill" and
                       t["selected_action"].get("name") == ref["skill_id"] and contains(t["loaded"], ref) for t in traces)
        executed = any(t["executed_skill"] and contains([t["executed_skill"]], ref) for t in traces)
        verified = any(t["executed_skill"] and contains([t["executed_skill"]], ref) and
                       t["executed_skill"]["success"] and t["verification_result"] for t in traces)
        labels = []
        if not searched: labels.append("NO_SEARCH")
        elif not retrieved: labels.append("RETRIEVAL_MISS")
        if retrieved and not loaded: labels.append("NOT_LOADED")
        for t in traces:
            if contains(t["loaded"], ref) and t["selected_action"].get("name") == ref["skill_id"]:
                labels.extend(t["error_labels"])
        if offered and not selected: labels.append("OFFERED_NOT_SELECTED")
        legal_primitive = bool(verdict["task_success"] and not verdict["attempted_policy_violation"] and
                               not agent["skill_events"])
        if legal_primitive: labels.append("SUCCESSFUL_PRIMITIVE_ALTERNATIVE")
        if (not verdict["task_success"] and "unexpected_outcome" in verdict["reason"] and
                agent["termination_source"] == "model"):
            labels.append("MODEL_TERMINAL_ERROR")
        rows.append({"skill_id": ref["skill_id"], "revision": ref["revision"], "searched": searched,
                     "retrieved": retrieved, "loaded": loaded, "gate_applicable": applicable,
                     "offered": offered, "selected": selected, "executed": executed, "verified": bool(verified),
                     "legal_primitive_alternative": legal_primitive, "error_labels": list(dict.fromkeys(labels)),
                     "primary_cause": "SUCCESSFUL_PRIMITIVE_ALTERNATIVE" if legal_primitive else next(iter(labels), None)})
    counts = {k: sum(r[k] for r in rows) for k in ("searched", "retrieved", "loaded", "gate_applicable",
              "offered", "selected", "executed", "verified", "legal_primitive_alternative")}
    n = len(rows)
    # Separate raw stage counts from a nested organic search funnel. Experimental
    # preloading can legitimately skip search; never silently place it in that chain.
    chain, alive = {"eligible": n}, rows
    for name in ("searched", "retrieved", "loaded", "gate_applicable", "offered", "selected", "executed", "verified"):
        alive = [r for r in alive if r[name]]
        chain[name] = len(alive)
    return {"schema": "selection-funnel-v1", "private_evaluator_only": True,
            "unit": "task_revision_at_initial_snapshot", "eligible": n, "raw_counts": counts,
            "organic_funnel": chain, "recall_at_k": counts["retrieved"] / n if n else None,
            "conditional_selection_rate": counts["selected"] / counts["offered"] if counts["offered"] else None,
            "all_task_eoc": verdict["task_success"], "opportunity_rows": rows,
            "scope": "initial full-task opportunities; rates conditional on these opportunities, not overall efficacy"}
