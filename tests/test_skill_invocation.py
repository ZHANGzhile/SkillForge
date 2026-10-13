"""Scripted CPU contracts only; never counted as true-model learning evidence."""
import copy
import pytest
from skillforge.environment import Environment,ToolError
from skillforge.schemas import Action
from skillforge.skill_evolution.catalog import Catalog
from skillforge.interview_sprint.workflows import make_case,private_items,verify_workflow,GOAL
from skillforge.skill_invocation.adapter import TOOL,InvocationAdapter,input_model,recommendation
from skillforge.skill_invocation.runtime import run_agent
from scripts.run_skill_invocation import learned_entry,PARENT
from scripts.run_interview_sprint import read


def execute_actions(actions,*,entry=None,refs=True,mode='B',observations=None,faults=None,catalog=None):
    entry=entry or learned_entry();case=make_case(169001,'dev');env=Environment(fixture=case.fixture,faults=faults)
    initial,items=env.snapshot(),private_items(env)
    class CPU:
        settings={'engineering_only':True};tokens=0
        def __init__(self):self.actions=iter(actions)
        def decide(self,context):return next(self.actions)
    captured=[]
    def tool(name,args,key,source):
        try:return env.call(name,args,case.authenticated_customer_id,key)
        finally:
            if env.audit:env.audit[-1]['decision_origin']=source
    start={'observations':observations or {},'loaded_refs':{entry['skill_id']:{'revision':entry['revision'],'content_hash':entry['revision']}} if refs else {}}
    try:
        result=run_agent(CPU(),case.public_task(),catalog or Catalog([entry]),tool,mode=mode,public_start=start,persist=captured.append)
        verdict=verify_workflow(case,initial,env.snapshot(),env.audit,result['outcome'],items,private_items(env))
        return result,copy.deepcopy(env.audit),verdict,captured
    finally:env.close()


def action(entry=None,inputs=None,**fields):
    entry=entry or learned_entry()
    return Action(type='tool',name=TOOL,arguments={**{'skill_id':entry['skill_id'],'revision':entry['revision'],
        'inputs':{'order_id':'IS13-O-169001'} if inputs is None else inputs},**fields})


def test_correct_input_executes_same_program_with_explicit_receipt_and_raw_action():
    raw=action();r,a,v,checkpoints=execute_actions([raw,Action(type='stop')])
    assert v['task_success'] and len(a)==5 and all(e['decision_origin']=='skill' for e in a)
    assert r['steps'][0]['action']==raw.model_dump() and r['skill_events'][0]['success']
    assert r['invocation_receipts'][0]['status']=='PROGRAM_VERIFIED'
    assert r['metrics']['decision_calls']==2 and r['metrics']['tool_calls']==5
    assert r['termination_source']=='model' and r['interventions']['runtime_intervention_count']==0
    assert any(c['invocation_adapter']['trace'] for c in checkpoints)
    schema=r['steps'][0]['context']['available_tools'][-3]['input_schema']
    # Locate by name because original virtual search/load tools follow the adapter.
    schema=next(t['input_schema'] for t in r['steps'][0]['context']['available_tools'] if t['name']==TOOL)
    assert schema['properties']['inputs']['required']==['order_id']
    assert 'default' not in schema['properties']['inputs']['properties']['order_id']


@pytest.mark.parametrize('inputs',[{}, {'order_id':123},{'order_id':True},{'order_id':None},{'order_id':'IS13-O-169001','extra':'x'}])
def test_missing_wrong_type_or_extra_inputs_are_rejected_without_effects(inputs):
    r,a,_,_=execute_actions([action(inputs=inputs),Action(type='stop')])
    assert r['steps'][0]['error']=='invalid_skill_inputs' and not a
    assert not r['skill_events'] and r['invocation_adapter']['trace'][0]['validation']=='REJECTED'


@pytest.mark.parametrize('mutation,error',[({'skill_id':'Order investigation dossier'},'skill_not_loaded'),
    ({'revision':'0'*64},'skill_revision_mismatch'),({'inputs':{'order_id':'OTHER'}},'skill_input_binding_mismatch')])
def test_no_alias_revision_or_input_repair(mutation,error):
    r,a,_,_=execute_actions([action(**mutation),Action(type='stop')])
    assert r['steps'][0]['error']==error and not a


def test_unloaded_skill_rejected_even_when_present_in_catalog():
    r,a,_,_=execute_actions([action(),Action(type='stop')],refs=False)
    assert r['steps'][0]['error']=='skill_not_loaded' and not a


