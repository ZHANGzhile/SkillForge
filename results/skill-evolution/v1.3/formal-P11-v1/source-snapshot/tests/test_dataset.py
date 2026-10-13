import json

import pytest

from skillforge.benchmark import run_benchmark
from skillforge.dataset import audit_splits, generate_experiment, load_dataset, write_dataset
from skillforge.model import ScriptedPolicy


def test_dataset_reproducible_immutable_and_tamper_detected(tmp_path):
    manifest = write_dataset(tmp_path, instances=1)
    assert write_dataset(tmp_path, instances=1) == manifest
    loaded, tasks = load_dataset(tmp_path)
    assert loaded == manifest
    assert len(tasks) == 72
    with pytest.raises(ValueError, match="immutable"):
        write_dataset(tmp_path, seed=100, instances=1)
    with (tmp_path / "test.jsonl").open("ab") as f:
        f.write(b"\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_dataset(tmp_path)


def test_split_audit_looks_at_content_not_labels():
    tasks = generate_experiment(instances=1)
    train = next(t for t in tasks if t.split == "train")
    test = next(t for t in tasks if t.split == "test" and t.family == train.family)
    test.template_text = train.template_text
    test.request = train.template_text.format(**test.parameters)
    test.template_id = "renamed-test-template"
    with pytest.raises(ValueError, match="template content"):
        audit_splits(tasks)


def test_heldout_structure_cannot_appear_in_training():
    tasks = generate_experiment(instances=1)
    next(t for t in tasks if t.split == "train").structure_id = "address_else_cancel_else_escalate"
    with pytest.raises(ValueError, match="held out"):
        audit_splits(tasks)


def test_new_instances_and_three_composite_branches_execute(tmp_path):
    tasks = [t for t in generate_experiment(instances=1) if t.split == "test"]
    summary, results = run_benchmark(ScriptedPolicy(), tasks=tasks, output_root=tmp_path)
    assert summary["task_success_rate"] == 1, [(r["task_id"], r["outcome"], r["verification"]["reason"]) for r in results if not r["verification"]["task_success"]]
    assert any(r["final_state"].get("order.status") == "CANCELLED" for r in results if r["task_family"] == "composite")
    assert all(r["initial_state"]["order.order_id"] != "O1" for r in results)
    assert all("expected" not in s["context"] and "task_hash" not in s["context"] for r in results for s in r["steps"])
