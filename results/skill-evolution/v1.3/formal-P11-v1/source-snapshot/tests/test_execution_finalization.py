import json

from scripts import finalize_execution_aware as module


def test_incomplete_model_invocation_never_emits_formal_aggregate(tmp_path, monkeypatch):
    root = tmp_path/'formal'; target = root/'model-layer/invocations'
    target.mkdir(parents=True)
    (target/'invocation.final.json').write_text(json.dumps({'status': 'incomplete'}))
    monkeypatch.setattr(module, 'load', lambda _: {})
    monkeypatch.setattr(module, 'audit', lambda _: {'complete': False, 'passed': True})
    result = module.finalize(root, 'invocation')
    assert result['status'] == 'incomplete'
    assert not (root/'REPORT.md').exists()
    record = json.loads((root/'audits/finalization-invocation.json').read_text())
    assert record['status'] == 'incomplete' and record['audit']['passed']
