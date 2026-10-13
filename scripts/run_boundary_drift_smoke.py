"""Registered controlled-tool drift smoke; never autonomous Agent research.

Private policy and fault schedules exist only in evaluator/child. Trigger gets
only the audited public receipt projection. No production mutations or model.
"""
import argparse
import json
from pathlib import Path
import subprocess
import shutil
import sys
import time

from scripts.run_skill_evolution import ROOT, digest_file
from scripts.skill_evolution_release import hashed, relative
from scripts.continue_skill_evolution_selection import publish
from skillforge.evolution_schemas import fingerprint
from skillforge.skill_evolution.catalog import Catalog
from skillforge.skill_evolution.agent_evidence import read
from skillforge.boundary_evolution.evidence import PublicReceiptAdapter
from skillforge.boundary_evolution.trigger import DriftController, TriggerPolicy


def child(request):
    # Private evaluator process, never imported by trigger/acquisition modules.
    import skillforge.environment as module
    from scripts.active_evolution_worlds import policy
    from skillforge.execution_aware.contracts import ExecutionContract
    from skillforge.evolution_execution import execute_frozen
    spec = request["spec"]
    if spec["world"] is not None:
        module.eligibility = lambda name, state, args: policy(spec["world"], name, state, args)
    env = module.Environment(path=request["database"], fixture=spec["fixture"], faults=spec["faults"])
    tracker = ExecutionContract(spec["task"]["task_id"])
    def dispatch(name, args, key): return env.call(name, args, spec["fixture"]["customer_id"], key)
    def call(name, args, key): return tracker.call(dispatch, name, args, key, source="skill")
    error = None
    try:
        execute_frozen(request["contract"], spec["task"]["parameters"], call, spec["task"]["task_id"])
    except module.ToolError as exc:
        error = exc.code
    result = {"task_id": spec["task"]["task_id"], "trajectory_id": fingerprint(spec["task"]),
        "tool_audit": env.audit, "execution_contract": tracker.checkpoint(), "public_error": error}
    env.close()
    return result


def specifications():
    result = []
    for stage, world, faults in [("no-change", None, {}),
            ("fault-only", None, {"get_customer": ["timeout"]}), ("changed", "W1", {})]:
        for index in range(3):
            ident = f"p6-controlled-20261012-{stage}-{index}"
            oid = "O-" + ident
            task = {"task_id": ident, "family": "refund", "request": "Refund the requested 100 minor units.",
                "parameters": {"order_id": oid, "amount": 100}}
            result.append({"stage": stage, "world": world, "task": task,
                "source_group": ident, "probe_origin": "daily", "sandbox_id": None,
                "fixture": {"order_id": oid, "customer_id": "C-" + ident, "risk": "LOW",
                    "order": "CONFIRMED", "shipment": "PROCESSING", "payment": "CAPTURED", "captured": 10000, "refunded": 0},
                "faults": faults})
    for index in range(2):
        spec = json.loads(json.dumps(result[-1]))
        ident = f"p6-controlled-20261012-explore-{index}"
        spec.update(stage="explore", source_group=ident, probe_origin="authorized_sandbox", sandbox_id="p6-isolated-explore")
        spec["task"]["task_id"] = ident
        spec["task"]["parameters"]["order_id"] = "O-" + ident
        spec["fixture"]["order_id"] = "O-" + ident
        spec["fixture"]["customer_id"] = "C-" + ident
        if index == 1: spec["faults"] = {"get_customer": ["timeout"]}
        result.append(spec)
    return result


