import json

from scripts.execution_aware_formal import H0
from scripts.execution_aware_protocol import write_split_dataset
from scripts.recover_execution_interruption import first_uncached, identity_for, reserve_unfinished
from skillforge.evolution_registry import immutable_json
from skillforge.evolution_schemas import fingerprint
from test_evolution_execution import parent


def test_next_possible_dispatch_preserves_frozen_serial_order_and_cache(tmp_path):
    dataset = tmp_path/'datasets/W3/411'; contract = parent('refund')
    write_split_dataset(dataset, 'W3', 411, {'explore': 80, 'model_validation': 8,
        'model_stable_validation': 4, 'model_test': 8, 'model_stable_test': 8}, contract)
    root = tmp_path/'formal'; protocol = {'data_root': str(dataset.parent.parent), 'model_settings': {}}
    boundary = {'world': 'W3', 'seed': 411, 'before': H0, 'effective': H0}
    immutable_json(root/'cpu-report.json', {'independent': [boundary], 'continuous': []})
    valid = json.loads((dataset/'model_validation.json').read_text(encoding='utf-8'))
    for spec in valid[:7]:
        identity = identity_for(protocol, spec, 'W3', contract, H0, 'old', False)
        immutable_json(root/'model-layer/cache'/(fingerprint(identity)+'.json'),
            {'identity': identity, 'result': {}, 'result_hash': fingerprint({})})
    pending = first_uncached(root, protocol)
    assert pending == identity_for(protocol, valid[7], 'W3', contract, H0, 'old', False)
    assert len(list((root/'model-layer/cache').glob('*.json'))) == 7


def test_unknown_dispatch_reservation_is_idempotent_and_spends_retry_slot(tmp_path):
    proposal = {'possible_unrecorded_dispatch': {'task_hash': 't', 'decision_only': False},
                'invocation': 'orphan', 'reserved_tokens': 16*16384}
    reserve_unfinished(tmp_path, proposal, {'task_wall_seconds': 180})
    reserve_unfinished(tmp_path, proposal, {'task_wall_seconds': 180})
    files = list((tmp_path/'model-layer/failures').glob('*.json'))
    assert len(files) == 1 and files[0].name.endswith('-0.json')
    assert json.loads(files[0].read_text())['reserved_tokens'] == 262144
