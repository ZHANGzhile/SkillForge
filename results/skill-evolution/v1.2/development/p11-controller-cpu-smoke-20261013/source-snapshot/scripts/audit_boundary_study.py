"""Portable, read-only verifier for the frozen boundary-study artifacts.

Preparation v1 recorded two absolute source paths. Only those known paths are
mapped to repository-relative files; their original bytes/hashes are required.
No frozen identity, checkpoint or original evaluator is rewritten.
"""
import argparse
import json
from pathlib import Path

from scripts.boundary_learning import public_contract, procedure_hash
from scripts.evaluate_boundary_gate import measure, paired, summarize
from scripts.evaluate_boundary_system import MODES, validate
from scripts.evaluate_reuse_ablation import read
from skillforge.dataset import digest, task_hash
from skillforge.evaluation_checkpoints import read_checkpoint
from skillforge.schemas import SkillContract, Task
from skillforge.training_data import file_hash


def load_prepared(plan_path="configs/boundary-study.json"):
    plan = read(plan_path)
    root, dataset = Path(plan["output"]), Path(plan["dataset"])
    identity = read(root / "preparation.json")
    checks = {plan_path: identity["plan_sha256"], str(dataset / "manifest.json"): identity["manifest_sha256"],
              plan["bundle"]: identity["source_bundle_sha256"]}
    permitted = {"scripts/prepare_boundary_study.py", "scripts/boundary_learning.py"}
    mapped = {}
    for recorded, expected in identity["sources"].items():
        matches = [p for p in permitted if recorded.replace("\\", "/").endswith("/" + p) or recorded == p]
        if len(matches) != 1 or matches[0] in mapped:
            raise ValueError("unrecognized or duplicate frozen source path")
        mapped[matches[0]] = expected
    if set(mapped) != permitted:
        raise ValueError("missing frozen source identity")
    checks.update(mapped)
    checks.update({str(root / n): h for n, h in identity["artifacts"].items()})
    manifest = read(dataset / "manifest.json")
    checks.update({str(dataset / n): h for n, h in manifest["files"].items()})
    if any(file_hash(p) != h for p, h in checks.items()):
        raise ValueError("frozen artifact/source hash mismatch")
    if digest({p.name: p.read_text(encoding="utf-8") for p in sorted(Path("skillforge").glob("*.py"))}) != identity["core_hash"]:
        raise ValueError("core source hash mismatch")
    tasks = [Task.model_validate_json(line) for s in ("train", "validation", "test") for line in (dataset / (s + ".jsonl")).read_text(encoding="utf-8").splitlines()]
    if {t.task_id: task_hash(t) for t in tasks} != manifest["task_hashes"]:
        raise ValueError("dataset coverage/hash mismatch")
    return plan, root, tasks, read(root / "boundaries.json"), identity


def audit_gate(plan_path="configs/boundary-study.json", audit_only=True):
    if not audit_only:
        raise ValueError("portable verifier is read-only")
    plan, root, tasks, boundaries, _ = load_prepared(plan_path)
    rows, summaries, comparisons = {}, {}, {}
    for group in "ABCD":
        rows[group] = []
        for task in [t for t in tasks if t.split in {"validation", "test"}]:
            skill = SkillContract.model_validate(boundaries["groups"][group][task.family])
            if procedure_hash(skill) != boundaries["procedure_hashes"][task.family]:
                raise ValueError("procedure changed")
            for mask in ("full", "empty", "hide_customer", "hide_payment_or_shipment"):
                row = measure(task, skill, mask, plan["retry_budget"])
                for event in row["audit"]:
                    event.pop("latency_ms", None)
                rows[group].append(row)
        summaries[group] = {s: summarize([r for r in rows[group] if r["split"] == s]) for s in ("validation", "test")}
    for left, right in plan["primary_comparisons"]:
        l, r = ([v for v in rows[g] if v["split"] == "test"] for g in (left, right))
        fa = paired(l, r, "INAPPLICABLE", "initial_prediction", "APPLICABLE", plan)
        fb = paired(l, r, "APPLICABLE", "initial_prediction", "INAPPLICABLE", plan)
        comparisons[left + "-" + right] = {"false_allow": fa, "false_block": fb,
            "supports_boundary_gain": bool(fa["ci95"] and fb["ci95"] and fa["ci95"][1] < 0 and fb["ci95"][1] <= plan["false_block_margin"]),
            "system_gain_claim": "pending independent real-model system outcomes"}
    result = {"identity": {"preparation_sha256": file_hash(root / "preparation.json"), "evaluator_sha256": file_hash("scripts/evaluate_boundary_gate.py")},
              "summary": summaries, "comparisons": comparisons}
    if result != read(root / "gate-report.json") or rows != read(root / "gate-rows.json"):
        raise ValueError("portable Gate replay differs from frozen results")
    return result


