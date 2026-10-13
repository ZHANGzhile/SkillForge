"""Program bytes stay frozen; separately hashed public Boundary replaces prior."""
from ..skill_evolution.catalog import Catalog
from ..evolution_schemas import Hypothesis, DOMAINS, fingerprint, check_fact
from ..evolution_common.artifacts import clone
from ..evolution_boundary import public_predictions, parent_identity
from ..skills import refund_facts
from ..schemas import GateResult, SkillContract


class BoundaryCatalog(Catalog):
    def __init__(self, entries, boundaries):
        super().__init__(entries)
        if set(boundaries) != {entry["skill_id"] for entry in self.entries()}:
            raise ValueError("one explicit Boundary binding per selected program required")
        checked = {}
        for entry in self.entries():
            value = clone(boundaries[entry["skill_id"]])
            if set(value) != {"parent_revision", "program_hash", "patch", "support_domain"}:
                raise ValueError("complete explicit Boundary/program/support binding required")
            if (value["parent_revision"] != entry["revision"] or value["program_hash"] !=
                    parent_identity(entry["contract"])["procedure_hash"]):
                raise ValueError("Boundary cannot change or silently rebind the frozen program")
            patch = Hypothesis.model_validate(value["patch"])
            if patch.kind == "other": raise ValueError("OTHER is not an executable Boundary")
            support = value["support_domain"]
            if set(support) != {"schema", "fields"} or support["schema"] != "declared-public-support-v1":
                raise ValueError("versioned declared public support required")
            for field, allowed in support["fields"].items():
                if field not in DOMAINS or (allowed is not None and
                        (not isinstance(allowed, list) or not allowed or DOMAINS[field] is None or
                         any(v not in DOMAINS[field] for v in allowed))):
                    raise ValueError("support outside declared public feature schema")
                if allowed is not None:
                    for allowed_value in allowed: check_fact(field, allowed_value)
            checked[entry["skill_id"]] = {**value, "patch": patch.model_dump(mode="json")}
        self._boundaries = clone(checked)
        self.bundle_hash = fingerprint({"schema": "program-boundary-bundle-v1", "catalog": self.hash,
                                        "boundaries": checked, "immutable_guard": "inherited-public-floor-v1"})

    def boundaries(self): return clone(self._boundaries)

    def public_boundary(self, skill_id):
        body = clone(self._boundaries[skill_id])
        return {"schema": "catalog-business-boundary-view-v1", **body, "revision": fingerprint(body),
            "semantics": "replace corresponding parent business boundary; immutable Guard and tool authorization remain independent",
            "terminal_policy": "inherited-terminal-rules-v1; applicability is not a refuse/escalate label"}

    def search_audited(self, query, top_k=5):
        results, audit = super().search_audited(query, top_k)
        for value in results:
            value["parent_applicable_when"] = value.pop("applicable_when")
            value["parent_forbidden_when"] = value.pop("forbidden_when")
            value["effective_boundary"] = self.public_boundary(value["skill_id"])
        audit.update(boundary_bundle_hash=self.bundle_hash)
        return results, audit

    def public_load(self, skill_id, rev, *, enrich=False):
        value = super().public_load(skill_id, rev, enrich=enrich)
        value["parent_applicable_when"] = value.pop("applicable_when")
        value["parent_forbidden_when"] = value.pop("forbidden_when")
        value["effective_boundary"] = self.public_boundary(skill_id)
        return value

    def effective_gate(self, skill, observations, parameters):
        skill = SkillContract.model_validate(skill)
        if any(key not in parameters for key in skill.inputs):
            return GateResult(status="UNKNOWN", missing_fields=["input." + key for key in skill.inputs if key not in parameters])
        facts = refund_facts(observations, parameters) if skill.family == "refund" else dict(observations)
        if skill.family == "refund":
            facts["request.amount"] = parameters["amount"]
            a, b = facts.get("payment.captured_amount"), facts.get("payment.refunded_amount")
            if type(a) is int and type(b) is int: facts["payment.remaining_amount"] = a - b
        value = self._boundaries[skill.skill_id]
        patch = Hypothesis.model_validate(value["patch"])
        baseline, guard = public_predictions(skill.model_dump(), facts, parameters)
        if guard is False:
            return GateResult(status="INAPPLICABLE", reason="immutable public Guard")
        for field, allowed in value["support_domain"]["fields"].items():
            if field not in facts and allowed is not None and set(allowed) != set(DOMAINS[field]):
                return GateResult(status="UNKNOWN", missing_fields=[field], reason="declared support membership not observed")
            if field in facts and allowed is not None and facts[field] not in allowed:
                return GateResult(status="UNKNOWN", reason="outside declared Boundary support")
        predicted = patch.predict(facts, baseline, guard)
        missing = {c.field for c in skill.preconditions + skill.forbidden_conditions if c.field not in facts}
        missing.update(p.field for p in patch.predicates if p.field not in facts)
        return GateResult(status="APPLICABLE" if predicted is True else "INAPPLICABLE" if predicted is False else "UNKNOWN",
            missing_fields=sorted(missing) if predicted is None else [],
            reason="effective versioned Boundary under immutable public Guard")


def h0_bindings(catalog):
    return {entry["skill_id"]: {"parent_revision": entry["revision"],
        "program_hash": parent_identity(entry["contract"])["procedure_hash"],
        "patch": {"hypothesis_id": "H0", "kind": "no_change", "predicates": []},
        "support_domain": {"schema": "declared-public-support-v1", "fields": {key: list(value) if value else None
            for key, value in DOMAINS.items()}}} for entry in catalog.entries()}
