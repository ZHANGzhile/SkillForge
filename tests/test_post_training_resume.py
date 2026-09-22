import json
import pytest

from scripts import evaluate_trained_student as evaluator
from skillforge.benchmark import generate_tasks
from skillforge.model import ScriptedPolicy


def setup_evaluation(monkeypatch, tmp_path, fatal=False):
    tasks = generate_tasks("validation")[:2]
    monkeypatch.setattr(evaluator, "load_dataset", lambda _: ({"dataset_hash": "frozen-test-data"}, tasks))
    monkeypatch.setattr(evaluator, "load_bundle", lambda *_: ({"bundle_hash": "frozen-test-contracts"}, []))
    class Model(ScriptedPolicy):
        loads = 0
        closes = 0
        @staticmethod
        def settings_for(config=None, adapter=None, label="Base"):
            return {"model": "evaluation-test-double-" + label, "version": "fixed",
                "adapter_sha256": label + "-test-hash" if adapter else None}
        def __init__(self, config=None, adapter=None, label="Base"):
            super().__init__()
            Model.loads += 1
            self.settings = self.settings_for(config, adapter, label)
            self.fatal_error = None
        def decide(self, context):
            if fatal:
                self.fatal_error = "CUDA backend unavailable (test double)"
                raise RuntimeError(self.fatal_error)
            return super().decide(context)
        def close(self):
            Model.closes += 1
    monkeypatch.setattr(evaluator, "HFModelClient", Model)
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"dataset": "test-data", "bundle": "test-contracts"}))
    return config, Model


def test_complete_resume_rebuilds_report_without_loading_model(monkeypatch, tmp_path):
    config, model = setup_evaluation(monkeypatch, tmp_path)
    output = tmp_path / "evaluation"
    first = evaluator.evaluate(config, "Base", None, "validation", output)
    assert first["full_system"]["tasks"] == 2
    assert model.loads == model.closes == 1
    (output / "evaluation.json").write_text('{"stale":true}')
    second = evaluator.evaluate(config, "Base", None, "validation", output, resume=True)
    assert first == second and model.loads == 1
    with pytest.raises(ValueError, match="model/data/code"):
        evaluator.evaluate(config, "Base", None, "validation", output, no_gate=True, resume=True)
    assert model.loads == 1
    path = next((output / "tasks").glob("*.json"))
    row = json.loads(path.read_text())
    row["metrics"]["tokens"] += 1
    path.write_text(json.dumps(row))
    with pytest.raises(ValueError, match="identity/content"):
        evaluator.evaluate(config, "Base", None, "validation", output, resume=True)
    assert model.loads == 1


def test_cuda_failure_stops_without_counting_a_completed_task(monkeypatch, tmp_path):
    config, model = setup_evaluation(monkeypatch, tmp_path, fatal=True)
    output = tmp_path / "evaluation"
    with pytest.raises(RuntimeError, match="infrastructure failed"):
        evaluator.evaluate(config, "Base", None, "validation", output)
    assert model.loads == model.closes == 1
    assert (output / "infrastructure_failure.json").is_file()
    assert not list((output / "tasks").glob("*.json"))
    assert not (output / "evaluation.json").exists()


def test_report_requires_frozen_weights_and_executed_complete_task_set(monkeypatch, tmp_path):
    from scripts.report_post_training import summarize_runs
    from skillforge.training_data import file_hash
    config, _ = setup_evaluation(monkeypatch, tmp_path)
    root = tmp_path / "comparison"
    root.mkdir()
    frozen = {"config_hash": file_hash(config), "adapters": {"SFT": "SFT-test-hash", "DPO": "DPO-test-hash"}}
    (root / "frozen_models.json").write_text(json.dumps(frozen))
    for label in ("Base", "SFT", "DPO", "DPO-no-gate"):
        model_label = label.removesuffix("-no-gate")
        # The injected fixtures contain validation-named tasks; the split field
        # is changed only inside this isolated test, never in project data.
        tasks = generate_tasks("test")[:2]
        monkeypatch.setattr(evaluator, "load_dataset", lambda _: ({"dataset_hash": "frozen-test-data"}, tasks))
        evaluator.evaluate(config, model_label, "test-adapter" if model_label != "Base" else None,
            "test", root / (label + "-test"), no_gate=label.endswith("-no-gate"))
    report = summarize_runs(root)
    assert len(report["summary"]) == 4 and report["paired_vs_base"]["DPO"] == {"helped": 0, "hurt": 0}
    path = root / "SFT-test/evaluation.json"
    altered = json.loads(path.read_text())
    altered["full_system"]["task_success_rate"] = 0.123
    path.write_text(json.dumps(altered))
    with pytest.raises(ValueError, match="summary differs"):
        summarize_runs(root)
