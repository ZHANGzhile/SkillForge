"""Agent-only runtime. Environment is a narrow RPC callable, never an object."""
import json
import time

from ..evolution_execution import execute_frozen
from ..evolution_schemas import fingerprint, Hypothesis
from ..environment import ToolError
from ..tool_schemas import tool_definitions
from .policy_view import bundle, prediction

MUTATIONS={"issue_refund","update_shipping_address","cancel_order"}
PUBLIC_TASK_KEYS={"task_id","family","request","parameters"}


def run_agent(model,task,contract,patch,epoch,tool_call,max_steps=16,decision_only=False):
    if set(task)!=PUBLIC_TASK_KEYS:raise ValueError("Agent accepts public task fields only")
    policy=bundle(contract,patch,epoch)
    patch_object=Hypothesis.model_validate(patch)
    state,history,steps,skills={},[],[],[]
    start=time.perf_counter(); before=model.tokens
    tool_calls=0
    def call(name,args,key):
        nonlocal tool_calls
        tool_calls+=1
        result=tool_call(name,args,key)
        state.update({k:v for k,v in result.items() if "." in k})
        return result
    errors=[]
    try:
        for name in ("get_customer","get_order","get_shipment","get_payment"):
            call(name,{"order_id":task["parameters"]["order_id"]},"hydrate:"+name)
        if task["family"]=="modify_address":
            call("validate_address",task["parameters"],"hydrate:address")
    except ToolError as exc:errors.append(exc.code)
    outcome="max_steps_exceeded"
    first_decision=None
    for i in range(1 if decision_only else max_steps):
        eligible=prediction(contract,patch,state,task["parameters"]) if not errors else None
        view={**policy,"effective_gate":"APPLICABLE" if eligible is True else "INAPPLICABLE" if eligible is False else "UNKNOWN"}
        executable=[{"skill_id":contract["skill_id"],"inputs":contract["inputs"],"procedure":contract["procedure"],"postconditions":contract["postconditions"]}] if eligible is True else []
        context={**task,"policy_view":view,"observations":dict(state),"read_errors":errors,
            "executable_skills":executable,"available_tools":tool_definitions(),"history":history[-4:]}
        step={"context":json.loads(json.dumps(context))}
        try:
            action=model.decide(context)
            step["action"]=action.model_dump()
            if first_decision is None:
                first_decision=(True if action.type=="skill" or (action.type=="tool" and action.name in MUTATIONS) else
                    False if action.type in {"refuse","escalate","stop"} else None)
            if decision_only:
                outcome="decision_only";steps.append(step);break
            if action.type=="skill":
                if action.name!=contract["skill_id"] or eligible is not True:raise ToolError("skill_not_executable")
                if action.arguments!={k:task["parameters"][k] for k in contract["inputs"]}:raise ToolError("skill_input_binding_mismatch")
                result=execute_frozen(contract,task["parameters"],call,"skill:"+str(i),patch_object)
                skills.append(result);step["result"]=result
            elif action.type=="tool":
                step["result"]=call(action.name,action.arguments,"action:"+str(i))
            elif action.type=="escalate":
                step["result"]=call("escalate_to_human",{"order_id":task["parameters"]["order_id"],"reason":action.arguments.get("reason","boundary review")},"escalate")
                outcome="escalated"
            else:outcome="completed" if action.type=="stop" else "refused"
            steps.append(step);history.append({k:v for k,v in step.items() if k!="context"})
            if action.type in {"stop","refuse","escalate"}:break
        except ToolError as exc:
            step["error"]=exc.code;steps.append(step);history.append({"error":exc.code})
        except Exception as exc:
            if getattr(model,"fatal_error",None):raise
            step["error"]="model_error";step["error_type"]=type(exc).__name__;steps.append(step)
            outcome="error";break
    return {"policy_view":policy,"steps":steps,"skill_events":skills,"outcome":outcome,"decision":first_decision,
        "metrics":{"tokens":model.tokens-before,"llm_calls":len(steps),"tool_calls":tool_calls,"seconds":time.perf_counter()-start},
        "protocol":"active-agent-runtime-v1","model_settings":model.settings}
