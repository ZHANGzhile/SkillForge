"""Scope the failed v1 clarification to an already observed HIGH-risk refund."""
import copy
import itertools
import json

from scripts.refund_priority import PriorityClient, render as original_render


def enabled(context):
    return context.get("family") == "refund" and context.get("observations", {}).get("customer.risk_level") == "HIGH"


def render(context, arm):
    if arm not in {"control", "priority"}:
        raise ValueError("unknown scoped priority arm")
    return original_render(context, "priority" if arm == "priority" and enabled(context) else "control")


def activation_proof():
    counts = {"checked": 0, "activated": 0, "byte_identical": 0}
    for family, risk, payment in itertools.product(("refund", "modify_address", "cancel_order", "composite", "ticket", "shipment_investigation", None),
            ("LOW", "MEDIUM", "HIGH", "UNKNOWN", None), ("CAPTURED", "PARTIALLY_REFUNDED", "FAILED", "REFUNDED", None)):
        state = {}
        if risk is not None:
            state["customer.risk_level"] = risk
        if payment is not None:
            state["payment.status"] = payment
        context = {"family": family, "policy": "fixed original policy", "observations": state, "executable_skills": []}
        control, priority = (render(context, a) for a in ("control", "priority"))
        same = json.dumps(control, ensure_ascii=False) == json.dumps(priority, ensure_ascii=False)
        if same == enabled(context):
            raise ValueError("priority activation scope differs")
        if not same:
            priority["policy"] = control["policy"]
            if priority != control:
                raise ValueError("priority changed a non-policy field")
        counts["checked"] += 1
        counts["activated"] += int(not same)
        counts["byte_identical"] += int(same)
    return counts


class ScopedPriorityClient(PriorityClient):
    def decide(self, context):
        sent = render(context, self.arm)
        self.inputs.append(copy.deepcopy(sent))
        self.messages.append(json.dumps(sent, ensure_ascii=False))
        return self.base.decide(sent)
