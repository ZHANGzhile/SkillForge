import copy
import json
from types import SimpleNamespace

import pytest

from scripts import evaluate_boundary_repeatability as repeat
from skillforge.dataset import digest


def test_selection_uses_serialized_order_and_excludes_alias_and_forced_steps():
    def row(context, action, forced=0):
        return {"boundary_experiment": {"forced_decisions": forced, "actual_model_inputs": [context]},
                "steps": ([{"action": {"type": "skill"}}] if forced else []) + [{"action": action}]}
    first, second = {"a": 1, "b": 2}, {"b": 2, "a": 1}
    stop, refuse = {"type": "stop"}, {"type": "refuse"}
    rows = {"t-A-autonomous": row(first, stop), "t-B-autonomous": row(second, stop),
            "t-C-autonomous": row(first, stop), "forced": row(first, refuse, 1),
            "alias": row(second, refuse)}
    selected = repeat.select_inputs(rows, {"alias": "t-B-autonomous"},
                                    {"groups": list("ABC"), "regression_task": "t", "stable_controls": 2})
    assert len(selected) == 2
    left, right = selected[digest(json.dumps(first))], selected[digest(json.dumps(second))]
    assert "historical_divergence" in left["selection"]
    assert "historical_divergence" not in right["selection"]
    assert all(ref["run"] != "alias" for ref in right["source_references"])
    assert next(r for r in left["source_references"] if r["run"] == "forced")["step"] == 1


def test_exact_request_preserves_text_and_checks_response_identity(monkeypatch):
    settings = {"system_prompt": "fixed"}
    model = SimpleNamespace(model="test", system_prompt="fixed", request_options={"seed": 42, "max_tokens": 512},
                            timeout=1, url="http://test/v1", key="unused", settings={"server_identity": settings},
                            expected_fingerprint=digest(settings))
    payload = {"system_fingerprint": digest(settings), "choices": [{"message": {"content": '{"type":"refuse"}'}}]}
    class Client:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def post(self, url, headers, json):
            assert json["messages"][1]["content"] == '{"z": 1, "a": 2}'
            return SimpleNamespace(status_code=200, json=lambda: payload, raise_for_status=lambda: None)
    monkeypatch.setattr(repeat.httpx, "Client", Client)
    monkeypatch.setattr(repeat, "read", lambda _: {"model": "test", "seed": 42, "max_tokens": 512})
    text = '{"z": 1, "a": 2}'
    row = repeat.exact_request(model, text)
    item = {"input": digest(text)}
    frozen = {"model_settings": settings, "inputs": {digest(text): {"user_json": text}}}
    repeat.check_exact(row, item, frozen, {"client_profile": "unused"})
    tampered = copy.deepcopy(row)
    tampered["request"]["messages"][1]["content"] = '{"a": 2, "z": 1}'
    with pytest.raises(ValueError, match="request/identity"):
        repeat.check_exact(tampered, item, frozen, {"client_profile": "unused"})
    payload["system_fingerprint"] = "wrong"
    with pytest.raises(ValueError, match="changed"):
        repeat.exact_request(model, text)


def test_resume_rejects_changed_freeze_before_model_connection(tmp_path, monkeypatch):
    frozen = {"jobs": {}}
    (tmp_path / "freeze.json").write_text('{"jobs": {"changed": 1}}')
    monkeypatch.setattr(repeat, "prepare", lambda: ({}, {}, tmp_path, {}, {}, frozen))
    monkeypatch.setattr(repeat, "create_client", lambda *_: pytest.fail("must not contact service"))
    with pytest.raises(ValueError, match="frozen protocol"):
        repeat.run()
