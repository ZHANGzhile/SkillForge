from pydantic import Field, StrictInt, ValidationError

from .schemas import StrictModel


class OrderInput(StrictModel):
    order_id: str = Field(default="O1", min_length=1, max_length=100)


class AddressInput(OrderInput):
    new_address: str


class RefundInput(OrderInput):
    amount: StrictInt


class TicketInput(OrderInput):
    reason: str = Field(default="manual review", max_length=2000)


INPUTS = {**{name: OrderInput for name in ["get_customer", "get_order", "get_order_items", "get_payment", "get_shipment", "cancel_order"]},
    "validate_address": AddressInput, "update_shipping_address": AddressInput, "issue_refund": RefundInput,
    "create_ticket": TicketInput, "escalate_to_human": TicketInput}


def tool_definitions():
    from .policies import MUTATIONS
    return [{"name": name, "input_schema": schema.model_json_schema(), "output_schema": {"type": "object"}, "side_effect": name in MUTATIONS,
        "description": name.replace("_", " "), "risk_level": "high" if name == "issue_refund" else "medium" if name in MUTATIONS else "read"}
        for name, schema in sorted(INPUTS.items())]
