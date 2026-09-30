"""Frozen, resumable, validation-gated refund precedence diagnosis."""
import argparse
from collections import Counter
import copy
import json
from pathlib import Path
import random
import time

from scripts.audit_boundary_study import load_prepared
from scripts.boundary_learning import public_contract
from scripts.boundary_runtime import BoundaryRuntime, POLICY_TEXT
from scripts.coordinator_io import atomic_json
from scripts.evaluate_boundary_repeatability import exact_request, check_exact
from scripts.evaluate_boundary_system import validate
from scripts.evaluate_reuse_ablation import create_client, read
from scripts.refund_priority import PriorityClient, render
from skillforge.dataset import digest, task_hash
from skillforge.environment import Environment
from skillforge.evaluation_checkpoints import read_checkpoint, save_checkpoint
from skillforge.jobs import JobStore, Worker
from skillforge.schemas import SkillContract
from skillforge.tool_schemas import tool_definitions
from skillforge.training_data import file_hash

PLAN = "configs/refund-priority.json"


def decision_context(task, skill):
    """Fixed authorized observations, not hidden state or a supplied target action."""
    env = Environment(fixture=task.fixture)
    observations = {}
    try:
        reads = ["get_order", "get_payment" if task.family == "refund" else "get_shipment", "get_customer"]
        if task.family == "modify_address":
            reads.append("validate_address")
        for tool in reads:
            args = {"order_id": task.parameters["order_id"]}
            if tool == "validate_address":
                args["new_address"] = task.parameters["new_address"]
            observations.update(env.call(tool, args, task.customer_id))
        audit = [{k: v for k, v in e.items() if k != "latency_ms"} for e in env.audit]
    finally:
        env.close()
    return {"request": task.request, "family": task.family, "parameters": task.parameters,
        "observations": observations, "history": [], "policy": POLICY_TEXT, "workflow": task.workflow,
        "available_tools": tool_definitions(), "executable_skills": [public_contract(skill)], "retrieved_memory": [],
        "evaluation_instruction": "This is a fixed-candidate decision probe. Choose the listed skill, refuse, or escalate. Candidate presence does not imply eligibility."}, audit


def prepare():
    plan = read(PLAN)
    source, parent, all_tasks, boundaries, preparation = load_prepared(plan["source_plan"])
    tasks = {t.task_id: t for t in all_tasks if t.split == "validation" or (t.split == "test" and t.family == "refund")}
    inputs, jobs = {}, {}
    contracts = {f: SkillContract.model_validate(c) for f, c in boundaries["groups"]["B"].items()}
    for tid, task in tasks.items():
        stage = "validation" if task.split == "validation" else "diagnostic"
        context, setup = decision_context(task, contracts[task.family])
        for arm in plan["arms"]:
            user_json = json.dumps(render(context, arm), ensure_ascii=False)
            h = digest(user_json)
            inputs[h] = {"user_json": user_json, "original_context": context, "setup_audit": setup}
            for rep in range(plan[stage + "_repeats"]):
                for kind in ("system", "decision"):
                    jobs[f"{stage}-{kind}-{tid}-{arm}-{rep}"] = {"stage": stage, "kind": kind, "task": tid,
                        "arm": arm, "repeat": rep, **({"input": h} if kind == "decision" else {})}
    files = [PLAN, "docs/REFUND_PRIORITY_PLAN.md", "scripts/refund_priority.py", "scripts/evaluate_refund_priority.py",
        "scripts/boundary_representation.py", "scripts/evaluate_boundary_repeatability.py", "scripts/audit_boundary_study.py",
        "scripts/evaluate_boundary_system.py", "scripts/boundary_runtime.py", "scripts/evaluate_reuse_ablation.py",
        source["reference"], source["client_profile"], str(parent / "preparation.json"), str(parent / "boundaries.json")]
    frozen = {"version": plan["version"], "inputs": inputs, "jobs": jobs,
        "files": {p.replace("\\", "/"): file_hash(p) for p in files}, "core_hash": preparation["core_hash"],
        "task_hashes": {tid: task_hash(t) for tid, t in tasks.items()}, "execution_contracts": boundaries["groups"]["B"],
        "model_settings": read(source["reference"])["model_settings"],
        "order": {stage: sorted((k for k, j in jobs.items() if j["stage"] == stage), key=lambda k: digest([plan["seed"], k]))
                  for stage in ("validation", "diagnostic")}}
    return plan, source, Path(plan["output"]), tasks, boundaries, frozen


def progress(root, stage, done, total, **extra):
    value = {"stage": stage, "completed": done, "total": total, "at": time.time(), **extra}
    atomic_json(root / "progress.json", value)
    Path("docs/REFUND_PRIORITY_LIVE.md").write_text("# 退款优先级实验实时记录\n\n```json\n" + json.dumps(value, ensure_ascii=False, indent=2) + "\n```\n", encoding="utf-8")


