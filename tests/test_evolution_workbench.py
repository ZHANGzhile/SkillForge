import json

import pytest
from fastapi.testclient import TestClient

from skillforge.evolution_schemas import fingerprint
from skillforge.evolution_workbench.data import EvolutionView


@pytest.fixture
def view(tmp_path, monkeypatch):
    run = {"key": "cpu/W1/101/passive", "stage": "cpu", "world": "W1", "seed": 101,
           "method": "passive", "status": "INCONCLUSIVE", "queries": 1}
    v = EvolutionView(tmp_path)
    monkeypatch.setattr(v, "index", lambda: {"runs": [run]})
    h0 = {"hypothesis_id": "H0", "kind": "no_change", "predicates": []}
    other = {"hypothesis_id": "OTHER", "kind": "other", "predicates": []}
    initial = {"hypotheses": [h0, other], "posterior": [.9, .1], "entropy": .325}
    candidate = {"candidate_id": "C1", "observations": {"risk": "LOW"}}
    q = {"index": 0, "candidate_id": "C1", "learned": False,
         "evidence": {"evidence_id": "E1", "label": "executable"},
         "ranked": [{"candidate_id": "C1", "eig": .1, "score": .05, "cost": 1, "mutation_probability": .2}]}
    q["row_hash"] = fingerprint(q)
    def save(name, data):
        p = tmp_path / run["key"] / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data), encoding="utf-8")
    save("learner/belief/belief_step_000.json", {"kind": "initial", "snapshot": initial, "snapshot_hash": fingerprint(initial)})
    save("learner/queries/query_000.json", q)
    save("learner-packet.json", {"candidates": [candidate], "learning": {"max_queries": 20}})
    save("summary.json", {"status": "INCONCLUSIVE"})
    return v


def test_passive_unlearned_observation_is_charged_without_belief_change(view):
    before = {str(p): (p.stat().st_mtime_ns, p.read_bytes()) for p in view.root.rglob("*.json")}
    trace = view.trace("cpu/W1/101/passive")
    assert len(trace["queries"]) == 1
    assert trace["queries"][0]["before"] == trace["queries"][0]["after"]
    assert trace["queries"][0]["entropy_change"] == 0
    assert before == {str(p): (p.stat().st_mtime_ns, p.read_bytes()) for p in view.root.rglob("*.json")}


def test_trace_refuses_edited_query_and_fabricated_learning(view):
    path = view.root / "cpu/W1/101/passive/learner/queries/query_000.json"
    q = json.loads(path.read_text())
    q["learned"] = True
    path.write_text(json.dumps(q))
    with pytest.raises(ValueError, match="query evidence"):
        view.trace("cpu/W1/101/passive")
    q["row_hash"] = fingerprint({k: v for k, v in q.items() if k != "row_hash"})
    path.write_text(json.dumps(q))
    with pytest.raises(ValueError, match="missing from belief"):
        view.trace("cpu/W1/101/passive")


def test_preview_is_read_only_and_artifacts_are_allowlisted(view, monkeypatch):
    import skillforge.evolution_workbench.app as module
    monkeypatch.setattr(module, "view", view)
    client = TestClient(module.preview)
    assert client.post("/api/evolution/trace", params={"run": "cpu/W1/101/passive"}).status_code == 405
    assert client.get("/api/evolution/trace", params={"run": "../../configs/deployment.local.json"}).status_code == 404
    assert client.get("/api/evolution/artifact", params={"run": "cpu/W1/101/passive", "name": "../../secrets"}).status_code == 404
    assert client.get("/api/evolution/artifact", params={"run": "cpu/W1/101/passive", "name": "summary"}).status_code == 200
    assert client.get("/api/v1/runs").status_code == 404
