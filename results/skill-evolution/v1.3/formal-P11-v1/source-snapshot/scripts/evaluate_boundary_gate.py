"""CPU-only paired three-state boundary evaluation and clustered intervals."""
from collections import Counter
import copy
import json
from pathlib import Path
import random

from scripts.boundary_learning import features, oracle, procedure_hash
from scripts.coordinator_io import atomic_json
from scripts.prepare_boundary_study import load_prepared, probe
from skillforge.dataset import digest
from skillforge.environment import Environment, ToolError
from skillforge.schemas import SkillContract
from skillforge.skills import gate, hydrate
from skillforge.training_data import file_hash


def masked(task, state, mask):
    visible = {**state, **features(task.family, state, task.parameters)}
    if mask == "empty":
        return {}
    prefix = "customer." if mask == "hide_customer" else "payment." if task.family == "refund" else "shipment."
    if mask != "full":
        visible = {k: v for k, v in visible.items() if not k.startswith(prefix) and not (prefix == "payment." and k.startswith("refund."))}
    return visible


def measure(task, skill, mask, retry_budget):
    env = Environment(fixture=task.fixture)
    try:
        state = masked(task, env.snapshot(), mask)
        before = copy.deepcopy(state)
        label = oracle(task.family, state, task.parameters)
        full_label = oracle(task.family, masked(task, env.snapshot(), "full"), task.parameters)
        initial = gate(skill, state, task.parameters)
        errors = []
        def call(name, args, key):
            for attempt in range(retry_budget + 1):
                try:
                    return env.call(name, args, task.customer_id, key)
                except ToolError as exc:
                    if exc.code not in {"timeout", "temporary_unavailable"} or attempt == retry_budget:
                        raise
        try:
            hydrate(skill, state, task.parameters, call, task.task_id + ":gate")
        except ToolError as exc:
            errors.append(exc.code)
        return {"task_id": task.task_id, "split": task.split, "cluster": task.structure_id, "mask": mask,
                "full_truth": full_label, "partial_truth": label, "initial_prediction": initial.model_dump(),
                "final_prediction": gate(skill, state, task.parameters).model_dump(), "observations_before": before,
                "observations_after": state, "queries": len(env.audit), "query_errors": errors, "audit": env.audit}
    finally:
        env.close()


def rate(n, d):
    return n / d if d else None


def summarize(rows):
    full = [r for r in rows if r["mask"] == "full"]
    positives = [r for r in full if r["full_truth"] == "APPLICABLE"]
    negatives = [r for r in full if r["full_truth"] == "INAPPLICABLE"]
    return {"full_contexts": len(full), "positive_contexts": len(positives), "negative_contexts": len(negatives),
            "false_allow_rate": rate(sum(r["initial_prediction"]["status"] == "APPLICABLE" for r in negatives), len(negatives)),
            "false_block_rate": rate(sum(r["initial_prediction"]["status"] == "INAPPLICABLE" for r in positives), len(positives)),
            "normal_allow_coverage": rate(sum(r["initial_prediction"]["status"] == "APPLICABLE" for r in positives), len(positives)),
            "all_masks": len(rows), "initial_unknown": sum(r["initial_prediction"]["status"] == "UNKNOWN" for r in rows),
            "remaining_unknown": sum(r["final_prediction"]["status"] == "UNKNOWN" for r in rows),
            "queries": sum(r["queries"] for r in rows), "query_errors": sum(len(r["query_errors"]) for r in rows),
            "partial_confusion": dict(Counter(r["partial_truth"] + "->" + r["initial_prediction"]["status"] for r in rows)),
            "resolved_confusion": dict(Counter(r["full_truth"] + "->" + r["final_prediction"]["status"] for r in rows))}


