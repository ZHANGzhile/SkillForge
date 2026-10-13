"""Read-only P1 evidence audit; never runs a model or feeds labels to learning."""
import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

from skillforge.environment import Environment
from skillforge.evolution_registry import immutable_json
from skillforge.evolution_schemas import fingerprint
from skillforge.execution_aware.contracts import ExecutionContract
from skillforge.schemas import Task
from skillforge.skill_evolution.catalog import Catalog
from skillforge.verifier import verify
from scripts.evolution_opportunities import selection_funnel


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def audit(root):
    root = Path(root)
    registration, report = read(root / "registration.json"), read(root / "report.json")
    tasks = {t["task_id"]: Task.model_validate(t) for t in read(root / "private-dev-tasks.json")}
    catalog = Catalog.load(root / "catalog.json")
    source_index = (root / "source-snapshot.json")
    recovered = False
    if source_index.exists():
        sources = read(source_index)
    else:
        sources = read(root / "source-snapshot-recovered.json")["files"]
        recovered = True
    for name, expected in sources.items():
        if sha(root / "source-snapshot" / name) != expected:
            raise ValueError("source snapshot hash mismatch")
    for name, expected in registration["sources"].items():
        if sources.get("skillforge/" + name.replace("\\", "/")) != expected:
            raise ValueError("registered source missing from snapshot")
    rows, case_hashes, model_calls, charged_tokens, checkpoints = [], {}, 0, 0, 0
    model_settings = read(root / "model-identity.json")
    for path in sorted(root.glob("*/result.json")):
        row = read(path)
        task = tasks[row["task_id"]]
        agent = row["agent"]
        if row["task_id"] in case_hashes or fingerprint(task.model_dump()) != row["task_hash"]:
            raise ValueError("task identity mismatch or duplicate")
        public = {k: getattr(task, k) for k in ("task_id", "family", "request", "parameters")}
        limits = registration["config"]["limits"]
        expected_identity = fingerprint({"task": public, "catalog": catalog.hash, "model": model_settings,
                                         "protocol": registration["protocol"], "sources": registration["sources"],
                                         "limits": [limits[k] for k in ("max_steps", "max_search", "max_load", "max_tokens")],
                                         "auto_terminate": task.family in {"refund", "modify_address", "cancel_order"}})
        if agent["identity"] != expected_identity or agent["catalog_hash"] != catalog.hash:
            raise ValueError("Agent execution identity mismatch")
        for step in agent["steps"]:
            context = step["context"]
            if {k: context[k] for k in public} != public or {"fixture", "expected", "gold"} & set(context):
                raise ValueError("non-public task context")
            if step.get("messages"):
                if len(step["messages"]) != 2 or json.loads(step["messages"][1]["content"]) != context:
                    raise ValueError("exact model messages/context mismatch")
            action = step["action"] or {}
            observable = registration["protocol"] in {
                "skill-search-load-use-v1.2-dev3-observable",
                "skill-search-load-use-v1.2-dev4-action-contract",
                "skill-search-load-use-v1.2-dev5-readonly-goals",
            }
            if observable:
                trace = step["selection_trace"]
                available = sorted([{"skill_id": e["skill_id"], "revision": e["revision"]} for e in catalog.entries()
                                    if e["contract"]["status"] == "VERIFIED"], key=lambda r: (r["skill_id"], r["revision"]))
                if (trace["model_visible_context_hash"] != fingerprint(context) or
                        trace["model_messages_hash"] != fingerprint(step.get("messages", [])) or
                        trace["selected_action"] != action or trace["available_verified"] != available or
                        trace["available_skill_set_hash"] != fingerprint(available) or
                        "selection_trace" in str(context["history"])):
                    raise ValueError("selection trace integrity/public separation mismatch")
            if action.get("name") == "search_skills" and not step.get("error"):
                expected = catalog.search_audited(**action["arguments"])[0] if observable else catalog.search(**action["arguments"])
                if step["result"] != expected:
                    raise ValueError("search replay mismatch")
            if action.get("name") == "load_skill" and not step.get("error"):
                args = action["arguments"]
                if step["result"] != catalog.public_load(args["skill_id"], args["revision"], enrich=observable):
                    raise ValueError("public load mismatch")
        if observable:
            for event in agent["search_events"]:
                results, replay = catalog.search_audited(**event["arguments"])
                if (results != event["results"] or
                        {k: v for k, v in replay.items() if k != "latency_ms"} !=
                        {k: v for k, v in event["audit"].items() if k != "latency_ms"} or event["audit"]["latency_ms"] < 0):
                    raise ValueError("search ranking audit mismatch")
            if "selection_funnel" in row:
                opportunities = read(path.parent / "opportunities.json")
                if (row["opportunity_hash"] != fingerprint(opportunities) or
                        row["selection_funnel"] != selection_funnel(agent, opportunities, row["verification"])):
                    raise ValueError("independent opportunity/funnel mismatch")
        tracker = ExecutionContract.restore(agent["execution_contract"], task.task_id)
        if [r.to_dict() for r in tracker.receipts] != agent["verification_receipts"]:
            raise ValueError("verification receipt mismatch")
        env = Environment(fixture=task.fixture)
        try: initial = env.snapshot(task.parameters["order_id"])
        finally: env.close()
        audit_log = row["tool_audit"]
        final = audit_log[-1]["after_state"] if audit_log else initial
        if verify(task, initial, final, audit_log, agent["outcome"]) != row["verification"]:
            raise ValueError("independent EOC mismatch")
        if any(e["tool_name"] in {"search_skills", "load_skill"} for e in audit_log):
            raise ValueError("virtual catalog action reached business Environment")
        if len(audit_log) != agent["metrics"]["tool_calls"]:
            raise ValueError("tool cost mismatch")
        total_tokens = sum(r["charged_tokens"] for r in agent["model_requests"])
        if total_tokens != agent["metrics"]["tokens"] or total_tokens != agent["budget"]["used"].get("tokens", 0):
            raise ValueError("model cost mismatch")
        task_checkpoints = sorted(path.parent.glob("checkpoints/*/snapshot.json"), key=lambda p: int(p.parent.name))
        if not task_checkpoints:
            raise ValueError("durable runtime checkpoint missing")
        for checkpoint in task_checkpoints:
            item = read(checkpoint)
            if fingerprint(item["body"]) != item["hash"] or sha(checkpoint.parent / "environment.sqlite") != item["body"]["database_sha256"]:
                raise ValueError("checkpoint database/runtime mismatch")
            if item["body"]["runtime"]["identity"] != agent["identity"]:
                raise ValueError("checkpoint task identity mismatch")
            checkpoints += 1
        final_checkpoint = read(task_checkpoints[-1])["body"]["runtime"]
        for key in ("identity", "execution_contract", "loaded_refs", "budget", "steps", "outcome", "termination_source"):
            if final_checkpoint[key] != agent[key]:
                raise ValueError("final runtime checkpoint differs from result")
        private = Environment.__new__(Environment)
        private.order_id = task.parameters["order_id"]
        private.db = sqlite3.connect((task_checkpoints[-1].parent / "environment.sqlite").resolve().as_uri() + "?mode=ro", uri=True)
        private.db.row_factory = sqlite3.Row
        try:
            if private.snapshot() != final:
                raise ValueError("final SQLite state differs from EOC evidence")
        finally: private.close()
        rows.append(row)
        case_hashes[row["task_id"]] = sha(path)
        model_calls += agent["metrics"]["llm_calls"]
        charged_tokens += total_tokens
    if len(rows) != report["n"] or report["planned"] != len(tasks) or charged_tokens != report["tokens"]:
        raise ValueError("aggregate count/cost mismatch")
    for key, actual in {"eoc": sum(r["verification"]["task_success"] for r in rows),
                        "actual_violations": sum(r["verification"]["actual_policy_violation"] for r in rows),
                        "attempted_violations": sum(r["verification"]["attempted_policy_violation"] for r in rows)}.items():
        if report[key] != actual: raise ValueError("aggregate verdict mismatch")
    result = {"passed": report["status"] == "complete" and len(rows) == len(tasks), "cases": len(rows),
              "model_calls": model_calls, "charged_tokens": charged_tokens, "checkpoints": checkpoints,
              "sources": len(sources), "source_snapshot_recovered": recovered,
              "generator_sha256": sha(__file__), "registration_sha256": sha(root / "registration.json"),
              "report_sha256": sha(root / "report.json"), "case_hashes": case_hashes,
              "scope": "identity, source snapshots, public catalog replay, exact saved messages, receipt integrity, EOC/cost recomputation and SQLite backup hashes; no inference rerun or causal efficacy claim"}
    receipt = root / "evidence-audits" / (result["generator_sha256"] + ".json")
    immutable_json(receipt, result)
    if not (root / "evidence-audit.json").exists():
        immutable_json(root / "evidence-audit.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--run", required=True)
    result = audit(parser.parse_args().run)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["passed"] else 1)
