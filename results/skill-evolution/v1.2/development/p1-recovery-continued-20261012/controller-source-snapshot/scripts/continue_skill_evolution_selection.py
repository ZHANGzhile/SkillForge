"""Continue never-started arms, retaining the exact registered serving identity.

The old partial report remains immutable. A new evidence tree binds every
inherited byte and charges only incremental work, without rerunning old arms.
This intentionally rejects mid-arm recovery and unresolved writes/reservations.
"""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import shutil
import time

from scripts.evolution_budget import CheckpointAdmission
from scripts.evolution_forks import check_pair, fork_starts
from scripts.evolution_opportunities import selection_funnel
from scripts.run_skill_evolution import ROOT, ModelSession, digest_file, prior_cost
from scripts.run_skill_evolution_selection import audit, read
from skillforge.environment import ToolError
from skillforge.evolution_common.snapshot import restore_snapshot, save_snapshot
from skillforge.evolution_registry import immutable_json
from skillforge.evolution_schemas import fingerprint
from skillforge.schemas import Task
from skillforge.skill_evolution.catalog import Catalog
from skillforge.skill_evolution.runtime import PROTOCOL, runtime_sources
from skillforge.verifier import verify


def publish(path, value):
    path = Path(path).resolve()
    immutable_json(Path("\\\\?\\" + str(path)) if os.name == "nt" else path, value)


def validate_parent(parent):
    reg, report = read(parent / "registration.json"), read(parent / "report.json")
    if report["status"] != "blocked_or_incomplete" or report.get("unfinished_task_budget"):
        raise ValueError("only a closed partial run with no pending arm can continue")
    receipt = audit(parent)
    if not receipt["missing_arms"]:
        raise ValueError("no missing arms")
    expected = {k.removeprefix("skillforge/"): v for k, v in reg["sources"].items()
                if k.startswith("skillforge/") and k != "skillforge/verifier.py"}
    if PROTOCOL != reg["protocol"] or runtime_sources() != expected:
        raise ValueError("registered serving sources differ; cannot continue old protocol")
    if digest_file(ROOT / "skillforge/verifier.py") != reg["sources"]["skillforge/verifier.py"]:
        raise ValueError("registered verifier differs")
    for missing in receipt["missing_arms"]:
        if (parent / missing["task_id"] / missing["arm"]).exists():
            raise ValueError("missing arm already started; reconciliation required")
    prior = prior_cost(reg["config"])
    if prior != report["shared_prior_cost"] or sum(r["tokens"] for r in prior) + report["charged_tokens_including_incomplete"] != report["shared_total_charged_tokens"]:
        raise ValueError("parent cost lineage mismatch")
    if abs(sum(r["wall_seconds"] for r in prior) + report["wall_seconds"] - report["shared_total_wall_seconds"]) > 1e-6:
        raise ValueError("parent wall cost lineage mismatch")
    return reg, report, receipt


