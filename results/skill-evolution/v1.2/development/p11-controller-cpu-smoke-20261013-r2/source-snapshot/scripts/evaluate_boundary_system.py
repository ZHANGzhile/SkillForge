"""Pinned real-model ABCD runs and pre-Gate, single-attempt counterfactuals."""
import argparse
import json
from pathlib import Path
import time

from scripts.boundary_learning import public_contract, procedure_hash
from scripts.boundary_runtime import BoundaryRuntime
from scripts.coordinator_io import atomic_json
from scripts.evaluate_reuse_ablation import create_client, read, validate_record
from scripts.prepare_boundary_study import load_prepared
from skillforge.dataset import digest, task_hash
from skillforge.environment import Environment
from skillforge.evaluation_checkpoints import read_checkpoint, save_checkpoint
from skillforge.jobs import JobStore, Worker
from skillforge.schemas import SkillContract
from skillforge.training_data import file_hash

MODES = ("autonomous", "gate", "bypass")


def prepared(plan_path):
    plan, root, tasks, boundaries, preparation = load_prepared(plan_path)
    tasks = [t for t in tasks if t.split == "test"]
    settings = read(plan["reference"])["model_settings"]
    identity = {"preparation_sha256": file_hash(root / "preparation.json"), "reference_sha256": file_hash(plan["reference"]),
                "profile_sha256": file_hash(plan["client_profile"]), "model_settings": settings,
                "code": {p: file_hash(p) for p in ("scripts/evaluate_boundary_system.py", "scripts/boundary_runtime.py", "scripts/evaluate_reuse_ablation.py")}}
    keys, aliases, owners = {}, {}, {}
    for task in tasks:
        for group in "ABCD":
            contract = public_contract(SkillContract.model_validate(boundaries["groups"][group][task.family]))
            for mode in MODES:
                key = task.task_id + "-" + group + "-" + mode
                fingerprint = digest([task_hash(task), contract, mode])
                if plan["reuse_identical_public_contracts"] and fingerprint in owners:
                    aliases[key] = owners[fingerprint]
                else:
                    owners[fingerprint] = key
                    keys[key] = (task, group, mode)
    identity["aliases"] = aliases
    identity["expected_keys"] = sorted(keys)
    return plan, root / "system", tasks, boundaries, identity, keys


def validate(row, task, group, mode, boundaries, identity):
    validate_record({**row, "model_settings": identity["model_settings"]}, task, identity["model_settings"])
    if row["model_settings"].get("server_identity") != identity["model_settings"]:
        raise ValueError("boundary study model identity differs")
    skill = SkillContract.model_validate(boundaries["groups"][group][task.family])
    cf = row["boundary_experiment"]
    env = Environment(fixture=task.fixture, faults=task.fixture.get("faults"))
    try:
        expected = {"observations": {}, "database_sql": list(env.db.iterdump()), "remaining_faults": env.faults,
                    "request": task.request, "parameters": task.parameters, "procedure_hash": procedure_hash(skill)}
    finally:
        env.close()
    forced = int(mode != "autonomous")
    if cf["intervention"] != mode or cf["fork"] != expected or cf["forced_decisions"] != forced:
        raise ValueError("intervention/fork evidence mismatch")
    if len(row["steps"]) <= forced:
        raise ValueError("no actual model continuation")
    if cf["actual_model_inputs"] != [s["context"] for s in row["steps"][forced:]]:
        raise ValueError("actual model inputs differ from recorded steps")
    if row["metrics"]["llm_calls"] != len(cf["actual_model_inputs"]) or row["metrics"]["decision_calls"] != len(row["steps"]):
        raise ValueError("forced versus actual call accounting mismatch")
    if forced and row["steps"][0]["action"] != {"type": "skill", "name": skill.skill_id, "arguments": task.parameters}:
        raise ValueError("initial intervention not the fixed Skill")
    for step in row["steps"]:
        if any(s != public_contract(skill) for s in step["context"]["executable_skills"]):
            raise ValueError("model-visible contract/provenance mismatch")
    if cf["forced_tool_policy_attempts"] != sum(bool(e["attempted_policy_violation"]) for e in row["tool_audit"] if e.get("decision_origin") == "experiment_skill"):
        raise ValueError("forced policy-attempt accounting mismatch")


