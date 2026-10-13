"""Predeclared learned W1 / oracle-labelled W6 interface dev cost smoke.

W1 uses a previously frozen, independently audited actual acquisition result.
W6 is ONLY an explicitly declared interface relaxation diagnostic, not learning.
No admission, activation, formal claim or model training is performed.
"""
import argparse
from contextlib import ExitStack
from pathlib import Path
import shutil
import time

from scripts.run_skill_evolution import ROOT, digest_file
from scripts.skill_evolution_release import relative
from scripts.continue_skill_evolution_selection import publish
from scripts.collect_boundary_stage2 import BoundarySession, collect
from scripts.boundary_stage2_evaluator import expected_task
from skillforge.skill_evolution.agent_evidence import read
from skillforge.skill_evolution.catalog import Catalog
from skillforge.boundary_runtime.catalog import BoundaryCatalog, h0_bindings
from skillforge.boundary_runtime.runtime import runtime_sources, PROTOCOL
from skillforge.boundary_lineage.proposal import propose, candidate_catalog, hashed, checked
from skillforge.evolution_common.artifacts import SplitLedger
from skillforge.evolution_schemas import fingerprint


def run(output):
    from scripts.execution_aware_gpu_lease import GPUServiceLease
    output = Path(output).resolve()
    if output.exists(): raise ValueError("fresh root required; interrupted arms remain charged")
    stage1 = ROOT / "results/skill-evolution/v1.2/formal-P5-v1"
    h0root = ROOT / "results/skill-evolution/v1.2/development/p6-real-runtime-smoke-20261012"
    dev = ROOT / "results/skill-evolution/v1.2/development/p7-acquisition-ablation-20261012"
    prior, prior_protocol, audit = read(h0root / "report.json"), read(h0root / "protocol.json"), read(h0root / "independent-audit.json")
    checked(prior); checked(audit)
    if not audit["passed"] or audit["report_hash"] != prior["hash"]: raise ValueError("audited prior budget required")
    devreport, devaudit = read(dev / "report.json"), read(dev / "independent-audit.json")
    checked(devreport); checked(devaudit)
    if devreport["selected"] != "KEEP_EXISTING" or not devaudit["passed"] or devaudit["report_hash"] != devreport["hash"]:
        raise ValueError("frozen development selection required")
    base = Catalog.load(stage1 / "stage1-catalog.json")
    parent = BoundaryCatalog(base.entries(), h0_bindings(base))
    learning = read(dev / "W1/2026101241/ExistingActiveV2/candidate-frozen.json")
    proposal = propose(parent, "refund_captured_payment", learning)
    if proposal["decision"] != "PROPOSE_BOUNDARY": raise ValueError("actual supported W1 proposal required")
    learned = candidate_catalog(parent, proposal)
    relaxation = parent.boundaries()
    relaxation["modify_unfulfilled_order_address"]["patch"] = {"hypothesis_id": "ORACLE_INTERFACE_W6", "kind": "relax",
        "predicates": [{"field": "customer.risk_level", "op": "eq", "value": "LOW"},
                       {"field": "shipment.status", "op": "eq", "value": "PROCESSING"}]}
    oracle = BoundaryCatalog(base.entries(), relaxation)
    catalogs = {"parent": parent, "learned_W1": learned, "oracle_interface_W6": oracle}
    planned = []
    for i, (world, shipment, family, target, scope) in enumerate([
        ("W1", "PROCESSING", "refund", "learned_W1", "learned Boundary dev"),
        ("W1", "NOT_STARTED", "refund", "learned_W1", "stable dev"),
        ("W6", "PROCESSING", "modify_address", "oracle_interface_W6", "oracle interface only")]):
        ident = f"p9-changed-dev-20261012-{i}"
        fixture = {"order_id": "O-" + ident, "customer_id": "C-" + ident, "risk": "LOW", "shipment": shipment}
        params = {"order_id": fixture["order_id"], **({"amount": 100} if family == "refund" else {"new_address": "Delivery lane 204"})}
        task = expected_task(ident, family, fixture, params, world, seed=2026101280+i)
        for arm in ("parent", target):
            planned.append({"task": task, "world": world, "arm": arm, "source_group": ident, "scope": scope,
                "faults": {}, "bundle_hash": catalogs[arm].bundle_hash})
    freeze = read(stage1 / "stage1-freeze.json")
    files = [Path(__file__), ROOT / "scripts/collect_boundary_stage2.py", ROOT / "scripts/boundary_stage2_evaluator.py",
        ROOT / "scripts/run_boundary_runtime_smoke.py", ROOT / "scripts/evolution_budget.py", ROOT / "scripts/execution_aware_gpu_lease.py",
        *ROOT.glob("skillforge/boundary_lineage/*.py"), ROOT / "scripts/active_evolution_worlds.py"]
    sources = {**freeze["implementation_sources"], **{"skillforge/" + k: v for k, v in runtime_sources().items()},
        **{relative(p): digest_file(p) for p in files}}
    for name, sha in sources.items():
        if digest_file(ROOT / name) != sha: raise ValueError("source changed before registration")
    protocol = hashed({"schema": "stage2-changed-boundary-interface-smoke-v1", "cases": planned, "sources": sources,
        "catalog_hash": base.hash, "catalogs": {k: c.boundaries() for k, c in catalogs.items()}, "runtime_protocol": PROTOCOL,
        "prior_report_hash": prior["hash"], "prior_tokens": prior["shared_total_tokens"],
        "prior_wall_seconds": prior_protocol["prior_wall_seconds"] + prior["collection_wall_seconds"],
        "phase_tokens": 350000, "phase_wall_seconds": 1200,
        "limits": {"max_steps": 12, "max_search": 3, "max_load": 3, "max_tokens": 131072},
        "proposal_hash": proposal["hash"], "acquisition_development_report_hash": devreport["hash"],
        "new_training": False, "activated": False, "scope": "dev cost/interface; W6 explicit oracle diagnostic, no learning/admission efficacy"})
    publish(output / "protocol.json", protocol); publish(output / "proposal.json", proposal)
    publish(output / "learner-result.json", learning); base.save(output / "catalog.json")
    publish(ROOT / "results/skill-evolution/v1.2/stage2-development-budget-ledger" / (fingerprint(relative(output)) + ".json"),
        {"protocol_hash": protocol["hash"], "phase_id": relative(output), "prior_report_hash": prior["hash"],
         "prior_tokens": protocol["prior_tokens"], "phase_tokens": protocol["phase_tokens"], "phase_wall_seconds": protocol["phase_wall_seconds"]})
    ledger = SplitLedger(ROOT / "results/skill-evolution/v1.2/source-ledger")
    for case in planned:
        task = case["task"]; ledger.claim(case["source_group"], "dev", related_groups=[task["task_id"], task["parameters"]["order_id"], task["customer_id"]])
    for name in sources:
        target = output / "source-snapshot" / name; target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(ROOT / name, target)
    started, tokens, statuses, rows, failure = time.perf_counter(), 0, [], [], None
    try:
        with GPUServiceLease(), ExitStack() as cleanup:
            session = BoundarySession(output); cleanup.callback(session.close)
            publish(output / "model-identity.json", session.settings)
            for i, case in enumerate(planned):
                row, status = collect(session, output / str(i), case, catalogs[case["arm"]], protocol["limits"],
                    prior_tokens=protocol["prior_tokens"] + tokens, token_cap=protocol["prior_tokens"] + protocol["phase_tokens"],
                    prior_wall=protocol["prior_wall_seconds"], wall_cap=protocol["prior_wall_seconds"] + protocol["phase_wall_seconds"], started=started)
                tokens += status["charged_tokens"]; statuses.append(status)
                if row is None: failure = status["failure"]; break
                agent, verdict = row["agent"], row["verification"]
                rows.append({"task_id": case["task"]["task_id"], "arm": case["arm"], "scope": case["scope"],
                    "eoc": verdict["task_success"], "outcome": agent["outcome"],
                    "autonomous_eoc": verdict["task_success"] and not agent["interventions"]["runtime_intervention_count"],
                    "runtime_assisted_eoc": verdict["task_success"] and bool(agent["interventions"]["runtime_intervention_count"]),
                    "interventions": agent["interventions"], "attempted_violations": verdict["attempted_policy_violation"],
                    "actual_violations": verdict["actual_policy_violation"], "tokens": status["charged_tokens"],
                    "model_calls": agent["metrics"]["llm_calls"], "selected_skills": len(agent["skill_events"])})
                print(rows[-1], flush=True)
    except Exception as exc: failure = type(exc).__name__ + ": " + str(exc)
    report = hashed({"schema": "stage2-changed-boundary-interface-smoke-results-v1", "protocol_hash": protocol["hash"],
        "complete": len(rows) == len(planned), "failure": failure, "rows": rows, "statuses": statuses,
        "charged_tokens": tokens, "shared_total_tokens": protocol["prior_tokens"] + tokens,
        "collection_wall_seconds": time.perf_counter() - started, "new_training": False, "activated": False,
        "approved_unknown_requests": sum(s["approved_unknown_requests"] for s in statuses), "gpu_hours": "UNMEASURED",
        "scope": protocol["scope"]})
    publish(output / "report.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--output", required=True)
    print(run(parser.parse_args().output))
