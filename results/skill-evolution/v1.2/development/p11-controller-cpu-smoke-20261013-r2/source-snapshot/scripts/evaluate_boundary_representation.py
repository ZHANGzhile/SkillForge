"""Frozen paired view intervention with unchanged execution B and real Student."""
import argparse
from collections import Counter
import copy
import json
from pathlib import Path
import time

from scripts.audit_boundary_study import audit_system, load_prepared
from scripts.boundary_representation import ViewClient, equivalent_states, render
from scripts.boundary_runtime import BoundaryRuntime
from scripts.coordinator_io import atomic_json
from scripts.evaluate_boundary_repeatability import exact_request, check_exact
from scripts.evaluate_boundary_system import validate
from scripts.evaluate_reuse_ablation import create_client, read
from skillforge.dataset import digest, task_hash
from skillforge.environment import Environment
from skillforge.evaluation_checkpoints import read_checkpoint, save_checkpoint
from skillforge.jobs import JobStore, Worker
from skillforge.schemas import SkillContract
from skillforge.training_data import file_hash

PLAN = "configs/boundary-representation.json"


def prepare():
    plan = read(PLAN)
    source, parent, tasks, boundaries, preparation = load_prepared(plan["source_plan"])
    rows, _ = audit_system(plan["source_plan"])
    tasks = {t.task_id: t for t in tasks if t.split == "test" and t.family == "refund"}
    base = SkillContract.model_validate(boundaries["groups"]["B"]["refund"])
    inputs, jobs = {}, {}
    for tid in tasks:
        context = rows[tid + "-B-autonomous"]["steps"][0]["context"]
        for arm in plan["arms"]:
            for rep in range(plan["system_repeats"]):
                jobs[f"system-{tid}-{arm}-{rep}"] = {"kind": "system", "task": tid, "arm": arm, "repeat": rep}
            if context["executable_skills"]:
                text = json.dumps(render(context, arm), ensure_ascii=False)
                h = digest(text)
                inputs[h] = {"user_json": text, "runtime_context": context, "task": tid, "arm": arm}
                for rep in range(plan["exact_repeats"]):
                    jobs[f"exact-{tid}-{arm}-{rep}"] = {"kind": "exact", "task": tid, "input": h, "arm": arm, "repeat": rep}
    files = [PLAN, "docs/BOUNDARY_REPRESENTATION_PLAN.md", "scripts/boundary_representation.py",
             "scripts/evaluate_boundary_representation.py", "scripts/evaluate_boundary_repeatability.py",
             "scripts/audit_boundary_study.py", "scripts/evaluate_boundary_system.py", "scripts/boundary_runtime.py", "scripts/evaluate_reuse_ablation.py",
             source["reference"], source["client_profile"], str(parent / "system/completed.json"),
             "results/boundary-repeatability/v1/completed.json", "results/boundary-repeatability/v1/report.json"]
    frozen = {"version": plan["version"], "inputs": inputs, "jobs": jobs, "equivalence": equivalent_states(base),
              "files": {p.replace("\\", "/"): file_hash(p) for p in files}, "core_hash": preparation["core_hash"],
              "task_hashes": {tid: task_hash(t) for tid, t in tasks.items()}, "execution_contract": base.model_dump(),
              "model_settings": read(source["reference"])["model_settings"],
              "order": sorted(jobs, key=lambda k: digest([plan["seed"], k]))}
    return plan, source, Path(plan["output"]), tasks, boundaries, frozen


def progress(root, stage, done, total, **extra):
    value = {"stage": stage, "completed": done, "total": total, "at": time.time(), **extra}
    atomic_json(root / "progress.json", value)
    Path("docs/BOUNDARY_REPRESENTATION_LIVE.md").write_text("# 边界表达对照实时记录\n\n```json\n" + json.dumps(value, ensure_ascii=False, indent=2) + "\n```\n", encoding="utf-8")


def freeze():
    _, _, root, _, _, frozen = prepare()
    if root.exists():
        raise ValueError("freeze exists; refusing overwrite")
    root.mkdir(parents=True)
    atomic_json(root / "freeze.json", frozen)
    progress(root, "frozen", 0, len(frozen["jobs"]))
    return {"jobs": len(frozen["jobs"]), "equivalence": frozen["equivalence"], "sha256": file_hash(root / "freeze.json")}


def validate_row(row, item, frozen, source, tasks, boundaries):
    if item["kind"] == "exact":
        check_exact(row, item, frozen, source)
        return
    # The old validator checks execution B against the original Runtime contexts.
    execution = copy.deepcopy(row)
    execution["boundary_experiment"]["actual_model_inputs"] = [s["context"] for s in row["steps"]]
    validate(execution, tasks[item["task"]], "B", "autonomous", boundaries, {"model_settings": frozen["model_settings"]})
    expected = [render(s["context"], item["arm"]) for s in row["steps"]]
    strings = [json.dumps(s, ensure_ascii=False) for s in expected]
    if row["boundary_experiment"]["actual_model_inputs"] != expected or row["representation"] != {"arm": item["arm"], "actual_user_messages": strings}:
        raise ValueError("recorded model input differs from view intervention")


