"""Independent, frozen retrospective repetition; never rewrites the source study."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import time

import httpx

from scripts.audit_boundary_study import audit_system, load_prepared
from scripts.boundary_runtime import BoundaryRuntime
from scripts.coordinator_io import atomic_json
from scripts.evaluate_boundary_system import validate
from scripts.evaluate_reuse_ablation import create_client, read
from skillforge.dataset import digest, task_hash
from skillforge.environment import Environment
from skillforge.evaluation_checkpoints import read_checkpoint, save_checkpoint
from skillforge.jobs import JobStore, Worker
from skillforge.schemas import Action, SkillContract
from skillforge.training_data import file_hash

PLAN = "configs/boundary-repeatability.json"
SCRIPT = "scripts/evaluate_boundary_repeatability.py"


def select_inputs(rows, aliases, plan):
    clusters = defaultdict(list)
    contexts = {}
    for key, row in sorted(rows.items()):
        if key in aliases:
            continue
        offset = row["boundary_experiment"]["forced_decisions"]
        for index, context in enumerate(row["boundary_experiment"]["actual_model_inputs"]):
            text = json.dumps(context, ensure_ascii=False)
            h = digest(text)
            contexts[h] = text
            clusters[h].append({"run": key, "step": index + offset, "action": row["steps"][index + offset]["action"]})
    repeated = {h: refs for h, refs in clusters.items() if len(refs) > 1}
    divergent = {h for h, refs in repeated.items() if len({digest(r["action"]) for r in refs}) > 1}
    stable = sorted(set(repeated) - divergent)[:plan["stable_controls"]]
    selected = {h: ["historical_divergence"] for h in divergent}
    selected.update({h: ["stable_control"] for h in stable})
    for group in plan["groups"]:
        context = rows[plan["regression_task"] + "-" + group + "-autonomous"]["boundary_experiment"]["actual_model_inputs"][0]
        selected.setdefault(digest(json.dumps(context, ensure_ascii=False)), []).append("regression_initial_" + group)
    return {h: {"user_json": contexts[h], "selection": selected[h], "source_references": clusters[h]} for h in sorted(selected)}


def prepare():
    plan = read(PLAN)
    source, parent, tasks, boundaries, preparation = load_prepared(plan["source_plan"])
    rows, completed = audit_system(plan["source_plan"])
    selected = select_inputs(rows, completed["aliases"], plan)
    normal = {t.task_id: t for t in tasks if t.split == "test" and t.expected.allowed_outcomes == ["completed"]}
    jobs = {}
    for h in selected:
        for repeat in range(plan["exact_repeats"]):
            jobs[f"exact-{h}-{repeat}"] = {"kind": "exact", "input": h, "repeat": repeat}
    for tid in normal:
        for group in plan["groups"]:
            for repeat in range(plan["normal_repeats"]):
                jobs[f"normal-{tid}-{group}-{repeat}"] = {"kind": "normal", "task": tid, "group": group, "repeat": repeat}
    paths = [PLAN, SCRIPT, "docs/BOUNDARY_REPEATABILITY_PLAN.md", plan["source_plan"], source["client_profile"], source["reference"],
             str(parent / "report.json"), str(parent / "system/completed.json"), str(parent / "system/identity.json"),
             "scripts/audit_boundary_study.py", "scripts/evaluate_boundary_system.py", "scripts/boundary_runtime.py",
             "scripts/evaluate_reuse_ablation.py"]
    frozen = {"version": plan["version"], "inputs": selected, "jobs": jobs,
              "order": sorted(jobs, key=lambda key: digest([plan["seed"], key])),
              "files": {p.replace("\\", "/"): file_hash(p) for p in paths}, "core_hash": preparation["core_hash"],
              "normal_tasks": {tid: task_hash(t) for tid, t in normal.items()},
              "model_settings": read(source["reference"])["model_settings"]}
    return plan, source, Path(plan["output"]), normal, boundaries, frozen


def freeze():
    plan, _, root, _, _, frozen = prepare()
    if root.exists():
        raise ValueError("freeze directory already exists; do not overwrite")
    root.mkdir(parents=True)
    atomic_json(root / "freeze.json", frozen)
    progress(root, 0, len(frozen["jobs"]), "frozen")
    return {"inputs": len(frozen["inputs"]), "jobs": len(frozen["jobs"]), "freeze_sha256": file_hash(root / "freeze.json")}


def exact_request(model, user_json):
    request = {"model": model.model, "messages": [{"role": "system", "content": model.system_prompt},
               {"role": "user", "content": user_json}], "temperature": 0, "response_format": {"type": "json_object"}, **model.request_options}
    started = time.time()
    with httpx.Client(timeout=model.timeout, trust_env=False) as client:
        response = client.post(model.url + "/chat/completions", headers={"Authorization": "Bearer " + model.key}, json=request)
    payload = response.json()
    result = {"task_id": digest(user_json), "request": request, "http_status": response.status_code,
              "response": payload, "started_at": started, "elapsed_seconds": time.time() - started,
              "model_settings": model.settings, "action": None}
    if response.status_code == 502 and payload.get("detail", {}).get("error") == "ValidationError":
        result["model_error"] = "server_invalid_action"
        return result
    response.raise_for_status()
    if payload.get("system_fingerprint") != model.expected_fingerprint:
        raise ValueError("private Student changed during exact repetition")
    try:
        result["action"] = Action.model_validate_json(payload["choices"][0]["message"]["content"]).model_dump(mode="json")
    except ValueError:
        result["model_error"] = "client_invalid_action"
    return result


def check_exact(row, item, frozen, source):
    profile = read(source["client_profile"])
    expected_request = {"model": profile["model"], "messages": [{"role": "system", "content": frozen["model_settings"]["system_prompt"]},
        {"role": "user", "content": frozen["inputs"][item["input"]]["user_json"]}], "temperature": 0,
        "response_format": {"type": "json_object"}, **{k: profile[k] for k in ("max_tokens", "reasoning_effort", "seed") if k in profile}}
    if row["request"] != expected_request or row["task_id"] != item["input"] or row["model_settings"]["server_identity"] != frozen["model_settings"]:
        raise ValueError("exact request/identity differs")
    payload = row["response"]
    if row["http_status"] == 502 and payload.get("detail", {}).get("error") == "ValidationError":
        if row["action"] is not None or row.get("model_error") != "server_invalid_action":
            raise ValueError("invalid model failure accounting")
        return
    if row["http_status"] != 200 or payload.get("system_fingerprint") != digest(frozen["model_settings"]):
        raise ValueError("response fingerprint/status differs")
    try:
        expected = Action.model_validate_json(payload["choices"][0]["message"]["content"]).model_dump(mode="json")
    except ValueError:
        if row["action"] is not None or row.get("model_error") != "client_invalid_action":
            raise ValueError("invalid model failure accounting")
    else:
        if row["action"] != expected or row.get("model_error"):
            raise ValueError("response/action differs")


def progress(root, done, total, stage, **extra):
    value = {"stage": stage, "completed": done, "total": total, "at": time.time(), **extra}
    atomic_json(root / "progress.json", value)
    Path("docs/BOUNDARY_REPEATABILITY_LIVE.md").write_text("# 重复性实验实时记录\n\n```json\n" + json.dumps(value, ensure_ascii=False, indent=2) + "\n```\n", encoding="utf-8")


def run(audit=False):
    plan, source, root, tasks, boundaries, frozen = prepare()
    if read(root / "freeze.json") != frozen:
        raise ValueError("frozen protocol/source/input identity changed")
    identity = {"freeze_sha256": file_hash(root / "freeze.json")}
    paths = root / "runs"
    if not audit:
        paths.mkdir(exist_ok=True)
    existing = {p.stem for p in paths.glob("*.json")}
    if existing - set(frozen["jobs"]) or (audit and existing != set(frozen["jobs"])):
        raise ValueError("repetition coverage differs")
    rows = {}
    for key in sorted(existing):
        item = frozen["jobs"][key]
        tid = item.get("task", item.get("input"))
        row = read_checkpoint(paths / (key + ".json"), {**identity, "key": key}, tid,
                              task_hash(tasks[tid]) if item["kind"] == "normal" else None)
        validate_row(row, item, frozen, source, tasks, boundaries)
        rows[key] = row
    model = None
    for key in frozen["order"]:
        if key in rows:
            continue
        item = frozen["jobs"][key]
        try:
            if model is None:
                model = create_client(source["client_profile"], frozen["model_settings"])
            if item["kind"] == "exact":
                row = exact_request(model, frozen["inputs"][item["input"]]["user_json"])
            else:
                task = tasks[item["task"]]
                env = Environment(fixture=task.fixture, faults=task.fixture.get("faults"))
                try:
                    row = BoundaryRuntime(model, max_steps=source["max_steps"], retry_budget=source["retry_budget"],
                        skills=[SkillContract.model_validate(boundaries["groups"][item["group"]][task.family])], intervention="autonomous").run(task, env)
                finally:
                    env.close()
                if model.fatal_error:
                    raise RuntimeError(model.fatal_error)
            validate_row(row, item, frozen, source, tasks, boundaries)
        except Exception as exc:
            atomic_json(root / ("infrastructure-failure-" + str(time.time_ns()) + ".json"), {"key": key, "error": type(exc).__name__, "message": str(exc)})
            progress(root, len(rows), len(frozen["jobs"]), "stopped", last_key=key, error=type(exc).__name__)
            raise
        rows[key] = save_checkpoint(paths / (key + ".json"), row, {**identity, "key": key})
        progress(root, len(rows), len(frozen["jobs"]), "running", last_key=key)
    completed = {**identity, "runs": {key: file_hash(paths / (key + ".json")) for key in sorted(rows)}}
    result = summarize(rows, frozen, plan, tasks)
    if audit:
        if read(root / "completed.json") != completed or read(root / "report.json") != result:
            raise ValueError("completion/report differs from audited records")
    else:
        atomic_json(root / "completed.json", completed)
        atomic_json(root / "report.json", result)
        write_report(result)
        progress(root, len(rows), len(frozen["jobs"]), "completed")
    return {"passed": True, "actual_runs": len(rows), "exact_inputs": len(frozen["inputs"]), "normal_scenarios": len(tasks)}


def validate_row(row, item, frozen, source, tasks, boundaries):
    if item["kind"] == "exact":
        check_exact(row, item, frozen, source)
    else:
        validate(row, tasks[item["task"]], item["group"], "autonomous", boundaries, {"model_settings": frozen["model_settings"]})


def summarize(rows, frozen, plan, tasks):
    exact, normal = {}, {}
    for h, context in frozen["inputs"].items():
        samples = [rows[k] for k, job in frozen["jobs"].items() if job["kind"] == "exact" and job["input"] == h]
        actions = Counter(json.dumps(r["action"], ensure_ascii=False, sort_keys=True) for r in samples)
        decisions = Counter(str(r["action"].get("type")) + ":" + str(r["action"].get("name")) if r["action"] else "invalid" for r in samples)
        historical = {digest(ref["action"]) for ref in context["source_references"]}
        exact[h] = {"selection": context["selection"], "repeats": len(samples), "actions": dict(actions), "decisions": dict(decisions),
                    "historical_actions": len(historical), "new_actions": sum(digest(r["action"]) not in historical for r in samples),
                    "tokens": sum(r["response"].get("usage", {}).get("total_tokens", 0) for r in samples)}
    for tid in sorted(tasks):
        normal[tid] = {}
        for group in plan["groups"]:
            samples = [rows[k] for k, job in frozen["jobs"].items() if job["kind"] == "normal" and job["task"] == tid and job["group"] == group]
            normal[tid][group] = {"success": sum(r["verification"]["task_success"] for r in samples), "runs": len(samples),
                "outcomes": dict(Counter(r["outcome"] for r in samples)),
                "first_actions": dict(Counter(json.dumps(r["steps"][0]["action"], ensure_ascii=False, sort_keys=True) for r in samples)),
                "actual_violations": sum(r["verification"]["actual_policy_violation"] for r in samples),
                **{metric: sum(r["metrics"][metric] for r in samples) for metric in ("llm_calls", "tokens", "tool_calls")}}
    return {"scope": plan["scope"], "exact": exact, "normal": normal,
            "totals": {g: {metric: sum(normal[t][g][metric] for t in normal) for metric in ("success", "runs", "actual_violations", "llm_calls", "tokens", "tool_calls")} for g in plan["groups"]}}


def write_report(result):
    lines = ["| Group | Normal EOC / runs | Model calls | Tokens | Tools | Actual violations |", "|---|---|---|---|---|---|"]
    for g, r in result["totals"].items():
        lines.append(f"| {g} | {r['success']}/{r['runs']} | {r['llm_calls']} | {r['tokens']} | {r['tool_calls']} | {r['actual_violations']} |")
    lines += ["", "| Input hash | Selection | Action frequencies |", "|---|---|---|"]
    for h, r in result["exact"].items():
        lines.append(f"| {h[:12]} | {', '.join(r['selection'])} | {json.dumps(r['decisions'], ensure_ascii=False)} |")
    lines += ["", "| Scenario | A | B | C |", "|---|---|---|---|"]
    for tid, groups in result["normal"].items():
        lines.append("| " + tid + " | " + " | ".join(f"{groups[g]['success']}/{groups[g]['runs']}" for g in "ABC") + " |")
    detail = "\n".join(lines)
    zh = "# 边界实验重复性诊断结果\n\n[English](en/BOUNDARY_REPEATABILITY_RESULTS.md)\n\n本轮为事后诊断：7个原样输入各10次、8个正常场景各组3次；正常场景的重复次数不是新增独立业务样本。保留历史分数，未改模型、后端或边界。完整Action、原样HTTP输入/响应、轨迹和费用见results/boundary-repeatability/v1。\n\n"
    en = "# Boundary study repeatability diagnostic\n\n[中文](../BOUNDARY_REPEATABILITY_RESULTS.md)\n\nRetrospective diagnostic: seven exact inputs repeated ten times, and all eight normal scenarios repeated three times per group. Repetitions are not additional independent business scenarios. Historical scores, model, backend and boundaries remain unchanged. Full Actions, exact HTTP requests/responses, trajectories and costs are in results/boundary-repeatability/v1.\n\n"
    zh += detail + "\n\n本轮不重新检验原联合主张，也不将无分歧解释为确定性保证。频数只描述该服务会话；单轮失败能否重现与底层原因是不同问题。原因未定位，不能将差异直接归因于seed、cuDNN或某条边界文本。\n"
    en += detail + "\n\nThis diagnostic does not retest the original joint claim or establish deterministic inference. Frequencies describe this serving session. Reproducing a failure does not identify its cause: seed handling, cuDNN and individual boundary text have not been causally isolated.\n"
    Path("docs/BOUNDARY_REPEATABILITY_RESULTS.md").write_text(zh, encoding="utf-8")
    Path("docs/en/BOUNDARY_REPEATABILITY_RESULTS.md").write_text(en, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--freeze", action="store_true")
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--audit", action="store_true")
    args = parser.parse_args()
    lock = None
    try:
        if args.run or args.freeze:
            lock = Worker(JobStore(".runtime/boundary-repeatability-lock"), lambda *_: None)
            lock.start()
        print(json.dumps(freeze() if args.freeze else run(audit=args.audit)))
    finally:
        if lock:
            lock.close()