def clustered_interval(values, seed=20260930, repeats=2000):
    # Each entry is a cluster-level mean, never an observation-mask replica.
    if not values:
        return {"clusters": 0, "difference": None, "ci95": None}
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(values) for _ in values) / len(values) for _ in range(repeats))
    return {"clusters": len(values), "difference": sum(values) / len(values),
            "ci95": [means[int(.025 * (repeats - 1))], means[int(.975 * (repeats - 1))]],
            "scope": "paired scenario-cluster percentile bootstrap; conditional synthetic-sample uncertainty"}


def paired(left, right, truth, prediction, target, plan):
    l = {r["task_id"]: r for r in left if r["mask"] == "full" and r["full_truth"] == truth}
    r = {v["task_id"]: v for v in right if v["mask"] == "full" and v["full_truth"] == truth}
    if set(l) != set(r):
        raise ValueError("paired Gate coverage differs")
    clusters = {}
    for tid, row in l.items():
        clusters.setdefault(row["cluster"], []).append(int(row[prediction]["status"] == target) - int(r[tid][prediction]["status"] == target))
    return clustered_interval([sum(v) / len(v) for v in clusters.values()], plan["seed"], plan["bootstrap_samples"])


def evaluate(plan_path="configs/boundary-study.json", audit_only=False):
    plan, root, tasks, boundaries, preparation = load_prepared(plan_path)
    selected = [t for t in tasks if t.split in {"validation", "test"}]
    # Oracle is checked by actual execution for every evaluated task, after fit.
    crosschecks = []
    for task in selected:
        crosschecks.append(probe(task, SkillContract.model_validate(boundaries["groups"]["C"][task.family])))
    rows, summaries, paired_results = {}, {}, {}
    for group in "ABCD":
        rows[group] = []
        for task in selected:
            skill = SkillContract.model_validate(boundaries["groups"][group][task.family])
            if procedure_hash(skill) != boundaries["procedure_hashes"][task.family]:
                raise ValueError("procedure differs between boundary groups")
            for mask in ("full", "empty", "hide_customer", "hide_payment_or_shipment"):
                rows[group].append(measure(task, skill, mask, plan["retry_budget"]))
        summaries[group] = {split: summarize([r for r in rows[group] if r["split"] == split]) for split in ("validation", "test")}
    for left, right in plan["primary_comparisons"]:
        l, r = ([row for row in rows[g] if row["split"] == "test"] for g in (left, right))
        false_allow = paired(l, r, "INAPPLICABLE", "initial_prediction", "APPLICABLE", plan)
        false_block = paired(l, r, "APPLICABLE", "initial_prediction", "INAPPLICABLE", plan)
        paired_results[left + "-" + right] = {"false_allow": false_allow, "false_block": false_block,
            "supports_boundary_gain": bool(false_allow["ci95"] and false_block["ci95"] and false_allow["ci95"][1] < 0 and false_block["ci95"][1] <= plan["false_block_margin"]),
            "system_gain_claim": "pending independent real-model system outcomes"}
    report = {"identity": {"preparation_sha256": file_hash(root / "preparation.json"), "evaluator_sha256": file_hash(__file__)},
              "summary": summaries, "comparisons": paired_results}
    # Deterministic query results omit latency; execution crosschecks contain UUIDs
    # and are integrity bound separately, not regenerated for byte equality.
    for group in rows:
        for row in rows[group]:
            for event in row["audit"]:
                event.pop("latency_ms", None)
    if audit_only:
        if report != json.loads((root / "gate-report.json").read_text(encoding="utf-8")) or rows != json.loads((root / "gate-rows.json").read_text(encoding="utf-8")):
            raise ValueError("Gate report or rows differ from deterministic replay")
    else:
        if (root / "gate-report.json").exists():
            raise ValueError("Gate report already frozen; use audit")
        atomic_json(root / "gate-rows.json", rows)
        atomic_json(root / "oracle-executions.json", crosschecks)
        atomic_json(root / "gate-report.json", report)
    return report


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args()
    print(json.dumps(evaluate(audit_only=args.audit_only), ensure_ascii=False))
