"""Replay registered controlled-tool public streams; no tools or model calls."""
import argparse
import math
from pathlib import Path

from scripts.run_skill_evolution import ROOT, digest_file
from scripts.skill_evolution_release import hashed
from scripts.continue_skill_evolution_selection import publish
from skillforge.skill_evolution.agent_evidence import read
from skillforge.skill_evolution.catalog import Catalog
from skillforge.evolution_schemas import fingerprint
from skillforge.boundary_evolution.evidence import PublicReceiptAdapter
from skillforge.boundary_evolution.trigger import DriftController


def check(value):
    if value["hash"] != fingerprint({k: v for k, v in value.items() if k != "hash"}):
        raise ValueError("saved controlled-stream record hash mismatch")
    return value


def audit(root, stage1):
    root, stage1 = Path(root).resolve(), Path(stage1).resolve()
    protocol, report = check(read(root / "protocol.json")), check(read(root / "report.json"))
    freeze = check(read(stage1 / "stage1-freeze.json"))
    if protocol["stage1_freeze_hash"] != freeze["hash"] or not protocol["engineering_only"]:
        raise ValueError("controlled stream must bind scoped Stage 1 freeze")
    for name, sha in protocol["sources"].items():
        if digest_file(ROOT / name) != sha or digest_file(root / "source-snapshot" / name) != sha:
            raise ValueError("controlled stream current/archive source changed")
    catalog = Catalog.load(stage1 / "stage1-catalog.json")
    if catalog.hash != protocol["catalog_hash"]: raise ValueError("frozen catalog mismatch")
    members = read(root / "source-receipts.json")
    specs = protocol["private_specs"]
    if set(members) != {spec["task"]["task_id"] for spec in specs}:
        raise ValueError("receipt membership differs from predeclared stream")
    controller, rows, key, calls = DriftController(protocol["policy"]), [], None, 0
    for i, spec in enumerate(specs):
        folder = root / f"event-{i:03d}"
        raw, member = read(folder / "raw.json"), members[spec["task"]["task_id"]]
        expected = {"task_hash": fingerprint(spec["task"]), "raw_hash": fingerprint(raw),
            "skill_id": next(row["skill_id"] for row in catalog.entries() if row["revision"] == protocol["parent_revision"]),
            "parent_revision": protocol["parent_revision"], "source_group": spec["source_group"],
            "probe_origin": spec["probe_origin"], "sandbox_id": spec["sandbox_id"], "evidence_origin": "controlled_procedure"}
        if member != expected or read(folder / "private-request.json")["spec"] != spec:
            raise ValueError("receipt source/origin differs from frozen collection plan")
        interaction = PublicReceiptAdapter(members, catalog).export(raw, spec["task"])
        if read(folder / "public-interaction.json") != interaction.model_dump(mode="json"):
            raise ValueError("public feedback projection differs from actual tool receipts")
        if spec["probe_origin"] == "daily":
            decision = controller.observe(interaction)
            if decision["state"] == "SUSPECTED_DRIFT":
                key = decision["trigger_key"]
                controller.begin_exploration(key, sandbox_id="p6-isolated-explore")
            row = {"stage": spec["stage"], "state": decision["state"],
                "independent_sources": decision["independent_sources"], "feedback": interaction.feedback}
        else:
            if key is None: raise ValueError("probe preceded drift trigger")
            evidence = controller.charge_probe(key, interaction)
            row = {"stage": "explore", "charged": True, "learnable": evidence is not None, "feedback": interaction.feedback}
        if read(folder / "trigger-checkpoint.json") != controller.checkpoint():
            raise ValueError("trigger checkpoint/state/budget differs from raw stream replay")
        controller = DriftController.restore(controller.checkpoint())
        rows.append(row); calls += len(raw["tool_audit"])
    if (report["rows"] != rows or report["protocol_hash"] != protocol["hash"] or report["actual_tool_calls"] != calls or
            report["new_model_calls"] != 0 or report["new_tokens"] != 0 or not report["passed"] or
            report["exploration_queries"] != 2 or report["learnable_exploration_receipts"] != 1 or
            report["checkpoint_replays"] != len(rows) or report["activated"] or report["deployed"] or
            not math.isfinite(report["wall_seconds"]) or report["wall_seconds"] < 0):
        raise ValueError("controlled stream aggregate differs from independent replay")
    receipt = hashed({"schema": "controlled-public-drift-audit-v1", "passed": True,
        "engineering_only": True, "protocol_hash": protocol["hash"], "report_hash": report["hash"],
        "replayed_events": len(rows), "actual_tool_calls": calls, "new_model_calls": 0, "new_tokens": 0,
        "audit_controller_sha256": digest_file(__file__)})
    publish(root / "independent-audit.json", receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True); parser.add_argument("--stage1", required=True)
    args = parser.parse_args()
    print(audit(args.run, args.stage1))
