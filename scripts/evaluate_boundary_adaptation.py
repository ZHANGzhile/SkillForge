"""Frozen CPU adaptation study; changed policy is isolated from boundary fitting."""
import argparse
from contextlib import contextmanager
import itertools
import json
from pathlib import Path

from scripts.audit_boundary_preparation import semantic
from scripts.audit_boundary_study import load_prepared
from scripts.boundary_learning import boundary_signature, procedure_hash
from scripts.bounded_boundary_adapter import adapt
from scripts.coordinator_io import atomic_json
from scripts.evaluate_reuse_ablation import read
import skillforge.environment as environment_module
from skillforge.dataset import digest
from skillforge.environment import Environment
from skillforge.schemas import Condition, SkillContract
from skillforge.skills import execute, gate, hydrate
from skillforge.training_data import file_hash

PLAN = "configs/boundary-adaptation.json"


@contextmanager
def changed_policy(rule):
    original = environment_module.eligibility
    def policy(name, state, arguments):
        decision = original(name, state, arguments)
        if name == "issue_refund" and decision == "allow" and state.get(rule["field"]) == rule["value"]:
            return "refuse"
        return decision
    environment_module.eligibility = policy
    try:
        yield
    finally:
        environment_module.eligibility = original


def generate(plan):
    rows = []
    for world in plan["worlds"]:
        for risk, payment, order, shipment in itertools.product(plan["feature_domains"]["customer.risk_level"],
                ("CAPTURED", "PARTIALLY_REFUNDED", "FAILED"), plan["feature_domains"]["order.status"], plan["feature_domains"]["shipment.status"]):
            if payment != "CAPTURED":
                split = "test"
            elif risk == "HIGH":
                continue
            elif (plan["feature_domains"]["order.status"].index(order) + plan["feature_domains"]["shipment.status"].index(shipment)) % 2 == 0:
                split = "train"
            else:
                split = "validation"
            uid = digest([plan["version"], world, split, risk, payment, order, shipment])[:20]
            fixture = {"order_id": "AO" + uid, "customer_id": "AC" + uid, "risk": risk, "payment": payment,
                       "order": order, "shipment": shipment, "captured": 20000 + int(uid[:3], 16),
                       "refunded": 1200 if payment == "PARTIALLY_REFUNDED" else 0}
            rows.append({"id": uid, "world": world, "policy_version": digest([plan["version"], world]), "split": split,
                         "fixture": fixture, "parameters": {"order_id": fixture["order_id"], "amount": 1700}})
    return rows


def prepare():
    plan = read(PLAN)
    source, parent, _, boundaries, old = load_prepared(plan["source_plan"])
    base = SkillContract.model_validate(boundaries["groups"]["C"]["refund"])
    specs = generate(plan)
    counts = {w: {s: sum(r["world"] == w and r["split"] == s for r in specs) for s in ("train", "validation", "test")} for w in plan["worlds"]}
    paths = [PLAN, "scripts/evaluate_boundary_adaptation.py", "scripts/bounded_boundary_adapter.py", "docs/BOUNDARY_ADAPTATION_PLAN.md",
             "scripts/boundary_learning.py", "scripts/audit_boundary_preparation.py", "scripts/audit_boundary_study.py", str(parent / "boundaries.json")]
    frozen = {"version": plan["version"], "specs": specs, "counts": counts, "base": base.model_dump(), "core_hash": old["core_hash"],
              "files": {p.replace("\\", "/"): file_hash(p) for p in paths}, "procedure_hash": procedure_hash(base)}
    return plan, Path(plan["output"]), base, specs, frozen


def freeze():
    _, root, _, _, frozen = prepare()
    if root.exists():
        raise ValueError("adaptation freeze already exists")
    root.mkdir(parents=True)
    atomic_json(root / "freeze.json", frozen)
    return {"counts": frozen["counts"], "sha256": file_hash(root / "freeze.json")}


def probe(spec, base, rule):
    env = Environment(fixture=spec["fixture"])
    try:
        initial = env.snapshot()
        database = list(env.db.iterdump())
        with changed_policy(rule):
            truth = environment_module.eligibility("issue_refund", initial, spec["parameters"]) == "allow"
            result = execute(base, spec["parameters"], dict(initial),
                lambda name, args, key: env.call(name, args, spec["fixture"]["customer_id"], key), spec["id"], enforce_gate=False)
        if result["success"] != truth:
            raise ValueError("controlled procedure disagrees with changed-policy applicability")
        label = "positive" if result["success"] else "negative" if result.get("error") == "business_rule_rejected" else "excluded"
        return {"id": spec["id"], "policy_version": spec["policy_version"], "split": spec["split"], "state": initial,
                "database_sql": database, "parameters": spec["parameters"], "label": label, "result": result,
                "tool_audit": env.audit, "final_state": env.snapshot(), "origin": "controlled-procedure-not-LLM"}
    finally:
        env.close()


def learning_examples(probes, domains):
    allowed = set(domains) | {"payment.captured_amount", "payment.refunded_amount"}
    return [{"id": r["id"], "policy_version": r["policy_version"], "split": r["split"], "label": r["label"],
             "state": {k: v for k, v in r["state"].items() if k in allowed}, "parameters": r["parameters"]}
            for r in probes if r["split"] == "train"]


