"""Independent protocol A freeze, CPU boundaries, and four-arm Agent evaluation."""
import argparse
import json
from pathlib import Path
import queue
import time
import uuid

from scripts.active_evolution_dataset import EvaluationStore, public_candidate
from scripts.active_evolution_continual import paired_measure
from scripts.evaluate_active_evolution import Evaluator, run_method
from scripts.execution_aware_agent_eval import ExecutionAgentSession
from scripts.execution_aware_gpu_lease import GPUServiceLease
from scripts.execution_aware_protocol import design, cost_gate, write_split_dataset
from scripts.prepare_active_evolution import file_hash
from skillforge.active_agent.policy_view import bundle
from skillforge.evolution_registry import immutable_json, boundary_admission
from skillforge.evolution_schemas import Hypothesis, fingerprint
from skillforge.execution_aware.admission import AdmissionEvidence, admission_funnel
from skillforge.execution_aware.factorial import paired_factorial
from skillforge.execution_aware.metrics import paired_execution_metrics


H0 = Hypothesis(hypothesis_id="H0", kind="no_change").model_dump(mode="json")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load(root):
    record = read(Path(root)/"protocol.json"); protocol = record["protocol"]
    if fingerprint(protocol) != record["protocol_hash"]:
        raise ValueError("protocol integrity mismatch")
    for path, digest in protocol["sources"].items():
        if file_hash(path) != digest:
            raise ValueError("frozen A source changed: "+path)
    for path, digest in protocol["datasets"].items():
        if file_hash(Path(path)/"manifest.json") != digest:
            raise ValueError("frozen A dataset manifest changed")
    return protocol


def strict_boundary(candidate, report):
    return boundary_admission(candidate, report) and report["stable_regressions"] == 0


def different(contract, before, after, specs):
    a, b = Hypothesis.model_validate(before), Hypothesis.model_validate(after)
    for spec in specs:
        c = public_candidate(spec, contract)
        x = a.predict(c.observations, c.baseline_prediction, c.guard_prediction)
        y = b.predict(c.observations, c.baseline_prediction, c.guard_prediction)
        if x is not None and y is not None and x != y:
            return True
    return False


