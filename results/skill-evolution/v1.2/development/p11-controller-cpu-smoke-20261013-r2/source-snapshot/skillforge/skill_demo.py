"""Real-model vertical demonstration on train/validation, never test tasks."""
import json
import uuid
from pathlib import Path
from .dataset import load_dataset
from .experiment import load_bundle
from .environment import Environment
from .menu_model import MenuModelClient
from .runtime import Runtime

CASES = ['normal', 'shipped', 'high_risk']
FAMILIES = ['modify_address', 'cancel_order', 'refund']


def select_tasks(family, case, split='train', all_instances=False):
    if family not in FAMILIES or case not in CASES or split not in {'train','validation'}:
        raise ValueError('Invalid demo selection')
    _, tasks = load_dataset('data/experiment-v1')
    expected = {'normal':'completed','shipped':'refused','high_risk':'escalated'}[case]
    chosen = [t for t in tasks if t.split == split and t.family == family
        and t.expected.allowed_outcomes == [expected] and not t.fixture.get('faults')
        and (case != 'shipped' or (t.fixture.get('payment') == 'FAILED' if family == 'refund' else t.fixture.get('shipment') == 'SHIPPED'))
        and (case != 'high_risk' or t.fixture.get('risk') == 'HIGH')]
    if not chosen:
        raise ValueError('Demo task not found')
    return chosen[:3] if all_instances else chosen[:1]


def run_case(family, case, split='train', task=None, output_root='results/skill-demo'):
    task = task or select_tasks(family, case, split)[0]
    if task.split not in {'train','validation'}:
        raise ValueError('Demo cannot run test tasks')
    manifest, _ = load_dataset('data/experiment-v1')
    bundle, skills = load_bundle('results/real-v2-frozen/frozen.json', manifest['dataset_hash'])
    model = MenuModelClient()
    root = Path(output_root) / str(uuid.uuid4())
    root.mkdir(parents=True)
    env = Environment(fixture=task.fixture, faults=task.fixture.get('faults'))
    try:
        result = Runtime(model, skills=[s for s in skills if s.family == family], max_steps=8).run(task, env, root/'trajectories')
    finally:
        env.close()
    result['model_exchanges'] = model.exchanges
    result['artifact_dir'] = str(root.resolve())
    result['bundle_hash'] = bundle['bundle_hash']
    result['demo_passed'] = (result['verification']['task_success']
        and not result['verification']['attempted_policy_violation']
        and (case != 'normal' or len(result['skill_events']) == 1 and result['skill_events'][0]['success']))
    (root/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result
