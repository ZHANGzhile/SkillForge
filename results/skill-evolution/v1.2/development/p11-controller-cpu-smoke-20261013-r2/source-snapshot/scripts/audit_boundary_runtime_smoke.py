"""Independent fixed-model smoke replay: SQLite, receipts, checkpoints and fees."""
import argparse
import json
from datetime import datetime
from pathlib import Path
import sqlite3
from unittest.mock import patch

from scripts.run_skill_evolution import ROOT, digest_file
from scripts.skill_evolution_release import hashed, fixed_model
from scripts.continue_skill_evolution_selection import publish
from scripts.evolution_budget import CheckpointAdmission
from scripts.run_skill_evolution_reuse import check_no_history
from skillforge.skill_evolution.agent_evidence import read, semantic
from skillforge.evolution_schemas import fingerprint
from skillforge.evolution_common.artifacts import clone
from skillforge.environment import Environment
from skillforge.schemas import Task, Action
from skillforge.verifier import verify
from skillforge.boundary_runtime.catalog import BoundaryCatalog
from skillforge.boundary_runtime.runtime import run_agent, runtime_sources
from skillforge.boundary_evolution.evidence import PublicReceiptAdapter
from skillforge.boundary_evolution.trigger import DriftController
from skillforge.execution_aware import contracts


def sql_dump(path):
    with sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True) as db:
        return list(db.iterdump())


def first_difference(left, right, path="checkpoint"):
    if type(left) is not type(right): return f"{path}: different types"
    if isinstance(left, dict):
        if set(left) != set(right): return f"{path}: different keys"
        for key in left:
            if left[key] != right[key]: return first_difference(left[key], right[key], path + "." + key)
    elif isinstance(left, list):
        if len(left) != len(right): return f"{path}: lengths {len(left)} != {len(right)}"
        for i, (a, b) in enumerate(zip(left, right)):
            if a != b: return first_difference(a, b, path + f"[{i}]")
    return f"{path}: {left!r} != {right!r}"


