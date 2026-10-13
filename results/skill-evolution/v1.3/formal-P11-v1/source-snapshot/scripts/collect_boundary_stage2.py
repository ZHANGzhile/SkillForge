"""One fixed-model actual SQLite arm with durable budget ACKs, no auto replay."""
import random
import time
from pathlib import Path

from scripts.run_boundary_runtime_smoke import BoundarySession
from scripts.continue_skill_evolution_selection import publish
from scripts.evolution_budget import CheckpointAdmission
from scripts.boundary_stage2_evaluator import private_policy
from skillforge.schemas import Task
from skillforge.environment import Environment, ToolError
from skillforge.verifier import verify
from skillforge.evolution_common.snapshot import save_snapshot
from skillforge.evolution_schemas import fingerprint


def collect(session, folder, planned, catalog, limits, *, prior_tokens, token_cap, prior_wall, wall_cap, started):
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=False)
    task = Task.model_validate(planned["task"])
    public_task = {key: getattr(task, key) for key in ("task_id", "family", "request", "parameters")}
    admission = CheckpointAdmission(prior_tokens, token_cap, prior_wall, wall_cap)
    env = Environment(str(folder / "live.sqlite"), fixture=task.fixture, faults=planned.get("faults", {}))
    initial, row, error, index = env.snapshot(), None, None, 0
    publish(folder / "initial-state.json", initial)
    try:
        with private_policy(planned["world"]):
            session.send({"type": "run", "task": public_task, "catalog": catalog.entries(), "boundaries": catalog.boundaries(), "limits": limits})
            while True:
                remaining = admission.remaining(time.perf_counter() - started)
                if remaining <= 0: raise TimeoutError("registered collection wall budget exhausted")
                msg = session.receive(min(120, remaining))
                if msg["type"] == "completed":
                    agent = msg["result"]
                    verdict = verify(task, initial, env.snapshot(), env.audit, agent["outcome"])
                    if admission.charged_tokens() != agent["metrics"]["tokens"]: raise ValueError("inference fee settlement mismatch")
                    row = {"task": task.model_dump(), "agent": agent, "initial_state": initial, "final_state": env.snapshot(),
                        "tool_audit": env.audit, "verification": verdict, "model_identity_hash": fingerprint(session.settings)}
                    publish(folder / "result.json", row); break
                if msg["type"] == "checkpoint":
                    value = msg["value"]
                    save_snapshot(folder / "checkpoints" / str(index), env, value, random.Random(task.seed))
                    decision = admission.inspect(value, time.perf_counter() - started)
                    if decision is not None:
                        decision["checkpoint_index"] = index
                        publish(folder / "admissions" / (str(decision["request_index"]) + ".json"), decision)
                        if not decision["approved"]: raise ValueError("registered inference budget denied")
                        admission.record_approval(decision)
                    index += 1; session.send({"type": "checkpoint_saved"})
                elif msg["type"] == "tool":
                    before = len(env.audit)
                    try:
                        value = env.call(msg["name"], msg["arguments"], task.customer_id, msg["key"])
                        session.send({"type": "tool_result", "result": value})
                    except ToolError as exc: session.send({"type": "tool_result", "error": exc.code})
                    for event in env.audit[before:]: event["decision_origin"] = msg["source"]
                else: raise ValueError("unexpected model RPC")
    except Exception as exc: error = type(exc).__name__ + ": " + str(exc)
    finally:
        status = {"task_id": task.task_id, "completed": row is not None, "charged_tokens": admission.charged_tokens(),
            "failure": error, "charged_model_requests": len(admission.approved),
            "approved_unknown_requests": sum(r["status"] == "pending" and i in admission.approved
                for i, r in enumerate((admission.last or {}).get("model_requests", [])))}
        publish(folder / "collection-status.json", status); env.close()
    return row, status
