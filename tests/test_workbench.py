from fastapi.testclient import TestClient
import pytest

from skillforge import api
from skillforge.benchmark import generate_tasks
from skillforge.environment import Environment
from skillforge.model import ScriptedPolicy
from skillforge.runtime import Runtime
from skillforge.schemas import Action
from skillforge.workbench import RunSubmission, Workbench
from test_jobs import wait_for


@pytest.fixture(autouse=True)
def isolated_workbench_dataset(tmp_path, monkeypatch):
    from skillforge.dataset import write_dataset
    root = tmp_path / "dataset"
    write_dataset(root, instances=1)
    monkeypatch.setenv("SKILLFORGE_DATASET", str(root))
    monkeypatch.setenv("SKILLFORGE_JOB_ROOT", str(tmp_path / "jobs"))


def test_cancellation_after_model_response_cannot_mutate():
    task = next(t for t in generate_tasks() if t.family == "refund" and t.expected.allowed_outcomes == ["completed"])
    cancelled = False
    class LateModel(ScriptedPolicy):
        def decide(self, context):
            nonlocal cancelled
            cancelled = True
            return Action(type="tool", name="issue_refund", arguments=task.parameters)
    env = Environment(fixture=task.fixture)
    try:
        result = Runtime(LateModel()).run(task, env, cancelled=lambda: cancelled)
        assert result["outcome"] == "cancelled"
        assert result["tool_audit"] == [] and env.snapshot()["refunds"] == []
        assert result["steps"][0]["action"]["name"] == "issue_refund"
        assert not result["verification"]["task_success"]
    finally:
        env.close()


def test_cancel_after_refund_commit_preserves_one_write(tmp_path):
    task = next(t for t in generate_tasks() if t.family == "refund" and t.expected.allowed_outcomes == ["completed"])
    cancelled, events = False, []
    def emit(kind, payload):
        nonlocal cancelled
        events.append((kind, payload))
        if kind == "tool" and payload["tool_name"] == "issue_refund" and payload["committed"]:
            cancelled = True
    path = tmp_path / "environment.sqlite"
    env = Environment(path=path, fixture=task.fixture)
    try:
        result = Runtime(ScriptedPolicy()).run(task, env, on_event=emit, cancelled=lambda: cancelled)
        assert result["outcome"] == "cancelled"
        assert len(result["final_state"]["refunds"]) == 1
        assert not result["verification"]["task_success"]
    finally:
        env.close()
    reopened = Environment(path=path, fixture=task.fixture)
    try:
        assert len(reopened.snapshot()["refunds"]) == 1
        assert any(k == "tool" and p["committed"] for k, p in events)
    finally:
        reopened.close()


def test_formal_api_manual_task_artifacts_and_idempotency(tmp_path, monkeypatch):
    monkeypatch.setenv("SKILLFORGE_JOB_ROOT", str(tmp_path / "jobs"))
    with TestClient(api.app) as client:
        assert client.get("/api/v1/health").json()["worker_alive"]
        dataset = client.get("/api/v1/dataset?split=train").json()
        task = next(t for t in dataset["tasks"] if t["family"] == "refund" and t["expected"]["allowed_outcomes"] == ["completed"])
        # Forging a frozen dataset ID through manual input is explicitly removed.
        body = {"task": task, "protocol": "free_action", "variant": "B0", "engineering": True}
        headers = {"Idempotency-Key": "request-1"}
        response = client.post("/api/v1/runs", json=body, headers=headers)
        assert response.status_code == 202
        jid = response.json()["run_id"]
        assert client.post("/api/v1/runs", json=body, headers=headers).json()["run_id"] == jid
        different = {**body, "max_steps": 1}
        assert client.post("/api/v1/runs", json=different, headers=headers).status_code == 409
        wait_for(lambda: client.get("/api/v1/runs/" + jid).json()["status"] == "succeeded")
        run = client.get("/api/v1/runs/" + jid).json()
        assert run["result"]["verification"]["task_success"]
        assert run["result"]["dataset_id"] == "manual-unregistered"
        assert run["result"]["origin"] == "manual" and run["result"]["engineering_only"]
        assert len(run["result"]["final_state"]["refunds"]) == 1
        assert client.get(f"/api/v1/runs/{jid}/artifacts/trajectory.json").json()["run_id"] == jid
        assert client.get(f"/api/v1/runs/{jid}/artifacts/environment.sqlite").content.startswith(b"SQLite format")
        assert client.get(f"/api/v1/runs/{jid}/artifacts/jobs.sqlite").status_code == 404
        assert client.post(f"/api/v1/runs/{jid}/retry").status_code == 409
        assert client.post(f"/api/v1/runs/{jid}/cancel", headers={"Origin": "https://unrelated.example"}).status_code == 403
        assert client.get("/api/v1/runs/not-a-run").status_code == 404
        assert client.get("/api/v1/dataset?split=other").status_code == 422
        assert client.get(f"/api/v1/runs/{jid}/events?after=-1").status_code == 422
        invalid = {"task_id": task["task_id"], "protocol": "skill_menu", "variant": "B0"}
        assert client.post("/api/v1/runs", json=invalid).status_code == 422
        assert "研究工作台" in client.get("/").text
    with TestClient(api.app) as restarted:
        assert restarted.get("/api/v1/runs/" + jid).json()["status"] == "succeeded"


def test_configuration_drift_fails_before_environment_creation(tmp_path):
    wb = Workbench(root=tmp_path)
    from skillforge.dataset import load_dataset
    _, tasks = load_dataset(wb.dataset)
    submission = RunSubmission(task_id=tasks[0].task_id, protocol="free_action", variant="B0", engineering=True)
    frozen = wb.freeze(submission)
    frozen["code_hash"] = "old-version"
    job, _ = wb.store.submit(frozen)
    import pytest
    with pytest.raises(ValueError, match="code changed"):
        wb.execute(job, lambda *args: None, lambda: False)
    assert not wb.store.directory(job["id"]).exists()


def test_training_reservation_blocks_real_jobs_but_keeps_reports_available(tmp_path, monkeypatch):
    from skillforge import workbench
    monkeypatch.setenv("SKILLFORGE_JOB_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setattr(workbench, "training_reserves_gpu", lambda: "sft")
    with TestClient(api.app) as client:
        state = client.get("/api/v1/health").json()
        assert state["worker_alive"] and state["training_gpu_reservation"] == "sft"
        task = client.get("/api/v1/dataset?split=train").json()["tasks"][0]
        response = client.post("/api/v1/runs", json={"task_id": task["task_id"], "protocol": "free_action", "variant": "B0"})
        assert response.status_code == 409 and "GPU" in response.json()["detail"]
        assert client.get("/api/v1/reports").status_code == 200
        assert client.get("/api/v1/runs").json()["runs"] == []
