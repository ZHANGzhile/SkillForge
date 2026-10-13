"""Raw DSL + public learner/EIG/RPC replay; no new sandbox/model invocation."""
import argparse
from pathlib import Path
import time

from scripts.run_skill_evolution import ROOT, digest_file
from scripts.skill_evolution_release import hashed
from scripts.continue_skill_evolution_selection import publish
from scripts.active_evolution_dataset import public_candidate, controlled_facts
from scripts.active_evolution_worlds import policy
from skillforge.skill_evolution.agent_evidence import read
from skillforge.evolution_schemas import Hypothesis, Candidate, EvidenceView, fingerprint
from skillforge.evolution_evidence import EvidenceBoundary
from skillforge.evolution_config import LearningOptions
from skillforge.active_learning import convergence_metrics
from skillforge.evolution_execution import execute_frozen
from skillforge.environment import ToolError
from skillforge.boundary_evolution.learner import learn_public
from skillforge.boundary_evolution.acquisition import ProbeOptions, METHODS


def checked(value):
    if value["hash"] != fingerprint({k: v for k, v in value.items() if k != "hash"}):
        raise ValueError("development artifact hash mismatch")
    return value


def replay_procedure(raw, spec, contract, world):
    index = 0
    def call(name, arguments, request_id):
        nonlocal index
        if index >= len(raw["tool_audit"]): raise ValueError("missing actual tool response")
        event = raw["tool_audit"][index]; index += 1
        if event["tool_name"] != name or event["arguments"] != arguments or event["request_id"] != request_id:
            raise ValueError("actual tool request differs from frozen DSL replay")
        if event.get("error"): raise ToolError(event["error"])
        return event["result"]
    execution, success = None, False
    try:
        execution = execute_frozen(contract, spec["parameters"], call, spec["task_id"], force_probe=True)
        success = execution["success"]
    except ToolError: pass
    violations = sum(bool(event["state_diff"]) and event["committed"] and event["tool_name"] in
        {"issue_refund", "update_shipping_address", "cancel_order"} and
        policy(world, event["tool_name"], event["before_state"], event["arguments"]) != "allow" for event in raw["tool_audit"])
    if index != len(raw["tool_audit"]) or execution != raw["execution"] or success != raw["procedure_success"] or violations != raw["actual_violations"]:
        raise ValueError("saved procedure success or violations differ from raw response replay")


