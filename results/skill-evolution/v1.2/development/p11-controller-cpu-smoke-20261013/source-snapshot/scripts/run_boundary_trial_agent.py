"""Real daily-trigger -> existing Active -> layered gates -> actual parent chain.

Identical task/model/Runtime/Boundary arms may share one actual physical run,
as preregistered. Logical method costs and deduplicated physical fees are both
reported. Reuse never crosses a task or changed bundle identity.
"""
import argparse
from contextlib import ExitStack
from pathlib import Path
import time

from scripts.run_skill_evolution import ROOT, digest_file
from scripts.skill_evolution_release import fixed_model
from scripts.collect_boundary_stage2 import BoundarySession, collect
from scripts.audit_boundary_stage2_arm import audit_arm
from scripts.run_boundary_trial_cpu import isolated, observations
from scripts.boundary_trial_probe import probe as actual_probe
from scripts.boundary_trial_audits import replay_probe
from scripts.active_evolution_dataset import public_candidate
from scripts.continue_skill_evolution_selection import publish
from skillforge.skill_evolution.agent_evidence import read
from skillforge.skill_evolution.catalog import Catalog
from skillforge.boundary_runtime.catalog import BoundaryCatalog, h0_bindings
from skillforge.boundary_runtime.runtime import runtime_sources
from skillforge.boundary_evolution.trigger import DriftController, Interaction
from skillforge.boundary_lineage.evidence import VersionedReceiptAdapter
from skillforge.boundary_lineage.proposal import checked, hashed, propose, candidate_catalog, parent_key
from skillforge.boundary_lineage.validation import declare_boundary_validation, boundary_gate, agent_gate
from skillforge.evolution_config import LearningOptions
from skillforge.evolution_schemas import fingerprint, EvidenceView
from skillforge.hypothesis import generate_hypotheses


