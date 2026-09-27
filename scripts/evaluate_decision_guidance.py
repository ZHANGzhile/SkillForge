"""Validation-gated, resumable policy-worksheet experiment; frozen core intact."""
import argparse
import copy
from pathlib import Path
import time

from scripts.audit_validation import audit as audit_validation
from scripts.coordinator_io import atomic_json
from scripts.decision_guidance import GuidedClient, augment
from scripts.evaluate_reuse_ablation import create_client, read, validate_record
from skillforge.benchmark import summarize
from skillforge.config import load_config
from skillforge.dataset import digest, load_dataset, task_hash, write_dataset
from skillforge.decision_eval import evaluate_decisions
from skillforge.environment import Environment
from skillforge.evaluation_checkpoints import read_checkpoint, save_checkpoint
from skillforge.experiment import load_bundle
from skillforge.jobs import JobStore, Worker
from skillforge.runtime import Runtime
from skillforge.training_data import file_hash


def progress(root, **value):
    value["at"] = time.time()
    atomic_json(root / "progress.json", value)
    Path("docs/DECISION_GUIDANCE_LIVE.md").write_text(
        "# 决策提示实验实时进度\n\n" + time.strftime("%Y-%m-%d %H:%M:%S") + "\n\n"
        + "```json\n" + __import__("json").dumps(value, ensure_ascii=False, indent=2) + "\n```\n"
        + "\n仅为固定权重的提示干预实验；未获准入时不进入test，不自动替换当前部署。\n", encoding="utf-8")


def validate_inputs(record, enabled):
    for i, step in enumerate(record["steps"]):
        expected = augment(step["context"], i) if enabled else step["context"]
        if step.get("model_input_context") != expected:
            raise ValueError("actual model input differs from declared intervention")


def validate_system(record, task, identity, enabled):
    if record["model_settings"].get("server_identity") != identity["model_settings"]:
        raise ValueError("guidance service identity mismatch")
    if record["model_settings"].get("guidance_sha256") != (identity["guidance_hash"] if enabled else None):
        raise ValueError("guidance settings mismatch")
    normalized = {**record, "model_settings": identity["model_settings"]}
    validate_record(normalized, task, identity["model_settings"])
    validate_inputs(record, enabled)


def decision_check(row, task, enabled):
    if row.get("skipped"):
        return
    # Model/schema errors are scored, with the submitted context still archived.
    sent = row.get("model_inputs", [])
    if len(sent) != 1:
        raise ValueError("decision must preserve its actual model input")
    original = copy.deepcopy(sent[0])
    original.pop("decision_guidance", None)
    if sent[0] != (augment(original, 0) if enabled else original):
        raise ValueError("decision guidance mismatch")
    if row.get("context") is not None and row["context"] != original:
        raise ValueError("decision original context mismatch")
    if "action" in row:
        target = {"completed": "skill", "refused": "refuse", "escalated": "escalate"}[task.expected.allowed_outcomes[0]]
        action = row["action"]
        correct = action["type"] == target and (target != "skill" or
            action["name"] == row["skill_id"] and action["arguments"] == task.parameters)
        if row["target"] != target or row["correct"] != correct:
            raise ValueError("decision verdict mismatch")
    elif row.get("correct") is not False:
        raise ValueError("unscored model error")


def run_stage(root, label, tasks, skills, identity, profile, enabled, all_progress_root):
    folder = root / label
    folder.mkdir(parents=True, exist_ok=True)
    identity = {**identity, "stage": label, "enabled": enabled,
                "task_hashes": {t.task_id: task_hash(t) for t in tasks}}
    path = folder / "identity.json"
    if path.exists() and read(path) != identity:
        raise ValueError("stage identity changed")
    atomic_json(path, identity)
    for name in ("tasks", "decisions"):
        (folder / name).mkdir(exist_ok=True)
    expected_decisions = {s.skill_id + "-" + t.task_id: (s, t) for s in skills for t in tasks if t.family == s.family}
    if {p.stem for p in (folder / "tasks").glob("*.json")} - set(identity["task_hashes"]):
        raise ValueError("unexpected system checkpoint")
    if {p.stem for p in (folder / "decisions").glob("*.json")} - set(expected_decisions):
        raise ValueError("unexpected decision checkpoint")
    records, decisions = {}, {}
    # Re-audit every saved row BEFORE resuming model calls.
    for task in tasks:
        path = folder / "tasks" / (task.task_id + ".json")
        if path.exists():
            row = read_checkpoint(path, identity, task.task_id, task_hash(task))
            validate_system(row, task, identity, enabled)
            records[task.task_id] = row
    for name, (skill, task) in expected_decisions.items():
        path = folder / "decisions" / (name + ".json")
        if path.exists():
            row = read_checkpoint(path, {**identity, "skill_id": skill.skill_id}, task.task_id, task_hash(task))
            decision_check(row, task, enabled)
            decisions[name] = row
    model = None
    def client():
        nonlocal model
        if model is None:
            model = GuidedClient(create_client(profile, identity["model_settings"]), enabled, identity["guidance_hash"])
        model.begin()
        return model
    def backend(row):
        if model.fatal_error:
            atomic_json(folder / "infrastructure_failure.json", {"error": model.fatal_error, "partial": row})
            raise RuntimeError("guidance infrastructure failure; partial not scored")
    for task in tasks:
        if task.task_id not in records:
            env = Environment(fixture=task.fixture, faults=task.fixture.get("faults"))
            try:
                row = Runtime(client(), skills=skills).run(task, env)
            finally:
                env.close()
            backend(row)
            if len(row["steps"]) != len(model.inputs):
                raise ValueError("model input count mismatch")
            for step, sent in zip(row["steps"], model.inputs):
                step["model_input_context"] = sent
            validate_system(row, task, identity, enabled)
            records[task.task_id] = save_checkpoint(folder / "tasks" / (task.task_id + ".json"), row, identity)
        progress(all_progress_root, stage=label, phase="full_system", completed=len(records), total=len(tasks))
    for name, (skill, task) in expected_decisions.items():
        if name not in decisions:
            row = evaluate_decisions(client(), skill, [task])["cases"][0]
            backend(row)
            row.update(task_hash=task_hash(task), skill_id=skill.skill_id, model_inputs=copy.deepcopy(model.inputs))
            decision_check(row, task, enabled)
            decisions[name] = save_checkpoint(folder / "decisions" / (name + ".json"), row, {**identity, "skill_id": skill.skill_id})
        progress(all_progress_root, stage=label, phase="decision_level", completed=len(decisions), total=len(expected_decisions))
    valid = [r for r in decisions.values() if not r.get("skipped")]
    report = {"identity": identity, "full_system": summarize(list(records.values())),
              "decision_level": {"evaluated": len(valid), "correct": sum(r["correct"] for r in valid), "skipped": len(decisions) - len(valid)}}
    path = folder / "evaluation.json"
    if path.exists() and read(path) != report:
        raise ValueError("guidance summary differs from audited evidence")
    atomic_json(path, report)
    return report