def audit(root):
    root = Path(root).resolve()
    protocol, report, settings = read(root / "protocol.json"), read(root / "report.json"), read(root / "model-identity.json")
    for value in (protocol, report):
        if value["hash"] != fingerprint({k: v for k, v in value.items() if k != "hash"}):
            raise ValueError("smoke protocol/report content identity mismatch")
    if not report["complete"] or report["failure"]: raise ValueError("incomplete smoke remains charged, cannot certify completion")
    fixed_model(settings)
    for name, sha in protocol["sources"].items():
        if digest_file(ROOT / name) != sha or digest_file(root / "source-snapshot" / name) != sha:
            raise ValueError("registered smoke source changed")
    if settings["stage2_runtime_sources_hash"] != fingerprint(runtime_sources()): raise ValueError("Runtime identity differs from worker")
    from skillforge.skill_evolution.catalog import Catalog
    base = Catalog.load(root / "catalog.json")
    catalog = BoundaryCatalog(base.entries(), protocol["boundaries"])
    if catalog.hash != protocol["catalog_hash"] or catalog.bundle_hash != protocol["bundle_hash"]:
        raise ValueError("program/Boundary identity mismatch")
    members = read(root / "source-receipts.json")
    adapter, controller = PublicReceiptAdapter(members, base), DriftController(protocol["trigger_policy"])
    rows, statuses, tokens, ncheckpoints = [], [], 0, 0
    for i, planned in enumerate(protocol["cases"]):
        folder = root / str(i)
        row, status = read(folder / "result.json"), read(folder / "collection-status.json")
        if row["task"] != planned["task"] or row["model_identity_hash"] != fingerprint(settings):
            raise ValueError("task/model differs from registered smoke plan")
        task = Task.model_validate(row["task"])
        public_task = {key: getattr(task, key) for key in ("task_id", "family", "request", "parameters")}
        check_no_history({"case": row["task"], "agent": row["agent"]})
        paths = sorted((folder / "checkpoints").glob("*/snapshot.json"), key=lambda p: int(p.parent.name))
        saved = []
        admission = CheckpointAdmission(protocol["prior_tokens"] + tokens, protocol["prior_tokens"] + protocol["phase_tokens"],
            protocol["prior_wall_seconds"], protocol["prior_wall_seconds"] + protocol["phase_wall_seconds"])
        elapsed, approval_names = 0., set()
        for index, path in enumerate(paths):
            value = read(path); body = value["body"]
            if value["hash"] != fingerprint(body) or body["database_sha256"] != digest_file(path.parent / "environment.sqlite"):
                raise ValueError("checkpoint content/SQLite file hash mismatch")
            checkpoint = body["runtime"]
            pending = [j for j, r in enumerate(checkpoint["model_requests"]) if r["status"] == "pending" and j not in admission.approved]
            if pending:
                name = str(pending[0]) + ".json"; receipt = read(folder / "admissions" / name)
                if receipt["elapsed_seconds"] < elapsed: raise ValueError("inference admission clock regressed")
                elapsed = receipt["elapsed_seconds"]
                expected = admission.inspect(checkpoint, elapsed)
                if receipt != {**expected, "checkpoint_index": index} or not receipt["approved"]:
                    raise ValueError("actual inference approval/budget differs from raw checkpoint")
                admission.record_approval(receipt); approval_names.add(name)
            else: admission.inspect(checkpoint, elapsed)
            saved.append(value)
        if approval_names != {p.name for p in (folder / "admissions").glob("*.json")}:
            raise ValueError("orphan model reservation")
        # Replay actual UUID identities and wall timestamps, never generate new
        # evidence. Their values do not determine actions, eligibility or EOC.
        ids = []
        with sqlite3.connect((folder / "live.sqlite").resolve().as_uri() + "?mode=ro", uri=True) as db:
            address_ids = iter([r[0] for r in db.execute("SELECT address_id FROM addresses WHERE address_id!='A1' ORDER BY rowid")])
        seen_requests = set()
        for event in row["tool_audit"]:
            if not event["committed"] or event["error"] or event["request_id"] in seen_requests: continue
            if event["tool_name"] == "issue_refund":
                before = {r["refund_id"] for r in event["before_state"]["refunds"]}
                new = [r for r in event["after_state"]["refunds"] if r["refund_id"] not in before]
                if len(new) != 1: raise ValueError("mutation receipt lacks unique actual refund")
                ids.extend([new[0]["transaction_id"], new[0]["refund_id"]])
            elif event["tool_name"] == "update_shipping_address": ids.append(next(address_ids))
            elif event["tool_name"] in {"create_ticket", "escalate_to_human"}: ids.append(event["result"]["ticket_id"])
            seen_requests.add(event["request_id"])
        identifiers = iter(ids)
        dates = iter(receipt["timestamp"] for receipt in row["agent"]["verification_receipts"])
        class RecordedClock:
            @staticmethod
            def now(tz): return datetime.fromisoformat(next(dates))
        class RecordedModel:
            def __init__(self): self.settings, self.tokens, self.index = clone(settings), 0, 0
            def decide(self, context):
                step, request = row["agent"]["steps"][self.index], row["agent"]["model_requests"][self.index]
                if (context != step["context"] or len(step["messages"]) != 2 or
                        step["messages"][0] != {"role": "system", "content": settings["system_prompt"]} or
                        step["messages"][1]["role"] != "user" or json.loads(step["messages"][1]["content"]) != context):
                    raise ValueError("raw model messages/context differ from independent replay")
                if request["status"] != "completed" or not request["usage_known"]:
                    raise ValueError("unknown/failed generation needs an explicit separate audit path")
                self.last_messages, self.last_response = clone(step["messages"]), step["model_response"]
                action = Action.model_validate_json(self.last_response)
                if action.model_dump() != step["action"]: raise ValueError("raw response differs from selected action")
                self.tokens += request["charged_tokens"]; self.index += 1
                return action
        env, model, cursor = Environment(fixture=task.fixture, faults=planned["faults"]), RecordedModel(), 0
        def persist(value):
            nonlocal cursor
            if cursor >= len(saved) or semantic(value) != semantic(saved[cursor]["body"]["runtime"]):
                detail = "unexpected extra checkpoint" if cursor >= len(saved) else first_difference(semantic(value), semantic(saved[cursor]["body"]["runtime"]))
                raise ValueError(f"Runtime checkpoint differs from action replay, arm {i}, checkpoint {cursor}: {detail}")
            body = saved[cursor]["body"]
            if semantic(body["audit"]) != semantic(env.audit) or body["faults"] != env.faults:
                raise ValueError("tool/fault checkpoint differs from actual SQLite replay")
            if list(env.db.iterdump()) != sql_dump(paths[cursor].parent / "environment.sqlite"):
                raise ValueError("checkpoint database differs from independent actual tool execution")
            cursor += 1
        def tool(name, args, key, source):
            before = len(env.audit)
            try: return env.call(name, args, task.customer_id, key)
            finally:
                for event in env.audit[before:]: event["decision_origin"] = source
        try:
            if env.snapshot() != row["initial_state"] or read(folder / "initial-state.json") != row["initial_state"]:
                raise ValueError("initial fixture/state mismatch")
            with patch("skillforge.environment.uuid.uuid4", side_effect=lambda: next(identifiers)), patch.object(contracts, "datetime", RecordedClock):
                replay = run_agent(model, public_task, catalog, tool, persist=persist, **protocol["limits"])
            expected, observed = clone(row["agent"]), clone(replay)
            expected["metrics"].pop("seconds"); observed["metrics"].pop("seconds")
            if semantic(expected) != semantic(observed) or cursor != len(saved) or model.index != len(expected["steps"]):
                raise ValueError("Agent result differs from full raw model/tool/checkpoint replay")
            if semantic(row["tool_audit"]) != semantic(env.audit) or row["final_state"] != env.snapshot() or list(env.db.iterdump()) != sql_dump(folder / "live.sqlite"):
                raise ValueError("final evidence/database differs from actual execution replay")
            verdict = verify(task, row["initial_state"], env.snapshot(), env.audit, replay["outcome"])
            if verdict != row["verification"] or admission.charged_tokens() != replay["metrics"]["tokens"]:
                raise ValueError("independent EOC/fee settlement differs")
        finally: env.close()
        expected_status = {"task_id": task.task_id, "completed": True, "charged_tokens": replay["metrics"]["tokens"],
            "failure": None, "charged_model_requests": len(admission.approved), "approved_unknown_requests": 0}
        if status != expected_status: raise ValueError("raw stage fee status mismatch")
        raw = {"task_id": task.task_id, "trajectory_id": fingerprint([task.task_id, replay["identity"]]),
            "tool_audit": row["tool_audit"], "execution_contract": replay["execution_contract"]}
        if read(folder / "public-receipt-source.json") != raw: raise ValueError("drift adapter source differs from actual execution")
        interaction = adapter.export(raw, public_task)
        if read(folder / "public-interaction.json") != interaction.model_dump(mode="json"): raise ValueError("public feedback projection mismatch")
        decision = controller.observe(interaction)
        if read(folder / "trigger-checkpoint.json") != controller.checkpoint(): raise ValueError("real public trigger checkpoint differs")
        rows.append({"task_id": task.task_id, "stage": planned["stage"], "eoc": verdict["task_success"],
            "trigger_state": decision["state"], "feedback": interaction.feedback, "tokens": status["charged_tokens"],
            "model_calls": replay["metrics"]["llm_calls"],
            "autonomous_eoc": verdict["task_success"] and not replay["interventions"]["runtime_intervention_count"],
            "runtime_assisted_eoc": verdict["task_success"] and bool(replay["interventions"]["runtime_intervention_count"]),
            "attempted_violations": verdict["attempted_policy_violation"], "actual_violations": verdict["actual_policy_violation"]})
        statuses.append(status); tokens += status["charged_tokens"]; ncheckpoints += len(saved)
    if (rows != report["rows"] or statuses != report["statuses"] or tokens != report["charged_tokens"] or
            report["shared_total_tokens"] != protocol["prior_tokens"] + tokens or tokens > protocol["phase_tokens"] or
            report["collection_wall_seconds"] > protocol["phase_wall_seconds"] or report["approved_unknown_requests"]):
        raise ValueError("real smoke aggregate/budget differs from independent replay")
    receipt = hashed({"schema": "stage2-real-h0-smoke-audit-v1", "passed": True,
        "protocol_hash": protocol["hash"], "report_hash": report["hash"], "replayed_arms": len(rows),
        "replayed_checkpoints": ncheckpoints, "shared_total_tokens": report["shared_total_tokens"],
        "new_model_calls": 0, "new_tokens": 0, "audit_controller_sha256": digest_file(__file__)})
    publish(root / "independent-audit.json", receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--run", required=True)
    print(audit(parser.parse_args().run))
