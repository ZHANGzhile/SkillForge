"""Private Stage 2 tools and EOC. Agent/learner imports of scripts are denied."""
from contextlib import contextmanager
from unittest.mock import patch

from scripts.active_evolution_worlds import policy as world_policy
from skillforge.policies import eligibility as original_policy
from skillforge.schemas import ExpectedOutcome, Task
from skillforge import environment, verifier


def policy(world, name, state, args):
    return original_policy(name, state, args) if world == "H0" else world_policy(world, name, state, args)


@contextmanager
def private_policy(world):
    def selected(name, state, args): return policy(world, name, state, args)
    # All paired arms share this actual environment policy. The selected public
    # Boundary changes model context/Gate only, never the evaluator's rule.
    with patch.object(environment, "eligibility", selected), patch.object(verifier, "eligibility", selected):
        yield


def expected_task(ident, family, fixture, params, world, *, split="train", seed=2026101280):
    env = environment.Environment(fixture=fixture)
    try: initial = env.snapshot(params["order_id"])
    finally: env.close()
    tool = {"refund": "issue_refund", "modify_address": "update_shipping_address", "cancel_order": "cancel_order"}[family]
    decision = policy(world, tool, initial, params)
    state = ({"payment.refunded_amount": initial["payment.refunded_amount"] + params["amount"]} if family == "refund"
        else {"order.shipping_address": params["new_address"]} if family == "modify_address" else {"order.status": "CANCELLED"}) if decision == "allow" else {}
    unchanged = [] if decision == "allow" else ["payment.refunded_amount", "order.shipping_address", "order.status"]
    request = (f"Please refund {params['amount']} minor units for my order {params['order_id']}." if family == "refund" else
        f"Please change the shipping address of order {params['order_id']} to {params['new_address']}." if family == "modify_address" else
        f"Please cancel my order {params['order_id']}.")
    return Task(task_id=ident, family=family, request=request, customer_id=fixture["customer_id"], parameters=params,
        fixture=fixture, split=split, template_id="stage2-independent-business-dev", seed=seed,
        dataset_id="stage2-business-dev", instance_id=ident,
        expected=ExpectedOutcome(allowed_outcomes=[{"allow": "completed", "refuse": "refused", "escalate": "escalated"}[decision]],
            expected_state=state, unchanged_fields=unchanged)).model_dump()
