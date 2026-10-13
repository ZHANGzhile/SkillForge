"""Freeze fresh scenarios, execute explicit training probes and fit boundaries."""
import argparse
import copy
import json
from pathlib import Path

from scripts.boundary_learning import boundary_signature, features, fit_groups, oracle, procedure_hash
from scripts.coordinator_io import atomic_json
from scripts.evaluate_reuse_ablation import read
from skillforge.dataset import digest, task_hash
from skillforge.environment import Environment, ToolError
from skillforge.schemas import ExpectedOutcome, SkillContract, Task
from skillforge.skills import compile_skill, execute
from skillforge.training_data import file_hash

FAMILIES = ("modify_address", "cancel_order", "refund")


def specs(family, split):
    common = [("normal_low", {}, "completed"), ("normal_medium", {"risk": "MEDIUM"}, "completed"),
              ("high_risk", {"risk": "HIGH"}, "escalated")]
    if family == "refund":
        singles = [("partial_payment", {"payment": "PARTIALLY_REFUNDED", "refunded": 1200}, "completed"),
                   ("exact_remaining", {"refunded": 1200, "exact": True, "payment": "PARTIALLY_REFUNDED"}, "completed"),
                   ("over_remaining", {"refunded": 1200, "over": True, "payment": "PARTIALLY_REFUNDED"}, "refused"),
                   ("failed_payment", {"payment": "FAILED"}, "refused"), ("zero_amount", {"zero": True}, "refused")]
        heldout = [("risk_over", {"risk": "HIGH", "over": True}, "escalated"),
                   ("risk_failed", {"risk": "HIGH", "payment": "FAILED"}, "escalated"),
                   ("shipped_partial", {"shipment": "SHIPPED", "payment": "PARTIALLY_REFUNDED", "refunded": 1200, "exact": True}, "completed")]
    else:
        singles = [("shipped", {"shipment": "SHIPPED"}, "refused"),
                   ("delivered", {"shipment": "DELIVERED"}, "refused"),
                   ("processing", {"shipment": "PROCESSING"}, "escalated"),
                   ("pending", {"order": "PENDING"}, "escalated")]
        if family == "modify_address":
            singles += [("invalid_address", {"invalid": True}, "refused")]
        heldout = [("risk_shipped", {"risk": "HIGH", "shipment": "SHIPPED"}, "escalated"),
                   ("risk_processing", {"risk": "HIGH", "shipment": "PROCESSING"}, "escalated"),
                   ("medium_pending", {"risk": "MEDIUM", "order": "PENDING"}, "escalated")]
    if split == "test":
        # Exactly eight predeclared scenario families per skill family.
        return common[:2] + [common[2], singles[0], singles[-1]] + heldout
    return common + singles


def generate(plan):
    tasks = []
    for split in ("train", "validation", "test"):
        for family in FAMILIES:
            for scenario, attrs, outcome in specs(family, split):
                uid = digest([plan["version"], plan["seed"], split, family, scenario])[:20]
                captured = 20000 + int(uid[:4], 16)
                fixture = {"order_id": "BO" + uid, "customer_id": "BC" + uid, "captured": captured,
                           "address": "Existing address " + uid, **attrs}
                amount = captured - attrs.get("refunded", 0) + (1 if attrs.get("over") else 0) if attrs.get("exact") or attrs.get("over") else 0 if attrs.get("zero") else 1700
                params = {"order_id": fixture["order_id"]}
                if family == "refund":
                    params["amount"] = amount
                if family == "modify_address":
                    params["new_address"] = "bad" if attrs.get("invalid") else "Updated address " + uid
                phrasing = {"train": "Please perform", "validation": "I request", "test": "Subject to the business policy, carry out"}[split]
                operation = {"refund": "a refund of {amount} minor currency units for {order_id}.",
                             "modify_address": "an address change on {order_id} to {new_address}.",
                             "cancel_order": "cancellation of {order_id}."}[family]
                template = phrasing + " " + operation
                unchanged = ["order.shipping_address", "order.status", "payment.refunded_amount"]
                changes = {}
                if outcome == "completed":
                    key = {"refund": "payment.refunded_amount", "modify_address": "order.shipping_address", "cancel_order": "order.status"}[family]
                    changes[key] = amount + attrs.get("refunded", 0) if family == "refund" else params["new_address"] if family == "modify_address" else "CANCELLED"
                    unchanged.remove(key)
                tasks.append(Task(task_id="boundary-" + uid, family=family, request=template.format(**params),
                    customer_id=fixture["customer_id"], parameters=params, split=split, template_id=digest(template),
                    template_text=template, seed=plan["seed"], fixture=fixture, dataset_id=plan["version"], instance_id=uid,
                    structure_id=family + ":" + scenario, expected=ExpectedOutcome(allowed_outcomes=[outcome], expected_state=changes, unchanged_fields=unchanged)))
    return tasks