def freeze(root, preparation, cost_root):
    root, preparation, cost_root = map(Path, (root, preparation, cost_root))
    if (root/"protocol.json").exists():
        return load(root)
    measured = read(cost_root/"identity.json"); smoke = read(cost_root/"summary.json"); invocation = read(cost_root/"invocation.json")
    repeatability = read(cost_root/"first-action-repeatability-v2.json")
    if repeatability["disagreeing_groups"]:
        raise ValueError("observed model disagreement requires a repeated-validation design before freezing")
    if invocation["status"] != "complete" or len(measured["jobs"]) != smoke["n"]:
        raise ValueError("complete factorial cost smoke required")
    for path, digest in measured["sources"].items():
        if file_hash(path) != digest:
            raise ValueError("measured dependency changed: "+path)
    prior = read("results/active-evolution/v1.1/development/resource-ledger.json")
    prior_tokens = prior["charged_tokens"] + invocation["charged_tokens"]
    prior_seconds = prior["invocation_seconds"] + invocation["invocation_seconds"]
    options = [(design(n), cost_gate(design(n), smoke, prior_tokens, prior_seconds)) for n in (8, 4)]
    chosen = next(((c, g) for c, g in options if g["cost_gate_passed"]), None)
    if chosen is None:
        raise ValueError("neither predeclared A workload fits shared budget; protocol stays unfrozen")
    config, gate = chosen
    data_root = preparation/"datasets" if config["model_counts"]["model_stable_test"] == 8 else root/"datasets"
    contracts = measured["contracts"]; counts = {**config["cpu_counts"], **config["model_counts"]}
    datasets = {}
    for world in config["worlds"]:
        for seed in config["paired_seeds"]:
            path = data_root/world/str(seed)
            if not (path/"manifest.json").exists():
                write_split_dataset(path, world, seed, counts, contracts["modify_address" if world == "W6" else "refund"])
            manifest = read(path/"manifest.json")
            if manifest["counts"] != counts or manifest["partial_coverage_splits"]:
                raise ValueError("dataset does not match selected design")
            datasets[path.as_posix()] = file_hash(path/"manifest.json")
    previous = None
    for epoch, world in enumerate(config["continual"]["worlds"], 1):
        path = root/"continuous/datasets"/str(epoch)
        write_split_dataset(path, world, config["continual"]["seed"], counts, contracts["refund"], previous_world=previous)
        datasets[path.as_posix()] = file_hash(path/"manifest.json"); previous = world
    # A does not depend on the evolving B controller or acquisition implementation.
    base = read("results/active-evolution/v1/formal-v1/protocol.json")["protocol"]
    sources = set(base["sources"])
    sources.update("skillforge/execution_aware/"+name+".py" for name in ("__init__", "contracts", "runtime", "worker", "metrics", "admission", "factorial"))
    sources.update("scripts/"+name+".py" for name in ("execution_aware_formal", "execution_aware_protocol", "execution_aware_agent_eval", "execution_aware_gpu_lease"))
    sources.update({measured["setup"]["config"], measured["setup"]["adapter"]+"/adapter_config.json"})
    config["status"] = "research-frozen"
    gate = cost_gate(config, smoke, prior_tokens, prior_seconds)
    protocol = {"config": config, "data_root": data_root.as_posix(), "datasets": datasets,
                "sources": {p: file_hash(p) for p in sorted(sources)}, "cost_gate": gate,
                "cost_identity_hash": fingerprint(measured), "cost_root": cost_root.as_posix(),
                "model_settings": read(cost_root/"model-settings.json"), "setup": measured["setup"],
                "prior_charged_tokens": prior_tokens, "prior_invocation_seconds": prior_seconds,
                "learning": read("configs/active-evolution-v1.json")["learning"],
                "bootstrap": {"seed": 110901, "replicates": 5000, "unit": "world-seed", "stratified_by": "world"},
                "candidate_test": "isolated diagnostics; never changes validation admission or activation",
                "effective_test": "runtime-specific admission fallback to actual Agent parent",
                "validation_repeats": 1,
                "validation_repeatability_evidence": {"sha256": file_hash(cost_root/"first-action-repeatability-v2.json"),
                    "identical_context_groups": repeatability["identical_context_groups"], "disagreeing_groups": 0,
                    "scope": "first actions only; no claim of deterministic full trajectories"},
                "continual_primary_inference": False,
                "activation": "isolated evaluation only; no deployment modification"}
    immutable_json(root/"protocol.json", {"protocol": protocol, "protocol_hash": fingerprint(protocol)})
    for path in sources:
        target = root/"sources"/path; target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and file_hash(target) != protocol["sources"][path]:
            raise ValueError("source snapshot differs")
        if not target.exists():
            target.write_bytes(Path(path).read_bytes())
    return protocol


def learn_one(dataset, directory, learning, seed, before=H0):
    result = run_method(dataset, directory/"learning", "active", learning, seed, evaluate_test=False)
    evaluator = Evaluator(dataset, directory/"boundary-evaluation")
    candidate_path = directory/"learning/learner/candidate.json"
    candidate = read(candidate_path) if candidate_path.exists() else None
    proposed = candidate["hypothesis"] if candidate else before
    passed = bool(candidate and strict_boundary(candidate, read(directory/"learning/validation.json")))
    support = evaluator.store.read("explore")
    nontrivial = different(evaluator.contract, before, proposed, support)
    cases = paired_measure(evaluator, Hypothesis.model_validate(proposed), Hypothesis.model_validate(before), ("validation", "stable_validation"))
    changed = [r for r in cases if r["split"] == "validation"]; stable = [r for r in cases if r["split"] == "stable_validation"]
    safe_against_parent = (not any(r["prediction"] and not r["truth"] for r in changed)
        and sum(r["truth"] and not r["prediction"] for r in changed) <= sum(r["truth"] and not r["baseline_prediction"] for r in changed)
        and not any(r["baseline_prediction"] == r["truth"] and r["prediction"] != r["truth"] for r in stable)
        and not any(r["actual_violations"] for r in cases))
    accepted = passed and safe_against_parent and nontrivial
    effective = proposed if accepted else before
    record = {"before": before, "proposal": proposed, "effective": effective, "nontrivial": nontrivial,
              "boundary_validation_passed": (passed and safe_against_parent) if candidate else None, "boundary_admitted": accepted,
              "belief_converged": result["convergence"]["converged"], "learning": result,
              "validation_cases": cases, "candidate_hash": fingerprint(candidate)}
    immutable_json(directory/"boundary.json", record)
    freeze_record = {"candidate_hash": fingerprint(record), "dataset_hash": fingerprint(evaluator.store.manifest)}
    immutable_json(directory/"boundary-freeze.json", freeze_record)
    test = paired_measure(evaluator, Hypothesis.model_validate(effective), Hypothesis.model_validate(before),
                          ("test", "stable_test"), record, freeze_record)
    immutable_json(directory/"boundary-test.json", {"freeze": freeze_record, "cases": test})
    return record


