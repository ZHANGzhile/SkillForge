"""Predeclared held-out subset, three isolated runs per task and model.

The main test is repeat one. Two new executions use identical greedy settings;
this is descriptive repeatability, not pass@k or independent random-seed trials.
"""
import argparse
import json
from pathlib import Path

from skillforge.dataset import load_dataset, task_hash, digest
from skillforge.environment import Environment
from skillforge.evaluation_checkpoints import read_checkpoint, save_checkpoint
from skillforge.experiment import load_bundle
from skillforge.hf_model import HFModelClient
from skillforge.runtime import Runtime
from skillforge.training import atomic_json
from skillforge.training_data import file_hash


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def prepare(config_path, output):
    config = read(config_path)
    manifest, tasks = load_dataset(config["dataset"])
    # Selection uses only prespecified strata and task IDs, never model results.
    selected = []
    for family in ("modify_address", "cancel_order", "refund"):
        for level in ("A", "B", "D", "E"):
            candidates = sorted((t for t in tasks if t.split == "test" and t.family == family and t.level == level), key=lambda t: t.task_id)
            if not candidates:
                raise ValueError("missing prespecified stability stratum")
            selected.append(candidates[0])
    plan = {"dataset_hash": manifest["dataset_hash"], "repeats": 3,
        "selection": "lexicographically first test task per primitive family x A/B/D/E stratum",
        "task_hashes": {t.task_id: task_hash(t) for t in selected},
        "strata": {t.task_id: {"family": t.family, "level": t.level} for t in selected},
        "labels": ["Base", "SFT", "DPO"],
        "scope": "identical greedy settings; independent environments; descriptive all-three-pass, not pass@k"}
    target = Path(output)
    if target.exists() and read(target) != plan:
        raise ValueError("stability selection is immutable")
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(target, plan)
    return plan


def summarize(plan, runs):
    expected = set(plan["task_hashes"])
    if set(runs) != expected:
        raise ValueError("stability coverage mismatch")
    cases = []
    for task_id, rows in runs.items():
        if len(rows) != plan["repeats"] or any(r["task_id"] != task_id or r["task_hash"] != plan["task_hashes"][task_id] for r in rows):
            raise ValueError("stability repeat/task identity mismatch")
        passed = [bool(r["verification"]["task_success"]) for r in rows]
        cases.append({"task_id": task_id, **plan["strata"][task_id], "passed": passed,
            "outcomes": [r["outcome"] for r in rows], "all_passed": all(passed),
            "outcome_consistent": len({r["outcome"] for r in rows}) == 1})
    return {"tasks": len(cases), "repeats": plan["repeats"],
        "pass_all_repeats": sum(r["all_passed"] for r in cases) / len(cases),
        "outcome_consistency_rate": sum(r["outcome_consistent"] for r in cases) / len(cases),
        "cases": cases, "scope": plan["scope"]}


def audit(evaluation_root, label, plan_path="configs/stability.json"):
    """Recompute repeat summaries from bound records, without importing torch."""
    root, plan = Path(evaluation_root), read(plan_path)
    parent = read(root / (label + "-test") / "identity.json")
    if label not in plan["labels"] or plan["dataset_hash"] != parent["dataset_hash"]:
        raise ValueError("stability plan differs from main evaluation")
    if any(parent["task_hashes"].get(key) != value for key, value in plan["task_hashes"].items()):
        raise ValueError("stability plan is not a subset of frozen test tasks")
    identity = {"parent": parent, "plan_sha256": file_hash(plan_path), "evaluator_sha256": file_hash(__file__)}
    folder = root / "stability" / label
    if read(folder / "identity.json") != identity:
        raise ValueError("stability audit identity mismatch")
    runs = {}
    for key, expected_hash in plan["task_hashes"].items():
        runs[key] = [read_checkpoint(root / (label + "-test") / "tasks" / (key + ".json"), parent, key, expected_hash)]
        for repeat in range(2, plan["repeats"] + 1):
            runs[key].append(read_checkpoint(folder / f"{key}-{repeat}.json", {**identity, "repeat": repeat}, key, expected_hash))
    expected = {"identity": identity, "label": label, **summarize(plan, runs)}
    actual = read(folder / "evaluation.json")
    # JSON map ordering is not part of the protocol; cases are compared by task.
    if ({k: v for k, v in actual.items() if k != "cases"} != {k: v for k, v in expected.items() if k != "cases"}
            or {r["task_id"]: r for r in actual["cases"]} != {r["task_id"]: r for r in expected["cases"]}
            or len(actual["cases"]) != len(expected["cases"])):
        raise ValueError("stability summary differs from executed repetitions")
    return actual