def progress(root, **kwargs):
    value = {**kwargs, "at": time.time()}
    atomic_json(root / "progress.json", value)
    Path("docs/BOUNDARY_STUDY_LIVE.md").write_bytes(("# 边界对照实时进度\n\n```json\n" + json.dumps(value, ensure_ascii=False, indent=2) + "\n```\n").encode())


def run(plan_path="configs/boundary-study.json", resume=False, audit_only=False):
    plan, root, tasks, boundaries, identity, keys = prepared(plan_path)
    if root.exists() and not (resume or audit_only):
        raise ValueError("existing experiment requires explicit resume")
    if audit_only and not (root / "completed.json").exists():
        raise ValueError("complete experiment required")
    root.mkdir(parents=True, exist_ok=True)
    (root / "runs").mkdir(exist_ok=True)
    if (root / "identity.json").exists() and read(root / "identity.json") != identity:
        raise ValueError("boundary system identity changed")
    if not audit_only:
        atomic_json(root / "identity.json", identity)
    existing = {p.stem for p in (root / "runs").glob("*.json")}
    if existing - set(keys) or (audit_only and existing != set(keys)):
        raise ValueError("checkpoint coverage mismatch")
    rows = {}
    # Audit all reusable rows before opening a model connection.
    for key in sorted(existing):
        task, group, mode = keys[key]
        row = read_checkpoint(root / "runs" / (key + ".json"), {**identity, "key": key}, task.task_id, task_hash(task))
        validate(row, task, group, mode, boundaries, identity)
        rows[key] = row
    model = None
    # Deterministic shuffled execution avoids constant group/arm serving order.
    order = sorted(keys, key=lambda key: digest([plan["seed"], key]))
    for key in order:
        if key in rows:
            continue
        task, group, mode = keys[key]
        if model is None:
            model = create_client(plan["client_profile"], identity["model_settings"])
        env = Environment(fixture=task.fixture, faults=task.fixture.get("faults"))
        try:
            row = BoundaryRuntime(model, max_steps=plan["max_steps"], retry_budget=plan["retry_budget"],
                skills=[SkillContract.model_validate(boundaries["groups"][group][task.family])], intervention=mode).run(task, env)
        finally:
            env.close()
        if model.fatal_error:
            atomic_json(root / "infrastructure-failure.json", {"key": key, "error": model.fatal_error, "partial": row})
            raise RuntimeError("infrastructure failure; partial not scored")
        validate(row, task, group, mode, boundaries, identity)
        rows[key] = save_checkpoint(root / "runs" / (key + ".json"), row, {**identity, "key": key})
        progress(root, stage="running", completed=len(rows), total=len(keys), logical_total=len(keys) + len(identity["aliases"]), last_key=key)
    expanded = {**rows, **{key: rows[source] for key, source in identity["aliases"].items()}}
    # Compare all forks, including the unmodified DB, before any Gate hydration.
    for task in tasks:
        forks = [expanded[task.task_id + "-" + g + "-" + m]["boundary_experiment"]["fork"] for g in "ABCD" for m in MODES]
        if any(f != forks[0] for f in forks):
            raise ValueError("paired forks differ")
    completed = {"actual_runs": len(rows), "logical_runs": len(expanded), "aliases": identity["aliases"],
                 "identity_sha256": file_hash(root / "identity.json"), "checkpoints": {key: file_hash(root / "runs" / (key + ".json")) for key in sorted(rows)}}
    if audit_only:
        if read(root / "completed.json") != completed:
            raise ValueError("completed summary differs from audited checkpoints")
    else:
        atomic_json(root / "completed.json", completed)
        progress(root, stage="completed", completed=len(rows), total=len(keys), logical_total=len(expanded))
    return expanded, completed


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args()
    lock = None
    try:
        if not args.audit_only:
            lock = Worker(JobStore(".runtime/boundary-study-lock"), lambda *_: None)
            lock.start()
        _, result = run(resume=args.resume, audit_only=args.audit_only)
        print({k: v for k, v in result.items() if k not in {"checkpoints", "aliases"}})
    except Exception as exc:
        if not args.audit_only:
            progress(Path(read("configs/boundary-study.json")["output"]) / "system", stage="failed", error=type(exc).__name__, message=str(exc))
        raise
    finally:
        if lock:
            lock.close()
