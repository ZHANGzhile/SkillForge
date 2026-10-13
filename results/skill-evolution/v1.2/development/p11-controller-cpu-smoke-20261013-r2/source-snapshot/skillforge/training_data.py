"""Fail-closed audits for the mixed real/explicit-teacher post-training corpus."""
import hashlib
import json
from pathlib import Path

from .dataset import digest, load_dataset, task_hash
from .experiment import load_bundle, read_sources
from .learning import make_preference
from .provenance import audit_sources
from .schemas import Action
from .supervision import messages
from .verifier import verify


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_training_data(dataset, bundle_path, real_dir, supervision_dir, baseline_path):
    manifest, tasks = load_dataset(dataset)
    known = {t.task_id: t for t in tasks if t.split == "train"}
    bundle, _ = load_bundle(bundle_path, manifest["dataset_hash"])
    baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
    if baseline["config"]["engineering_only"] or baseline["config"]["dataset_hash"] != manifest["dataset_hash"]:
        raise ValueError("post-training requires a real same-dataset baseline")
    if not {"B0", "B1", "B2", "B3"} <= {s["label"] for s in baseline["summary"]}:
        raise ValueError("post-training requires complete B0-B3 results")
    if any(s["tasks"] != manifest["audit"]["counts"]["test"] * s["repeat_count"] for s in baseline["summary"]):
        raise ValueError("baseline task coverage mismatch")
    real_root, teacher_root = Path(real_dir), Path(supervision_dir)
    real = json.loads((real_root / "audit.json").read_text(encoding="utf-8"))
    teacher = json.loads((teacher_root / "manifest.json").read_text(encoding="utf-8"))
    if real["dataset_hash"] != manifest["dataset_hash"] or teacher["dataset_hash"] != manifest["dataset_hash"] or teacher["bundle_hash"] != bundle["bundle_hash"]:
        raise ValueError("training manifest dataset/bundle mismatch")
    if file_hash(real_root / "train.jsonl") != real["train_sha256"] or file_hash(baseline_path) != real["baseline_sha256"]:
        raise ValueError("real training data or baseline hash mismatch")
    for name, expected in teacher["files"].items():
        if Path(name).name != name or file_hash(teacher_root / name) != expected:
            raise ValueError("teacher artifact hash mismatch")
    runtime = read_sources(teacher_root / "runtime.jsonl")
    audit_sources(runtime, tasks, allow_engineering=True)
    by_trajectory = {r["trajectory_id"]: r for r in runtime}
    evidence = read_sources(teacher_root / "counterfactuals.jsonl")
    by_evidence = {}
    for row in evidence:
        task = known.get(row["task_id"])
        if task is None or row["split"] != "train" or row["task_hash"] != task_hash(task):
            raise ValueError("counterfactual evidence must match frozen train tasks")
        if digest({k: v for k, v in row.items() if k != "evidence_id"}) != row["evidence_id"]:
            raise ValueError("counterfactual evidence content hash mismatch")
        verdict = verify(task, row["initial_state"], row["final_state"], row["tool_audit"], row["outcome"])
        correct = verdict["task_success"] and not verdict["attempted_policy_violation"] and not verdict["actual_policy_violation"]
        if correct != row["verified_correct"] or verdict != row["verification"]:
            raise ValueError("counterfactual verdict mismatch")
        by_evidence[row["evidence_id"]] = row
    rows = []
    for row in read_sources(real_root / "train.jsonl"):
        if row["split"] != "train" or row["protocol"] != "free_action":
            raise ValueError("real SFT source split/protocol mismatch")
        for source in row["evidence"]:
            if source["task_id"] not in known or task_hash(known[source["task_id"]]) != source["task_hash"]:
                raise ValueError("real SFT example must match frozen train task")
        rows.append({**row, "supervision_origin": "real_model_trajectory"})
    for row in read_sources(teacher_root / "sft.jsonl"):
        if row["split"] != "train" or row["task_id"] not in known or row["task_hash"] != task_hash(known[row["task_id"]]):
            raise ValueError("teacher SFT example must match frozen train task")
        if row["supervision_origin"] == "deterministic_contract_teacher":
            trajectory = by_trajectory[row["source_trajectory_id"]]
            step = next(s for s in trajectory["steps"] if s["step_id"] == row["source_step_id"])
            if not trajectory["verification"]["task_success"] or step.get("error") or step.get("result", {}).get("success") is False:
                raise ValueError("teacher target was not verified")
            expected = messages(step["context"], step["action"])
        elif row["supervision_origin"] == "executed_contract_counterfactual":
            source = by_evidence[row["evidence_id"]]
            if not source["verified_correct"]:
                raise ValueError("negative evidence cannot be an SFT target")
            expected = messages(source["prompt"], source["action"])
        else:
            raise ValueError("unrecognized teacher origin")
        if expected != row["messages"]:
            raise ValueError("teacher target/context differs from verified execution")
        rows.append(row)
    unique = {}
    for row in rows:
        if [m["role"] for m in row["messages"]] != ["system", "user", "assistant"]:
            raise ValueError("SFT requires one explicit assistant target")
        Action.model_validate_json(row["messages"][-1]["content"])
        if set(json.loads(row["messages"][1]["content"])) & {"expected", "fixture", "initial_state", "final_state", "verification"}:
            raise ValueError("oracle fields cannot enter training prompts")
        key = digest(row["messages"])
        if key in unique:
            unique[key]["origins"].append(row["supervision_origin"])
        else:
            unique[key] = {"example_id": key, "messages": row["messages"], "origins": [row["supervision_origin"]]}
    pairs = []
    for pair in read_sources(teacher_root / "dpo.jsonl"):
        chosen, rejected = [by_evidence[e] for e in pair["evidence"]]
        verified_pair = make_preference(chosen, rejected)
        if any(pair[k] != v for k, v in verified_pair.items()) or chosen["initial_state"] != rejected["initial_state"]:
            raise ValueError("DPO requires identical context and pre-action state")
        if pair["messages"] != messages(pair["prompt"]):
            raise ValueError("DPO rendered prompt differs from evidence")
        pairs.append({"messages": pair["messages"], "chosen": json.dumps(pair["chosen"], ensure_ascii=False),
            "rejected": json.dumps(pair["rejected"], ensure_ascii=False), "evidence": pair["evidence"],
            "snapshot_id": pair["snapshot_id"], "task_id": pair["task_id"]})
    summary = {"dataset_hash": manifest["dataset_hash"], "bundle_hash": bundle["bundle_hash"],
        "baseline_hash": file_hash(baseline_path), "real_manifest_hash": file_hash(real_root / "audit.json"),
        "teacher_manifest_hash": file_hash(teacher_root / "manifest.json"),
        "sft_examples": len(unique), "dpo_pairs": len(pairs), "supervision": "real trajectories + explicitly labelled deterministic contract teacher"}
    summary["corpus_hash"] = digest({"sft": list(unique.values()), "dpo": pairs, "audit": summary})
    return list(unique.values()), pairs, summary
