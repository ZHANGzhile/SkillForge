"""Resume frozen collection after an auditor-only parse-failure repair.

Reuses exact complete physical arms, including failed model decisions. Does
not replay writes/inference, refill probe/token budgets, change model/runtime/
acquisition/gates, or overwrite the original partial report. Incomplete physical
arms remain unsupported. A source-bound continuation manifest is mandatory.
"""
import argparse
from pathlib import Path
import shutil
import time
from unittest.mock import patch

from scripts import run_boundary_trial_agent as frozen
from scripts.audit_boundary_stage2_arm_v2 import audit_arm as corrected_audit
from scripts.boundary_trial_audits import replay_probe
from scripts.continue_skill_evolution_selection import publish
from scripts.run_skill_evolution import ROOT, digest_file
from skillforge.skill_evolution.agent_evidence import read
from skillforge.boundary_lineage.proposal import checked, hashed
from skillforge.boundary_evolution.learner import learn_public
from skillforge.boundary_evolution.acquisition import ProbeOptions
from skillforge.evolution_schemas import fingerprint


def replay_learner(folder, method, seeds, pool, hypotheses, probe, options, random_seed):
    packet = read(folder / "public-packet.json")
    expected = {"output": str(folder.resolve()), "method": method, "random_seed": random_seed,
        "seed_evidence": [e.model_dump(mode="json") for e in seeds], "candidates": [c.model_dump(mode="json") for c in pool],
        "hypotheses": [h.model_dump(mode="json") for h in hypotheses], "learning": options.model_dump()}
    if packet != expected: raise ValueError("public learner resume identity differs")
    index = 0
    def query(key):
        nonlocal index
        req, response = read(folder / "rpc" / (str(index) + ".json")), read(folder / "rpc" / (str(index) + "-response.json"))
        index += 1
        if req != {"type": "probe", "candidate_id": key}: raise ValueError("acquisition resume differs from original frozen EIG")
        e = probe(key)
        if e.model_dump(mode="json") != response: raise ValueError("actual sandbox receipt differs from original learner response")
        return e
    def no_expansion(requests): raise ValueError("unselected acquisition")
    value = learn_public(method, hypotheses, seeds, pool, query, no_expansion, learning=options, probe_options=ProbeOptions())
    result = hashed({**value, "public_packet_hash": fingerprint(packet)})
    if result != read(folder / "candidate-frozen.json") or read(folder / "rpc" / (str(index) + ".json")) != {"type": "completed", "result_hash": result["hash"]}:
        raise ValueError("candidate resume differs from immutable learning evidence")
    return result


