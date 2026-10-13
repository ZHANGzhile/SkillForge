"""Immutable governance sidecars; historical catalog/revision bytes stay valid.

Semantic identity here means exact canonical DSL equivalence under declared
input renaming, not a proof for reordered calls or arbitrary support domains.
"""
import json
from pathlib import Path

from ..evolution_common.artifacts import clone
from ..evolution_registry import immutable_json
from ..evolution_schemas import fingerprint
from ..schemas import SkillContract


def identities(contract, goal_hash=None):
    skill = SkillContract.model_validate(contract)
    aliases = {name: "i" + str(index) for index, name in enumerate(skill.inputs)}
    if len(aliases) != len(skill.inputs):
        raise ValueError("duplicate input name")
    def binding(value):
        if isinstance(value, str) and value.startswith("$input."):
            if value[7:] not in aliases:
                raise ValueError("undeclared input binding")
            return "$input." + aliases[value[7:]]
        if isinstance(value, dict): return {key: binding(item) for key, item in value.items()}
        if isinstance(value, list): return [binding(item) for item in value]
        return value
    def condition(value):
        return {key: value[key] for key in ("field", "op", "value")}
    program = []
    for node in skill.procedure:
        if node.kind == "call": program.append({"kind": "call", "tool": node.tool, "arguments": binding(node.arguments)})
        elif node.kind == "assert": program.append({"kind": "assert", "condition": condition(node.condition.model_dump()) if node.condition else None})
        else: program.append({"kind": "finish"})
    boundary = {key: sorted([condition(item.model_dump()) for item in getattr(skill, key)], key=fingerprint)
                for key in ("preconditions", "forbidden_conditions")}
    program_body = {"inputs": len(aliases), "family": skill.family, "procedure": program,
                    "postconditions": binding(skill.postconditions), "policy_version": skill.policy_version}
    boundary_hash = fingerprint(boundary)
    program_hash = fingerprint(program_body)
    # This deliberately coarse read/effect signature only flags candidates
    # for controlled comparison. It never authorizes merging or publication.
    calls = [item for item in program if item["kind"] == "call"]
    effects = {"calls": sorted({fingerprint(item) for item in calls}),
               "assertions": [item for item in program if item["kind"] == "assert"],
               "postconditions": program_body["postconditions"], "family": skill.family,
               "policy_version": skill.policy_version, "inputs": len(aliases)}
    return {"program_fingerprint": program_hash, "boundary_fingerprint": boundary_hash,
            "semantic_fingerprint": fingerprint({"program": program_hash, "boundary": boundary_hash, "goal": goal_hash}),
            "effect_signature": fingerprint(effects),
            "scope": "exact canonical DSL under positional input renaming; coarse effects are potential duplicates only"}


def deduplicate(contract, goal_hash, entries):
    target = identities(contract, goal_hash)
    exact, potential = [], []
    for entry in entries:
        other_goal = entry.get("goal_hash", entry.get("support_domain", {}).get("goal_hash"))
        other = identities(entry["contract"], other_goal)
        ref = {"skill_id": entry["skill_id"], "revision": entry["revision"]}
        if target["semantic_fingerprint"] == other["semantic_fingerprint"]:
            exact.append(ref)
        elif target["effect_signature"] == other["effect_signature"]:
            potential.append(ref)
    order = lambda rows: sorted(rows, key=lambda item: (item["skill_id"], item["revision"]))
    return {"status": "EXACT_DUPLICATE" if exact else "POTENTIAL_DUPLICATE" if potential else "NOVEL",
            "exact": order(exact), "potential": order(potential), **target}