def run(root):
    from scripts.execution_aware_gpu_lease import GPUServiceLease
    root = Path(root).resolve()
    p = read(root / "protocol.json"); checked(p)
    for name, sha in p["sources"].items():
        if digest_file(ROOT / name) != sha or digest_file(root / "source-snapshot" / name) != sha: raise ValueError("registered sources changed")
    output = root / "agent"
    if output.exists(): raise ValueError("fresh Agent run required; do not auto-replay interrupted physical arms")
    output.mkdir()
    base = Catalog.load(root / "catalog.json")
    options = LearningOptions.model_validate(p["learning"])
    initial = BoundaryCatalog(base.entries(), h0_bindings(base))
    tokens, statuses, arms, stages, failures, physical_cache = 0, [], [], [], [], {}
    started = time.perf_counter()
    publish(output / "running.json", {"protocol_hash": p["hash"], "status": "running"})
    try:
        with GPUServiceLease(), ExitStack() as cleanup:
            session = BoundarySession(output); cleanup.callback(session.close)
            fixed_model(session.settings)
            publish(output / "model-identity.json", session.settings)
            common_identity = fingerprint({"model": session.settings, "runtime_sources": runtime_sources(), "limits": p["limits"]})
            def execute(case, catalog, local, role):
                nonlocal tokens
                identity = fingerprint({"task": case["task"], "faults": case["faults"], "bundle": catalog.bundle_hash,
                    "world": case["world"], "execution": common_identity})
                if identity not in physical_cache:
                    index = len(statuses)
                    physical_folder = output / "physical" / str(index)
                    prior_tokens = p["prior_tokens"] + tokens
                    row, status = collect(session, physical_folder, case, catalog, p["limits"],
                        prior_tokens=prior_tokens, token_cap=p["prior_tokens"] + p["phase_tokens"],
                        prior_wall=p["prior_wall_seconds"], wall_cap=p["prior_wall_seconds"] + p["phase_wall_seconds"], started=started)
                    charge = {"prior_tokens": prior_tokens, "token_cap": p["prior_tokens"] + p["phase_tokens"],
                        "prior_wall": p["prior_wall_seconds"], "wall_cap": p["prior_wall_seconds"] + p["phase_wall_seconds"]}
                    tokens += status["charged_tokens"]; statuses.append(status)
                    publish(physical_folder / "case.json", case); publish(physical_folder / "charge-context.json", charge)
                    publish(physical_folder / "boundaries.json", catalog.boundaries())
                    if row is None: raise RuntimeError(status["failure"])
                    audit = audit_arm(physical_folder, case, catalog, session.settings, p["limits"], **charge)
                    proof = hashed({"schema": "continuous-agent-physical-arm-audit-v1", "passed": True,
                        "evidence_index": audit["evidence_index"], "checkpoints": audit["replayed_checkpoints"], "new_model_calls": 0})
                    publish(physical_folder / "independent-audit.json", proof)
                    physical_cache[identity] = (row, status, str(physical_folder.relative_to(root)).replace("\\", "/"), proof["hash"])
                row, status, reference, audit_hash = physical_cache[identity]
                publish(local / (role + "-reference.json"), {"physical_folder": reference, "identity": identity, "audit_hash": audit_hash,
                    "case_hash": fingerprint(case), "bundle_hash": catalog.bundle_hash})
                a, v = row["agent"], row["verification"]
                arms.append({"task_id": case["task"]["task_id"], "source_group": case["source_group"], "partition": case["partition"],
                    "stable": case["stable"], "role": role, "folder": str(local.relative_to(root)).replace("\\", "/"), "physical_folder": reference,
                    "bundle_hash": catalog.bundle_hash, "eoc": v["task_success"], "outcome": a["outcome"],
                    "expected_outcomes": case["task"]["expected"]["allowed_outcomes"],
                    "autonomous_eoc": v["task_success"] and not a["interventions"]["runtime_intervention_count"],
                    "runtime_assisted_eoc": v["task_success"] and bool(a["interventions"]["runtime_intervention_count"]),
                    "interventions": a["interventions"], "actual_violations": int(v["actual_policy_violation"]),
                    "attempted_violations": int(v["attempted_policy_violation"]), "tokens": status["charged_tokens"],
                    "model_calls": a["metrics"]["llm_calls"], "execution_identity": common_identity,
                    "evidence_hash": fingerprint(row), "cost_settled": True})
                publish(local / (role + "-summary.json"), arms[-1])
                return row, arms[-1]
            for world in p["agent_worlds"]:
                for seed in p["sequence_seeds"]:
                    parent = initial
                    controller = DriftController(p["trigger_policy"])
                    previous_stage = None
                    for stage in range(3):
                        key = f"{world}/{seed}/{stage}"
                        local = output / world / str(seed) / str(stage)
                        design = read(root / "datasets" / world / str(seed) / str(stage) / "agent-cases.json")
                        skill_id = "modify_unfulfilled_order_address" if world == "W6" else "refund_captured_payment"
                        contract = next(e["contract"] for e in base.entries() if e["skill_id"] == skill_id)
                        parent_before, seeds, decisions = parent.bundle_hash, [], []
                        trigger = None
                        for i, case in enumerate(c for c in design if c["partition"] == "daily"):
                            execute(case, initial, local / "daily" / str(i), "NoAdapt")
                            row, summary = execute(case, parent, local / "daily" / str(i), "ExistingActive")
                            public_task = {k: case["task"][k] for k in ("task_id", "family", "request", "parameters")}
                            raw = {"task_id": public_task["task_id"], "trajectory_id": fingerprint([public_task["task_id"], row["agent"]["identity"]]),
                                "tool_audit": row["tool_audit"], "execution_contract": row["agent"]["execution_contract"]}
                            member = {"task_hash": fingerprint(public_task), "raw_hash": fingerprint(raw), "skill_id": skill_id,
                                "parent_revision": parent.boundaries()[skill_id]["parent_revision"], "source_group": case["source_group"],
                                "probe_origin": "daily", "evidence_origin": "model_tool", "boundary_bundle_hash": parent.bundle_hash,
                                "boundary_revision": parent.public_boundary(skill_id)["revision"]}
                            bound = VersionedReceiptAdapter({public_task["task_id"]: member}, parent).export(raw, public_task)
                            interaction = Interaction.model_validate(bound["drift_interaction"])
                            decision = controller.observe(interaction)
                            publish(local / "daily" / str(i) / "public-bound-receipt.json", bound)
                            publish(local / "daily" / str(i) / "decision.json", decision)
                            decisions.append(decision)
                            if not case["faults"]: seeds.append(EvidenceView.model_validate(bound["absolute_learning_evidence"]))
                            if decision["state"] == "SUSPECTED_DRIFT" and not decision["pause_related_skill"]: trigger = decision
                        proposal, learner, candidate, br, ar, boundary_audit = None, None, parent, None, None, None
                        if trigger:
                            sandbox_id = "agent-authorized-sandbox-" + fingerprint(key)
                            controller.begin_exploration(trigger["trigger_key"], sandbox_id=sandbox_id)
                            segment = trigger["trigger_key"]
                            seeds = [e.model_copy(update={"policy_epoch": segment, "split": "seed"}) for e in seeds]
                            specs = read(root / "datasets" / world / str(seed) / str(stage) / "explore.json")
                            specs = [{**s, "policy_epoch": segment} for s in specs]
                            publish(local / "explore-bound-members.json", specs)
                            by_id = {s["task_id"]: s for s in specs}; pool = [public_candidate(s, contract) for s in specs]
                            def query(cid):
                                spec = by_id[cid]
                                raw = actual_probe(spec, design[0]["world"], contract)
                                replay_probe(raw, spec, contract, design[0]["world"])
                                publish(local / "exploration-probes" / (cid + ".json"), raw)
                                e = observations(raw, spec, contract)
                                status = parent.effective_gate(contract, e.observations, spec["parameters"]).status
                                drift = e.model_copy(update={"baseline_prediction": {"APPLICABLE": True, "INAPPLICABLE": False}.get(status)})
                                body = {"source_group": "continuous-agent-explore-" + cid, "object_id": spec["parameters"]["order_id"],
                                    "parent_revision": parent_key(parent, skill_id), "evidence": drift.model_dump(mode="json"),
                                    "feedback": "business" if e.label != "unknown" else "unknown", "probe_origin": "authorized_sandbox",
                                    "sandbox_id": sandbox_id, "query_receipt_hash": fingerprint(raw)}
                                controller.charge_probe(segment, Interaction(receipt_id=fingerprint(body), **body))
                                return e
                            learner = isolated(local / "learner", "ExistingActiveV2", seeds, pool,
                                generate_hypotheses(p["hypothesis_fields"]), query, options, seed + stage)
                            proposal = propose(parent, skill_id, learner); publish(local / "proposal.json", proposal)
                            if proposal["decision"] == "PROPOSE_BOUNDARY":
                                candidate = candidate_catalog(parent, proposal)
                                validation_design = [c for c in design if c["partition"] == "validation"]
                                members = [{"task_id": c["task"]["task_id"], "task_hash": fingerprint(c["task"]),
                                    "source_group": c["source_group"], "split": "stable_validation" if c["stable"] else "validation"} for c in validation_design]
                                plan = declare_boundary_validation(parent, proposal, members)
                                publish(local / "boundary-validation-plan.json", plan)
                                cases = []
                                for c, member in zip(validation_design, members):
                                    raw = actual_probe(c["spec"], c["world"], contract); replay_probe(raw, c["spec"], contract, c["world"])
                                    publish(local / "boundary-probes" / (c["task"]["task_id"] + ".json"), raw)
                                    factors = public_candidate(c["spec"], contract)
                                    errors = {e["error"] for e in raw["tool_audit"] if e["error"]}
                                    truth = True if raw["procedure_success"] else False if errors == {"business_rule_rejected"} else None
                                    def pred(cat): return {"APPLICABLE": True, "INAPPLICABLE": False}.get(cat.effective_gate(contract, factors.observations, c["spec"]["parameters"]).status)
                                    cases.append({**member, "probe_hash": fingerprint(raw), "truth": truth, "parent": pred(parent),
                                        "candidate": pred(candidate), "actual_violations": raw["actual_violations"], "agent_planned": True})
                                br = boundary_gate(plan, cases); publish(local / "boundary-validation.json", br)
                                boundary_audit = hashed({"schema": "continuous-agent-boundary-audit-v1", "passed": True,
                                    "proposal_hash": proposal["hash"], "boundary_report_hash": br["hash"], "actual_probe_hashes": [c["probe_hash"] for c in cases]})
                                publish(local / "boundary-independent-audit.json", boundary_audit)
                                if br["decision"] == "BOUNDARY_GATE_PASSED":
                                    pairs = []
                                    for c, member in zip(validation_design, members):
                                        old_row, old = execute(c, parent, local / "validation" / c["task"]["task_id"], "parent")
                                        new_row, new = execute(c, candidate, local / "validation" / c["task"]["task_id"], "candidate")
                                        if old_row["initial_state"] != new_row["initial_state"]: raise ValueError("paired initial states differ")
                                        fields = ("eoc", "actual_violations", "attempted_violations", "tokens", "model_calls", "cost_settled", "execution_identity", "bundle_hash", "evidence_hash")
                                        pairs.append({**member, "initial_state_hash": fingerprint(old_row["initial_state"]),
                                            "parent": {k: old[k] for k in fields}, "candidate": {k: new[k] for k in fields}})
                                    ar = agent_gate(br, pairs, **p["agent_gate"])
                                    publish(local / "agent-validation.json", ar)
                                    if ar["decision"] == "AGENT_GATE_PASSED": parent = candidate
                        stage_record = hashed({"schema": "continuous-real-agent-stage-v1", "protocol_hash": p["hash"], "key": key,
                            "previous_stage_hash": previous_stage, "parent_bundle_hash": parent_before, "effective_bundle_hash": parent.bundle_hash,
                            "effective_boundaries": parent.boundaries(), "triggered": trigger is not None,
                            "belief_converged": bool(learner and proposal["certificate"]["status"] == "SUPPORTED_CANDIDATE"),
                            "proposal_hash": proposal["hash"] if proposal else None, "queries": len(learner["queries"]) if learner else 0,
                            "boundary_admitted": bool(br and br["decision"] == "BOUNDARY_GATE_PASSED" and boundary_audit),
                            "agent_admitted": bool(ar and ar["decision"] == "AGENT_GATE_PASSED"),
                            "isolated_activated": parent.bundle_hash != parent_before, "deployed": False,
                            "boundary_report_hash": br["hash"] if br else None, "agent_report_hash": ar["hash"] if ar else None,
                            "decision": "ISOLATED_ACTIVATED" if parent.bundle_hash != parent_before else ar["decision"] if ar else
                                br["decision"] if br else proposal["decision"] if proposal else "NO_TRIGGER"})
                        publish(local / "decision-before-test.json", stage_record)
                        previous_stage = stage_record["hash"]; stages.append(stage_record)
                        for i, c in enumerate(c for c in design if c["partition"] == "test"):
                            execute(c, initial, local / "test" / str(i), "NoAdapt")
                            execute(c, parent, local / "test" / str(i), "ExistingActive")
                        publish(local / "trigger-checkpoint.json", controller.checkpoint())
                        publish(local / "complete.json", {"stage_hash": stage_record["hash"], "status": "complete"})
                        print({"stage": key, "decision": stage_record["decision"], "physical_arms": len(statuses), "tokens": tokens}, flush=True)
    except Exception as exc: failures.append(type(exc).__name__ + ": " + str(exc))
    report = hashed({"schema": "continuous-real-agent-results-v1", "protocol_hash": p["hash"],
        "complete": not failures and len(stages) == len(p["agent_worlds"]) * len(p["sequence_seeds"]) * 3,
        "failure": failures, "stages": stages, "logical_arms": arms, "physical_statuses": statuses,
        "charged_tokens": tokens, "shared_total_tokens": p["prior_tokens"] + tokens, "collection_wall_seconds": time.perf_counter() - started,
        "scope": "engineering scale; fixed weights/program/discovery/Runtime; actual real daily triggers and separate CPU probes; no formal test feedback into learning",
        "new_training": False, "deployed": False, "gpu_hours": "UNMEASURED"})
    publish(output / "report.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--run", required=True)
    print(run(parser.parse_args().run))
