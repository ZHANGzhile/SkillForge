"""CPU tests for diagnostic availability; never real Agent learning evidence."""
import json
from pathlib import Path

from skillforge.environment import Environment
from skillforge.schemas import Action
from skillforge.skill_evolution.catalog import Catalog
from skillforge.interview_sprint import adapters as api
from skillforge.interview_sprint.workflows import make_case, verify_workflow, private_items


def test_actual_learned_program_supports_exact_preload_contract():
    root = Path(__file__).resolve().parents[1]/'results/interview-sprint/20261013-v3'
    entries = json.loads((root/'candidate-catalog.json').read_text())
    entry = next(e for e in entries if e['contract']['family']=='order_investigation_dossier')
    case = make_case(139001,'dev')
    class CPU:
        settings = {'engineering_only':True}
        tokens = 0
        def __init__(self): self.actions=iter([Action(type='skill',name=entry['skill_id'],arguments=case.parameters),Action(type='stop')])
        def decide(self,context):return next(self.actions)
    env=Environment(fixture=case.fixture);initial,items=env.snapshot(),private_items(env)
    def tool(name,args,key,source):
        try:return env.call(name,args,case.authenticated_customer_id,key)
        finally:
            if env.audit:env.audit[-1]['decision_origin']=source
    try:
        result=api.run_agent(CPU(),case.public_task(),Catalog(entries),tool,
            public_start={'observations':{},'loaded_refs':{entry['skill_id']:{'revision':entry['revision'],'content_hash':entry['revision']}}})
        assert result['skill_events'][0]['success'] and result['metrics']['decision_calls']==2
        assert verify_workflow(case,initial,env.snapshot(),env.audit,result['outcome'],items,private_items(env))['task_success']
    finally:env.close()
