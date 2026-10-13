"""CPU contracts for bounded interface follow-up, not autonomous evidence."""
import pytest
from skillforge.environment import Environment
from skillforge.schemas import Action
from skillforge.interview_sprint import adapters as old
from skillforge.interview_sprint.workflows import GOAL, make_case, private_items, verify_workflow
from skillforge.interview_reference.runtime import run_agent
from skillforge.interview_reference.model import SYSTEM_PROMPT, ORIGINAL_PROMPT
from skillforge.skill_evolution.catalog import Catalog
from skillforge.skill_evolution.governance import identities
from scripts.run_interview_reference import parent_metadata, WorkerSubstitution


def test_metadata_revision_preserves_actual_learned_program_and_boundary():
    parent,entry,published,governance=parent_metadata()
    assert entry['name']==entry['skill_id'] and entry['contract']['version']==parent['contract']['version']+1
    assert entry['parent_revision']==parent['revision'] and governance['revision_kind']=='metadata_revision'
    assert identities(parent['contract'],GOAL.identity)==identities(published['contract'],GOAL.identity)
    assert parent['contract']['procedure']==published['contract']['procedure']


def test_new_runtime_keeps_strict_identifiers_and_does_not_auto_search():
    parent,entry,published,governance=parent_metadata()
    case=make_case(149001,'dev');env=Environment(fixture=case.fixture)
    class CPU:
        settings={'engineering_only':True};tokens=0
        def __init__(self):self.actions=iter([Action(type='skill',name=parent['name'],arguments=case.parameters),Action(type='stop')])
        def decide(self,context):return next(self.actions)
    result=run_agent(CPU(),case.public_task(),Catalog([published]),lambda *args:None,
        public_start={'observations':{},'loaded_refs':{published['skill_id']:{'revision':published['revision'],'content_hash':published['revision']}}})
    assert result['steps'][0]['error']=='skill_not_loaded'
    assert result['metrics']['search_calls']==0 and result['metrics']['load_calls']==0
    assert result['interventions']['runtime_intervention_count']==0
    env.close()


def test_exact_metadata_executes_same_five_reads_in_existing_dsl():
    parent,entry,published,governance=parent_metadata();case=make_case(149002,'dev')
    class CPU:
        settings={'engineering_only':True};tokens=0
        def __init__(self):self.actions=iter([Action(type='skill',name=published['skill_id'],arguments=case.parameters),Action(type='stop')])
        def decide(self,context):return next(self.actions)
    env=Environment(fixture=case.fixture);initial,items=env.snapshot(),private_items(env)
    def tool(name,args,key,source):return env.call(name,args,case.authenticated_customer_id,key)
    try:
        result=run_agent(CPU(),case.public_task(),Catalog([published]),tool,
            public_start={'observations':{},'loaded_refs':{published['skill_id']:{'revision':published['revision'],'content_hash':published['revision']}}})
        assert result['skill_events'][0]['success']
        assert verify_workflow(case,initial,env.snapshot(),env.audit,result['outcome'],items,private_items(env))['task_success']
        assert len(env.audit)==5
    finally:env.close()


def test_prompt_and_launcher_change_are_explicit_and_narrow():
    assert SYSTEM_PROMPT.startswith(ORIGINAL_PROMPT) and 'first' in SYSTEM_PROMPT and 'search_skills once' in SYSTEM_PROMPT
    assert 'trace_dae7a91522975618' not in SYSTEM_PROMPT and 'get_payment' not in SYSTEM_PROMPT[len(ORIGINAL_PROMPT):]
    with pytest.raises(ValueError):WorkerSubstitution().Popen(['python','-m','other.module'])


def test_correct_id_with_missing_arguments_is_rejected_without_runtime_repair():
    parent,entry,published,governance=parent_metadata();case=make_case(149003,'dev')
    class CPU:
        settings={'engineering_only':True};tokens=0
        def __init__(self):self.actions=iter([Action(type='skill',name=published['skill_id'],arguments={}),Action(type='stop')])
        def decide(self,context):return next(self.actions)
    def blocked(*args):raise AssertionError('invalid binding must not reach the business tool')
    result=run_agent(CPU(),case.public_task(),Catalog([published]),blocked,
        public_start={'observations':{},'loaded_refs':{published['skill_id']:{'revision':published['revision'],'content_hash':published['revision']}}})
    assert result['steps'][0]['error']=='skill_input_binding_mismatch'
    assert not result['skill_events'] and result['metrics']['tool_calls']==0
    assert result['interventions']['runtime_intervention_count']==0
