"""Trusted public receipt binding for the *current* program/Boundary parent."""
from ..boundary_evolution.evidence import PublicReceiptAdapter
from ..boundary_evolution.trigger import Interaction
from ..evolution_schemas import EvidenceView, fingerprint
from .proposal import parent_key, hashed


class VersionedReceiptAdapter:
    def __init__(self, members, catalog):
        self.catalog, self.members = catalog, members
        self.base = PublicReceiptAdapter(members, catalog)

    def export(self, raw, task):
        member = self.members.get(task["task_id"], {})
        skill_id = member.get("skill_id")
        if (member.get("boundary_bundle_hash") != self.catalog.bundle_hash or
                member.get("boundary_revision") != self.catalog.public_boundary(skill_id)["revision"]):
            raise ValueError("receipt not pinned to the current Boundary parent")
        original = self.base.export(raw, task)
        entry = self.catalog.get(skill_id, member["parent_revision"])
        gate = self.catalog.effective_gate(entry["contract"], original.evidence.observations, task["parameters"])
        baseline = True if gate.status == "APPLICABLE" else False if gate.status == "INAPPLICABLE" else None
        view = original.evidence.model_dump(mode="json")
        view.update(baseline_prediction=baseline, policy_epoch="public-stream")
        view["evidence_id"] = fingerprint({k: v for k, v in view.items() if k != "evidence_id"})
        body = original.model_dump(mode="json")
        body.update(parent_revision=parent_key(self.catalog, skill_id), evidence=view)
        body["receipt_id"] = fingerprint({k: v for k, v in body.items() if k != "receipt_id"})
        interaction = Interaction.model_validate(body)
        # Learning remains absolute relative to the frozen original rule. Only
        # drift detection uses today's effective parent as its baseline.
        return hashed({"schema": "versioned-public-business-receipt-v1", "program_revision": entry["revision"],
            "boundary_revision": member["boundary_revision"], "bundle_hash": self.catalog.bundle_hash,
            "drift_interaction": interaction.model_dump(mode="json"),
            "absolute_learning_evidence": original.evidence.model_dump(mode="json"),
            "scope": "public-only projection; trusted controller owns task/raw membership"})