def audit_system(plan_path="configs/boundary-study.json", audit_only=True):
    if not audit_only:
        raise ValueError("portable verifier is read-only")
    plan, parent, tasks, boundaries, _ = load_prepared(plan_path)
    root, tasks = parent / "system", [t for t in tasks if t.split == "test"]
    if not (root / "completed.json").exists():
        raise ValueError("complete system experiment required")
    identity = {"preparation_sha256": file_hash(parent / "preparation.json"), "reference_sha256": file_hash(plan["reference"]),
        "profile_sha256": file_hash(plan["client_profile"]), "model_settings": read(plan["reference"])["model_settings"],
        "code": {p: file_hash(p) for p in ("scripts/evaluate_boundary_system.py", "scripts/boundary_runtime.py", "scripts/evaluate_reuse_ablation.py")}}
    keys, owners, aliases = {}, {}, {}
    for task in tasks:
        for group in "ABCD":
            contract = public_contract(SkillContract.model_validate(boundaries["groups"][group][task.family]))
            for mode in MODES:
                key = task.task_id + "-" + group + "-" + mode
                fingerprint = digest([task_hash(task), contract, mode])
                if plan["reuse_identical_public_contracts"] and fingerprint in owners:
                    aliases[key] = owners[fingerprint]
                else:
                    owners[fingerprint] = key
                    keys[key] = (task, group, mode)
    identity.update(aliases=aliases, expected_keys=sorted(keys))
    if identity != read(root / "identity.json") or {p.stem for p in (root / "runs").glob("*.json")} != set(keys):
        raise ValueError("system identity/coverage mismatch")
    rows = {}
    for key, (task, group, mode) in keys.items():
        row = read_checkpoint(root / "runs" / (key + ".json"), {**identity, "key": key}, task.task_id, task_hash(task))
        validate(row, task, group, mode, boundaries, identity)
        rows[key] = row
    expanded = {**rows, **{key: rows[source] for key, source in aliases.items()}}
    for task in tasks:
        forks = [expanded[task.task_id + "-" + g + "-" + m]["boundary_experiment"]["fork"] for g in "ABCD" for m in MODES]
        if any(f != forks[0] for f in forks):
            raise ValueError("paired fork mismatch")
    completed = {"actual_runs": len(rows), "logical_runs": len(expanded), "aliases": aliases,
                 "identity_sha256": file_hash(root / "identity.json"), "checkpoints": {key: file_hash(root / "runs" / (key + ".json")) for key in sorted(rows)}}
    if completed != read(root / "completed.json"):
        raise ValueError("completed evidence manifest differs")
    return expanded, completed


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate-only", action="store_true")
    args = parser.parse_args()
    from scripts.audit_boundary_preparation import audit
    preparation = audit()
    gate = audit_gate()
    _, completed = (None, None) if args.gate_only else audit_system()
    print(json.dumps({"passed": True, "preparation": preparation, "gate_groups": len(gate["summary"]),
                      "system_actual_runs": completed["actual_runs"] if completed else None}))
