"""Bind the independently audited Stage 1 result and its exact retained catalog."""
import argparse
from pathlib import Path

from scripts.run_skill_evolution import ROOT, digest_file
from scripts.run_skill_evolution_rounds import audit, load_protocol, ResearchRegistry
from scripts.skill_evolution_release import hashed, relative
from scripts.continue_skill_evolution_selection import publish
from skillforge.skill_evolution.agent_evidence import read
from skillforge.evolution_schemas import fingerprint
from skillforge.evolution_common.artifacts import load_record


def freeze(root):
    root = Path(root).resolve()
    receipt = audit(root)
    protocol = load_protocol(root)
    report = read(root / "report.json")
    registry = ResearchRegistry(root / "r")
    snapshot, catalog = registry.load(report["selected_snapshot"])
    programs = []
    for entry in catalog.entries():
        registration = load_record(registry.root, "registrations", snapshot["registrations"][entry["revision"]])
        contract = entry["contract"]
        programs.append({"skill_id": entry["skill_id"], "revision": entry["revision"],
            "family": contract["family"], "boundary_revision": entry["boundary_revision"],
            "program_hash": fingerprint({key: contract[key] for key in ("inputs", "procedure", "postconditions")}),
            "registration_kind": registration["kind"],
            "new_program_admission_by_stage1": registration["kind"] == "formal_program"})
    manifest = hashed({"schema": "skill-evolution-stage1-freeze-v1", "run": relative(root),
        "protocol_hash": protocol["hash"], "independent_audit_hash": receipt["hash"],
        "report_hash": report["hash"], "selected_snapshot": report["selected_snapshot"],
        "catalog_hash": catalog.hash, "programs": programs, "implementation_sources": protocol["sources"],
        "runtime_sources": protocol["runtime_sources"], "settings": protocol["settings"],
        "catalog_file": relative(root / "stage1-catalog.json"),
        "completed_real_rounds": report["completed_real_rounds"], "test_arms": receipt["test_arms"],
        "new_candidates": sum(row["n_candidates"] for row in report["rounds"]),
        "program_admitted": report["program_admitted"], "agent_admitted": report["agent_admitted"],
        "isolated_activated": report["isolated_activated"], "deployed": False,
        "new_model_calls": 0, "new_tokens": 0, "shared_total_tokens": report["shared_total_tokens"],
        "scope": "scoped readonly three-round study completed; legacy programs retained; no new Skill benefit demonstrated",
        "unsupported": protocol["unsupported"],
        "stage2_execution_integration": "NOT_YET_VALIDATED: versioned business Boundary must integrate without program or immutable Guard changes",
        "freeze_controller_sha256": digest_file(__file__)})
    catalog.save(root / "stage1-catalog.json")
    publish(root / "stage1-freeze.json", manifest)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    args = parser.parse_args()
    value = freeze(args.run)
    print({key: value[key] for key in ("hash", "catalog_hash", "completed_real_rounds", "new_candidates")})
