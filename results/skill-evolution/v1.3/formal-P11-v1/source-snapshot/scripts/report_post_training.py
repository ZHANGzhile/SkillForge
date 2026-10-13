import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from skillforge.training import atomic_json
from skillforge.benchmark import summarize
from skillforge.evaluation_checkpoints import read_checkpoint
from scripts.error_analysis import summarize_diagnostics


def summarize_runs(root):
    root = Path(root)
    rows, results, identities, errors = [], {}, [], {}
    validation_corpora = set()
    strata, families, outcomes, failures, diagnostics = {}, {}, {}, {}, {}
    frozen = json.loads((root / "frozen_models.json").read_text(encoding="utf-8"))
    for label in ["Base", "SFT", "DPO", "DPO-no-gate"]:
        folder = root / (label + "-test")
        report = json.loads((folder / "evaluation.json").read_text(encoding="utf-8"))
        identity = json.loads((folder / "identity.json").read_text(encoding="utf-8"))
        model_label = label.removesuffix("-no-gate")
        if (any(report.get(k) != value for k, value in identity.items()) or identity["label"] != model_label
                or identity["split"] != "test" or identity["gate"] != (label != "DPO-no-gate")
                or identity["config_hash"] != frozen["config_hash"]
                or identity["model_settings"]["adapter_sha256"] != frozen["adapters"].get(model_label)):
            raise ValueError("evaluation report or frozen model identity mismatch")
        expected = identity["task_hashes"]
        if {p.stem for p in (folder / "tasks").glob("*.json")} != set(expected):
            raise ValueError("evaluation must cover exactly the frozen task set")
        records = [read_checkpoint(folder / "tasks" / (key + ".json"), identity, key, value) for key, value in expected.items()]
        actual_summary = summarize(records)
        if any(report["full_system"].get(k) != value for k, value in actual_summary.items()):
            raise ValueError("evaluation summary differs from executed tasks")
        actual_decisions = []
        for skill_id, task_ids in identity["decision_tasks"].items():
            for task_id in task_ids:
                actual_decisions.append(read_checkpoint(folder / "decisions" / (skill_id + "-" + task_id + ".json"),
                    {**identity, "skill_id": skill_id}, task_id))
        if actual_decisions != [row for group in report["decision_level"] for row in group["cases"]]:
            raise ValueError("decision report differs from executed probes")
        for group in report["decision_level"]:
            valid = [r for r in group["cases"] if not r.get("skipped")]
            accuracy = sum(r["correct"] for r in valid) / len(valid) if valid else None
            if group["evaluated"] != len(valid) or group["skipped"] != len(group["cases"]) - len(valid) or group["accuracy"] != accuracy:
                raise ValueError("decision summary differs from executed probes")
        by_task = {r["task_id"]: r for r in records}
        if len(by_task) != len(records) or len(records) != report["full_system"]["tasks"]:
            raise ValueError("duplicate or missing task records")
        results[label] = by_task
        identities.append({"dataset": report["dataset_hash"], "bundle": report["bundle_hash"],
            "runtime_config": identity["runtime_config"], "source_hash": identity["source_hash"],
            "evaluator_hash": identity["evaluator_hash"], "task_hashes": expected,
            "settings": {k: v for k, v in report["model_settings"].items() if k not in {"model", "adapter_sha256"}}})
        evaluated = sum(d["evaluated"] for d in report["decision_level"])
        correct = sum(sum(r.get("correct", False) for r in d["cases"] if not r.get("skipped")) for d in report["decision_level"])
        validation_path = root / (model_label + "-validation") / "evaluation.json"
        likelihood = None
        if validation_path.is_file():
            validation = json.loads(validation_path.read_text(encoding="utf-8"))
            if validation["model_settings"] != report["model_settings"]:
                raise ValueError("validation/test model settings mismatch")
            if validation.get("validation_loss"):
                likelihood = validation["validation_loss"]["token_weighted_loss"]
                validation_corpora.add(validation["likelihood_manifest_sha256"])
        rows.append({**report["full_system"], "label": label, "decision_evaluated": evaluated,
            "decision_accuracy": correct / evaluated if evaluated else None, "validation_token_loss": likelihood})
        errors[label] = dict(Counter(category for r in records for category in r["error_categories"]))
        diagnostics[label] = summarize_diagnostics(records)
        strata[label] = {level: summarize([r for r in records if r["level"] == level]) for level in sorted({r["level"] for r in records})}
        families[label] = {family: summarize([r for r in records if r["task_family"] == family]) for family in sorted({r["task_family"] for r in records})}
        outcomes[label] = {"observed": dict(Counter(r["outcome"] for r in records)),
            "correct_under_expected_outcome_contract": dict(Counter(r["outcome"] for r in records if r["verification"]["task_success"]))}
        failures[label] = [{"task_id": r["task_id"], "family": r["task_family"], "level": r["level"], "outcome": r["outcome"],
            "reasons": r["verification"]["reason"], "categories": r["error_categories"]} for r in records if not r["verification"]["task_success"]]
    if any(identity != identities[0] for identity in identities):
        raise ValueError("model comparisons must share data, contracts and serving protocol")
    if len(validation_corpora) > 1:
        raise ValueError("validation loss must use the same held-out targets")
    base = results["Base"]
    paired = {}
    for label, group in results.items():
        if set(group) != set(base) or any(group[k]["task_hash"] != base[k]["task_hash"] for k in base):
            raise ValueError("paired evaluation task identity mismatch")
        paired[label] = {
            "helped": sum(group[k]["verification"]["task_success"] and not base[k]["verification"]["task_success"] for k in base),
            "hurt": sum(base[k]["verification"]["task_success"] and not group[k]["verification"]["task_success"] for k in base)}
    output = {"summary": rows, "paired_vs_base": paired, "error_categories": errors,
        "by_level": strata, "by_family": families, "outcome_breakdown": outcomes, "failed_tasks": failures,
        "supplementary_diagnostics": diagnostics,
        "identity": identities[0], "scope": "single-seed bounded synthetic research evaluation",
        "limitations": ["NF4/HF serving differs from the original Ollama/Q4 baseline",
            "SFT combines real train trajectories and explicitly labelled deterministic contract supervision",
            "DPO uses executed same-context candidate-action preferences",
            "validation likelihood uses separately frozen deterministic contract targets, never optimizer data",
            "legacy attempted_policy_violation_rate counts all tool failures; model-attributed and automatic-gate rates are reported separately",
            "paired changes are descriptive; causal NTR and significance are not asserted"]}
    atomic_json(root / "comparison.json", output)
    with (root / "comparison.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    print(json.dumps(summarize_runs(args.root)["summary"], indent=2))
