"""Small real-model integration check using train tasks only; no test tuning."""
import json
import logging
from pathlib import Path

import httpx

from skillforge.benchmark import run_benchmark
from skillforge.dataset import load_dataset
from skillforge.model import ModelClient


def main():
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    _, tasks = load_dataset('data/experiment-v1')
    selected = []
    for family, outcome in [('modify_address', 'completed'), ('modify_address', 'refused'),
                            ('cancel_order', 'completed'), ('refund', 'completed'), ('refund', 'escalated')]:
        selected.append(next(t for t in tasks if t.split == 'train' and t.family == family
            and t.expected.allowed_outcomes == [outcome] and not t.fixture.get('faults')))
    model = ModelClient()
    summary, results = run_benchmark(model, tasks=selected, output_root='results/local-student', label='B0-real-train-smoke')
    path = Path('results/local-student') / summary['run_id']
    with httpx.Client(trust_env=False, timeout=10) as client:
        ps = client.get('http://127.0.0.1:11434/api/ps').json()
    (path / 'gpu_residency.json').write_text(json.dumps(ps, indent=2), encoding='utf-8')
    print(json.dumps({'summary': summary, 'artifact_dir': str(path.resolve()),
        'cases': [{'family': r['task_family'], 'outcome': r['outcome'], 'success': r['verification']['task_success'],
                   'errors': r['error_categories']} for r in results]}, indent=2), flush=True)


if __name__ == '__main__':
    main()
