"""Synthetic RPC/controller evidence only, never a real model benchmark."""
import json
import random
import shutil
import time

import pytest

from test_skill_evolution_learn import SimulatedSession
from scripts import run_skill_evolution_reuse as reuse
from scripts.collect_skill_evolution_learn import collect_one
from scripts.continue_skill_evolution_selection import publish
from scripts.plan_skill_evolution_reuse import build_draft
from scripts.evolution_budget import CheckpointAdmission
from skillforge.environment import Environment
from skillforge.evolution_common.artifacts import SplitLedger
from skillforge.evolution_common.snapshot import save_snapshot
from skillforge.evolution_schemas import fingerprint
from skillforge.skill_evolution.catalog import Catalog
from skillforge.skill_evolution.registry import VersionedRegistry
from skillforge.skill_evolution.runtime import SYSTEM_PROMPT,PROTOCOL,runtime_sources,run_agent
from skillforge.skill_evolution.validation import ValidationCase
from skillforge.skill_evolution.workflows import make_case


def synthetic_run(tmp_path,monkeypatch):
    original = reuse.ROOT
    config = {"prior_run":"prior","registry_run":"registry","adapter_sha256":"unit-token-interface-not-real-model",
        "limits":{"max_steps":12,"max_search":3,"max_load":3,"max_tokens":65536},
        "budget":{"phase_id":"unit-only-phase","project_max_tokens":100000,"project_max_wall_seconds":400}}
    root = tmp_path / "run"; root.mkdir()
    sources = {"skillforge/"+name:value for name,value in runtime_sources().items()}
    for name in ("scripts/run_skill_evolution_reuse.py","scripts/evolution_budget.py","scripts/collect_skill_evolution_learn.py"):
        sources[name] = reuse.digest_file(original / name)
        target = tmp_path / name; target.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(original / name,target)
    for name in sources:
        target = root / "source-snapshot" / name; target.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(original / name,target)
    monkeypatch.setattr(reuse,"ROOT",tmp_path)
    catalog = Catalog([]); catalog.save(tmp_path / "prior/catalog.json")
    prior = {"shared_total_charged_tokens":1000,"shared_total_wall_seconds":20}
    publish(tmp_path / "prior/report.json",prior)
    registry = VersionedRegistry(tmp_path / "registry/r")
    baseline = registry.bootstrap(catalog,reason="synthetic unit-only baseline",evidence=reuse.hashed({"catalog_hash":catalog.hash}))
    retained = registry.retain(baseline,reason="synthetic zero-update fixture",evidence=reuse.hashed({"real_candidates":0}))
    cases = [make_case("shipment_summary",86700,"dev"),make_case("logistics_investigation",86710,"dev")]
    ledger = SplitLedger(tmp_path / "results/skill-evolution/v1.2/source-ledger")
    for case in cases: ledger.claim(case.source_group,"dev",related_groups=[case.task_id,case.parameters["order_id"],case.authenticated_customer_id])
    schedule = [{"task_id":case.task_id,"method":method,"folder":f"c{i}/{method.lower()}"}
                for i,case in enumerate(cases) for method in reuse.METHODS[i:]+reuse.METHODS[:i]]
    for method in reuse.METHODS: catalog.save(root / (method + "-catalog.json"))
    publish(root / "private-dev-cases.json",[case.model_dump() for case in cases])
    body = {"schema":"synthetic-controller-unit","config":config,"protocol":PROTOCOL,"sources":sources,
        "prior_tokens":1000,"prior_wall":20,"prior_reuse_runs":[],"prior_report_sha256":reuse.digest_file(tmp_path / "prior/report.json"),
        "cases_hash":fingerprint([case.model_dump() for case in cases]),"catalogs":{method:catalog.hash for method in reuse.METHODS},
        "schedule":schedule,"parent_snapshot":retained}
    registration = {**body,"protocol_hash":fingerprint(body)}; publish(root / "registration.json",registration)
    publish(tmp_path / "results/skill-evolution/v1.2/reuse-budget-ledger" / (fingerprint(config["budget"]["phase_id"])+".json"),{
        "phase_id":config["budget"]["phase_id"],"output":"run","protocol_hash":registration["protocol_hash"],"ceilings":config["budget"],
        **{key:registration[key] for key in ("prior_tokens","prior_wall","prior_reuse_runs","prior_report_sha256")}})
    session = SimulatedSession()
    session.settings = {**session.settings,"prompt_sha256":fingerprint(SYSTEM_PROMPT),"decision_protocol":PROTOCOL,
                        "adapter_sha256":config["adapter_sha256"]}
    publish(root / "model-identity.json",session.settings)
    rows,statuses = [],[]
    started = time.perf_counter()
    try:
        for item in schedule:
            case = next(case for case in cases if case.task_id==item["task_id"])
            row,status = collect_one(session,case,catalog,root / item["folder"],config,
                1000+sum(status["charged_tokens"] for status in statuses),20,started)
            assert status["completed"]
            rows.append((case.task_id,item["method"],row)); statuses.append({**item,**status})
    finally: session.close()
    report = reuse.summarize(registration,rows,statuses,None,time.perf_counter()-started); publish(root / "report.json",report)
    return root,registration,report,rows


