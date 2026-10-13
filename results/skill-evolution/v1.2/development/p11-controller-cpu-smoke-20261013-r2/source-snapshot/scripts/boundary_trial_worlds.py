"""Private registered continuous-study worlds; never imported by workers."""
from contextlib import contextmanager
from unittest.mock import patch

from scripts.boundary_stage2_evaluator import policy as known_policy
from skillforge import environment, verifier


def policy(world, name, state, args):
    if world != "STRUCTURAL3": return known_policy(world, name, state, args)
    prior = known_policy("H0", name, state, args)
    if (prior == "allow" and name == "issue_refund" and state.get("customer.risk_level") == "MEDIUM"
            and state.get("shipment.status") == "PROCESSING" and state.get("payment.status") == "PARTIALLY_REFUNDED"):
        return "escalate"
    return prior


@contextmanager
def selected_policy(world):
    def selected(name, state, args): return policy(world, name, state, args)
    with patch.object(environment, "eligibility", selected), patch.object(verifier, "eligibility", selected): yield
