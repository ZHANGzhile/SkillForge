"""CPU interface contracts only; not autonomous model evidence."""
import pytest
from scripts import run_interview_binding as study
from scripts import run_interview_sprint as base
from skillforge.interview_binding.model import INTERFACE_INSTRUCTION, ORIGINAL_PROMPT, SYSTEM_PROMPT
from skillforge.interview_binding.runtime import run_agent
from skillforge.interview_sprint.workflows import make_case, private_items, verify_workflow
from skillforge.skill_evolution.catalog import Catalog
from skillforge.environment import Environment
from skillforge.schemas import Action


def model(actions):
    class CPU:
        settings={'engineering_only':True};tokens=0
        def __init__(self):self.actions=iter(actions)
        def decide(self,context):return next(self.actions)
    return CPU()


def test_common_prompt_has_generic_binding_without_candidate_or_business_sequence():
    assert SYSTEM_PROMPT==ORIGINAL_PROMPT+INTERFACE_INSTRUCTION
    assert 'parameters' in INTERFACE_INSTRUCTION and 'REQUIRED' in INTERFACE_INSTRUCTION
    for forbidden in ['trace_dae7a91522975618','order_id','get_customer','get_payment','get_shipment']:
        assert forbidden not in INTERFACE_INSTRUCTION


def test_runtime_does_not_repair_empty_arguments_or_auto_discover():
    _,_,entry,_=study.parent_metadata();case=make_case(159001,'dev')
    def blocked(*args):raise AssertionError('invalid binding must never reach a business tool')
    result=run_agent(model([Action(type='skill',name=entry['skill_id'],arguments={}),Action(type='stop')]),
        case.public_task(),Catalog([entry]),blocked,public_start={'observations':{},'loaded_refs':{
            entry['skill_id']:{'revision':entry['revision'],'content_hash':entry['revision']}}})
    assert result['steps'][0]['error']=='skill_input_binding_mismatch'
    assert not result['skill_events'] and result['metrics']['tool_calls']==0
    assert result['metrics']['search_calls']==result['metrics']['load_calls']==0
    assert result['interventions']['runtime_intervention_count']==0


def test_model_supplied_bound_arguments_execute_original_five_read_program():
    _,_,entry,_=study.parent_metadata();case=make_case(159002,'dev');env=Environment(fixture=case.fixture)
    initial,items=env.snapshot(),private_items(env)
    def tool(name,args,key,source):return env.call(name,args,case.authenticated_customer_id,key)
    try:
        result=run_agent(model([Action(type='skill',name=entry['skill_id'],arguments=case.parameters),Action(type='stop')]),
            case.public_task(),Catalog([entry]),tool,public_start={'observations':{},'loaded_refs':{
                entry['skill_id']:{'revision':entry['revision'],'content_hash':entry['revision']}}})
        assert result['skill_events'][0]['success'] and len(env.audit)==5
        assert verify_workflow(case,initial,env.snapshot(),env.audit,result['outcome'],items,private_items(env))['task_success']
        assert result['termination_source']=='model' and result['interventions']['runtime_intervention_count']==0
    finally:env.close()


def test_failed_dev_cannot_refill_or_enter_formal(tmp_path):
    base.publish(tmp_path/'discovery_dev/report.json',{'complete':True,'dev_gate_passed':False,'combined_tokens':1300000})
    with pytest.raises(ValueError,match='no formal expansion'):study.prior_tokens(tmp_path,{'prior_charged_tokens':1263669},'formal')


def test_only_explicit_worker_module_can_be_substituted():
    with pytest.raises(ValueError):study.WorkerSubstitution().Popen(['python','-m','other.module'])
