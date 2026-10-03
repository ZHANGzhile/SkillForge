"""Cost-only development smoke, paired unchanged/updated public bundles."""
import argparse
import json
import math
from pathlib import Path

from scripts.active_evolution_agent_eval import AgentSession
from scripts.active_evolution_dataset import generate
from scripts.active_evolution_gpu_lease import GPUServiceLease
from scripts.prepare_active_evolution import cost_plan,file_hash
from scripts.active_evolution_cost import formal_cost_plan
from skillforge.evolution_registry import immutable_json
from skillforge.evolution_schemas import Hypothesis,Predicate,fingerprint


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',default='results/active-evolution/v1/development/new-runtime-cost-v3')
    args=parser.parse_args();root=Path(args.output)
    config=json.loads(Path('configs/active-evolution-v1.json').read_text(encoding='utf-8'))
    contracts={s['family']:s for s in json.loads(Path('results/real-v2-frozen/frozen.json').read_text(encoding='utf-8'))['skills']}
    setup={'config':'configs/training.recovery-v1.json','adapter':'results/training/main-v3/sft/adapter',
        'adapter_sha256':'f195fe00128aa86587b5b37b5a3940116276966162d8f72c5bb222baf445669b'}
    h0=Hypothesis(hypothesis_id='H0',kind='no_change').model_dump(mode='json')
    # Development fixtures/patched bundles are declared here before GPU outcomes.
    # They measure context and execution cost, never choose formal candidates.
    patches={
        'W3':Hypothesis(hypothesis_id='development-numeric',kind='restrict',predicates=(Predicate(field='customer.risk_level',op='eq',value='MEDIUM'),Predicate(field='request.amount',op='gt',value=3000))),
        'W5':Hypothesis(hypothesis_id='development-category',kind='restrict',predicates=(Predicate(field='customer.risk_level',op='eq',value='MEDIUM'),Predicate(field='shipment.status',op='eq',value='PROCESSING'))),
        'W6':Hypothesis(hypothesis_id='development-relax',kind='relax',predicates=(Predicate(field='customer.risk_level',op='eq',value='LOW'),Predicate(field='shipment.status',op='eq',value='PROCESSING')))}
    selected={'W3':(0,6),'W5':(0,2),'W6':(0,1)}
    jobs=[]
    for world in ('W3','W5','W6'):
        rows=generate(world,8801,{'model_validation':8})
        for index in selected[world]:
            for phase,patch in [('before',h0),('after',patches[world].model_dump(mode='json'))]:
                for decision in (False,True):
                    jobs.append({'world':world,'spec':rows[index],'phase':phase,'patch':patch,'decision_only':decision})
    paths=list(Path('skillforge/active_agent').glob('*.py'))+[Path(__file__).resolve().relative_to(Path.cwd()),Path('scripts/active_evolution_agent_eval.py'),Path('scripts/active_evolution_cost.py'),Path('skillforge/evolution_execution.py')]
    identity={'development_only':True,'setup':setup,'jobs':jobs,'config':config,'sources':{p.as_posix():file_hash(p) for p in paths},
        'scope':'12 full-system and 12 separate first-decision development executions; manual patches are cost fixtures, not learned outcome claims'}
    immutable_json(root/'identity.json',identity)
    records=[]
    with GPUServiceLease():
        session=AgentSession(root/'agent',setup)
        try:
            immutable_json(root/'model-settings.json',session.settings)
            for i,job in enumerate(jobs):
                path=root/'tasks'/f'{i:03d}.json'
                if path.exists():
                    saved=json.loads(path.read_text(encoding='utf-8'))
                    if saved['identity_hash']!=fingerprint(identity) or saved['result_hash']!=fingerprint(saved['result']):raise ValueError('smoke checkpoint changed')
                    result=saved['result']
                else:
                    result=session.run(job['spec'],job['world'],contracts[job['spec']['family']],job['patch'],job['decision_only'])
                    immutable_json(path,{'identity_hash':fingerprint(identity),'job':i,'result':result,'result_hash':fingerprint(result)})
                records.append(result)
                print(json.dumps({'completed':len(records),'total':len(jobs),'world':job['world'],'phase':job['phase'],
                    'seconds':round(result['seconds'],2),'tokens':result['agent']['metrics']['tokens'],'outcome':result['agent']['outcome']}),flush=True)
        finally:session.close()
    seconds=sorted(r['seconds'] for r in records)
    smoke={'n':len(records),'mean_seconds':sum(seconds)/len(seconds),'p95_seconds':seconds[math.ceil(.95*len(seconds))-1],
        'mean_tokens':sum(r['agent']['metrics']['tokens'] for r in records)/len(records),
        'mean_llm_calls':sum(r['agent']['metrics']['llm_calls'] for r in records)/len(records),
        'model_errors':sum(r['agent']['outcome']=='error' for r in records),'development_only':True}
    def grouped(decision):
        rows=[r for r in records if r['decision_only']==decision]
        times=sorted(r['seconds'] for r in rows)
        return {'n':len(rows),'p95_seconds':times[math.ceil(.95*len(rows))-1],
            'mean_tokens':sum(r['agent']['metrics']['tokens'] for r in rows)/len(rows),
            'model_errors':sum(r['agent']['outcome']=='error' for r in rows)}
    smoke['full_system']=grouped(False);smoke['decision']=grouped(True)
    plan=formal_cost_plan(config,smoke['full_system'],smoke['decision'])
    immutable_json(root/'summary.json',smoke);immutable_json(root/'cost-gate.json',plan)
    print(json.dumps({'smoke':smoke,'cost_gate':plan}),flush=True)


if __name__=='__main__':main()
