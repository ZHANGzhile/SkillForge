"""Execute the frozen parent DSL under an experimental boundary patch.

No new-world policy or expected outcomes enter this module. The environment
still guards every mutation. Forced applicability probes bypass only the Skill
gate, never the environment's guard.
"""
from .evolution_boundary import parent_identity, public_predictions
from .evolution_schemas import Hypothesis
from .schemas import SkillContract
from .skills import execute, refund_facts


def execute_frozen(contract, parameters, call, key, patch=None, force_probe=False):
    skill=SkillContract.model_validate(contract)
    mutation={"refund":"issue_refund","modify_address":"update_shipping_address","cancel_order":"cancel_order"}[skill.family]
    verify_read="get_payment" if skill.family=="refund" else "get_order"
    calls=[step.tool for step in skill.procedure if step.kind=="call"]
    if mutation not in calls or verify_read not in calls[calls.index(mutation)+1:] or not skill.postconditions:
        raise ValueError("frozen procedure must contain mutation, subsequent read and postconditions")
    if any(name not in parameters for name in skill.inputs):
        raise ValueError("frozen Skill inputs incomplete")
    patch=patch or Hypothesis(hypothesis_id="H0",kind="no_change")
    if patch.kind=="other":
        raise ValueError("OTHER cannot execute")
    state={}
    # Same read schedule for all arms. Values come exclusively from tool reads.
    for name in ("get_customer","get_order","get_shipment","get_payment"):
        result=call(name,{"order_id":parameters["order_id"]},key+":"+name)
        state.update({k:v for k,v in result.items() if "." in k})
    if skill.family=="modify_address":
        state.update(call("validate_address",{"order_id":parameters["order_id"],"new_address":parameters["new_address"]},key+":address"))
    facts=refund_facts(state,parameters) if skill.family=="refund" else dict(state)
    if skill.family=="refund":
        facts["request.amount"]=parameters["amount"]
        captured,refunded=facts.get("payment.captured_amount"),facts.get("payment.refunded_amount")
        if type(captured) is int and type(refunded) is int:
            facts["payment.remaining_amount"]=captured-refunded
    baseline,guard=public_predictions(contract,facts,parameters)
    prediction=patch.predict(facts,baseline,guard)
    receipt={"parent":parent_identity(contract),"hypothesis":patch.model_dump(mode="json"),
        "boundary_prediction":prediction,"forced_applicability_probe":force_probe,
        "execution_protocol":"frozen-parent-dsl-v1"}
    if not force_probe and prediction is not True:
        return {**receipt,"success":False,"blocked":True,"internal_steps":[],
            "gate_status":"UNKNOWN" if prediction is None else "INAPPLICABLE"}
    # The patched gate was evaluated above. Reapplying the old Skill gate here
    # would make legitimate relaxations impossible. The procedure is unchanged.
    event=execute(skill,parameters,state,call,key+":procedure",enforce_gate=False)
    event["parent_gate_status"]=event["gate_status"]
    event.update(receipt)
    event["gate_status"]="FORCED_PROBE" if force_probe else "APPLICABLE"
    event["applicable"]=prediction
    event["blocked"]=False
    return event
