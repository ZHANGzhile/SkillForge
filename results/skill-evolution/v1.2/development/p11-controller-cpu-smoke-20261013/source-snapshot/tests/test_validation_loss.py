import json
import pytest

from scripts import validation_loss
from skillforge.dataset import write_dataset, load_dataset
from skillforge.experiment import read_sources
from skillforge.learning import build_sft


def test_heldout_likelihood_targets_remain_outside_training(tmp_path, monkeypatch):
    dataset = tmp_path / "dataset"
    write_dataset(dataset, instances=1)
    manifest, tasks = load_dataset(dataset)
    monkeypatch.setattr(validation_loss, "load_bundle", lambda *_: ({"bundle_hash": "test-bundle"}, []))
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"dataset": str(dataset), "bundle": "test-bundle"}))
    output = tmp_path / "heldout"
    report = validation_loss.prepare(config, output)
    assert report["tasks"] == 23 and report["teacher_llm_calls"] == 0
    _, rows = validation_loss.load_targets(output, tasks, manifest["dataset_hash"], "test-bundle")
    assert rows and all(r["split"] == "validation" for r in rows)
    with pytest.raises(ValueError, match="train split"):
        build_sft(read_sources(output / "trajectories.jsonl"))
    with pytest.raises(ValueError, match="held-out task set"):
        validation_loss.load_targets(output, [t for t in tasks if t.split == "train"], manifest["dataset_hash"], "test-bundle")
    with (output / "targets.jsonl").open("a") as stream:
        stream.write('{}\n')
    with pytest.raises(ValueError, match="file hash"):
        validation_loss.load_targets(output, tasks, manifest["dataset_hash"], "test-bundle")
