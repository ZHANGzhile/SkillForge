"""Acceptance harness integration; test doubles stay inside tmp_path only."""
from contextlib import nullcontext
from types import SimpleNamespace

from fastapi.testclient import TestClient

from scripts import accept_trained_workbench as acceptance
from skillforge import api, workbench
from skillforge.dataset import write_dataset
from skillforge.model import ScriptedPolicy


def test_acceptance_downloads_actual_persisted_runs_and_manual_database(tmp_path, monkeypatch):
    dataset = tmp_path / "dataset"
    write_dataset(dataset, instances=1)
    monkeypatch.setenv("SKILLFORGE_DATASET", str(dataset))
    monkeypatch.setenv("SKILLFORGE_JOB_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setattr(workbench, "training_reserves_gpu", lambda: None)
    monkeypatch.setattr(workbench, "load_bundle", lambda *_: ({"bundle_hash": "explicit-test-double", "engineering_only": False}, []))
    class TestModel(ScriptedPolicy):
        model = "Qwen3-4B-NF4-TEST-DOUBLE-NOT-REAL"
        adapter = "openai"
        settings = {"server_identity": {"test_double": True}}
        def pin_identity(self):
            pass
    monkeypatch.setattr(workbench, "ModelClient", TestModel)
    with TestClient(api.app) as client:
        monkeypatch.setattr(acceptance, "httpx", SimpleNamespace(Client=lambda **kwargs: nullcontext(client)))
        # Poll quickly for a CPU-only in-process worker, without changing the
        # worker's own synchronization or the real acceptance timeout.
        import time
        monkeypatch.setattr(acceptance, "time", SimpleNamespace(monotonic=time.monotonic, sleep=lambda _: time.sleep(.01)))
        report = acceptance.accept("http://testserver", tmp_path / "acceptance")
    assert report["passed"] and len(report["cases"]) == 6
    assert all(row["database_verified"] and row["duplicate_submission_reused"] and row["events"] for row in report["cases"])
    assert (tmp_path / "acceptance/custom_partial_refund-environment.sqlite").is_file()