def freeze():
    _, _, root, _, _, frozen = prepare()
    if root.exists():
        raise ValueError("existing freeze; refusing overwrite")
    root.mkdir(parents=True)
    atomic_json(root / "freeze.json", frozen)
    progress(root, "frozen", 0, len(frozen["jobs"]))
    return {"jobs": len(frozen["jobs"]), "freeze_sha256": file_hash(root / "freeze.json")}


def decision_score(action, task, skill):
    target = {"completed": "skill", "refused": "refuse", "escalated": "escalate"}[task.expected.allowed_outcomes[0]]
    return {"target": target, "correct": bool(action and action["type"] == target and
            (target != "skill" or action["name"] == skill.skill_id and action["arguments"] == task.parameters))}


def validate_row(row, job, frozen, source, tasks, boundaries):
    task = tasks[job["task"]]
    if job["kind"] == "decision":
        check_exact(row, job, frozen, source)
        skill = SkillContract.model_validate(frozen["execution_contracts"][task.family])
        if row["score"] != decision_score(row["action"], task, skill) or row["target_task_id"] != task.task_id:
            raise ValueError("fixed-candidate verdict differs")
        return
    original = copy.deepcopy(row)
    original["boundary_experiment"]["actual_model_inputs"] = [s["context"] for s in row["steps"]]
    validate(original, task, "B", "autonomous", boundaries, {"model_settings": frozen["model_settings"]})
    expected = [render(s["context"], job["arm"]) for s in row["steps"]]
    if row["boundary_experiment"]["actual_model_inputs"] != expected or row["priority_view"] != {
            "arm": job["arm"], "actual_user_messages": [json.dumps(s, ensure_ascii=False) for s in expected]}:
        raise ValueError("actual priority model input differs")


def summary(rows, frozen, stage, tasks, plan):
    scenarios = {}
    for tid, task in sorted(tasks.items()):
        if ("validation" if task.split == "validation" else "diagnostic") != stage:
            continue
        scenarios[tid] = {"structure_id": task.structure_id, "normal": task.expected.allowed_outcomes == ["completed"]}
        for arm in plan["arms"]:
            selected = {kind: [r for k, r in rows.items() if frozen["jobs"][k]["task"] == tid and
                frozen["jobs"][k]["arm"] == arm and frozen["jobs"][k]["kind"] == kind] for kind in ("system", "decision")}
            system, decisions = selected["system"], selected["decision"]
            scenarios[tid][arm] = {"system_runs": len(system), "success": sum(r["verification"]["task_success"] for r in system),
                "normal_success": sum(r["verification"]["task_success"] for r in system) if scenarios[tid]["normal"] else 0,
                "normal_runs": len(system) if scenarios[tid]["normal"] else 0,
                "actual_violations": sum(r["verification"]["actual_policy_violation"] for r in system),
                "model_attempts": sum(r["policy_attempts"]["model_triggered_tool_attempts"] +
                    r["policy_attempts"]["blocked_inapplicable_skill_calls"] for r in system),
                "blocked_writes": sum(e["error"] == "business_rule_rejected" for r in system for e in r["tool_audit"]),
                "skill_attempts": sum(len(r["skill_events"]) for r in system),
                "outcomes": dict(Counter(r["outcome"] for r in system)),
                **{m: sum(r["metrics"][m] for r in system) for m in ("llm_calls", "tokens", "tool_calls", "gate_tool_calls")},
                "decision_runs": len(decisions), "correct": sum(r["score"]["correct"] for r in decisions),
                "decision_actions": dict(Counter(r["action"]["type"] if r["action"] else "invalid" for r in decisions)),
                "decision_tokens": sum(r["response"].get("usage", {}).get("total_tokens", 0) for r in decisions),
                "decision_setup_tools": sum(len(frozen["inputs"][frozen["jobs"][k]["input"]]["setup_audit"]) for k in rows
                    if frozen["jobs"][k]["task"] == tid and frozen["jobs"][k]["arm"] == arm and frozen["jobs"][k]["kind"] == "decision")}
    numeric = [k for k, v in next(iter(scenarios.values()))["control"].items() if isinstance(v, (int, float))]
    totals = {arm: {m: sum(s[arm][m] for s in scenarios.values()) for m in numeric} for arm in plan["arms"]}
    paired = {}
    for metric, denom in (("success", "system_runs"), ("correct", "decision_runs")):
        deltas = {tid: s["priority"][metric] / s["priority"][denom] - s["control"][metric] / s["control"][denom] for tid, s in scenarios.items()}
        values, rng = list(deltas.values()), random.Random(plan["seed"])
        samples = sorted(sum(rng.choices(values, k=len(values))) / len(values) for _ in range(plan["bootstrap_samples"]))
        paired[metric] = {"scenario_deltas": deltas, "independent_scenarios": len(values), "mean_delta": sum(values) / len(values),
            "ci95": [samples[int(len(samples) * .025)], samples[min(len(samples) - 1, int(len(samples) * .975))]],
            "improved": [k for k, v in deltas.items() if v > 0], "regressed": [k for k, v in deltas.items() if v < 0]}
    return {"totals": totals, "scenarios": scenarios, "paired": paired}