def test_existing_business_gate_denies_without_hydration_or_writes():
    entry=next(e for e in read(PARENT/'protocol.json')['static_catalog'] if e['contract']['family']=='cancel_order')
    r,a,_,_=execute_actions([action(entry),Action(type='stop')],entry=entry,
        observations={'customer.risk_level':'HIGH','shipment.status':'NOT_STARTED','order.status':'CONFIRMED'})
    event=r['skill_events'][0]
    assert not event['success'] and event['gate_status']=='INAPPLICABLE' and not a
    assert r['invocation_receipts'][0]['status']=='FAILED'


def test_tool_fault_recorded_as_failed_program_receipt():
    r,a,_,_=execute_actions([action(),Action(type='stop')],faults={'get_payment':['timeout']})
    assert r['skill_events'][0]['error']=='timeout' and not r['skill_events'][0]['success']
    assert r['invocation_receipts'][0]['status']=='FAILED'
    assert r['invocation_adapter']['trace'][0]['business_calls'][-1]['error']=='timeout'


def test_business_permissions_are_unchanged():
    r,a,_,_=execute_actions([Action(type='tool',name='cancel_order',arguments={'order_id':'IS13-O-169001'}),Action(type='stop')])
    assert r['steps'][0]['error']=='invalid_tool' and not a


def test_recommendation_uses_public_request_and_metadata_only():
    catalog=Catalog(read(PARENT/'candidate-catalog.json'));case=make_case(169003,'dev')
    rec=recommendation(case.public_task(),catalog,GOAL.required_evidence)
    assert rec['public_results'][0]['skill_id']==learned_entry()['skill_id']
    assert rec['model_search_calls']==0 and rec['system_search_calls']==1
    with pytest.raises(ValueError):recommendation({**case.public_task(),'fixture':case.fixture},catalog,GOAL.required_evidence)


def test_A_preserves_old_preloaded_interface_and_never_exposes_new_tool():
    entry=learned_entry()
    r,a,_,_=execute_actions([Action(type='skill',name=entry['name'],arguments={'order_id':'IS13-O-169001'}),Action(type='stop')],mode='A')
    assert r['steps'][0]['error']=='skill_not_loaded' and not a
    assert TOOL not in {d['name'] for d in r['steps'][0]['context']['available_tools']}


def test_conflicting_loaded_revision_is_not_overridden():
    entry=learned_entry();new=read('results/interview-sprint/reference-followup-20261013-v1/plan.json')['published_entry']
    r,a,_,_=execute_actions([action(revision=new['revision']),Action(type='tool',name='load_skill',arguments={
        'skill_id':entry['skill_id'],'revision':new['revision']}),Action(type='stop')],catalog=Catalog([entry,new]))
    assert r['steps'][0]['error']=='skill_revision_mismatch'
    assert r['steps'][1]['error']=='skill_revision_conflict' and not a


def test_input_types_are_derived_for_multiple_contract_fields_without_defaults():
    entry=next(e for e in read(PARENT/'protocol.json')['static_catalog'] if e['contract']['family']=='refund')
    model=input_model(entry['contract']);schema=model.model_json_schema()
    assert set(schema['required'])=={'order_id','amount'}
    assert schema['properties']['amount']['type']=='integer'
    with pytest.raises(ValueError):model.model_validate({'order_id':'X','amount':True})


def test_original_ownership_guard_still_rejects_an_explicit_bound_invocation():
    entry=learned_entry();case=make_case(169001,'dev');env=Environment(fixture=case.fixture)
    class CPU:
        settings={'engineering_only':True};tokens=0
        def __init__(self):self.actions=iter([action(),Action(type='stop')])
        def decide(self,context):return next(self.actions)
    def tool(name,args,key,source):return env.call(name,args,'UNAUTHORIZED',key)
    try:
        r=run_agent(CPU(),case.public_task(),Catalog([entry]),tool,mode='B',public_start={'observations':{},
            'loaded_refs':{entry['skill_id']:{'revision':entry['revision'],'content_hash':entry['revision']}}})
        assert not r['skill_events'][0]['success'] and r['skill_events'][0]['error']=='permission_denied'
        assert len(env.audit)==1 and env.audit[0]['result'] is None
        assert r['invocation_receipts'][0]['status']=='FAILED'
    finally:env.close()
