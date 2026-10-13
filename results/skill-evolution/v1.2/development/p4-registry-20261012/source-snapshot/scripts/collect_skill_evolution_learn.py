"""Registered real-model workflow learn collection and independent audit.

Only public task/catalog/tool RPC reach the worker. Private fixtures, coverage,
EOC and source ownership remain in this controller. No mock model fallback.
"""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import random
import shutil
import sqlite3
import time

from scripts.continue_skill_evolution_selection import audit_continuation, publish
from scripts.evolution_budget import CheckpointAdmission
from scripts.evolution_forks import prepare_snapshot
from scripts.run_skill_evolution import ROOT, ModelSession, digest_file, static_catalog
from skillforge.environment import Environment, ToolError
from skillforge.evolution_common.artifacts import SplitLedger
from skillforge.evolution_common.snapshot import save_snapshot
from skillforge.evolution_schemas import fingerprint
from skillforge.execution_aware.contracts import ExecutionContract
from skillforge.schemas import SkillContract
from skillforge.skills import hydrate, gate, execute
from skillforge.skill_evolution.catalog import Catalog
from skillforge.skill_evolution.experience import mine_opportunities
from skillforge.skill_evolution.runtime import PROTOCOL, runtime_sources
from skillforge.skill_evolution.workflows import GOALS, WorkflowCase, private_items, verify_workflow


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def evaluate_static(case, catalog):
    evidence = []
    for entry in catalog.entries():
        skill = SkillContract.model_validate(entry["contract"])
        if skill.status != "VERIFIED":
            continue
        env = Environment(fixture=case.fixture)
        initial, items, state = env.snapshot(), private_items(env), {}
        tracker = ExecutionContract(case.task_id + ":coverage:" + skill.skill_id)
        def dispatch(name, args, key):
            result = env.call(name, args, case.authenticated_customer_id, key)
            env.audit[-1]["decision_origin"] = "scripted:static-coverage"
            return result
        def call(name, args, key):
            return tracker.call(dispatch, name, args, key, source="skill")
        event, status, verdict = None, "INPUT_NOT_AVAILABLE", None
        try:
            if all(name in case.parameters for name in skill.inputs):
                hydrate(skill, state, case.parameters, call, case.task_id)
                status = gate(skill, state, case.parameters).status
                if status == "APPLICABLE":
                    event = execute(skill, case.parameters, state, call, case.task_id)
                    verdict = verify_workflow(case, initial, env.snapshot(), env.audit,
                                              "completed" if event["success"] else "error", items, private_items(env))
            evidence.append({"skill_id": entry["skill_id"], "revision": entry["revision"], "status": status,
                             "program_structure_hash": fingerprint({"inputs": sorted(skill.inputs), "calls":
                                 [{"tool": node.tool, "arguments": node.arguments} for node in skill.procedure if node.kind == "call"]}),
                             "covers_goal": bool(verdict and verdict["task_success"] and not tracker.pending()),
                             "event": event, "verification": verdict, "tool_audit": env.audit})
        finally:
            env.close()
    return evidence


