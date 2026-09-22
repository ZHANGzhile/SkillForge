import json

import httpx
import hashlib
import pytest

from skillforge.model import ModelClient


def test_profile_controls_request_and_env_overrides(tmp_path, monkeypatch):
    path = tmp_path / 'model.json'
    path.write_text(json.dumps({'url': 'http://127.0.0.1:11434/v1', 'model': 'local-model',
        'reasoning_effort': 'none', 'max_tokens': 512, 'seed': 42, 'timeout_seconds': 120}))
    monkeypatch.setenv('SKILLFORGE_MODEL_CONFIG', str(path))
    monkeypatch.delenv('SKILLFORGE_MODEL_URL', raising=False)
    monkeypatch.setenv('SKILLFORGE_MODEL_NAME', 'override')
    captured = []
    original = httpx.Client
    def respond(request):
        payload = json.loads(request.content)
        captured.append(payload)
        return httpx.Response(200, json={'choices': [{'message': {'content': '{"type":"stop"}'}}], 'usage': {'total_tokens': 15}})
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    client = ModelClient()
    assert client.model == 'override'
    assert client.decide({'request': 'done'}).type == 'stop'
    assert captured[0]['reasoning_effort'] == 'none'
    assert captured[0]['max_tokens'] == 512
    assert client.tokens == 15
    assert client.settings['reasoning_effort'] == 'none'
    assert 'key' not in client.settings


def test_qwen3_raw_adapter_preserves_messages_and_accounts_tokens(tmp_path, monkeypatch):
    path = tmp_path / 'model.json'
    path.write_text(json.dumps({'url': 'http://127.0.0.1:11434/v1', 'model': 'qwen3',
        'adapter': 'ollama_qwen3_raw', 'max_tokens': 512, 'seed': 42}))
    monkeypatch.setenv('SKILLFORGE_MODEL_CONFIG', str(path))
    monkeypatch.delenv('SKILLFORGE_MODEL_URL', raising=False)
    original = httpx.Client
    def respond(request):
        assert request.url.path == '/api/generate'
        payload = json.loads(request.content)
        assert payload['raw'] is True and payload['stream'] is False
        assert 'Read required state' in payload['prompt']
        assert 'probe-context' in payload['prompt']
        assert payload['prompt'].endswith('<think>\n\n</think>\n\n')
        assert payload['options'] == {'temperature': 0, 'num_predict': 512, 'seed': 42}
        return httpx.Response(200, json={'response': '{"type":"stop"}',
            'prompt_eval_count': 100, 'eval_count': 7})
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    client = ModelClient()
    assert client.decide({'request': 'probe-context'}).type == 'stop'
    assert client.tokens == 107
    assert client.settings['adapter'] == 'ollama_qwen3_raw'


def test_prompt_version_is_explicit_and_reproducible(tmp_path, monkeypatch):
    path = tmp_path / 'model.json'
    path.write_text(json.dumps({'prompt_version': 'v2'}))
    monkeypatch.setenv('SKILLFORGE_MODEL_CONFIG', str(path))
    client = ModelClient()
    assert client.settings['prompt_version'] == 'v2'
    assert client.settings['prompt_sha256'] == hashlib.sha256(client.system_prompt.encode()).hexdigest()
    path.write_text(json.dumps({'prompt_version': 'missing-version'}))
    with pytest.raises(ValueError, match='prompt version'):
        ModelClient()
