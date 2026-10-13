"""Revised P1 same-state availability smoke / independent read-only audit.

Not a formal Skill evolution experiment. All three static skills are offered in
the treatment: no private opportunity label chooses the option for the model.
"""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import random
import sqlite3
import time

from scripts.evolution_forks import prepare_snapshot, fork_starts, check_pair
from scripts.evolution_opportunities import evaluate_opportunities, selection_funnel
from scripts.run_skill_evolution import ROOT, ModelSession, digest_file, snapshot_sources, static_catalog, smoke_tasks, prior_cost
from skillforge.environment import Environment, ToolError
from skillforge.evolution_common.artifacts import SplitLedger
from skillforge.evolution_common.snapshot import restore_snapshot, save_snapshot
from skillforge.evolution_registry import immutable_json
from skillforge.evolution_schemas import fingerprint
from skillforge.schemas import Task
from skillforge.schemas import SkillContract
from skillforge.skill_evolution.runtime import PROTOCOL, runtime_sources
from skillforge.skill_evolution.catalog import Catalog
from skillforge.skills import gate
from skillforge.verifier import verify


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def smoke(config, output):
    from scripts.execution_aware_gpu_lease import GPUServiceLease
    started = time.perf_counter()
    catalog, sources = static_catalog(config), snapshot_sources(output)
    prior = prior_cost(config)
    prior_tokens, prior_wall = sum(r["tokens"] for r in prior), sum(r["wall_seconds"] for r in prior)
    tasks = smoke_tasks(config)
    catalog.save(output / "catalog.json")
    immutable_json(output / "private-dev-tasks.json", [t.model_dump() for t in tasks])
    registration = {"schema": "availability-fork-dev-v1", "config": config, "protocol": PROTOCOL,
                    "catalog_hash": catalog.hash, "sources": sources, "prior_cost": prior,
                    "intervention": "all static verified skills loaded versus none; same initial public reads and history; search/load disabled in both",
                    "scope": "two developmental task pairs, no admission or statistical efficacy claim"}
    immutable_json(output / "registration.json", {**registration, "protocol_hash": fingerprint(registration)})
    ledger = SplitLedger(ROOT / "results/skill-evolution/v1.2/source-ledger")
    prepared = []
    for task in tasks:
        ledger.claim(task.task_id, "dev", related_groups=[task.parameters["order_id"], task.customer_id])
        folder = output / task.task_id
        folder.mkdir()
        env = Environment(str(folder / "source.sqlite"), fixture=task.fixture)
        public = {k: getattr(task, k) for k in ("task_id", "family", "request", "parameters")}
        try:
            observations = {}
            for name in ("get_order", "get_customer", "get_payment", "get_shipment"):
                observations.update(env.call(name, {"order_id": task.parameters["order_id"]}, task.customer_id))
            staged = prepare_snapshot(folder / "initial-snapshot", env, public, catalog, observations, random.Random(task.seed))
            opportunities = evaluate_opportunities(task, catalog, folder / "initial-snapshot", folder / "opportunity-forks", staged["runtime_identity"])
            immutable_json(folder / "opportunities.json", opportunities)
            loaded = {e["skill_id"]: {"revision": e["revision"], "content_hash": e["revision"]} for e in catalog.entries()
                      if e["contract"]["status"] == "VERIFIED"}
            starts = fork_starts(folder / "initial-snapshot", catalog, loaded)
            prepared.append((task, public, folder, staged, starts, opportunities))
        finally:
            env.close()
    rows, pairs, failure, unfinished = [], [], None, None
    try:
        with GPUServiceLease(), ExitStack() as cleanup:
            session = ModelSession(config, output)
            cleanup.callback(session.close)
            immutable_json(output / "model-identity.json", session.settings)
            for task, public, folder, staged, starts, opportunities in prepared:
                arms = {}
                # Counterbalance which arm is executed first; record the order.
                order = ("provided", "withheld") if len(pairs) % 2 == 0 else ("withheld", "provided")
                for arm in order:
                    charged = prior_tokens + sum(r["agent"]["metrics"]["tokens"] for r in rows)
                    if charged + config["limits"]["max_tokens"] > config["smoke"]["max_model_tokens"]:
                        raise ValueError("shared developmental token budget exhausted before arm")
                    remaining = config["smoke"]["max_wall_seconds"] - prior_wall - (time.perf_counter() - started)
                    if remaining <= 0:
                        raise TimeoutError("shared developmental wall budget exhausted")
                    arm_dir = folder / arm
                    env, saved, rng = restore_snapshot(folder / "initial-snapshot", arm_dir / "live.sqlite", staged["runtime_identity"])
                    prefix_audit_count, initial = len(env.audit), env.snapshot()
                    checkpoint_index = 0
                    session.send({"type": "run", "task": public, "catalog": catalog.entries(),
                                  "limits": config["limits"], "public_start": starts[arm]})
                    try:
                        while True:
                            remaining = config["smoke"]["max_wall_seconds"] - prior_wall - (time.perf_counter() - started)
                            if remaining <= 0:
                                raise TimeoutError("shared developmental wall budget exhausted")
                            msg = session.receive(min(120, remaining))
                            if msg["type"] == "completed":
                                break
                            if msg["type"] == "checkpoint":
                                unfinished = msg["value"]["budget"]
                                save_snapshot(arm_dir / "checkpoints" / str(checkpoint_index), env, msg["value"], rng)
                                checkpoint_index += 1
                                session.send({"type": "checkpoint_saved"})
                            elif msg["type"] == "tool":
                                before = len(env.audit)
                                try:
                                    result = env.call(msg["name"], msg["arguments"], task.customer_id, msg["key"])
                                    response = {"type": "tool_result", "result": result}
                                except ToolError as exc:
                                    response = {"type": "tool_result", "error": exc.code}
                                finally:
                                    for event in env.audit[before:]: event["decision_origin"] = msg["source"]
                                session.send(response)
                            else:
                                raise ValueError("unexpected worker RPC")
                        agent = msg["result"]
                        verdict = verify(task, initial, env.snapshot(), env.audit, agent["outcome"])
                        row = {"task_id": task.task_id, "arm": arm, "experiment_split": "dev", "public_start": starts[arm],
                               "initial_state_hash": fingerprint(initial), "snapshot_hash": staged["snapshot_hash"],
                               "task_hash": fingerprint(task.model_dump()), "prefix_audit_count": prefix_audit_count,
                               "agent": agent, "verification": verdict, "tool_audit": env.audit,
                               "selection_funnel": selection_funnel(agent, opportunities, verdict)}
                        immutable_json(arm_dir / "result.json", row)
                        rows.append(row); arms[arm] = agent; unfinished = None
                        print(json.dumps({"task": task.task_id, "arm": arm, "eoc": verdict["task_success"],
                                          "skills": len(agent["skill_events"]), "tokens": agent["metrics"]["tokens"]}), flush=True)
                    finally:
                        env.close()
                pair = {"task_id": task.task_id, "order": list(order), **check_pair(arms["provided"], arms["withheld"])}
                immutable_json(folder / "pair-check.json", pair)
                pairs.append(pair)
    except Exception as exc:
        failure = type(exc).__name__ + ": " + str(exc)
    charged = sum(r["agent"]["metrics"]["tokens"] for r in rows) + (unfinished or {}).get("used", {}).get("tokens", 0)
    wall = time.perf_counter() - started
    report = {"status": "complete" if len(pairs) == len(tasks) and failure is None else "blocked_or_incomplete",
              "failure": failure, "n": len(rows), "planned": 2 * len(tasks), "pairs": len(pairs),
              "eoc": sum(r["verification"]["task_success"] for r in rows),
              "actual_violations": sum(r["verification"]["actual_policy_violation"] for r in rows),
              "attempted_violations": sum(r["verification"]["attempted_policy_violation"] for r in rows),
              "tokens": sum(r["agent"]["metrics"]["tokens"] for r in rows),
              "charged_tokens_including_incomplete": charged, "wall_seconds": wall,
              "shared_total_charged_tokens": prior_tokens + charged, "shared_total_wall_seconds": prior_wall + wall,
              "unfinished_task_budget": unfinished, "shared_prior_cost": prior,
              "preparation_tool_calls": 4 * len(tasks), "opportunity_evaluation_tool_calls": sum(len(r.get("tool_audit", [])) for _,_,_,_,_,o in prepared for r in o["opportunities"]),
              "engineering_passed": bool(len(pairs) == len(tasks) and not failure),
              "research_claim_passed": None, "isolated_activated": False,
              "scope": "availability causality plumbing; independent unit task pair; not Skill learning, retrieval efficacy or significance"}
    immutable_json(output / "report.json", report)
    return report


