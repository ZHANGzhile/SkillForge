import json

import pytest

from scripts import evaluate_fresh_holdout as fresh
from skillforge.dataset import write_dataset
from skillforge.model import ScriptedPolicy


def test_fresh_evaluation_keeps_compilation_provenance_and_audits_resume(tmp_path, monkeypatch):
    original, heldout = tmp_path / "original", tmp_path / "heldout"
    source_manifest = write_dataset(original, seed=10, instances=1)
    holdout_manifest = write_dataset(heldout, seed=11, instances=1)
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"dataset": str(original), "bundle": "explicit-test-bundle"}), encoding="utf-8")
    def bundle(path, dataset_hash):
        assert dataset_hash == source_manifest["dataset_hash"]
        return {"bundle_hash": "explicit-test-only"}, []
    monkeypatch.setattr(fresh, "load_bundle", bundle)
    class TestModel(ScriptedPolicy):
        def __init__(self, *_):
            pass
        @staticmethod
        def settings_for(*_):
            return {"model": "scripted-engineering-only", "explicit_test_double": True}
        def close(self):
            pass
    monkeypatch.setattr(fresh, "HFModelClient", TestModel)
    output = tmp_path / "output"
    report = fresh.evaluate(config, heldout, "test-adapter", "SFT", output)
    assert report["training_dataset_hash"] == source_manifest["dataset_hash"]
    assert report["holdout_dataset_hash"] == holdout_manifest["dataset_hash"]
    assert report["full_system"]["tasks"] == 26
    assert fresh.audit(output, config, heldout) == report
    def forbidden(*_):
        raise AssertionError("completed resume must not load a model")
    monkeypatch.setattr(TestModel, "__init__", forbidden)
    assert fresh.evaluate(config, heldout, "test-adapter", "SFT", output, resume=True) == report
    with pytest.raises(ValueError, match="original corpus"):
        fresh.inputs(config, original)
    report["full_system"]["task_success_rate"] = -1
    (output / "evaluation.json").write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="differs from checkpoints"):
        fresh.audit(output, config, heldout)
