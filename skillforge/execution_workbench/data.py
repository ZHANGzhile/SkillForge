"""Recorded evidence only; no model, tool, learner or activation capabilities."""
import json
from pathlib import Path
import re

from ..evolution_schemas import fingerprint


ROOT = Path(__file__).resolve().parents[2]/'results/active-evolution/v1.1/formal-A-v2'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


class ExecutionView:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        self._cache = {}

    def protocol(self):
        record = read(self.root/'protocol.json')
        if fingerprint(record['protocol']) != record['protocol_hash']:
            raise ValueError('protocol identity mismatch')
        return record

    def cache(self, key):
        if not re.fullmatch('[0-9a-f]{64}', key):
            raise KeyError('unknown task')
        path = self.root/'model-layer/cache'/(key+'.json')
        if not path.is_file():
            raise KeyError('unknown task')
        record = read(path)
        if (fingerprint(record['identity']) != key or fingerprint(record['result']) != record['result_hash']
                or record['identity']['protocol_hash'] != self.protocol()['protocol_hash']):
            raise ValueError('task identity mismatch')
        return record

    def task(self, key):
        record = self.cache(key); result = record['result']; agent = result['agent']
        return {'key': key, 'identity': record['identity'], 'verification': result['verification'],
                'decision_correct': result['decision_correct'], 'decision_only': result['decision_only'],
                'agent': {k: v for k, v in agent.items() if k != 'steps'},
                'steps': [{k: v for k, v in step.items() if k != 'context'} for step in agent['steps']],
                'tool_audit': result['tool_audit'], 'result_hash': record['result_hash'],
                'scope': 'human evaluator view; never supplied to learner or model'}

    def index(self):
        identity = self.protocol(); protocol = identity['protocol']; config = protocol['config']
        cpu = read(self.root/'cpu-report.json') if (self.root/'cpu-report.json').exists() else None
        model = read(self.root/'model-report.json') if (self.root/'model-report.json').exists() else None
        groups = []; task_groups = {}
        for world in config['worlds']:
            for seed in config['paired_seeds']:
                groups.append((f'{world}/{seed}', world, seed, Path(protocol['data_root'])/world/str(seed),
                               self.root/'cpu'/world/str(seed), self.root/'model-layer/independent'/world/str(seed), False))
        for epoch, world in enumerate(config['continual']['worlds'], 1):
            groups.append((f'epoch/{epoch}', world, config['continual']['seed'], self.root/'continuous/datasets'/str(epoch),
                           self.root/'continuous/cpu'/str(epoch), self.root/'model-layer/continuous'/str(epoch), True))
        rows = []
        for key, world, seed, dataset, boundary_dir, model_dir, continuous in groups:
            manifest = read(dataset/'manifest.json')
            for member in manifest['members'].values():
                task_groups[member['hash']] = key
            boundary = read(boundary_dir/'boundary.json') if (boundary_dir/'boundary.json').exists() else None
            activation = read(model_dir/'activation.json') if (model_dir/'activation.json').exists() else None
            report = read(model_dir/'report.json') if (model_dir/'report.json').exists() else None
            if activation and activation['protocol_hash'] != identity['protocol_hash']:
                raise ValueError('activation protocol mismatch')
            if activation:
                frozen = read(model_dir/'evaluation-freeze.json')
                if frozen != {'candidate_hash': fingerprint(activation), 'dataset_hash': fingerprint(manifest)}:
                    raise ValueError('activation freeze mismatch')
            rows.append({'key': key, 'world': world, 'seed': seed, 'continuous': continuous,
                'belief_converged': boundary['belief_converged'] if boundary else None,
                'boundary_admitted': boundary['boundary_admitted'] if boundary else None,
                'boundary_validation_passed': boundary['boundary_validation_passed'] if boundary else None,
                'proposal': boundary['proposal'] if boundary else None,
                'runtime_admission': activation['runtime_admission'] if activation else None,
                'report': report, 'model_complete': report is not None})
        tasks = []
        for path in (self.root/'model-layer/cache').glob('*.json'):
            stamp = (path.stat().st_mtime_ns, path.stat().st_size)
            saved = self._cache.get(path.stem)
            if not saved or saved[0] != stamp:
                record = self.cache(path.stem); result = record['result']; agent = result['agent']
                row = {'key': path.stem, 'task_hash': record['identity']['task_hash'], 'runtime': record['identity']['runtime'],
                    'decision_only': result['decision_only'], 'decision_correct': result['decision_correct'],
                    'eoc': result['verification']['task_success'], 'outcome': agent['outcome'],
                    'patch': record['identity']['patch'], 'tokens': agent['metrics']['tokens'],
                    'interventions': agent.get('interventions'), 'seconds': result['seconds']}
                self._cache[path.stem] = (stamp, row)
            row = dict(self._cache[path.stem][1])
            if row['task_hash'] not in task_groups:
                raise ValueError('task outside frozen dataset')
            row['group'] = task_groups[row['task_hash']]; tasks.append(row)
        planned = len(config['worlds'])*len(config['paired_seeds']); independent = [r for r in rows if not r['continuous']]
        funnel = {runtime: {'planned': planned,
            'belief_converged': sum(r['belief_converged'] is True for r in independent),
            'boundary_admitted': sum(r['boundary_admitted'] is True for r in independent),
            'agent_admitted': sum(bool(r['runtime_admission'] and r['runtime_admission'][runtime]['agent_admitted']) for r in independent),
            'activated': sum(bool(r['runtime_admission'] and r['runtime_admission'][runtime]['agent_admitted']) for r in independent),
            'agent_pending': sum(r['boundary_admitted'] is True and not r['runtime_admission'] for r in independent),
            'h0_or_no_candidate': sum(r['boundary_admitted'] is False for r in independent), 'deployed': 0}
                  for runtime in ('old', 'new')}
        failures = [read(p) for p in (self.root/'model-layer/failures').glob('*.json')]
        invocations = [read(p) for p in (self.root/'model-layer/invocations').glob('*.final.json')]
        open_invocations = [p.stem for p in (self.root/'model-layer/invocations').glob('*.start.json')
                            if not p.with_name(p.name.replace('.start.json', '.final.json')).exists()]
        from scripts.execution_resource_accounting import sleep_accounting
        accounting = sleep_accounting(self.root, protocol)
        return {'protocol_hash': identity['protocol_hash'], 'complete': model is not None and not open_invocations,
            'status': 'running' if open_invocations else ('complete' if model else 'stopped'),
            'cpu_complete': cpu is not None, 'groups': rows, 'funnel': funnel, 'tasks': tasks,
            'factorial': model['factorial'] if model else None, 'model_settings': protocol['model_settings'],
            'budget': {'tokens': protocol['prior_charged_tokens']+sum(t['tokens'] for t in tasks)+sum(f['reserved_tokens'] for f in failures),
                       'token_limit': config['limits']['shared_tokens'], 'closed_seconds': protocol['prior_invocation_seconds']+sum(i['seconds'] for i in invocations),
                       'second_limit': config['limits']['shared_gpu_seconds'], 'open_invocations': len(open_invocations),
                       'infrastructure_failures': len(failures), **accounting},
            'scope': 'A only; fixed denominator, isolated activation, no deployment; incomplete matrix has no aggregate effects'}
