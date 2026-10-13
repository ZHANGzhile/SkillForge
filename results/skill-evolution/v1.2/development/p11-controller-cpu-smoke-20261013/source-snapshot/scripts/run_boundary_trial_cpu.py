"""Frozen continuous CPU Boundary benchmark; no real Agent capability claim."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

from scripts.run_skill_evolution import ROOT, digest_file
from scripts.skill_evolution_release import relative
from scripts.continue_skill_evolution_selection import publish
from scripts.boundary_trial_dataset import cpu_specs, daily_spec
from scripts.active_evolution_dataset import public_candidate
from scripts.boundary_trial_probe import probe as actual_probe
from skillforge.skill_evolution.agent_evidence import read
from skillforge.skill_evolution.catalog import Catalog
from skillforge.boundary_runtime.catalog import BoundaryCatalog, h0_bindings
from skillforge.boundary_evolution.trigger import DriftController, Interaction
from skillforge.boundary_lineage.proposal import checked, hashed, propose, candidate_catalog, parent_key
from skillforge.boundary_lineage.validation import declare_boundary_validation, boundary_gate
from skillforge.evolution_evidence import EvidenceBoundary
from skillforge.evolution_boundary import public_predictions
from skillforge.evolution_schemas import EvidenceView, Hypothesis, fingerprint
from skillforge.evolution_config import LearningOptions
from skillforge.hypothesis import generate_hypotheses
from skillforge.evolution_common.artifacts import SplitLedger
from skillforge.active_learning import convergence_metrics


def isolated(folder, method, seeds, pool, hypotheses, probe, options, random_seed):
    folder.mkdir(parents=True, exist_ok=False)
    packet = {"output": str(folder.resolve()), "method": method, "random_seed": random_seed,
        "seed_evidence": [e.model_dump(mode="json") for e in seeds], "candidates": [c.model_dump(mode="json") for c in pool],
        "hypotheses": [h.model_dump(mode="json") for h in hypotheses], "learning": options.model_dump()}
    publish(folder / "public-packet.json", packet)
    with (folder / "worker.stderr.log").open("w", encoding="utf-8") as stderr:
        p = subprocess.Popen([sys.executable, "-m", "skillforge.boundary_trials.worker"], cwd=ROOT, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=stderr, text=True, encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        try:
            p.stdin.write(json.dumps(packet) + "\n"); p.stdin.flush()
            for i, line in enumerate(p.stdout):
                request = json.loads(line); publish(folder / "rpc" / (str(i) + ".json"), request)
                if request["type"] == "completed":
                    p.wait(timeout=10)
                    value = read(folder / "candidate-frozen.json"); checked(value)
                    if p.returncode or value["hash"] != request["result_hash"]: raise ValueError("worker freeze mismatch")
                    return value
                if request["type"] != "probe": raise ValueError("unselected candidate expansion is forbidden")
                response = probe(request["candidate_id"]).model_dump(mode="json")
                publish(folder / "rpc" / (str(i) + "-response.json"), response)
                p.stdin.write(json.dumps({"type": "response", "value": response}) + "\n"); p.stdin.flush()
            raise RuntimeError("public worker exited before candidate freeze")
        finally:
            if p.poll() is None: p.kill(); p.wait(timeout=10)
            p.stdin.close(); p.stdout.close()


def observations(raw, spec, contract):
    c = public_candidate(spec, contract)
    manifest = {"policy_epoch": spec["policy_epoch"], "members": {spec["task_id"]: {"hash": fingerprint(spec), "split": spec["split"]}}}
    return EvidenceBoundary(manifest).export(raw, spec, c.baseline_prediction, c.guard_prediction)


def run(root):
    root = Path(root).resolve()
    p = read(root / "protocol.json"); checked(p)
    if (root / "cpu/report.json").exists(): raise ValueError("complete CPU benchmark cannot be rerun")
    for name, sha in p["sources"].items():
        if digest_file(ROOT / name) != sha or digest_file(root / "source-snapshot" / name) != sha: raise ValueError("registered execution source changed")
    base = Catalog.load(root / "catalog.json")
    options = LearningOptions.model_validate(p["learning"])
    ledger = SplitLedger(ROOT / "results/skill-evolution/v1.2/source-ledger")
    physical, tool_calls, rows, chains, started = 0, 0, [], [], time.perf_counter()
    for world in p["cpu_worlds"]:
        for seed in p["sequence_seeds"]:
            controllers = {m: DriftController(p["trigger_policy"]) for m in p["cpu_methods"]}
            parents = {m: BoundaryCatalog(base.entries(), h0_bindings(base)) for m in p["cpu_methods"]}
            for stage, actual_world in enumerate((world, world, "H0")):
                folder = root / "cpu" / world / str(seed) / str(stage)
                skill_id = "modify_unfulfilled_order_address" if world == "W6" else "refund_captured_payment"
                contract = next(e["contract"] for e in base.entries() if e["skill_id"] == skill_id)
                specs = {split: cpu_specs(world, seed, stage, split, n) for split, n in p["cpu_counts"].items()}
                daily = [daily_spec(world, seed, stage, i) for i in range(3)]
                for split, values in specs.items(): publish(folder / "dataset" / (split + ".json"), values)
                publish(folder / "dataset/daily.json", daily)
                for spec in [*daily, *(s for v in specs.values() for s in v)]:
                    partition = spec["split"] if spec["split"] in {"validation", "stable_validation", "test", "stable_test"} else "train"
                    ledger.claim("continuous-cpu-" + spec["task_id"], partition,
                        related_groups=[spec["task_id"], spec["fixture"]["order_id"], spec["fixture"]["customer_id"]])
                cache = {}
                def actual(spec):
                    nonlocal physical, tool_calls
                    key = spec["task_id"]
                    if key not in cache:
                        raw = actual_probe(spec, actual_world, contract)
                        publish(folder / "private-probes" / (key + ".json"), raw)
                        cache[key] = raw; physical += 1; tool_calls += len(raw["tool_audit"])
                    return cache[key]
                segment = specs["explore"][0]["policy_epoch"]
                seeds = [observations(actual(s), s, contract).model_copy(update={"policy_epoch": segment}) for s in daily]
                pool = [public_candidate(s, contract) for s in specs["explore"]]
                hypotheses = generate_hypotheses(p["hypothesis_fields"])
                by_id = {s["task_id"]: s for s in specs["explore"]}
                for method in p["cpu_methods"]:
                    parent, controller = parents[method], controllers[method]
                    parent_before = parent.bundle_hash
                    decisions = []
                    for spec, e in zip(daily, seeds):
                        status = parent.effective_gate(contract, e.observations, spec["parameters"]).status
                        view = e.model_copy(update={"baseline_prediction": {"APPLICABLE": True, "INAPPLICABLE": False}.get(status), "policy_epoch": "public-stream"})
                        body = {"source_group": "continuous-cpu-" + spec["task_id"], "object_id": spec["parameters"]["order_id"],
                            "parent_revision": parent_key(parent, skill_id), "evidence": view.model_dump(mode="json"),
                            "feedback": "business" if e.label != "unknown" else "unknown", "probe_origin": "daily",
                            "query_receipt_hash": fingerprint(actual(spec))}
                        item = Interaction(receipt_id=fingerprint(body), **body)
                        decisions.append(controller.observe(item))
                    local = folder / method
                    publish(local / "daily-decisions.json", decisions)
                    trigger = next((d for d in decisions if d["state"] == "SUSPECTED_DRIFT" and not d["pause_related_skill"]), None)
                    proposal, learner, candidate, br = None, None, parent, None
                    logical_queries, converged, reason = 0, False, "NO_TRIGGER"
                    if trigger and method != "no_adapt":
                        controller.begin_exploration(trigger["trigger_key"], sandbox_id="cpu-trial-" + fingerprint([world, seed, stage, method]))
                        def query(key):
                            spec = by_id[key]
                            e = observations(actual(spec), spec, contract)
                            status = parent.effective_gate(contract, e.observations, spec["parameters"]).status
                            drift_view = e.model_copy(update={"baseline_prediction": {"APPLICABLE": True, "INAPPLICABLE": False}.get(status)})
                            body = {"source_group": "continuous-cpu-" + key, "object_id": spec["parameters"]["order_id"],
                                "parent_revision": parent_key(parent, skill_id), "evidence": drift_view.model_dump(mode="json"),
                                "feedback": "business" if e.label != "unknown" else "unknown", "probe_origin": "authorized_sandbox",
                                "sandbox_id": controller.explorations[trigger["trigger_key"]]["sandbox_id"], "query_receipt_hash": fingerprint(actual(spec))}
                            controller.charge_probe(trigger["trigger_key"], Interaction(receipt_id=fingerprint(body), **body))
                            return e
                        learner = isolated(local / "learner", method, seeds, pool, hypotheses, query, options, seed + stage)
                        logical_queries = len(learner["queries"]); converged = learner["belief_supported"]; reason = learner["stop_reason"]
                        if method in {"ExistingActiveV2", "OriginalActive"}:
                            proposal = propose(parent, skill_id, learner)
                            publish(local / "proposal.json", proposal)
                            if proposal["decision"] == "PROPOSE_BOUNDARY": candidate = candidate_catalog(parent, proposal)
                        elif converged:
                            h = Hypothesis.model_validate(learner["diagnostic_hypothesis"])
                            bindings = parent.boundaries(); bindings[skill_id]["patch"] = h.model_dump(mode="json")
                            candidate = BoundaryCatalog(base.entries(), bindings)
                    # CPU references have their own Boundary-only parent chain.
                    # They never become the effective parent of a real Agent.
                    validation = []
                    for split in ("validation", "stable_validation"):
                        for spec in specs[split]:
                            raw = actual(spec); c = public_candidate(spec, contract)
                            errors = {e["error"] for e in raw["tool_audit"] if e["error"]}
                            truth = True if raw["procedure_success"] else False if errors == {"business_rule_rejected"} else None
                            def predicted(cat):
                                return {"APPLICABLE": True, "INAPPLICABLE": False}.get(cat.effective_gate(contract, c.observations, spec["parameters"]).status)
                            validation.append({"task_id": spec["task_id"], "task_hash": fingerprint(spec),
                                "source_group": "continuous-cpu-" + spec["task_id"], "split": split, "probe_hash": fingerprint(raw),
                                "truth": truth, "parent": predicted(parent), "candidate": predicted(candidate), "actual_violations": raw["actual_violations"]})
                    if candidate.bundle_hash != parent.bundle_hash:
                        # Same strict paired Boundary arithmetic for references;
                        # proposal identity is explicit even without Active certificate.
                        plan = hashed({"schema": "cpu-boundary-reference-validation-plan-v1", "proposal_hash": proposal["hash"] if proposal else learner["hash"],
                            "parent_bundle_hash": parent.bundle_hash, "candidate_bundle_hash": candidate.bundle_hash,
                            "members": [{k: r[k] for k in ("task_id", "task_hash", "source_group", "split")} for r in validation]})
                        br = boundary_gate(plan, validation)
                        publish(local / "boundary-validation-plan.json", plan); publish(local / "boundary-validation.json", br)
                        if br["decision"] == "BOUNDARY_GATE_PASSED": parents[method] = candidate
                    effective = parents[method]
                    freeze = hashed({"method": method, "parent_bundle_hash": parent_before, "candidate_bundle_hash": candidate.bundle_hash,
                        "effective_bundle_hash": effective.bundle_hash, "learner_hash": learner["hash"] if learner else None,
                        "boundary_report_hash": br["hash"] if br else None, "agent_admitted": False, "activated": False})
                    publish(local / "decision-before-test.json", freeze)
                    tested = []
                    for split in ("test", "stable_test"):
                        for spec in specs[split]:
                            raw = actual(spec); c = public_candidate(spec, contract)
                            errors = {e["error"] for e in raw["tool_audit"] if e["error"]}
                            truth = True if raw["procedure_success"] else False if errors == {"business_rule_rejected"} else None
                            def pred(cat): return {"APPLICABLE": True, "INAPPLICABLE": False}.get(cat.effective_gate(contract, c.observations, spec["parameters"]).status)
                            tested.append({"task_id": spec["task_id"], "split": split, "truth": truth,
                                "candidate": pred(candidate), "effective": pred(effective), "parent": pred(parent), "probe_hash": fingerprint(raw)})
                    summary = {"world": world, "sequence_seed": seed, "stage": stage, "method": method,
                        "triggered": trigger is not None, "queries": logical_queries, "raw_belief_converged": converged,
                        "queries_to_convergence": logical_queries if converged else None, "stop_reason": reason,
                        "boundary_gate": br["decision"] if br else "NO_CANDIDATE", "cpu_boundary_updated": effective.bundle_hash != parent_before,
                        "candidate_false_allow": sum(r["candidate"] is True and r["truth"] is False for r in tested),
                        "candidate_false_block": sum(r["candidate"] is False and r["truth"] is True for r in tested),
                        "effective_false_allow": sum(r["effective"] is True and r["truth"] is False for r in tested),
                        "effective_false_block": sum(r["effective"] is False and r["truth"] is True for r in tested),
                        "stable_regressions": sum(r["split"] == "stable_test" and r["parent"] == r["truth"] and r["effective"] != r["truth"] for r in tested),
                        "unknown_test": sum(r["truth"] is None or r["effective"] is None for r in tested),
                        "parent_bundle_hash": parent_before, "effective_bundle_hash": effective.bundle_hash,
                        "agent_admitted": False, "activated": False}
                    publish(local / "test.json", tested); publish(local / "trigger-checkpoint.json", controller.checkpoint()); publish(local / "result.json", hashed(summary))
                    rows.append(summary); chains.append(freeze); print(summary, flush=True)
    report = hashed({"schema": "continuous-cpu-boundary-results-v1", "protocol_hash": p["hash"], "complete": True,
        "runs": rows, "methods": {m: convergence_metrics([r for r in rows if r["method"] == m]) for m in p["cpu_methods"]},
        "cpu_parent_chains": chains, "physical_probes": physical, "physical_tool_calls": tool_calls,
        "logical_queries": sum(r["queries"] for r in rows), "cpu_wall_seconds": time.perf_counter() - started,
        "new_model_calls": 0, "new_tokens": 0, "agent_admitted": False, "activated": False,
        "scope": "CPU-only controlled daily stream; Boundary-only chain separate from actual Agent parent chain; engineering scale"})
    publish(root / "cpu/report.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--run", required=True)
    print(run(parser.parse_args().run))
