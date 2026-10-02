"""Independent, finite active-learning contracts; no policy/oracle imports."""
import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


DOMAINS = {
    "customer.risk_level": ("LOW", "MEDIUM", "HIGH"),
    "order.status": ("CONFIRMED", "PENDING", "CANCELLED"),
    "shipment.status": ("NOT_STARTED", "PROCESSING", "SHIPPED", "DELIVERED"),
    "payment.status": ("CAPTURED", "PARTIALLY_REFUNDED", "FAILED", "REFUNDED"),
    "address.valid": (False, True), "refund.amount_valid": (False, True),
    "request.amount": None, "payment.captured_amount": None,
    "payment.refunded_amount": None, "payment.remaining_amount": None,
}
LEARNING_SPLITS = {"seed", "explore"}


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def check_fact(field, value):
    if field not in DOMAINS:
        raise ValueError("field outside public feature schema")
    domain = DOMAINS[field]
    if domain is None:
        if type(value) is not int:
            raise ValueError("numeric features require integer minor units")
    elif not any(type(value) is type(v) and value == v for v in domain):
        raise ValueError("value outside public feature domain")


class Predicate(Record):
    field: str
    op: Literal["eq", "neq", "in", "not_in", "lt", "lte", "gt", "gte"]
    value: Any

    @model_validator(mode="after")
    def typed(self):
        values = self.value if self.op in {"in", "not_in"} else [self.value]
        if not isinstance(values, list) or not values:
            raise ValueError("membership requires nonempty list")
        for value in values:
            check_fact(self.field, value)
        if self.op in {"lt", "lte", "gt", "gte"} and DOMAINS[self.field] is not None:
            raise ValueError("ordered comparison requires numeric field")
        return self

    def matches(self, facts):
        if self.field not in facts:
            return None
        v = facts[self.field]
        check_fact(self.field, v)
        return {"eq": lambda: v == self.value, "neq": lambda: v != self.value,
            "in": lambda: v in self.value, "not_in": lambda: v not in self.value,
            "lt": lambda: v < self.value, "lte": lambda: v <= self.value,
            "gt": lambda: v > self.value, "gte": lambda: v >= self.value}[self.op]()


class Hypothesis(Record):
    hypothesis_id: str
    kind: Literal["no_change", "restrict", "relax", "other"]
    predicates: tuple[Predicate, ...] = Field(default=(), max_length=2)

    @model_validator(mode="after")
    def shape(self):
        if (self.kind in {"restrict", "relax"}) != bool(self.predicates):
            raise ValueError("structured patches require one or two predicates")
        return self

    def predict(self, facts, baseline):
        if self.kind == "other":
            return None
        if self.kind == "no_change":
            return baseline
        values = [p.matches(facts) for p in self.predicates]
        match = False if False in values else None if None in values else True
        # True/False here mean executability, not terminal outcome.
        if self.kind == "restrict":
            if baseline is False or match is True:
                return False
            return baseline if match is False else None
        if baseline is True or match is True:
            return True
        return baseline if match is False else None


class EvidenceView(Record):
    evidence_id: str
    trajectory_id: str
    member_hash: str
    split: Literal["seed", "explore"]
    policy_epoch: str
    family: Literal["refund", "modify_address", "cancel_order"]
    observations: dict[str, Any]
    baseline_prediction: bool | None
    label: Literal["executable", "not_executable", "unknown"]
    origin: Literal["controlled_procedure", "model_tool"]
    tool_calls: int = Field(ge=0)

    @model_validator(mode="after")
    def facts(self):
        for field, value in self.observations.items():
            check_fact(field, value)
        return self


class Candidate(Record):
    candidate_id: str
    observations: dict[str, Any]
    baseline_prediction: bool | None
    cost: float = Field(ge=0, allow_inf_nan=False)
    mutation_probability: float = Field(ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def facts(self):
        for field, value in self.observations.items():
            check_fact(field, value)
        return self
