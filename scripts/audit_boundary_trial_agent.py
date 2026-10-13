"""Full read-only real Agent controller replay, with fresh SQLite per physical arm."""
import argparse
from contextlib import nullcontext
from pathlib import Path
import time
from unittest.mock import patch

from scripts import run_boundary_trial_agent as controller
from scripts.audit_boundary_stage2_arm import audit_arm
from scripts.boundary_trial_audits import replay_probe
from scripts.continue_skill_evolution_selection import publish
from scripts.run_skill_evolution import digest_file
from scripts.skill_evolution_release import fixed_model
from skillforge.skill_evolution.agent_evidence import read
from skillforge.boundary_lineage.proposal import checked, hashed
from skillforge.boundary_evolution.learner import learn_public
from skillforge.boundary_evolution.acquisition import ProbeOptions
from skillforge.evolution_schemas import fingerprint


def audit(root):
    root = Path(root).resolve(); output = root / "agent"; started = time.perf_counter()
    report, protocol, settings = read(output / "report.json"), read(root / "protocol.json"), read(output / "model-identity.json")
    checked(report); checked(protocol); fixed_model(settings)
    if not report["complete"] or report["failure"] or report["protocol_hash"] != protocol["hash"]:
        raise ValueError("incomplete Agent studies remain charged, cannot certify completion")
    for name, sha in protocol["sources"].items():
        if digest_file(controller.ROOT / name) != sha or digest_file(root / "source-snapshot" / name) != sha:
            raise ValueError("registered current/archived source changed")
    probes = {p.stem: p for pattern in ("*/*/*/exploration-probes/*.json", "*/*/*/boundary-probes/*.json") for p in output.glob(pattern)}
    replayed, raw_indices, physical_calls, requests = 0, {}, 0, 0
    class RecordedSession:
        def __init__(self, folder): self.settings = settings
        def close(self): pass
    def collect(session, folder, case, catalog, limits, **charge):
        nonlocal replayed, physical_calls, requests
        planned, context = read(folder / "case.json"), read(folder / "charge-context.json")
        if case != planned or {k: charge[k] for k in context} != context or read(folder / "boundaries.json") != catalog.boundaries():
            raise ValueError("physical arm plan/charge/bundle differs from controller replay")
        row, status = read(folder / "result.json"), read(folder / "collection-status.json")
        replayed += 1; physical_calls += len(row["tool_audit"]); requests += status["charged_model_requests"]
        return row, status
    def actual_audit(folder, case, catalog, model_settings, limits, **charge):
        replay = audit_arm(folder, case, catalog, model_settings, limits, **charge)
        # This receipt was published only after collection's initial arm audit.
        # It must not recursively enter its own original raw-evidence index.
        replay["evidence_index"].pop("independent-audit.json", None)
        raw_indices[str(folder.relative_to(root)).replace("\\", "/")] = replay["evidence_index"]
        return replay
    def actual(spec, world, contract):
        raw = read(probes[spec["task_id"]]); replay_probe(raw, spec, contract, world)
        return raw
    def learner(folder, method, seeds, pool, hypotheses, probe, options, random_seed):
        packet = read(folder / "public-packet.json")
        expected = {"output": str(folder.resolve()), "method": method, "random_seed": random_seed,
            "seed_evidence": [e.model_dump(mode="json") for e in seeds], "candidates": [c.model_dump(mode="json") for c in pool],
            "hypotheses": [h.model_dump(mode="json") for h in hypotheses], "learning": options.model_dump()}
        if packet != expected: raise ValueError("learner packet differs from actual real daily evidence")
        index = 0
        def query(key):
            nonlocal index
            request, response = read(folder / "rpc" / (str(index) + ".json")), read(folder / "rpc" / (str(index) + "-response.json"))
            index += 1
            if request != {"type": "probe", "candidate_id": key}: raise ValueError("query differs from independent acquisition replay")
            e = probe(key)
            if e.model_dump(mode="json") != response: raise ValueError("query label differs from actual sandbox tool receipt")
            return e
        def no_expansion(requests): raise ValueError("unselected acquisition candidate")
        result = learn_public(method, hypotheses, seeds, pool, query, no_expansion, learning=options, probe_options=ProbeOptions())
        frozen = hashed({**result, "public_packet_hash": fingerprint(packet)})
        if read(folder / "candidate-frozen.json") != frozen or read(folder / "rpc" / (str(index) + ".json")) != {"type": "completed", "result_hash": frozen["hash"]}:
            raise ValueError("candidate differs from full Bayes/EIG/stop replay")
        return frozen
    def compare(path, value):
        expected = read(path)
        if Path(path) == output / "report.json":
            value = {**value, "collection_wall_seconds": expected["collection_wall_seconds"]}
            value["hash"] = fingerprint({k: v for k, v in value.items() if k != "hash"})
        if value != expected: raise ValueError("controller output differs at " + str(Path(path).relative_to(root)))
    exists, mkdir = Path.exists, Path.mkdir
    def visible(path): return False if path == output else exists(path)
    def ensure(path, *args, **kwargs):
        if path == output: return None
        return mkdir(path, *args, **kwargs)
    with patch.object(Path, "exists", visible), patch.object(Path, "mkdir", ensure), patch.object(controller, "BoundarySession", RecordedSession), \
            patch("scripts.execution_aware_gpu_lease.GPUServiceLease", lambda: nullcontext()), patch.object(controller, "collect", collect), \
            patch.object(controller, "audit_arm", actual_audit), patch.object(controller, "actual_probe", actual), \
            patch.object(controller, "isolated", learner), patch.object(controller, "publish", compare), patch("builtins.print"):
        controller.run(root)
    if replayed != len(report["physical_statuses"]) or replayed != len(raw_indices): raise ValueError("physical arm reuse/coverage mismatch")
    if report["charged_tokens"] > protocol["phase_tokens"] or report["shared_total_tokens"] != protocol["prior_tokens"] + report["charged_tokens"]:
        raise ValueError("global token ledger mismatch")
    if report["collection_wall_seconds"] > protocol["phase_wall_seconds"]: raise ValueError("registered collection wall cap exceeded")
    publish(output / "independent-evidence-index.json", hashed({"arms": raw_indices}))
    receipt = hashed({"schema": "continuous-real-agent-independent-audit-v1", "passed": True,
        "protocol_hash": protocol["hash"], "report_hash": report["hash"], "physical_arms": replayed,
        "logical_arms": len(report["logical_arms"]), "completed_stages": len(report["stages"]),
        "charged_model_requests": requests, "replayed_actual_tool_calls": physical_calls,
        "new_model_calls": 0, "new_tokens": 0, "evidence_index_hash": fingerprint(raw_indices),
        "audit_wall_seconds": time.perf_counter() - started, "auditor_sha256": digest_file(__file__),
        "scope": "real action-to-tool causality, SQLite/Receipt/checkpoint/fees, public drift, acquisition, independent layered gates and true effective parent replay"})
    publish(output / "independent-audit.json", receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--run", required=True)
    print(audit(parser.parse_args().run))
