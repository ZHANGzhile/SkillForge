"""Frozen same-protocol full-system / decision-level post-training evaluation."""
import argparse
import json
from pathlib import Path

from skillforge.benchmark import summarize
from skillforge.dataset import load_dataset, digest, task_hash
from skillforge.decision_eval import evaluate_decisions
from skillforge.experiment import load_bundle
from skillforge.hf_model import HFModelClient
from skillforge.environment import Environment
from skillforge.runtime import Runtime
from skillforge.training import atomic_json
from skillforge.training_data import file_hash
from skillforge.evaluation_checkpoints import read_checkpoint, save_checkpoint
from skillforge.config import load_config
from scripts.validation_loss import load_targets, score as score_validation_loss


def evaluate(config_path, label, adapter, split, output, no_gate=False, resume=False, validation_data=None):
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    manifest, tasks = load_dataset(config["dataset"])
    bundle, skills = load_bundle(config["bundle"], manifest["dataset_hash"])
    selected = [task for task in tasks if task.split == split]
    likelihood_targets = None
    if split == "validation" and validation_data:
        _, likelihood_targets = load_targets(validation_data, selected, manifest["dataset_hash"], bundle["bundle_hash"])
    root = Path(output)
    if root.exists() and not resume:
        raise ValueError("evaluation output exists; use explicit --resume")
    root.mkdir(parents=True, exist_ok=True)
    settings = HFModelClient.settings_for(config, adapter, label)
    identity = {"label": label, "split": split, "dataset_hash": manifest["dataset_hash"],
        "bundle_hash": bundle["bundle_hash"], "model_settings": settings, "gate": not no_gate,
        "runtime_config": load_config(), "config_hash": file_hash(config_path),
        "task_hashes": {task.task_id: task_hash(task) for task in selected},
        "decision_tasks": {skill.skill_id: [task.task_id for task in selected if task.family == skill.family] for skill in skills},
        "likelihood_manifest_sha256": file_hash(Path(validation_data) / "manifest.json") if likelihood_targets is not None else None,
        "likelihood_evaluator_hash": file_hash(Path(__file__).with_name("validation_loss.py")),
        "scope": "HF/NF4 same-protocol comparison; separate from prior Ollama/Q4 baseline"}
    identity["source_hash"] = digest({p.name: p.read_text(encoding="utf-8") for p in sorted(Path("skillforge").glob("*.py"))})
    identity["evaluator_hash"] = file_hash(__file__)
    identity_path = root / "identity.json"
    if identity_path.exists() and json.loads(identity_path.read_text(encoding="utf-8")) != identity:
        raise ValueError("evaluation resume model/data/code mismatch")
    atomic_json(identity_path, identity)
    # Validate every reusable checkpoint before allocating the GPU or accepting
    # a completed report. A file's existence alone is not a successful run.
    task_dir, decision_dir = root / "tasks", root / "decisions"
    task_dir.mkdir(exist_ok=True)
    decision_dir.mkdir(exist_ok=True)
    for task in selected:
        path = task_dir / (task.task_id + ".json")
        if path.exists():
            read_checkpoint(path, identity, task.task_id, task_hash(task))
    for skill in skills:
        for task in [t for t in selected if t.family == skill.family]:
            path = decision_dir / (skill.skill_id + "-" + task.task_id + ".json")
            if path.exists():
                read_checkpoint(path, {**identity, "skill_id": skill.skill_id}, task.task_id)
    model = None
    def get_model():
        nonlocal model
        if model is None:
            model = HFModelClient(config_path, adapter, label)
        return model
    try:
        records = []
        for task in selected:
            path = task_dir / (task.task_id + ".json")
            if path.exists():
                record = read_checkpoint(path, identity, task.task_id, task_hash(task))
            else:
                if model is None:
                    model = HFModelClient(config_path, adapter, label)
                env = Environment(fixture=task.fixture, faults=task.fixture.get("faults"))
                try:
                    record = Runtime(model, skills=skills, verified=not no_gate).run(task, env)
                    if getattr(model, "fatal_error", None):
                        atomic_json(root / "infrastructure_failure.json", {"error": model.fatal_error, "partial_trajectory": record})
                        raise RuntimeError("evaluation infrastructure failed: " + model.fatal_error)
                    record = save_checkpoint(path, record, identity)
                finally:
                    env.close()
            records.append(record)
            atomic_json(root / "progress.json", {"phase": "full_system", "completed": len(records), "total": len(selected)})
        summary = {"label": label, "model": settings["model"], "engineering_only": False, **summarize(records)}
        decisions = []
        for skill in skills:
            rows = []
            for task in [t for t in selected if t.family == skill.family]:
                path = decision_dir / (skill.skill_id + "-" + task.task_id + ".json")
                if path.exists():
                    row = read_checkpoint(path, {**identity, "skill_id": skill.skill_id}, task.task_id)
                else:
                    if model is None:
                        model = HFModelClient(config_path, adapter, label)
                    row = evaluate_decisions(model, skill, [task])["cases"][0]
                    if getattr(model, "fatal_error", None):
                        atomic_json(root / "infrastructure_failure.json", {"error": model.fatal_error, "partial_decision": row})
                        raise RuntimeError("evaluation infrastructure failed: " + model.fatal_error)
                    row = save_checkpoint(path, row, {**identity, "skill_id": skill.skill_id})
                rows.append(row)
                atomic_json(root / "progress.json", {"phase": "decision_level", "family": skill.family, "completed": len(rows)})
            valid = [r for r in rows if not r.get("skipped")]
            decisions.append({"family": skill.family, "evaluated": len(valid), "skipped": len(rows) - len(valid),
                "accuracy": sum(r["correct"] for r in valid) / len(valid) if valid else None, "cases": rows})
        likelihood = score_validation_loss(get_model, likelihood_targets, identity, root, config["max_length"]) if likelihood_targets is not None else None
        report = {**identity, "full_system": summary, "decision_level": decisions, "validation_loss": likelihood}
        atomic_json(root / "evaluation.json", report)
        atomic_json(root / "progress.json", {"phase": "completed", "full_system": summary})
        return report
    finally:
        if model is not None:
            model.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/training.json")
    parser.add_argument("--label", choices=["Base", "SFT", "DPO"], required=True)
    parser.add_argument("--adapter")
    parser.add_argument("--split", choices=["validation", "test"], default="validation")
    parser.add_argument("--output", required=True)
    parser.add_argument("--no-gate", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--validation-data", default=json.loads(Path("configs/training-runs.json").read_text(encoding="utf-8")).get("validation_loss_data"))
    args = parser.parse_args()
    if (args.label == "Base") != (args.adapter is None):
        parser.error("Base has no adapter; SFT/DPO require --adapter")
    report = evaluate(args.config, args.label, args.adapter, args.split, args.output, args.no_gate, args.resume, args.validation_data)
    print(json.dumps({"label": args.label, "split": args.split, "full_system": report["full_system"],
        "decision_accuracy": [d["accuracy"] for d in report["decision_level"]]}, indent=2))