def run_cpu(root):
    root = Path(root); protocol = load(root); c = protocol["config"]; rows = []
    for world in c["worlds"]:
        for seed in c["paired_seeds"]:
            record = learn_one(Path(protocol["data_root"])/world/str(seed), root/"cpu"/world/str(seed), protocol["learning"], seed)
            rows.append({"world": world, "seed": seed, **record})
            print(json.dumps({"stage": "A-CPU", "world": world, "seed": seed, "admitted": record["boundary_admitted"]}), flush=True)
    # Continuous learning begins only after the independent matrix is complete.
    previous = H0; lineage = []
    for epoch, world in enumerate(c["continual"]["worlds"], 1):
        record = learn_one(root/"continuous/datasets"/str(epoch), root/"continuous/cpu"/str(epoch), protocol["learning"], c["continual"]["seed"], previous)
        node = {"epoch": epoch, "world": world, "parent_node": fingerprint(lineage[-1]) if lineage else None, **record}
        immutable_json(root/"continuous/cpu"/str(epoch)/"lineage.json", node)
        lineage.append(node); previous = record["effective"]
    immutable_json(root/"cpu-report.json", {"protocol_hash": fingerprint(protocol), "independent": rows, "continuous": lineage})


def agent_admission(before, after, decisions_before, decisions_after, changed_count):
    if (not before or len(before) != len(after) or len(decisions_before) != changed_count
            or len(decisions_after) != changed_count or not 0 < changed_count < len(before)):
        raise ValueError("complete paired validation with stable anchors required")
    for a, b in list(zip(before, after))+list(zip(decisions_before, decisions_after)):
        if a["spec_hash"] != b["spec_hash"]:
            raise ValueError("validation pairing mismatch")
    regressions = [a["verification"]["task_success"] and not b["verification"]["task_success"] for a, b in zip(before, after)]
    normal = sum(reg and a["truth_executable"] for reg, a in zip(regressions, before))
    stable = sum(regressions[changed_count:])
    passed = (normal == 0 and stable == 0 and not any(r["verification"]["actual_policy_violation"] for r in after)
              and sum(r["verification"]["task_success"] for r in after) >= sum(r["verification"]["task_success"] for r in before)
              and sum(r["decision_correct"] for r in decisions_after) >= sum(r["decision_correct"] for r in decisions_before))
    return {"passed": passed, "normal_regressions": normal, "stable_regressions": stable}


