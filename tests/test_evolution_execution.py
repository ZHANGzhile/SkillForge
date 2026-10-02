import copy

import pytest

from scripts.active_evolution_dataset import generate, controlled_facts
from scripts.active_evolution_model_design import model_core
from scripts.active_evolution_worlds import policy
from skillforge.evolution_execution import execute_frozen
from skillforge.evolution_schemas import Hypothesis, Predicate
from skillforge.policies import eligibility
from skillforge.sandbox_probe import run_probe
from skillforge.schemas import SkillContract, SkillStep, Condition


def parent(family):
    refund=family=="refund"
    mutation="issue_refund" if refund else "update_shipping_address"
    args={"order_id":"$input.order_id",("amount" if refund else "new_address"):"$input."+("amount" if refund else "new_address")}
    pre=[Condition(field="customer.risk_level",op="in",value=["LOW","MEDIUM"],evidence=["old"])]
    if not refund:
        pre+=[Condition(field="shipment.status",value="NOT_STARTED",evidence=["old"])]
    return SkillContract(skill_id="test-parent",family=family,inputs=["order_id","amount" if refund else "new_address"],
        preconditions=pre,forbidden_conditions=[],procedure=[SkillStep(kind="call",tool=mutation,arguments=args),
        SkillStep(kind="call",tool="get_payment" if refund else "get_order",arguments={"order_id":"$input.order_id"}),SkillStep(kind="finish")],
        postconditions={"payment.refunded_amount":"$state.refund.expected_total"} if refund else {"order.shipping_address":"$input.new_address"},
        source_trajectory_ids=[],policy_version="v1.1").model_dump(mode="json")


def test_frozen_dsl_probe_and_patched_execution_share_procedure():
    spec=next(r for r in generate("W6",919,{"explore":80}) if r["fixture"]["risk"]=="LOW" and r["fixture"]["shipment"]=="PROCESSING")
    contract=parent("modify_address")
    original=copy.deepcopy(contract)
    h0=Hypothesis(hypothesis_id="H0",kind="no_change")
    patch=Hypothesis(hypothesis_id="relax",kind="relax",predicates=(Predicate(field="customer.risk_level",op="eq",value="LOW"),))
    forced=run_probe(spec,"W6",contract=contract)
    blocked=run_probe(spec,"W6",contract=contract,hypothesis=h0.model_dump(mode="json"))
    relaxed=run_probe(spec,"W6",contract=contract,hypothesis=patch.model_dump(mode="json"))
    assert forced["procedure_success"] and relaxed["procedure_success"]
    assert not blocked["procedure_success"] and blocked["execution"]["blocked"]
    assert not any(r["tool_name"]=="update_shipping_address" for r in blocked["tool_audit"])
    assert forced["execution"]["parent"]["procedure_hash"]==relaxed["execution"]["parent"]["procedure_hash"]
    assert relaxed["actual_violations"]==0 and contract==original
    spec["fixture"]["risk"]="HIGH"
    unsafe=run_probe(spec,"W6",contract=contract,hypothesis=patch.model_dump(mode="json"))
    assert unsafe["execution"]["blocked"] and not unsafe["procedure_success"]


def test_real_dsl_postcondition_failure_is_not_probe_success():
    spec=generate("W3",919,{"explore":80})[0]
    contract=parent("refund")
    contract["postconditions"]={"payment.refunded_amount":-1}
    result=run_probe(spec,"W3",contract=contract)
    assert not result["procedure_success"]
    assert result["execution"]["error"]=="skill_postcondition_failed"
    contract["procedure"]=[{"kind":"finish"}]
    with pytest.raises(ValueError,match="mutation"):
        execute_frozen(contract,spec["parameters"],lambda *_:None,"test")


def test_model_strata_cover_declared_shifts_and_threshold_neighbours():
    for world in ("W3","W5","W6"):
        rows=generate(world,919,{"model_validation":8,"model_test":8,"model_stable_validation":4})
        family="modify_address" if world=="W6" else "refund"
        assert len(model_core(family))==8
        tool="update_shipping_address" if world=="W6" else "issue_refund"
        for split in ("model_validation","model_test"):
            selected=[r for r in rows if r["split"]==split]
            assert any((policy(world,tool,controlled_facts(r),r["parameters"])=="allow") !=
                (eligibility(tool,controlled_facts(r),r["parameters"])=="allow") for r in selected)
            if family=="refund":
                assert {r["parameters"]["amount"] for r in selected}>={3000,3001}
        for r in (r for r in rows if r["split"]=="model_stable_validation"):
            assert (policy(world,tool,controlled_facts(r),r["parameters"])=="allow") == (eligibility(tool,controlled_facts(r),r["parameters"])=="allow")
