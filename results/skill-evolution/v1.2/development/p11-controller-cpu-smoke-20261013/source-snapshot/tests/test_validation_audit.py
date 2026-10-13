import json
from pathlib import Path

import pytest

from scripts import audit_validation as auditor
from skillforge.benchmark import generate_tasks, summarize
from skillforge.dataset import task_hash
from skillforge.environment import Environment
from skillforge.evaluation_checkpoints import save_checkpoint
from skillforge.model import ScriptedPolicy
from skillforge.runtime import Runtime
from skillforge.training_data import file_hash


def test_validation_release_audit_rejects_summary_and_nonfinite_scores(tmp_path, monkeypatch):
    task = generate_tasks("validation")[0]
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"dataset": "test-data", "bundle": "test-bundle"}))
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "manifest.json").write_text('{"test_double":true}')
    monkeypatch.setattr(auditor, "load_dataset", lambda _: ({"dataset_hash": "test-dataset-hash"}, [task]))
    monkeypatch.setattr(auditor, "load_bundle", lambda *_: ({"bundle_hash": "test-bundle-hash"}, []))
    target = {"example_id": "example-1", "action_type": "stop", "task_id": task.task_id, "task_hash": task_hash(task)}
    monkeypatch.setattr(auditor, "load_targets", lambda *_: ({}, [target]))
    identity = {"split": "validation", "dataset_hash": "test-dataset-hash", "bundle_hash": "test-bundle-hash",
        "config_hash": file_hash(config), "task_hashes": {task.task_id: task_hash(task)}, "decision_tasks": {},
        "likelihood_manifest_sha256": file_hash(corpus / "manifest.json"),
        "likelihood_evaluator_hash": file_hash(Path(auditor.__file__).with_name("validation_loss.py"))}
    folder = tmp_path / "evaluation"
    for name in ("tasks", "validation_loss"):
        (folder / name).mkdir(parents=True)
    (folder / "identity.json").write_text(json.dumps(identity))
    env = Environment(fixture=task.fixture)
    try:
        record = Runtime(ScriptedPolicy()).run(task, env)
    finally:
        env.close()
    save_checkpoint(folder / "tasks" / (task.task_id + ".json"), record, identity)
    score = {**target, "skipped": False, "log_probability": -2.0, "target_tokens": 2}
    score_path = folder / "validation_loss/example-1.json"
    score_identity = {**identity, "phase": "validation_loss"}
    save_checkpoint(score_path, score, score_identity)
    report = {**identity, "full_system": summarize([record]), "decision_level": [],
        "validation_loss": {"token_weighted_loss": 1.0, "example_mean_loss": 1.0, "examples": 1,
            "target_tokens": 2, "skipped_example_ids": []}}
    report_path = folder / "evaluation.json"
    report_path.write_text(json.dumps(report))
    assert auditor.audit(folder, config, corpus) == report
    report["validation_loss"]["token_weighted_loss"] = .1
    report_path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="summary differs"):
        auditor.audit(folder, config, corpus)
    report["validation_loss"]["token_weighted_loss"] = 1.0
    report_path.write_text(json.dumps(report))
    save_checkpoint(score_path, {**score, "log_probability": float("nan")}, score_identity)
    with pytest.raises(ValueError, match="invalid validation likelihood"):
        auditor.audit(folder, config, corpus)
