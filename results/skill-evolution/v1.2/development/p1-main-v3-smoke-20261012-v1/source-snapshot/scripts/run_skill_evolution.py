"""Two-phase entrypoint. P0 preflight and real-model P1 smoke; no mock fallback."""
import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import queue
import random
import shutil
import subprocess
import threading
import time
import uuid

from skillforge.evolution_common.artifacts import SplitLedger, record
from skillforge.evolution_common.snapshot import save_snapshot
from skillforge.evolution_registry import immutable_json
from skillforge.evolution_schemas import fingerprint
from skillforge.skill_evolution.catalog import Catalog, revision
from skillforge.skill_evolution.runtime import PROTOCOL, SYSTEM_PROMPT, runtime_sources


ROOT = Path(__file__).resolve().parents[1]


def digest_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def preflight(config, output, tests=True):
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    sources = {}
    for name in ("formal-A-v2", "formal-B-v1"):
        p = ROOT / "results/active-evolution/v1.1" / name / "protocol.json"
        value = json.loads(p.read_text(encoding="utf-8"))
        expected = value["protocol"]["sources"]
        mismatches = [f for f, h in expected.items() if not (ROOT / f).is_file() or digest_file(ROOT / f) != h]
        sources[name] = {"protocol_hash": value["protocol_hash"], "count": len(expected), "mismatches": mismatches}
    old = json.loads((ROOT / "results/active-evolution/v1/preparation/baseline.json").read_text(encoding="utf-8"))
    differences = []
    for p, expected in old["files"].items():
        actual = digest_file(ROOT / p) if (ROOT / p).is_file() else None
        if actual != expected:
            published = subprocess.check_output(["git", "show", config["baseline"] + ":" + p], cwd=ROOT)
            differences.append({"path": p, "historical_sha256": expected, "actual_sha256": actual,
                                "matches_approved_publication": hashlib.sha256(published).hexdigest() == actual})
    historical_ok = all(d["path"] in {"README.md", "README.zh-CN.md"} and d["matches_approved_publication"] for d in differences)
    pytest_result = {"status": "not_requested"}
    if tests:
        copied = ROOT / ".runtime" / ("skill-evolution-preflight-" + uuid.uuid4().hex)
        copied.mkdir(parents=True)
        for name in ("skillforge", "scripts", "tests", "configs"):
            shutil.copytree(ROOT / name, copied / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "model.local.json", "deployment.local.json"))
        shutil.copy2(ROOT / "pyproject.toml", copied / "pyproject.toml")
        env = {k: v for k, v in os.environ.items() if not k.startswith("SKILLFORGE_")}
        env.update(PYTHONPATH=str(copied), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        result = subprocess.run([str(ROOT / ".venv/Scripts/python.exe") if os.name == "nt" else "python", "-m", "pytest", "-q"],
                                cwd=copied, env=env, capture_output=True, text=True, encoding="utf-8")
        (output / "pytest.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        pytest_result = {"status": "passed" if result.returncode == 0 else "failed", "returncode": result.returncode,
                         "source_copy": str(copied), "log_sha256": digest_file(output / "pytest.log")}
    assets = {"adapter": digest_file(ROOT / config["adapter"] / "adapter_model.safetensors"),
              "base_config_present": (ROOT / config["training_config"]).exists()}
    report = {"schema": "two-phase-preflight-v1", "head": head, "requested_baseline": config["baseline"],
              "same_head": head == config["baseline"], "frozen_sources": sources,
              "historical_files": len(old["files"]), "historical_differences": differences,
              "historical_evidence_passed": historical_ok, "pytest": pytest_result, "assets": assets,
              "runtime_sources": runtime_sources(), "prompt_hash": fingerprint(SYSTEM_PROMPT),
              "scope": "new engineering verification; historical README differences explicitly bound to published baseline"}
    report["passed"] = historical_ok and all(not s["mismatches"] for s in sources.values()) and assets["adapter"] == config["adapter_sha256"] and pytest_result["status"] != "failed"
    immutable_json(output / "preflight.json", report)
    return report


def static_catalog(config):
    frozen = json.loads((ROOT / config["static_bundle"]).read_text(encoding="utf-8"))
    metadata = {
        "modify_address": ("Change shipping address", "modify update shipping delivery address of unfulfilled order"),
        "cancel_order": ("Cancel order", "cancel cancellation stop fulfillment of unfulfilled order"),
        "refund": ("Refund captured payment", "refund return captured payment money amount with read-back verification"),
    }
    entries = []
    for skill in frozen["skills"]:
        name, description = metadata[skill["family"]]
        entries.append(revision(skill, name=name, description=description,
                                support_domain={"scope": "historical static library; original policy", "policy_version": skill["policy_version"]}))
    return Catalog(entries)


def smoke_tasks(config):
    """Fresh dev entities. Independent EOC specification precedes Agent execution."""
    from skillforge.schemas import Task, ExpectedOutcome
    rows = []
    for i, case in enumerate(config["smoke"]["cases"]):
        family = "cancel_order" if case.startswith("cancel") else "modify_address" if case.startswith("address") else "refund"
        oid, cid = f"DEV12-{config['smoke']['seed']}-{i}", f"CDEV12-{i}"
        params = {"order_id": oid}
        if family == "refund": params["amount"] = 2300
        if family == "modify_address": params["new_address"] = f"{110+i} Orchard Avenue, Paris"
        fixture = {"order_id": oid, "customer_id": cid}
        expected_outcome = "completed"
        if case == "refund_failed": fixture["payment"] = "FAILED"; expected_outcome = "refused"
        if case == "address_shipped": fixture["shipment"] = "SHIPPED"; expected_outcome = "refused"
        if case == "refund_high": fixture["risk"] = "HIGH"; expected_outcome = "escalated"
        state = ({"order.status": "CANCELLED"} if family == "cancel_order" else
                 {"order.shipping_address": params["new_address"]} if family == "modify_address" else {"payment.refunded_amount": 2300}) if expected_outcome == "completed" else {}
        request = {"cancel_order": f"Please cancel order {oid} if permitted.",
                   "modify_address": f"Change order {oid} delivery address to {params.get('new_address')} if permitted.",
                   "refund": f"Refund exactly 2300 minor currency units for order {oid} if permitted."}[family]
        rows.append(Task(task_id=f"p1-{case}-{config['smoke']['seed']}", family=family, request=request,
                         customer_id=cid, parameters=params, split="train", template_id="p1-dev-"+case,
                         seed=config["smoke"]["seed"], fixture=fixture, dataset_id="skill-evolution-v1.2-dev",
                         expected=ExpectedOutcome(allowed_outcomes=[expected_outcome], expected_state=state)))
    return rows


class ModelSession:
    def __init__(self, config, output):
        self.log = (output / "agent.stderr.log").open("w", encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if not k.startswith("SKILLFORGE_")}
        env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        python = ROOT / (".venv-train/Scripts/python.exe" if os.name == "nt" else ".venv-train/bin/python")
        self.process = subprocess.Popen([str(python), "-m", "skillforge.skill_evolution.worker"], cwd=ROOT,
                                        env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log,
                                        text=True, encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        self.events = queue.Queue()
        def reader():
            for line in self.process.stdout: self.events.put(line)
            self.events.put(None)
        self.reader = threading.Thread(target=reader, daemon=True)
        self.reader.start()
        try:
            self.send({"config": str(ROOT / config["training_config"]), "adapter": str(ROOT / config["adapter"]),
                       "adapter_sha256": config["adapter_sha256"], "output": str(output.resolve())})
            ready = self.receive(240)
            if ready["type"] != "ready": raise RuntimeError("model initialization failed")
            self.settings = ready["settings"]
        except BaseException:
            self.close()
            raise

    def send(self, packet):
        self.process.stdin.write(json.dumps(packet, ensure_ascii=False)+"\n")
        self.process.stdin.flush()

    def receive(self, timeout=120):
        try: line = self.events.get(timeout=timeout)
        except queue.Empty as exc: raise TimeoutError("Agent RPC timed out; preserve pending reservation") from exc
        if line is None: raise RuntimeError("model worker exited; inspect agent.stderr.log")
        return json.loads(line)

    def close(self):
        if self.log.closed:
            return
        if self.process.poll() is None:
            try: self.send({"type": "close"}); self.process.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired): self.process.kill(); self.process.wait(timeout=10)
        self.process.stdin.close(); self.process.stdout.close(); self.log.close()
        self.reader.join(timeout=2)


def smoke(config, output):
    from scripts.execution_aware_gpu_lease import GPUServiceLease
    from skillforge.environment import Environment, ToolError
    from skillforge.verifier import verify
    catalog = static_catalog(config)
    catalog.save(output / "catalog.json")
    tasks = smoke_tasks(config)
    immutable_json(output / "private-dev-tasks.json", [t.model_dump() for t in tasks])
    immutable_json(output / "registration.json", {"config": config, "catalog_hash": catalog.hash, "protocol": PROTOCOL,
                                                "sources": runtime_sources(), "scope": "P1 developmental real-model smoke only"})
    ledger = SplitLedger(ROOT / "results/skill-evolution/v1.2/source-ledger")
    for task in tasks: ledger.claim(task.task_id, "dev", related_groups=[task.parameters["order_id"], task.customer_id])
    rows, failure, session = [], None, None
    unfinished_budget = None
    started = time.perf_counter()
    try:
        with GPUServiceLease(), ExitStack() as cleanup:
            session = ModelSession(config, output)
            cleanup.callback(session.close)
            immutable_json(output / "model-identity.json", session.settings)
            for task in tasks:
                charged = sum(r["agent"]["metrics"]["tokens"] for r in rows)
                if charged + config["limits"]["max_tokens"] > config["smoke"]["max_model_tokens"] or time.perf_counter()-started >= config["smoke"]["max_wall_seconds"]:
                    failure = "development budget exhausted"; break
                folder = output / task.task_id
                folder.mkdir()
                env = Environment(str(folder / "live.sqlite"), fixture=task.fixture)
                rng = random.Random(task.seed)
                initial = env.snapshot(task.parameters["order_id"])
                public = {k: getattr(task, k) for k in ("task_id", "family", "request", "parameters")}
                session.send({"type": "run", "task": public, "catalog": catalog.entries(), "limits": config["limits"]})
                checkpoint_index = 0
                unfinished_budget = None
                try:
                    while True:
                        remaining = config["smoke"]["max_wall_seconds"] - (time.perf_counter() - started)
                        if remaining <= 0:
                            raise TimeoutError("development wall budget exhausted")
                        msg = session.receive(min(120, remaining))
                        if msg["type"] == "completed": break
                        if msg["type"] == "checkpoint":
                            unfinished_budget = msg["value"]["budget"]
                            save_snapshot(folder / "checkpoints" / str(checkpoint_index), env, msg["value"], rng)
                            checkpoint_index += 1
                            session.send({"type": "checkpoint_saved"})
                        elif msg["type"] == "tool":
                            try:
                                before = len(env.audit)
                                value = env.call(msg["name"], msg["arguments"], task.customer_id, msg["key"])
                                response = {"type": "tool_result", "result": value}
                            except ToolError as exc: response = {"type": "tool_result", "error": exc.code}
                            finally:
                                for event in env.audit[before:]: event["decision_origin"] = msg["source"]
                            session.send(response)
                        else: raise ValueError("unexpected model RPC")
                    final = env.snapshot(task.parameters["order_id"])
                    agent = msg["result"]
                    row = {"task_id": task.task_id, "source_group": task.task_id, "experiment_split": "dev",
                           "task_hash": fingerprint(task.model_dump()), "agent": agent,
                           "verification": verify(task, initial, final, env.audit, agent["outcome"]),
                           "tool_audit": env.audit, "scope": "private evaluator envelope; never sent to Agent"}
                    immutable_json(folder / "result.json", row)
                    rows.append(row)
                    unfinished_budget = None
                    print(json.dumps({"task": task.task_id, "success": row["verification"]["task_success"],
                                      "search": agent["metrics"]["search_calls"], "load": agent["metrics"]["load_calls"],
                                      "skills": len(agent["skill_events"]), "tokens": agent["metrics"]["tokens"]}), flush=True)
                finally: env.close()
            session.close(); session = None
    except Exception as exc:
        failure = type(exc).__name__ + ": " + str(exc)
    finally:
        if session: session.close()
    report = {"status": "complete" if len(rows) == len(tasks) and failure is None else "blocked_or_incomplete",
              "failure": failure, "n": len(rows), "planned": len(tasks), "eoc": sum(r["verification"]["task_success"] for r in rows),
              "actual_violations": sum(r["verification"]["actual_policy_violation"] for r in rows),
              "attempted_violations": sum(r["verification"]["attempted_policy_violation"] for r in rows),
              "search_tasks": sum(bool(r["agent"]["search_events"]) for r in rows),
              "load_tasks": sum(bool(r["agent"]["load_events"]) for r in rows),
              "skill_tasks": sum(bool(r["agent"]["skill_events"]) for r in rows),
              "tokens": sum(r["agent"]["metrics"]["tokens"] for r in rows), "wall_seconds": time.perf_counter()-started,
              "unfinished_task_budget": unfinished_budget,
              "charged_tokens_including_incomplete": sum(r["agent"]["metrics"]["tokens"] for r in rows) + (unfinished_budget or {}).get("used", {}).get("tokens", 0),
              "engineering_passed": None, "research_claim_passed": None,
              "stronger_model_comparison": config["stronger_model"], "scope": "dev capability/cost smoke; no efficacy claim"}
    immutable_json(output / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["preflight", "smoke"])
    parser.add_argument("--config", default="configs/skill-evolution-v1.2.dev.json")
    parser.add_argument("--output", required=True)
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args()
    os.chdir(ROOT)
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    if args.command == "preflight": result = preflight(config, output, not args.skip_tests)
    else: result = smoke(config, output)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    raise SystemExit(0 if result.get("passed", result.get("status") == "complete") else 1)


if __name__ == "__main__": main()