def continue_run(parent, output):
    from scripts.execution_aware_gpu_lease import GPUServiceLease
    started = time.perf_counter()
    parent, output = Path(parent).resolve(), Path(output).resolve()
    reg, previous, parent_audit = validate_parent(parent)
    output.mkdir(parents=True, exist_ok=False)
    excluded = {"report.json", "evidence-audits", "agent.stderr.log"}
    inherited = {}
    for path in parent.rglob("*"):
        relative = path.relative_to(parent)
        if path.is_file() and relative.parts[0] not in excluded:
            target = output / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            inherited[relative.as_posix()] = digest_file(path)
    shutil.copyfile(parent / "report.json", output / "parent-report.json")
    controller_sources = {name: digest_file(ROOT / name) for name in
                          ("scripts/evolution_budget.py", "scripts/continue_skill_evolution_selection.py",
                           "scripts/run_skill_evolution.py", "scripts/run_skill_evolution_selection.py")}
    for name in controller_sources:
        target = output / "controller-source-snapshot" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    manifest = {"schema": "availability-fork-continuation-v1", "parent": str(parent.relative_to(ROOT)),
                "parent_report_sha256": digest_file(parent / "report.json"), "protocol_hash": reg["protocol_hash"],
                "inherited_files": inherited, "missing_arms": parent_audit["missing_arms"],
                "controller_sources": controller_sources,
                "prior_tokens": previous["shared_total_charged_tokens"],
                "prior_wall_seconds": previous["shared_total_wall_seconds"],
                "scope": "never-started arms only; exact serving sources/prompt/model/limits; checkpoint ACK admission"}
    manifest["continuation_hash"] = fingerprint(manifest)
    publish(output / "continuation.json", manifest)
    catalog = Catalog.load(output / "catalog.json")
    tasks = {t["task_id"]: Task.model_validate(t) for t in read(output / "private-dev-tasks.json")}
    rows, failure, unfinished, incremental_tokens, denied = [], None, None, 0, None
    config = reg["config"]
    admission = None
    try:
        with GPUServiceLease(), ExitStack() as cleanup:
            remaining = config["smoke"]["max_wall_seconds"] - manifest["prior_wall_seconds"] - (time.perf_counter() - started) - 10
            if remaining <= 0:
                raise TimeoutError("shared developmental wall budget exhausted before loading")
            session = ModelSession(config, output, init_timeout=remaining)
            cleanup.callback(session.close)
            if session.settings != read(output / "model-identity.json"):
                raise ValueError("registered model identity differs")
            for missing in manifest["missing_arms"]:
                task, arm = tasks[missing["task_id"]], missing["arm"]
                folder = output / task.task_id
                snapshot = read(folder / "initial-snapshot/snapshot.json")
                refs = {e["skill_id"]: {"revision": e["revision"], "content_hash": e["revision"]}
                        for e in catalog.entries() if e["contract"]["status"] == "VERIFIED"}
                starts = fork_starts(folder / "initial-snapshot", catalog, refs)
                arm_dir = folder / arm
                env, _, rng = restore_snapshot(folder / "initial-snapshot", arm_dir / "live.sqlite", snapshot["body"]["runtime"]["identity"])
                prefix, initial, checkpoint_index = len(env.audit), env.snapshot(), 0
                admission = CheckpointAdmission(manifest["prior_tokens"] + incremental_tokens,
                                                config["smoke"]["max_model_tokens"], manifest["prior_wall_seconds"],
                                                config["smoke"]["max_wall_seconds"])
                public = {k: getattr(task, k) for k in ("task_id", "family", "request", "parameters")}
                session.send({"type": "run", "task": public, "catalog": catalog.entries(),
                              "limits": config["limits"], "public_start": starts[arm]})
                try:
                    while True:
                        remaining = admission.remaining(time.perf_counter() - started)
                        if remaining <= 0:
                            raise TimeoutError("shared developmental wall budget exhausted")
                        msg = session.receive(min(120, remaining))
                        if msg["type"] == "completed":
                            break
                        if msg["type"] == "checkpoint":
                            value = msg["value"]
                            unfinished = value["budget"]
                            save_snapshot(arm_dir / "checkpoints" / str(checkpoint_index), env, value, rng)
                            decision = admission.inspect(value, time.perf_counter() - started)
                            if decision is not None:
                                decision["checkpoint_index"] = checkpoint_index
                                publish(arm_dir / "admissions" / (str(decision["request_index"]) + ".json"), decision)
                                if not decision["approved"]:
                                    denied = decision
                                    raise ValueError("request denied before ACK: " + decision["reason"])
                                admission.record_approval(decision)
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
                    if admission.charged_tokens() != agent["metrics"]["tokens"]:
                        raise ValueError("admission/final charge mismatch")
                    verdict = verify(task, initial, env.snapshot(), env.audit, agent["outcome"])
                    row = {"task_id": task.task_id, "arm": arm, "experiment_split": "dev", "public_start": starts[arm],
                           "initial_state_hash": fingerprint(initial), "snapshot_hash": snapshot["hash"],
                           "task_hash": fingerprint(task.model_dump()), "prefix_audit_count": prefix,
                           "agent": agent, "verification": verdict, "tool_audit": env.audit,
                           "selection_funnel": selection_funnel(agent, read(folder / "opportunities.json"), verdict)}
                    publish(arm_dir / "result.json", row)
                    rows.append(row)
                    incremental_tokens += agent["metrics"]["tokens"]
                    unfinished, admission = None, None
                    print(json.dumps({"task": task.task_id, "arm": arm, "eoc": verdict["task_success"],
                                      "tokens": agent["metrics"]["tokens"]}), flush=True)
                finally:
                    env.close()
                if all((folder / a / "result.json").exists() for a in ("provided", "withheld")):
                    arms = {a: read(folder / a / "result.json")["agent"] for a in ("provided", "withheld")}
                    # The inherited arm ran first. Execution order is factual.
                    publish(folder / "pair-check.json", {"task_id": task.task_id,
                            "order": ["withheld" if arm == "provided" else "provided", arm],
                            **check_pair(arms["provided"], arms["withheld"])})
    except Exception as exc:
        failure = type(exc).__name__ + ": " + str(exc)
    incremental_tokens += admission.charged_tokens() if admission is not None else 0
    all_rows = [read(p) for p in output.glob("*/*/result.json")]
    pairs = len(list(output.glob("*/pair-check.json")))
    wall = time.perf_counter() - started
    complete = len(all_rows) == previous["planned"] and not failure
    report = {**previous, "status": "complete" if complete else "blocked_or_incomplete", "failure": failure,
              "n": len(all_rows), "pairs": pairs,
              "eoc": sum(r["verification"]["task_success"] for r in all_rows),
              "actual_violations": sum(r["verification"]["actual_policy_violation"] for r in all_rows),
              "attempted_violations": sum(r["verification"]["attempted_policy_violation"] for r in all_rows),
              "tokens": sum(r["agent"]["metrics"]["tokens"] for r in all_rows),
              "charged_tokens_including_incomplete": incremental_tokens, "wall_seconds": wall,
              "incremental_completed_tokens": sum(r["agent"]["metrics"]["tokens"] for r in rows),
              "inherited_completed_tokens": previous["tokens"], "incremental_cases": len(rows),
              "shared_total_charged_tokens": manifest["prior_tokens"] + incremental_tokens,
              "shared_total_wall_seconds": manifest["prior_wall_seconds"] + wall,
              "unfinished_task_budget": unfinished, "denied_before_ack": denied,
              "shared_prior_cost": [*previous["shared_prior_cost"],
                                    {"path": manifest["parent"], "report_sha256": manifest["parent_report_sha256"],
                                     "status": previous["status"], "tokens": previous["charged_tokens_including_incomplete"],
                                     "wall_seconds": previous["wall_seconds"]}],
              "continuation_hash": manifest["continuation_hash"], "engineering_passed": complete}
    publish(output / "report.json", report)
    return report