def measure(spec, skill, rule, truth):
    env = Environment(fixture=spec["fixture"])
    try:
        initial = env.snapshot()
        full = gate(skill, initial, spec["parameters"]).status
        state = {}
        first = gate(skill, state, spec["parameters"]).status
        def call(name, args, key):
            return env.call(name, args, spec["fixture"]["customer_id"], key)
        with changed_policy(rule):
            hydrate(skill, state, spec["parameters"], call, spec["id"] + ":hydrate")
            decision = gate(skill, state, spec["parameters"]).status
            queries = len(env.audit)
            result = execute(skill, spec["parameters"], state, call, spec["id"] + ":execute") if decision == "APPLICABLE" else None
        final = env.snapshot()
        return {"id": spec["id"], "split": spec["split"], "truth": truth, "full_gate": full, "initial_gate": first,
                "hydrated_gate": decision, "queries": queries, "tool_calls": len(env.audit), "procedure_result": result,
                "blocked_writes": sum(e["error"] == "business_rule_rejected" for e in env.audit),
                "actual_violation": not truth and final["payment.refunded_amount"] != initial["payment.refunded_amount"],
                "initial_state": initial, "final_state": final, "tool_audit": env.audit}
    finally:
        env.close()


def summarize(rows):
    applicable = [r for r in rows if r["truth"]]
    forbidden = [r for r in rows if not r["truth"]]
    fa = sum(r["full_gate"] == "APPLICABLE" for r in forbidden)
    fb = sum(r["full_gate"] == "INAPPLICABLE" for r in applicable)
    return {"cases": len(rows), "applicable": len(applicable), "inapplicable": len(forbidden), "false_allow": fa, "false_block": fb,
            "false_allow_rate": fa / len(forbidden) if forbidden else None, "false_block_rate": fb / len(applicable) if applicable else None,
            "initial_unknown": sum(r["initial_gate"] == "UNKNOWN" for r in rows), "remaining_unknown": sum(r["hydrated_gate"] == "UNKNOWN" for r in rows),
            "queries": sum(r["queries"] for r in rows), "tool_calls": sum(r["tool_calls"] for r in rows),
            "procedure_success": sum(bool(r["procedure_result"] and r["procedure_result"]["success"]) for r in rows),
            "blocked_writes": sum(r["blocked_writes"] for r in rows), "actual_violations": sum(r["actual_violation"] for r in rows)}


def run(audit=False):
    plan, root, base, specs, frozen = prepare()
    if read(root / "freeze.json") != frozen:
        raise ValueError("adaptation source/spec freeze changed")
    if not audit and (root / "completed.json").exists():
        raise ValueError("completed study is immutable; use --audit")
    artifacts, results = {}, {}
    for world, rule in plan["worlds"].items():
        selected = [s for s in specs if s["world"] == world]
        probes = [probe(s, base, rule) for s in selected]
        examples = learning_examples(probes, plan["feature_domains"])
        learned, trace = adapt(base, examples, plan["feature_domains"], plan["max_conditions"])
        manual = base.model_copy(deep=True)
        manual.forbidden_conditions.append(Condition(field=rule["field"], value=rule["value"], evidence=["manual-new-policy"]))
        contracts = {"stale": base, "learned": learned, "manual": manual}
        if any(procedure_hash(s) != frozen["procedure_hash"] for s in contracts.values()):
            raise ValueError("adaptation changed fixed program")
        rows = {g: [measure(s, skill, rule, p["label"] == "positive") for s, p in zip(selected, probes) if s["split"] != "train"] for g, skill in contracts.items()}
        artifacts[world + "-probes.json"] = probes
        artifacts[world + "-learning-inputs.json"] = examples
        artifacts[world + "-contracts.json"] = {"contracts": {g: s.model_dump() for g, s in contracts.items()}, "trace": trace}
        artifacts[world + "-rows.json"] = rows
        results[world] = {"train_positive": sum(e["label"] == "positive" for e in examples), "train_negative": sum(e["label"] == "negative" for e in examples),
            "excluded_probes": sum(p["label"] == "excluded" for p in probes), "learned_conditions": trace,
            "learned_matches_manual": boundary_signature(learned) == boundary_signature(manual),
            "summary": {g: {split: summarize([r for r in group if r["split"] == split]) for split in ("validation", "test")} for g, group in rows.items()}}
    artifacts["report.json"] = {"scope": plan["scope"], "worlds": results}
    for name, value in artifacts.items():
        if audit:
            if semantic(read(root / name)) != semantic(value):
                raise ValueError("CPU replay differs: " + name)
        else:
            atomic_json(root / name, value)
    complete = {"freeze_sha256": file_hash(root / "freeze.json"), "artifacts": {name: file_hash(root / name) for name in sorted(artifacts)}}
    if audit:
        if complete != read(root / "completed.json"):
            raise ValueError("adaptation evidence manifest mismatch")
    else:
        atomic_json(root / "completed.json", complete)
    return {"passed": True, "worlds": len(results), "controlled_probes": len(specs), "group_measurements": sum(len(v[g]) for n, v in artifacts.items() if n.endswith("-rows.json") for g in v)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    for arg in ("freeze", "run", "audit"):
        group.add_argument("--" + arg, action="store_true")
    args = parser.parse_args()
    print(json.dumps(freeze() if args.freeze else run(audit=args.audit)))
