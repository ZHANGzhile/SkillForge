"""Optional refund policy clarification; never selects or replaces an Action."""
import copy
import json

from scripts.boundary_representation import render as render_boundary

CLARIFICATION = (
    " Refund outcome precedence (after authorized observations): first check customer risk. "
    "If customer.risk_level is HIGH, escalate for manual review even when payment.status is FAILED "
    "or the requested amount is invalid or exceeds the remaining balance. "
    "Payment/amount refusal rules apply only after customer risk is known and is not HIGH. "
    "Missing customer risk requires an authorized read; missing does not mean non-HIGH. "
    "An inapplicable Skill cannot determine whether the required outcome is refusal or escalation."
)


def render(context, arm):
    if arm not in {"control", "priority"}:
        raise ValueError("unknown refund priority arm")
    # Both arms include the separately studied display repair; execution stays B.
    result = render_boundary(context, "allowlist_view")
    if arm == "priority" and result.get("family") == "refund":
        result["policy"] += CLARIFICATION
    return result


class PriorityClient:
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
