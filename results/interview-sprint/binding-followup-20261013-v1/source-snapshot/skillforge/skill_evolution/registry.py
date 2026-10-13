"""Immutable catalog selection snapshots, separate from service activation.

Legacy imports retain their original bytes and historical admission scope.
New program publication requires real learn provenance and formal validation.
Every operation creates a new snapshot; no mutable latest pointer is written.
"""
from pathlib import Path

from ..evolution_common.artifacts import clone, record, load_record
from ..evolution_schemas import fingerprint
from .catalog import Catalog, revision
from .governance import governed_revision, deduplicate
from .validation import audit_program_admission, checked_hash


def verified_publication(entry):
    """A new hash for VERIFIED; never relabel the original CANDIDATE bytes."""
    Catalog([entry])
    if entry["contract"]["status"] != "CANDIDATE":
        raise ValueError("publication requires an exact candidate revision")
    contract = clone(entry["contract"])
    contract["status"] = "VERIFIED"
    return revision(contract, name=entry["name"], description=entry["description"], support_domain=entry["support_domain"],
                    parent_revision=entry["parent_revision"], dependencies=entry["dependencies"])


class VersionedRegistry:
    def __init__(self, root):
        self.root = Path(root)

    @staticmethod
    def _catalog(entries):
        catalog = Catalog(entries)
        if (len({entry["skill_id"] for entry in entries}) != len(entries) or
                any(entry["contract"]["status"] != "VERIFIED" for entry in entries)):
            raise ValueError("selected catalog requires one VERIFIED version per Skill")
        return catalog

    def _snapshot(self, entries, *, parent, operation, reason, evidence, registrations, target=None):
        if not reason: raise ValueError("snapshot reason required")
        catalog = self._catalog(entries)
        body = {"schema": "versioned-skill-catalog-v1", "parent_snapshot": parent, "operation": operation,
                "reason": reason, "evidence": clone(evidence), "rollback_target": target,
                "catalog_hash": catalog.hash, "entries": catalog.entries(), "registrations": clone(registrations),
                "isolated_activated": False, "deployed": False,
                "scope": "immutable catalog selection; service activation requires a separate audited controller"}
        return record(self.root, "snapshots", body)

    def load(self, identity):
        body = load_record(self.root, "snapshots", identity)
        catalog = self._catalog(body["entries"])
        if catalog.hash != body["catalog_hash"] or body["isolated_activated"] or body["deployed"]:
            raise ValueError("catalog snapshot content/disposition mismatch")
        if any(entry["revision"] not in body["registrations"] for entry in catalog.entries()):
            raise ValueError("selected revision lacks registration provenance")
        for entry in catalog.entries():
            registration = load_record(self.root, "registrations", body["registrations"][entry["revision"]])
            if registration["published_entry"] != entry:
                raise ValueError("snapshot registration/selected revision mismatch")
            if registration["kind"] == "formal_program":
                self._audit_registration(registration)
            elif registration["kind"] != "legacy_import":
                raise ValueError("unknown registration scope")
        return body, catalog

    def bootstrap(self, catalog, *, reason, evidence):
        """Import an explicitly identified legacy baseline, no new admission."""
        checked_hash(evidence)
        if evidence.get("catalog_hash") != catalog.hash:
            raise ValueError("legacy evidence must bind exact catalog")
        self._catalog(catalog.entries())
        registrations = {}
        for entry in catalog.entries():
            registrations[entry["revision"]] = record(self.root, "registrations", {
                "kind": "legacy_import", "published_entry": entry, "evidence": clone(evidence),
                "program_admitted_by_this_run": False, "agent_admitted_by_this_run": False})
        return self._snapshot(catalog.entries(), parent=None, operation="LEGACY_IMPORT", reason=reason,
                              evidence=evidence, registrations=registrations)

    @staticmethod
    def _audit_registration(value):
        from .provenance import ROOT, audit_compiler_run
        receipt = value["program_admission"]
        audit_program_admission(receipt)
        proposal = value["proposal_entry"]
        if (receipt["decision"] != "ADMITTED" or receipt["catalog_revision"] != proposal["revision"] or
                receipt["report"]["entry"] != proposal or verified_publication(proposal) != value["published_entry"]):
            raise ValueError("formal program admission/publication mismatch")
        provenance = audit_compiler_run(ROOT / value["compiler_run"])
        if provenance["hash"] != value["provenance_hash"]:
            raise ValueError("registered learn provenance changed")
        candidates = [item["candidate"] for item in provenance["proposal"]["results"] if item["candidate"] is not None]
        candidate = receipt["report"]["protocol"]["learn_candidate"]
        if candidate not in candidates or candidate["skill"] != proposal["contract"]:
            raise ValueError("candidate was not compiled from audited real learn traces")
        if value["governance"] != governed_revision(proposal, goal_hash=candidate["goal_hash"],
                parent=value["parent_entry"], revision_kind="program_revision"):
            raise ValueError("formal governance/parent identity mismatch")
        if not value["governance"]["parent_eligible_for_formal_lineage"]:
            raise ValueError("unverified parent cannot publish")
        return provenance

    def register_program(self, parent_snapshot, entry, *, program_admission, compiler_run, reason):
        """Store a validated program, without Agent admission or activation."""
        from .provenance import ROOT, audit_compiler_run
        checked_hash(program_admission)
        if program_admission.get("decision") != "ADMITTED" or program_admission.get("catalog_revision") != entry["revision"]:
            raise ValueError("exact formal program admission required before registration")
        previous, catalog = self.load(parent_snapshot)
        parent = next((item for item in catalog.entries() if item["skill_id"] == entry["skill_id"]), None)
        provenance = audit_compiler_run(compiler_run)
        goal = entry["support_domain"].get("goal_hash")
        governance = governed_revision(entry, goal_hash=goal, parent=parent)
        duplicate = deduplicate(entry["contract"], goal, [item for item in catalog.entries() if item != parent])
        if duplicate["status"] != "NOVEL":
            raise ValueError("duplicate or potential duplicate requires controlled comparison before registration")
        registration = {"kind": "formal_program", "proposal_entry": clone(entry), "published_entry": verified_publication(entry),
                        "parent_entry": parent, "program_admission": clone(program_admission), "governance": governance,
                        "compiler_run": Path(compiler_run).resolve().relative_to(ROOT).as_posix(),
                        "provenance_hash": provenance["hash"], "deduplication": duplicate,
                        "agent_admitted_by_this_run": False}
        self._audit_registration(registration)
        registration_id = record(self.root, "registrations", registration)
        published = registration["published_entry"]
        entries = [item for item in catalog.entries() if item != parent] + [published]
        registrations = {**previous["registrations"], published["revision"]: registration_id}
        return self._snapshot(entries, parent=parent_snapshot, operation="PROGRAM_REGISTERED", reason=reason,
                              evidence={"registration_id": registration_id}, registrations=registrations)

    def retain(self, parent_snapshot, *, reason, evidence):
        checked_hash(evidence)
        previous, catalog = self.load(parent_snapshot)
        return self._snapshot(catalog.entries(), parent=parent_snapshot, operation="RETAIN_PARENT", reason=reason,
                              evidence=evidence, registrations=previous["registrations"])

    def deprecate(self, parent_snapshot, revision_hash, *, reason, evidence):
        checked_hash(evidence)
        previous, catalog = self.load(parent_snapshot)
        entries = [entry for entry in catalog.entries() if entry["revision"] != revision_hash]
        if len(entries) == len(catalog.entries()): raise ValueError("deprecation requires an active exact revision")
        # Dependency closure is rechecked by Catalog before any snapshot writes.
        return self._snapshot(entries, parent=parent_snapshot, operation="DEPRECATED", reason=reason,
                              evidence={"revision": revision_hash, "receipt": evidence}, registrations=previous["registrations"])

    def rollback(self, parent_snapshot, target_snapshot, *, reason, evidence):
        checked_hash(evidence)
        cursor, ancestors = parent_snapshot, set()
        while cursor is not None:
            if cursor in ancestors: raise ValueError("cyclic snapshot lineage")
            ancestors.add(cursor)
            node, _ = self.load(cursor)
            cursor = node["parent_snapshot"]
        if target_snapshot == parent_snapshot or target_snapshot not in ancestors:
            raise ValueError("rollback requires a prior admitted/imported ancestor snapshot")
        target, catalog = self.load(target_snapshot)
        return self._snapshot(catalog.entries(), parent=parent_snapshot, operation="ROLLBACK", reason=reason,
                              evidence=evidence, registrations=target["registrations"], target=target_snapshot)