def audit(root):
    root = Path(root); reg, report = read(root / "registration.json"), read(root / "report.json")
    if fingerprint({k: v for k, v in reg.items() if k != "protocol_hash"}) != reg["protocol_hash"]:
        raise ValueError("protocol hash mismatch")
    catalog = Catalog.load(root / "catalog.json")
    if catalog.hash != reg["catalog_hash"]:
        raise ValueError("catalog mismatch")
    for name, expected in reg["sources"].items():
        if digest_file(root / "source-snapshot" / name) != expected:
            raise ValueError("source snapshot mismatch")
    settings = read(root / "model-identity.json")
    pairs, tokens, cases, actual, attempted, eoc = [], 0, 0, 0, 0, 0
    for data in read(root / "private-dev-tasks.json"):
        task = Task.model_validate(data); folder = root / task.task_id
        snap = read(folder / "initial-snapshot/snapshot.json")
        if fingerprint(snap["body"]) != snap["hash"] or digest_file(folder / "initial-snapshot/environment.sqlite") != snap["body"]["database_sha256"]:
            raise ValueError("initial snapshot mismatch")
        offered_refs = {e["skill_id"]: {"revision": e["revision"], "content_hash": e["revision"]}
                        for e in catalog.entries() if e["contract"]["status"] == "VERIFIED"}
        expected_starts = fork_starts(folder / "initial-snapshot", catalog, offered_refs)
        arms = {arm: read(folder / arm / "result.json") for arm in ("provided", "withheld")}
        checked = check_pair(arms["provided"]["agent"], arms["withheld"]["agent"])
        saved_pair = read(folder / "pair-check.json")
        if any(saved_pair[k] != v for k, v in checked.items()) or arms["provided"]["initial_state_hash"] != arms["withheld"]["initial_state_hash"]:
            raise ValueError("pair initial conditions mismatch")
        for arm, row in arms.items():
            agent = row["agent"]; public = {k: data[k] for k in ("task_id", "family", "request", "parameters")}
            if (row["public_start"] != expected_starts[arm] or row["snapshot_hash"] != snap["hash"] or
                    row["tool_audit"][:row["prefix_audit_count"]] != snap["body"]["audit"] or
                    row["prefix_audit_count"] != len(snap["body"]["audit"]) or
                    agent["steps"][0]["context"]["observations"] != expected_starts[arm]["observations"]):
                raise ValueError("fork did not inherit declared initial public state")
            limits = reg["config"]["limits"]
            runtime = {k.removeprefix("skillforge/"): v for k, v in reg["sources"].items() if k.startswith("skillforge/") and k != "skillforge/verifier.py"}
            expected_identity = fingerprint({"task": public, "catalog": catalog.hash, "model": settings,
                                             "protocol": reg["protocol"], "sources": runtime,
                                             "limits": [limits[k] for k in ("max_steps", "max_search", "max_load", "max_tokens")],
                                             "auto_terminate": True, "public_start": row["public_start"]})
            if agent["identity"] != expected_identity or row["task_hash"] != fingerprint(data):
                raise ValueError("runtime identity mismatch")
            initial_env = Environment(fixture=task.fixture)
            try: initial = initial_env.snapshot()
            finally: initial_env.close()
            if fingerprint(initial) != row["initial_state_hash"]:
                raise ValueError("initial goal state mismatch")
            audit_log = row["tool_audit"]
            final = audit_log[-1]["after_state"] if audit_log else initial
            if verify(task, initial, final, audit_log, agent["outcome"]) != row["verification"]:
                raise ValueError("independent paired EOC mismatch")
            if len(audit_log) - row["prefix_audit_count"] != agent["metrics"]["tool_calls"]:
                raise ValueError("runtime tool cost mismatch")
            opportunities = read(folder / "opportunities.json")
            if selection_funnel(agent, opportunities, row["verification"]) != row["selection_funnel"]:
                raise ValueError("paired selection funnel mismatch")
            charged = sum(r["charged_tokens"] for r in agent["model_requests"])
            if charged != agent["metrics"]["tokens"] or charged != agent["budget"]["used"].get("tokens", 0):
                raise ValueError("paired model cost mismatch")
            for step in agent["steps"]:
                context, trace = step["context"], step["selection_trace"]
                if (trace["model_visible_context_hash"] != fingerprint(context) or
                        trace["model_messages_hash"] != fingerprint(step["messages"]) or
                        json.loads(step["messages"][1]["content"]) != context or
                        "selection_trace" in str(context["history"]) or
                        {k: context[k] for k in public} != public):
                    raise ValueError("paired public context/message mismatch")
                for loaded in context["catalog"]["loaded_skills"]:
                    expected = catalog.public_load(loaded["skill_id"], loaded["revision"], enrich=True)
                    skill = SkillContract.model_validate(catalog.get(loaded["skill_id"], loaded["revision"])["contract"])
                    expected["gate"] = gate(skill, context["observations"], task.parameters).model_dump()
                    if loaded != expected:
                        raise ValueError("paired public Skill view differs from exact catalog revision")
            checkpoints = sorted((folder / arm / "checkpoints").glob("*/snapshot.json"), key=lambda p: int(p.parent.name))
            if not checkpoints:
                raise ValueError("missing arm checkpoints")
            for path in checkpoints:
                checkpoint = read(path)
                if (fingerprint(checkpoint["body"]) != checkpoint["hash"] or
                        digest_file(path.parent / "environment.sqlite") != checkpoint["body"]["database_sha256"] or
                        checkpoint["body"]["runtime"]["identity"] != agent["identity"]):
                    raise ValueError("paired checkpoint mismatch")
            saved = read(checkpoints[-1])["body"]["runtime"]
            if any(saved[k] != agent[k] for k in ("identity", "steps", "budget", "execution_contract", "outcome")):
                raise ValueError("final paired runtime mismatch")
            private = Environment.__new__(Environment)
            private.order_id = task.parameters["order_id"]
            private.db = sqlite3.connect((checkpoints[-1].parent / "environment.sqlite").resolve().as_uri() + "?mode=ro", uri=True)
            private.db.row_factory = sqlite3.Row
            try:
                if private.snapshot() != final:
                    raise ValueError("final paired SQLite state mismatch")
            finally:
                private.close()
            tokens += charged; cases += 1
            actual += row["verification"]["actual_policy_violation"]
            attempted += row["verification"]["attempted_policy_violation"]
            eoc += row["verification"]["task_success"]
        pairs.append(checked)
    if (cases != report["n"] or tokens != report["tokens"] or eoc != report["eoc"] or
            actual != report["actual_violations"] or attempted != report["attempted_violations"]):
        raise ValueError("paired aggregate mismatch")
    result = {"passed": report["status"] == "complete", "pairs": len(pairs), "cases": cases,
              "charged_tokens": tokens, "generator_sha256": digest_file(__file__),
              "report_sha256": digest_file(root / "report.json"), "protocol_hash": reg["protocol_hash"],
              "scope": "source/message/initial state pairing, checkpoint integrity, EOC and cost recomputation; no significance claim"}
    immutable_json(root / "evidence-audits" / (result["generator_sha256"] + ".json"), result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["smoke", "audit"])
    parser.add_argument("--config", default="configs/skill-evolution-v1.2.fork-dev.json")
    parser.add_argument("--output"); parser.add_argument("--run")
    args = parser.parse_args()
    if args.command == "audit":
        result = audit(args.run)
    else:
        output = Path(args.output).resolve(); output.mkdir(parents=True, exist_ok=False)
        result = smoke(read(args.config), output)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    raise SystemExit(0 if result.get("passed", result.get("status") == "complete") else 1)


if __name__ == "__main__":
    main()
