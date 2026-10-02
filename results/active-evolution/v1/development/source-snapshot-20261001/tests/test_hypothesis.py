import pytest

from skillforge.evolution_schemas import Hypothesis, Predicate
from skillforge.hypothesis import generate_hypotheses


def test_conjunction_is_not_or_and_relaxation_recovers_false_block():
    predicates = (Predicate(field="customer.risk_level", op="eq", value="MEDIUM"),
        Predicate(field="request.amount", op="gt", value=3000))
    h = Hypothesis(hypothesis_id="h", kind="restrict", predicates=predicates)
    assert h.predict({"customer.risk_level": "LOW", "request.amount": 5000}, True) is True
    assert h.predict({"customer.risk_level": "MEDIUM", "request.amount": 3000}, True) is True
    assert h.predict({"customer.risk_level": "MEDIUM", "request.amount": 3001}, True) is False
    assert h.predict({"customer.risk_level": "MEDIUM"}, True) is None
    assert h.predict({"customer.risk_level": "LOW"}, True) is True
    relaxed = Hypothesis(hypothesis_id="r", kind="relax", predicates=predicates)
    assert relaxed.predict({"customer.risk_level": "MEDIUM", "request.amount": 3001}, False) is True


@pytest.mark.parametrize("op,value,expected", [("eq",100,True),("neq",100,False),("in",[100,200],True),
    ("not_in",[200],True),("lt",101,True),("lte",100,True),("gt",100,False),("gte",100,True)])
def test_operators(op, value, expected):
    assert Predicate(field="request.amount", op=op, value=value).matches({"request.amount":100}) is expected


def test_typed_domain_and_enumeration():
    for kwargs in [dict(field="hidden.rule",op="eq",value=True),dict(field="request.amount",op="gt",value=True),
        dict(field="customer.risk_level",op="lt",value="LOW"),dict(field="request.amount",op="in",value=3)]:
        with pytest.raises(ValueError):
            Predicate(**kwargs)
    hs = generate_hypotheses(["shipment.status", "customer.risk_level"])
    assert hs == generate_hypotheses(["customer.risk_level", "shipment.status"])
    assert {h.kind for h in hs} == {"no_change","restrict","relax","other"}
    assert all(len(h.predicates)<=2 for h in hs)
    assert all(p.field in {"shipment.status","customer.risk_level"} for h in hs for p in h.predicates)
