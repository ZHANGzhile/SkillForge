"""Small, explicitly development-only real-model cost measurement."""
import argparse
import json
import math
import os
from pathlib import Path
import time

from scripts.prepare_active_evolution import cost_plan, file_hash, write_new
from skillforge.environment import Environment
from skillforge.evolution_schemas import fingerprint
from skillforge.model import ModelClient
from skillforge.runtime import Runtime
from skillforge.schemas import ExpectedOutcome, Task


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",default="results/active-evolution/v1/development/cost-smoke-v1")
    args=parser.parse_args()
    root=Path(args.output)
    os.environ["SKILLFORGE_MODEL_CONFIG"]="configs/model.hf-sft.json"
    model=ModelClient(url="http://127.0.0.1:8002/v1",model="Qwen3-4B-NF4-SFT")
    model.pin_identity()
    specs=[("refund",{},"completed"),("refund",{"risk":"HIGH"},"escalated"),
        ("refund",{"payment":"FAILED"},"refused"),("modify_address",{},"completed"),
        ("modify_address",{"shipment":"PROCESSING"},"escalated"),("cancel_order",{},"completed")]
    tasks=[]
    for i,(family,fixture,outcome) in enumerate(specs):
        oid,cid=f"DEV-COST-O{i}",f"DEV-COST-C{i}"
        params={"order_id":oid}
        if family=="refund": params["amount"]=1200
        if family=="modify_address": params["new_address"]="Development delivery avenue 202"
        tasks.append(Task(task_id=f"development-cost-{i}",family=family,request=f"Development cost task: {family} using {json.dumps(params)}.",
            customer_id=cid,parameters=params,split="train",template_id=f"development-cost-template-{i}",seed=701,
            fixture={**fixture,"order_id":oid,"customer_id":cid},expected=ExpectedOutcome(allowed_outcomes=[outcome]),
            dataset_id="development-only-cost-smoke"))
    identity={"development_only":True,"model":model.settings,"tasks":[t.model_dump() for t in tasks],
        "files":{p:file_hash(p) for p in [__file__,"skillforge/runtime.py","skillforge/model.py","configs/model.hf-sft.json"]}}
    write_new(root/"identity.json",identity)
    rows=[]
    for task in tasks:
        target=root/(task.task_id+".json")
        if target.exists():
            record=json.loads(target.read_text(encoding="utf-8"))
            if record["identity_hash"]!=fingerprint(identity) or record["result_hash"]!=fingerprint(record["result"]):
                raise ValueError("cost smoke checkpoint mismatch")
        else:
            env=Environment(fixture=task.fixture)
            started=time.perf_counter()
            try:
                result=Runtime(model,max_steps=16).run(task,env)
            finally:
                env.close()
            record={"identity_hash":fingerprint(identity),"result":result,"result_hash":fingerprint(result),"seconds":time.perf_counter()-started}
            write_new(target,record)
        rows.append(record)
        print(json.dumps({"completed":len(rows),"total":len(tasks),"task":task.task_id}),flush=True)
    valid=all(r["result"]["outcome"]!="error" for r in rows)
    if not valid:
        raise RuntimeError("infrastructure/model error in smoke; do not estimate budget")
    seconds=sorted(r["seconds"] for r in rows)
    smoke={"development_only":True,"n":len(rows),"mean_seconds":sum(seconds)/len(rows),
        "p95_seconds":seconds[math.ceil(.95*len(seconds))-1],
        "mean_tokens":sum(r["result"]["metrics"]["tokens"] for r in rows)/len(rows),
        "mean_llm_calls":sum(r["result"]["metrics"]["llm_calls"] for r in rows)/len(rows),
        "mean_tool_calls":sum(r["result"]["metrics"]["tool_calls"] for r in rows)/len(rows),
        "scope":"Six old-policy development tasks; small-sample cost estimate, not new-world research or final cost admission"}
    config=json.loads(Path("configs/active-evolution-v1.json").read_text(encoding="utf-8"))
    write_new(root/"summary.json",smoke)
    write_new(root/"cost-estimate.json",cost_plan(config,smoke))
    print(json.dumps(smoke))


if __name__=="__main__":
    main()
