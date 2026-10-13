"""Fixed-main-v3 Stage 2 interface cost smoke and real daily receipt adapter.

No Boundary learning, validation, activation or research efficacy claim here.
Only H0 bindings; independent legacy business EOC remains controller-private.
"""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time

from scripts.run_skill_evolution import ROOT, digest_file
from scripts.skill_evolution_release import ADAPTER, ADAPTER_SHA, fixed_model, hashed, relative
from scripts.continue_skill_evolution_selection import publish
from scripts.evolution_budget import CheckpointAdmission
from skillforge.skill_evolution.agent_evidence import read
from skillforge.skill_evolution.catalog import Catalog
from skillforge.boundary_runtime.catalog import BoundaryCatalog, h0_bindings
from skillforge.boundary_runtime.runtime import PROTOCOL, runtime_sources
from skillforge.boundary_evolution.evidence import PublicReceiptAdapter
from skillforge.boundary_evolution.trigger import DriftController, TriggerPolicy
from skillforge.evolution_common.artifacts import SplitLedger
from skillforge.evolution_common.snapshot import save_snapshot
from skillforge.evolution_schemas import fingerprint
from skillforge.schemas import Task, ExpectedOutcome
from skillforge.environment import Environment, ToolError
from skillforge.verifier import verify


class BoundarySession:
    def __init__(self, folder):
        self.log = (folder / "agent.stderr.log").open("w", encoding="utf-8")
        env = {key: value for key, value in os.environ.items() if not key.startswith("SKILLFORGE_")}
        env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        self.process = subprocess.Popen([str(ROOT / ".venv-train/Scripts/python.exe"), "-m", "skillforge.boundary_runtime.worker"],
            cwd=ROOT, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log,
            text=True, encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW)
        self.events = queue.Queue()
        def reader():
            for line in self.process.stdout: self.events.put(line)
            self.events.put(None)
        self.reader = threading.Thread(target=reader, daemon=True); self.reader.start()
        try:
            self.send({"config": str(ROOT / "configs/training.recovery-v1.json"), "adapter": str(ROOT / ADAPTER),
                "adapter_sha256": ADAPTER_SHA, "output": str(folder / "worker-public")})
            ready = self.receive(240)
            if ready["type"] != "ready": raise ValueError("fixed model not ready")
            self.settings = ready["settings"]; fixed_model(self.settings)
            if self.settings["stage2_runtime_sources_hash"] != fingerprint(runtime_sources()):
                raise ValueError("worker/runtime source identity mismatch")
        except BaseException: self.close(); raise

    def send(self, value):
        self.process.stdin.write(json.dumps(value, ensure_ascii=False) + "\n"); self.process.stdin.flush()

    def receive(self, timeout):
        try: line = self.events.get(timeout=timeout)
        except queue.Empty as exc: raise TimeoutError("model RPC timeout; retain approved unknown reservation") from exc
        if line is None: raise RuntimeError("model worker exited; inspect agent.stderr.log")
        return json.loads(line)

    def close(self):
        if self.log.closed: return
        if self.process.poll() is None:
            try: self.send({"type": "close"}); self.process.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired): self.process.kill(); self.process.wait(timeout=10)
        self.process.stdin.close(); self.process.stdout.close(); self.log.close(); self.reader.join(timeout=2)


def cases():
    rows = []
    for index, family in enumerate(["refund", "refund", "refund", "cancel_order", "modify_address", "refund", "refund"]):
        ident = f"p6-real-h0-20261012-{index}"
        oid, cid = "O-" + ident, "C-" + ident
        params = {"order_id": oid}
        if family == "refund": params["amount"] = 100
        if family == "modify_address": params["new_address"] = "Delivery lane 204"
        high, fault = index == 5, index == 6
        state = {"payment.refunded_amount": 100} if family == "refund" else {"order.status": "CANCELLED"} if family == "cancel_order" else {"order.shipping_address": params["new_address"]}
        expected = ExpectedOutcome(allowed_outcomes=["escalated"] if high else ["completed"],
            expected_state={} if high else state, unchanged_fields=["payment.refunded_amount"] if high else [])
        task = Task(task_id=ident, family=family, request=f"Please {'refund 100 minor units for' if family == 'refund' else 'cancel' if family == 'cancel_order' else 'change the shipping address to Delivery lane 204 for'} my order {oid}.",
            customer_id=cid, parameters=params, split="train", template_id="p6-real-h0-cost-dev", seed=2026101260 + index,
            fixture={"order_id": oid, "customer_id": cid, "risk": "HIGH" if high else "LOW"}, expected=expected,
            dataset_id="p6-real-h0-cost-dev", instance_id=ident)
        rows.append({"task": task.model_dump(), "source_group": ident,
                     "faults": {"get_customer": ["timeout"]} if fault else {},
                     "stage": "fault-only" if fault else "immutable-risk" if high else "no-change"})
    return rows