def admitted(report, gate):
    summary = report["full_system"]
    return (round(summary["tasks"] * summary["task_success_rate"]) >= gate["minimum_successes"]
        and round(summary["tasks"] * summary["model_attempted_policy_violation_rate"]) <= gate["maximum_model_attempts"]
        and round(summary["tasks"] * summary["actual_policy_violation_rate"]) <= gate["maximum_actual_violations"]
        and report["decision_level"]["correct"] >= gate["minimum_correct_decisions"])


def run(plan_path, resume=False):
    plan = read(plan_path)
    root = Path(plan["output"])
    if root.exists() and not resume:
        raise ValueError("output exists; explicit --resume required")
    root.mkdir(parents=True, exist_ok=True)
    config = read(plan["training_config"])
    reference = audit_validation(plan["reference_validation"], plan["training_config"], plan["validation_loss_data"])
    manifest, tasks = load_dataset(config["dataset"])
    bundle, skills = load_bundle(config["bundle"], manifest["dataset_hash"])
    write_dataset(plan["fresh_dataset"], seed=plan["fresh_seed"], instances=plan["fresh_instances"])
    fresh_manifest, fresh = load_dataset(plan["fresh_dataset"])
    for dataset in plan["excluded_datasets"]:
        _, excluded = load_dataset(dataset)
        for key in (lambda t: t.task_id, lambda t: t.instance_id, lambda t: t.parameters["order_id"]):
            if {key(t) for t in fresh} & {key(t) for t in excluded}:
                raise ValueError("new instance dataset overlaps prior corpus")
    identity = {"plan_sha256": file_hash(plan_path), "config_sha256": file_hash(plan["training_config"]),
        "profile_sha256": file_hash(plan["client_profile"]), "evaluator_hash": file_hash(__file__),
        "guidance_hash": file_hash(Path(__file__).with_name("decision_guidance.py")),
        "client_auditor_hash": file_hash(Path(__file__).with_name("evaluate_reuse_ablation.py")),
        "source_hash": digest({p.name: p.read_text(encoding="utf-8") for p in sorted(Path("skillforge").glob("*.py"))}),
        "runtime_config": load_config(), "dataset_hash": manifest["dataset_hash"],
        "fresh_dataset_hash": fresh_manifest["dataset_hash"], "bundle_hash": bundle["bundle_hash"],
        "model_settings": reference["model_settings"], "reference_sha256": file_hash(Path(plan["reference_validation"]) / "evaluation.json")}
    validation = run_stage(root, "validation", [t for t in tasks if t.split == "validation"], skills, identity, plan["client_profile"], True, root)
    selection = {"admitted": admitted(validation, plan["validation_gate"]), "split": "validation",
        "gate": plan["validation_gate"], "validation_report_sha256": file_hash(root / "validation/evaluation.json"), "identity": identity}
    if (root / "selection.json").exists() and read(root / "selection.json") != selection:
        raise ValueError("validation selection changed")
    atomic_json(root / "selection.json", selection)
    if not selection["admitted"]:
        progress(root, stage="rejected", reason="predeclared_validation_gate_failed", validation=validation["full_system"], decisions=validation["decision_level"])
        return selection
    reports = {}
    for label, enabled in (("control", False), ("guided", True)):
        reports[label] = run_stage(root, label, [t for t in fresh if t.split == "test"], skills, identity, plan["client_profile"], enabled, root)
    result = {"identity": identity, "selection": selection, "arms": reports, "scope": plan["scope"], "causal_ntr": None}
    atomic_json(root / "comparison.json", result)
    progress(root, stage="completed", tasks_per_arm=78)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", default="configs/decision-guidance.json")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    lock = Worker(JobStore(".runtime/decision-guidance-lock"), lambda *_: None)
    lock.start()
    try:
        result = run(args.plan, args.resume)
        print({"completed": "arms" in result, "admitted": result.get("admitted", True)})
    except Exception as exc:
        progress(Path(read(args.plan)["output"]), stage="failed", error=type(exc).__name__, message=str(exc))
        raise
    finally:
        lock.close()
