"""Held-out deterministic-contract targets for likelihood reporting, never training."""
import argparse
import json
from collections import Counter
from pathlib import Path

from skillforge.dataset import load_dataset, task_hash, digest
from skillforge.environment import Environment
from skillforge.experiment import load_bundle, read_sources
from skillforge.model import ScriptedPolicy
from skillforge.runtime import Runtime
from skillforge.supervision import messages, write_jsonl
from skillforge.training import atomic_json, encode_example, collate_one, completion_logps
from skillforge.training_data import file_hash
from skillforge.evaluation_checkpoints import read_checkpoint, save_checkpoint
from skillforge.verifier import verify


def prepare(config_path, output):
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    manifest, tasks = load_dataset(config["dataset"])
    bundle, skills = load_bundle(config["bundle"], manifest["dataset_hash"])
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    trajectories, targets = [], []
    for task in [t for t in tasks if t.split == "validation"]:
        env = Environment(fixture=task.fixture, faults=task.fixture.get("faults"))
        try:
            record = Runtime(ScriptedPolicy(), skills=skills).run(task, env)
        finally:
            env.close()
        verdict = record["verification"]
        if not verdict["task_success"] or verdict["actual_policy_violation"]:
            raise ValueError("validation target teacher failed the outcome contract: " + task.task_id)
        trajectories.append(record)
        previous = None
        for step in record["steps"]:
            action = step.get("action")
            if not action or step.get("error") or step.get("result", {}).get("success") is False:
                continue
            encoded = json.dumps(action, sort_keys=True)
            if encoded == previous:
                continue
            previous = encoded
            target = {"task_id": task.task_id, "task_hash": task_hash(task), "step_id": step["step_id"],
                "split": "validation", "source_trajectory_id": record["trajectory_id"],
                "messages": messages(step["context"], action), "action_type": action["type"]}
            target["example_id"] = digest({k: v for k, v in target.items() if k != "source_trajectory_id"})
            targets.append(target)
    report = {"split": "validation", "dataset_hash": manifest["dataset_hash"], "bundle_hash": bundle["bundle_hash"],
        "tasks": len(trajectories), "examples": len(targets), "action_counts": dict(Counter(t["action_type"] for t in targets)),
        "origin": "deterministic_contract_teacher", "teacher_llm_calls": 0,
        "scope": "held-out completion likelihood only; excluded from every optimization corpus",
        "files": {"trajectories.jsonl": write_jsonl(root / "trajectories.jsonl", trajectories),
            "targets.jsonl": write_jsonl(root / "targets.jsonl", targets)}}
    atomic_json(root / "manifest.json", report)
    return report


def load_targets(output, tasks, dataset_hash, bundle_hash):
    root = Path(output)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    known = {t.task_id: t for t in tasks if t.split == "validation"}
    if manifest["split"] != "validation" or manifest["dataset_hash"] != dataset_hash or manifest["bundle_hash"] != bundle_hash:
        raise ValueError("validation likelihood corpus identity mismatch")
    for name in ("trajectories.jsonl", "targets.jsonl"):
        if file_hash(root / name) != manifest["files"][name]:
            raise ValueError("validation likelihood corpus file hash mismatch")
    records = read_sources(root / "trajectories.jsonl")
    if len(records) != len(known) or {r["task_id"] for r in records} != set(known):
        raise ValueError("validation teacher must cover exactly the held-out task set")
    indexed = {}
    for record in records:
        task = known[record["task_id"]]
        if record["split"] != "validation" or record["task_hash"] != task_hash(task) or record["metrics"]["llm_calls"] != 0:
            raise ValueError("validation teacher task/provenance mismatch")
        verdict = verify(task, record["initial_state"], record["final_state"], record["tool_audit"], record["outcome"])
        if verdict != record["verification"] or not verdict["task_success"] or verdict["actual_policy_violation"]:
            raise ValueError("invalid validation teacher outcome")
        indexed[record["trajectory_id"]] = record
    targets = read_sources(root / "targets.jsonl")
    if len(targets) != manifest["examples"] or len({r["example_id"] for r in targets}) != len(targets):
        raise ValueError("validation target count/identity mismatch")
    for row in targets:
        if row["split"] != "validation" or row["task_id"] not in known or row["task_hash"] != task_hash(known[row["task_id"]]):
            raise ValueError("likelihood targets must remain in validation")
        record = indexed[row["source_trajectory_id"]]
        if record["task_id"] != row["task_id"]:
            raise ValueError("validation target source task mismatch")
        step = next(s for s in record["steps"] if s["step_id"] == row["step_id"])
        if (step.get("error") or step.get("result", {}).get("success") is False
                or row["messages"] != messages(step["context"], step["action"])
                or row["example_id"] != digest({k: v for k, v in row.items() if k not in {"example_id", "source_trajectory_id"}})):
            raise ValueError("validation target differs from verified action")
    return manifest, targets


def score(get_model, targets, identity, root, max_length):
    import torch
    folder = Path(root) / "validation_loss"
    folder.mkdir(exist_ok=True)
    likelihood_identity = {**identity, "phase": "validation_loss"}
    scores = []
    for row in targets:
        path = folder / (row["example_id"] + ".json")
        if path.exists():
            result = read_checkpoint(path, likelihood_identity, row["task_id"], row["task_hash"])
        else:
            model = get_model()
            example = encode_example(model.tokenizer, row["messages"][:-1], row["messages"][-1]["content"], max_length)
            result = {"task_id": row["task_id"], "task_hash": row["task_hash"], "example_id": row["example_id"], "action_type": row["action_type"]}
            if example is None:
                result.update(skipped=True, reason="exceeds_frozen_context_limit")
            else:
                batch = {k: v.to("cuda") for k, v in collate_one([example]).items()}
                with torch.no_grad(), torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                    sums, counts = completion_logps(model.network, batch)
                result.update(skipped=False, log_probability=float(sums.item()), target_tokens=int(counts.item()))
            result = save_checkpoint(path, result, likelihood_identity)
        scores.append(result)
        atomic_json(Path(root) / "progress.json", {"phase": "validation_loss", "completed": len(scores), "total": len(targets)})
    valid = [r for r in scores if not r["skipped"]]
    if not valid:
        raise ValueError("no held-out likelihood targets were evaluated")
    return {"token_weighted_loss": -sum(r["log_probability"] for r in valid) / sum(r["target_tokens"] for r in valid),
        "example_mean_loss": sum(-r["log_probability"] / r["target_tokens"] for r in valid) / len(valid),
        "examples": len(valid), "target_tokens": sum(r["target_tokens"] for r in valid),
        "skipped_example_ids": [r["example_id"] for r in scores if r["skipped"]],
        "origin": "held-out deterministic contract targets; not model-generated validation success"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/training.cudnn.json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.config, args.output), indent=2))
