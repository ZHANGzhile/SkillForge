"""Independent read-only evidence audit; never updates a learner or candidate."""
import argparse
import json
from pathlib import Path

from scripts.active_evolution_dataset import EvaluationStore,public_candidate
from scripts.active_evolution_formal import load_protocol,aggregate
from scripts.active_evolution_worlds import policy
from scripts.prepare_active_evolution import file_hash
from skillforge.evolution_registry import immutable_json
from skillforge.evolution_metrics import retention
from skillforge.evolution_schemas import Hypothesis,fingerprint


def audit(root):
    root=Path(root);protocol=load_protocol(root)
    report=json.loads((root/'cpu-report.json').read_text(encoding='utf-8'))
    expected={tuple(x) for x in protocol['cpu_order']}
    if len(report['runs'])!=len(expected) or {(r['world'],r['seed'],r['method']) for r in report['runs']}!=expected:raise ValueError('incomplete CPU matrix')
    audited_cases=audited_queries=0
    for row in report['runs']:
        world,seed,method=row['world'],row['seed'],row['method']
        path=root/'cpu'/world/str(seed)/method
        frozen=json.loads((path/'effective-version.json').read_text(encoding='utf-8'))
        freeze=json.loads((path/'evaluation-freeze.json').read_text(encoding='utf-8'))
        store=EvaluationStore(Path(protocol['data_root'])/world/str(seed))
        specs={s['task_id']:s for split in ('test','stable_test') for s in store.read(split,frozen,freeze)}
        contract=json.loads((store.root/'parent-skill.json').read_text(encoding='utf-8'))
        h=Hypothesis.model_validate(frozen['effective_hypothesis'])
        cases=json.loads((path/'test.json').read_text(encoding='utf-8'))['cases']
        if len(cases)!=len(specs) or {c['task_id'] for c in cases}!=set(specs):raise ValueError('heldout coverage changed')
        for case in cases:
            spec=specs[case['task_id']];public=public_candidate(spec,contract)
            saved=json.loads((path/'evaluator/private-probes'/(spec['task_id']+'.json')).read_text(encoding='utf-8'))
            probe=saved['result']
            if fingerprint(probe)!=saved['result_hash'] or fingerprint(probe)!=case['probe_hash']:raise ValueError('probe evidence modified')
            if fingerprint(spec)!=case['task_hash'] or saved['identity']['task_hash']!=fingerprint(spec):raise ValueError('task evidence binding changed')
            if case['truth']!=probe['procedure_success'] or case['baseline_prediction']!=public.baseline_prediction or case['prediction']!=h.predict(public.observations,public.baseline_prediction,public.guard_prediction):raise ValueError('prediction/truth inconsistent')
            violations=sum(bool(e['state_diff']) and e['committed'] and e['tool_name'] in {'issue_refund','update_shipping_address','cancel_order'} and
                policy(world,e['tool_name'],e['before_state'],e['arguments'])!='allow' for e in probe['tool_audit'])
            if violations!=case['actual_violations']:raise ValueError('violation counter inconsistent')
            audited_cases+=1
        test=[r for r in cases if r['split']=='test'];stable=[r for r in cases if r['split']=='stable_test']
        recalculated={'test_cases':len(test),'false_allow':sum(r['prediction'] and not r['truth'] for r in test),
            'false_block':sum(not r['prediction'] and r['truth'] for r in test),'actual_violations':sum(r['actual_violations'] for r in cases),
            'retention':retention(stable),'boundary_accuracy':sum(r['prediction']==r['truth'] for r in test)/len(test)}
        if any(row[k]!=v for k,v in recalculated.items()):raise ValueError('per-run heldout metrics changed')
        saved_summary=json.loads((path/'summary.json').read_text(encoding='utf-8'))
        if any(row[k]!=saved_summary[k] for k in ('queries','queries_to_convergence','status','method')):raise ValueError('learning summary changed')
        queries=sorted((path/'learner/queries').glob('query_*.json'))
        if len(queries)!=row['queries'] or len(queries)>protocol['config']['learning']['max_queries']:raise ValueError('query accounting changed')
        for qpath in queries:
            q=json.loads(qpath.read_text(encoding='utf-8'))
            if q['row_hash']!=fingerprint({k:v for k,v in q.items() if k!='row_hash'}):raise ValueError('query changed')
            if method=='active' and q['candidate_id']!=q['ranked'][0]['candidate_id']:raise ValueError('Active did not select frozen acquisition maximum')
            audited_queries+=1
    if aggregate(report['runs'],protocol['config'])!=report['aggregate']:raise ValueError('final metrics cannot be reproduced')
    result={'passed':True,'protocol_hash':fingerprint(protocol),'auditor_sha256':file_hash(__file__),
        'runs':len(expected),'heldout_cases':audited_cases,'queries':audited_queries,
        'scope':'independent read-only manifest/probe/prediction/metric audit; not a second GPU execution'}
    immutable_json(root/'independent-audit.json',result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',default='results/active-evolution/v1/formal-v1')
    print(json.dumps(audit(parser.parse_args().root)))
