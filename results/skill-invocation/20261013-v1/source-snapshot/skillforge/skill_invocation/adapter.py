"""Loaded VERIFIED contracts determine schemas; model arguments are never filled."""
from pydantic import Field, ValidationError, create_model
from skillforge.environment import ToolError
from skillforge.schemas import SkillContract, StrictModel
from skillforge.tool_schemas import INPUTS
from skillforge.skills import gate, hydrate, execute
from skillforge.evolution_schemas import fingerprint
from skillforge.evolution_common.artifacts import clone
from skillforge.skill_evolution.catalog import public_condition
from skillforge.policies import MUTATIONS

TOOL = 'execute_verified_skill'


def input_model(contract):
    """Infer only declared inputs from their actual typed business-tool uses.

    SkillContract v1 has input names rather than types. No guessed defaults are
    allowed: an unused/untyped input rejects schema generation. Constraints from
    every occurrence are intersected, including strict scalar types.
    """
    skill=SkillContract.model_validate(contract);uses={key:[] for key in skill.inputs}
    for step in skill.procedure:
        if step.kind!='call':continue
        if step.tool not in INPUTS:raise ValueError('unknown typed business tool')
        props=INPUTS[step.tool].model_json_schema()['properties']
        for arg,value in step.arguments.items():
            if isinstance(value,str) and value.startswith('$input.'):
                key=value[7:]
                if key not in uses or arg not in props:raise ValueError('untyped contract input use')
                uses[key].append(props[arg])
    fields={};types={'string':str,'integer':int,'number':float,'boolean':bool}
    for key,schemas in uses.items():
        if not schemas or len({s.get('type') for s in schemas})!=1 or schemas[0].get('type') not in types:
            raise ValueError('missing or inconsistent scalar input type: '+key)
        constraints={'strict':True}
        for json_key,field_key,combine in [('minLength','min_length',max),('maxLength','max_length',min),
                ('minimum','ge',max),('maximum','le',min),('exclusiveMinimum','gt',max),('exclusiveMaximum','lt',min)]:
            values=[s[json_key] for s in schemas if json_key in s]
            if values:constraints[field_key]=combine(values)
        unsupported={'enum','pattern','anyOf','oneOf','allOf','$ref'}
        if any(unsupported.intersection(s) for s in schemas):raise ValueError('unsupported input constraint')
        fields[key]=(types[schemas[0]['type']],Field(...,**constraints))
    return create_model('VerifiedSkillInputs',__base__=StrictModel,**fields)


def recommendation(task,catalog,allowed_tools):
    if set(task)!={'task_id','family','request','parameters'}:raise ValueError('public task only')
    # The full-library ranking consumes request text and public metadata only.
    # Permission filtering is independent of workflow identity and EOC.
    query=task['request'];results,audit=catalog.search_audited(query,top_k=5)
    eligible=[r for r in results if set(r['required_tools'])<=set(allowed_tools)]
    chosen=eligible[:1]
    return {'schema':'public-candidate-recommendation-v1','query':query,'public_results':chosen,
        'search_audit':audit,'discovery_source':'system_public_metadata','model_search_calls':0,
        'system_search_calls':1,'system_preload_count':len(chosen),
        'loaded_refs':{r['skill_id']:{'revision':r['revision'],'content_hash':r['revision']} for r in chosen}}