def probe(task, skill):
    env = Environment(fixture=task.fixture)
    try:
        initial = env.snapshot()
        visible = copy.deepcopy(initial)
        visible.update(features(task.family, initial, task.parameters))
        def call(name, args, key):
            return env.call(name, args, task.customer_id, key)
        result = execute(skill, task.parameters, visible, call, task.task_id, enforce_gate=False)
        label = "positive" if result["success"] else "negative" if result.get("error") == "business_rule_rejected" else "excluded"
        applicable = oracle(task.family, {**initial, **features(task.family, initial, task.parameters)}, task.parameters) == "APPLICABLE"
        if result["success"] != applicable:
            raise ValueError("scenario oracle differs from actual fixed-procedure execution: " + task.task_id)
        return {"id": task.task_id + "-probe", "split": task.split, "family": task.family, "task_id": task.task_id,
                "task_hash": task_hash(task), "label": label, "exclusion_reason": result.get("error") if label == "excluded" else None,
                "origin": "explicit-experimental-procedure-execution-not-LLM",
                "state": initial, "parameters": task.parameters, "features": features(task.family, initial, task.parameters),
                "result": result, "tool_audit": env.audit, "final_state": env.snapshot()}
    finally:
        env.close()


def source_audit(bundle):
    rows = []
    for family in FAMILIES:
        source = bundle["memory"]
        baseline = compile_skill(source, family)
        negative = [r for r in source if r["task_family"] == family and not r["verification"]["task_success"] and
                    any(e.get("error") in {"business_rule_rejected", "permission_denied"} for e in r["tool_audit"])]
        variants = []
        for dropped in negative:
            try:
                changed = compile_skill([r for r in source if r["trajectory_id"] != dropped["trajectory_id"]], family)
                variants.append({"removed": dropped["trajectory_id"], "admitted": True,
                                 "boundary_changed": boundary_signature(changed) != boundary_signature(baseline),
                                 "evidence_changed": changed.model_dump() != baseline.model_dump()})
            except ValueError as exc:
                variants.append({"removed": dropped["trajectory_id"], "admitted": False, "reason": str(exc)})
        try:
            ids = {r["trajectory_id"] for r in negative}
            compile_skill([r for r in source if r["trajectory_id"] not in ids], family)
            no_negative = "admitted"
        except ValueError as exc:
            no_negative = str(exc)
        rows.append({"family": family, "boundary": boundary_signature(baseline), "negative_sources": len(negative),
                     "leave_one_out": variants, "all_failures_removed": no_negative})
    return {"scope": "Original real source corpus; evidence/admission intervention, not new learner results", "families": rows}


