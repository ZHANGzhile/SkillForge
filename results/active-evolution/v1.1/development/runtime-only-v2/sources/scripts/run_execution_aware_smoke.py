"""P10.5 fixed-H0 paired development executions. Not a formal protocol freeze."""
import argparse
import json
from pathlib import Path
import time

from scripts.active_evolution_dataset import generate
from scripts.execution_aware_gpu_lease import GPUServiceLease
from scripts.execution_aware_agent_eval import ExecutionAgentSession
from scripts.prepare_active_evolution import file_hash
from skillforge.evolution_registry import immutable_json
from skillforge.evolution_schemas import Hypothesis, fingerprint
from skillforge.execution_aware.metrics import paired_execution_metrics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("results/active-evolution/v1.1/development/runtime-only-v1"))
    args = parser.parse_args(); root = args.output
    setup = {"config": "configs/training.recovery-v1.json", "adapter": "results/training/main-v3/sft/adapter",
             "adapter_sha256": "f195fe00128aa86587b5b37b5a3940116276966162d8f72c5bb222baf445669b"}
    h0 = Hypothesis(hypothesis_id="H0", kind="no_change").model_dump(mode="json")
    contracts = {s["family"]: s for s in json.loads(Path("results/real-v2-frozen/frozen.json").read_text(encoding="utf-8"))["skills"]}
    jobs = []
    for world in ("W3", "W5", "W6"):
        specs = generate(world, 110510, {"model_validation": 8})
        for index in (0, 1, 2, 6):
            for runtime in ("old", "new"):
                jobs.append({"world": world, "spec": specs[index], "runtime": runtime})
    sources = sorted(set(Path("skillforge").rglob("*.py")) | {Path(__file__), Path("scripts/execution_aware_agent_eval.py"),
        Path("scripts/active_evolution_dataset.py"), Path("scripts/active_evolution_worlds.py"), Path("scripts/execution_aware_gpu_lease.py")})
    identity = {"development_only": True, "stage": "P10.5", "jobs": jobs, "setup": setup, "contracts": contracts,
                "patch": h0, "sources": {str(p): file_hash(p) for p in sources},
                "scope": "fixed H0, paired runtime-only development tasks, same six-world rule family; not learned-bundle gain",
                "limits": {"tokens": 1000000, "wall_seconds": 3600, "task_token_reservation": 16*16384},
                "selection": "pre-outcome indices 0,1,2,6, seed110510; no selection on model success"}
    immutable_json(root / "identity.json", identity)
    before, after = [], []
    started = time.perf_counter(); tokens = 0
    with GPUServiceLease():
        session = ExecutionAgentSession(root / "agent", setup)
        try:
            immutable_json(root / "model-settings.json", session.settings)
            for i, job in enumerate(jobs):
                path = root / "tasks" / f"{i:03d}.json"
                if path.exists():
                    saved = json.loads(path.read_text(encoding="utf-8"))
                    if saved["identity_hash"] != fingerprint(identity) or fingerprint(saved["result"]) != saved["result_hash"]:
                        raise ValueError("smoke checkpoint identity changed")
                    result = saved["result"]
                else:
                    if tokens + identity["limits"]["task_token_reservation"] > identity["limits"]["tokens"] or time.perf_counter()-started > 3400:
                        raise RuntimeError("development budget exhausted before dispatch")
                    immutable_json(root / "attempts" / f"{i:03d}.json", {"identity_hash": fingerprint(identity), "job": i,
                        "token_reservation": identity["limits"]["task_token_reservation"]})
                    result = session.run(job["spec"], job["world"], contracts[job["spec"]["family"]], h0, runtime=job["runtime"])
                    immutable_json(path, {"identity_hash": fingerprint(identity), "job": i, "result": result, "result_hash": fingerprint(result)})
                tokens += result["agent"]["metrics"]["tokens"]
                (before if job["runtime"] == "old" else after).append(result)
                print(json.dumps({"completed": i+1, "total": len(jobs), "runtime": job["runtime"],
                                  "eoc": result["verification"]["task_success"], "tokens": tokens}), flush=True)
        finally:
            session.close()
    summary = {"identity_hash": fingerprint(identity), "stage": "P10.5-development-only", "metrics": paired_execution_metrics(before, after),
               "before_eoc": sum(r["verification"]["task_success"] for r in before),
               "after_eoc": sum(r["verification"]["task_success"] for r in after),
               "actual_violations": sum(r["verification"]["actual_policy_violation"] for r in before+after),
               "tokens": tokens, "invocation_seconds": time.perf_counter()-started,
               "task_seconds": sum(r["seconds"] for r in before+after), "formal_cost_gate": "not_frozen"}
    immutable_json(root / "summary.json", summary)
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
