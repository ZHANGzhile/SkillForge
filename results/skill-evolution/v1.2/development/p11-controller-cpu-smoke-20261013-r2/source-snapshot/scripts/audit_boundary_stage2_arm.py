"""Independent recorded-response replay against actual SQLite and policy.

No new model calls; validates every action, tool effect, receipt, checkpoint,
initial/final database and durable token reservation. Collection provenance
and the externally registered file index are additional controller checks.
"""
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from unittest.mock import patch

from scripts.run_skill_evolution import digest_file
from scripts.evolution_budget import CheckpointAdmission
from scripts.audit_boundary_runtime_smoke import sql_dump, first_difference
from scripts.boundary_stage2_evaluator import private_policy
from scripts.run_skill_evolution_reuse import check_no_history
from skillforge.skill_evolution.agent_evidence import read, semantic
from skillforge.evolution_schemas import fingerprint
from skillforge.evolution_common.artifacts import clone
from skillforge.environment import Environment
from skillforge.schemas import Task, Action
from skillforge.verifier import verify
from skillforge.boundary_runtime.runtime import run_agent
from skillforge.execution_aware import contracts


def audit_arm(folder, case, catalog, settings, limits, *, prior_tokens, token_cap, prior_wall, wall_cap):
    folder = Path(folder)
    row, status = read(folder / "result.json"), read(folder / "collection-status.json")
    if (row["task"] != case["task"] or row["model_identity_hash"] != fingerprint(settings) or
            row["agent"]["boundary_bundle_hash"] != catalog.bundle_hash or not status["completed"] or status["failure"]):
        raise ValueError("complete matching actual task/model/Boundary evidence required")
    task = Task.model_validate(row["task"])
    public_task = {k: getattr(task, k) for k in ("task_id", "family", "request", "parameters")}
    check_no_history({"case": row["task"], "agent": row["agent"]})
    paths = sorted((folder / "checkpoints").glob("*/snapshot.json"), key=lambda p: int(p.parent.name))
    if [int(p.parent.name) for p in paths] != list(range(len(paths))): raise ValueError("noncontiguous checkpoint journal")
    admission = CheckpointAdmission(prior_tokens, token_cap, prior_wall, wall_cap)
    saved, names, elapsed = [], set(), 0.
    for index, path in enumerate(paths):
        value = read(path); body = value["body"]
        if value["hash"] != fingerprint(body) or body["database_sha256"] != digest_file(path.parent / "environment.sqlite"):
            raise ValueError("checkpoint/SQLite content hash mismatch")
        state = body["runtime"]
        pending = [i for i, r in enumerate(state["model_requests"]) if r["status"] == "pending" and i not in admission.approved]
        if pending:
            name = str(pending[0]) + ".json"; receipt = read(folder / "admissions" / name)
            if receipt["elapsed_seconds"] < elapsed: raise ValueError("admission clock regressed")
            elapsed = receipt["elapsed_seconds"]
            expected = admission.inspect(state, elapsed)
            if receipt != {**expected, "checkpoint_index": index} or not receipt["approved"]:
                raise ValueError("durable request approval/budget mismatch")
            admission.record_approval(receipt); names.add(name)
        else: admission.inspect(state, elapsed)
        saved.append(value)
    if names != {p.name for p in (folder / "admissions").glob("*.json")}: raise ValueError("orphan request approval")
    ids, seen = [], set()
    with sqlite3.connect((folder / "live.sqlite").resolve().as_uri() + "?mode=ro", uri=True) as db:
        addresses = iter(r[0] for r in db.execute("SELECT address_id FROM addresses WHERE address_id!='A1' ORDER BY rowid"))
    for e in row["tool_audit"]:
        if not e["committed"] or e["error"] or e["request_id"] in seen: continue
        if e["tool_name"] == "issue_refund":
            before = {r["refund_id"] for r in e["before_state"]["refunds"]}
            new = [r for r in e["after_state"]["refunds"] if r["refund_id"] not in before]
            if len(new) != 1: raise ValueError("unique actual refund identity required")
            ids.extend([new[0]["transaction_id"], new[0]["refund_id"]])
        elif e["tool_name"] == "update_shipping_address": ids.append(next(addresses))
        elif e["tool_name"] in {"create_ticket", "escalate_to_human"}: ids.append(e["result"]["ticket_id"])
        seen.add(e["request_id"])
    identifiers = iter(ids)
    dates = iter(r["timestamp"] for r in row["agent"]["verification_receipts"])
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
                raise ValueError("raw messages/context differ from replay")
            if request["status"] != "completed" or not request["usage_known"]:
                raise ValueError("unknown/failed model generation needs a separate audit path")
            self.last_messages, self.last_response = clone(step["messages"]), step["model_response"]
            action = Action.model_validate_json(self.last_response)
            if action.model_dump() != step["action"]: raise ValueError("raw response differs from action")
            self.tokens += request["charged_tokens"]; self.index += 1
            return action
    env, model, cursor = Environment(fixture=task.fixture, faults=case.get("faults", {})), RecordedModel(), 0
    def persist(value):
        nonlocal cursor
        if cursor >= len(saved) or semantic(value) != semantic(saved[cursor]["body"]["runtime"]):
            detail = "extra checkpoint" if cursor >= len(saved) else first_difference(semantic(value), semantic(saved[cursor]["body"]["runtime"]))
            raise ValueError(f"checkpoint {cursor} differs: {detail}")
        body = saved[cursor]["body"]
        if semantic(body["audit"]) != semantic(env.audit) or body["faults"] != env.faults:
            raise ValueError("checkpoint tool/fault journal differs")
        if list(env.db.iterdump()) != sql_dump(paths[cursor].parent / "environment.sqlite"):
            raise ValueError("checkpoint actual SQLite differs from independent execution")
        cursor += 1
    def tool(name, args, key, source):
        before = len(env.audit)
        try: return env.call(name, args, task.customer_id, key)
        finally:
            for e in env.audit[before:]: e["decision_origin"] = source
    try:
        if env.snapshot() != row["initial_state"] or read(folder / "initial-state.json") != row["initial_state"]:
            raise ValueError("initial task/fixture differs")
        with private_policy(case["world"]), patch("skillforge.environment.uuid.uuid4", side_effect=lambda: next(identifiers)), patch.object(contracts, "datetime", RecordedClock):
            replay = run_agent(model, public_task, catalog, tool, persist=persist, **limits)
            verdict = verify(task, row["initial_state"], env.snapshot(), env.audit, replay["outcome"])
        expected, observed = clone(row["agent"]), clone(replay)
        expected["metrics"].pop("seconds"); observed["metrics"].pop("seconds")
        if semantic(expected) != semantic(observed) or cursor != len(saved) or model.index != len(expected["steps"]):
            raise ValueError("Agent result differs from raw model/tool replay")
        if semantic(row["tool_audit"]) != semantic(env.audit) or row["final_state"] != env.snapshot() or list(env.db.iterdump()) != sql_dump(folder / "live.sqlite"):
            raise ValueError("final actual SQLite/audit evidence differs")
        if verdict != row["verification"] or admission.charged_tokens() != replay["metrics"]["tokens"]:
            raise ValueError("independent EOC/fees differ")
    finally: env.close()
    expected_status = {"task_id": task.task_id, "completed": True, "charged_tokens": replay["metrics"]["tokens"],
        "failure": None, "charged_model_requests": len(admission.approved), "approved_unknown_requests": 0}
    if status != expected_status: raise ValueError("raw settlement status differs")
    return {"row": row, "status": status, "replayed_checkpoints": cursor,
        "evidence_index": {str(p.relative_to(folder)).replace("\\", "/"): digest_file(p)
            for p in folder.rglob("*") if p.is_file() and p.suffix in {".json", ".sqlite"}}}
