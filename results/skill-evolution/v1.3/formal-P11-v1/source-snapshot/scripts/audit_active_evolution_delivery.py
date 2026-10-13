"""Read-only delivery audit added after protocol freeze; never supplies labels to learners."""
import argparse
import json
from pathlib import Path

from scripts.active_evolution_dataset import EvaluationStore, public_candidate, state_for_policy
from scripts.active_evolution_formal import load_protocol
from scripts.active_evolution_model_benchmark import admission, metrics
from scripts.active_evolution_worlds import policy
from scripts.prepare_active_evolution import file_hash
from skillforge.active_agent.policy_view import bundle
from skillforge.evolution_metrics import retention
from skillforge.evolution_registry import immutable_json
from skillforge.evolution_schemas import Hypothesis, fingerprint
from skillforge.schemas import ExpectedOutcome, Task
import skillforge.verifier as verifier


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def audit_continuous(root, protocol):
    report = read(root / "continuous-report.json")
    require(report["protocol_hash"] == fingerprint(protocol), "continuous protocol mismatch")
    methods = protocol["config"]["methods"]
    h0 = Hypothesis(hypothesis_id="H0", kind="no_change").model_dump(mode="json")
    previous = {m: h0 for m in methods}
    parents = {}
    recomputed = []
    for epoch, world in enumerate(protocol["continuous_epochs"]["worlds"], 1):
        store = EvaluationStore(root / "continuous/datasets" / str(epoch))
        contract = read(store.root / "parent-skill.json")
        for method in methods:
            directory = root / "continuous" / str(epoch) / method
            node = read(directory / "lineage.json")
            require((node["epoch"], node["world"], node["method"]) == (epoch, world, method),
                    "continuous node identity mismatch")
            require(node["learning_status"] == read(directory / "learning/summary.json")["status"],
                    "continuous learning status mismatch")
            expected_parent = parents.get(method, bundle(contract, h0, "original-public-policy")["revision"])
            require(node["parent_revision"] == expected_parent, "lineage parent mismatch")
            require(node["previous_hypothesis"] == previous[method], "lineage prior patch mismatch")
            require(node["bundle"] == bundle(contract, node["effective_hypothesis"],
                    store.manifest["policy_epoch"], expected_parent), "bundle revision mismatch")
            proposal = read(directory / "learning/effective-version.json")["effective_hypothesis"]
            valid = node["validation"]
            changed = [r for r in valid if r["split"] == "validation"]
            stable = [r for r in valid if r["split"] == "stable_validation"]
            safe = (not any(r["prediction"] and not r["truth"] for r in changed)
                    and sum(r["truth"] and not r["prediction"] for r in changed)
                    <= sum(r["truth"] and not r["baseline_prediction"] for r in changed)
                    and not any(r["actual_violations"] for r in valid)
                    and retention(stable)["regression_rate"] <= .05)
            accepted = node["learning_status"] == "VERIFIED" and safe
            require(node["accepted_update"] == accepted, "continuous admission mismatch")
            require(node["effective_hypothesis"] == (proposal if accepted else previous[method]),
                    "rejected proposal replaced prior bundle")
            freeze = read(directory / "evaluation-freeze.json")
            test = read(directory / "test.json")
            require(test["freeze"] == freeze, "continuous test freeze mismatch")
            before = Hypothesis.model_validate(previous[method])
            after = Hypothesis.model_validate(node["effective_hypothesis"])
            for rows, splits, patch in [(valid, ("validation", "stable_validation"),
                                        Hypothesis.model_validate(proposal)),
                                       (test["cases"], ("test", "stable_test"), after)]:
                specs = {s["task_id"]: s for split in splits for s in store.read(split, node, freeze)}
                require(len(rows) == len(specs) and {r["task_id"] for r in rows} == set(specs),
                        "continuous case coverage mismatch")
                for row in rows:
                    spec = specs[row["task_id"]]
                    public = public_candidate(spec, contract)
                    args = (public.observations, public.baseline_prediction, public.guard_prediction)
                    probe = read(directory / "admission/private-probes" / (spec["task_id"] + ".json"))
                    require(fingerprint(probe["result"]) == probe["result_hash"] == row["probe_hash"],
                            "continuous probe hash mismatch")
                    require(row["task_hash"] == fingerprint(spec) == probe["identity"]["task_hash"],
                            "continuous task binding mismatch")
                    truth = policy(world, "issue_refund", state_for_policy(spec), spec["parameters"]) == "allow"
                    require(row["truth"] == truth == probe["result"]["procedure_success"], "continuous truth mismatch")
                    require(row["baseline_prediction"] == before.predict(*args)
                            and row["prediction"] == patch.predict(*args), "continuous prediction mismatch")
                    require(row["actual_violations"] == probe["result"]["actual_violations"], "continuous safety mismatch")
                    if "stable" in row["split"] and epoch > 1:
                        prior_world = protocol["continuous_epochs"]["worlds"][epoch - 2]
                        require(truth == (policy(prior_world, "issue_refund", state_for_policy(spec), spec["parameters"]) == "allow"),
                                "changed policy case included in stable retention")
            cases = test["cases"]
            changed = [r for r in cases if r["split"] == "test"]
            retained = retention([r for r in cases if r["split"] == "stable_test"])
            expected = {"epoch": epoch, "world": world, "method": method, "accepted_update": accepted,
                        "revision": node["bundle"]["revision"], "parent_revision": expected_parent,
                        "queries": read(directory / "learning/summary.json")["queries"],
                        "before_correct": sum(r["baseline_prediction"] == r["truth"] for r in changed),
                        "after_correct": sum(r["prediction"] == r["truth"] for r in changed),
                        "false_allow": sum(r["prediction"] and not r["truth"] for r in cases),
                        "false_block": sum(not r["prediction"] and r["truth"] for r in cases),
                        "actual_violations": sum(r["actual_violations"] for r in cases),
                        "retention": retained, "negative_transfer_count": retained["regression_count"]}
            require(test["metrics"] == expected, "continuous metrics mismatch")
            recomputed.append(expected)
            previous[method] = node["effective_hypothesis"]
            parents[method] = node["bundle"]["revision"]
    require(report["epochs"] == recomputed, "continuous report coverage/metrics mismatch")
    return {"epoch_method_runs": len(recomputed), "accepted_updates": sum(r["accepted_update"] for r in recomputed)}