def audit(root):
    root = Path(root).resolve(); started = time.perf_counter()
    protocol, report = checked(read(root / "protocol.json")), checked(read(root / "report.json"))
    for name, sha in protocol["sources"].items():
        if digest_file(ROOT / name) != sha or digest_file(root / "source-snapshot" / name) != sha:
            raise ValueError("registered current/archive development source mismatch")
    if list(METHODS) != protocol["methods"]: raise ValueError("method matrix changed")
    physical, runs = [], []
    for world in protocol["worlds"]:
        for seed in protocol["seeds"]:
            folder = root / world / str(seed)
            manifest, contract = read(folder / "dataset/manifest.json"), read(folder / "dataset/parent-skill.json")
            specs = {row["task_id"]: row for split in protocol["counts"] for row in read(folder / "dataset" / (split + ".json"))}
            if manifest["members"] != {key: {"hash": fingerprint(spec), "split": spec["split"]} for key, spec in specs.items()}:
                raise ValueError("base dataset membership changed")
            generated = {}
            for path in (folder / "generated-specs").glob("*.json"):
                value = read(path); spec = value["spec"]
                if spec["task_id"] in specs or spec["split"] != "explore": raise ValueError("generated source aliases another partition")
                if any(controlled_facts(spec).get(k) != v for k, v in value["request"]["factors"].items()):
                    raise ValueError("generated request/factors cannot describe actual sandbox task")
                generated[spec["task_id"]] = value; specs[spec["task_id"]] = spec
                manifest["members"][spec["task_id"]] = {"hash": fingerprint(spec), "split": "explore"}
            boundary = EvidenceBoundary(manifest)
            probes = {}
            for path in (folder / "private-probes").glob("*.json"):
                value = read(path); raw = value["result"]; spec = specs[path.stem]
                if value["result_hash"] != fingerprint(raw) or value["task_hash"] != fingerprint(spec):
                    raise ValueError("actual sandbox source receipt tampered")
                replay_procedure(raw, spec, contract, world)
                probes[path.stem] = raw
                physical.append({"world": world, "seed": seed, "task_id": path.stem,
                    "tool_calls": len(raw["tool_audit"]), "actual_violations": raw["actual_violations"]})
            def export(key):
                c = public_candidate(specs[key], contract)
                return boundary.export(probes[key], specs[key], c.baseline_prediction, c.guard_prediction)
            initial = [public_candidate(row, contract) for row in read(folder / "dataset/explore.json")]
            seed_views = [export(row["task_id"]) for row in read(folder / "dataset/seed.json")]
            for method in METHODS:
                local = folder / method
                packet = read(local / "public-packet.json")
                if (packet["seed_evidence"] != [v.model_dump(mode="json") for v in seed_views] or
                        packet["candidates"] != [c.model_dump(mode="json") for c in initial] or
                        packet["learning"] != protocol["learning"] or packet["probe_options"] != protocol["probe_options"] or packet["method"] != method):
                    raise ValueError("learner input differs from actual seed/pool or registered options")
                rpc_index = 0
                def rpc(expected):
                    nonlocal rpc_index
                    request = read(local / "rpc" / (str(rpc_index) + ".json"))
                    response = read(local / "rpc" / (str(rpc_index) + "-response.json"))
                    rpc_index += 1
                    if request != expected: raise ValueError("query/expansion differs from independent acquisition replay")
                    return response
                def probe(key):
                    if specs[key]["split"] != "explore": raise ValueError("learner accessed heldout")
                    response = rpc({"type": "probe", "candidate_id": key})
                    expected = export(key)
                    if response != expected.model_dump(mode="json"): raise ValueError("learner label differs from actual tool receipt")
                    return expected
                def expand(requests):
                    response = rpc({"type": "expand", "requests": requests})
                    values = [Candidate.model_validate(row) for row in response]
                    if len(values) != len(requests): raise ValueError("generated budget mismatch")
                    for req, c in zip(requests, values):
                        saved = generated[c.candidate_id]
                        if req["request_id"] != saved["request"]["request_id"] or req["factors"] != saved["request"]["factors"] or c != public_candidate(saved["spec"], contract):
                            raise ValueError("generated public query not bound to exact realized factors")
                    return values
                replayed = learn_public(method, [Hypothesis.model_validate(h) for h in packet["hypotheses"]], seed_views,
                    initial, probe, expand, learning=LearningOptions.model_validate(protocol["learning"]),
                    probe_options=ProbeOptions.model_validate(protocol["probe_options"]))
                expected = hashed({**replayed, "public_packet_hash": fingerprint(packet)})
                if read(local / "candidate-frozen.json") != expected or read(local / "rpc" / (str(rpc_index) + ".json")) != {"type": "completed", "result_hash": expected["hash"]}:
                    raise ValueError("candidate/Belief/EIG/stop differs from full raw replay")
                measured = []
                top, effective = Hypothesis.model_validate(expected["diagnostic_hypothesis"]), Hypothesis.model_validate(expected["effective_hypothesis"])
                for split in ("validation", "stable_validation"):
                    for spec in read(folder / "dataset" / (split + ".json")):
                        c = public_candidate(spec, contract); truth = probes[spec["task_id"]]["procedure_success"]
                        measured.append({"task_id": spec["task_id"], "split": split, "truth": truth,
                            "effective": effective.predict(c.observations, c.baseline_prediction, c.guard_prediction),
                            "diagnostic": top.predict(c.observations, c.baseline_prediction, c.guard_prediction), "parent": c.baseline_prediction})
                validation = hashed({"candidate_hash": expected["hash"], "cases": measured,
                    "false_allow": sum(r["effective"] is True and not r["truth"] for r in measured),
                    "false_block": sum(r["effective"] is False and r["truth"] for r in measured),
                    "diagnostic_errors": sum(r["diagnostic"] != r["truth"] for r in measured),
                    "stable_errors": sum(r["effective"] != r["truth"] for r in measured if r["split"] == "stable_validation")})
                if read(local / "dev-validation.json") != validation: raise ValueError("development outcome aggregate differs from raw validation receipts")
                qs = expected["queries"]
                runs.append({"world": world, "seed": seed, "method": method, "queries": len(qs),
                    "queries_to_convergence": expected["queries_to_convergence"], "belief_supported": expected["belief_supported"],
                    "stop_reason": expected["stop_reason"], "generated_candidates": expected["generated_candidates"],
                    **{k: validation[k] for k in ("false_allow", "false_block", "diagnostic_errors", "stable_errors")},
                    "broad_queries": sum(q["phase"] == "BROAD" for q in qs), "deep_queries": sum(q["phase"] == "DEEP" for q in qs),
                    "unknown_queries": sum(q["evidence"]["label"] == "unknown" for q in qs),
                    "uninformative_queries": sum(q["selected_eig"] < protocol["learning"]["min_information_gain"] for q in qs)})
    aggregate = {}
    for method in METHODS:
        selected = [row for row in runs if row["method"] == method]
        aggregate[method] = {**convergence_metrics(selected), **{key: sum(row[key] for row in selected) for key in
            ("false_allow", "false_block", "stable_errors", "diagnostic_errors", "generated_candidates", "queries", "broad_queries", "deep_queries", "unknown_queries", "uninformative_queries")}}
    base = aggregate["OriginalActive"]
    viable = [name for name in ("BroadOnly", "DeepOnly", "BroadThenDeep") if
        aggregate[name]["convergence_rate_within_budget"] > base["convergence_rate_within_budget"] and
        all(aggregate[name][key] <= base[key] for key in ("restricted_mean_queries_to_convergence", "false_allow", "false_block", "stable_errors"))]
    if any(row["actual_violations"] for row in physical): viable = []
    selected = min(viable, key=lambda name: (aggregate[name]["generated_candidates"], name)) if viable else "KEEP_EXISTING"
    if (report["runs"] != runs or report["methods"] != aggregate or report["selected"] != selected or
            report["physical_probes"] != len(physical) or report["physical_tool_calls"] != sum(p["tool_calls"] for p in physical) or
            report["logical_explore_queries"] != sum(row["queries"] for row in runs) or
            sorted(read(root / "physical-probes.json"), key=lambda r: (r["world"], r["seed"], r["task_id"])) != sorted(physical, key=lambda r: (r["world"], r["seed"], r["task_id"]))):
        raise ValueError("development matrix or selection differs from independently replayed evidence")
    receipt = hashed({"schema": "boundary-acquisition-dev-audit-v1", "passed": True,
        "protocol_hash": protocol["hash"], "report_hash": report["hash"], "replayed_runs": len(runs),
        "replayed_logical_queries": report["logical_explore_queries"], "replayed_actual_probes": len(physical),
        "selected": selected, "new_model_calls": 0, "new_tokens": 0, "new_tool_calls": 0,
        "audit_wall_seconds": time.perf_counter() - started, "audit_controller_sha256": digest_file(__file__)})
    publish(root / "independent-audit.json", receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--run", required=True)
    print(audit(parser.parse_args().run))
