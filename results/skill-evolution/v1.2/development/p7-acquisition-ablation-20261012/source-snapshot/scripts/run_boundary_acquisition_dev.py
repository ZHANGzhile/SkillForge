"""Predeclared five-method acquisition dev ablation with actual sandbox receipts.

Not formal research, Agent admission, activation or a new training run. The
public learner has capability functions only; private validation opens after
each method's candidate freeze. Test/Stage 1 feedback never selects queries.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

from scripts.run_skill_evolution import ROOT, digest_file
from scripts.skill_evolution_release import hashed, relative
from scripts.continue_skill_evolution_selection import publish
from skillforge.skill_evolution.agent_evidence import read
from skillforge.skill_evolution.catalog import Catalog
from skillforge.evolution_schemas import Candidate, EvidenceView, Hypothesis, fingerprint
from skillforge.evolution_config import LearningOptions
from skillforge.evolution_evidence import EvidenceBoundary
from skillforge.evolution_boundary import parent_identity
from skillforge.belief import BeliefState
from skillforge.hypothesis import generate_hypotheses
from skillforge.active_learning import stopping_reason, convergence_metrics
from skillforge.execution_aware.challenge import ChallengeOptions, challenge_gate
from skillforge.boundary_evolution.acquisition import (METHODS, ProbeOptions, select,
    deep_requests, has_public_conflict, supported_stop)



def isolated_learn(folder, method, hypotheses, seeds, initial, probe, expand, learning, options):
    folder.mkdir(parents=True, exist_ok=False)
    packet = {"output": str(folder), "method": method,
        "hypotheses": [h.model_dump(mode="json") for h in hypotheses],
        "seed_evidence": [e.model_dump(mode="json") for e in seeds],
        "candidates": [c.model_dump(mode="json") for c in initial],
        "learning": learning.model_dump(), "probe_options": options.model_dump()}
    publish(folder / "public-packet.json", packet)
    with (folder / "worker.stderr.log").open("w", encoding="utf-8") as stderr:
        process = subprocess.Popen([sys.executable, "-m", "skillforge.boundary_evolution.learner_worker"],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr,
            text=True, encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        try:
            process.stdin.write(json.dumps(packet) + "\n"); process.stdin.flush()
            index = 0
            for line in process.stdout:
                request = json.loads(line)
                publish(folder / "rpc" / (str(index) + ".json"), request); index += 1
                if request["type"] == "completed":
                    result = read(folder / "candidate-frozen.json")
                    if result["hash"] != request["result_hash"] or result["public_packet_hash"] != fingerprint(packet):
                        raise ValueError("guarded learner completion identity mismatch")
                    process.wait(timeout=10)
                    if process.returncode: raise RuntimeError("public learner failed after completion")
                    return result
                if request["type"] == "probe": value = probe(request["candidate_id"]).model_dump(mode="json")
                elif request["type"] == "expand": value = [c.model_dump(mode="json") for c in expand(request["requests"])]
                else: raise ValueError("learner requested unsupported capability")
                publish(folder / "rpc" / (str(index - 1) + "-response.json"), value)
                process.stdin.write(json.dumps({"type": "response", "value": value}) + "\n"); process.stdin.flush()
            raise RuntimeError("public learner exited without completion; inspect worker.stderr.log")
        finally:
            if process.poll() is None: process.terminate(); process.wait(timeout=10)
            process.stdin.close(); process.stdout.close()


def run(stage1, output):
    from scripts.active_evolution_dataset import write_dataset, EvaluationStore, public_candidate, controlled_facts, _spec
    from skillforge.sandbox_probe import run_probe
    stage1, output = Path(stage1).resolve(), Path(output).resolve()
    if output.exists(): raise ValueError("fresh development root required")
    freeze = read(stage1 / "stage1-freeze.json")
    if freeze["hash"] != fingerprint({k: v for k, v in freeze.items() if k != "hash"}):
        raise ValueError("stage1 freeze tampered")
    catalog = Catalog.load(stage1 / "stage1-catalog.json")
    if catalog.hash != freeze["catalog_hash"]: raise ValueError("frozen catalog changed")
    worlds, seeds = ["W1", "W5", "W6"], [2026101241, 2026101242]
    options, probe_options = LearningOptions(), ProbeOptions()
    files = [Path(__file__), *ROOT.glob("skillforge/boundary_evolution/*.py"), *(ROOT / name for name in
        ["scripts/active_evolution_dataset.py", "scripts/active_evolution_worlds.py", "scripts/active_evolution_model_design.py",
         "skillforge/active_learning.py", "skillforge/belief.py", "skillforge/hypothesis.py", "skillforge/sandbox_probe.py",
         "skillforge/evolution_execution.py", "skillforge/evolution_boundary.py", "skillforge/evolution_evidence.py",
         "skillforge/execution_aware/challenge.py", "skillforge/execution_aware/acquisition.py",
         "skillforge/execution_aware/learner_worker.py"])]
    sources = {**freeze["implementation_sources"], **{relative(path): digest_file(path) for path in files}}
    for name, sha in freeze["implementation_sources"].items():
        if digest_file(ROOT / name) != sha: raise ValueError("frozen first-stage implementation changed")
    protocol = hashed({"schema": "boundary-acquisition-five-method-dev-v1", "engineering_only": True,
        "stage1_freeze_hash": freeze["hash"], "catalog_hash": catalog.hash,
        "worlds": worlds, "seeds": seeds, "methods": list(METHODS), "learning": options.model_dump(),
        "probe_options": probe_options.model_dump(), "counts": {"seed": 2, "explore": 40, "validation": 40, "stable_validation": 8},
        "sources": sources, "max_logical_explore_queries": len(worlds) * len(seeds) * len(METHODS) * 20,
        "new_model_calls": 0, "new_tokens": 0,
        "selection_rule": "candidate vs OriginalActive: strictly greater convergence and no worse RMQ, effective false allow/block, stable errors; zero actual probe violations; tie prefer fewer generated candidates then method name; otherwise KEEP_EXISTING",
        "fallback_rule": "common historical H0 for all acquisition comparisons; abstention is reported separately and never counted as convergence",
        "scope": "new dev seeds in known world families; finite-domain controlled sandbox, no formal/Agent/structural generalization claims"})
    publish(output / "protocol.json", protocol)
    for name in sources:
        target = output / "source-snapshot" / name
        target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(ROOT / name, target)
    started = time.perf_counter()
    results, physical = [], []
    # All base datasets and membership are frozen before the first query.
    for world in worlds:
        for seed in seeds:
            family = "modify_address" if world == "W6" else "refund"
            entry = next(row for row in catalog.entries() if row["contract"]["family"] == family)
            folder = output / world / str(seed)
            write_dataset(folder / "dataset", world, seed, protocol["counts"], entry["contract"])
    for world in worlds:
        for seed in seeds:
            folder = output / world / str(seed)
            store = EvaluationStore(folder / "dataset")
            contract = read(folder / "dataset/parent-skill.json")
            original_manifest = store.manifest
            boundary = EvidenceBoundary(original_manifest)
            specifications = {row["task_id"]: row for split in protocol["counts"] for row in read(folder / "dataset" / (split + ".json"))}
            cache = {}
            def actual(spec):
                key = spec["task_id"]
                if key not in cache:
                    value = run_probe(spec, world, contract=contract)
                    publish(folder / "private-probes" / (key + ".json"),
                            {"task_hash": fingerprint(spec), "result_hash": fingerprint(value), "result": value})
                    cache[key] = value
                    physical.append({"world": world, "seed": seed, "task_id": key,
                        "tool_calls": len(value["tool_audit"]), "actual_violations": value["actual_violations"]})
                return cache[key]
            def evidence_for(spec):
                candidate = public_candidate(spec, contract)
                return boundary.export(actual(spec), spec, candidate.baseline_prediction, candidate.guard_prediction)
            initial = [public_candidate(row, contract) for row in read(folder / "dataset/explore.json")]
            initial_seed = [evidence_for(row) for row in read(folder / "dataset/seed.json")]
            fields = sorted(set().union(*(e.observations for e in initial_seed)) & {"customer.risk_level", "order.status", "shipment.status", "payment.status", "request.amount", "payment.remaining_amount"})
            hypotheses = generate_hypotheses(fields)
            # Numeric thresholds are the original declared domain, unchanged by outcomes.
            publish(folder / "public-initial.json", {"candidates": [c.model_dump(mode="json") for c in initial],
                "seed_evidence": [e.model_dump(mode="json") for e in initial_seed],
                "hypotheses": [h.model_dump(mode="json") for h in hypotheses]})
            generated_specs = {}
            def expand(requests):
                values = []
                for request in requests:
                    facts = request["factors"]
                    address = facts.get("address.valid", True)
                    factors = (facts["customer.risk_level"], facts["order.status"], facts["shipment.status"],
                        facts["payment.status"], facts["payment.remaining_amount"], facts.get("request.amount", 100), address)
                    index = int(request["request_id"][:12], 16)
                    spec = _spec(world, seed, "explore", index, factors)
                    # _spec uses a canonical balance; preserve explicitly requested numeric facts.
                    spec["fixture"].update(captured=facts["payment.captured_amount"], refunded=facts["payment.refunded_amount"])
                    if any(controlled_facts(spec).get(k) != value for k, value in facts.items()):
                        raise ValueError("generated factor request cannot be realized by the frozen sandbox schema")
                    key = spec["task_id"]
                    if key in specifications and key not in generated_specs: raise ValueError("generated task aliases a base member")
                    if key not in generated_specs:
                        publish(folder / "generated-specs" / (key + ".json"), {"request": request, "spec": spec})
                        generated_specs[key] = spec; specifications[key] = spec
                        boundary.manifest["members"][key] = {"hash": fingerprint(spec), "split": "explore"}
                    values.append(public_candidate(spec, contract))
                return values
            def probe(key):
                spec = specifications[key]
                if spec["split"] != "explore": raise ValueError("learner cannot query heldout or seed partitions")
                return evidence_for(spec)
            for method in METHODS:
                local = folder / method
                result = isolated_learn(local, method, hypotheses, initial_seed, initial, probe, expand, options, probe_options)
                # Private dev validation only after all candidate decisions are frozen.
                measured = []
                diagnostic = Hypothesis.model_validate(result["diagnostic_hypothesis"])
                effective = Hypothesis.model_validate(result["effective_hypothesis"])
                for split in ("validation", "stable_validation"):
                    for spec in read(folder / "dataset" / (split + ".json")):
                        candidate = public_candidate(spec, contract); truth = bool(actual(spec)["procedure_success"])
                        predicted = effective.predict(candidate.observations, candidate.baseline_prediction, candidate.guard_prediction)
                        top = diagnostic.predict(candidate.observations, candidate.baseline_prediction, candidate.guard_prediction)
                        measured.append({"task_id": spec["task_id"], "split": split, "truth": truth,
                            "effective": predicted, "diagnostic": top, "parent": candidate.baseline_prediction})
                validation = hashed({"candidate_hash": result["hash"], "cases": measured,
                    "false_allow": sum(row["effective"] is True and not row["truth"] for row in measured),
                    "false_block": sum(row["effective"] is False and row["truth"] for row in measured),
                    "diagnostic_errors": sum(row["diagnostic"] != row["truth"] for row in measured),
                    "stable_errors": sum(row["effective"] != row["truth"] for row in measured if row["split"] == "stable_validation")})
                publish(local / "dev-validation.json", validation)
                summary = {"world": world, "seed": seed, "method": method, "queries": len(result["queries"]),
                    "queries_to_convergence": result["queries_to_convergence"], "belief_supported": result["belief_supported"],
                    "stop_reason": result["stop_reason"], "generated_candidates": result["generated_candidates"],
                    **{key: validation[key] for key in ("false_allow", "false_block", "diagnostic_errors", "stable_errors")},
                    "broad_queries": sum(q["phase"] == "BROAD" for q in result["queries"]),
                    "deep_queries": sum(q["phase"] == "DEEP" for q in result["queries"]),
                    "unknown_queries": sum(q["evidence"]["label"] == "unknown" for q in result["queries"]),
                    "uninformative_queries": sum(q["selected_eig"] < options.min_information_gain for q in result["queries"])}
                results.append(summary); print(json.dumps(summary), flush=True)
    aggregate = {}
    for method in METHODS:
        runs = [row for row in results if row["method"] == method]
        aggregate[method] = {**convergence_metrics(runs), **{key: sum(row[key] for row in runs) for key in
            ("false_allow", "false_block", "stable_errors", "diagnostic_errors", "generated_candidates", "queries", "broad_queries", "deep_queries", "unknown_queries", "uninformative_queries")}}
    base = aggregate["OriginalActive"]
    viable = [name for name in ("BroadOnly", "DeepOnly", "BroadThenDeep") if
        aggregate[name]["convergence_rate_within_budget"] > base["convergence_rate_within_budget"] and
        all(aggregate[name][key] <= base[key] for key in ("restricted_mean_queries_to_convergence", "false_allow", "false_block", "stable_errors"))]
    if any(row["actual_violations"] for row in physical): viable = []
    selected = min(viable, key=lambda name: (aggregate[name]["generated_candidates"], name)) if viable else "KEEP_EXISTING"
    report = hashed({"schema": "boundary-acquisition-five-method-dev-results-v1", "protocol_hash": protocol["hash"],
        "complete": True, "engineering_only": True, "runs": results, "methods": aggregate, "selected": selected,
        "physical_probes": len(physical), "physical_tool_calls": sum(row["tool_calls"] for row in physical),
        "actual_probe_violations": sum(row["actual_violations"] for row in physical),
        "logical_explore_queries": sum(row["queries"] for row in results),
        "shared_probe_cache": "actual identical sandbox receipts cached across paired methods; logical method query cost counted in each method",
        "new_model_calls": 0, "new_tokens": 0, "cpu_wall_seconds": time.perf_counter() - started,
        "agent_admitted": False, "activated": False, "scope": protocol["scope"]})
    publish(output / "physical-probes.json", physical); publish(output / "report.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage1", required=True); parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = run(args.stage1, args.output)
    print(json.dumps({key: result[key] for key in ("complete", "selected", "physical_probes", "logical_explore_queries")}))