def collect_one(session, case, catalog, folder, config, prior_tokens, prior_wall, started):
    folder.mkdir(parents=True, exist_ok=False)
    env = Environment(str(folder / "live.sqlite"), fixture=case.fixture)
    rng, initial, items = random.Random(case.seed), env.snapshot(), private_items(env)
    coverage = evaluate_static(case, catalog)
    publish(folder / "static-coverage.json", coverage)
    staged = prepare_snapshot(folder / "initial-snapshot", env, case.public_task(), catalog, {}, rng)
    admission = CheckpointAdmission(prior_tokens, config["budget"]["project_max_tokens"], prior_wall,
                                    config["budget"]["project_max_wall_seconds"])
    index, denied, failure, row = 0, None, None, None
    try:
        session.send({"type": "run", "task": case.public_task(), "catalog": catalog.entries(), "limits": config["limits"]})
        while True:
            remaining = admission.remaining(time.perf_counter() - started)
            if remaining <= 0:
                raise TimeoutError("P2 registered wall budget exhausted")
            msg = session.receive(min(120, remaining))
            if msg["type"] == "completed":
                agent = msg["result"]
                verdict = verify_workflow(case, initial, env.snapshot(), env.audit, agent["outcome"], items, private_items(env))
                if admission.charged_tokens() != agent["metrics"]["tokens"]:
                    raise ValueError("final inference charge mismatch")
                row = {"schema": "workflow-learn-trajectory-v1", "case": case.model_dump(),
                       "model_identity_hash": fingerprint(session.settings), "snapshot_hash": staged["snapshot_hash"],
                       "initial_state": initial, "initial_items": items, "final_state": env.snapshot(), "final_items": private_items(env),
                       "agent": agent, "tool_audit": env.audit, "verification": verdict, "static_coverage": coverage}
                publish(folder / "result.json", row)
                break
            if msg["type"] == "checkpoint":
                value = msg["value"]
                save_snapshot(folder / "checkpoints" / str(index), env, value, rng)
                decision = admission.inspect(value, time.perf_counter() - started)
                if decision is not None:
                    decision["checkpoint_index"] = index
                    publish(folder / "admissions" / (str(decision["request_index"]) + ".json"), decision)
                    if not decision["approved"]:
                        denied = decision
                        raise ValueError("inference denied before ACK: " + decision["reason"])
                    admission.record_approval(decision)
                index += 1
                session.send({"type": "checkpoint_saved"})
            elif msg["type"] == "tool":
                before = len(env.audit)
                try:
                    value = env.call(msg["name"], msg["arguments"], case.authenticated_customer_id, msg["key"])
                    response = {"type": "tool_result", "result": value}
                except ToolError as exc:
                    response = {"type": "tool_result", "error": exc.code}
                finally:
                    for event in env.audit[before:]: event["decision_origin"] = msg["source"]
                session.send(response)
            else:
                raise ValueError("unexpected workflow worker RPC")
    except Exception as exc:
        failure = type(exc).__name__ + ": " + str(exc)
    finally:
        env.close()
    status = {"task_id": case.task_id, "completed": row is not None, "failure": failure,
              "charged_tokens": admission.charged_tokens(), "denied_before_ack": denied,
              "last_budget": admission.last["budget"] if admission.last else None,
              "static_evaluation_tool_calls": sum(len(e["tool_audit"]) for e in coverage)}
    publish(folder / "collection-status.json", status)
    return row, status


