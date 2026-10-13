"""Evaluator-side policy oracle. Never import from learner modules."""
from skillforge.policies import eligibility as old_policy, valid_address

WORLDS = ("W1", "W2", "W3", "W4", "W5", "W6")


def policy(world, tool, state, arguments):
    if world not in WORLDS:
        raise ValueError("unknown world")
    original = old_policy(tool, state, arguments)
    if world == "W6" and tool == "update_shipping_address":
        if state.get("customer.risk_level") == "LOW" and state.get("order.status") == "CONFIRMED" and state.get("shipment.status") == "PROCESSING" and valid_address(arguments.get("new_address")):
            return "allow"
    if original != "allow" or tool != "issue_refund":
        return original
    if world == "W1" and state.get("shipment.status") == "PROCESSING":
        return "escalate"
    if world == "W2" and state.get("order.status") == "PENDING":
        return "escalate"
    if world == "W3" and state.get("customer.risk_level") == "MEDIUM" and arguments["amount"] > 3000:
        return "escalate"
    if world == "W4" and state.get("payment.status") == "PARTIALLY_REFUNDED" and state["payment.captured_amount"]-state["payment.refunded_amount"] < 5000:
        return "refuse"
    if world == "W5" and state.get("customer.risk_level") == "MEDIUM" and state.get("shipment.status") == "PROCESSING":
        return "refuse"
    return original


def difference_witnesses():
    common = {"customer.risk_level":"LOW", "order.status":"CONFIRMED", "shipment.status":"NOT_STARTED",
        "payment.status":"CAPTURED", "payment.captured_amount":20000,"payment.refunded_amount":0}
    cases = {"W1": {"shipment.status":"PROCESSING"}, "W2":{"order.status":"PENDING"},
        "W3":{"customer.risk_level":"MEDIUM"}, "W4":{"payment.status":"PARTIALLY_REFUNDED","payment.refunded_amount":16000},
        "W5":{"customer.risk_level":"MEDIUM","shipment.status":"PROCESSING"}, "W6":{"shipment.status":"PROCESSING"}}
    result = []
    for world, delta in cases.items():
        state = {**common, **delta}
        args = {"amount":3500,"new_address":"Valid delivery address 200"}
        tool = "update_shipping_address" if world=="W6" else "issue_refund"
        before, after = old_policy(tool,state,args),policy(world,tool,state,args)
        if (before == "allow") == (after == "allow"):
            raise ValueError("world has no witnessed applicability change")
        result.append({"world":world,"state":state,"arguments":args,"before":before,"after":after})
    return result
