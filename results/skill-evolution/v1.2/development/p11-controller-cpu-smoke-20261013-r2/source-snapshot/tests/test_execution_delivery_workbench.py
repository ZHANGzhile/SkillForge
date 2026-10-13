import json

import pytest
from fastapi.testclient import TestClient

from scripts.execution_delivery_workbench import AcquisitionView
from skillforge.evolution_schemas import fingerprint


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value),encoding='utf-8')


def test_b_progress_distinguishes_stopped_running_and_auditing(tmp_path):
    view = AcquisitionView(tmp_path)
    assert view.index()['status']=='not_frozen'
    protocol={'config':{'worlds':['W3'],'paired_seeds':[1],'methods':['active','active_v2']},'selected_variant':'gate'}
    ph=fingerprint(protocol);write(tmp_path/'protocol.json',{'protocol':protocol,'protocol_hash':ph})
    assert view.index()['status']=='stopped'
    write(tmp_path/'invocations/one.start.json',{'protocol_hash':ph})
    assert view.index()['status']=='running'
    write(tmp_path/'cpu-report.json',{'protocol_hash':ph,'aggregate':{}})
    assert view.index()['status']=='auditing' and not view.index()['audit_passed']
    write(tmp_path/'invocations/one.final.json',{'status':'incomplete'})
    assert view.index()['status']=='audit_incomplete' and not view.index()['complete']


def test_b_trace_rejects_path_injection_and_incomplete_run(tmp_path, monkeypatch):
    import scripts.execution_delivery_workbench as module
    view=AcquisitionView(tmp_path)
    protocol={'config':{'worlds':['W3'],'paired_seeds':[1],'methods':['active_v2']},'selected_variant':'gate'}
    write(tmp_path/'protocol.json',{'protocol':protocol,'protocol_hash':fingerprint(protocol)})
    monkeypatch.setattr(module,'b_view',view)
    client=TestClient(module.app)
    assert client.get('/api/acquisition-evolution/index').status_code==200
    assert client.post('/api/acquisition-evolution/index').status_code==405
    assert client.get('/api/acquisition-evolution/trace',params={'world':'../../secrets','seed':1,'method':'active_v2'}).status_code==404
    with pytest.raises(KeyError):
        view.trace('W3',1,'active_v2')
    write(tmp_path/'protocol.json',{'protocol':protocol,'protocol_hash':'forged'})
    assert client.get('/api/acquisition-evolution/index').status_code==409