def prepare(plan_path="configs/boundary-study.json"):
    plan = read(plan_path)
    root, dataset = Path(plan["output"]), Path(plan["dataset"])
    if root.exists() or dataset.exists():
        raise ValueError("immutable output already exists; audit rather than overwrite")
    bundle = read(plan["bundle"])
    if digest({k: v for k, v in bundle.items() if k != "bundle_hash"}) != bundle["bundle_hash"] or digest(bundle["memory"]) != bundle["source_hash"]:
        raise ValueError("source bundle integrity mismatch")
    bases = {s["family"]: SkillContract.model_validate(s) for s in bundle["skills"]}
    tasks = generate(plan)
    ids = [t.task_id for t in tasks]
    assert len(ids) == len(set(ids))
    assert {t.structure_id for t in tasks if t.split == "test"} - {t.structure_id for t in tasks if t.split != "test"}
    # No test execution/outcome feeds fit_groups. This ordering is intentional.
    training = [probe(t, bases[t.family]) for t in tasks if t.split == "train"]
    groups, traces = {g: {} for g in "ABCD"}, {}
    for family in FAMILIES:
        variants, traces[family] = fit_groups(bases[family], training, plan["max_added_conditions"])
        for group, skill in variants.items():
            groups[group][family] = skill.model_dump()
    root.mkdir(parents=True)
    dataset.mkdir(parents=True)
    for split in ("train", "validation", "test"):
        (dataset / (split + ".jsonl")).write_bytes(("".join(t.model_dump_json() + "\n" for t in tasks if t.split == split)).encode())
    manifest = {"version": plan["version"], "seed": plan["seed"], "counts": {s: sum(t.split == s for t in tasks) for s in ("train", "validation", "test")},
                "files": {s + ".jsonl": file_hash(dataset / (s + ".jsonl")) for s in ("train", "validation", "test")},
                "heldout_structures": sorted({t.structure_id for t in tasks if t.split == "test"} - {t.structure_id for t in tasks if t.split != "test"}),
                "task_hashes": {t.task_id: task_hash(t) for t in tasks}}
    atomic_json(dataset / "manifest.json", manifest)
    atomic_json(root / "source-audit.json", source_audit(bundle))
    atomic_json(root / "training-probes.json", training)
    atomic_json(root / "boundaries.json", {"groups": groups, "learning_traces": traces, "procedure_hashes": {f: procedure_hash(s) for f, s in bases.items()}})
    identity = {"plan_sha256": file_hash(plan_path), "manifest_sha256": file_hash(dataset / "manifest.json"),
                "source_bundle_sha256": file_hash(plan["bundle"]), "core_hash": digest({p.name: p.read_text(encoding="utf-8") for p in sorted(Path("skillforge").glob("*.py"))}),
                "sources": {str(p).replace('\\', '/'): file_hash(p) for p in (Path(__file__), Path(__file__).with_name("boundary_learning.py"))},
                "artifacts": {n: file_hash(root / n) for n in ("source-audit.json", "training-probes.json", "boundaries.json")}}
    atomic_json(root / "preparation.json", identity)
    return manifest


def load_prepared(plan_path="configs/boundary-study.json"):
    plan = read(plan_path)
    root, dataset = Path(plan["output"]), Path(plan["dataset"])
    identity = read(root / "preparation.json")
    checks = {plan_path: identity["plan_sha256"], str(dataset / "manifest.json"): identity["manifest_sha256"], plan["bundle"]: identity["source_bundle_sha256"], **identity["sources"],
              **{str(root / n): h for n, h in identity["artifacts"].items()}}
    manifest = read(dataset / "manifest.json")
    checks.update({str(dataset / n): h for n, h in manifest["files"].items()})
    if any(file_hash(p) != h for p, h in checks.items()):
        raise ValueError("boundary study preparation identity changed")
    if digest({p.name: p.read_text(encoding="utf-8") for p in sorted(Path("skillforge").glob("*.py"))}) != identity["core_hash"]:
        raise ValueError("frozen core changed")
    tasks = [Task.model_validate_json(line) for s in ("train", "validation", "test") for line in (dataset / (s + ".jsonl")).read_text(encoding="utf-8").splitlines()]
    if {t.task_id: task_hash(t) for t in tasks} != manifest["task_hashes"]:
        raise ValueError("task coverage/hash mismatch")
    return plan, root, tasks, read(root / "boundaries.json"), identity


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", default="configs/boundary-study.json")
    print(prepare(parser.parse_args().plan))
