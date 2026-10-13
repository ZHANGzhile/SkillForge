"""Bounded model-view transformation; never replaces the execution contract."""
import copy
import itertools
import json

from scripts.boundary_learning import public_contract
from skillforge.schemas import Condition
from skillforge.skills import gate

DOMAIN = ("CAPTURED", "PARTIALLY_REFUNDED", "FAILED")
FORBIDDEN = {"field": "payment.status", "op": "eq", "value": "FAILED"}
ALLOWED = {"field": "payment.status", "op": "in", "value": ["CAPTURED", "PARTIALLY_REFUNDED"]}


def render(context, arm):
    if arm not in {"original", "allowlist_view"}:
        raise ValueError("unknown representation arm")
    result = copy.deepcopy(context)
    if arm == "original" or context.get("observations", {}).get("payment.status") not in DOMAIN:
        return result
    for skill in result.get("executable_skills", []):
        if skill["family"] != "refund":
            continue
        if skill["forbidden_conditions"].count(FORBIDDEN) != 1 or any(c["field"] == "payment.status" for c in skill["preconditions"]):
            raise ValueError("renderer requires the frozen B payment boundary")
        skill["forbidden_conditions"].remove(FORBIDDEN)
        skill["preconditions"].insert(0, copy.deepcopy(ALLOWED))
    return result


def equivalent_states(base):
    counts = {"checked": 0, "transformed": 0, "unchanged": 0, "states": {}}
    for payment, risk, amount, balance in itertools.product((*DOMAIN, "REFUNDED", "UNDECLARED", None),
            ("LOW", "MEDIUM", "HIGH", None), (0, 100, 101, None), (True, False)):
        observed = {}
        if payment is not None:
            observed["payment.status"] = payment
        if risk is not None:
            observed["customer.risk_level"] = risk
        if balance:
            observed.update({"payment.captured_amount": 100, "payment.refunded_amount": 0})
        params = {} if amount is None else {"amount": amount}
        context = {"observations": observed, "executable_skills": [public_contract(base)]}
        view = render(context, "allowlist_view")["executable_skills"][0]
        shown = base.model_copy(deep=True)
        for key in ("preconditions", "forbidden_conditions"):
            setattr(shown, key, [Condition(**c, evidence=["display-proof-only"]) for c in view[key]])
        before, after = gate(base, observed, params).status, gate(shown, observed, params).status
        if before != after:
            raise ValueError("view changes current-state applicability")
        changed = view != public_contract(base)
        counts["checked"] += 1
        counts["transformed" if changed else "unchanged"] += 1
        counts["states"][before] = counts["states"].get(before, 0) + 1
    return counts


class ViewClient:
    def __init__(self, base, arm):
        self.base, self.arm = base, arm
        self.model, self.settings = base.model, base.settings
        self.inputs, self.messages = [], []

    @property
    def tokens(self):
        return self.base.tokens

    @property
    def fatal_error(self):
        return self.base.fatal_error

    def decide(self, context):
        sent = render(context, self.arm)
        self.inputs.append(copy.deepcopy(sent))
        self.messages.append(json.dumps(sent, ensure_ascii=False))
        return self.base.decide(sent)
