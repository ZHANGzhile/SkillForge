import json
import subprocess
import sys

import pytest

from skillforge.active_agent.policy_view import bundle, prediction
from skillforge.active_agent.runtime import run_agent
from skillforge.environment import Environment
from skillforge.environment import ToolError
from skillforge.evolution_schemas import Hypothesis, Predicate
from skillforge.schemas import Action
from test_evolution_execution import parent


class PublicModel:
    tokens=0
    settings={"model":"scripted-test-only"}
    def decide(self,context):
        self.tokens+=1
        assert not ({"fixture","expected","initial_state","gold","world"}&set(context))
        if context["history"]:return Action(type="stop")
        if context["executable_skills"]:
            return Action(type="skill",name=context["executable_skills"][0]["skill_id"],arguments=context["parameters"])
        return Action(type="escalate")


def test_public_bundle_and_runtime_never_receive_gold():
    contract=parent("refund");patch=Hypothesis(hypothesis_id="H0",kind="no_change").model_dump()
    task={"task_id":"dev","family":"refund","request":"Refund 1000","parameters":{"order_id":"O1","amount":1000}}
    env=Environment()
    try:
        result=run_agent(PublicModel(),task,contract,patch,"opaque-epoch",lambda n,a,k:env.call(n,a,"C1",k))
        assert result["outcome"]=="completed" and result["skill_events"][0]["success"]
        assert env.snapshot()["payment.refunded_amount"]==1000
        assert result["decision"] is True
        with pytest.raises(ValueError,match="public task"):
            run_agent(PublicModel(),{**task,"expected":"secret"},contract,patch,"epoch",lambda *_:None)
    finally:env.close()


def test_policy_revision_changes_only_from_public_bundle():
    c=parent("refund")
    h0=Hypothesis(hypothesis_id="H0",kind="no_change").model_dump()
    h1=Hypothesis(hypothesis_id="p",kind="restrict",predicates=(Predicate(field="request.amount",op="gt",value=3000),)).model_dump()
    assert bundle(c,h0,"epoch")["revision"]!=bundle(c,h1,"epoch")["revision"]
    facts={"customer.risk_level":"LOW","payment.status":"CAPTURED","payment.captured_amount":10000,"payment.refunded_amount":0}
    assert prediction(c,h1,facts,{"amount":3000}) is True
    assert prediction(c,h1,facts,{"amount":3001}) is False
    assert prediction(c,h1,{},{"amount":3001}) is None


def test_repeated_rejected_write_is_failed_not_reexecuted_or_scored_success():
    class Repeating(PublicModel):
        def decide(self,context):return Action(type='tool',name='issue_refund',arguments=context['parameters'])
    calls=[]
    env=Environment()
    def guarded(name,args,key):
        if name=='issue_refund':
            calls.append(name);raise ToolError('business_rule_rejected')
        return env.call(name,args,'C1',key)
    task={'task_id':'t','family':'refund','request':'Refund','parameters':{'order_id':'O1','amount':1000}}
    try:
        result=run_agent(Repeating(),task,parent('refund'),Hypothesis(hypothesis_id='H0',kind='no_change').model_dump(),'e',guarded)
        assert calls==['issue_refund']
        assert result['outcome']=='repeated_rejected_mutation'
        assert len(result['steps'])==2
        assert env.snapshot()['payment.refunded_amount']==0
    finally:env.close()


@pytest.mark.parametrize("mode",["file","module"])
def test_agent_process_cannot_read_gold_or_private_files(tmp_path,mode):
    private=tmp_path/"gold.json";private.write_text('SECRET GOLD')
    output=tmp_path/"agent";output.mkdir()
    request={"guard_test":True,"output":str(output)}
    if mode=="file":request["path"]=str(private)
    result=subprocess.run([sys.executable,"-m","skillforge.active_agent.worker"],input=json.dumps(request)+'\n',capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)=={"type":"denied"}
