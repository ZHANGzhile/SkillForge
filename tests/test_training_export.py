import hashlib
import json

import pytest

from scripts.export_sft_data import export
from skillforge.dataset import load_dataset, write_dataset
from skillforge.environment import Environment
from skillforge.model import ScriptedPolicy
from skillforge.runtime import Runtime


@pytest.fixture
def export_inputs(tmp_path):
    dataset = tmp_path / "dataset"
    write_dataset(dataset, instances=1)
    manifest, tasks = load_dataset(dataset)
    task = next(t for t in tasks if t.split == "train" and t.family == "cancel_order" and t.expected.allowed_outcomes == ["completed"])
    # A deliberately labelled test double checks format/provenance guards only.
    model = ScriptedPolicy()
    model.model = "unit-test-double"
    model.settings = {"system_prompt": "unit test", "prompt_sha256": hashlib.sha256(b"unit test").hexdigest()}
    env = Environment(fixture=task.fixture)
    try:
        record = Runtime(model).run(task, env)
    finally:
        env.close()
    source = tmp_path / "source.jsonl"
    source.write_text(json.dumps(record), encoding="utf-8")
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"config": {"engineering_only": False, "dataset_hash": manifest["dataset_hash"]},
        "summary": [{"label": label, "tasks": manifest["audit"]["counts"]["test"], "repeat_count": 1} for label in ["B0", "B1", "B2", "B3"]]}), encoding="utf-8")
    return {"dataset": dataset, "source": source, "baseline": baseline, "output": tmp_path / "export"}, record


def test_export_exact_history_and_completion_targets(export_inputs):
    args, record = export_inputs
    report = export(**args)
    examples = [json.loads(line) for line in (args["output"] / "train.jsonl").read_text(encoding="utf-8").splitlines()]
    assert examples and not report["trained"] and not report["ready_for_skill_learning"]
    for example in examples:
        evidence = example["evidence"][0]
        step = record["steps"][evidence["step_id"]]
        assert json.loads(example["messages"][1]["content"]) == step["context"]
        assert json.loads(example["messages"][2]["content"]) == step["action"]
        assert "expected" not in json.loads(example["messages"][1]["content"])
    assert hashlib.sha256((args["output"] / "train.jsonl").read_bytes()).hexdigest() == report["train_sha256"]
    with pytest.raises(FileExistsError):
        export(**args)


@pytest.mark.parametrize("change,match", [
    (lambda r: r.update(split="test"), "train split"),
    (lambda r: r.update(model="scripted-engineering-only"), "scripted source"),
    (lambda r: r["model_settings"].update(decision_protocol="bounded_skill_menu"), "separately"),
    (lambda r: r["model_settings"].update(system_prompt="changed"), "hash"),
    (lambda r: r["steps"][0]["context"].update(expected={"answer": "secret"}), "oracle"),
])
def test_training_export_rejects_contamination(export_inputs, change, match):
    args, record = export_inputs
    change(record)
    args["source"].write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match=match):
        export(**args)
    assert not args["output"].exists()


def test_training_export_requires_completed_real_baseline(export_inputs):
    args, _ = export_inputs
    baseline = json.loads(args["baseline"].read_text())
    baseline["summary"].pop()
    args["baseline"].write_text(json.dumps(baseline))
    with pytest.raises(ValueError, match="incomplete"):
        export(**args)
