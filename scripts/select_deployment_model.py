"""Choose the product adapter using the declared validation-only policy."""
import json
from pathlib import Path

from scripts.audit_validation import audit
from scripts.coordinator_io import atomic_json
from skillforge.training_data import file_hash


def choose(reports, policy):
    if policy != {"candidates": ["SFT", "DPO"], "split": "validation", "require_zero_actual_violations": True,
            "ranking": ["task_success_rate_desc", "decision_accuracy_desc", "average_llm_calls_asc", "candidate_order"], "scope": policy.get("scope")}:
        raise ValueError("unsupported deployment selection policy")
    candidates = []
    for index, label in enumerate(policy["candidates"]):
        report = reports[label]
        if report["split"] != "validation":
            raise ValueError("deployment selection cannot consume test scores")
        summary = report["full_system"]
        valid = [row for group in report["decision_level"] for row in group["cases"] if not row.get("skipped")]
        accuracy = sum(r["correct"] for r in valid) / len(valid) if valid else -1
        candidates.append({"label": label, "eligible": summary["actual_policy_violation_rate"] == 0,
            "eoc_pass_rate": summary["task_success_rate"], "decision_accuracy": accuracy,
            "average_llm_calls": summary["average_llm_calls"], "tie_order": index})
    eligible = [r for r in candidates if r["eligible"]]
    if not eligible:
        raise ValueError("no trained candidate passed the actual-violation eligibility rule")
    selected = max(eligible, key=lambda r: (r["eoc_pass_rate"], r["decision_accuracy"], -r["average_llm_calls"], -r["tie_order"]))
    return {"label": selected["label"], "candidates": candidates, "selection_split": "validation"}


def select():
    plan = json.loads(Path("configs/training-runs.json").read_text(encoding="utf-8"))
    policy_path = Path("configs/deployment-selection.json")
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    root = Path(plan["evaluation_root"])
    reports = {label: audit(root / (label + "-validation"), plan["config"], plan["validation_loss_data"]) for label in policy["candidates"]}
    selection = {**choose(reports, policy), "policy_sha256": file_hash(policy_path),
        "validation_reports": {label: file_hash(root / (label + "-validation") / "evaluation.json") for label in reports},
        "adapter_sha256": {label: reports[label]["model_settings"]["adapter_sha256"] for label in reports}, "scope": policy["scope"]}
    target = root / "deployment-selection.json"
    if target.exists() and json.loads(target.read_text(encoding="utf-8")) != selection:
        raise ValueError("deployment selection changed after it was frozen")
    atomic_json(target, selection)
    return selection


if __name__ == "__main__":
    print(json.dumps(select(), indent=2))
