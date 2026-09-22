"""Recompute complete held-out validation evidence without loading a model."""
import json
import math
from pathlib import Path

from skillforge.benchmark import summarize
from skillforge.dataset import load_dataset, task_hash
from skillforge.evaluation_checkpoints import read_checkpoint
from skillforge.experiment import load_bundle
from skillforge.training_data import file_hash
from scripts.validation_loss import load_targets


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def audit(folder, config_path, likelihood_data):
    folder = Path(folder)
    identity, report = read(folder / "identity.json"), read(folder / "evaluation.json")
    config = read(config_path)
    manifest, tasks = load_dataset(config["dataset"])
    bundle, _ = load_bundle(config["bundle"], manifest["dataset_hash"])
    selected = [task for task in tasks if task.split == "validation"]
    if (identity["split"] != "validation" or identity["dataset_hash"] != manifest["dataset_hash"]
            or identity["bundle_hash"] != bundle["bundle_hash"] or identity["config_hash"] != file_hash(config_path)
            or any(report.get(k) != v for k, v in identity.items())
            or identity["task_hashes"] != {t.task_id: task_hash(t) for t in selected}):
        raise ValueError("validation identity/data coverage mismatch")
    expected = identity["task_hashes"]
    if {p.stem for p in (folder / "tasks").glob("*.json")} != set(expected):
        raise ValueError("validation task checkpoint coverage mismatch")
    records = [read_checkpoint(folder / "tasks" / (key + ".json"), identity, key, value) for key, value in expected.items()]
    if any(report["full_system"].get(k) != v for k, v in summarize(records).items()):
        raise ValueError("validation summary differs from executed tasks")
    decisions = []
    for skill_id, task_ids in identity["decision_tasks"].items():
        for task_id in task_ids:
            decisions.append(read_checkpoint(folder / "decisions" / (skill_id + "-" + task_id + ".json"),
                {**identity, "skill_id": skill_id}, task_id))
    if decisions != [row for group in report["decision_level"] for row in group["cases"]]:
        raise ValueError("validation decisions differ from executed probes")
    for group in report["decision_level"]:
        valid = [r for r in group["cases"] if not r.get("skipped")]
        accuracy = sum(r["correct"] for r in valid) / len(valid) if valid else None
        if group["evaluated"] != len(valid) or group["skipped"] != len(group["cases"]) - len(valid) or group["accuracy"] != accuracy:
            raise ValueError("validation decision summary mismatch")
    if (identity["likelihood_manifest_sha256"] != file_hash(Path(likelihood_data) / "manifest.json")
            or identity["likelihood_evaluator_hash"] != file_hash(Path(__file__).with_name("validation_loss.py"))):
        raise ValueError("validation likelihood evaluator/corpus changed")
    _, targets = load_targets(likelihood_data, selected, manifest["dataset_hash"], bundle["bundle_hash"])
    if {p.stem for p in (folder / "validation_loss").glob("*.json")} != {r["example_id"] for r in targets}:
        raise ValueError("validation likelihood checkpoint coverage mismatch")
    scores = []
    for target in targets:
        row = read_checkpoint(folder / "validation_loss" / (target["example_id"] + ".json"),
            {**identity, "phase": "validation_loss"}, target["task_id"], target["task_hash"])
        if row["example_id"] != target["example_id"] or row["action_type"] != target["action_type"]:
            raise ValueError("validation likelihood target mismatch")
        if not row["skipped"] and (type(row["target_tokens"]) is not int or row["target_tokens"] <= 0
                or not math.isfinite(row["log_probability"]) or row["log_probability"] > 1e-6):
            raise ValueError("invalid validation likelihood score")
        scores.append(row)
    valid = [r for r in scores if not r["skipped"]]
    if not valid:
        raise ValueError("empty validation likelihood evaluation")
    recalculated = {"token_weighted_loss": -sum(r["log_probability"] for r in valid) / sum(r["target_tokens"] for r in valid),
        "example_mean_loss": sum(-r["log_probability"] / r["target_tokens"] for r in valid) / len(valid),
        "examples": len(valid), "target_tokens": sum(r["target_tokens"] for r in valid),
        "skipped_example_ids": [r["example_id"] for r in scores if r["skipped"]]}
    if any(report["validation_loss"].get(k) != v for k, v in recalculated.items()):
        raise ValueError("validation likelihood summary differs from scored targets")
    return report
