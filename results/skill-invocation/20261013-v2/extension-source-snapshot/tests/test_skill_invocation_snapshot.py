"""Full scripted RPC/checkpoint regression for the zero-inference failure."""
import json
import queue
import threading
import time
from functools import partial
from types import SimpleNamespace

from scripts import continue_skill_invocation as extension
from scripts import run_interview_sprint as base
from scripts.run_skill_invocation import learned_entry,Condition
from scripts.continue_interview_sprint import safe_coverage
from skillforge.interview_sprint import adapters as old
from skillforge.interview_sprint.workflows import make_case,verify_workflow
from skillforge.skill_invocation.runtime import run_agent
from skillforge.skill_invocation.adapter import TOOL
from skillforge.skill_evolution.catalog import Catalog
from skillforge.skill_evolution.runtime import SYSTEM_PROMPT
from skillforge.schemas import Action
from skillforge.environment import ToolError


def test_structured_rpc_snapshot_admission_and_independent_replay(tmp_path):
    entry=learned_entry();case=make_case(169011,'dev');catalog=Catalog([entry])
    class Session:
        settings={'model':'SCRIPTED_CPU_ONLY','engineering_only':False,'system_prompt':SYSTEM_PROMPT}
        def __init__(self):self.events=queue.Queue();self.replies=queue.Queue();self.thread=None
        def send(self,packet):
            if packet['type']!='run':self.replies.put(packet);return
            def work():
                actions=iter([Action(type='tool',name=TOOL,arguments={'skill_id':entry['skill_id'],'revision':entry['revision'],'inputs':case.parameters}),Action(type='stop')])
                class Model:
                    settings=self.settings;tokens=0
                    def decide(inner,context):
                        inner.tokens+=100;value=next(actions)
                        inner.last_messages=[{'role':'system','content':SYSTEM_PROMPT},{'role':'user','content':json.dumps(context)}]
                        inner.last_response=value.model_dump_json();return value
                def persist(value):
                    self.events.put({'type':'checkpoint','value':value})
                    assert self.replies.get(timeout=10)['type']=='checkpoint_saved'
                def tool(name,args,key,source):
                    self.events.put({'type':'tool','name':name,'arguments':args,'key':key,'source':source})
                    reply=self.replies.get(timeout=10)
                    if reply.get('error'):raise ToolError(reply['error'])
                    return reply['result']
                result=run_agent(Model(),packet['task'],Catalog(packet['catalog']),tool,persist=persist,
                    public_start=packet['public_start'],**packet['limits'])
                self.events.put({'type':'completed','result':result})
            self.thread=threading.Thread(target=work);self.thread.start()
        def receive(self,timeout=10):return self.events.get(timeout=min(timeout,10))
    config={'limits':{'max_steps':12,'max_search':3,'max_load':3,'max_tokens':65536},
        'budget':{'project_max_tokens':20000,'project_max_wall_seconds':200}}
    collect=old.bind(extension.collection,{'verify_workflow':verify_workflow,'evaluate_static':safe_coverage,
        'prepare_snapshot':old.bind(extension.prepare,{'run_agent':run_agent})})
    session=Session();folder=tmp_path/'rpc'
    row,status=collect(Condition(session,'B',entry),case,catalog,folder,config,0,0,time.perf_counter())
    session.thread.join(timeout=10)
    assert status['completed'] and row['verification']['task_success'] and status['charged_tokens']==200
    start={'observations':{},'loaded_refs':{entry['skill_id']:{'revision':entry['revision'],'content_hash':entry['revision']}}}
    proof=old.bind(base.audit_arm,{'api':SimpleNamespace(run_agent=partial(run_agent,mode='B',public_start=start))})(
        folder,case,catalog,session.settings,config['limits'],(0,20000,0,200))
    assert proof['passed'] and proof['replay_tool_calls']==5
    assert row['agent']['steps'][0]['action']['name']==TOOL
    assert len(row['agent']['invocation_adapter']['trace'])==1