def run(root):
    root = Path(root).resolve(); output = root / "agent"; continuation = output / "continuation-v2"
    p, old = read(root / "protocol.json"), read(output / "report.json")
    checked(p); checked(old)
    if old["complete"] or old["protocol_hash"] != p["hash"] or continuation.exists():
        raise ValueError("one fresh continuation of this exact partial run only")
    for name, sha in p["sources"].items():
        if digest_file(ROOT / name) != sha or digest_file(root / "source-snapshot" / name) != sha:
            raise ValueError("frozen execution/proposer/model source changed")
    if old["failure"] != ["ValueError: checkpoint 16 differs: checkpoint.budget.used.tokens: 27331 != 14852"]:
        raise ValueError("only the diagnosed known-usage invalid Action audit interruption is authorized by this continuation")
    folders = sorted((output / "physical").glob("*"), key=lambda path: int(path.name))
    if [int(f.name) for f in folders] != list(range(len(folders))) or len(folders) != len(old["physical_statuses"]):
        raise ValueError("physical collection membership changed")
    original_index = {}
    for f, status in zip(folders, old["physical_statuses"]):
        if (not status["completed"] or status["failure"] or status["approved_unknown_requests"] or
                read(f / "collection-status.json") != status or not (f / "result.json").exists()):
            raise ValueError("incomplete/unknown physical work cannot be silently replayed")
        original_index.update({str(path.relative_to(root)).replace("\\", "/"): digest_file(path) for path in f.rglob("*") if path.is_file()})
    files = [Path(__file__), ROOT / "scripts/audit_boundary_stage2_arm_v2.py", ROOT / "scripts/audit_boundary_trial_agent_v2.py"]
    extension = hashed({"schema": "frozen-boundary-auditor-continuation-v1", "protocol_hash": p["hash"],
        "original_partial_report_hash": old["hash"], "original_partial_report_sha256": digest_file(output / "report.json"),
        "reused_physical_arms": len(folders), "prior_charged_tokens": old["charged_tokens"],
        "prior_collection_wall_seconds": old["collection_wall_seconds"], "original_evidence_index": original_index,
        "auditor_extensions": {str(f.relative_to(ROOT)).replace("\\", "/"): digest_file(f) for f in files},
        "change": "known-usage invalid Action output is replayed through the unchanged strict Action schema and remains model_error/EOC failure",
        "new_runtime": False, "new_model": False, "new_acquisition": False, "new_data": False, "new_gates": False,
        "budget_refill": False, "replay_completed_inference": False, "replay_completed_mutations": False})
    publish(continuation / "manifest.json", extension)
    for name in extension["auditor_extensions"]:
        path = continuation / "source-snapshot" / name; path.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(ROOT / name, path)
    probes = {path.stem: path for pattern in ("*/*/*/exploration-probes/*.json", "*/*/*/boundary-probes/*.json") for path in output.glob(pattern)}
    original_collect, original_probe, original_learner = frozen.collect, frozen.actual_probe, frozen.isolated
    def collect(session, folder, case, catalog, limits, **charge):
        if (folder / "collection-status.json").exists():
            context = read(folder / "charge-context.json")
            if case != read(folder / "case.json") or any(charge[k] != v for k, v in context.items()) or read(folder / "boundaries.json") != catalog.boundaries():
                raise ValueError("complete physical arm differs from resumed task/bundle/fee identity")
            return read(folder / "result.json"), read(folder / "collection-status.json")
        # Account for the first residency/collection interval without charging
        # its completed requests twice or resetting the original phase cap.
        charge["started"] -= old["collection_wall_seconds"]
        return original_collect(session, folder, case, catalog, limits, **charge)
    def actual(spec, world, contract):
        if spec["task_id"] in probes:
            value = read(probes[spec["task_id"]]); replay_probe(value, spec, contract, world)
            return value
        return original_probe(spec, world, contract)
    def learner(folder, *args):
        if (folder / "candidate-frozen.json").exists(): return replay_learner(folder, *args)
        return original_learner(folder, *args)
    def audit_arm(*args, **kwargs):
        value = corrected_audit(*args, **kwargs)
        value["evidence_index"].pop("independent-audit.json", None)
        return value
    def save(path, value):
        if Path(path) == output / "report.json":
            value = {**value, "collection_wall_seconds": value["collection_wall_seconds"] + old["collection_wall_seconds"]}
            value = hashed({k: v for k, v in value.items() if k != "hash"})
            publish(continuation / "report.json", value)
        else: publish(path, value)
    exists, mkdir = Path.exists, Path.mkdir
    def visible(path): return False if path == output else exists(path)
    def ensure(path, *args, **kwargs): return None if path == output else mkdir(path, *args, **kwargs)
    with patch.object(Path, "exists", visible), patch.object(Path, "mkdir", ensure), patch.object(frozen, "collect", collect), \
            patch.object(frozen, "actual_probe", actual), patch.object(frozen, "isolated", learner), \
            patch.object(frozen, "audit_arm", audit_arm), patch.object(frozen, "publish", save):
        frozen.run(root)
    result = read(continuation / "report.json"); checked(result)
    # Every original byte remains independently inspectable after continuation.
    if any(digest_file(root / name) != sha for name, sha in original_index.items()):
        raise ValueError("continuation changed original complete physical evidence")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--run", required=True)
    r = run(parser.parse_args().run); print({k: r[k] for k in ("complete", "failure", "charged_tokens", "shared_total_tokens")})
