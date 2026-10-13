"""Small invocation extension; original Runtime function code is unchanged."""
import hashlib
from pathlib import Path
from skillforge.interview_sprint import adapters as old
from skillforge.execution_aware.contracts import ExecutionContract
from .adapter import InvocationAdapter,TOOL,recommendation

PROTOCOL='contract-guided-skill-invocation-v1'
MODES={'A','B','C'}


def sources():
    root=Path(__file__).resolve().parents[2];out=old.sources()
    for p in [*Path(__file__).parent.glob('*.py'),*(root/'scripts'/n for n in ['run_skill_invocation.py','continue_interview_sprint.py','collect_skill_evolution_learn.py','evolution_budget.py','evolution_forks.py','run_skill_evolution.py'])]:
        out[p.relative_to(root).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def run_agent(model,task,catalog,tool_call,*,mode='A',public_start=None,persist=None,checkpoint=None,**limits):
    if mode not in MODES:raise ValueError('unknown invocation condition')
    if checkpoint is not None:raise ValueError('this dev adapter does not claim checkpoint recovery support')
    start=old.clone(public_start or {'observations':{},'loaded_refs':{}});rec=None
    if mode=='C':
        if start['loaded_refs']:raise ValueError('C recommendation must start before assisted preload')
        rec=recommendation(task,catalog,old.GOAL.required_evidence)
        start['loaded_refs']=rec['loaded_refs']
    adapter=InvocationAdapter(catalog,start['loaded_refs'],task,recommendation_view=rec)
    tracker=None
    def save_adapter():
        # The unchanged Runtime tracker persist barrier saves both nested tool
        # progress and adapter evidence before effects, via persist_with_adapter.
        if tracker is not None and tracker.persist:tracker.persist(tracker.checkpoint())
    class Contract(ExecutionContract):
        def __init__(self,*args,**kwargs):
            nonlocal tracker
            super().__init__(*args,**kwargs);tracker=self
        def call(self,dispatch,name,args,key,source='model'):
            if name==TOOL and mode!='A':
                return adapter.invoke(args,lambda n,a,k,s:super(Contract,self).call(dispatch,n,a,k,source=s),key,save_adapter)
            return super().call(dispatch,name,args,key,source=source)
    class Observed:
        def __init__(self,inner):self.inner=inner
        def __getattr__(self,name):return getattr(self.inner,name)
        def decide(self,context):adapter.observe(context);return self.inner.decide(context)
    def definitions():return old.readonly_tools()+([adapter.definition()] if mode!='A' else [])
    def effect(name,args,key,source):return tool_call(name,args,key,adapter.origin or source)
    def persist_with_adapter(value):
        if persist:persist({**value,'invocation_adapter':adapter.snapshot(),'invocation_mode':mode})
    runtime=old.bind(old.run_agent,{'ExecutionContract':Contract,'tool_definitions':definitions,
        'PROTOCOL':PROTOCOL+':'+mode,'runtime_sources':sources})
    result=runtime(Observed(model),task,catalog,effect,public_start=start,persist=persist_with_adapter,**limits)
    result['skill_events'].extend(adapter.events)
    result['invocation_adapter']=adapter.snapshot();result['invocation_mode']=mode
    result['invocation_receipts']=[r['verification_receipt'] for r in adapter.trace if 'verification_receipt' in r]
    return result
