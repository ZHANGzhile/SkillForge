"""Centralized business policy; no model calls or database access."""

POLICY_VERSION = "v1.1"
MUTATIONS = {"update_shipping_address", "cancel_order", "issue_refund", "create_ticket", "escalate_to_human"}
READS = {"get_customer", "get_order", "get_order_items", "get_payment", "get_shipment", "validate_address"}
TOOLS = MUTATIONS | READS


def eligibility(tool: str, state: dict, args: dict) -> str:
    if tool in {"create_ticket", "escalate_to_human"}:
        return "allow"
    if state.get("customer.risk_level") == "HIGH":
        return "escalate"
    if tool in {"update_shipping_address", "cancel_order"}:
        if state.get("shipment.status") in {"SHIPPED", "DELIVERED"}:
            return "refuse"
        if tool == "cancel_order" and state.get("order.status") == "CANCELLED":
            return "allow"
        if state.get("order.status") != "CONFIRMED" or state.get("shipment.status") != "NOT_STARTED":
            return "escalate"
        if tool == "update_shipping_address" and not valid_address(args.get("new_address")):
            return "refuse"
    if tool == "issue_refund":
        amount = args.get("amount")
        if type(amount) is not int or amount <= 0:
            return "refuse"
        if state.get("payment.status") not in {"CAPTURED", "PARTIALLY_REFUNDED"}:
            return "refuse"
        if amount > state["payment.captured_amount"] - state["payment.refunded_amount"]:
            return "refuse"
    return "allow"


def valid_address(address):
    return isinstance(address, str) and 8 <= len(address.strip()) <= 300