def run(stage1, output):
    from scripts.execution_aware_gpu_lease import GPUServiceLease
    import random
    stage1, output = Path(stage1).resolve(), Path(output).resolve()
    if output.exists(): raise ValueError("fresh real smoke root required")
    freeze, prior = read(stage1 / "stage1-freeze.json"), read(stage1 / "report.json")
    if freeze["report_hash"] != prior["hash"]: raise ValueError("Stage 1 prior report changed")
    for name, sha in freeze["implementation_sources"].items():
        if digest_file(ROOT / name) != sha: raise ValueError("frozen Stage 1 source changed")
    base = Catalog.load(stage1 / "stage1-catalog.json")
    catalog = BoundaryCatalog(base.entries(), h0_bindings(base))
    planned = cases()
    sources = {**freeze["implementation_sources"], **{"skillforge/" + key: value for key, value in runtime_sources().items()}}
    sources.update({relative(path): digest_file(path) for path in [Path(__file__),
        *ROOT.glob("skillforge/boundary_evolution/*.py"), ROOT / "scripts/evolution_budget.py",
        ROOT / "scripts/execution_aware_gpu_lease.py", ROOT / "skillforge/verifier.py"]})
    protocol = hashed({"schema": "stage2-real-h0-interface-smoke-v1", "stage1_freeze_hash": freeze["hash"],
        "prior_report_hash": prior["hash"], "prior_tokens": prior["shared_total_tokens"],
        "prior_wall_seconds": prior["shared_total_wall_seconds"], "phase_tokens": 250000, "phase_wall_seconds": 900,
        "cases": planned, "catalog_hash": catalog.hash, "bundle_hash": catalog.bundle_hash,
        "boundaries": catalog.boundaries(), "sources": sources, "runtime_protocol": PROTOCOL,
        "limits": {"max_steps": 12, "max_search": 3, "max_load": 3, "max_tokens": 131072},
        "trigger_policy": TriggerPolicy().model_dump(), "new_training": False, "activated": False,
        "scope": "real fixed-model dev cost/interface and no-change/fault stream only; H0 only, no boundary adaptation efficacy"})
    publish(output / "protocol.json", protocol)
    publish(ROOT / "results/skill-evolution/v1.2/stage2-development-budget-ledger" / (fingerprint(relative(output)) + ".json"),
        {"phase_id": relative(output), "protocol_hash": protocol["hash"], "prior_report_hash": prior["hash"],
         "prior_tokens": protocol["prior_tokens"], "phase_tokens": 250000, "phase_wall_seconds": 900})
    ledger = SplitLedger(ROOT / "results/skill-evolution/v1.2/source-ledger")
    for planned_case in planned:
        task = planned_case["task"]
        ledger.claim(planned_case["source_group"], "dev", related_groups=[task["task_id"], task["parameters"]["order_id"], task["customer_id"]])
    for name in sources:
        target = output / "source-snapshot" / name; target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(ROOT / name, target)
    base.save(output / "catalog.json")
    started, tokens, rows, statuses, failure, members = time.perf_counter(), 0, [], [], None, {}
    controller = DriftController(protocol["trigger_policy"])
    session = None
    try:
        with GPUServiceLease(), ExitStack() as cleanup:
            session = BoundarySession(output); cleanup.callback(session.close)
            publish(output / "model-identity.json", session.settings)
            for index, planned_case in enumerate(planned):
                task = Task.model_validate(planned_case["task"])
                public_task = {key: getattr(task, key) for key in ("task_id", "family", "request", "parameters")}
                folder = output / str(index); folder.mkdir()
                env = Environment(str(folder / "live.sqlite"), fixture=task.fixture, faults=planned_case["faults"])
                initial = env.snapshot()
                publish(folder / "initial-state.json", initial)
                admission = CheckpointAdmission(protocol["prior_tokens"] + tokens,
                    protocol["prior_tokens"] + protocol["phase_tokens"], protocol["prior_wall_seconds"],
                    protocol["prior_wall_seconds"] + protocol["phase_wall_seconds"])
                row, error, checkpoint_index = None, None, 0
                try:
                    session.send({"type": "run", "task": public_task, "catalog": catalog.entries(),
                                  "boundaries": catalog.boundaries(), "limits": protocol["limits"]})
                    while True:
                        remaining = admission.remaining(time.perf_counter() - started)
                        if remaining <= 0: raise TimeoutError("registered Stage 2 dev wall budget exhausted")
                        msg = session.receive(min(120, remaining))
                        if msg["type"] == "completed":
                            agent = msg["result"]
                            verdict = verify(task, initial, env.snapshot(), env.audit, agent["outcome"])
                            if admission.charged_tokens() != agent["metrics"]["tokens"]: raise ValueError("inference fee settlement mismatch")
                            row = {"task": task.model_dump(), "agent": agent, "initial_state": initial,
                                "final_state": env.snapshot(), "tool_audit": env.audit, "verification": verdict,
                                "model_identity_hash": fingerprint(session.settings)}
                            publish(folder / "result.json", row); break
                        if msg["type"] == "checkpoint":
                            value = msg["value"]
                            save_snapshot(folder / "checkpoints" / str(checkpoint_index), env, value, random.Random(task.seed))
                            decision = admission.inspect(value, time.perf_counter() - started)
                            if decision is not None:
                                decision["checkpoint_index"] = checkpoint_index
                                publish(folder / "admissions" / (str(decision["request_index"]) + ".json"), decision)
                                if not decision["approved"]: raise ValueError("registered inference budget denied")
                                admission.record_approval(decision)
                            checkpoint_index += 1; session.send({"type": "checkpoint_saved"})
                        elif msg["type"] == "tool":
                            try:
                                value = env.call(msg["name"], msg["arguments"], task.customer_id, msg["key"])
                                session.send({"type": "tool_result", "result": value})
                            except ToolError as exc: session.send({"type": "tool_result", "error": exc.code})
                            env.audit[-1]["decision_origin"] = msg["source"]
                        else: raise ValueError("unexpected model RPC")
                except Exception as exc: error = type(exc).__name__ + ": " + str(exc)
                finally:
                    charged = admission.charged_tokens(); tokens += charged
                    status = {"task_id": task.task_id, "completed": row is not None, "charged_tokens": charged, "failure": error,
                        "charged_model_requests": len(admission.approved),
                        "approved_unknown_requests": sum(r["status"] == "pending" and i in admission.approved
                            for i, r in enumerate((admission.last or {}).get("model_requests", [])))}
                    publish(folder / "collection-status.json", status); statuses.append(status); env.close()
                if row is None: failure = error; break
                entry = next(e for e in catalog.entries() if e["contract"]["family"] == task.family)
                raw = {"task_id": task.task_id, "trajectory_id": fingerprint([task.task_id, agent["identity"]]),
                    "tool_audit": row["tool_audit"], "execution_contract": agent["execution_contract"]}
                publish(folder / "public-receipt-source.json", raw)
                members[task.task_id] = {"task_hash": fingerprint(public_task), "raw_hash": fingerprint(raw),
                    "skill_id": entry["skill_id"], "parent_revision": entry["revision"], "source_group": planned_case["source_group"],
                    "probe_origin": "daily", "sandbox_id": None, "evidence_origin": "model_tool"}
                interaction = PublicReceiptAdapter(members, base).export(raw, public_task)
                decision = controller.observe(interaction)
                publish(folder / "public-interaction.json", interaction.model_dump(mode="json"))
                publish(folder / "trigger-checkpoint.json", controller.checkpoint())
                rows.append({"task_id": task.task_id, "stage": planned_case["stage"], "eoc": verdict["task_success"],
                    "trigger_state": decision["state"], "feedback": interaction.feedback,
                    "tokens": charged, "model_calls": agent["metrics"]["llm_calls"],
                    "autonomous_eoc": verdict["task_success"] and not agent["interventions"]["runtime_intervention_count"],
                    "runtime_assisted_eoc": verdict["task_success"] and bool(agent["interventions"]["runtime_intervention_count"]),
                    "attempted_violations": verdict["attempted_policy_violation"], "actual_violations": verdict["actual_policy_violation"]})
                print(json.dumps(rows[-1]), flush=True)
    except Exception as exc: failure = type(exc).__name__ + ": " + str(exc)
    publish(output / "source-receipts.json", members)
    report = hashed({"schema": "stage2-real-h0-interface-smoke-results-v1", "protocol_hash": protocol["hash"],
        "complete": len(rows) == len(planned), "failure": failure, "rows": rows, "statuses": statuses,
        "charged_tokens": tokens, "shared_total_tokens": protocol["prior_tokens"] + tokens,
        "collection_wall_seconds": time.perf_counter() - started, "new_training": False, "activated": False,
        "charged_model_requests": sum(status["charged_model_requests"] for status in statuses),
        "approved_unknown_requests": sum(status["approved_unknown_requests"] for status in statuses),
        "new_model_calls": sum(row["model_calls"] for row in rows), "gpu_hours": "UNMEASURED", "scope": protocol["scope"]})
    publish(output / "report.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--stage1", required=True); parser.add_argument("--output", required=True)
    args = parser.parse_args(); result = run(args.stage1, args.output)
    print(json.dumps({key: result[key] for key in ("complete", "failure", "charged_tokens", "shared_total_tokens")}))