def governed_revision(entry, *, goal_hash, revision_kind="program_revision", parent=None, lane="program"):
    body = {key: value for key, value in entry.items() if key != "revision"}
    if fingerprint(body) != entry["revision"]:
        raise ValueError("catalog revision integrity mismatch")
    if entry["dependencies"]:
        raise ValueError("dependency governance requires a declared composition protocol")
    if entry.get("support_domain", {}).get("goal_hash") != goal_hash:
        raise ValueError("governance goal must match declared catalog support domain")
    if revision_kind not in {"metadata_revision", "program_revision", "boundary_revision"} or lane not in {"program", "boundary"}:
        raise ValueError("unknown revision kind or lane")
    current = identities(entry["contract"], goal_hash)
    if parent:
        if parent["contract"]["status"] in {"REJECTED", "DEPRECATED", "NEEDS_REFINEMENT"}:
            raise ValueError("rejected or inactive revision cannot be a parent")
        if fingerprint({key: value for key, value in parent.items() if key != "revision"}) != parent["revision"]:
            raise ValueError("parent revision integrity mismatch")
        previous_goal = parent.get("support_domain", {}).get("goal_hash")
        previous = identities(parent["contract"], previous_goal)
        if (entry["skill_id"] != parent["skill_id"] or entry["parent_revision"] != parent["revision"] or
                entry["contract"]["version"] != parent["contract"]["version"] + 1):
            raise ValueError("exact parent and incremented same-Skill version required")
        if entry["contract"]["policy_version"] != parent["contract"]["policy_version"] or goal_hash != previous_goal:
            raise ValueError("policy or goal change requires a separate protocol")
        program_changed = current["program_fingerprint"] != previous["program_fingerprint"]
        boundary_changed = current["boundary_fingerprint"] != previous["boundary_fingerprint"]
        if revision_kind == "metadata_revision" and (program_changed or boundary_changed):
            raise ValueError("metadata revision cannot change executable behavior")
        if revision_kind == "program_revision" and (not program_changed or boundary_changed):
            raise ValueError("program revision must change program and preserve boundary")
        if revision_kind == "boundary_revision" and (program_changed or not boundary_changed or lane != "boundary"):
            raise ValueError("boundary revision requires boundary lane and unchanged program")
    elif revision_kind != "program_revision" or entry["parent_revision"] is not None:
        raise ValueError("initial program revision must have no parent")
    if lane == "program" and revision_kind == "boundary_revision":
        raise ValueError("stage one cannot change boundaries")
    sidecar = {"schema": "skill-governance-revision-v1", "catalog_revision": entry["revision"],
               "skill_id": entry["skill_id"], "revision_kind": revision_kind, "lane": lane,
               "goal_hash": goal_hash, "parent_revision": parent["revision"] if parent else None,
               "parent_eligible_for_formal_lineage": parent is None or parent["contract"]["status"] == "VERIFIED",
               "supersedes": parent["revision"] if parent else None, "dependencies": entry["dependencies"], **current}
    return {**sidecar, "hash": fingerprint(sidecar)}