def test_three_arm_collector_and_independent_audit_keep_budget_and_no_history(tmp_path,monkeypatch):
    root,registration,report,rows = synthetic_run(tmp_path,monkeypatch)
    receipt = reuse.audit(root)
    assert receipt["run_completed"] and receipt["costs_reconciled"] and receipt["audited_arms"]==6
    assert receipt["replay_tool_calls"]==15 and receipt["no_history_checked_arms"]==6
    assert report["charged_tokens_including_incomplete"]==2100 and report["shared_total_charged_tokens"]==3100
    assert report["shared_total_wall_seconds"]==20+report["wall_seconds"] and report["no_history_checked_arms"]==6
    assert all(item["C_minus_B_eoc"]==0 and item["B_minus_C_model_calls"]==0 for item in report["paired_C_B"])
    assert not report["agent_admitted"] and not report["isolated_activated"]


@pytest.mark.parametrize("change",["fees","arm_counts","order","catalog","context","model","wall","phase_ledger"])
def test_controller_audit_rejects_forged_cost_or_method_evidence(tmp_path,monkeypatch,change):
    root,registration,report,rows = synthetic_run(tmp_path,monkeypatch)
    if change=="fees": report["shared_total_charged_tokens"] -= 1000; (root / "report.json").write_text(json.dumps(report))
    elif change=="arm_counts": report["methods"]["C"]["eoc"] = 99; (root / "report.json").write_text(json.dumps(report))
    elif change=="order":
        registration["schedule"].reverse(); registration["protocol_hash"] = fingerprint({k:v for k,v in registration.items() if k!="protocol_hash"})
        (root / "registration.json").write_text(json.dumps(registration))
    elif change=="catalog":
        registration["catalogs"]["A"]="forged"; registration["protocol_hash"] = fingerprint({k:v for k,v in registration.items() if k!="protocol_hash"})
        (root / "registration.json").write_text(json.dumps(registration))
    elif change=="context":
        path = root / "c0/a/result.json"; row = reuse.read(path); row["agent"]["steps"][0]["context"]["raw_trajectories"]=["learn"]
        path.write_text(json.dumps(row))
    elif change=="model":
        path = root / "model-identity.json"; value = reuse.read(path); value["adapter_sha256"]="other"; path.write_text(json.dumps(value))
    elif change=="wall":
        report["wall_seconds"]=0; report["shared_total_wall_seconds"]=20; (root / "report.json").write_text(json.dumps(report))
    else:
        path = tmp_path / "results/skill-evolution/v1.2/reuse-budget-ledger" / (fingerprint("unit-only-phase")+".json")
        owner = reuse.read(path); owner["prior_tokens"]=0; path.write_text(json.dumps(owner))
    with pytest.raises(ValueError): reuse.audit(root)


