import copy
import json

import httpx
import pytest

from scripts import evaluate_reuse_ablation as ablation
from skillforge.dataset import generate_experiment, task_hash
from skillforge.environment import Environment
from skillforge.model import ScriptedPolicy
from skillforge.runtime import Runtime


@pytest.fixture
def experiment(tmp_path, monkeypatch):
    # All generated model records in these tests are explicit doubles and only
    # exist in tmp_path; no production evidence or GPU endpoint is used.
    monkeypatch.chdir(tmp_path)
    tasks = [t for t in generate_experiment(instances=1) if t.split == "test"][:2]
    settings = {"model": "explicit-test-double"}
    class TestPolicy(ScriptedPolicy):
        model = "explicit-test-double"
        fatal_error = None
    policy = TestPolicy()
    policy.settings = settings
    reference = {}
    for task in tasks:
        env = Environment(fixture=task.fixture)
        try:
            reference[task.task_id] = Runtime(policy).run(task, env)
        finally:
            env.close()
    root = tmp_path / "output"
    plan = {"output": str(root), "client_profile": "explicit-unused-profile"}
    identity = {"model_settings": settings, "task_hashes": {t.task_id: task_hash(t) for t in tasks}}
    monkeypatch.setattr(ablation, "prepared", lambda _: (plan, identity, tasks, reference))
    client = TestPolicy()
    client.settings = {"server_identity": settings}
    monkeypatch.setattr(ablation, "create_client", lambda *_: client)
    return root, tasks, reference, settings


def test_ablation_round_trip_resume_and_summary_tamper(experiment, monkeypatch):
    root, tasks, reference, settings = experiment
    report = ablation.evaluate("test-plan")
    assert report["paired"]["tasks"] == 2
    assert report["paired"]["same_context_causal_ntr"] is None
    assert ablation.audit("test-plan") == report
    def forbidden(*_):
        raise AssertionError("Completed resume must not call the real service")
    monkeypatch.setattr(ablation, "create_client", forbidden)
    assert ablation.evaluate("test-plan", resume=True) == report
    altered = copy.deepcopy(report)
    altered["paired"]["paired_regressions"] = 99
    (root / "evaluation.json").write_text(json.dumps(altered), encoding="utf-8")
    with pytest.raises(ValueError, match="differs from audited"):
        ablation.audit("test-plan")


def test_paired_effect_is_not_same_context_causal_ntr(experiment):
    _, tasks, reference, _ = experiment
    left, right = copy.deepcopy(reference), copy.deepcopy(reference)
    for i, task in enumerate(tasks):
        left[task.task_id]["verification"]["task_success"] = i == 0
        right[task.task_id]["verification"]["task_success"] = i == 1
    summary = ablation.paired_summary(left, right)
    assert summary["paired_improvements"] == summary["paired_regressions"] == 1
    assert summary["skill_enabled_system_regression_rate"] == .5
    assert summary["regression_given_b0_success"] == 1
    assert summary["same_context_causal_ntr"] is None
    left.pop(tasks[0].task_id)
    with pytest.raises(ValueError, match="complete task coverage"):
        ablation.paired_summary(left, right)


def test_b0_rejects_memory_and_wrong_server(experiment):
    _, tasks, reference, settings = experiment
    task = tasks[0]
    row = copy.deepcopy(reference[task.task_id])
    row["model_settings"] = {"server_identity": settings}
    ablation.validate_record(row, task, settings, b0=True)
    row["steps"][0]["context"]["retrieved_memory"] = [{"forbidden": True}]
    with pytest.raises(ValueError, match="Skill/Gate/memory"):
        ablation.validate_record(row, task, settings, b0=True)
    row["steps"][0]["context"]["retrieved_memory"] = []
    row["model_settings"]["server_identity"] = {"wrong": True}
    with pytest.raises(ValueError, match="frozen real model"):
        ablation.validate_record(row, task, settings, b0=True)


@pytest.mark.parametrize("error,fatal", [("RuntimeError", True), ("ValidationError", False)])
def test_http_infrastructure_is_not_scored_as_model_failure(monkeypatch, error, fatal):
    client = ablation.PinnedClient.__new__(ablation.PinnedClient)
    response = httpx.Response(502, json={"detail": {"error": error}}, request=httpx.Request("POST", "http://test.local"))
    def fail(*_):
        response.raise_for_status()
    monkeypatch.setattr(ablation.ModelClient, "decide", fail)
    with pytest.raises(httpx.HTTPStatusError):
        client.decide({})
    assert bool(client.fatal_error) == fatal