class RevisionMemory:
    """Private optimizer attempts, learn/dev only, at most two per parent.

    Single controller; immutable numbered files reject concurrent replacement.
    Formal admission evidence belongs elsewhere and cannot be fed back here.
    """
    def __init__(self, root, ledger):
        self.root, self.ledger = Path(root), ledger
        self.entries = []
        for path in sorted(self.root.glob("*.json")):
            entry = json.loads(path.read_text(encoding="utf-8"))
            body = {key: value for key, value in entry.items() if key != "hash"}
            if (fingerprint(body) != entry["hash"] or body["sequence"] != len(self.entries) or
                    body["previous_hash"] != (self.entries[-1]["hash"] if self.entries else None)):
                raise ValueError("RevisionMemory integrity/lineage mismatch")
            self._check_attempt(body["attempt"])
            self.entries.append(entry)

    def _check_attempt(self, attempt):
        required = {"candidate_revision", "parent_revision", "trigger_gap", "changed_nodes", "support_domain",
                    "pairs", "accepted_in_dev", "reason", "evidence_hashes"}
        if set(attempt) != required or not attempt["parent_revision"] or not attempt["candidate_revision"]:
            raise ValueError("complete scoped revision attempt required")
        if type(attempt["accepted_in_dev"]) is not bool or not attempt["reason"] or not attempt["evidence_hashes"]:
            raise ValueError("explicit outcome/reason/evidence required")
        if sum(item["attempt"]["parent_revision"] == attempt["parent_revision"] for item in self.entries) >= 2:
            raise ValueError("two-attempt revision budget exhausted")
        if any(item["attempt"]["candidate_revision"] == attempt["candidate_revision"] for item in self.entries):
            raise ValueError("candidate attempt already recorded")
        if not attempt["pairs"]:
            raise ValueError("learn/dev evidence required")
        for pair in attempt["pairs"]:
            if (set(pair) != {"source_group", "task_id", "split", "outcome"} or pair["split"] not in {"train", "dev"} or
                    pair["outcome"] not in {"win", "loss", "tie"}):
                raise ValueError("RevisionMemory accepts learn/dev feedback only")
            for key in (pair["source_group"], pair["task_id"]):
                if self.ledger.owners.get(key) != pair["split"]:
                    raise ValueError("feedback source not owned by declared learn/dev split")

    def append(self, **attempt):
        self._check_attempt(attempt)
        body = {"schema": "skill-revision-memory-v1", "sequence": len(self.entries),
                "previous_hash": self.entries[-1]["hash"] if self.entries else None, "attempt": clone(attempt)}
        entry = {**body, "hash": fingerprint(body)}
        immutable_json(self.root / (str(body["sequence"]).zfill(6) + ".json"), entry)
        self.entries.append(entry)
        return entry


class Lifecycle:
    """Append-only disposition; no implicit Agent admission or service activation."""
    ALLOWED = {"DISCOVERED": {"CANDIDATE", "REJECTED", "INCONCLUSIVE"},
               "CANDIDATE": {"VERIFIED", "REJECTED", "INCONCLUSIVE"},
               "VERIFIED": {"DEPRECATED"}, "REJECTED": set(), "INCONCLUSIVE": set(), "DEPRECATED": set()}

    def __init__(self, root, revision):
        self.root, self.revision = Path(root), revision
        if fingerprint({key: value for key, value in revision.items() if key != "hash"}) != revision["hash"]:
            raise ValueError("governance revision tampered")
        self.events = []
        for path in sorted(self.root.glob("*.json")):
            event = json.loads(path.read_text(encoding="utf-8"))
            body = {key: value for key, value in event.items() if key != "hash"}
            if (fingerprint(body) != event["hash"] or body["revision_hash"] != revision["hash"] or
                    body["sequence"] != len(self.events) or
                    body["previous_hash"] != (self.events[-1]["hash"] if self.events else None)):
                raise ValueError("lifecycle integrity mismatch")
            self._check(body["status"], body["reason"], body["evidence"])
            self.events.append(event)

    @property
    def status(self): return self.events[-1]["status"] if self.events else None

    def _check(self, status, reason, evidence):
        if not reason or (self.status is None and status != "DISCOVERED") or (
                self.status is not None and status not in self.ALLOWED[self.status]):
            raise ValueError("invalid lifecycle transition or missing reason")
        if status == "VERIFIED":
            from .validation import audit_program_admission
            audit_program_admission(evidence)
            if not self.revision["parent_eligible_for_formal_lineage"]:
                raise ValueError("unverified draft cannot enter formal parent lineage")
            if evidence["decision"] != "ADMITTED" or evidence["catalog_revision"] != self.revision["catalog_revision"]:
                raise ValueError("formal program admission bound to exact revision required")

    def transition(self, status, *, reason, evidence=None):
        evidence = clone(evidence or {})
        self._check(status, reason, evidence)
        body = {"schema": "skill-lifecycle-event-v1", "sequence": len(self.events), "revision_hash": self.revision["hash"],
                "previous_hash": self.events[-1]["hash"] if self.events else None,
                "status": status, "reason": reason, "evidence": evidence}
        entry = {**body, "hash": fingerprint(body)}
        immutable_json(self.root / (str(body["sequence"]).zfill(6) + ".json"), entry)
        self.events.append(entry)
        return entry
