"""Audit real train trajectories and export exact free-Action chat targets.

Does not train a model or convert menu choices into invented free-Action evidence.
"""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from skillforge.dataset import digest, load_dataset
from skillforge.experiment import read_sources
from skillforge.learning import build_sft, context_hash
from skillforge.provenance import audit_sources
from skillforge.schemas import Action


def export(dataset, source, baseline, output):
    manifest, tasks = load_dataset(dataset)
    records = read_sources(source)
    audit = audit_sources(records, tasks, allow_engineering=False)
    report = json.loads(Path(baseline).read_text(encoding="utf-8"))
    if report["config"]["engineering_only"] or report["config"]["dataset_hash"] != manifest["dataset_hash"]:
        raise ValueError("real same-dataset B0-B3 results are required before post-training")
    labels = {row["label"] for row in report["summary"]}
    if not {"B0", "B1", "B2", "B3"} <= labels:
        raise ValueError("B0-B3 baseline is incomplete")
    if any(row["tasks"] != manifest["audit"]["counts"]["test"] * row["repeat_count"] for row in report["summary"]):
        raise ValueError("baseline task count does not match the frozen test split")
    by_id = {r["trajectory_id"]: r for r in records}
    for record in records:
        settings = record.get("model_settings", {})
        if settings.get("decision_protocol") or record.get("protocol", "free_action") != "free_action":
            raise ValueError("menu and free-Action training evidence must be exported separately")
        prompt = settings.get("system_prompt")
        if not prompt or hashlib.sha256(prompt.encode()).hexdigest() != settings.get("prompt_sha256"):
            raise ValueError("source system prompt is missing or its hash does not match")
    examples, dedup = [], {}
    filtered = build_sft(records)
    for row in filtered:
        source_record = by_id[row["source_trajectory_id"]]
        Action.model_validate(row["target"])
        context = row["prompt"]
        if set(context) & {"expected", "fixture", "initial_state", "final_state", "verification"}:
            raise ValueError("oracle state cannot enter the model prompt")
        messages = [{"role": "system", "content": source_record["model_settings"]["system_prompt"]},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
            {"role": "assistant", "content": json.dumps(row["target"], ensure_ascii=False)}]
        evidence = {"trajectory_id": row["source_trajectory_id"], "step_id": row["source_step_id"],
            "task_id": source_record["task_id"], "task_hash": source_record["task_hash"]}
        key = digest(messages)
        if key in dedup:
            dedup[key]["evidence"].append(evidence)
            continue
        example = {"example_id": key, "split": "train", "protocol": "free_action", "messages": messages,
            "context_hash": context_hash(context), "action_type": row["target"]["type"],
            "family": source_record["task_family"], "evidence": [evidence]}
        dedup[key] = example
        examples.append(example)
    counts = dict(Counter(r["action_type"] for r in examples))
    export_report = {"format": "skillforge-sft-chat-v1", "dataset_hash": manifest["dataset_hash"],
        "source_sha256": hashlib.sha256(Path(source).read_bytes()).hexdigest(),
        "baseline_sha256": hashlib.sha256(Path(baseline).read_bytes()).hexdigest(), "source_audit": audit,
        "source_actions": sum(len(r["steps"]) for r in records), "accepted_before_dedup": len(filtered),
        "examples": len(examples), "action_counts": counts, "family_counts": dict(Counter(r["family"] for r in examples)),
        "protocol": "free_action", "label_policy": "assistant completion only; preserve exact observed history",
        "trained": False, "ready_for_skill_learning": counts.get("skill", 0) > 0,
        "remaining": ["verified Skill-action supervision coverage", "same-context counterfactual DPO evidence", "training and held-out evaluation"],
        "limitations": ["source audit verifies manifest/verdict consistency, not cryptographic model attestation",
                        "historical free-Action corpus alone may not teach Skill selection",
                        "refusal/escalation samples require their original Expected Outcome Contract to pass"]}
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    content = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in examples)
    (root / "train.jsonl").write_bytes(content.encode("utf-8"))
    export_report["train_sha256"] = hashlib.sha256(content.encode()).hexdigest()
    (root / "audit.json").write_text(json.dumps(export_report, ensure_ascii=False, indent=2), encoding="utf-8")
    return export_report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset", "source", "baseline", "output"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    print(json.dumps(export(**vars(args)), ensure_ascii=False, indent=2))