def run(stage1, output):
    stage1, output = Path(stage1).resolve(), Path(output).resolve()
    if output.exists(): raise ValueError("fresh smoke root required; never overwrite receipts")
    freeze = read(stage1 / "stage1-freeze.json")
    if freeze["hash"] != fingerprint({k: v for k, v in freeze.items() if k != "hash"}):
        raise ValueError("stage1 freeze tampered")
    for name, sha in freeze["implementation_sources"].items():
        if digest_file(ROOT / name) != sha: raise ValueError("frozen Stage 1 implementation changed")
    catalog = Catalog.load(stage1 / "stage1-catalog.json")
    if catalog.hash != freeze["catalog_hash"]: raise ValueError("frozen catalog changed")
    entry = next(row for row in catalog.entries() if row["contract"]["family"] == "refund")
    specs = specifications()
    files = [Path(__file__), *ROOT.glob("skillforge/boundary_evolution/*.py"),
        ROOT / "skillforge/gap_detection.py", ROOT / "skillforge/evolution_evidence.py",
        ROOT / "skillforge/evolution_boundary.py", ROOT / "skillforge/evolution_execution.py",
        ROOT / "scripts/active_evolution_worlds.py"]
    protocol = hashed({"schema": "controlled-public-drift-smoke-v1", "engineering_only": True,
        "stage1_freeze_hash": freeze["hash"], "catalog_hash": catalog.hash, "parent_revision": entry["revision"],
        "policy": TriggerPolicy().model_dump(), "private_specs": specs,
        "sources": {relative(path): digest_file(path) for path in sorted(files)},
        "model_calls": 0, "tokens": 0, "max_tool_receipts": len(specs),
        "scope": "controlled isolated SQLite flow, not genuine Agent daily interactions or formal trigger precision/recall"})
    publish(output / "protocol.json", protocol)
    for name in protocol["sources"]:
        target = output / "source-snapshot" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    controller = DriftController(protocol["policy"])
    members, rows, key = {}, [], None
    started = time.perf_counter()
    for index, spec in enumerate(specs):
        folder = output / f"event-{index:03d}"
        request = {"spec": spec, "contract": entry["contract"], "database": str(folder / "sandbox.sqlite")}
        publish(folder / "private-request.json", request)
        response = folder / "raw.json"
        subprocess.run([sys.executable, "-m", "scripts.run_boundary_drift_smoke", "child",
            "--request", str(folder / "private-request.json"), "--response", str(response)],
            check=True, timeout=30, capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        raw = read(response)
        members[spec["task"]["task_id"]] = {"task_hash": fingerprint(spec["task"]), "raw_hash": fingerprint(raw),
            "skill_id": entry["skill_id"], "parent_revision": entry["revision"], "source_group": spec["source_group"],
            "probe_origin": spec["probe_origin"], "sandbox_id": spec["sandbox_id"], "evidence_origin": "controlled_procedure"}
        interaction = PublicReceiptAdapter(members, catalog).export(raw, spec["task"])
        publish(folder / "public-interaction.json", interaction.model_dump(mode="json"))
        if spec["probe_origin"] == "daily":
            decision = controller.observe(interaction)
            if decision["state"] == "SUSPECTED_DRIFT":
                key = decision["trigger_key"]
                controller.begin_exploration(key, sandbox_id="p6-isolated-explore")
            row = {"stage": spec["stage"], "state": decision["state"],
                   "independent_sources": decision["independent_sources"], "feedback": interaction.feedback}
        else:
            if key is None: raise ValueError("exploration cannot precede public trigger")
            evidence = controller.charge_probe(key, interaction)
            row = {"stage": "explore", "charged": True, "learnable": evidence is not None,
                   "feedback": interaction.feedback}
        checkpoint = controller.checkpoint()
        publish(folder / "trigger-checkpoint.json", checkpoint)
        controller = DriftController.restore(checkpoint)
        rows.append(row)
    publish(output / "source-receipts.json", members)
    passed = ([row["state"] for row in rows[:3]] == ["NO_CHANGE"] * 3 and
        [row["state"] for row in rows[3:6]] == ["INFRASTRUCTURE"] * 3 and
        [row["state"] for row in rows[6:9]] == ["INCONCLUSIVE", "INCONCLUSIVE", "SUSPECTED_DRIFT"] and
        rows[9]["learnable"] and not rows[10]["learnable"])
    report = hashed({"schema": "controlled-public-drift-smoke-results-v1", "passed": passed,
        "engineering_only": True, "protocol_hash": protocol["hash"], "rows": rows,
        "actual_tool_calls": sum(len(read(output / f"event-{i:03d}" / "raw.json")["tool_audit"]) for i in range(len(specs))),
        "new_model_calls": 0, "new_tokens": 0, "exploration_queries": 2,
        "learnable_exploration_receipts": 1, "checkpoint_replays": len(rows),
        "wall_seconds": time.perf_counter() - started, "activated": False, "deployed": False,
        "scope": protocol["scope"]})
    publish(output / "report.json", report)
    if not passed: raise ValueError("controlled tool smoke behavior differs from preregistered expected states")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    smoke = sub.add_parser("run"); smoke.add_argument("--stage1", required=True); smoke.add_argument("--output", required=True)
    worker = sub.add_parser("child"); worker.add_argument("--request", required=True); worker.add_argument("--response", required=True)
    args = parser.parse_args()
    if args.command == "child": publish(args.response, child(read(args.request)))
    else: print(json.dumps(run(args.stage1, args.output)))
