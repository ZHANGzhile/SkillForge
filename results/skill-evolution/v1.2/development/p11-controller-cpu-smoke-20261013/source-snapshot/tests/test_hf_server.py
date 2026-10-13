from fastapi.testclient import TestClient
from skillforge import hf_server
from skillforge.prompts import PROMPTS
from skillforge.schemas import Action


def test_private_student_protocol_and_no_fallback(monkeypatch):
    class Model:
        model = 'Qwen3-4B-NF4-SFT'
        tokens = 0
        settings = {'test_double': True}
        def decide(self, context):
            if context.get('fail'):
                raise ValueError('invalid generated Action')
            self.tokens += 23
            return Action(type='refuse')
        def close(self):
            pass
    monkeypatch.setattr(hf_server, 'HFModelClient', lambda **kwargs: Model())
    body = {'model': Model.model, 'messages': [{'role': 'system', 'content': PROMPTS['v2']}, {'role': 'user', 'content': '{}'}]}
    with TestClient(hf_server.app) as client:
        assert client.get('/health').json()['ready']
        response = client.post('/v1/chat/completions', json=body)
        assert response.status_code == 200
        assert response.json()['usage']['total_tokens'] == 23
        assert 'refuse' in response.json()['choices'][0]['message']['content']
        assert client.post('/v1/chat/completions', json={**body, 'model': 'unknown'}).status_code == 404
        assert client.post('/v1/chat/completions', json={**body, 'max_tokens': 3}).status_code == 422
        body['messages'][1]['content'] = '{"fail":true}'
        assert client.post('/v1/chat/completions', json=body).status_code == 502
        body['messages'][0]['content'] = 'changed protocol'
        assert client.post('/v1/chat/completions', json=body).status_code == 400