def admission(report):
    c, p = (report["totals"][a] for a in ("control", "priority"))
    checks = {m: p[m] >= c[m] for m in ("success", "normal_success", "correct")}
    checks.update(actual_violations=p["actual_violations"] == 0, model_attempts=p["model_attempts"] <= c["model_attempts"])
    return {"admitted": all(checks.values()), "checks": checks, "scope": "research diagnostic admission only; no product deployment"}


def run(audit=False):
    plan, source, root, tasks, boundaries, frozen = prepare()
    if read(root / "freeze.json") != frozen:
        raise ValueError("frozen priority protocol/source changed")
    identity = {"freeze_sha256": file_hash(root / "freeze.json")}
    folder = root / "runs"
    if not audit:
        folder.mkdir(exist_ok=True)
    existing = {p.stem for p in folder.glob("*.json")}
    if existing - set(frozen["jobs"]):
        raise ValueError("unexpected priority checkpoint")
    rows = {}
    for key in sorted(existing):
        job = frozen["jobs"][key]
        row = read_checkpoint(folder / (key + ".json"), {**identity, "key": key}, job.get("input", job["task"]),
            task_hash(tasks[job["task"]]) if job["kind"] == "system" else None)
        validate_row(row, job, frozen, source, tasks, boundaries)
        rows[key] = row
    model, reports, selection = None, {}, None
    for stage in ("validation", "diagnostic"):
        if stage == "diagnostic" and not selection["admitted"]:
            if any(j["stage"] == stage for k, j in frozen["jobs"].items() if k in rows):
                raise ValueError("diagnostic executed without validation admission")
            break
        for key in frozen["order"][stage]:
            if key in rows:
                continue
            if audit:
                raise ValueError("incomplete priority evidence")
            job, row = frozen["jobs"][key], None
            try:
                if model is None:
                    model = create_client(source["client_profile"], frozen["model_settings"])
                task = tasks[job["task"]]
                skill = SkillContract.model_validate(frozen["execution_contracts"][task.family])
                if job["kind"] == "decision":
                    row = exact_request(model, frozen["inputs"][job["input"]]["user_json"])
                    row.update(target_task_id=task.task_id, score=decision_score(row["action"], task, skill))
                else:
                    client, env = PriorityClient(model, job["arm"]), Environment(fixture=task.fixture, faults=task.fixture.get("faults"))
                    try:
                        row = BoundaryRuntime(client, max_steps=source["max_steps"], retry_budget=source["retry_budget"], skills=[skill]).run(task, env)
                    finally:
                        env.close()
                    row["boundary_experiment"]["actual_model_inputs"] = client.inputs
                    row["priority_view"] = {"arm": job["arm"], "actual_user_messages": client.messages}
                    if model.fatal_error:
                        raise RuntimeError(model.fatal_error)
                validate_row(row, job, frozen, source, tasks, boundaries)
            except Exception as exc:
                atomic_json(root / ("infrastructure-failure-" + str(time.time_ns()) + ".json"), {"key": key, "error": str(exc), "partial": row})
                progress(root, "stopped", len(rows), len(frozen["jobs"]), last_key=key)
                raise
            rows[key] = save_checkpoint(folder / (key + ".json"), row, {**identity, "key": key})
            progress(root, stage, len(rows), len(frozen["jobs"]), last_key=key)
        reports[stage] = summary(rows, frozen, stage, tasks, plan)
        if stage == "validation":
            selection = {**admission(reports[stage]), "validation_sha256": digest(reports[stage]), **identity}
            if (root / "selection.json").exists() and read(root / "selection.json") != selection:
                raise ValueError("priority validation selection changed")
            if not audit:
                atomic_json(root / "selection.json", selection)
    for tid in tasks:
        starts = [digest([r["boundary_experiment"]["fork"], json.dumps(r["steps"][0]["context"], ensure_ascii=False)])
                  for k, r in rows.items() if frozen["jobs"][k]["kind"] == "system" and frozen["jobs"][k]["task"] == tid]
        if starts and len(set(starts)) != 1:
            raise ValueError("paired full-system initial context/fork differs")
    result = {"scope": plan["scope"], "selection": selection, "reports": reports}
    completed = {**identity, "runs": {k: file_hash(folder / (k + ".json")) for k in sorted(rows)}}
    if audit:
        if read(root / "report.json") != result or read(root / "completed.json") != completed or read(root / "selection.json") != selection:
            raise ValueError("priority report/completion differs")
    else:
        atomic_json(root / "report.json", result)
        atomic_json(root / "completed.json", completed)
        progress(root, "completed" if selection["admitted"] else "rejected", len(rows), len(frozen["jobs"]))
    return {"passed": True, "runs": len(rows), "admitted": selection["admitted"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    for arg in ("freeze", "run", "audit"):
        group.add_argument("--" + arg, action="store_true")
    args = parser.parse_args()
    lock = None
    try:
        if not args.audit:
            lock = Worker(JobStore(".runtime/refund-priority-lock"), lambda *_: None)
            lock.start()
        print(json.dumps(freeze() if args.freeze else run(audit=args.audit)))
    finally:
        if lock:
            lock.close()