def register(config, output):
    declaration = ROOT / config["declaration"]
    goals, declared = read(declaration / "goals.json"), read(declaration / "report.json")
    expected = {key: {"goal": value.model_dump(), "hash": value.identity} for key, value in GOALS.items()}
    if goals != expected or declared["goal_set_hash"] != fingerprint(goals):
        raise ValueError("predeclared goal mismatch")
    cases = [WorkflowCase.model_validate(row) for row in read(declaration / "planned-learn-cases.json")]
    if any(case.split != "train" for case in cases) or len({case.task_id for case in cases}) != len(cases):
        raise ValueError("unique learn/train cases required")
    for case in cases: case.public_task()
    parent = ROOT / config["budget"]["p1_closed_run"]
    receipt = audit_continuation(parent)
    prior = read(parent / "report.json")
    if not receipt["run_completed"] or prior.get("unfinished_task_budget"):
        raise ValueError("prior P1 run must be closed/reconciled")
    budget = config["budget"]
    ledger_root = ROOT / "results/skill-evolution/v1.2/learn-budget-ledger"
    history = []
    for path in sorted(ledger_root.glob("*.json")):
        owner = read(path)
        if owner["phase_id"] == budget["phase_id"]:
            raise ValueError("phase already registered; inspect its report before declaring a new budget")
        previous_path = ROOT / owner["output"] / "report.json"
        if not previous_path.exists():
            raise ValueError("prior learn phase is open; cannot reset its budget")
        previous = read(previous_path)
        if any(not s["completed"] and not s["denied_before_ack"] for s in previous["case_statuses"]):
            raise ValueError("prior incomplete learn phase requires reconciliation")
        history.append({"path": owner["output"], "report_sha256": digest_file(previous_path),
                        "tokens": previous["charged_tokens_including_incomplete"], "wall_seconds": previous["wall_seconds"]})
    prior_tokens = prior["shared_total_charged_tokens"] + sum(r["tokens"] for r in history)
    prior_wall = prior["shared_total_wall_seconds"] + sum(r["wall_seconds"] for r in history)
    if (budget["project_max_tokens"] != prior_tokens + budget["phase_max_tokens"] or
            abs(budget["project_max_wall_seconds"] - prior_wall - budget["phase_max_wall_seconds"]) > 1e-6):
        raise ValueError("explicit phase budget must preserve P1 cumulative costs")
    sources = {"skillforge/" + name: value for name, value in runtime_sources().items()}
    sources.update({name: digest_file(ROOT / name) for name in
                    ("scripts/collect_skill_evolution_learn.py", "scripts/evolution_budget.py",
                     "scripts/run_skill_evolution.py", "scripts/evolution_forks.py",
                     "scripts/continue_skill_evolution_selection.py", "scripts/run_skill_evolution_selection.py")})
    for name in sources:
        target = output / "source-snapshot" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
        if digest_file(target) != sources[name]:
            raise ValueError("source changed during collection registration")
    catalog = static_catalog(config)
    catalog.save(output / "catalog.json")
    publish(output / "private-learn-cases.json", [case.model_dump() for case in cases])
    publish(output / "goals.json", goals)
    reg = {"schema": "workflow-learn-collection-v1", "config": config, "protocol": PROTOCOL, "sources": sources,
           "catalog_hash": catalog.hash, "declaration_report_sha256": digest_file(declaration / "report.json"),
           "cases_hash": fingerprint([case.model_dump() for case in cases]), "goal_set_hash": fingerprint(goals),
           "p1_report_sha256": digest_file(parent / "report.json"), "p1_audit": receipt,
           "prior_tokens": prior_tokens, "prior_wall_seconds": prior_wall, "prior_learn_runs": history,
           "scope": "P2 learn-only development collection, fixed main-v3 and historical static catalog; no formal validation/test or activation"}
    reg["protocol_hash"] = fingerprint(reg)
    publish(output / "registration.json", reg)
    publish(ledger_root / (fingerprint(budget["phase_id"]) + ".json"),
            {"phase_id": budget["phase_id"], "output": output.relative_to(ROOT).as_posix(),
             "protocol_hash": reg["protocol_hash"], "registered_budget": budget})
    return reg, cases, catalog


def collect(config, output):
    from scripts.execution_aware_gpu_lease import GPUServiceLease
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    reg, cases, catalog = register(config, output)
    ledger = SplitLedger(ROOT / "results/skill-evolution/v1.2/source-ledger")
    for case in cases:
        ledger.claim(case.source_group, "train", related_groups=[case.task_id, case.parameters["order_id"], case.authenticated_customer_id])
    rows, statuses, failure = [], [], None
    try:
        with GPUServiceLease(), ExitStack() as cleanup:
            remaining = config["budget"]["project_max_wall_seconds"] - reg["prior_wall_seconds"] - (time.perf_counter() - started) - 10
            if remaining <= 0: raise TimeoutError("P2 wall budget exhausted before loading")
            session = ModelSession(config, output, init_timeout=remaining)
            cleanup.callback(session.close)
            if session.settings.get("engineering_only") is not False or session.settings.get("adapter_sha256") != config["adapter_sha256"]:
                raise ValueError("registered real model adapter required")
            publish(output / "model-identity.json", session.settings)
            for case in cases:
                row, status = collect_one(session, case, catalog, output / case.task_id, config,
                                          reg["prior_tokens"] + sum(s["charged_tokens"] for s in statuses), reg["prior_wall_seconds"], started)
                statuses.append(status)
                if row: rows.append(row)
                print(json.dumps({"task": case.task_id, "eoc": row["verification"]["task_success"] if row else None,
                                  "tokens": status["charged_tokens"], "failure": status["failure"]}), flush=True)
                if not status["completed"]:
                    failure = status["failure"]; break
    except Exception as exc:
        failure = type(exc).__name__ + ": " + str(exc)
    charged, wall = sum(s["charged_tokens"] for s in statuses), time.perf_counter() - started
    report = {"schema": "workflow-learn-report-v1", "protocol_hash": reg["protocol_hash"],
              "status": "complete" if len(rows) == len(cases) and not failure else "blocked_or_incomplete",
              "failure": failure, "n": len(rows), "planned": len(cases),
              "eoc": sum(row["verification"]["task_success"] for row in rows),
              "attempted_policy_violations": sum(row["verification"]["attempted_policy_violation"] for row in rows),
              "actual_policy_violations": sum(row["verification"]["actual_policy_violation"] for row in rows),
              "actual_workflow_violations": sum(row["verification"]["actual_workflow_violation"] for row in rows),
              "tokens": sum(row["agent"]["metrics"]["tokens"] for row in rows),
              "charged_tokens_including_incomplete": charged, "wall_seconds": wall,
              "shared_total_charged_tokens": reg["prior_tokens"] + charged,
              "shared_total_wall_seconds": reg["prior_wall_seconds"] + wall,
              "case_statuses": statuses, "program_admitted": False, "agent_admitted": False,
              "research_claim_passed": None, "isolated_activated": False, "deployed": False}
    publish(output / "report.json", report)
    return report