def checked_cache(cache, key, expected_identity):
    record = read(cache / (key + ".json"))
    require(key == fingerprint(expected_identity) and record["identity"] == expected_identity,
            "model task/bundle pairing mismatch")
    require(record["result_hash"] == fingerprint(record["result"]), "model evidence hash mismatch")
    result = record["result"]
    require(result["spec_hash"] == expected_identity["task_hash"]
            and result["decision_only"] == expected_identity["decision_only"], "model result identity mismatch")
    require(result["decision_correct"] == (result["agent"]["decision"] is result["truth_executable"]),
            "model Decision metric mismatch")
    return result


def audit_model_outcome(result, spec, world):
    initial, final = result["initial_state"], result["final_state"]
    tool = "update_shipping_address" if spec["family"] == "modify_address" else "issue_refund"
    gold = policy(world, tool, initial, spec["parameters"])
    require(result["truth_executable"] == (gold == "allow"), "model truth mismatch")
    expected_state = {}
    if gold == "allow":
        expected_state = ({"order.shipping_address": spec["parameters"]["new_address"]}
                          if spec["family"] == "modify_address" else
                          {"payment.refunded_amount": initial["payment.refunded_amount"] + spec["parameters"]["amount"]})
    task = Task(task_id=spec["task_id"], family=spec["family"], request=spec["request"],
                customer_id=spec["fixture"]["customer_id"], parameters=spec["parameters"], split="validation",
                template_id=spec["template"], seed=0,
                expected=ExpectedOutcome(allowed_outcomes=[{"allow": "completed", "refuse": "refused", "escalate": "escalated"}[gold]],
                                         expected_state=expected_state))
    original = verifier.eligibility
    try:
        verifier.eligibility = lambda name, state, args: policy(world, name, state, args)
        require(result["verification"] == verifier.verify(task, initial, final, result["tool_audit"], result["agent"]["outcome"]),
                "model EOC/safety evidence mismatch")
    finally:
        verifier.eligibility = original


