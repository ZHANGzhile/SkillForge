from scripts.active_evolution_worlds import difference_witnesses
from skillforge.environment import Environment
from skillforge.policies import eligibility
from skillforge.sandbox_probe import database_hash, run_probe


def spec(shipment="PROCESSING",family="refund"):
    return {"task_id":"probe-a","policy_epoch":"epoch-a","split":"explore","family":family,
        "fixture":{"order_id":"Oa","customer_id":"Ca","shipment":shipment},
        "parameters":{"order_id":"Oa", **({"amount":100} if family=="refund" else {"new_address":"New delivery address 100"})}}


def test_six_worlds_really_change_applicability():
    assert len(difference_witnesses())==6


def test_probe_rejected_write_cannot_change_source_or_global_policy(tmp_path):
    s=spec()
    path=tmp_path/"source.sqlite"
    env=Environment(path,fixture=s["fixture"])
    initial=env.snapshot()
    env.close()
    before=database_hash(path)
    result=run_probe(s,"W1",path)
    assert not result["procedure_success"]
    assert result["tool_audit"][-1]["error"]=="business_rule_rejected"
    assert result["actual_violations"]==0
    assert database_hash(path)==before
    assert eligibility("issue_refund",initial,s["parameters"])=="allow"


def test_false_block_probe_can_succeed_and_faults_are_isolated(tmp_path):
    s=spec(family="modify_address")
    path=tmp_path/"source.sqlite"
    env=Environment(path,fixture=s["fixture"])
    env.close()
    before=database_hash(path)
    result=run_probe(s,"W6",path)
    assert result["procedure_success"] and result["actual_violations"]==0
    assert database_hash(path)==before
    faults={"get_order":["timeout"]}
    result=run_probe(s,"W6",path,faults=faults)
    assert not result["procedure_success"]
    assert faults=={"get_order":["timeout"]}
    assert result["remaining_faults"]["get_order"]==[]
