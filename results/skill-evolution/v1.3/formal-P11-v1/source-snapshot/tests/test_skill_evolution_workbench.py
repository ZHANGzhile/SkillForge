"""Read-only saved-evidence views; no inference or admission is performed."""
import json

import pytest
from fastapi.testclient import TestClient

from skillforge.evolution_schemas import fingerprint
from skillforge.skill_evolution_workbench import app as module
from skillforge.skill_evolution_workbench.data import SkillEvolutionView


def save(path, value, *, hashed=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    if hashed: value = {**value, "hash": fingerprint(value)}
    path.write_text(json.dumps(value), encoding="utf-8")
    return value


def planned_view(tmp_path):
    rounds = [{"round": number, "learn_cases": [{"task_id": "unit-"+str(number)}]} for number in (1, 2, 3)]
    save(tmp_path / "protocol.json", {"schema": "p5-three-round-research-protocol-v1", "frozen": True,
        "draft": {"rounds": rounds, "final_test_cases": [{"case": {"task_id": "unit-test"}}]},
        "budget": {"prior_tokens": 123}, "settings": {"model": "SCRIPTED-VIEW-ONLY"}, "no_history": {}, "unsupported": {}}, hashed=True)
    return SkillEvolutionView(tmp_path)


def test_view_is_read_only_handles_not_started_live_and_hash_tampering(tmp_path):
    view = planned_view(tmp_path)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    value = view.index()
    assert value["ready"] and value["status"] == "RUNNING"
    assert value["budget"]["observed_shared_tokens"] == 123 and not value["budget"]["cost_finalized"]
    assert value["funnel"]["learn_completed"] == 0 and not value["deployed"]
    assert before == {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    save(tmp_path / "r1/learn/0/C/collection-status.json", {"completed": True, "charged_tokens": 100, "failure": None})
    assert view.index()["budget"]["observed_shared_tokens"] == 223
    protocol = json.loads((tmp_path / "protocol.json").read_text()); protocol["frozen"] = False
    save(tmp_path / "protocol.json", protocol)
    with pytest.raises(ValueError, match="hash mismatch"): view.index()


def test_live_approved_unknown_reservation_is_visible_but_not_finalized(tmp_path):
    view = planned_view(tmp_path)
    folder = tmp_path / "r1/learn/0/C"
    save(folder / "initial-snapshot/snapshot.json", {})
    body = {"runtime": {"model_requests": [{"status": "pending", "reserved_tokens": 16384}]}}
    save(folder / "checkpoints/0/snapshot.json", {"hash": fingerprint(body), "body": body})
    save(folder / "admissions/0.json", {"approved": True})
    value = view.index()
    assert value["rounds"][0]["learn"]["pending_requests"] == 1
    assert value["budget"]["observed_shared_tokens"] == 123+16384
    assert not value["budget"]["cost_finalized"]


def test_api_has_only_read_routes_and_rejects_unplanned_trace_and_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "view", planned_view(tmp_path))
    client = TestClient(module.app)
    assert client.get("/api/skill-evolution/index").status_code == 200
    assert client.get("/skill-evolution").status_code == 200
    assert client.post("/api/skill-evolution/index").status_code == 405
    for name in ("../../pyproject.toml", "r4/result.json", "test/0/C/result.json"):
        assert client.get("/api/skill-evolution/artifact", params={"name": name}).status_code == 404
    assert client.get("/api/skill-evolution/trace", params={"stage": "learn", "index": 999, "method": "C"}).status_code == 404
    assert client.get("/api/skill-evolution/trace", params={"stage": "learn", "index": 0, "method": "A"}).status_code == 404
