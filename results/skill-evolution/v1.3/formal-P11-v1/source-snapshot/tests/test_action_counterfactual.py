import copy
import json

import pytest

from test_skills import address_skill
from scripts import evaluate_action_counterfactual as cf
from skillforge.dataset import generate_experiment
from skillforge.environment import Environment
from skillforge.model import ScriptedPolicy
from skillforge.runtime import Runtime


@pytest.fixture
def experiment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs").mkdir()
    class TestPolicy(ScriptedPolicy):
        model, fatal_error = "explicit-test-double", None
    settings = {"model": "explicit-test-double"}
    source_model = TestPolicy()
    source_model.settings = settings
    task = next(t for t in generate_experiment(instances=1) if t.split == "test" and t.family == "modify_address" and t.expected.allowed_outcomes == ["completed"] and not t.fixture.get("faults"))
    skills = [address_skill()]
    env = Environment(fixture=task.fixture)
    try:
        source = Runtime(source_model, skills=skills).run(task, env)
    finally:
        env.close()
    cases, exclusions = cf.select_cases([source], 16)
    assert len(cases) == 1 and not exclusions
    root = tmp_path / "evidence"
    plan = {"output": str(root), "client_profile": "unused"}
    identity = {"model_settings": settings, "cases": cases, "exclusions": []}
    monkeypatch.setattr(cf, "prepared", lambda _: (plan, identity, {task.task_id: task}, skills, {task.task_id: source}))
    def create(*_):
        model = TestPolicy()
        model.settings = {"server_identity": settings}
        return model
    monkeypatch.setattr(cf, "create_client", create)
    return root, source, task, cases[0], skills, identity


def test_real_runtime_fork_pair_resume_and_read_only_audit(experiment, monkeypatch):
    root, source, task, case, skills, identity = experiment
    report = cf.run("unused")
    assert report["paired"]["contexts"] == report["paired"]["skill_successes"] == report["paired"]["primitive_successes"] == 1
    assert report["paired"]["observed_reuse_counterfactual_ntr"] == 0
    def forbidden(*_):
        raise AssertionError("completed audit/resume must not call model service")
    monkeypatch.setattr(cf, "create_client", forbidden)
    assert cf.run("unused", resume=True) == cf.run("unused", audit_only=True) == report
    rows = [json.loads(p.read_text(encoding="utf-8")) for p in (root / "branches").glob("*.json")]
    assert rows[0]["counterfactual"]["fork"] == rows[1]["counterfactual"]["fork"]
    for row in rows:
        assert row["metrics"]["llm_calls"] == len(row["counterfactual"]["actual_model_inputs"])
        assert row["metrics"]["decision_calls"] == row["metrics"]["llm_calls"] + case["step_id"] + 1
        assert not row["verification"]["actual_policy_violation"]
    changed = copy.deepcopy(report)
    changed["paired"]["harmed"] = 99
    (root / "evaluation.json").write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="summary differs"):
        cf.run("unused", audit_only=True)


def test_selection_does_not_filter_by_success_and_explains_exclusion(experiment):
    _, source, _, case, _, _ = experiment
    failed = copy.deepcopy(source)
    failed["verification"]["task_success"] = False
    assert cf.select_cases([failed], 16)[0] == cf.select_cases([source], 16)[0]
    assert case["step_id"] > 0
    failed["steps"][0]["action"]["name"] = "cancel_order"
    selected, skipped = cf.select_cases([failed], 16)
    assert not selected and skipped[0]["reason"] == "prefix_not_read_only"


def test_fork_requires_exact_context_database_and_fault_queues(experiment):
    _, source, task, case, skills, _ = experiment
    expected = cf.capture(task, source, case, skills)
    changed = copy.deepcopy(expected)
    changed["remaining_faults"] = {"update_shipping_address": ["timeout"]}
    env = Environment(fixture=task.fixture)
    try:
        model = cf.ForkClient(None, env, source, case, "capture", changed)
        Runtime(model, skills=skills).run(task, env)
        assert "fork database/context/fault" in model.fatal_error
        assert model.actual_calls == 0
    finally:
        env.close()
    changed_source = copy.deepcopy(source)
    changed_source["steps"][0]["context"]["observations"]["hidden.fake"] = True
    with pytest.raises(ValueError, match="context differs"):
        cf.capture(task, changed_source, case, skills)


def test_conditional_ntr_denominator_and_mismatched_pair(experiment):
    root, *_ = experiment
    cf.run("unused")
    pair = {}
    for path in (root / "branches").glob("*.json"):
        row = json.loads(path.read_text(encoding="utf-8"))
        pair[row["counterfactual"]["arm"]] = row
    pair["skill"]["verification"]["task_success"] = False
    report = cf.summarize_pairs([pair])
    assert report["harmed"] == 1 and report["observed_reuse_counterfactual_ntr"] == 1
    assert report["population_causal_ntr"] is None
    pair["primitive"]["verification"]["task_success"] = False
    assert cf.summarize_pairs([pair])["observed_reuse_counterfactual_ntr"] is None
    pair["primitive"]["counterfactual"]["fork"]["remaining_faults"] = {"x": []}
    with pytest.raises(ValueError, match="differ"):
        cf.summarize_pairs([pair])
