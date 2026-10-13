"""New independent CPU Boundary validation of frozen dev learner proposals.

No Agent admission/activation; retains honest abstentions from every planned
world-seed. Exact public candidate freezes precede all independent validation.
"""
import argparse
from pathlib import Path
import shutil
import time

from scripts.run_skill_evolution import ROOT, digest_file
from scripts.skill_evolution_release import relative
from scripts.continue_skill_evolution_selection import publish
from scripts.active_evolution_dataset import write_dataset, public_candidate
from skillforge.skill_evolution.agent_evidence import read
from skillforge.skill_evolution.catalog import Catalog
from skillforge.boundary_runtime.catalog import BoundaryCatalog, h0_bindings
from skillforge.boundary_lineage.proposal import checked, hashed, propose, candidate_catalog
from skillforge.boundary_lineage.validation import declare_boundary_validation, boundary_gate
from skillforge.evolution_evidence import EvidenceBoundary
from skillforge.evolution_schemas import fingerprint
from skillforge.evolution_common.artifacts import SplitLedger
from skillforge.sandbox_probe import run_probe


def run(output):
    output = Path(output).resolve()
    if output.exists(): raise ValueError("fresh independent validation root required")
    old = ROOT / "results/skill-evolution/v1.2/development/p7-acquisition-ablation-20261012"
    stage1 = ROOT / "results/skill-evolution/v1.2/formal-P5-v1"
    report, audit = read(old / "report.json"), read(old / "independent-audit.json")
    checked(report); checked(audit)
    if not audit["passed"] or audit["report_hash"] != report["hash"] or report["selected"] != "KEEP_EXISTING":
        raise ValueError("frozen acquisition decision required")
    base = Catalog.load(stage1 / "stage1-catalog.json")
    parent = BoundaryCatalog(base.entries(), h0_bindings(base))
    planned = [{"world": w, "learner_seed": s, "validation_seed": 2026101290 + i * 2 + j}
        for i, w in enumerate(("W1", "W5", "W6")) for j, s in enumerate((2026101241, 2026101242))]
    sources = {relative(p): digest_file(p) for p in [Path(__file__),
        *ROOT.glob("skillforge/boundary_lineage/*.py"), ROOT / "scripts/active_evolution_dataset.py",
        ROOT / "scripts/active_evolution_worlds.py", ROOT / "skillforge/sandbox_probe.py", ROOT / "skillforge/evolution_evidence.py",
        ROOT / "skillforge/evolution_execution.py", ROOT / "skillforge/boundary_runtime/catalog.py"]}
    protocol = hashed({"schema": "boundary-layered-independent-dev-v1", "planned": planned, "sources": sources,
        "catalog_hash": base.hash, "parent_bundle_hash": parent.bundle_hash, "acquisition_report_hash": report["hash"],
        "method": "ExistingActiveV2", "counts": {"validation": 60, "stable_validation": 16},
        "new_model_calls": 0, "new_tokens": 0, "scope": "CPU development validation only; no Agent admission or formal research claim"})
    publish(output / "protocol.json", protocol); base.save(output / "catalog.json")
    for name in sources:
        target = output / "source-snapshot" / name; target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(ROOT / name, target)
    ledger = SplitLedger(ROOT / "results/skill-evolution/v1.2/source-ledger")
    frozen = []
    # Freeze every proposal (including abstention) before opening any validation.
    for i, case in enumerate(planned):
        result = read(old / case["world"] / str(case["learner_seed"]) / "ExistingActiveV2/candidate-frozen.json")
        skill_id = "modify_unfulfilled_order_address" if case["world"] == "W6" else "refund_captured_payment"
        proposal = propose(parent, skill_id, result)
        folder = output / str(i)
        publish(folder / "learner-result.json", result); publish(folder / "proposal.json", proposal)
        frozen.append((case, folder, proposal))
    started, rows, tool_calls, physical = time.perf_counter(), [], 0, 0
    for case, folder, proposal in frozen:
        summary = {**case, "proposal_hash": proposal["hash"], "proposal_decision": proposal["decision"],
            "certificate_status": proposal["certificate"]["status"], "boundary_gate": "NOT_EVALUATED", "agent_gate": "NOT_PLANNED",
            "boundary_admitted": False, "agent_admitted": False, "activated": False}
        if proposal["decision"] == "PROPOSE_BOUNDARY":
            candidate = candidate_catalog(parent, proposal)
            entry = base.get(proposal["skill_id"], proposal["program_revision"])
            write_dataset(folder / "dataset", case["world"], case["validation_seed"], protocol["counts"], entry["contract"])
            specs = [s for split in protocol["counts"] for s in read(folder / "dataset" / (split + ".json"))]
            members = []
            for spec in specs:
                group = "p10-independent-dev-" + spec["task_id"]
                ledger.claim(group, "dev", related_groups=[spec["task_id"], spec["parameters"]["order_id"], spec["fixture"]["customer_id"]])
                members.append({"task_id": spec["task_id"], "task_hash": fingerprint(spec), "source_group": group, "split": spec["split"]})
            plan = declare_boundary_validation(parent, proposal, members); publish(folder / "validation-plan.json", plan)
            boundary = EvidenceBoundary({"members": {s["task_id"]: {"hash": fingerprint(s), "split": s["split"]} for s in specs}})
            cases = []
            for spec, member in zip(specs, members):
                raw = run_probe(spec, case["world"], contract=entry["contract"])
                publish(folder / "private-probes" / (spec["task_id"] + ".json"), raw)
                c = public_candidate(spec, entry["contract"])
                # EvidenceBoundary's public learner view disallows validation;
                # independent validator reads the actual probe, not learner IPC.
                errors = {e["error"] for e in raw["tool_audit"] if e["error"]}
                truth = True if raw["procedure_success"] else False if errors == {"business_rule_rejected"} else None
                # Successful execution of a forced immutable Guard refusal is
                # not a mutation success. procedure_success in legacy executor
                # already separates it; ambiguous failures remain UNKNOWN.
                old_gate = parent.effective_gate(entry["contract"], c.observations, spec["parameters"]).status
                new_gate = candidate.effective_gate(entry["contract"], c.observations, spec["parameters"]).status
                cases.append({**member, "probe_hash": fingerprint(raw), "truth": truth,
                    "parent": {"APPLICABLE": True, "INAPPLICABLE": False}.get(old_gate),
                    "candidate": {"APPLICABLE": True, "INAPPLICABLE": False}.get(new_gate),
                    "actual_violations": raw["actual_violations"]})
                tool_calls += len(raw["tool_audit"]); physical += 1
            br = boundary_gate(plan, cases); publish(folder / "boundary-validation.json", br)
            summary.update(boundary_gate=br["decision"], counts=br["counts"])
        rows.append(summary); print(summary, flush=True)
    result = hashed({"schema": "boundary-layered-independent-dev-results-v1", "protocol_hash": protocol["hash"],
        "complete": True, "rows": rows, "physical_probes": physical, "physical_tool_calls": tool_calls,
        "cpu_wall_seconds": time.perf_counter() - started, "new_model_calls": 0, "new_tokens": 0,
        "agent_admitted": False, "activated": False, "scope": protocol["scope"]})
    publish(output / "report.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--output", required=True)
    print(run(parser.parse_args().output))