def audit(root):
    root = Path(root); reg, report = read(root / "registration.json"), read(root / "report.json")
    if fingerprint({k: v for k, v in reg.items() if k != "protocol_hash"}) != reg["protocol_hash"] or report["protocol_hash"] != reg["protocol_hash"]:
        raise ValueError("collection protocol hash mismatch")
    for name, expected in reg["sources"].items():
        if digest_file(root / "source-snapshot" / name) != expected:
            raise ValueError("collection source snapshot mismatch")
    if digest_file(ROOT / "skillforge/skill_evolution/workflows.py") != reg["sources"]["skillforge/skill_evolution/workflows.py"]:
        raise ValueError("workflow verifier differs; audit with registered source version")
    cases, settings = read(root / "private-learn-cases.json"), read(root / "model-identity.json")
    catalog = Catalog.load(root / "catalog.json")
    if fingerprint(cases) != reg["cases_hash"] or catalog.hash != reg["catalog_hash"]:
        raise ValueError("collection data identity mismatch")
    if fingerprint(read(root / "goals.json")) != reg["goal_set_hash"] or settings.get("engineering_only") is not False:
        raise ValueError("collection goals or real model identity mismatch")
    rows, statuses, charged = [], [], 0
    for case_data in cases:
        case = WorkflowCase.model_validate(case_data); folder = root / case.task_id
        if not (folder / "collection-status.json").exists(): continue
        status = read(folder / "collection-status.json")
        if status["task_id"] != case.task_id:
            raise ValueError("collection status task mismatch")
        statuses.append(status)
        admission = CheckpointAdmission(reg["prior_tokens"] + charged, reg["config"]["budget"]["project_max_tokens"],
                                        reg["prior_wall_seconds"], reg["config"]["budget"]["project_max_wall_seconds"])
        checkpoints = sorted((folder / "checkpoints").glob("*/snapshot.json"), key=lambda p: int(p.parent.name))
        last, pending_contexts, seen, denied, last_elapsed = None, {}, set(), None, 0
        for path in checkpoints:
            if denied:
                raise ValueError("checkpoint follows denied inference")
            snap = read(path)
            if fingerprint(snap["body"]) != snap["hash"] or digest_file(path.parent / "environment.sqlite") != snap["body"]["database_sha256"]:
                raise ValueError("collection checkpoint integrity mismatch")
            last = snap["body"]["runtime"]
            pending = [i for i, r in enumerate(last["model_requests"]) if r["status"] == "pending" and i not in admission.approved]
            if pending:
                receipt = read(folder / "admissions" / (str(pending[0]) + ".json"))
                decision = admission.inspect(last, receipt["elapsed_seconds"])
                if receipt != {**decision, "checkpoint_index": int(path.parent.name)} or receipt["elapsed_seconds"] < last_elapsed:
                    raise ValueError("collection admission mismatch")
                seen.add(str(pending[0]) + ".json"); last_elapsed = receipt["elapsed_seconds"]
                public_observed = {}
                for event in snap["body"]["audit"]:
                    if not event["error"]:
                        public_observed.update({k: v for k, v in (event["result"] or {}).items() if "." in k})
                if fingerprint(public_observed) != fingerprint(last["state"]):
                    raise ValueError("observations not grounded in preceding public receipts")
                pending_contexts[pending[0]] = {"state": last["state"], "context_hash": last["model_requests"][pending[0]]["context_hash"]}
                if receipt["approved"]: admission.record_approval(receipt)
                else:
                    denied = receipt
                    if receipt != status["denied_before_ack"]: raise ValueError("denied request not reconciled")
            else:
                admission.inspect(last, 0)
        if admission.charged_tokens() != status["charged_tokens"]:
            raise ValueError("collection cost mismatch")
        if seen != {p.name for p in (folder / "admissions").glob("*.json")}:
            raise ValueError("orphan collection admission")
        charged += status["charged_tokens"]
        if not status["completed"]: continue
        row = read(folder / "result.json"); agent = row["agent"]
        initial_snap = read(folder / "initial-snapshot/snapshot.json")
        if (fingerprint(initial_snap["body"]) != initial_snap["hash"] or initial_snap["hash"] != row["snapshot_hash"] or
                digest_file(folder / "initial-snapshot/environment.sqlite") != initial_snap["body"]["database_sha256"] or initial_snap["body"]["audit"]):
            raise ValueError("collection initial snapshot mismatch")
        sources = {k.removeprefix("skillforge/"): v for k, v in reg["sources"].items() if k.startswith("skillforge/")}
        expected_identity = fingerprint({"task": case.public_task(), "catalog": catalog.hash, "model": settings,
            "protocol": reg["protocol"], "sources": sources,
            "limits": [reg["config"]["limits"][k] for k in ("max_steps", "max_search", "max_load", "max_tokens")], "auto_terminate": False})
        if row["case"] != case_data or row["model_identity_hash"] != fingerprint(settings) or agent["identity"] != expected_identity:
            raise ValueError("collection runtime/task/model mismatch")
        if last is None or any(last[k] != agent[k] for k in ("identity", "steps", "budget", "model_requests", "execution_contract", "outcome")):
            raise ValueError("collection final checkpoint mismatch")
        if (agent["metrics"]["llm_calls"] != len(agent["model_requests"]) or agent["metrics"]["tool_calls"] != len(row["tool_audit"]) or
                agent["budget"]["used"]["tokens"] != status["charged_tokens"] or
                sum(r["charged_tokens"] for r in agent["model_requests"]) != status["charged_tokens"]):
            raise ValueError("collection model/tool metrics mismatch")
        for index, step in enumerate(agent["steps"]):
            context = step["context"]
            if (step["messages"][0]["content"] != settings["system_prompt"] or json.loads(step["messages"][1]["content"]) != context or
                    fingerprint(context) != step["selection_trace"]["model_visible_context_hash"] or
                    fingerprint(step["messages"]) != step["selection_trace"]["model_messages_hash"]):
                raise ValueError("collection model message mismatch")
            if (context["observations"] != pending_contexts[index]["state"] or fingerprint(context) != pending_contexts[index]["context_hash"] or
                    {k: context[k] for k in case.public_task()} != case.public_task() or
                    context["policy_view"].get("workflow_goal_hash") != case.goal_hash or
                    context["policy_view"].get("workflow_goal") != GOALS[case.workflow_id].model_dump() or
                    any("selection_trace" in old_step for old_step in context["history"])):
                raise ValueError("collection public context not grounded")
        env = Environment(fixture=case.fixture)
        try:
            if env.snapshot() != row["initial_state"] or private_items(env) != row["initial_items"]:
                raise ValueError("collection initial DB mismatch")
        finally: env.close()
        final_path = checkpoints[-1].parent / "environment.sqlite"
        db = Environment.__new__(Environment); db.order_id = case.parameters["order_id"]
        db.db = sqlite3.connect(final_path.resolve().as_uri() + "?mode=ro", uri=True); db.db.row_factory = sqlite3.Row
        try:
            if db.snapshot() != row["final_state"] or private_items(db) != row["final_items"]:
                raise ValueError("collection final DB mismatch")
        finally: db.close()
        if read(checkpoints[-1])["body"]["audit"] != row["tool_audit"]:
            raise ValueError("collection audit prefix mismatch")
        verdict = verify_workflow(case, row["initial_state"], row["final_state"], row["tool_audit"], agent["outcome"], row["initial_items"], row["final_items"])
        if verdict != row["verification"] or agent["metrics"]["tokens"] != status["charged_tokens"]:
            raise ValueError("collection independent EOC mismatch")
        if row["static_coverage"] != read(folder / "static-coverage.json"):
            raise ValueError("collection static coverage mismatch")
        rows.append(row)
    if (report["n"] != len(rows) or report["planned"] != len(cases) or
            (report["status"] == "complete" and len(rows) != len(cases)) or
            report["tokens"] != sum(r["agent"]["metrics"]["tokens"] for r in rows) or
            report["eoc"] != sum(r["verification"]["task_success"] for r in rows) or
            charged != report["charged_tokens_including_incomplete"] or report["shared_total_charged_tokens"] != reg["prior_tokens"] + charged or
            abs(report["shared_total_wall_seconds"] - reg["prior_wall_seconds"] - report["wall_seconds"]) > 1e-6):
        raise ValueError("collection aggregate accounting mismatch")
    if report["case_statuses"] != statuses:
        raise ValueError("collection aggregate statuses mismatch")
    for field, verdict_field in {
        "attempted_policy_violations": "attempted_policy_violation",
        "actual_policy_violations": "actual_policy_violation",
        "actual_workflow_violations": "actual_workflow_violation",
    }.items():
        if report[field] != sum(row["verification"][verdict_field] for row in rows):
            raise ValueError("collection aggregate safety mismatch")
    receipt = {"passed": True, "run_completed": report["status"] == "complete", "n": len(rows), "charged_tokens": charged,
               "report_sha256": digest_file(root / "report.json"), "protocol_hash": reg["protocol_hash"],
               "generator_sha256": digest_file(__file__), "scope": "sources, exact messages, checkpoints/SQLite, request admission, independent workflow EOC and charges"}
    publish(root / "evidence-audits" / (digest_file(__file__) + ".json"), receipt)
    return receipt


