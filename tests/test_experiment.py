import json

import pytest

from skillforge.benchmark import run_benchmark
from skillforge.dataset import load_dataset, write_dataset
from skillforge.experiment import compare, prepare
from skillforge.model import ScriptedPolicy
from skillforge.schemas import Action


class FailureFixture(ScriptedPolicy):
    def decide(self, context):
        if not context["history"]:
            return Action(type="tool", name="cancel_order" if context["family"] == "cancel_order" else "update_shipping_address", arguments=context["parameters"])
        return Action(type="stop")


def test_frozen_experiment_runs_paired_baselines_and_ablation(tmp_path):
    dataset = tmp_path / "dataset"
    write_dataset(dataset, instances=3)
    _, tasks = load_dataset(dataset)
    train = [t for t in tasks if t.split == "train" and t.family in {"modify_address", "cancel_order"}]
    _, good = run_benchmark(ScriptedPolicy(), train, output_root=tmp_path / "sources")
    _, bad = run_benchmark(FailureFixture(), [t for t in train if t.fixture.get("shipment") == "SHIPPED"], output_root=tmp_path / "sources")
    source = tmp_path / "sources.jsonl"
    source.write_text("\n".join(json.dumps(r) for r in good + bad), encoding="utf-8")
    bundle = prepare(dataset, source, tmp_path / "frozen", engineering=True)
    assert len(bundle["skills"]) == 2
    assert all(s["forbidden_conditions"] == [] for s in bundle["naive_skills"])
    assert all(not any(e.startswith("policy:") or e.startswith("failure:") for e in c["evidence"])
        for s in bundle["naive_skills"] for c in s["preconditions"])
    report = compare(dataset, tmp_path / "frozen/frozen.json", ScriptedPolicy, output_dir=tmp_path / "compare", engineering=True, ablation=True)
    assert len(report["summary"]) == 5
    assert {row["tasks"] for row in report["summary"]} == {78}
    assert all(row["task_success_rate"] == 1 for row in report["summary"]), report["summary"]
    assert report["config"]["engineering_only"]
    assert len(report["config"]["source_code_hash"]) == 64
    assert set(report["by_level"]["B3"]) == set("ABCDE")
    with pytest.raises(ValueError, match="scripted source"):
        compare(dataset, tmp_path / "frozen/frozen.json", ScriptedPolicy, output_dir=tmp_path / "invalid")
    path = tmp_path / "frozen/frozen.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["skills"][0]["preconditions"] = []
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        compare(dataset, path, ScriptedPolicy, engineering=True)