def audit_continuation(root):
    root = Path(root)
    manifest, report, reg = read(root / "continuation.json"), read(root / "report.json"), read(root / "registration.json")
    if fingerprint({k: v for k, v in manifest.items() if k != "continuation_hash"}) != manifest["continuation_hash"]:
        raise ValueError("continuation manifest hash mismatch")
    parent = ROOT / manifest["parent"]
    if digest_file(parent / "report.json") != manifest["parent_report_sha256"] or digest_file(root / "parent-report.json") != manifest["parent_report_sha256"]:
        raise ValueError("parent report mismatch")
    for name, expected in manifest["inherited_files"].items():
        if digest_file(root / name) != expected or digest_file(parent / name) != expected:
            raise ValueError("inherited evidence changed")
    for name, expected in manifest["controller_sources"].items():
        if digest_file(root / "controller-source-snapshot" / name) != expected:
            raise ValueError("controller source snapshot changed")
    if manifest["protocol_hash"] != reg["protocol_hash"] or report["continuation_hash"] != manifest["continuation_hash"]:
        raise ValueError("continuation protocol mismatch")
    prior = read(root / "parent-report.json")
    if manifest["prior_tokens"] != prior["shared_total_charged_tokens"] or manifest["prior_wall_seconds"] != prior["shared_total_wall_seconds"]:
        raise ValueError("continuation prior cost mismatch")
    added, added_tokens = 0, 0
    for arm in manifest["missing_arms"]:
        folder = root / arm["task_id"] / arm["arm"]
        result_path = folder / "result.json"
        if not result_path.exists():
            continue
        row = read(result_path)
        admission = CheckpointAdmission(manifest["prior_tokens"] + added_tokens, reg["config"]["smoke"]["max_model_tokens"],
                                       manifest["prior_wall_seconds"], reg["config"]["smoke"]["max_wall_seconds"])
        for checkpoint in sorted((folder / "checkpoints").glob("*/snapshot.json"), key=lambda p: int(p.parent.name)):
            value = read(checkpoint)["body"]["runtime"]
            pending = [i for i, r in enumerate(value["model_requests"]) if r["status"] == "pending" and i not in admission.approved]
            if pending:
                receipt = read(folder / "admissions" / (str(pending[0]) + ".json"))
                expected = admission.inspect(value, receipt["elapsed_seconds"])
                if expected is None or receipt != {**expected, "checkpoint_index": int(checkpoint.parent.name)} or not receipt["approved"]:
                    raise ValueError("invalid per-request budget admission")
                admission.record_approval(receipt)
            else:
                admission.inspect(value, 0)
        if admission.charged_tokens() != row["agent"]["metrics"]["tokens"]:
            raise ValueError("continuation charge mismatch")
        added += 1; added_tokens += admission.charged_tokens()
    if (report["incremental_cases"] != added or report["incremental_completed_tokens"] != added_tokens or
            report["inherited_completed_tokens"] != prior["tokens"] or
            report["tokens"] != prior["tokens"] + added_tokens or
            report["shared_total_charged_tokens"] != manifest["prior_tokens"] + report["charged_tokens_including_incomplete"] or
            abs(report["shared_total_wall_seconds"] - manifest["prior_wall_seconds"] - report["wall_seconds"]) > 1e-6 or
            (report["status"] == "complete" and report["charged_tokens_including_incomplete"] != added_tokens)):
        raise ValueError("continuation accounting mismatch")
    receipt = audit(root)
    receipt = {**receipt, "continuation_hash": manifest["continuation_hash"],
               "incremental_charged_tokens": report["charged_tokens_including_incomplete"],
               "generator_sha256": digest_file(__file__)}
    publish(root / "continuation-audits" / (digest_file(__file__) + ".json"), receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["continue", "audit"])
    parser.add_argument("--parent"); parser.add_argument("--output"); parser.add_argument("--run")
    args = parser.parse_args()
    result = continue_run(args.parent, args.output) if args.command == "continue" else audit_continuation(args.run)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    raise SystemExit(0 if result.get("passed", result.get("status") == "complete") else 1)
