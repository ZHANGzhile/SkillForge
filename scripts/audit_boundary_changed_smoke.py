"""Independent actual SQLite replay of learned/oracle-labelled dev arms."""
import argparse
from pathlib import Path

from scripts.run_skill_evolution import ROOT, digest_file
from scripts.skill_evolution_release import fixed_model
from scripts.continue_skill_evolution_selection import publish
from scripts.audit_boundary_stage2_arm import audit_arm
from skillforge.skill_evolution.agent_evidence import read
from skillforge.skill_evolution.catalog import Catalog
from skillforge.boundary_runtime.catalog import BoundaryCatalog, h0_bindings
from skillforge.boundary_runtime.runtime import runtime_sources
from skillforge.boundary_lineage.proposal import checked, hashed, propose
from skillforge.evolution_schemas import fingerprint


def audit(root):
    root = Path(root).resolve()
    p, r, settings = read(root / "protocol.json"), read(root / "report.json"), read(root / "model-identity.json")
    checked(p); checked(r); fixed_model(settings)
    if r["protocol_hash"] != p["hash"] or not r["complete"] or r["failure"]: raise ValueError("complete pinned dev run required")
    for name, sha in p["sources"].items():
        if digest_file(ROOT / name) != sha or digest_file(root / "source-snapshot" / name) != sha: raise ValueError("registered source changed")
    if settings["stage2_runtime_sources_hash"] != fingerprint(runtime_sources()): raise ValueError("actual worker Runtime identity differs")
    base = Catalog.load(root / "catalog.json")
    catalogs = {name: BoundaryCatalog(base.entries(), values) for name, values in p["catalogs"].items()}
    proposal = read(root / "proposal.json")
    if proposal != propose(catalogs["parent"], "refund_captured_payment", read(root / "learner-result.json")):
        raise ValueError("learned proposal differs from actual Bayes/public support replay")
    if proposal["candidate_bundle_hash"] != catalogs["learned_W1"].bundle_hash or proposal["hash"] != p["proposal_hash"]:
        raise ValueError("learned candidate identity mismatch")
    rows, statuses, indices, tokens, checkpoints = [], [], {}, 0, 0
    for i, case in enumerate(p["cases"]):
        catalog = catalogs[case["arm"]]
        if catalog.bundle_hash != case["bundle_hash"]: raise ValueError("planned Boundary mismatch")
        replay = audit_arm(root / str(i), case, catalog, settings, p["limits"],
            prior_tokens=p["prior_tokens"] + tokens, token_cap=p["prior_tokens"] + p["phase_tokens"],
            prior_wall=p["prior_wall_seconds"], wall_cap=p["prior_wall_seconds"] + p["phase_wall_seconds"])
        row, status = replay["row"], replay["status"]
        agent, verdict = row["agent"], row["verification"]
        rows.append({"task_id": case["task"]["task_id"], "arm": case["arm"], "scope": case["scope"],
            "eoc": verdict["task_success"], "outcome": agent["outcome"],
            "autonomous_eoc": verdict["task_success"] and not agent["interventions"]["runtime_intervention_count"],
            "runtime_assisted_eoc": verdict["task_success"] and bool(agent["interventions"]["runtime_intervention_count"]),
            "interventions": agent["interventions"], "attempted_violations": verdict["attempted_policy_violation"],
            "actual_violations": verdict["actual_policy_violation"], "tokens": status["charged_tokens"],
            "model_calls": agent["metrics"]["llm_calls"], "selected_skills": len(agent["skill_events"])})
        statuses.append(status); indices[str(i)] = replay["evidence_index"]
        tokens += status["charged_tokens"]; checkpoints += replay["replayed_checkpoints"]
    if (rows != r["rows"] or statuses != r["statuses"] or tokens != r["charged_tokens"] or
            r["shared_total_tokens"] != p["prior_tokens"] + tokens or tokens > p["phase_tokens"] or
            r["collection_wall_seconds"] > p["phase_wall_seconds"] or r["approved_unknown_requests"]):
        raise ValueError("aggregate/budget differs from full arm replay")
    publish(root / "independent-evidence-index.json", hashed({"arms": indices}))
    receipt = hashed({"schema": "stage2-changed-smoke-independent-audit-v1", "passed": True,
        "protocol_hash": p["hash"], "report_hash": r["hash"], "replayed_arms": len(rows), "replayed_checkpoints": checkpoints,
        "evidence_index_hash": fingerprint(indices), "new_model_calls": 0, "new_tokens": 0,
        "auditor_sources": {str(Path(name).as_posix()): digest_file(ROOT / name) for name in
            ["scripts/audit_boundary_changed_smoke.py", "scripts/audit_boundary_stage2_arm.py", "scripts/audit_boundary_runtime_smoke.py"]},
        "scope": "dev execution fidelity, not formal efficacy or automatic admission"})
    publish(root / "independent-audit.json", receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--run", required=True)
    print(audit(parser.parse_args().run))