class InvocationAdapter:
    def __init__(self,catalog,refs,task,*,recommendation_view=None):
        self.catalog,self.refs,self.task=catalog,clone(refs),clone(task)
        self.recommendation=recommendation_view;self.context=None;self.trace=[];self.events=[];self.origin=None
        self.models={}
        for sid,ref in refs.items():
            entry=catalog.get(sid,ref['revision'])
            if ref!={'revision':entry['revision'],'content_hash':entry['revision']}:raise ValueError('loaded content mismatch')
            self.models[(sid,ref['revision'])]=input_model(entry['contract'])

    def definition(self):
        choices=[];gates=[]
        for sid,ref in sorted(self.refs.items()):
            entry=self.catalog.get(sid,ref['revision']);model=self.models[(sid,ref['revision'])]
            choices.append({'type':'object','additionalProperties':False,
                'properties':{'skill_id':{'type':'string','const':sid},'revision':{'type':'string','const':ref['revision']},
                              'inputs':model.model_json_schema()},'required':['skill_id','revision','inputs']})
            gates.append({'skill_id':sid,'revision':ref['revision'],
                'preconditions':[public_condition(c) for c in entry['contract']['preconditions']],
                'forbidden_conditions':[public_condition(c) for c in entry['contract']['forbidden_conditions']],
                'live_status_location':'catalog.loaded_skills[].gate'})
        schema=choices[0] if len(choices)==1 else {'oneOf':choices} if choices else {'not':{}}
        out={'name':TOOL,'description':'Execute an explicitly selected loaded VERIFIED Skill. Supply its exact skill_id, revision and every required input in inputs. The original applicability Gate is enforced. Returns execution result and a contract verification receipt.',
            'input_schema':schema,'output_schema':{'type':'object','required':['skill_event','verification_receipt'],
                'properties':{'skill_event':{'type':'object'},'verification_receipt':{'type':'object'}}},
            'side_effect':any(n['tool'] in MUTATIONS for sid,ref in self.refs.items() for n in self.catalog.get(sid,ref['revision'])['contract']['procedure'] if n['kind']=='call'),
            'applicability_gates':gates,'execution_authority':'unchanged Gate, DSL, tool schemas and ownership Guard'}
        if self.recommendation:
            out['system_recommended_candidates']=clone(self.recommendation['public_results'])
        return out

    def observe(self,context):
        self.context=clone(context)

    def validate(self,args):
        if type(args) is not dict or set(args)!={'skill_id','revision','inputs'}:raise ToolError('invalid_skill_invocation_arguments')
        sid,rev=args['skill_id'],args['revision']
        if type(sid) is not str or type(rev) is not str:raise ToolError('invalid_skill_reference_type')
        loaded={v['skill_id']:v for v in self.context['catalog']['loaded_skills']}
        if sid not in loaded:raise ToolError('skill_not_loaded')
        if loaded[sid]['revision']!=rev:raise ToolError('skill_revision_mismatch')
        # Only schemas produced for this explicitly pinned loaded set are valid.
        if (sid,rev) not in self.models:raise ToolError('skill_not_in_invocation_schema')
        entry=self.catalog.get(sid,rev);skill=SkillContract.model_validate(entry['contract'])
        for dep in entry['dependencies']:
            if loaded.get(dep['skill_id'],{}).get('revision')!=dep['revision']:raise ToolError('skill_dependency_not_loaded')
        try:inputs=self.models[(sid,rev)].model_validate(args['inputs']).model_dump()
        except ValidationError as exc:raise ToolError('invalid_skill_inputs') from exc
        if inputs!={k:self.task['parameters'].get(k) for k in skill.inputs}:raise ToolError('skill_input_binding_mismatch')
        return skill,inputs

    def invoke(self,args,call,key,persist):
        record={'sequence':len(self.trace),'raw_arguments':clone(args),'validation':'PENDING',
            'context_hash':fingerprint(self.context),'business_calls':[]}
        self.trace.append(record);persist()
        try:
            skill,inputs=self.validate(args);record['validation']='VALID';persist()
            state=clone(self.context['observations'])
            def tracked(name,arguments,request_id):
                item={'tool':name,'arguments':clone(arguments),'request_id':request_id,'source':self.origin}
                record['business_calls'].append(item);persist()
                try:
                    value=call(name,arguments,request_id,self.origin);item['result']=clone(value);return value
                except ToolError as exc:item['error']=exc.code;raise
                finally:persist()
            self.origin='gate/hydrate'
            try:hydrate(skill,state,inputs,tracked,key+':gate')
            finally:self.origin=None
            disposition=gate(skill,state,inputs);record['gate']=disposition.model_dump();persist()
            self.origin='skill'
            try:event=execute(skill,inputs,state,tracked,key+':program')
            finally:self.origin=None
            event.update(revision=args['revision'],invocation_interface=TOOL)
            self.events.append(event)
            body={'schema':'skill-invocation-verification-v1','skill_id':skill.skill_id,'revision':args['revision'],
                'input_hash':fingerprint(inputs),'gate_status':disposition.status,
                'status':'PROGRAM_VERIFIED' if event['success'] else 'FAILED',
                'postcondition_check':clone(event.get('verification',{})),
                'observed_program_results_hash':fingerprint(event['internal_steps']),
                'scope':'unchanged DSL contract postconditions; independent task EOC evaluated externally'}
            receipt={**body,'receipt_hash':fingerprint(body)}
            record.update(success=event['success'],skill_event=clone(event),verification_receipt=receipt);persist()
            return {'skill_event':event,'verification_receipt':receipt}
        except (ToolError,ValueError) as exc:
            record.update(validation='REJECTED' if record['validation']=='PENDING' else record['validation'],
                success=False,error=getattr(exc,'code',str(exc)));persist();raise

    def snapshot(self):
        return clone({'trace':self.trace,'events':self.events,'pinned_loaded_refs':self.refs,
            'system_candidate_discovery':self.recommendation,'automatic_argument_fill':False,
            'automatic_id_repair':False,'automatic_termination':False})