class ModelLedger:
    """Exact-identity cache, bounded task dispatch and inclusive invocation costs."""

    def __init__(self, root, protocol):
        self.root = Path(root)/"model-layer"; self.protocol = protocol
        self.cache = self.root/"cache"; self.cache.mkdir(parents=True, exist_ok=True)
        self.protocol_hash = fingerprint(protocol); self.limits = protocol["config"]["limits"]
        self.charged_tokens = protocol["prior_charged_tokens"]
        self.prior_seconds = protocol["prior_invocation_seconds"]
        self.retries = 0; self.session = None; self.invocation_start = None
        for path in self.cache.glob("*.json"):
            record = read(path)
            if record["result_hash"] != fingerprint(record["result"]) or record["identity"]["protocol_hash"] != self.protocol_hash or path.stem != fingerprint(record["identity"]):
                raise ValueError("model cache identity/integrity changed")
            self.charged_tokens += record["result"]["agent"]["metrics"]["tokens"]
        for path in (self.root/"failures").glob("*.json"):
            failure = read(path)
            self.charged_tokens += failure["reserved_tokens"]; self.retries += 1
        for start in (self.root/"invocations").glob("*.start.json"):
            final = start.with_name(start.name.replace(".start.json", ".final.json"))
            if not final.exists():
                raise RuntimeError("unreconciled prior invocation; inspect owned worker and resource ledger before resume")
            self.prior_seconds += read(final)["seconds"]

    def open(self):
        self.session = ExecutionAgentSession(self.root/"agents"/uuid.uuid4().hex, self.protocol["setup"])
        if self.session.settings != self.protocol["model_settings"]:
            self.session.close(); self.session = None
            raise ValueError("frozen model settings differ")

    def evaluate(self, spec, world, contract, patch, runtime, decision=False):
        identity = {"task_hash": fingerprint(spec), "world": world, "contract": fingerprint(contract), "patch": patch,
                    "runtime": runtime, "decision_only": decision, "protocol_hash": self.protocol_hash,
                    "model": fingerprint(self.protocol["model_settings"])}
        key = fingerprint(identity); target = self.cache/(key+".json")
        if target.exists():
            record = read(target)
            if record["identity"] != identity or record["result_hash"] != fingerprint(record["result"]):
                raise ValueError("cached evaluation differs")
            return record["result"], key
        reservation = (1 if decision else 16)*16384
        elapsed = time.perf_counter()-self.invocation_start
        if (self.charged_tokens+reservation > self.limits["shared_tokens"] or
                self.prior_seconds+elapsed+self.limits["task_wall_seconds"] > self.limits["shared_gpu_seconds"]):
            raise RuntimeError("shared A+B budget exhausted; preserve incomplete evaluation")
        previous_failures = list((self.root/"failures").glob(key+"-*.json"))
        if len(previous_failures) > self.limits["per_task_retries"] or self.retries > self.limits["global_infrastructure_retries"]:
            raise RuntimeError("infrastructure retry limit exhausted")
        attempt = len(previous_failures); start = time.perf_counter(); original_receive = self.session.receive
        def bounded_receive(timeout=120):
            remaining = min(self.limits["task_wall_seconds"]-(time.perf_counter()-start),
                            self.limits["shared_gpu_seconds"]-self.prior_seconds-(time.perf_counter()-self.invocation_start))
            if remaining <= 0:
                raise TimeoutError("frozen task/invocation time limit reached")
            return original_receive(min(timeout, remaining))
        self.session.receive = bounded_receive
        try:
            result = self.session.run(spec, world, contract, patch, decision, runtime)
        except BaseException as exc:
            elapsed = time.perf_counter()-start
            immutable_json(self.root/"failures"/(key+"-"+str(attempt)+".json"),
                {"identity": identity, "reserved_tokens": reservation, "seconds": elapsed, "error_type": type(exc).__name__})
            self.charged_tokens += reservation; self.retries += 1
            self.session.receive = original_receive
            if (not isinstance(exc, (RuntimeError, OSError, TimeoutError, queue.Empty)) or
                    attempt >= self.limits["per_task_retries"] or self.retries > self.limits["global_infrastructure_retries"]):
                raise
            self.session.close(); self.session = None; self.open()
            return self.evaluate(spec, world, contract, patch, runtime, decision)
        finally:
            if self.session is not None and self.session.receive is bounded_receive:
                self.session.receive = original_receive
        self.charged_tokens += result["agent"]["metrics"]["tokens"]
        immutable_json(target, {"identity": identity, "result": result, "result_hash": fingerprint(result)})
        print(json.dumps({"stage": "A-model-task", "runtime": runtime, "decision": decision,
                          "unique_cached": len(list(self.cache.glob('*.json'))), "charged_tokens_all_v11": self.charged_tokens}), flush=True)
        return result, key


