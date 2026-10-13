"""Public receipt classification and bounded-window drift suspicion.

This module cannot call tools, read gold, activate a Boundary, or update Belief.
EvidenceViews enter only through a trusted adapter after tool-receipt audit.
Epoch/world identity never participates in a trigger or independence key.
"""
from collections import defaultdict
from typing import Literal

from pydantic import Field, model_validator

from ..evolution_schemas import Record, EvidenceView, fingerprint
from ..evolution_common.artifacts import clone
from ..gap_detection import detect_gaps, PATTERN_FIELDS


class TriggerPolicy(Record):
    schema_version: Literal["public-drift-trigger-v1"] = "public-drift-trigger-v1"
    independent_sources: int = Field(default=3, ge=3)
    window_events: int = Field(default=60, ge=3)
    probe_budget: int = Field(default=20, ge=0, le=20)


class Interaction(Record):
    """Trusted public adapter output, never an Agent-supplied label."""
    receipt_id: str
    source_group: str
    object_id: str
    parent_revision: str
    evidence: EvidenceView
    feedback: Literal["business", "unknown", "infrastructure", "permission", "arguments",
                      "program", "verification", "termination", "immutable_guard"]
    probe_origin: Literal["daily", "authorized_sandbox"]
    sandbox_id: str | None = None
    query_receipt_hash: str

    @model_validator(mode="after")
    def valid(self):
        for text in (self.receipt_id, self.source_group, self.object_id, self.parent_revision, self.query_receipt_hash):
            if not text:
                raise ValueError("complete receipt/source/parent identity required")
        if self.probe_origin == "authorized_sandbox" and not self.sandbox_id:
            raise ValueError("exploration requires a concrete authorized sandbox")
        if self.feedback not in {"business", "immutable_guard"} and self.evidence.label != "unknown":
            raise ValueError("non-business errors cannot teach executability")
        if self.feedback == "business" and self.evidence.label == "unknown":
            raise ValueError("business label requires attributable tool feedback")
        return self


def conflict(item):
    view = item.evidence
    if item.feedback == "immutable_guard":
        return "IMMUTABLE_GUARD_CONFLICT"
    if item.feedback != "business" or view.guard_prediction is not True:
        return None
    if view.label == "not_executable" and view.baseline_prediction is True:
        return "gate_false_allow"
    if view.label == "executable" and view.baseline_prediction is False:
        return "gate_false_block"
    return None


