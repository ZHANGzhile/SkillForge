"""Post-hoc, read-only attribution of all effective continual A test pairs."""
from collections import Counter
from pathlib import Path

from scripts.active_evolution_dataset import EvaluationStore
from scripts.execution_aware_formal import load, read
from scripts.prepare_active_evolution import file_hash
from scripts.recover_execution_interruption import identity_for
from skillforge.evolution_registry import immutable_json
from skillforge.evolution_schemas import fingerprint


def attribute(root):
    root = Path(root); protocol = load(root); rows = []; inputs = {}
    for epoch, world in enumerate(protocol['config']['continual']['worlds'], 1):
        directory = root/'model-layer/continuous'/str(epoch)
        activation = read(directory/'activation.json'); freeze = read(directory/'evaluation-freeze.json')
        dataset = root/'continuous/datasets'/str(epoch); store = EvaluationStore(dataset)
        contract = read(dataset/'parent-skill.json')
        for runtime in ('old', 'new'):
            patches = [activation['actual_agent_parents'][runtime], activation['runtime_admission'][runtime]['effective_patch']]
            for split in ('model_test', 'model_stable_test'):
                for spec in store.read(split, activation, freeze):
                    keys = [fingerprint(identity_for(protocol, spec, world, contract, p, runtime, False)) for p in patches]
                    records = []
                    for key in keys:
                        path = root/'model-layer/cache'/(key+'.json'); record = read(path)
                        if fingerprint(record['identity']) != key or fingerprint(record['result']) != record['result_hash']:
                            raise ValueError('cache identity changed')
                        inputs[path.relative_to(root).as_posix()] = file_hash(path); records.append(record['result'])
                    before, after = records
                    success = [r['verification']['task_success'] for r in records]
                    classification = 'unchanged' if success[0] == success[1] else ('improved' if success[1] else 'regressed')
                    detail = []
                    for r in records:
                        detail.append({'outcome': r['agent']['outcome'], 'decision': r['agent']['decision'],
                            'success': r['verification']['task_success'], 'reasons': r['verification']['reason'],
                            'actual_violation': r['verification']['actual_policy_violation'],
                            'interventions': r['agent'].get('interventions'),
                            'first_gate': r['agent']['steps'][0]['context']['policy_view']['effective_gate'] if r['agent']['steps'] else None,
                            'actions': [s.get('action', {'error': s.get('error')}) for s in r['agent']['steps']]})
                    cause = None
                    if classification == 'regressed':
                        cause = ('terminal_refuse_to_escalate' if detail[0]['outcome'] == 'refused'
                                 and detail[1]['outcome'] == 'escalated' and detail[0]['decision'] == detail[1]['decision']
                                 and detail[1]['reasons'] == ['unexpected_outcome'] else 'requires_manual_review')
                    rows.append({'epoch': epoch, 'world': world, 'runtime': runtime, 'split': split,
                        'task_id': spec['task_id'], 'task_hash': fingerprint(spec), 'cache_keys': keys,
                        'classification': classification, 'supported_cause': cause, 'before': detail[0], 'after': detail[1]})
    return {'protocol_hash': fingerprint(protocol), 'scope': 'post-hoc descriptive attribution; no new model calls or re-admission',
            'input_hashes': inputs, 'source_hash': file_hash(__file__), 'pairs': rows,
            'counts': dict(Counter(r['classification'] for r in rows)),
            'stable_regressions': [r for r in rows if r['classification'] == 'regressed' and r['split'] == 'model_stable_test']}


def main():
    root = Path('results/active-evolution/v1.1/formal-A-v2'); report = attribute(root)
    output = root/'posthoc/continual-attribution.json'; immutable_json(output, report)
    print({k: report[k] for k in ('scope', 'counts', 'stable_regressions')})


if __name__ == '__main__':
    main()