def evaluate_group(ledger, dataset, directory, world, seed, boundary, agent_parents):
    directory = Path(directory); store = EvaluationStore(dataset)
    contract = read(Path(dataset)/"parent-skill.json")
    valid = store.read("model_validation"); stable_valid = store.read("model_stable_validation")
    common_parent, proposed = boundary["before"], boundary["effective"]
    patches = {runtime: {"old": common_parent, "proposal": proposed, "agent_parent": agent_parents[runtime]}
               for runtime in ("old", "new")}
    refs = []; admitted = {}; validation = {}
    def batch(specs, runtime, phase, decision=False):
        rows = []
        for spec in specs:
            row, key = ledger.evaluate(spec, world, contract, patches[runtime][phase], runtime, decision)
            rows.append(row); refs.append(key)
        return rows
    for runtime in ("old", "new"):
        before = batch(valid+stable_valid, runtime, "agent_parent")
        after = batch(valid+stable_valid, runtime, "proposal")
        before_d = batch(valid, runtime, "agent_parent", True); after_d = batch(valid, runtime, "proposal", True)
        gate = agent_admission(before, after, before_d, after_d, len(valid))
        nontrivial = different(contract, agent_parents[runtime], proposed, store.read("explore"))
        admitted[runtime] = boundary["boundary_admitted"] and nontrivial and gate["passed"]
        validation[runtime] = {**gate, "nontrivial": nontrivial, "agent_admitted": admitted[runtime],
                               "effective_patch": proposed if admitted[runtime] else agent_parents[runtime]}
    activation = {"protocol_hash": ledger.protocol_hash, "world": world, "seed": seed,
                  "boundary": {k: boundary[k] for k in ("belief_converged", "boundary_validation_passed", "boundary_admitted", "nontrivial")},
                  "canonical_parent": common_parent, "proposal": proposed, "actual_agent_parents": agent_parents,
                  "runtime_admission": validation, "validation_refs": refs.copy(), "scope": "isolated evaluation activation only"}
    freeze_record = {"candidate_hash": fingerprint(activation), "dataset_hash": fingerprint(store.manifest)}
    immutable_json(directory/"activation.json", activation); immutable_json(directory/"evaluation-freeze.json", freeze_record)
    test = store.read("model_test", activation, freeze_record); stable_test = store.read("model_stable_test", activation, freeze_record)
    tests = {}; decisions = {}
    for runtime in ("old", "new"):
        tests[runtime] = {phase: batch(test+stable_test, runtime, phase) for phase in ("old", "proposal", "agent_parent")}
        decisions[runtime] = {phase: batch(test, runtime, phase, True) for phase in ("old", "proposal", "agent_parent")}
    def eoc(rows):
        return sum(r["verification"]["task_success"] for r in rows)/len(rows)
    candidate_arms = {r+"_"+p: eoc(tests[r][p][:len(test)]) for r in ("old", "new") for p in ("old", "proposal")}
    effective_arms = {r+"_"+p: eoc(tests[r]["proposal" if p == "proposal" and admitted[r] else "agent_parent"][:len(test)])
                      for r in ("old", "new") for p in ("old", "proposal")}
    runtime_results = {}
    for runtime in ("old", "new"):
        a = tests[runtime]["agent_parent"]; b = tests[runtime]["proposal" if admitted[runtime] else "agent_parent"]
        da = decisions[runtime]["agent_parent"]; db = decisions[runtime]["proposal" if admitted[runtime] else "agent_parent"]
        runtime_results[runtime] = {"before_new_eoc": eoc(a[:len(test)]), "after_new_eoc": eoc(b[:len(test)]),
            "stable_regressions": sum(x["verification"]["task_success"] and not y["verification"]["task_success"] for x,y in zip(a[len(test):],b[len(test):])),
            "normal_regressions": sum(x["truth_executable"] and x["verification"]["task_success"] and not y["verification"]["task_success"] for x,y in zip(a,b)),
            "actual_violations": sum(x["verification"]["actual_policy_violation"] for x in b),
            "attempted_violations": sum(x["verification"]["attempted_policy_violation"] for x in b),
            "before_decision_correct": sum(x["decision_correct"] for x in da), "after_decision_correct": sum(x["decision_correct"] for x in db),
            "decision_tasks": len(db),
            "before_decision_false_allow": sum(x["agent"]["decision"] is True and not x["truth_executable"] for x in da),
            "after_decision_false_allow": sum(x["agent"]["decision"] is True and not x["truth_executable"] for x in db),
            "before_decision_false_block": sum(x["agent"]["decision"] is False and x["truth_executable"] for x in da),
            "after_decision_false_block": sum(x["agent"]["decision"] is False and x["truth_executable"] for x in db),
            "before_decision_unknown": sum(x["agent"]["decision"] is None for x in da),
            "after_decision_unknown": sum(x["agent"]["decision"] is None for x in db),
            "before_tokens": sum(x["agent"]["metrics"]["tokens"] for x in a), "after_tokens": sum(x["agent"]["metrics"]["tokens"] for x in b),
            "before_tool_calls": sum(x["agent"]["metrics"]["tool_calls"] for x in a), "after_tool_calls": sum(x["agent"]["metrics"]["tool_calls"] for x in b),
            "before_llm_calls": sum(x["agent"]["metrics"]["llm_calls"] for x in a), "after_llm_calls": sum(x["agent"]["metrics"]["llm_calls"] for x in b),
            "before_seconds": sum(x["seconds"] for x in a), "after_seconds": sum(x["seconds"] for x in b),
            "agent_admitted": admitted[runtime], "effective_patch": validation[runtime]["effective_patch"]}
    result = {"world": world, "seed": seed, "complete": True, "candidate_arms": candidate_arms, "effective_arms": effective_arms,
              "boundary": activation["boundary"], "runtime_results": runtime_results,
              "runtime_assistance": paired_execution_metrics(tests["old"]["old"], tests["new"]["old"]),
              "refs": refs, "test_freeze": freeze_record, "scope": "candidate diagnostics and effective deployed-policy simulation reported separately"}
    immutable_json(directory/"report.json", result)
    print(json.dumps({"stage": "A-model-group", "world": world, "seed": seed, "admitted": admitted}), flush=True)
    return result