def run(audit=False):
    plan, source, root, tasks, boundaries, frozen = prepare()
    if read(root / "freeze.json") != frozen:
        raise ValueError("representation freeze/source changed")
    identity = {"freeze_sha256": file_hash(root / "freeze.json")}
    folder = root / "runs"
    if not audit:
        folder.mkdir(exist_ok=True)
    existing = {p.stem for p in folder.glob("*.json")}
    if existing - set(frozen["jobs"]) or (audit and existing != set(frozen["jobs"])):
        raise ValueError("representation checkpoint coverage mismatch")
    rows = {}
    for key in sorted(existing):
        job = frozen["jobs"][key]
        row = read_checkpoint(folder / (key + ".json"), {**identity, "key": key}, job.get("input", job["task"]),
                              task_hash(tasks[job["task"]]) if job["kind"] == "system" else None)
        validate_row(row, job, frozen, source, tasks, boundaries)
        rows[key] = row
    model = None
    for key in frozen["order"]:
        if key in rows:
            continue
        job = frozen["jobs"][key]
        row = None
        try:
            if model is None:
                model = create_client(source["client_profile"], frozen["model_settings"])
            if job["kind"] == "exact":
                row = exact_request(model, frozen["inputs"][job["input"]]["user_json"])
            else:
                task = tasks[job["task"]]
                client = ViewClient(model, job["arm"])
                env = Environment(fixture=task.fixture, faults=task.fixture.get("faults"))
                try:
                    row = BoundaryRuntime(client, max_steps=source["max_steps"], retry_budget=source["retry_budget"],
                        skills=[SkillContract.model_validate(frozen["execution_contract"])], intervention="autonomous").run(task, env)
                finally:
                    env.close()
                row["boundary_experiment"]["actual_model_inputs"] = client.inputs
                row["representation"] = {"arm": job["arm"], "actual_user_messages": client.messages}
                if model.fatal_error:
                    raise RuntimeError(model.fatal_error)
            validate_row(row, job, frozen, source, tasks, boundaries)
        except Exception as exc:
            atomic_json(root / ("infrastructure-failure-" + str(time.time_ns()) + ".json"), {"key": key, "error": str(exc), "partial": row})
            progress(root, "stopped", len(rows), len(frozen["jobs"]), last_key=key)
            raise
        rows[key] = save_checkpoint(folder / (key + ".json"), row, {**identity, "key": key})
        progress(root, "running", len(rows), len(frozen["jobs"]), last_key=key)
    # Both arms must fork from identical B observations and full environment.
    for tid in tasks:
        samples = [rows[k] for k, j in frozen["jobs"].items() if j["kind"] == "system" and j["task"] == tid]
        starts = [digest([r["boundary_experiment"]["fork"], json.dumps(r["steps"][0]["context"], ensure_ascii=False)]) for r in samples]
        if len(set(starts)) != 1:
            raise ValueError("representation arms have different initial runtime contexts/forks")
    completed = {**identity, "runs": {k: file_hash(folder / (k + ".json")) for k in sorted(rows)}}
    result = summarize(rows, frozen, plan, tasks)
    if audit:
        if read(root / "completed.json") != completed or read(root / "report.json") != result:
            raise ValueError("representation report/completion mismatch")
    else:
        atomic_json(root / "completed.json", completed)
        atomic_json(root / "report.json", result)
        progress(root, "completed", len(rows), len(frozen["jobs"]))
    return {"passed": True, "runs": len(rows), "equivalence": frozen["equivalence"]}


def summarize(rows, frozen, plan, tasks):
    exact, system = {}, {}
    for tid, task in sorted(tasks.items()):
        system[tid], exact[tid] = {}, {}
        for arm in plan["arms"]:
            selected = [rows[k] for k, j in frozen["jobs"].items() if j["task"] == tid and j["arm"] == arm and j["kind"] == "system"]
            system[tid][arm] = {"normal": task.expected.allowed_outcomes == ["completed"], "runs": len(selected),
                "success": sum(r["verification"]["task_success"] for r in selected),
                "actual_violations": sum(r["verification"]["actual_policy_violation"] for r in selected),
                "blocked_writes": sum(e["error"] == "business_rule_rejected" for r in selected for e in r["tool_audit"]),
                "skill_attempts": sum(len(r["skill_events"]) for r in selected),
                "outcomes": dict(Counter(r["outcome"] for r in selected)),
                **{m: sum(r["metrics"][m] for r in selected) for m in ("llm_calls", "tokens", "tool_calls", "gate_tool_calls")}}
            selected = [rows[k] for k, j in frozen["jobs"].items() if j["task"] == tid and j["arm"] == arm and j["kind"] == "exact"]
            if selected:
                exact[tid][arm] = {"runs": len(selected), "actions": dict(Counter(json.dumps(r["action"], ensure_ascii=False, sort_keys=True) for r in selected)),
                    "decisions": dict(Counter(r["action"]["type"] + ":" + r["action"]["name"] if r["action"] else "invalid" for r in selected)),
                    "tokens": sum(r["response"].get("usage", {}).get("total_tokens", 0) for r in selected)}
    metrics = ("runs", "success", "actual_violations", "blocked_writes", "skill_attempts", "llm_calls", "tokens", "tool_calls", "gate_tool_calls")
    totals = {a: {m: sum(s[a][m] for s in system.values()) for m in metrics} for a in plan["arms"]}
    for arm in plan["arms"]:
        totals[arm]["normal_success"] = sum(s[arm]["success"] for s in system.values() if s[arm]["normal"])
        totals[arm]["normal_runs"] = sum(s[arm]["runs"] for s in system.values() if s[arm]["normal"])
    return {"scope": plan["scope"], "exact": exact, "system": system, "totals": totals,
            "scenario_deltas": {tid: s["allowlist_view"]["success"] - s["original"]["success"] for tid, s in system.items()}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    for arg in ("freeze", "run", "audit"):
        group.add_argument("--" + arg, action="store_true")
    args = parser.parse_args()
    lock = None
    try:
        if not args.audit:
            lock = Worker(JobStore(".runtime/boundary-representation-lock"), lambda *_: None)
            lock.start()
        print(json.dumps(freeze() if args.freeze else run(audit=args.audit)))
    finally:
        if lock:
            lock.close()
