import json

import pytest
from fastapi.testclient import TestClient

from skillforge.evolution_schemas import fingerprint
from skillforge.execution_workbench.data import ExecutionView


@pytest.fixture
def view(tmp_path):
    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')
    dataset = tmp_path/'datasets'
    protocol = {'config': {'worlds': ['W3'], 'paired_seeds': [1, 2], 'continual': {'worlds': [], 'seed': 3},
                'limits': {'shared_tokens': 20000000, 'shared_gpu_seconds': 43200}},
                'data_root': str(dataset), 'model_settings': {}, 'prior_charged_tokens': 100, 'prior_invocation_seconds': 20}
    write(tmp_path/'protocol.json', {'protocol': protocol, 'protocol_hash': fingerprint(protocol)})
    for seed in (1, 2):
        write(dataset/'W3'/str(seed)/'manifest.json', {'members': {'t'+str(seed): {'hash': 'hash'+str(seed)}}})
        write(tmp_path/'cpu/W3'/str(seed)/'boundary.json', {'belief_converged': seed == 1,
            'boundary_admitted': seed == 1, 'boundary_validation_passed': True if seed == 1 else None, 'proposal': {}})
    identity = {'task_hash': 'hash1', 'runtime': 'new', 'patch': {}, 'protocol_hash': fingerprint(protocol)}
    result = {'agent': {'metrics': {'tokens': 30}, 'outcome': 'decision_only', 'steps': []},
              'verification': {'task_success': False}, 'tool_audit': [], 'decision_only': True, 'decision_correct': True, 'seconds': .1}
    key = fingerprint(identity)
    write(tmp_path/'model-layer/cache'/(key+'.json'), {'identity': identity, 'result': result, 'result_hash': fingerprint(result)})
    return ExecutionView(tmp_path), key


def test_pending_funnel_has_fixed_denominator_and_read_only_view(view):
    v, key = view
    before = {str(p): p.read_bytes() for p in v.root.rglob('*.json')}
    result = v.index()
    assert result['funnel']['new']['planned'] == 2
    assert result['funnel']['new']['agent_pending'] == 1
    assert result['funnel']['new']['activated'] == 0
    assert not result['complete'] and result['factorial'] is None
    assert result['budget']['tokens'] == 130
    assert result['status'] == 'stopped'
    assert v.task(key)['decision_correct']
    assert before == {str(p): p.read_bytes() for p in v.root.rglob('*.json')}


def test_task_path_and_mutated_cached_evidence_are_rejected(view):
    v, key = view
    with pytest.raises(KeyError):
        v.task('../../configs/deployment.local.json')
    v.index()
    path = v.root/'model-layer/cache'/(key+'.json')
    value = json.loads(path.read_text()); value['result']['agent']['metrics']['tokens'] = 1
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='identity'):
        v.index()


def test_preview_exposes_no_experiment_or_deployment_mutation_routes(view, monkeypatch):
    import skillforge.execution_workbench.app as module
    monkeypatch.setattr(module, 'view', view[0])
    client = TestClient(module.app)
    assert client.get('/api/execution-evolution/index').status_code == 200
    assert client.post('/api/execution-evolution/index').status_code == 405
    assert client.get('/api/execution-evolution/task', params={'key': '../../secrets'}).status_code == 404
    assert client.get('/api/v1/runs').status_code == 404
    assert client.get('/api/execution-evolution/task', params={'key': view[1]}).status_code == 200