@pytest.mark.parametrize("approved",[True,False])
def test_interrupted_request_preserves_unknown_reservation_or_denied_zero_cost(tmp_path,approved):
    env = Environment(); rng = random.Random(1)
    context = {"prior_tokens":0 if approved else 99000,"max_tokens":100000,"prior_wall":0,"max_wall":400}
    admission = CheckpointAdmission(**context)
    class BeforeInferenceInterrupted(RuntimeError): pass
    class NeverCalled:
        settings={"engineering_only":False}; tokens=0
        def decide(self,context): raise AssertionError("must not reach inference")
    denied = None
    def persist(value):
        nonlocal denied
        save_snapshot(tmp_path / "checkpoints/0",env,value,rng)
        receipt = admission.inspect(value,1)
        reuse.publish(tmp_path / "admissions/0.json",{**receipt,"checkpoint_index":0})
        if receipt["approved"]: admission.record_approval(receipt)
        else: denied={**receipt,"checkpoint_index":0}
        raise BeforeInferenceInterrupted()
    try:
        task={"task_id":"unit-interrupted","family":"shipment_summary","request":"read status","parameters":{"order_id":"O1"}}
        with pytest.raises(BeforeInferenceInterrupted): run_agent(NeverCalled(),task,Catalog([]),lambda *_:None,persist=persist)
        reuse.publish(tmp_path / "collection-status.json",{"task_id":task["task_id"],"completed":False,"failure":"unit interruption",
            "denied_before_ack":denied,"charged_tokens":16384 if approved else 0,"last_budget":admission.last["budget"]})
        assert reuse.audit_incomplete(tmp_path,context)==(16384 if approved else 0)
        assert not env.audit
    finally: env.close()


def test_no_history_does_not_remove_current_task_evidence():
    row = {"case":{"task_id":"task"},"agent":{"steps":[{"context":{"task_id":"task","history":[]},"action":{"type":"stop"}}]}}
    assert reuse.check_no_history(row)
    row["agent"]["steps"][0]["context"]["history"]=[{"task_id":"other-task"}]
    with pytest.raises(ValueError,match="current-task"): reuse.check_no_history(row)


def test_draft_declares_three_rounds_fresh_entities_and_conditional_costs():
    registration = {"protocol_hash":"smoke","config":{"limits":{"max_tokens":65536}}}
    report = {"protocol_hash":"smoke","status":"complete","completed_arms":6,"wall_seconds":180,
        "methods":{method:{"tokens":24000,"n":2} for method in reuse.METHODS},
        "shared_total_charged_tokens":600000,"shared_total_wall_seconds":2100}
    draft = build_draft(registration,report,seed=87600)
    assert not draft["frozen"] and draft["completed_real_rounds"]==0 and len(draft["rounds"])==3
    assert draft["cost_estimate"]["max_model_runs"]==120 and draft["cost_estimate"]["planning_tokens_with_2x_margin"]==2880000
    groups,entities = [],[]
    for phase in draft["rounds"]:
        cases = phase["learn_cases"]+[item["case"] for item in phase["agent_validation_cases"]]
        for probes in phase["program_validation_probes"].values():
            cases += [ValidationCase.model_validate(item).case.model_dump() for item in probes]
        for case in cases:
            groups.append(case["source_group"]); entities.append(case["parameters"]["order_id"])
        assert sum(not item["stable"] for item in phase["agent_validation_cases"])==6
        assert not phase["validation_feedback_to_optimizer"]
    groups += [item["case"]["source_group"] for item in draft["final_test_cases"]]
    assert len(groups)==len(set(groups)) and len(entities)==len(set(entities))
    assert len(draft["final_test_cases"])==18 and draft["no_history"]["current_task_history_retained"]
    assert draft["generalization"]["structural_compositional"].startswith("UNSUPPORTED")


def test_draft_cannot_freeze_incomplete_or_unmatched_smoke():
    with pytest.raises(ValueError,match="complete matched"):
        build_draft({"protocol_hash":"a"},{"status":"blocked_or_incomplete","protocol_hash":"a"})
