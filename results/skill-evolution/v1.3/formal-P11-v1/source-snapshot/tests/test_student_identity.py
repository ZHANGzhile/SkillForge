import json
import httpx
import pytest

from skillforge.dataset import digest
from skillforge.model import ModelClient


def test_private_student_version_is_pinned_across_decisions(tmp_path, monkeypatch):
    config = tmp_path / "student.json"
    config.write_text(json.dumps({"url": "http://127.0.0.1:8002/v1", "model": "test-SFT", "prompt_version": "v2",
        "require_server_identity": True}))
    monkeypatch.setenv("SKILLFORGE_MODEL_CONFIG", str(config))
    monkeypatch.delenv("SKILLFORGE_MODEL_NAME", raising=False)
    monkeypatch.delenv("SKILLFORGE_MODEL_URL", raising=False)
    current = {"adapter_sha256": "first-trained-version"}
    def handle(request):
        if request.url.path == "/health":
            return httpx.Response(200, json={"ready": True, "model": "test-SFT", "settings": current})
        return httpx.Response(200, json={"system_fingerprint": digest(current), "usage": {"total_tokens": 3},
            "choices": [{"message": {"content": '{"type":"refuse"}'}}]})
    client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client(transport=httpx.MockTransport(handle)))
    model = ModelClient()
    model.pin_identity()
    assert model.settings["server_identity"] == current
    assert model.decide({}).type == "refuse"
    current["adapter_sha256"] = "replacement-trained-version"
    with pytest.raises(ValueError, match="changed after"):
        model.decide({})
    fresh = ModelClient()
    fresh.pin_identity()
    assert fresh.settings != model.settings
