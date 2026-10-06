"""Execution-aware v1.1 Runtime; public tasks and narrow tool capabilities only."""
import json
import time

from ..evolution_execution import execute_frozen
from ..evolution_schemas import fingerprint, Hypothesis
from ..environment import ToolError
from ..tool_schemas import tool_definitions
from ..active_agent.policy_view import bundle, prediction
from .contracts import ExecutionContract

MUTATIONS={"issue_refund","update_shipping_address","cancel_order"}
PUBLIC_TASK_KEYS={"task_id","family","request","parameters"}


def run_agent(model,task,contract,patch,epoch,tool_call,max_steps=16,decision_only=False, *, single_goal=False, checkpoint=None, persist=None):
    if set(task)!=PUBLIC_TASK_KEYS:raise ValueError("Agent accepts public task fields only")
    if checkpoint and decision_only:raise ValueError("first-decision probes cannot resume prior execution")
    supported_postconditions = {
        "refund": {"payment.refunded_amount": "$state.refund.expected_total"},
        "modify_address": {"order.shipping_address": "$input.new_address"},
        "cancel_order": {"order.status": "CANCELLED"},
    }
    single_goal = bool(single_goal and contract["family"] == task["family"]
                       and contract["postconditions"] == supported_postconditions.get(task["family"]))
    policy=bundle(contract,patch,epoch)
    patch_object=Hypothesis.model_validate(patch)
    tracker = ExecutionContract.restore(checkpoint, task["task_id"], persist) if checkpoint else ExecutionContract(task["task_id"], persist)
    state,history,steps,skills={},[],[],[]
    source = "model"
    termination_source = None
    start=time.perf_counter(); before=model.tokens
    tool_calls=0
    rejected=set()
    def dispatch(name,args,key):
        nonlocal tool_calls
        signature=fingerprint([name,args])
        if name in MUTATIONS and signature in rejected:raise ToolError("repeated_rejected_mutation")
        tool_calls+=1
        try:result=tool_call(name,args,key)
        except ToolError as exc:
            if name in MUTATIONS and exc.code=="business_rule_rejected":rejected.add(signature)
            raise
        state.update({k:v for k,v in result.items() if "." in k})
        return result
    def call(name,args,key):
        return tracker.call(dispatch, name, args, key, source=source)
    errors=[]
    try:
        if tracker.pending():
            tracker.verify_pending(dispatch)
        for name in ("get_customer","get_order","get_shipment","get_payment"):
            call(name,{"order_id":task["parameters"]["order_id"]},"hydrate:"+name)
        if task["family"]=="modify_address":
            call("validate_address",task["parameters"],"hydrate:address")
    except ToolError as exc:errors.append(exc.code)
    outcome="max_steps_exceeded"
    first_decision=None
    for i in range(1 if decision_only else max_steps):
        if tracker.pending():
            outcome = "commit_unknown" if any(o["commit"] != "COMMITTED" for o in tracker.pending()) else "verification_failed"
            break
        if checkpoint and not decision_only and tracker.terminal_ready(task["parameters"], task["family"], single_goal):
            tracker._event("intervention", action="auto_termination")
            termination_source="runtime"; outcome="completed"; break
        eligible=prediction(contract,patch,state,task["parameters"]) if not errors else None
        view={**policy,"effective_gate":"APPLICABLE" if eligible is True else "INAPPLICABLE" if eligible is False else "UNKNOWN"}
        executable=[{"skill_id":contract["skill_id"],"inputs":contract["inputs"],"procedure":contract["procedure"],"postconditions":contract["postconditions"]}] if eligible is True else []
        context={**task,"policy_view":view,"observations":dict(state),"read_errors":errors,
            "executable_skills":executable,"available_tools":tool_definitions(),"history":history[-4:]}
        step={"context":json.loads(json.dumps(context))}
        try:
            action=model.decide(context)
            step['model_response']=getattr(model,'last_response',None)
            step["action"]=action.model_dump()
            if i==0:
                first_decision=(True if action.type=="skill" or (action.type=="tool" and action.name in MUTATIONS) else
                    False if action.type in {"refuse","escalate","stop"} else None)
            if decision_only:
                outcome="decision_only";steps.append(step);break
            if action.type=="skill":
                if action.name!=contract["skill_id"] or eligible is not True:raise ToolError("skill_not_executable")
                if action.arguments!={k:task["parameters"][k] for k in contract["inputs"]}:raise ToolError("skill_input_binding_mismatch")
                source="skill"
                try:
                    result=execute_frozen(contract,task["parameters"],call,"skill:"+str(i),patch_object)
                finally:
                    source="model"
                skills.append(result);step["result"]=result
                if result.get('error')=='repeated_rejected_mutation':
                    outcome='repeated_rejected_mutation';steps.append(step);break
            elif action.type=="tool":
                step["result"]=call(action.name,action.arguments,"action:"+str(i))
            elif action.type=="escalate":
                step["result"]=call("escalate_to_human",{"order_id":task["parameters"]["order_id"],"reason":action.arguments.get("reason","boundary review")},"escalate")
                outcome="escalated"
            else:outcome="completed" if action.type=="stop" else "refused"
            if tracker.pending():
                tracker.verify_pending(dispatch)
            if action.type == "tool" and tracker.terminal_ready(task["parameters"], task["family"], single_goal):
                tracker._event("intervention", action="auto_termination")
                outcome="completed"; termination_source="runtime"
            elif action.type in {"stop", "refuse", "escalate"}:
                termination_source="model"
            steps.append(step);history.append({k:v for k,v in step.items() if k not in {"context","model_response"}})
            if action.type in {"stop","refuse","escalate"} or termination_source == "runtime":break
        except ToolError as exc:
            step["error"]=exc.code;steps.append(step);history.append({"error":exc.code})
            if tracker.pending():
                outcome="commit_unknown" if any(o["commit"] != "COMMITTED" for o in tracker.pending()) else "verification_failed"
                break
            if exc.code=='repeated_rejected_mutation':
                outcome=exc.code;break
        except Exception as exc:
            if getattr(model,"fatal_error",None):raise
            step["error"]="model_error";step["error_type"]=type(exc).__name__
            step['model_response']=getattr(model,'last_response',None);steps.append(step)
            outcome="error";break
    return {"policy_view":policy,"steps":steps,"skill_events":skills,"outcome":outcome,"decision":first_decision,
        "metrics":{"tokens":model.tokens-before,"llm_calls":len(steps),"tool_calls":tool_calls,"seconds":time.perf_counter()-start},
        "protocol":"execution-aware-runtime-v1.1-dev","model_settings":model.settings,
        "termination_source":termination_source,"execution_contract":tracker.checkpoint(),
        "verification_receipts":[r.to_dict() for r in tracker.receipts],"interventions":tracker.metrics()}
