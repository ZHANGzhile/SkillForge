"""Read-only full controller replay from saved actual sandbox responses.

No new sandbox/model calls. Publication is replaced by exact comparisons and
the source ledger becomes a read-only ownership checker. Only the audit receipt
is newly published after every planned transition has replayed successfully.
"""
import argparse
from pathlib import Path
import time
from unittest.mock import patch

from scripts import run_boundary_trial_cpu as controller
from scripts.boundary_trial_audits import replay_probe
from scripts.run_skill_evolution import digest_file
from scripts.continue_skill_evolution_selection import publish
from skillforge.skill_evolution.agent_evidence import read
from skillforge.evolution_common.artifacts import SplitLedger
from skillforge.boundary_lineage.proposal import checked, hashed
from skillforge.boundary_evolution.learner import learn_public
from skillforge.boundary_evolution.acquisition import ProbeOptions
from skillforge.boundary_trials.reference import learn_reference
from skillforge.evolution_schemas import fingerprint


def audit(root):
    root = Path(root).resolve(); started = time.perf_counter()
    report = read(root / "cpu/report.json"); checked(report)
    probes = {p.stem: p for p in (root / "cpu").glob("*/*/*/private-probes/*.json")}
    if len(probes) != report["physical_probes"]: raise ValueError("physical probe membership differs")
    count, source_ledger = 0, SplitLedger(controller.ROOT / "results/skill-evolution/v1.2/source-ledger")
    class ReadOnlyLedger:
        def __init__(self, root): pass
        def claim(self, group, split, *, related_groups=()):
            if any(source_ledger.owners.get(key) != split for key in (group, *related_groups)):
                raise ValueError("original source/entity split ownership missing")
    def actual(spec, world, contract):
        nonlocal count
        raw = read(probes[spec["task_id"]]); replay_probe(raw, spec, contract, world)
        count += 1
        return raw
    def compare(path, value):
        expected = read(path)
        if Path(path) == root / "cpu/report.json":
            value = {**value, "cpu_wall_seconds": expected["cpu_wall_seconds"]}
            value["hash"] = fingerprint({k: v for k, v in value.items() if k != "hash"})
        if value != expected: raise ValueError("controller publication differs at " + str(Path(path).relative_to(root)))
    def learner(folder, method, seeds, pool, hypotheses, probe, options, random_seed):
        packet = read(folder / "public-packet.json")
        expected_packet = {"output": str(folder.resolve()), "method": method, "random_seed": random_seed,
            "seed_evidence": [e.model_dump(mode="json") for e in seeds], "candidates": [c.model_dump(mode="json") for c in pool],
            "hypotheses": [h.model_dump(mode="json") for h in hypotheses], "learning": options.model_dump()}
        if packet != expected_packet: raise ValueError("public learner packet differs from actual seed/pool/controller")
        index = 0
        def query(key):
            nonlocal index
            request, response = read(folder / "rpc" / (str(index) + ".json")), read(folder / "rpc" / (str(index) + "-response.json"))
            index += 1
            if request != {"type": "probe", "candidate_id": key}: raise ValueError("query sequence differs from independent EIG replay")
            actual = probe(key)
            if actual.model_dump(mode="json") != response: raise ValueError("learner response differs from actual probe projection")
            return actual
        if method in {"OriginalActive", "ExistingActiveV2"}:
            def no_expansion(requests): raise ValueError("unselected acquisition expansion")
            result = learn_public(method, hypotheses, seeds, pool, query, no_expansion, learning=options, probe_options=ProbeOptions())
        else: result = learn_reference(method, hypotheses, seeds, pool, query, learning=options, random_seed=random_seed)
        frozen = hashed({**result, "public_packet_hash": fingerprint(packet)})
        if read(folder / "candidate-frozen.json") != frozen or read(folder / "rpc" / (str(index) + ".json")) != {"type": "completed", "result_hash": frozen["hash"]}:
            raise ValueError("candidate freeze differs from full public acquisition replay")
        return frozen
    exists = Path.exists
    def visible(path): return False if path == root / "cpu/report.json" else exists(path)
    with patch.object(Path, "exists", visible), patch.object(controller, "SplitLedger", ReadOnlyLedger), patch.object(controller, "publish", compare), \
            patch.object(controller, "actual_probe", actual), patch.object(controller, "isolated", learner), patch("builtins.print"):
        controller.run(root)
    if count != len(probes): raise ValueError("replayed probe count differs")
    receipt = hashed({"schema": "continuous-cpu-boundary-independent-audit-v1", "passed": True,
        "protocol_hash": report["protocol_hash"], "report_hash": report["hash"], "replayed_runs": len(report["runs"]),
        "replayed_actual_probe_receipts": count, "replayed_logical_queries": report["logical_queries"],
        "new_model_calls": 0, "new_tokens": 0, "new_tool_calls": 0, "audit_wall_seconds": time.perf_counter() - started,
        "auditor_sha256": digest_file(__file__), "scope": "full saved-response/DSL, trigger, Bayes/EIG, layered arithmetic and parent-chain replay; no new actual business tools"})
    publish(root / "cpu/independent-audit.json", receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--run", required=True)
    print(audit(parser.parse_args().run))
