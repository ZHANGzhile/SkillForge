"""Two consecutive policy epochs; persistent bundle lineage, no weight update."""
import json
from pathlib import Path

from scripts.active_evolution_dataset import generate,audit_splits,state_for_policy,public_candidate
from scripts.active_evolution_worlds import policy
from scripts.evaluate_active_evolution import Evaluator,run_method
from scripts.active_evolution_formal import load_protocol
from skillforge.active_agent.policy_view import bundle
from skillforge.evolution_boundary import parent_identity
from skillforge.evolution_metrics import retention
from skillforge.evolution_registry import immutable_json
from skillforge.evolution_schemas import Hypothesis,fingerprint


def prepare_epoch(root,world,previous_world,seed,counts,contract):
    enlarged={k:(v*8 if 'stable' in k else v) for k,v in counts.items()}
    generated=generate(world,seed,enlarged);rows=[]
    for split,n in counts.items():
        selected=[]
        for row in (r for r in generated if r['split']==split):
            if 'stable' in split and previous_world:
                state=state_for_policy(row)
                if (policy(world,'issue_refund',state,row['parameters'])=='allow')!=(policy(previous_world,'issue_refund',state,row['parameters'])=='allow'):continue
            selected.append(row)
            if len(selected)==n:break
        if len(selected)!=n:raise ValueError('insufficient adjacent-epoch stable support')
        rows.extend(selected)
    audit_splits(rows)
    manifest={'format':'active-continuous-dataset-v1','world':world,'previous_world':previous_world,'seed':seed,
        'policy_epoch':rows[0]['policy_epoch'],'counts':counts,'parent':parent_identity(contract),
        'members':{r['task_id']:{'hash':fingerprint(r),'split':r['split']} for r in rows},
        'scope':'fresh epoch evidence; stable labels unchanged in both adjacent policies and original safety floor'}
    for split in counts:immutable_json(Path(root)/(split+'.json'),[r for r in rows if r['split']==split])
    immutable_json(Path(root)/'manifest.json',manifest);immutable_json(Path(root)/'parent-skill.json',contract)


def paired_measure(evaluator,current,previous,splits,candidate=None,freeze=None):
    rows=evaluator.measure(current,splits,candidate,freeze)
    specs={s['task_id']:s for split in splits for s in evaluator.store.read(split,candidate,freeze)}
    for row in rows:
        public=public_candidate(specs[row['task_id']],evaluator.contract)
        row['baseline_prediction']=previous.predict(public.observations,public.baseline_prediction,public.guard_prediction)
    return rows


def run_continual(root):
    root=Path(root);protocol=load_protocol(root)
    if not (root/'cpu-report.json').exists():raise ValueError('complete independent CPU worlds before continual epochs')
    config=protocol['config'];plan=protocol['continuous_epochs'];seed=plan['seed']
    contract=json.loads((Path(protocol['data_root'])/'W3'/str(config['paired_seeds'][0])/'parent-skill.json').read_text(encoding='utf-8'))
    base=Hypothesis(hypothesis_id='H0',kind='no_change');states={m:base for m in config['methods']}
    parents={m:bundle(contract,base.model_dump(mode='json'),'original-public-policy')['revision'] for m in config['methods']}
    reports=[];previous_world=None
    for epoch,world in enumerate(plan['worlds'],1):
        dataset=root/'continuous'/'datasets'/str(epoch)
        counts=dict(config['splits'])
        counts.update({k:config['model_layer'][k] for k in ('model_validation','model_stable_validation','model_test','model_stable_test')})
        prepare_epoch(dataset,world,previous_world,seed,counts,contract)
        for method in config['methods']:
            directory=root/'continuous'/str(epoch)/method
            result=run_method(dataset,directory/'learning',method,config['learning'],seed,evaluate_test=False)
            before=states[method]
            proposal=json.loads((directory/'learning/effective-version.json').read_text(encoding='utf-8'))
            proposed=Hypothesis.model_validate(proposal['effective_hypothesis'])
            evaluator=Evaluator(dataset,directory/'admission')
            cases=paired_measure(evaluator,proposed,before,('validation','stable_validation'))
            changed=[r for r in cases if r['split']=='validation'];stable=[r for r in cases if r['split']=='stable_validation']
            safe=(not any(r['prediction'] and not r['truth'] for r in changed) and
                sum(r['truth'] and not r['prediction'] for r in changed)<=sum(r['truth'] and not r['baseline_prediction'] for r in changed) and
                not any(r['actual_violations'] for r in cases) and retention(stable)['regression_rate']<=.05)
            accepted=result['status']=='VERIFIED' and safe
            after=proposed if accepted else before
            view=bundle(contract,after.model_dump(mode='json'),evaluator.store.manifest['policy_epoch'],parents[method])
            node={'epoch':epoch,'world':world,'method':method,'parent_revision':parents[method],'bundle':view,
                'previous_hypothesis':before.model_dump(mode='json'),'effective_hypothesis':after.model_dump(mode='json'),
                'accepted_update':accepted,'learning_status':result['status'],'validation':cases,
                'scope':'new epoch node even on rejection; rejected proposal retains previous admitted boundary'}
            immutable_json(directory/'lineage.json',node)
            freeze={'candidate_hash':fingerprint(node),'dataset_hash':fingerprint(evaluator.store.manifest)}
            immutable_json(directory/'evaluation-freeze.json',freeze)
            test=paired_measure(evaluator,after,before,('test','stable_test'),node,freeze)
            metrics={'epoch':epoch,'world':world,'method':method,'accepted_update':accepted,'revision':view['revision'],
                'parent_revision':parents[method],'queries':result['queries'],
                'before_correct':sum(r['baseline_prediction']==r['truth'] for r in test if r['split']=='test'),
                'after_correct':sum(r['prediction']==r['truth'] for r in test if r['split']=='test'),
                'false_allow':sum(r['prediction'] and not r['truth'] for r in test),'false_block':sum(not r['prediction'] and r['truth'] for r in test),
                'actual_violations':sum(r['actual_violations'] for r in test),'retention':retention([r for r in test if r['split']=='stable_test'])}
            metrics['negative_transfer_count']=metrics['retention']['regression_count']
            immutable_json(directory/'test.json',{'freeze':freeze,'cases':test,'metrics':metrics})
            states[method]=after;parents[method]=view['revision'];reports.append(metrics)
            print(json.dumps({'epoch':epoch,'method':method,'accepted_update':accepted,'queries':result['queries']}),flush=True)
        previous_world=world
    immutable_json(root/'continuous-report.json',{'protocol_hash':fingerprint(protocol),'epochs':reports})


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--root',default='results/active-evolution/v1/formal-v1')
    run_continual(parser.parse_args().root)
