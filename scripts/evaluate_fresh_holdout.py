"""Evaluate a frozen model on a separately frozen, disjoint instance corpus.

Skills retain their original training-dataset provenance. The new test corpus
is an evaluation input, never relabelled as the skills' compilation dataset.
"""
import argparse
import json
from pathlib import Path

from scripts.coordinator_io import atomic_json
from skillforge.benchmark import summarize
from skillforge.config import load_config
from skillforge.dataset import digest, load_dataset, task_hash
from skillforge.decision_eval import evaluate_decisions
from skillforge.environment import Environment
from skillforge.evaluation_checkpoints import read_checkpoint, save_checkpoint
from skillforge.experiment import load_bundle
from skillforge.hf_model import HFModelClient
from skillforge.runtime import Runtime
from skillforge.training_data import file_hash


def inputs(config_path, dataset):
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    training_manifest, original = load_dataset(config["dataset"])
    manifest, tasks = load_dataset(dataset)
    if manifest["dataset_hash"] == training_manifest["dataset_hash"]:
        raise ValueError("fresh holdout cannot be the original corpus")
    for key in (lambda t: t.task_id, lambda t: t.parameters["order_id"], lambda t: t.instance_id):
        if {key(t) for t in original} & {key(t) for t in tasks}:
            raise ValueError("fresh holdout contains original task/order/instance IDs")
    bundle, skills = load_bundle(config["bundle"], training_manifest["dataset_hash"])
    return config, training_manifest, manifest, [t for t in tasks if t.split == "test"], bundle, skills


def evaluate(config_path, dataset, adapter, label, output, resume=False):
    config, original, manifest, tasks, bundle, skills = inputs(config_path, dataset)
    root = Path(output)
    if root.exists() and not resume:
        raise ValueError("output exists; explicit --resume required")
    root.mkdir(parents=True, exist_ok=True)
    settings = HFModelClient.settings_for(config, adapter, label)
    identity = {"label": label, "split": "test", "training_dataset_hash": original["dataset_hash"],
        "holdout_dataset_hash": manifest["dataset_hash"], "bundle_hash": bundle["bundle_hash"],
        "model_settings": settings, "config_hash": file_hash(config_path), "runtime_config": load_config(),
        "source_hash": digest({p.name: p.read_text(encoding="utf-8") for p in sorted(Path("skillforge").glob("*.py"))}),
        "evaluator_hash": file_hash(__file__), "gate": True,
        "task_hashes": {t.task_id: task_hash(t) for t in tasks},
        "decision_tasks": {s.skill_id: [t.task_id for t in tasks if t.family == s.family] for s in skills},
        "scope": "Fresh instances from a known generator and known structural families; no claim of unseen business semantics."}
    path = root / "identity.json"
    if path.exists() and json.loads(path.read_text(encoding="utf-8")) != identity:
        raise ValueError("fresh evaluation model/data/code identity changed")
    atomic_json(path, identity)
    (root / "tasks").mkdir(exist_ok=True)
    (root / "decisions").mkdir(exist_ok=True)
    # Audit reusable evidence before allocating the GPU.
    for task in tasks:
        checkpoint = root / "tasks" / (task.task_id + ".json")
        if checkpoint.exists():
            read_checkpoint(checkpoint, identity, task.task_id, task_hash(task))
    for skill in skills:
        for task_id in identity["decision_tasks"][skill.skill_id]:
            checkpoint = root / "decisions" / (skill.skill_id + "-" + task_id + ".json")
            if checkpoint.exists():
                read_checkpoint(checkpoint, {**identity, "skill_id": skill.skill_id}, task_id)
    model = None
    def get_model():
        nonlocal model
        if model is None:
            model = HFModelClient(config_path, adapter, label)
        return model
    def check_backend(partial):
        if getattr(model, "fatal_error", None):
            atomic_json(root / "infrastructure_failure.json", {"error": model.fatal_error, "partial": partial})
            raise RuntimeError("fresh evaluation infrastructure failed: " + model.fatal_error)
    try:
        records = []
        for task in tasks:
            checkpoint = root / "tasks" / (task.task_id + ".json")
            if checkpoint.exists():
                record = read_checkpoint(checkpoint, identity, task.task_id, task_hash(task))
            else:
                env = Environment(fixture=task.fixture, faults=task.fixture.get("faults"))
                try:
                    record = Runtime(get_model(), skills=skills).run(task, env)
                finally:
                    env.close()
                check_backend(record)
                record = save_checkpoint(checkpoint, record, identity)
            records.append(record)
            atomic_json(root / "progress.json", {"phase": "full_system", "completed": len(records), "total": len(tasks)})
        groups = []
        for skill in skills:
            rows = []
            for task in [t for t in tasks if t.family == skill.family]:
                checkpoint = root / "decisions" / (skill.skill_id + "-" + task.task_id + ".json")
                if checkpoint.exists():
                    row = read_checkpoint(checkpoint, {**identity, "skill_id": skill.skill_id}, task.task_id)
                else:
                    row = evaluate_decisions(get_model(), skill, [task])["cases"][0]
                    check_backend(row)
                    row = save_checkpoint(checkpoint, row, {**identity, "skill_id": skill.skill_id})
                rows.append(row)
                atomic_json(root / "progress.json", {"phase": "decision_level", "family": skill.family, "completed": len(rows)})
            valid = [r for r in rows if not r.get("skipped")]
            groups.append({"family": skill.family, "evaluated": len(valid), "skipped": len(rows)-len(valid),
                "accuracy": sum(r["correct"] for r in valid)/len(valid) if valid else None, "cases": rows})
        report = {**identity, "full_system": summarize(records), "decision_level": groups,
            "by_family": {family: summarize([r for r in records if r["task_family"] == family]) for family in sorted({r["task_family"] for r in records})}}
        atomic_json(root / "evaluation.json", report)
        atomic_json(root / "progress.json", {"phase": "completed"})
        return report
    finally:
        if model is not None:
            model.close()