def run_models(root):
    root = Path(root); protocol = load(root); cpu = read(root/"cpu-report.json")
    if cpu["protocol_hash"] != fingerprint(protocol):
        raise ValueError("CPU protocol differs")
    ledger = ModelLedger(root, protocol); invocation_id = uuid.uuid4().hex
    ledger.invocation_start = time.perf_counter(); status = "incomplete"; independent = []; continuous = []
    immutable_json(ledger.root/"invocations"/(invocation_id+".start.json"), {"protocol_hash": fingerprint(protocol)})
    try:
        with GPUServiceLease():
            ledger.open()
            try:
                for row in cpu["independent"]:
                    world, seed = row["world"], row["seed"]
                    independent.append(evaluate_group(ledger, Path(protocol["data_root"])/world/str(seed),
                        root/"model-layer/independent"/world/str(seed), world, seed, row, {"old": H0, "new": H0}))
                parents = {"old": H0, "new": H0}; nodes = {"old": None, "new": None}
                for row in cpu["continuous"]:
                    epoch, world = row["epoch"], row["world"]; directory = root/"model-layer/continuous"/str(epoch)
                    report = evaluate_group(ledger, root/"continuous/datasets"/str(epoch), directory, world,
                                            protocol["config"]["continual"]["seed"], row, parents)
                    lineage = {}
                    for runtime in ("old", "new"):
                        node = {"epoch": epoch, "world": world, "runtime": runtime, "parent_node": nodes[runtime],
                                "before_patch": parents[runtime], "effective_patch": report["runtime_results"][runtime]["effective_patch"],
                                "accepted_update": report["runtime_results"][runtime]["agent_admitted"], "cpu_node_hash": fingerprint(row)}
                        lineage[runtime] = node; parents[runtime] = node["effective_patch"]; nodes[runtime] = fingerprint(node)
                    immutable_json(directory/"lineage.json", lineage); continuous.append({"epoch": epoch, **report})
            finally:
                if ledger.session is not None:
                    ledger.session.close()
        cohorts = {}
        for runtime in ("old", "new"):
            rows = [AdmissionEvidence(f"{r['world']}/{r['seed']}", "active", True, r["boundary"]["nontrivial"],
                r["boundary"]["belief_converged"], r["boundary"]["boundary_validation_passed"], True,
                r["runtime_results"][runtime]["agent_admitted"], r["runtime_results"][runtime]["agent_admitted"])
                for r in independent]
            cohorts[runtime] = admission_funnel(rows)
        factorial = {scope: paired_factorial([{**r, "bundle_scope": scope, "arms": r[scope+"_arms"]} for r in independent],
                                               seed=protocol["bootstrap"]["seed"], replicates=protocol["bootstrap"]["replicates"])
                     for scope in ("candidate", "effective")}
        immutable_json(root/"model-report.json", {"protocol_hash": fingerprint(protocol), "independent": independent,
            "continuous": continuous, "funnel": cohorts, "factorial": factorial,
            "charged_tokens_all_v11": ledger.charged_tokens,
            "scope": "A protocol only; independent world-seed inference excludes continuous epochs"})
        status = "complete"
    finally:
        immutable_json(ledger.root/"invocations"/(invocation_id+".final.json"), {"protocol_hash": fingerprint(protocol),
            "status": status, "seconds": time.perf_counter()-ledger.invocation_start,
            "charged_tokens_all_v11": ledger.charged_tokens, "infrastructure_failures": ledger.retries})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("freeze", "cpu", "models"))
    parser.add_argument("--root", type=Path, default=Path("results/active-evolution/v1.1/formal-A-v2"))
    parser.add_argument("--preparation", type=Path, default=Path("results/active-evolution/v1.1/preparation-A-v1"))
    parser.add_argument("--cost-root", type=Path, default=Path("results/active-evolution/v1.1/development/factorial-cost-v1"))
    args = parser.parse_args()
    if args.stage == "freeze":
        print(fingerprint(freeze(args.root, args.preparation, args.cost_root)))
    elif args.stage == "cpu":
        run_cpu(args.root)
    else:
        run_models(args.root)


if __name__ == "__main__":
    main()
