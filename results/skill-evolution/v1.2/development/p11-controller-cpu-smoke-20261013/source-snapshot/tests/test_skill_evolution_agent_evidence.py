"""Scripted token-interface fixtures test replay, never model capability."""
import copy
import json
import random

import pytest

from scripts.evolution_budget import CheckpointAdmission
from scripts.evolution_forks import prepare_snapshot
from skillforge.environment import Environment
from skillforge.evolution_common.artifacts import SplitLedger
from skillforge.evolution_common.snapshot import save_snapshot
from skillforge.evolution_registry import immutable_json
from skillforge.evolution_schemas import fingerprint
from skillforge.schemas import Action
from skillforge.skill_evolution.agent_evidence import (read, audit_trajectory, execution_identity, initial_identity,
    declare_evidence_protocol, audit_paired_files, audit_paired_report)
from skillforge.skill_evolution.catalog import Catalog
from skillforge.skill_evolution.runtime import run_agent, runtime_sources, PROTOCOL, SYSTEM_PROMPT
from skillforge.skill_evolution.workflows import GOALS, make_case, private_items, verify_workflow


LIMITS = {"max_steps": 12, "max_search": 3, "max_load": 3, "max_tokens": 65536}
SETTINGS = {"model": "scripted-unit-token-interface-not-an-LLM", "engineering_only": False,
            "system_prompt": SYSTEM_PROMPT, "prompt_sha256": fingerprint(SYSTEM_PROMPT), "decision_protocol": PROTOCOL}
BUDGET = {"prior_tokens": 0, "max_tokens": 2000000, "prior_wall": 0, "max_wall": 2000}


def fixture(folder, case, *, prior=0, search=False):
    folder.mkdir(parents=True)
    env, catalog, rng = Environment(fixture=case.fixture), Catalog([]), random.Random(case.seed)
    initial, items = env.snapshot(), private_items(env)
    staged = prepare_snapshot(folder / "initial-snapshot", env, case.public_task(), catalog, {}, rng)
    actions = [Action(type="tool", name=name, arguments=case.parameters) for name in GOALS[case.workflow_id].required_evidence]
    if search: actions.insert(0, Action(type="tool", name="search_skills", arguments={"query":"shipment"}))
    actions.append(Action(type="stop"))
    class Model:
        settings, tokens = SETTINGS, 0
        def decide(self, context):
            action = actions.pop(0); self.tokens += 100
            self.last_messages = [{"role":"system","content":SYSTEM_PROMPT},{"role":"user","content":json.dumps(context)}]
            self.last_response = action.model_dump_json()
            return action
    admission, index = CheckpointAdmission(**{**BUDGET, "prior_tokens": prior}), 0
    def persist(value):
        nonlocal index
        save_snapshot(folder / "checkpoints" / str(index), env, value, rng)
        decision = admission.inspect(value, 1)
        if decision is not None:
            immutable_json(folder / "admissions" / (str(decision["request_index"]) + ".json"), {**decision,"checkpoint_index":index})
            admission.record_approval(decision)
        index += 1
    def call(name, args, key, source):
        result = env.call(name, args, case.authenticated_customer_id, key)
        env.audit[-1]["decision_origin"] = source
        return result
    try:
        agent = run_agent(Model(), case.public_task(), catalog, call, **LIMITS, persist=persist, auto_terminate=False)
        row = {"schema":"synthetic-unit-only", "case":case.model_dump(), "model_identity_hash":fingerprint(SETTINGS),
            "snapshot_hash":staged["snapshot_hash"],"initial_state":initial,"initial_items":items,
            "final_state":env.snapshot(),"final_items":private_items(env),"agent":agent,"tool_audit":env.audit,
            "verification":verify_workflow(case,initial,env.snapshot(),env.audit,agent["outcome"],items,private_items(env))}
        immutable_json(folder / "result.json",row)
        immutable_json(folder / "collection-status.json",{"task_id":case.task_id,"completed":True,"failure":None,
            "denied_before_ack":None,"charged_tokens":agent["metrics"]["tokens"],"last_budget":agent["budget"]})
        return row
    finally: env.close()


def replay(folder, *, budget=None, sources=None):
    return audit_trajectory(folder,Catalog([]),SETTINGS,sources or runtime_sources(),LIMITS,charge_context=budget or BUDGET)


def rewrite(path, value): path.write_text(json.dumps(value), encoding="utf-8")


def test_full_replay_includes_search_messages_checkpoints_cost_and_eoc(tmp_path):
    row = fixture(tmp_path / "run",make_case("logistics_investigation",92345,"train"),search=True)
    evidence = replay(tmp_path / "run")
    assert evidence["eoc"] and evidence["autonomous_eoc"] and not evidence["runtime_assisted_eoc"]
    assert evidence["model_calls"] == 5 and evidence["tokens"] == 500 and evidence["replay_tool_calls"] == 3
    assert not evidence["new_model_calls"] and not evidence["agent_admitted"]
    assert len(evidence["evidence_files"]) > 20


