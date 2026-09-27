"""Optional, bounded prompt augmentation. No oracle, tools, or action selection."""
import copy

from skillforge.policies import READS

VERSION = "visible-policy-worksheet-v1"


def worksheet(context, step_index):
    state = context.get("observations", {})
    family = context.get("family")
    result = {
        "version": VERSION,
        "remaining_decisions": max(0, 16 - step_index),
        "priority_order": [
            "Permission denied/not found: refuse. Exhausted read retries: escalate.",
            "After authorized reads, HIGH customer risk requires escalation even if shipment is SHIPPED or address is invalid.",
            "Check the requested workflow before making a terminal refusal; failure of its first branch is not failure of the whole workflow.",
            "Once sufficient facts are known, choose the permitted action or terminal outcome. Re-reading unchanged facts does not resolve ineligibility.",
            "After successful mutation verify its resulting state once before stop; do not repeat the mutation. A successful verified Skill includes verification.",
        ],
    }
    if family == "composite":
        workflow = context.get("workflow")
        if workflow == "address_else_cancel_else_escalate":
            result["workflow"] = "Check address eligibility; if ineligible, check cancellation with order_id only (invalid address is not a cancellation condition); if neither is eligible, escalate. HIGH risk still requires escalation before mutations."
        elif workflow == "address_else_escalate":
            result["workflow"] = "Check address eligibility; if ineligible, escalate. This request does not authorize cancellation."
    if family == "refund":
        fields = ("payment.captured_amount", "payment.refunded_amount")
        if all(type(state.get(key)) is int for key in fields):
            remaining = state[fields[0]] - state[fields[1]]
            amount = context.get("parameters", {}).get("amount")
            result["refund_arithmetic"] = {"remaining": remaining, "requested_is_integer": type(amount) is int}
            if type(amount) is int:
                result["refund_arithmetic"].update(requested=amount, positive=amount > 0, exceeds_remaining=amount > remaining)
        result["refund_rule"] = "Check authorized customer risk and payment status too. Nonpositive/noninteger/excess amount means refuse without attempting a refund. Shipment status is irrelevant to refund eligibility."
    repeated = 0
    for item in reversed(context.get("history", [])):
        action = item.get("action") or {}
        if action.get("type") != "tool" or action.get("name") not in READS or item.get("error"):
            break
        repeated += 1
    result["consecutive_read_actions"] = repeated
    return result


def augment(context, step_index):
    value = copy.deepcopy(context)
    value["decision_guidance"] = worksheet(context, step_index)
    return value


class GuidedClient:
    def __init__(self, base, enabled, guidance_hash):
        self.base, self.enabled = base, enabled
        self.model = base.model
        self.settings = {**base.settings, "decision_guidance": VERSION if enabled else None,
                         "guidance_sha256": guidance_hash if enabled else None}
        self.inputs = []

    @property
    def tokens(self):
        return self.base.tokens

    @property
    def fatal_error(self):
        return self.base.fatal_error

    def begin(self):
        self.inputs = []

    def decide(self, context):
        sent = augment(context, len(self.inputs)) if self.enabled else copy.deepcopy(context)
        self.inputs.append(copy.deepcopy(sent))
        return self.base.decide(sent)
