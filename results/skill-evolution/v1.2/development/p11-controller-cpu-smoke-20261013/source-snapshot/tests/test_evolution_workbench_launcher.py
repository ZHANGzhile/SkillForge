import json

import pytest

from scripts import start_active_evolution_workbench as launcher


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(launcher, "get", lambda url: None)
    def forbidden(*args, **kwargs):
        raise AssertionError("Model or Workbench process must not start")
    monkeypatch.setattr(launcher, "launch", forbidden)
    return tmp_path


def test_active_formal_gpu_lease_prevents_workbench_start(isolated):
    lease = isolated / ".runtime/active-evolution-gpu-lease.json"
    lease.parent.mkdir()
    lease.write_text("{}")
    with pytest.raises(RuntimeError, match="GPU evaluation is active"):
        launcher.start()


def test_missing_delivery_audit_does_not_start_a_gpu_model(isolated):
    with pytest.raises(RuntimeError, match="delivery audit"):
        launcher.start()


def test_wrong_protocol_receipt_cannot_start_workbench(isolated, monkeypatch):
    import scripts.active_evolution_formal as formal
    monkeypatch.setattr(formal, "load_protocol", lambda root: {"model_settings": {"adapter_sha256": "fixed"}})
    receipt = isolated / "results/active-evolution/v1/formal-v1/delivery-audit.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(json.dumps({"passed": True, "protocol_hash": "another-protocol"}))
    with pytest.raises(RuntimeError, match="different protocol"):
        launcher.start()


def test_preview_reuse_needs_no_model_or_deployment(isolated, monkeypatch):
    monkeypatch.setattr(launcher, "get", lambda url: {"ready": True} if ":8081/" in url else None)
    assert launcher.start(preview=True) == {"url": "http://127.0.0.1:8081/evolution", "reused": True, "preview": True}