def mine(root):
    root = Path(root)
    receipt = audit(root)
    rows = [read(path) for path in sorted(root.glob("*/result.json"))]
    screen = read(root / "registration.json")["config"]["opportunity_screen"]
    if screen["skill_search_load_execute_stop_decisions"] != 4:
        raise ValueError("unsupported Skill cost screen")
    result = mine_opportunities(rows, read(root / "model-identity.json"), min_sources=screen["min_sources"],
                                min_model_call_saving=screen["min_model_call_saving"])
    result.update(collection_audit=receipt, generator_sha256=digest_file(ROOT / "skillforge/skill_evolution/experience.py"))
    publish(root / "opportunity-screens" / (result["generator_sha256"] + ".json"), result)
    return {"status": result["status"], "trajectories": len(result["normalized"]),
            "opportunities": sum(r["status"] == "OPPORTUNITY" for r in result["records"])}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["collect", "audit", "mine"])
    parser.add_argument("--config", default="configs/skill-evolution-v1.2.learn-dev.json")
    parser.add_argument("--output"); parser.add_argument("--run")
    args = parser.parse_args()
    result = collect(read(args.config), args.output) if args.command == "collect" else audit(args.run) if args.command == "audit" else mine(args.run)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    raise SystemExit(0 if result.get("passed", result.get("status") != "blocked_or_incomplete") else 1)