@pytest.mark.parametrize("mutation", ["action", "raw_response", "tool", "tokens", "eoc", "context", "model", "incomplete"])
def test_replay_rejects_forged_counted_evidence(tmp_path, mutation):
    folder = tmp_path / "run"; fixture(folder,make_case("shipment_summary",92346,"train"))
    row = read(folder / "result.json")
    if mutation == "action": row["agent"]["steps"][0]["action"]["name"] = "get_shipment"
    elif mutation == "raw_response": row["agent"]["steps"][0]["model_response"] = '{"type":"stop"}'
    elif mutation == "tool": row["tool_audit"][0]["result"]["order.status"] = "FAKE"
    elif mutation == "tokens": row["agent"]["metrics"]["tokens"] = 1
    elif mutation == "eoc": row["verification"]["task_success"] = False
    elif mutation == "context": row["agent"]["steps"][0]["context"]["gold"] = "private"
    elif mutation == "model": row["model_identity_hash"] = "wrong"
    elif mutation == "incomplete":
        status = read(folder / "collection-status.json"); status["completed"] = False; rewrite(folder / "collection-status.json",status)
    rewrite(folder / "result.json",row)
    with pytest.raises(ValueError): replay(folder)


def test_rehashed_checkpoint_rng_and_wrong_source_budget_are_rejected(tmp_path):
    folder = tmp_path / "run"; fixture(folder,make_case("shipment_summary",92347,"train"))
    with pytest.raises(ValueError,match="budget"): replay(folder,budget={**BUDGET,"prior_tokens":1})
    with pytest.raises(ValueError,match="source"): replay(folder,sources={**runtime_sources(),"environment.py":"wrong"})
    path = folder / "checkpoints/0/snapshot.json"; snap = read(path)
    snap["body"]["random_state"][1][0] += 1; snap["hash"] = fingerprint(snap["body"]); rewrite(path,snap)
    with pytest.raises(ValueError,match="RNG"): replay(folder)


def test_paired_files_recompute_counts_and_reject_rehashed_report(tmp_path):
    ledger = SplitLedger(tmp_path / "sources")
    case = make_case("shipment_summary",92348,"validation")
    ledger.claim(case.source_group,"stable_validation",related_groups=[case.task_id,case.parameters["order_id"],case.authenticated_customer_id])
    protocol = declare_evidence_protocol([{"case":case.model_dump(),"stable":True}],Catalog([]),Catalog([]),SETTINGS,runtime_sources(),LIMITS,ledger,budget=BUDGET)
    fixture(tmp_path / "baseline",case,search=True); fixture(tmp_path / "candidate",case,prior=400)
    refs = [{"task_id":case.task_id,"baseline":"baseline","candidate":"candidate"}]
    report = audit_paired_files(protocol,refs,ledger,artifact_root=tmp_path)
    assert report["statistical_gate"]["stable_cases"] == 1 and report["statistical_gate"]["decision"] == "INCONCLUSIVE"
    assert report["statistical_gate"]["pairs"][0]["baseline"]["model_calls"] == 4
    assert audit_paired_report(report,ledger,artifact_root=tmp_path)["passed"]
    fake = copy.deepcopy(report); fake["statistical_gate"]["pairs"][0]["candidate"]["model_calls"] = 0; fake["hash"] = fingerprint({k:v for k,v in fake.items() if k != "hash"})
    with pytest.raises(ValueError,match="independent raw-file"): audit_paired_report(fake,ledger,artifact_root=tmp_path)
    with pytest.raises(ValueError,match="distinct"):
        audit_paired_files(protocol,[{**refs[0],"candidate":"baseline"}],ledger,artifact_root=tmp_path)


def test_heldout_declaration_rejects_train_dev_and_relabelled_entities(tmp_path):
    ledger = SplitLedger(tmp_path / "sources")
    for split in ("train","dev","test"):
        case = make_case("shipment_summary",92349,split)
        with pytest.raises(ValueError,match="cannot enter"):
            declare_evidence_protocol([{"case":case.model_dump(),"stable":False}],Catalog([]),Catalog([]),SETTINGS,runtime_sources(),LIMITS,ledger,budget=BUDGET)
    case = make_case("shipment_summary",92350,"validation")
    ledger.claim(case.source_group,"validation",related_groups=[case.task_id])
    ledger.claim(case.parameters["order_id"],"train",related_groups=[case.authenticated_customer_id])
    with pytest.raises(ValueError,match="ownership"):
        declare_evidence_protocol([{"case":case.model_dump(),"stable":False}],Catalog([]),Catalog([]),SETTINGS,runtime_sources(),LIMITS,ledger,budget=BUDGET)


def test_execution_identity_does_not_depend_on_catalog_but_binds_backend():
    sources = runtime_sources()
    original = execution_identity(SETTINGS,sources,LIMITS,PROTOCOL)
    assert execution_identity({**SETTINGS,"model":"other"},sources,LIMITS,PROTOCOL) != original
    assert execution_identity(SETTINGS,sources,{**LIMITS,"max_steps":11},PROTOCOL) != original
