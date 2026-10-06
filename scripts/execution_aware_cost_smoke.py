"""Predeclared development cost strata for protocol A; never a quality gate."""
import argparse
import json
import math
from pathlib import Path
import time

from scripts.active_evolution_dataset import generate
from scripts.execution_aware_agent_eval import ExecutionAgentSession
from scripts.execution_aware_gpu_lease import GPUServiceLease
from scripts.prepare_active_evolution import file_hash
from skillforge.evolution_registry import immutable_json
from skillforge.evolution_schemas import Hypothesis, Predicate, fingerprint


def jobs_and_setup():
    setup = {"config": "configs/training.recovery-v1.json", "adapter": "results/training/main-v3/sft/adapter",
             "adapter_sha256": "f195fe00128aa86587b5b37b5a3940116276966162d8f72c5bb222baf445669b"}
    h0 = Hypothesis(hypothesis_id="H0", kind="no_change").model_dump(mode="json")
    fixtures = {
        "W3": Hypothesis(hypothesis_id="cost-numeric", kind="restrict", predicates=(
            Predicate(field="customer.risk_level", op="eq", value="MEDIUM"), Predicate(field="request.amount", op="gt", value=3000))),
        "W5": Hypothesis(hypothesis_id="cost-category", kind="restrict", predicates=(
            Predicate(field="customer.risk_level", op="eq", value="MEDIUM"), Predicate(field="shipment.status", op="eq", value="PROCESSING"))),
        "W6": Hypothesis(hypothesis_id="cost-relax", kind="relax", predicates=(
            Predicate(field="customer.risk_level", op="eq", value="LOW"), Predicate(field="shipment.status", op="eq", value="PROCESSING"))),
    }
    selected = {"W3": (0, 6), "W5": (0, 2), "W6": (0, 1)}
    jobs = []
    for world, indices in selected.items():
        specs = generate(world, 110712, {"model_validation": 8})
        for index in indices:
            for phase, patch in (("old", h0), ("proposal", fixtures[world].model_dump(mode="json"))):
                for runtime in ("old", "new"):
                    for decision in (False, True):
                        jobs.append({"world": world, "spec": specs[index], "phase": phase, "patch": patch,
                                     "runtime": runtime, "decision_only": decision})
    return jobs, setup


def summarize(jobs, results):
    strata = []
    for world in ("W3", "W5", "W6"):
        for runtime in ("old", "new"):
            for phase in ("old", "proposal"):
                for decision in (False, True):
                    rows = [r for j, r in zip(jobs, results) if (j["world"], j["runtime"], j["phase"], j["decision_only"]) == (world, runtime, phase, decision)]
                    seconds = sorted(r["seconds"] for r in rows)
                    strata.append({"world": world, "runtime": runtime, "bundle": phase, "decision_only": decision,
                        "n": len(rows), "p95_seconds": seconds[math.ceil(.95*len(rows))-1],
                        "mean_tokens": sum(r["agent"]["metrics"]["tokens"] for r in rows)/len(rows),
                        "max_tokens": max(r["agent"]["metrics"]["tokens"] for r in rows),
                        "model_errors": sum(r["agent"]["outcome"] == "error" for r in rows)})
    return {"development_only": True, "strata": strata, "n": len(results),
            "scope": "manual patches are cost fixtures, not learned proposals; n=2 per stratum does not guarantee tail cost",
            "quality_is_not_resource_gate": True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("results/active-evolution/v1.1/development/factorial-cost-v1"))
    args = parser.parse_args(); root = args.output
    jobs, setup = jobs_and_setup()
    contracts = {s["family"]: s for s in json.loads(Path("results/real-v2-frozen/frozen.json").read_text(encoding="utf-8"))["skills"]}
    files = sorted(set(Path("skillforge").rglob("*.py")) | {Path(__file__), Path("scripts/execution_aware_agent_eval.py"),
        Path("scripts/execution_aware_gpu_lease.py"), Path("scripts/active_evolution_dataset.py"), Path("scripts/active_evolution_worlds.py")})
    identity = {"stage": "A-cost-development", "setup": setup, "jobs": jobs, "contracts": contracts,
                "sources": {str(p): file_hash(p) for p in files}, "max_tokens": 2000000, "max_wall_seconds": 3600,
                "seed": 110712, "scope": "48 predeclared executions, distinct from runtime-only development and formal seeds"}
    immutable_json(root/"identity.json", identity)
    if (root/"invocation.json").exists():
        raise ValueError("completed or interrupted invocation already recorded; audit before resuming")
    started = time.perf_counter(); results = []; tokens = 0; reserved = 0; status = "incomplete"
    try:
        with GPUServiceLease():
            session = ExecutionAgentSession(root/"agent", setup)
            try:
                immutable_json(root/"model-settings.json", session.settings)
                for i, job in enumerate(jobs):
                    reservation = (1 if job["decision_only"] else 16)*16384
                    if tokens+reservation > identity["max_tokens"] or time.perf_counter()-started > 3300:
                        raise RuntimeError("cost smoke budget exhausted before dispatch")
                    reserved = reservation
                    immutable_json(root/"attempts"/f"{i:03d}.json", {"identity_hash": fingerprint(identity), "job": i, "reserved_tokens": reservation})
                    result = session.run(job["spec"], job["world"], contracts[job["spec"]["family"]],
                                         job["patch"], job["decision_only"], job["runtime"])
                    immutable_json(root/"tasks"/f"{i:03d}.json", {"identity_hash": fingerprint(identity), "job": i,
                        "result": result, "result_hash": fingerprint(result)})
                    tokens += result["agent"]["metrics"]["tokens"]; reserved = 0; results.append(result)
                    print(json.dumps({"completed": i+1, "total": len(jobs), "world": job["world"], "runtime": job["runtime"],
                                      "bundle": job["phase"], "decision": job["decision_only"], "tokens": tokens}), flush=True)
            finally:
                session.close()
        immutable_json(root/"summary.json", {"identity_hash": fingerprint(identity), **summarize(jobs, results)})
        status = "complete"
    finally:
        immutable_json(root/"invocation.json", {"identity_hash": fingerprint(identity), "status": status,
            "executions": len(results), "tokens": tokens, "incomplete_reserved_tokens": reserved,
            "charged_tokens": tokens+reserved, "invocation_seconds": time.perf_counter()-started})


if __name__ == "__main__":
    main()
