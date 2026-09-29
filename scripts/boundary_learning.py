"""Finite categorical boundary induction; no runtime-policy oracle access.

The feature domains and derived refund/address predicates are declared human
priors. This module learns condition selection, not the predicate semantics.
"""
import copy
import itertools

from skillforge.dataset import digest
from skillforge.schemas import Condition
from skillforge.skills import gate, matches, refund_facts

DOMAINS = {
    "customer.risk_level": ["LOW", "MEDIUM", "HIGH"],
    "order.status": ["CONFIRMED", "CANCELLED", "PENDING"],
    "shipment.status": ["NOT_STARTED", "PROCESSING", "SHIPPED", "DELIVERED"],
    "payment.status": ["CAPTURED", "PARTIALLY_REFUNDED", "FAILED"],
    "address.valid": [False, True], "refund.amount_valid": [False, True],
}


def fields(family):
    return (["customer.risk_level", "payment.status", "refund.amount_valid"] if family == "refund" else
            ["customer.risk_level", "order.status", "shipment.status"] + (["address.valid"] if family == "modify_address" else []))


def procedure_hash(skill):
    return digest({k: skill.model_dump()[k] for k in ("skill_id", "family", "inputs", "procedure", "postconditions")})


def boundary_signature(skill):
    return {k: [{x: c.model_dump()[x] for x in ("field", "op", "value")} for c in getattr(skill, k)]
            for k in ("preconditions", "forbidden_conditions")}


def public_contract(skill):
    value = skill.model_dump(exclude={"statistics", "source_trajectory_ids"})
    for key in ("preconditions", "forbidden_conditions"):
        for condition in value[key]:
            condition.pop("evidence", None)
    return value


def condition_accepts(item, state):
    condition = Condition(field=item["field"], op=item["op"], value=item["value"], evidence=["declared-feature"])
    result = matches(condition, state)
    return not result if item["forbidden"] else result


def candidates(family):
    """Enumerate the same bounded syntax for every group; no policy labels."""
    rows = []
    for field in fields(family):
        values = DOMAINS[field]
        for value in values:
            for forbidden in (False, True):
                rows.append(dict(field=field, op="eq", value=value, forbidden=forbidden))
        for size in range(2, len(values)):
            for subset in itertools.combinations(values, size):
                rows.append(dict(field=field, op="in", value=list(subset), forbidden=False))
    return sorted(rows, key=lambda c: (1 if c["op"] == "eq" else 2, digest(c)))


def refine(skill, positive, negative, limit):
    result = skill.model_copy(deep=True)
    trace = []
    pool = [c for c in candidates(skill.family) if all(condition_accepts(c, p["features"]) for p in positive)]
    remaining = [n for n in negative if gate(result, {**n["state"], **n["features"]}, n["parameters"]).status == "APPLICABLE"]
    for _ in range(limit):
        scored = [(sum(not condition_accepts(c, n["features"]) for n in remaining), i, c) for i, c in enumerate(pool)]
        if not scored or max(s[0] for s in scored) == 0:
            break
        covered, _, chosen = min(scored, key=lambda x: (-x[0], x[1]))
        rejected = [n for n in remaining if not condition_accepts(chosen, n["features"])]
        evidence = ["success:" + p["id"] for p in positive] + ["failure:" + n["id"] for n in rejected]
        condition = Condition(**{k: chosen[k] for k in ("field", "op", "value")}, evidence=evidence)
        getattr(result, "forbidden_conditions" if chosen["forbidden"] else "preconditions").append(condition)
        trace.append({"added": chosen, "excluded_failures": [n["id"] for n in rejected], "preserved_positive_count": len(positive)})
        remaining = [n for n in remaining if n not in rejected]
    return result, {"steps": trace, "unresolved_failures": [n["id"] for n in remaining]}


def fit_groups(base, examples, limit=6):
    if any(e["split"] != "train" for e in examples):
        raise ValueError("boundary learner accepts train procedure evidence only")
    examples = [e for e in examples if e["family"] == base.family]
    positive = [e for e in examples if e["label"] == "positive"]
    negative = [e for e in examples if e["label"] == "negative"]
    if not positive or not negative:
        raise ValueError("both successful and business-rejected procedure evidence required")
    a = base.model_copy(deep=True)
    a.preconditions, a.forbidden_conditions = [], []
    for field in fields(base.family):
        values = {p["features"][field] for p in positive}
        if len(values) == 1:
            a.preconditions.append(Condition(field=field, value=next(iter(values)), evidence=["success:" + p["id"] for p in positive]))
    a.source_trajectory_ids = [p["id"] for p in positive]
    c = base.model_copy(deep=True)
    for condition in c.preconditions + c.forbidden_conditions:
        condition.evidence = ["declared-policy:" + condition.field]
    c.source_trajectory_ids = []
    b, b_trace = refine(a, positive, negative, limit)
    d, d_trace = refine(c, positive, negative, limit)
    b.source_trajectory_ids = d.source_trajectory_ids = [e["id"] for e in positive + negative]
    groups = dict(A=a, B=b, C=c, D=d)
    for skill in groups.values():
        skill.status = "VALIDATING"
        skill.statistics = {}
        if procedure_hash(skill) != procedure_hash(base):
            raise ValueError("boundary study changed the fixed procedure")
    return groups, {"B": b_trace, "D": d_trace, "positive_count": len(positive), "negative_count": len(negative)}


def features(family, state, parameters):
    # Same hand-engineered input predicate used by the existing environment.
    from skillforge.policies import valid_address
    result = refund_facts(state, parameters) if family == "refund" else dict(state)
    if family == "modify_address":
        result["address.valid"] = valid_address(parameters.get("new_address"))
    return {field: result[field] for field in fields(family)}


def oracle(family, observed, parameters):
    """Independent explicit scenario truth, three-valued over partial facts.

    Checked against actual environment executions by the dataset builder.
    It describes procedure applicability, not which terminal EOC to choose.
    """
    known = refund_facts(observed, parameters) if family == "refund" else observed
    requirements = [("customer.risk_level", ["LOW", "MEDIUM"])]
    if family == "refund":
        requirements += [("payment.status", ["CAPTURED", "PARTIALLY_REFUNDED"]), ("refund.amount_valid", [True])]
    else:
        requirements += [("order.status", ["CONFIRMED"]), ("shipment.status", ["NOT_STARTED"])]
        if family == "modify_address":
            requirements += [("address.valid", [True])]
    if any(key in known and known[key] not in allowed for key, allowed in requirements):
        return "INAPPLICABLE"
    return "APPLICABLE" if all(key in known for key, _ in requirements) else "UNKNOWN"
