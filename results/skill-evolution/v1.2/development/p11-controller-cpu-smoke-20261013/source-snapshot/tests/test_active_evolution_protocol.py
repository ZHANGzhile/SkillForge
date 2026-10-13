import copy
import json
from pathlib import Path

import pytest

from scripts.active_evolution_dataset import EvaluationStore, audit_splits, generate, write_dataset
from scripts.evaluate_active_evolution import run_worker
from skillforge.evolution_boundary import public_predictions
from skillforge.evolution_config import LearningOptions
from skillforge.evolution_registry import boundary_admission
from skillforge.evolution_schemas import Candidate, Hypothesis, Predicate, fingerprint
from skillforge.evolution_validation import counters
from skillforge.schemas import SkillContract, Condition, SkillStep
from test_belief import evidence, hypotheses
from skillforge.evolution import EvolutionController
from test_evolution import validation


def contract():
    return SkillContract(skill_id="public_test_refund",family="refund",inputs=["order_id","amount"],
        preconditions=[Condition(field="payment.status",op="in",value=["CAPTURED","PARTIALLY_REFUNDED"],evidence=["declared-old-policy"]),
            Condition(field="refund.amount_valid",value=True,evidence=["declared-old-policy"])],
        forbidden_conditions=[Condition(field="customer.risk_level",value="HIGH",evidence=["declared-old-policy"])],
        procedure=[SkillStep(kind="finish")],postconditions={},source_trajectory_ids=[],policy_version="v1.1").model_dump(mode="json")


def test_all_splits_objects_and_templates_disjoint_and_stable_labels_unchanged():
    from scripts.active_evolution_dataset import state_for_policy
    from scripts.active_evolution_worlds import policy
    from skillforge.policies import eligibility
    counts={s:8 for s in ("seed","explore","validation","test","stable_validation","stable_test","model_test","model_stable_test")}
    rows=generate("W3",919,counts)
    assert audit_splits(rows)==dict(sorted(counts.items()))
    assert rows==generate("W3",919,dict(counts))
    for row in rows:
        if "stable" in row["split"]:
            state=state_for_policy(row)
            assert (policy("W3","issue_refund",state,row["parameters"])=="allow")== (eligibility("issue_refund",state,row["parameters"])=="allow")
    bad=copy.deepcopy(rows)
    bad[-1]["fixture"]["customer_id"]=rows[0]["fixture"]["customer_id"]
    with pytest.raises(ValueError,match="customer_id"):
        audit_splits(bad)


def test_holdout_rejected_before_open_and_manifest_tampering_detected(tmp_path,monkeypatch):
    write_dataset(tmp_path,"W1",7,{"seed":4,"test":4},contract())
    store=EvaluationStore(tmp_path)
    original=Path.read_text
    def blocked(path,*args,**kwargs):
        if path.name=="test.json":
            pytest.fail("test file opened before freeze")
        return original(path,*args,**kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path,"read_text",blocked)
        with pytest.raises(PermissionError):
            store.read("test")
    candidate={"version":"frozen"}
    freeze={"candidate_hash":fingerprint(candidate),"dataset_hash":fingerprint(store.manifest)}
    assert len(store.read("test",candidate,freeze))==4
    path=tmp_path/"seed.json"
    rows=json.loads(path.read_text())
    rows[0]["fixture"]["risk"]="tampered"
    path.write_text(json.dumps(rows))
    with pytest.raises(ValueError,match="changed"):
        store.read("seed")


def test_worker_process_cannot_read_private_file(tmp_path):
    secret=tmp_path/"private-test.json"
    secret.write_text('{"gold":true}')
    packet={"output":str(tmp_path/"learner"),"access_probe":str(secret)}
    result=run_worker(packet,lambda _:pytest.fail("no probe expected"))
    assert result["type"]=="access_denied"
    result=run_worker({"output":str(tmp_path/"learner2"),"import_probe":"policies"},lambda _:pytest.fail("no probe expected"))
    assert result["type"]=="access_denied"


def test_worker_can_journal_public_inputs_without_receiving_validation(tmp_path):
    candidate=Candidate(candidate_id="c",observations={"shipment.status":"PROCESSING"},baseline_prediction=True,cost=1,mutation_probability=1)
    packet={"output":str(tmp_path/"learner"),"identity":{"policy_epoch":"p","parent_hash":"parent"},
        "hypotheses":[h.model_dump(mode="json") for h in hypotheses()],
        "seed_evidence":[evidence(99,split="seed").model_dump()],"candidates":[candidate.model_dump()],
        "learning":{},"passive_order":["c"],"method":"no_adapt","random_seed":42}
    result=run_worker(packet,lambda _:pytest.fail("No adaptation cannot probe"))
    assert result["result"]["status"]=="UNCHANGED"
    assert (tmp_path/"learner/candidate.json").exists()
    assert not (tmp_path/"learner/validation.json").exists()


