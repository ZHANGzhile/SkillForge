"""Frozen protocol identity, complete CPU matrix and paired final aggregation."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import importlib.metadata
import json
from pathlib import Path
import random

from scripts.evaluate_active_evolution import run_method
from scripts.prepare_active_evolution import file_hash
from skillforge.active_learning import convergence_metrics
from skillforge.evolution_metrics import retention
from skillforge.evolution_registry import immutable_json
from skillforge.evolution_schemas import fingerprint


def protocol_sources():
    return sorted(set(Path('skillforge').rglob('*.py'))|set(Path('scripts').glob('*active_evolution*.py'))|
        {Path('scripts/run_active_agent_smoke.py')})


def load_protocol(root):
    record=json.loads((Path(root)/'protocol.json').read_text(encoding='utf-8'))
    payload=record['protocol']
    if record['protocol_hash']!=fingerprint(payload):raise ValueError('protocol tampered')
    for path,digest in payload['sources'].items():
        if file_hash(path)!=digest:raise ValueError('frozen protocol source changed: '+path)
    for dataset,digest in payload['dataset_manifests'].items():
        if file_hash(Path(dataset)/'manifest.json')!=digest:raise ValueError('frozen dataset manifest changed')
    return payload


def freeze(root,data,cost):
    config=json.loads(Path('configs/active-evolution-v1.json').read_text(encoding='utf-8'))
    gate=json.loads((Path(cost)/'cost-gate.json').read_text(encoding='utf-8'))
    if not gate['cost_gate_passed']:raise ValueError('new Runtime cost gate has not passed')
    measured=json.loads((Path(cost)/'identity.json').read_text(encoding='utf-8'))
    for path,digest in measured['sources'].items():
        if file_hash(path)!=digest:raise ValueError('Runtime differs from measured cost smoke: '+path)
    datasets={}
    for world in config['worlds']:
        for seed in config['paired_seeds']:
            path=Path(data)/world/str(seed)
            manifest=json.loads((path/'manifest.json').read_text(encoding='utf-8'))
            if manifest['partial_coverage_splits']:raise ValueError('incomplete declared coverage')
            datasets[path.as_posix()]=file_hash(path/'manifest.json')
    payload={'version':'active-self-evolution-formal-v1','config':config,'data_root':str(data),
        'cost_gate_hash':file_hash(Path(cost)/'cost-gate.json'),'cost_root':str(cost),'cost_gate':gate,
        'model_settings':json.loads((Path(cost)/'model-settings.json').read_text(encoding='utf-8')),
        'dataset_manifests':datasets,'sources':{p.as_posix():file_hash(p) for p in protocol_sources()},
        'packages':{p:importlib.metadata.version(p) for p in ('pydantic','numpy')},
        'cpu_order':[[w,s,m] for w in config['worlds'] for s in config['paired_seeds'] for m in config['methods']],
        'continuous_epochs':{'worlds':['W3','W5'],'seed':1701,'parent':'previous admitted public bundle',
            'update':'replace learned overlay; immutable base DSL; fresh belief/evidence each epoch',
            'stable':'exclude states whose gold executability changed between adjacent epochs'},
        'paired_bootstrap':{'seed':99173,'replicates':2000,'unit':'world-seed paired block'},
        'formal_model_execution_enabled':True,'continual_qlora':False,
        'passive_stream':'label-independent SHA256 permutation; all interactions charged, only failure labels update belief',
        'decision_protocol':'separate one-action evaluation at fixed post-hydration state; reads/invalid outputs score UNKNOWN',
        'task_failures':'malformed output and repeated rejected mutation count as failures, not infrastructure retries',
        'research_acceptance':'joint convergence point estimates plus held-out false allow=0, violations=0 and stable regressions<=5%'}
    immutable_json(Path(root)/'protocol.json',{'protocol':payload,'protocol_hash':fingerprint(payload)})
    return payload


def summarize_run(directory,result):
    record=json.loads((Path(directory)/'test.json').read_text(encoding='utf-8'))
    rows=record['cases'];test=[r for r in rows if r['split']=='test'];stable=[{**r,'split':'stable_test'} for r in rows if r['split']=='stable_test']
    return {**result,'test_cases':len(test),'false_allow':sum(r['prediction'] and not r['truth'] for r in test),
        'false_block':sum(not r['prediction'] and r['truth'] for r in test),'actual_violations':sum(r['actual_violations'] for r in rows),
        'retention':retention(stable),'boundary_accuracy':sum(r['prediction']==r['truth'] for r in test)/len(test)}


def aggregate(rows,config):
    cap=config['learning']['max_queries'];by_method={}
    for method in config['methods']:
        group=[r for r in rows if r['method']==method]
        by_method[method]={**convergence_metrics(group,cap),'actual_queries':sum(r['queries'] for r in group),
            'false_allow':sum(r['false_allow'] for r in group),'false_block':sum(r['false_block'] for r in group),
            'actual_violations':sum(r['actual_violations'] for r in group),'stable_regressions':sum(r['retention']['regression_count'] for r in group),
            'published_runs':sum(r['status']=='VERIFIED' for r in group),
            'converged_but_not_admitted':sum(r['queries_to_convergence'] is not None and r['status']!='VERIFIED' for r in group)}
    paired={}
    for r in rows:paired.setdefault((r['world'],r['seed']),{})[r['method']]=r
    blocks=list(paired.values());rng=random.Random(99173);draws=[]
    def contrasts(sample):
        rate=lambda m:sum(b[m]['queries_to_convergence'] is not None for b in sample)/len(sample)
        rmq=lambda m:sum(cap if b[m]['queries_to_convergence'] is None else b[m]['queries_to_convergence'] for b in sample)/len(sample)
        return rate('active')-rate('random'),rmq('active')-rmq('random')
    for _ in range(2000):draws.append(contrasts([rng.choice(blocks) for _ in blocks]))
    intervals=[]
    for i in range(2):
        values=sorted(x[i] for x in draws);intervals.append([values[49],values[1949]])
    a,b=by_method['active'],by_method['random'];denominator=b['restricted_mean_queries_to_convergence']
    reduction=1-a['restricted_mean_queries_to_convergence']/denominator if denominator else None
    joint=a['convergence_rate_within_budget']>=b['convergence_rate_within_budget'] and reduction is not None and reduction>=.2
    stable_cases=sum(r['retention'].get('cases',0) for r in rows if r['method']=='active')
    safe=a['false_allow']==0 and a['actual_violations']==0 and stable_cases>0 and a['stable_regressions']/stable_cases<=.05
    return {'methods':by_method,'paired_bootstrap_95':{'rate_difference':intervals[0],'rmq_difference':intervals[1]},
        'relative_rmq_reduction':reduction,'joint_point_estimate_passed':joint,'heldout_safety_passed':safe,
        'research_hypothesis_passed':joint and safe,
        'scope':'complete frozen CPU boundary matrix; finite-model convergence accompanied by held-out safety/quality, not Agent EOC'}


def run_cpu(root,workers=4):
    root=Path(root);p=load_protocol(root);config=p['config'];rows=[]
    def work(item):
        world,seed,method=item
        directory=root/'cpu'/world/str(seed)/method
        result=run_method(Path(p['data_root'])/world/str(seed),directory,method,config['learning'],seed,evaluate_test=True)
        row={'world':world,'seed':seed,**summarize_run(directory,result)}
        immutable_json(directory/'metrics.json',row)
        return row
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures={executor.submit(work,item):item for item in p['cpu_order']}
        for future in as_completed(futures):
            row=future.result();rows.append(row)
            print(json.dumps({'completed':len(rows),'total':len(futures),'world':row['world'],'seed':row['seed'],
                'method':row['method'],'status':row['status'],'queries':row['queries']}),flush=True)
    rows.sort(key=lambda r:(r['world'],r['seed'],r['method']))
    report={'protocol_hash':fingerprint(p),'runs':rows,'aggregate':aggregate(rows,config)}
    immutable_json(root/'cpu-report.json',report)
    return report


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['freeze','cpu'])
    parser.add_argument('--root',default='results/active-evolution/v1/formal-v1')
    parser.add_argument('--data',default='results/active-evolution/v1/preparation/dataset-v3')
    parser.add_argument('--cost',default='results/active-evolution/v1/development/new-runtime-cost-v3')
    parser.add_argument('--workers',type=int,default=4);args=parser.parse_args()
    if args.action=='freeze':print(json.dumps({'protocol_hash':fingerprint(freeze(args.root,args.data,args.cost))}))
    else:run_cpu(args.root,args.workers)


if __name__=='__main__':main()
