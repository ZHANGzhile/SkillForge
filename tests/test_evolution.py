import json
import sqlite3

import pytest

from scripts.prepare_active_evolution import cost_plan
from skillforge.belief import BeliefState
from skillforge.evolution_journal import BeliefJournal
from skillforge.evolution import EvolutionController
from skillforge.evolution_registry import EvolutionRegistry
from skillforge.evolution_schemas import Candidate, fingerprint
from test_belief import evidence, hypotheses


def test_belief_journal_resume_identity_immutability_and_tampering(tmp_path):
    path=tmp_path/"belief.sqlite"
    identity={"model":"dev","code":"hash","dataset":"hash"}
    journal=BeliefJournal(path,identity)
    b=BeliefState(hypotheses(),"p")
    journal.append(b)
    b.update(evidence())
    journal.append(b)
    journal.append(b)
    assert BeliefJournal(path,identity).restore().snapshot()==b.snapshot()
    journal.export(tmp_path/"export")
    assert len(list((tmp_path/"export").glob("belief_step_*.json")))==2
    with pytest.raises(ValueError,match="identity"):
        BeliefJournal(path,{**identity,"code":"changed"})
    changed=BeliefState(hypotheses(),"p")
    changed.update(evidence(label="executable"))
    with pytest.raises(ValueError,match="immutable"):
        journal.append(changed)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE checkpoints SET payload='{}' WHERE step=1")
    with pytest.raises((ValueError,KeyError)):
        journal.restore()


def test_cost_gate_accounts_for_more_than_final_test_and_does_not_auto_unlock():
    plan={"worlds":["W1","W2","W3","W4","W5","W6"],"methods":["no_adapt","passive","random","active"],
        "splits":{"seed":12},"model_layer":{"worlds":["W3","W5","W6"],"repeats":1,
        "model_validation":4,"model_stable_validation":4,"model_test":8,"model_stable_test":8,
        "infrastructure_retries":1,"global_retry_fraction":.1}}
    result=cost_plan(plan)
    assert result["stages"]["final_full_system"]==192
    assert result["total_tasks"]==732
    assert result["global_retry_tasks"]==74
    assert not result["formal_model_execution_enabled"]
    measured=cost_plan(plan,{"p95_seconds":10,"mean_tokens":500})
    assert measured["estimates"]["hours_at_p95"]==pytest.approx(7320/3600)
    assert not measured["formal_model_execution_enabled"]


def validation(candidate, rejected=False):
    return {"candidate_hash":fingerprint(candidate),"split":"validation+stable_validation",
        "positive_cases":4,"negative_cases":4,"actual_violations":0,"false_allow":int(rejected),
        "false_block":0,"baseline_false_block":0,"normal_failures":0,"baseline_normal_failures":0,
        "stable_cases":20,"stable_regressions":0}


def test_controller_accepted_rejected_and_resume_without_requery(tmp_path):
    candidates=[Candidate(candidate_id=str(i),observations={"shipment.status":"PROCESSING"},baseline_prediction=True,cost=1,mutation_probability=1) for i in range(8)]
    seed=[evidence(100,split="seed")]
    called=[]
    def probe(key):
        called.append(key)
        return evidence(int(key))
    identity={"policy_epoch":"p","parent_hash":"parent","code_hash":"dev","dataset_hash":"dev"}
    for rejected in (False,True):
        folder=tmp_path/str(rejected)
        controller=EvolutionController(folder,identity,hypotheses(),seed,candidates,probe,
            lambda candidate: validation(candidate,rejected),folder/"registry")
        result=controller.run()
        assert result["status"]==("REJECTED" if rejected else "VERIFIED")
        before=len(called)
        assert controller.run()==result
        assert len(called)==before
        if rejected:
            assert not (folder/"registry").exists()
        else:
            entry=EvolutionRegistry(folder/"registry").load(result["registry_version"])
            assert entry["candidate"]["parent_hash"]=="parent"
        query=next((folder/"queries").glob("*.json"))
        damaged=json.loads(query.read_text(encoding="utf-8"))
        damaged["candidate_id"]="tampered"
        query.write_text(json.dumps(damaged),encoding="utf-8")
        with pytest.raises(ValueError,match="corrupted"):
            controller.run()
