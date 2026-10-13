from fastapi.testclient import TestClient

from skillforge import api


def test_task_and_trace_api(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "ROOT", tmp_path)
    client = TestClient(api.app)
    response = client.post("/tasks", json={"scripted": True, "case_index": 22})
    assert response.status_code == 202
    tid = response.json()["task_id"]
    result = client.get(f"/tasks/{tid}/trace").json()
    assert result["verification"]["task_success"]
    assert len(result["final_state"]["refunds"]) == 1
    assert client.post("/tasks", json={"case_index": -1}).status_code == 400
    assert client.get("/").status_code == 200


def test_skill_demo_api_uses_real_runner_and_validates_selection(tmp_path, monkeypatch):
    from skillforge import skill_demo
    monkeypatch.setattr(api, 'ROOT', tmp_path)
    calls=[]
    def run_case(family, case):
        calls.append((family,case))
        return {'demo_passed':True,'model':'test-double'}
    monkeypatch.setattr(skill_demo, 'run_case', run_case)
    client=TestClient(api.app)
    response=client.post('/skill-demo/run',json={'family':'refund','case':'high_risk'})
    assert response.status_code==202
    assert calls==[('refund','high_risk')]
    result=client.get('/tasks/'+response.json()['task_id']).json()
    assert result['status']=='completed' and result['result']['demo_passed']
    assert client.post('/skill-demo/run',json={'family':'unknown'}).status_code==422
    page=client.get('/skill-demo')
    assert page.status_code==200 and '运行真实模型演示' in page.text
