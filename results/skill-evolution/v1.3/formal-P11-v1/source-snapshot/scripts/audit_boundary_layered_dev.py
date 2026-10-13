"""Independent CPU DSL/public-support replay for all frozen proposal outcomes."""
import argparse
from pathlib import Path

from scripts.run_skill_evolution import ROOT, digest_file
from scripts.continue_skill_evolution_selection import publish
from scripts.audit_boundary_acquisition_dev import replay_procedure
from scripts.active_evolution_dataset import public_candidate, generate
from skillforge.skill_evolution.agent_evidence import read
from skillforge.skill_evolution.catalog import Catalog
from skillforge.boundary_runtime.catalog import BoundaryCatalog, h0_bindings
from skillforge.boundary_lineage.proposal import checked, hashed, propose, candidate_catalog
from skillforge.boundary_lineage.validation import declare_boundary_validation, boundary_gate
from skillforge.evolution_schemas import fingerprint


def audit(root):
    root = Path(root).resolve()
    protocol, report = read(root / "protocol.json"), read(root / "report.json")
    checked(protocol); checked(report)
    if report["protocol_hash"] != protocol["hash"] or not report["complete"]: raise ValueError("complete protocol-bound run required")
    for name, sha in protocol["sources"].items():
        if digest_file(ROOT / name) != sha or digest_file(root / "source-snapshot" / name) != sha: raise ValueError("registered source changed")
    base = Catalog.load(root / "catalog.json")
    parent = BoundaryCatalog(base.entries(), h0_bindings(base))
    rows, tool_calls, physical, index = [], 0, 0, {}
    for i, case in enumerate(protocol["planned"]):
        folder = root / str(i)
        result, saved = read(folder / "learner-result.json"), read(folder / "proposal.json")
        skill_id = "modify_unfulfilled_order_address" if case["world"] == "W6" else "refund_captured_payment"
        proposal = propose(parent, skill_id, result)
        if saved != proposal: raise ValueError("proposal differs from Bayes/support replay")
        summary = {**case, "proposal_hash": proposal["hash"], "proposal_decision": proposal["decision"],
            "certificate_status": proposal["certificate"]["status"], "boundary_gate": "NOT_EVALUATED", "agent_gate": "NOT_PLANNED",
            "boundary_admitted": False, "agent_admitted": False, "activated": False}
        if proposal["decision"] == "PROPOSE_BOUNDARY":
            candidate = candidate_catalog(parent, proposal)
            entry = base.get(skill_id, proposal["program_revision"])
            ordered_counts = {k: protocol["counts"][k] for k in ("validation", "stable_validation")}
            generated = generate(case["world"], case["validation_seed"], ordered_counts)
            specs = [s for split in ordered_counts for s in read(folder / "dataset" / (split + ".json"))]
            if specs != generated: raise ValueError("independent validation dataset differs from registered generation")
            members = [{"task_id": s["task_id"], "task_hash": fingerprint(s), "source_group": "p10-independent-dev-" + s["task_id"], "split": s["split"]} for s in specs]
            plan = declare_boundary_validation(parent, proposal, members)
            if plan != read(folder / "validation-plan.json"): raise ValueError("validation plan changed")
            cases = []
            for spec, member in zip(specs, members):
                path = folder / "private-probes" / (spec["task_id"] + ".json")
                raw = read(path)
                replay_procedure(raw, spec, entry["contract"], case["world"])
                c = public_candidate(spec, entry["contract"])
                errors = {e["error"] for e in raw["tool_audit"] if e["error"]}
                truth = True if raw["procedure_success"] else False if errors == {"business_rule_rejected"} else None
                old_gate = parent.effective_gate(entry["contract"], c.observations, spec["parameters"]).status
                new_gate = candidate.effective_gate(entry["contract"], c.observations, spec["parameters"]).status
                cases.append({**member, "probe_hash": fingerprint(raw), "truth": truth,
                    "parent": {"APPLICABLE": True, "INAPPLICABLE": False}.get(old_gate),
                    "candidate": {"APPLICABLE": True, "INAPPLICABLE": False}.get(new_gate), "actual_violations": raw["actual_violations"]})
                physical += 1; tool_calls += len(raw["tool_audit"])
                index[str(path.relative_to(root)).replace("\\", "/")] = digest_file(path)
            br = boundary_gate(plan, cases)
            if br != read(folder / "boundary-validation.json"): raise ValueError("Boundary gate differs from independent raw receipt replay")
            summary.update(boundary_gate=br["decision"], counts=br["counts"])
        rows.append(summary)
    if rows != report["rows"] or physical != report["physical_probes"] or tool_calls != report["physical_tool_calls"]:
        raise ValueError("aggregate differs from all planned independent validation units")
    publish(root / "independent-evidence-index.json", hashed({"files": index}))
    receipt = hashed({"schema": "boundary-layered-independent-dev-audit-v1", "passed": True,
        "protocol_hash": protocol["hash"], "report_hash": report["hash"], "replayed_proposals": len(rows),
        "replayed_probe_receipts": physical, "new_tool_calls": 0, "new_model_calls": 0, "new_tokens": 0,
        "evidence_index_hash": fingerprint(index), "auditor_sha256": digest_file(__file__),
        "scope": "saved response/DSL and arithmetic replay; collection source index establishes actual sandbox provenance"})
    publish(root / "independent-audit.json", receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--run", required=True)
    print(audit(parser.parse_args().run))
