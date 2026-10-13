import copy
import json
import random

import pytest

from scripts.audit_evolution_run import audit
from scripts.run_skill_evolution import snapshot_sources
from skillforge.environment import Environment
from skillforge.evolution_common.snapshot import save_snapshot
from skillforge.evolution_registry import immutable_json
from skillforge.evolution_schemas import fingerprint
from skillforge.schemas import Task, ExpectedOutcome
from skillforge.skill_evolution.catalog import Catalog
from skillforge.skill_evolution.runtime import PROTOCOL, run_agent, runtime_sources
from skillforge.verifier import verify
from test_skill_evolution_catalog import entry
from test_skill_evolution_runtime import Model, actions, call, TASK


@pytest.fixture
def evidence(tmp_path):
    root = tmp_path / "run"; root.mkdir()
    e = entry(); catalog = Catalog([e]); catalog.save(root / "catalog.json")
    task = Task(**TASK, split="train", template_id="audit-fixture", seed=42,
                expected=ExpectedOutcome(allowed_outcomes=["completed"], expected_state={"order.status": "CANCELLED"}))
    immutable_json(root / "private-dev-tasks.json", [task.model_dump()])
    limits = {"max_steps": 16, "max_search": 3, "max_load": 3, "max_tokens": 131072}
    immutable_json(root / "registration.json", {"protocol": PROTOCOL, "sources": runtime_sources(), "config": {"limits": limits}})
    snapshot_sources(root)
    folder = root / task.task_id; folder.mkdir()
    model = Model(actions(e)); env = Environment()
    saved = []
    initial = env.snapshot()
    agent = run_agent(model, TASK, catalog, call(env), persist=lambda value: saved.append(copy.deepcopy(value)))
    save_snapshot(folder / "checkpoints/0", env, saved[-1], random.Random(42))
    row = {"task_id": task.task_id, "task_hash": fingerprint(task.model_dump()), "agent": agent,
           "verification": verify(task, initial, env.snapshot(), env.audit, agent["outcome"]), "tool_audit": env.audit}
    immutable_json(folder / "result.json", row)
    immutable_json(root / "model-identity.json", model.settings)
    immutable_json(root / "report.json", {"status": "complete", "n": 1, "planned": 1, "tokens": 0,
                                         "eoc": 1, "actual_violations": 0, "attempted_violations": 0})
    env.close()
    return root


def test_audit_recomputes_scripted_engineering_evidence_without_model(evidence):
    result = audit(evidence)
    assert result["passed"] and result["cases"] == 1 and result["model_calls"] == 0
    assert result["checkpoints"] == 1


def test_audit_catches_forged_eoc_even_when_result_json_is_valid(evidence):
    path = next(evidence.glob("*/result.json")); value = json.loads(path.read_text())
    value["verification"]["task_success"] = False
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="EOC mismatch"): audit(evidence)


def test_audit_catches_database_or_exact_context_tamper(evidence):
    path = next(evidence.glob("*/result.json")); value = json.loads(path.read_text())
    value["agent"]["steps"][0]["messages"] = [{"role": "system", "content": "fixture"}, {"role": "user", "content": "{}"}]
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="messages/context"): audit(evidence)