def audit_models(root, protocol):
    report = read(root / "model-report.json")
    require(report["protocol_hash"] == fingerprint(protocol), "model report protocol mismatch")
    config = protocol["config"]
    output = root / "model-layer"
    h0 = Hypothesis(hypothesis_id="H0", kind="no_change").model_dump(mode="json")
    states = {m: h0 for m in config["methods"]}
    jobs = []
    for world in config["model_layer"]["worlds"]:
        seed = config["model_layer"]["paired_seed"]
        for method in config["methods"]:
            jobs.append(("independent", world, method, Path(protocol["data_root"]) / world / str(seed),
                         output / "independent" / world / method,
                         read(root / "cpu" / world / str(seed) / method / "effective-version.json")["effective_hypothesis"]))
    for epoch, world in enumerate(protocol["continuous_epochs"]["worlds"], 1):
        for method in config["methods"]:
            jobs.append(("epoch-" + str(epoch), world, method, root / "continuous/datasets" / str(epoch),
                         output / "continuous" / str(epoch) / method,
                         read(root / "continuous" / str(epoch) / method / "lineage.json")["effective_hypothesis"]))
    require(len(report["runs"]) == len(jobs), "model matrix incomplete")
    seen = set()
    for (stage, world, method, dataset, directory, proposal), row in zip(jobs, report["runs"]):
        store = EvaluationStore(dataset)
        contract = read(dataset / "parent-skill.json")
        activation = read(directory / "activation.json")
        freeze = read(directory / "freeze.json")
        require(row == read(directory / "report.json") and (row["stage"], row["world"], row["method"]) == (stage, world, method),
                "model report order/identity mismatch")
        before_patch = h0 if stage == "independent" else states[method]
        require(activation["before_patch"] == row["before_patch"] == before_patch
                and activation["proposal_patch"] == proposal, "Agent lineage mismatch")
        require(activation["protocol_hash"] == fingerprint(protocol), "Agent activation protocol mismatch")
        refs = iter(row["refs"])
        def batch(specs, patch, decision=False):
            values = []
            for spec in specs:
                key = next(refs, None)
                identity = {"task_hash": fingerprint(spec), "world": world, "contract": fingerprint(contract),
                            "patch": patch, "decision_only": decision, "protocol_hash": fingerprint(protocol),
                            "model": fingerprint(protocol["model_settings"])}
                require(key is not None, "missing model evidence reference")
                value = checked_cache(output / "cache", key, identity)
                audit_model_outcome(value, spec, world)
                values.append(value)
                seen.add(key)
            return values
        valid, stable = store.read("model_validation"), store.read("model_stable_validation")
        bv, av = batch(valid + stable, before_patch), batch(valid + stable, proposal)
        bd, ad = batch(valid, before_patch, True), batch(valid, proposal, True)
        require(activation["validation_refs"] == row["refs"][:2 * (len(valid) + len(stable)) + 2 * len(valid)],
                "activation validation references mismatch")
        admitted = admission(bv, av, bd, ad)
        effective = proposal if admitted else before_patch
        require(row["agent_admitted"] == activation["agent_admitted"] == admitted
                and row["effective_patch"] == activation["effective_patch"] == effective, "Agent admission mismatch")
        test = store.read("model_test", activation, freeze)
        stable_test = store.read("model_stable_test", activation, freeze)
        before, after = batch(test + stable_test, before_patch), batch(test + stable_test, effective)
        db, da = batch(test, before_patch, True), batch(test, effective, True)
        require(next(refs, None) is None, "extra model evidence references")
        require(row["before"] == metrics(before, db) and row["after"] == metrics(after, da), "Agent metric mismatch")
        regressions = sum(a["verification"]["task_success"] and not b["verification"]["task_success"]
                          for a, b in zip(before[len(test):], after[len(test):]))
        require(row["stable_cases"] == len(stable_test)
                and row["stable_regressions"] == row["negative_transfer_count"] == regressions, "Agent retention mismatch")
        if stage != "independent":
            states[method] = effective
    seconds = tokens = 0
    records = list((output / "cache").glob("*.json"))
    require({p.stem for p in records} == seen, "unreferenced or missing model cache result")
    for path in records:
        r = read(path)["result"]
        seconds += r["seconds"]
        tokens += r["agent"]["metrics"]["tokens"]
    attempts = list((output / "infrastructure-attempts").glob("*.json"))
    for path in attempts:
        r = read(path)
        seconds += r["seconds"]
        tokens += r["reserved_tokens"]
    require(abs(seconds - report["charged_gpu_task_seconds"]) < 1e-6
            and tokens == report["charged_tokens"], "resource accounting mismatch")
    require(seconds <= 12 * 3600 and tokens <= 20_000_000, "formal resource budget exceeded")
    require(len(attempts) <= protocol["cost_gate"]["global_retry_tasks"], "retry budget exceeded")
    return {"paired_runs": len(jobs), "unique_executions": len(seen), "infrastructure_attempts": len(attempts),
            "charged_gpu_task_seconds": seconds, "charged_tokens": tokens}


def audit(root):
    root = Path(root)
    protocol = load_protocol(root)
    cpu = read(root / "independent-audit.json")
    require(cpu["passed"] and cpu["protocol_hash"] == fingerprint(protocol), "CPU evidence audit missing")
    result = {"passed": True, "protocol_hash": fingerprint(protocol), "auditor_sha256": file_hash(__file__),
              "continuous": audit_continuous(root, protocol), "model": audit_models(root, protocol),
              "scope": "read-only lineage, evidence pairing, admission, metrics and charged-budget audit; no new model execution"}
    immutable_json(root / "delivery-audit.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="results/active-evolution/v1/formal-v1")
    print(json.dumps(audit(parser.parse_args().root)))
