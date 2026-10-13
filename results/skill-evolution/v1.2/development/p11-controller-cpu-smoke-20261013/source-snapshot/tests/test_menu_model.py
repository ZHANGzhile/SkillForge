import json
import httpx
import pytest
from skillforge.menu_model import MenuModelClient
from skillforge.tool_schemas import tool_definitions


def context():
    return {'parameters':{'order_id':'O-demo','new_address':'123 Example Street'},'request':'Change address',
        'policy':'HIGH risk requires escalation', 'observations':{'customer.risk_level':'LOW'}, 'history':[],
        'available_tools':tool_definitions(), 'executable_skills':[{'skill_id':'address_skill','family':'modify_address',
            'inputs':['order_id','new_address']}]}


def model(tmp_path, monkeypatch, respond):
    profile = tmp_path/'model.json'
    profile.write_text(json.dumps({'adapter':'ollama_qwen3_raw','url':'http://localhost:11434/v1'}))
    monkeypatch.setenv('SKILLFORGE_MODEL_CONFIG',str(profile))
    original = httpx.Client
    monkeypatch.setattr(httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(respond),**kw))
    return MenuModelClient()


def test_model_can_choose_refusal_even_with_available_skill(tmp_path,monkeypatch):
    def respond(request):
        data=json.loads(request.content)
        choices=data['format']['properties']['choice']['enum']
        assert 'skill:address_skill' in choices and 'refuse' in choices and 'escalate' in choices
        assert 'stop' not in choices
        assert 'read:update_shipping_address' not in choices
        return httpx.Response(200,json={'response':'{"reason":"decline","choice":"refuse"}','prompt_eval_count':30,'eval_count':5})
    m=model(tmp_path,monkeypatch,respond)
    assert m.decide(context()).type=='refuse'  # Adapter must not replace with the expected skill.
    assert m.tokens==35 and len(m.exchanges)==1


def test_skill_binding_and_receipt_transition(tmp_path,monkeypatch):
    seen=[]
    def respond(request):
        choices=json.loads(request.content)['format']['properties']['choice']['enum']
        seen.append(choices)
        choice='skill:address_skill' if len(seen)==1 else 'stop'
        return httpx.Response(200,json={'response':json.dumps({'reason':'execute','choice':choice})})
    m=model(tmp_path,monkeypatch,respond)
    ctx=context()
    action=m.decide(ctx)
    assert action.type=='skill' and action.arguments==ctx['parameters']
    ctx['history']=[{'action':action.model_dump(),'result':{'success':True,'verification':{'matched':True}}}]
    assert m.decide(ctx).type=='stop'
    assert 'skill:address_skill' not in seen[1] and 'refuse' in seen[1] and 'escalate' in seen[1]


def test_invalid_model_choice_is_not_scripted_fallback(tmp_path,monkeypatch):
    m=model(tmp_path,monkeypatch,lambda r:httpx.Response(200,json={'response':'{"choice":"invented"}'}))
    with pytest.raises(KeyError):
        m.decide(context())