def test_no_adapt_never_queries_and_passive_uses_stream_without_learning_success(tmp_path):
    candidates=[Candidate(candidate_id=str(i),observations={"shipment.status":"PROCESSING"},baseline_prediction=True,cost=1,mutation_probability=1) for i in range(4)]
    called=[]
    def probe(key):
        called.append(key)
        return evidence(int(key),label="executable")
    for method in ("no_adapt","passive","random","active"):
        root=tmp_path/method
        c=EvolutionController(root,{"policy_epoch":"p","parent_hash":"parent"},hypotheses(),
            [evidence(99,split="seed")],candidates,probe,validation,root/"registry",
            learning={"accuracy":.9,"max_queries":2,"posterior_threshold":.999},passive_order=["3","2","1","0"])
        before=len(called)
        result=c.run(method=method)
        assert result["queries"]==(0 if method=="no_adapt" else 2)
        assert len(called)-before==result["queries"]
        if method=="passive":
            assert called[-2:]==["3","2"]
            assert result["learned_exploration_samples"]==0
            assert result["exploration_tool_calls"]==6
        initial=json.loads((root/"belief/belief_step_000.json").read_text())
        assert initial["snapshot"]["accuracy"]==.9
        assert c.run(method=method)==result


def test_relaxation_cannot_override_immutable_guard():
    h=Hypothesis(hypothesis_id="relax",kind="relax",predicates=(Predicate(field="shipment.status",op="eq",value="PROCESSING"),))
    assert h.predict({"shipment.status":"PROCESSING"},False,False) is False
    assert h.predict({"shipment.status":"PROCESSING"},False,True) is True
    assert h.predict({"shipment.status":"PROCESSING"},False,None) is None


def test_report_recomputed_from_cases_and_bound_to_evaluator():
    rows=[]
    for i,(split,truth) in enumerate((("validation",True),("validation",False),("stable_validation",True))):
        rows.append({"task_id":str(i),"task_hash":fingerprint(i),"split":split,"truth":truth,"prediction":truth,
            "baseline_prediction":truth,"procedure_success":truth,"actual_violations":0,"probe_hash":"a"*64})
    identity={"dataset_hash":"dataset","validator_code_hash":"code","validation_members":{
        r["task_id"]:{"hash":r["task_hash"],"split":r["split"]} for r in rows}}
    candidate={"parent_hash":"parent","parent_identity":{"contract_hash":"parent"},"admission_identity":identity}
    report={"candidate_hash":fingerprint(candidate),"split":"validation+stable_validation", "admission_identity":identity,
        "cases":rows,"cases_hash":fingerprint(rows),**counters(rows)}
    assert boundary_admission(candidate,report)
    bad=copy.deepcopy(report)
    bad["false_allow"]=1
    with pytest.raises(ValueError,match="aggregate"):
        boundary_admission(candidate,bad)
    bad=copy.deepcopy(report)
    bad["admission_identity"]["validator_code_hash"]="changed"
    with pytest.raises(ValueError,match="identity"):
        boundary_admission(candidate,bad)


def test_public_core_covers_each_shift_without_world_specific_learning_pool():
    from scripts.active_evolution_dataset import controlled_facts, coverage_core, state_for_policy
    from scripts.active_evolution_worlds import policy
    from skillforge.policies import eligibility
    cores=[]
    for world in ("W1","W2","W3","W4","W5","W6"):
        rows=generate(world,211,{"explore":80,"validation":40})
        for split in ("explore","validation"):
            selected=[r for r in rows if r["split"]==split]
            tool="update_shipping_address" if world=="W6" else "issue_refund"
            assert any((policy(world,tool,state_for_policy(r),r["parameters"])=="allow") !=
                       (eligibility(tool,state_for_policy(r),r["parameters"])=="allow") for r in selected)
        if world!="W6":
            cores.append([controlled_facts(r) for r in rows[:len(coverage_core("refund"))]])
    assert all(c==cores[0] for c in cores)


def test_partial_model_coverage_is_explicit_and_noop_not_a_new_version(tmp_path):
    from skillforge.evolution_registry import EvolutionRegistry
    manifest=write_dataset(tmp_path/"data","W3",7,{"seed":6,"explore":80,"validation":40,"model_test":4},contract())
    assert manifest["partial_coverage_splits"]==["model_test"]
    assert manifest["public_core_required"]==38
    assert manifest["coverage_requirements"]["model_test"]==8
    candidate={"hypothesis":Hypothesis(hypothesis_id="H0",kind="no_change").model_dump(),
        "parent_hash":"old","training_evidence":["e"],"belief_hash":"b"}
    with pytest.raises(ValueError,match="no-change"):
        EvolutionRegistry(tmp_path/"registry").publish(candidate,validation(candidate))
