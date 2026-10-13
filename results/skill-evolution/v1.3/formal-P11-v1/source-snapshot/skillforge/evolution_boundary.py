"""Versioned old-contract adapter and immutable safety floor. No new-policy oracle."""
from .evolution_schemas import fingerprint
from .schemas import SkillContract
from .skills import gate


def parent_identity(contract):
    skill = SkillContract.model_validate(contract)
    return {"contract_hash": fingerprint(skill.model_dump(mode="json")),
            "procedure_hash": fingerprint({k: contract[k] for k in ("inputs", "procedure", "postconditions")}),
            "skill_id": skill.skill_id, "version": skill.version}


def public_predictions(contract, facts, parameters):
    """The existing policy floor is declared prior knowledge, never learned gold."""
    skill = SkillContract.model_validate(contract)
    base = gate(skill, facts, parameters).status
    baseline = True if base == "APPLICABLE" else False if base == "INAPPLICABLE" else None
    floor = [("customer.risk_level", ("LOW", "MEDIUM"))]
    if skill.family == "refund":
        floor += [("payment.status", ("CAPTURED", "PARTIALLY_REFUNDED")), ("refund.amount_valid", (True,))]
    else:
        floor += [("order.status", ("CONFIRMED",)), ("shipment.status", ("NOT_STARTED", "PROCESSING"))]
        if skill.family == "modify_address":
            floor += [("address.valid", (True,))]
    if any(field in facts and facts[field] not in allowed for field, allowed in floor):
        guard = False
    elif all(field in facts for field, _ in floor):
        guard = True
    else:
        guard = None
    return baseline, guard