def evaluate(config_path, plan_path, evaluation_root, label, adapter=None):
    config, plan = read(config_path), read(plan_path)
    manifest, tasks = load_dataset(config["dataset"])
    if manifest["dataset_hash"] != plan["dataset_hash"] or label not in plan["labels"]:
        raise ValueError("stability dataset/label mismatch")
    bundle, skills = load_bundle(config["bundle"], manifest["dataset_hash"])
    selected = {t.task_id: t for t in tasks if t.task_id in plan["task_hashes"]}
    if {k: task_hash(v) for k, v in selected.items()} != plan["task_hashes"] or any(t.split != "test" for t in selected.values()):
        raise ValueError("stability task mismatch")
    root = Path(evaluation_root)
    original = root / (label + "-test")
    parent = read(original / "identity.json")
    if (parent["model_settings"] != HFModelClient.settings_for(config, adapter, label)
            or parent["source_hash"] != digest({p.name: p.read_text(encoding="utf-8") for p in sorted(Path("skillforge").glob("*.py"))})
            or parent["bundle_hash"] != bundle["bundle_hash"] or not parent["gate"]
            or parent["config_hash"] != file_hash(config_path)):
        raise ValueError("stability must reuse exact main-test model and runtime")
    identity = {"parent": parent, "plan_sha256": file_hash(plan_path), "evaluator_sha256": file_hash(__file__)}
    folder = root / "stability" / label
    folder.mkdir(parents=True, exist_ok=True)
    if (folder / "identity.json").exists() and read(folder / "identity.json") != identity:
        raise ValueError("stability resume identity mismatch")
    atomic_json(folder / "identity.json", identity)
    runs = {}
    # Audit reusable evidence before loading a model.
    for key, task in selected.items():
        runs[key] = [read_checkpoint(original / "tasks" / (key + ".json"), parent, key, task_hash(task))]
        for repeat in range(2, plan["repeats"] + 1):
            path = folder / f"{key}-{repeat}.json"
            if path.exists():
                read_checkpoint(path, {**identity, "repeat": repeat}, key, task_hash(task))
    model = None
    try:
        completed = 0
        for key, task in selected.items():
            for repeat in range(2, plan["repeats"] + 1):
                path = folder / f"{key}-{repeat}.json"
                repeat_identity = {**identity, "repeat": repeat}
                if path.exists():
                    row = read_checkpoint(path, repeat_identity, key, task_hash(task))
                else:
                    if model is None:
                        model = HFModelClient(config_path, adapter, label)
                    env = Environment(fixture=task.fixture, faults=task.fixture.get("faults"))
                    try:
                        row = Runtime(model, skills=skills, verified=True).run(task, env)
                        if getattr(model, "fatal_error", None):
                            atomic_json(folder / "infrastructure_failure.json", {"error": model.fatal_error, "partial": row})
                            raise RuntimeError(model.fatal_error)
                        row = save_checkpoint(path, row, repeat_identity)
                    finally:
                        env.close()
                runs[key].append(row)
                completed += 1
                atomic_json(folder / "progress.json", {"completed": completed, "total": len(selected) * (plan["repeats"] - 1)})
        report = {"identity": identity, "label": label, **summarize(plan, runs)}
        atomic_json(folder / "evaluation.json", report)
        return report
    finally:
        if model is not None:
            model.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/training.cudnn.json")
    parser.add_argument("--plan", default="configs/stability.json")
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--label", choices=["Base", "SFT", "DPO"])
    parser.add_argument("--adapter")
    parser.add_argument("--root", default="results/post-training/main-v2")
    args = parser.parse_args()
    if args.prepare:
        print(json.dumps(prepare(args.config, args.plan), indent=2))
    else:
        if not args.label or ((args.label == "Base") != (args.adapter is None)):
            parser.error("Base has no adapter; SFT/DPO require --adapter")
        print(json.dumps(evaluate(args.config, args.plan, args.root, args.label, args.adapter), indent=2))