def audit(output, config_path, dataset):
    root = Path(output)
    config, original, manifest, tasks, bundle, skills = inputs(config_path, dataset)
    identity = json.loads((root / "identity.json").read_text(encoding="utf-8"))
    report = json.loads((root / "evaluation.json").read_text(encoding="utf-8"))
    source = digest({p.name: p.read_text(encoding="utf-8") for p in sorted(Path("skillforge").glob("*.py"))})
    if (identity["split"] != "test" or identity["gate"] is not True
            or identity["training_dataset_hash"] != original["dataset_hash"] or identity["holdout_dataset_hash"] != manifest["dataset_hash"]
            or identity["bundle_hash"] != bundle["bundle_hash"] or identity["config_hash"] != file_hash(config_path)
            or identity["evaluator_hash"] != file_hash(__file__) or identity["source_hash"] != source
            or identity["runtime_config"] != load_config() or identity["task_hashes"] != {t.task_id: task_hash(t) for t in tasks}
            or any(report.get(k) != v for k, v in identity.items())):
        raise ValueError("fresh report identity mismatch")
    if {p.stem for p in (root / "tasks").glob("*.json")} != set(identity["task_hashes"]):
        raise ValueError("fresh report task coverage mismatch")
    records = [read_checkpoint(root / "tasks" / (t.task_id + ".json"), identity, t.task_id, task_hash(t)) for t in tasks]
    expected = {s.skill_id: [t.task_id for t in tasks if t.family == s.family] for s in skills}
    if identity["decision_tasks"] != expected:
        raise ValueError("fresh decision task coverage mismatch")
    groups = []
    for skill in skills:
        rows = [read_checkpoint(root / "decisions" / (skill.skill_id + "-" + tid + ".json"),
            {**identity, "skill_id": skill.skill_id}, tid) for tid in expected[skill.skill_id]]
        valid = [r for r in rows if not r.get("skipped")]
        groups.append({"family": skill.family, "evaluated": len(valid), "skipped": len(rows)-len(valid),
            "accuracy": sum(r["correct"] for r in valid)/len(valid) if valid else None, "cases": rows})
    families = {family: summarize([r for r in records if r["task_family"] == family]) for family in sorted({r["task_family"] for r in records})}
    if report["full_system"] != summarize(records) or report["decision_level"] != groups or report["by_family"] != families:
        raise ValueError("fresh report summary differs from checkpoints")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--adapter", required=True)
    parser.add_argument("--label", choices=["SFT", "DPO"], required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    result = evaluate(args.config, args.dataset, args.adapter, args.label, args.output, args.resume)
    print(json.dumps(result["full_system"], indent=2))