class DriftController:
    def __init__(self, policy=None):
        self.policy = TriggerPolicy.model_validate(policy or {})
        self.events = []
        self.seen = {}
        self.explorations = {}
        self.query_receipts = {}
        self.actions = []

    def observe(self, interaction):
        item = Interaction.model_validate(interaction)
        value = item.model_dump(mode="json")
        if item.receipt_id in self.seen:
            if self.seen[item.receipt_id] != fingerprint(value):
                raise ValueError("conflicting receipt replay")
            return self.events[self._index(item.receipt_id)]["decision"]
        active = [Interaction.model_validate(row["interaction"]) for row in
                  self.events[-(self.policy.window_events - 1):]] if self.policy.window_events > 1 else []
        active.append(item)
        matching = [row for row in active if row.parent_revision == item.parent_revision and
                    row.evidence.family == item.evidence.family]
        # Remove excluded failures before using the existing boundary-only gap lane.
        views = []
        for row in matching:
            if row.feedback == "business" and row.evidence.guard_prediction is True:
                views.append(row.evidence.model_copy(update={"policy_epoch": "public-stream"}))
        gaps = detect_gaps(views)
        kind = conflict(item)
        pattern = {key: item.evidence.observations[key] for key in PATTERN_FIELDS
                   if key in item.evidence.observations}
        members = [row for row in matching if conflict(row) == kind and
                   {key: row.evidence.observations[key] for key in PATTERN_FIELDS
                    if key in row.evidence.observations} == pattern]
        # Require independent provenance AND distinct objects; aliases/retries do not multiply evidence.
        by_source = defaultdict(set)
        for row in members:
            by_source[row.source_group].add(row.object_id)
        # A small exact bipartite matching avoids a greedy count depending on arrival order.
        assigned = {}
        def assign(source, visited):
            for obj in sorted(by_source[source]):
                if obj in visited:
                    continue
                visited.add(obj)
                if obj not in assigned or assign(assigned[obj], visited):
                    assigned[obj] = source
                    return True
            return False
        for source in sorted(by_source):
            assign(source, set())
        independent = len(assigned)
        state, reason, pause = "NO_CHANGE", "no attributable public business conflict", False
        if kind == "IMMUTABLE_GUARD_CONFLICT":
            state, reason, pause = "SUSPECTED_DRIFT", "immutable Guard breach: pause only; never learn a relaxation", True
        elif item.feedback == "infrastructure":
            state, reason = "INFRASTRUCTURE", "transient or transport failure is not a policy label"
        elif item.feedback in {"arguments", "program", "verification", "termination"}:
            state, reason = "MODEL_OR_PROGRAM_ERROR", item.feedback
        elif item.feedback == "permission":
            reason = "authorization denial is not mutable business eligibility"
        elif kind:
            state = "SUSPECTED_DRIFT" if independent >= self.policy.independent_sources else "INCONCLUSIVE"
            reason = "independent public business conflicts" if state == "SUSPECTED_DRIFT" else "insufficient independent business conflicts"
        elif item.feedback == "unknown":
            state, reason = "INCONCLUSIVE", "unattributable or missing feedback; no negative label inferred"
        key = fingerprint({"parent": item.parent_revision, "family": item.evidence.family,
                           "kind": kind, "pattern": pattern})
        if key in self.explorations and state == "SUSPECTED_DRIFT" and not pause:
            state = "EXPLORING"
        decision = {"state": state, "reason": reason, "conflict_type": kind, "trigger_key": key,
            "parent_revision": item.parent_revision, "family": item.evidence.family,
            "independent_sources": independent, "window_events": self.policy.window_events,
            "receipt_ids": sorted(row.receipt_id for row in members), "gap_ids": sorted(g["gap_id"] for g in gaps),
            "pause_related_skill": pause, "boundary_update_allowed": False,
            "belief_update_allowed": False, "probe_calls_started": 0}
        self.seen[item.receipt_id] = fingerprint(value)
        self.events.append({"interaction": value, "decision": decision})
        self.actions.append({"kind": "observe", "interaction": value})
        return clone(decision)

    def _index(self, receipt_id):
        return next(i for i, row in enumerate(self.events) if row["interaction"]["receipt_id"] == receipt_id)

    def begin_exploration(self, trigger_key, *, sandbox_id):
        decisions = [row["decision"] for row in self.events if row["decision"]["trigger_key"] == trigger_key]
        if (not decisions or decisions[-1]["state"] != "SUSPECTED_DRIFT" or
                decisions[-1]["pause_related_skill"] or not sandbox_id or trigger_key in self.explorations):
            raise ValueError("fresh supported suspicion and authorized sandbox required")
        self.explorations[trigger_key] = {"sandbox_id": sandbox_id, "used": 0,
            "limit": self.policy.probe_budget, "receipts": []}
        self.actions.append({"kind": "begin", "trigger_key": trigger_key, "sandbox_id": sandbox_id})
        return clone(self.explorations[trigger_key])

    def charge_probe(self, trigger_key, interaction):
        item = Interaction.model_validate(interaction)
        slot = self.explorations[trigger_key]
        decision = next(row["decision"] for row in self.events if row["decision"]["trigger_key"] == trigger_key)
        if (item.probe_origin != "authorized_sandbox" or item.sandbox_id != slot["sandbox_id"] or
                item.parent_revision != decision["parent_revision"] or item.evidence.family != decision["family"]):
            raise ValueError("query receipt must bind exact sandbox, family and parent")
        if item.query_receipt_hash in self.query_receipts:
            raise ValueError("query receipt already consumed")
        if slot["used"] >= slot["limit"]:
            raise ValueError("probe budget exhausted")
        slot["used"] += 1
        slot["receipts"].append(item.receipt_id)
        self.query_receipts[item.query_receipt_hash] = item.receipt_id
        self.actions.append({"kind": "probe", "trigger_key": trigger_key,
                             "interaction": item.model_dump(mode="json")})
        # UNKNOWN and excluded faults consume budget but do not generate Bayes labels.
        return item.evidence if item.feedback == "business" and item.evidence.guard_prediction is True else None

    def checkpoint(self):
        body = {"schema": "public-drift-checkpoint-v1", "policy": self.policy.model_dump(),
            "events": clone(self.events), "explorations": clone(self.explorations),
            "query_receipts": clone(self.query_receipts), "actions": clone(self.actions)}
        return {**body, "hash": fingerprint(body)}

    @classmethod
    def restore(cls, checkpoint):
        body = {key: value for key, value in checkpoint.items() if key != "hash"}
        if fingerprint(body) != checkpoint["hash"] or body["schema"] != "public-drift-checkpoint-v1":
            raise ValueError("trigger checkpoint integrity mismatch")
        result = cls(body["policy"])
        for action in body["actions"]:
            if action["kind"] == "observe" and set(action) == {"kind", "interaction"}:
                result.observe(action["interaction"])
            elif action["kind"] == "begin" and set(action) == {"kind", "trigger_key", "sandbox_id"}:
                result.begin_exploration(action["trigger_key"], sandbox_id=action["sandbox_id"])
            elif action["kind"] == "probe" and set(action) == {"kind", "trigger_key", "interaction"}:
                result.charge_probe(action["trigger_key"], action["interaction"])
            else:
                raise ValueError("unknown persisted trigger action")
        if result.checkpoint() != checkpoint:
            raise ValueError("trigger checkpoint decision/accounting replay mismatch")
        return result
