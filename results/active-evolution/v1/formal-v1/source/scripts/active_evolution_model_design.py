"""Predeclared small Agent subprotocol; no learned rule or oracle is consulted.

This covers eight representative strata, not the CPU layer's full factor core.
Refund worlds share exactly the same design. Instances/templates remain split.
"""


def model_core(family, stable=False):
    def row(risk="LOW", shipment="NOT_STARTED", amount=1000, order="CONFIRMED",
            payment="CAPTURED", address=True):
        return (risk, order, shipment, payment, 10000, amount, address)

    if family=="refund":
        if stable:
            return [row(),row(risk="MEDIUM"),row(risk="HIGH"),row(payment="FAILED")]
        return [row(),row(risk="MEDIUM"),row(risk="MEDIUM",shipment="PROCESSING"),
            row(shipment="PROCESSING"),row(risk="HIGH",shipment="PROCESSING"),
            row(risk="MEDIUM",amount=3000),row(risk="MEDIUM",amount=3001),row(amount=3001)]
    if family=="modify_address":
        if stable:
            return [row(),row(risk="MEDIUM",shipment="PROCESSING"),
                row(order="PENDING"),row(shipment="SHIPPED")]
        return [row(),row(shipment="PROCESSING"),row(risk="MEDIUM"),
            row(risk="MEDIUM",shipment="PROCESSING"),row(risk="HIGH",shipment="PROCESSING"),
            row(shipment="SHIPPED"),row(order="PENDING",shipment="PROCESSING"),
            row(shipment="PROCESSING",address=False)]
    raise ValueError("undeclared model family")
