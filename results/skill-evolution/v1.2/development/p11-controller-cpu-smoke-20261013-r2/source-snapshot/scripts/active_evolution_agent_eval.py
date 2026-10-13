"""Private evaluator and narrow Agent RPC. Gold never enters model context."""
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time

from scripts.active_evolution_worlds import policy
from skillforge.evolution_registry import immutable_json
from skillforge.evolution_schemas import fingerprint
from skillforge.schemas import Task,ExpectedOutcome


class AgentSession:
    def __init__(self,output,setup):
        self.output=Path(output).resolve();self.output.mkdir(parents=True,exist_ok=True)
        env={k:v for k,v in os.environ.items() if not k.startswith("SKILLFORGE_")}
        env.update(PYTHONUTF8="1",PYTHONIOENCODING="utf-8",HF_HUB_OFFLINE="1",TRANSFORMERS_OFFLINE="1")
        self.errors=(self.output/"agent.stderr.log").open("a",encoding="utf-8")
        self.events=queue.Queue()
        self.process=subprocess.Popen([str(Path('.venv-train/Scripts/python.exe').resolve()),'-m','skillforge.active_agent.worker'],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.errors,text=True,encoding="utf-8",env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
        def read():
            for line in self.process.stdout:self.events.put(line)
            self.events.put(None)
        self.reader=threading.Thread(target=read,daemon=True);self.reader.start()
        try:
            self.send({**setup,"output":str(self.output)})
            ready=self.receive(240)
            if ready["type"]!="ready":raise RuntimeError("Agent startup failed")
            self.settings=ready["settings"]
        except BaseException:
            self.close();raise

    def send(self,value):
        self.process.stdin.write(json.dumps(value,ensure_ascii=False)+"\n");self.process.stdin.flush()

    def receive(self,timeout=120):
        line=self.events.get(timeout=timeout)
        if line is None:raise RuntimeError("Agent exited; inspect agent.stderr.log")
        return json.loads(line)

    def run(self,spec,world,contract,patch,decision_only=False):
        import skillforge.environment as environment
        import skillforge.verifier as verifier
        prior_environment,prior_verifier=environment.eligibility,verifier.eligibility
        oracle=lambda name,state,args:policy(world,name,state,args)
        environment.eligibility=verifier.eligibility=oracle
        env=environment.Environment(fixture=spec["fixture"])
        initial=env.snapshot();started=time.perf_counter()
        try:
            self.send({"type":"run","task":{k:spec[k] for k in ("task_id","family","request","parameters")},
                "contract":contract,"patch":patch,"epoch":spec["policy_epoch"],"decision_only":decision_only})
            while True:
                message=self.receive()
                if message["type"]=="completed":break
                if message["type"]!="tool":raise ValueError("unexpected Agent RPC")
                # Neither snapshots, audit records, gold dispositions nor error
                # details are included in the response capability.
                try:
                    key=spec["task_id"]+":"+fingerprint([message["name"],message["arguments"]])
                    value=env.call(message["name"],message["arguments"],spec["fixture"]["customer_id"],key)
                    self.send({"type":"tool_result","result":value})
                except environment.ToolError as exc:self.send({"type":"tool_result","error":exc.code})
            result=message["result"];final=env.snapshot()
            tool="update_shipping_address" if spec["family"]=="modify_address" else "issue_refund"
            gold=oracle(tool,initial,spec["parameters"])
            expected_state={}
            if gold=="allow":
                expected_state=({"order.shipping_address":spec["parameters"]["new_address"]} if spec["family"]=="modify_address" else
                    {"payment.refunded_amount":initial["payment.refunded_amount"]+spec["parameters"]["amount"]})
            expected=ExpectedOutcome(allowed_outcomes=[{"allow":"completed","refuse":"refused","escalate":"escalated"}[gold]],expected_state=expected_state)
            task=Task(task_id=spec["task_id"],family=spec["family"],request=spec["request"],customer_id=spec["fixture"]["customer_id"],
                parameters=spec["parameters"],split="validation",template_id=spec["template"],seed=0,expected=expected)
            verification=verifier.verify(task,initial,final,env.audit,result["outcome"])
            return {"agent":result,"spec_hash":fingerprint(spec),"truth_executable":gold=="allow",
                "decision_correct":result["decision"] is (gold=="allow"),"verification":verification,
                "tool_audit":env.audit,"initial_state":initial,"final_state":final,
                "seconds":time.perf_counter()-started,"decision_only":decision_only,
                "scope":"private evaluation; this envelope is never sent to Agent/learner"}
        finally:
            env.close();environment.eligibility=prior_environment;verifier.eligibility=prior_verifier

    def close(self):
        if self.process.poll() is None:
            try:self.send({"type":"close"});self.process.wait(timeout=10)
            except (OSError,subprocess.TimeoutExpired):self.process.kill();self.process.wait(timeout=5)
        self.process.stdin.close();self.process.stdout.close();self.errors.close()
        self.reader.join(timeout=2)
