"""Content identities, immutable records, split ownership and explicit budgets."""
import json
import math
from pathlib import Path

from ..evolution_registry import immutable_json
from ..evolution_schemas import fingerprint


def clone(value):
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def record(root, kind, body):
    body = clone(body)
    identity = fingerprint({"kind": kind, "body": body})
    immutable_json(Path(root) / kind / (identity + ".json"),
                   {"schema": "two-phase-record-v1", "kind": kind, "hash": identity, "body": body})
    return identity


def load_record(root, kind, identity):
    if len(identity) != 64 or any(c not in "0123456789abcdef" for c in identity):
        raise ValueError("invalid record identity")
    entry = json.loads((Path(root) / kind / (identity + ".json")).read_text(encoding="utf-8"))
    if entry["kind"] != kind or entry["hash"] != identity or fingerprint({"kind": kind, "body": entry["body"]}) != identity:
        raise ValueError("record integrity mismatch")
    return entry["body"]


def system_manifest(**fields):
    required = {"parent_system_id", "execution_model", "proposal_model", "tokenizer", "prompt",
                "action_protocol", "sources", "catalog_hash", "skill_revisions", "boundary_revisions",
                "retrieval", "decoding", "data_identity", "protocol_identity"}
    if set(fields) != required:
        raise ValueError("complete explicit system identity required")
    body = clone(fields)
    return {"schema": "evolution-system-v1", "system_id": fingerprint(body), **body}


class SplitLedger:
    """Append-only single-controller source ownership. Forks inherit their source."""
    def __init__(self, root):
        self.root = Path(root)
        self.owners = {}
        for path in sorted(self.root.glob("*.json")):
            item = json.loads(path.read_text(encoding="utf-8"))
            body = item["body"]
            if fingerprint(body) != item["hash"]:
                raise ValueError("split ledger tampered")
            for key in body["keys"]:
                if key in self.owners and self.owners[key] != body["split"]:
                    raise ValueError("cross-split provenance")
                self.owners[key] = body["split"]

    def claim(self, source_group, split, *, related_groups=()):
        if split not in {"train", "dev", "validation", "test", "stable_validation", "stable_test"}:
            raise ValueError("unknown split")
        keys = sorted(set([source_group, *related_groups]))
        if not source_group or any(not isinstance(k, str) or not k for k in keys):
            raise ValueError("nonempty source keys required")
        if any(k in self.owners and self.owners[k] != split for k in keys):
            raise ValueError("source or fork cannot cross splits")
        body = {"keys": keys, "split": split}
        immutable_json(self.root / (fingerprint(body) + ".json"), {"hash": fingerprint(body), "body": body})
        self.owners.update({k: split for k in keys})


class Budget:
    """Charge attempted work, including rejected requests; never silently refill."""
    def __init__(self, limits, used=None):
        self.limits, self.used = dict(limits), dict(used or {})
        if any(type(v) not in {int, float} or not math.isfinite(v) or v < 0 for v in [*self.limits.values(), *self.used.values()]):
            raise ValueError("finite nonnegative budgets required")
        if set(self.used) - set(self.limits):
            raise ValueError("unregistered budget counter")
        if any(v > self.limits[k] for k, v in self.used.items()):
            raise ValueError("restored budget exceeds limit")

    def charge(self, name, amount=1):
        if name not in self.limits or type(amount) not in {int, float} or not math.isfinite(amount) or amount < 0:
            raise ValueError("invalid budget charge")
        if self.used.get(name, 0) + amount > self.limits[name]:
            raise ValueError("budget_exhausted:" + name)
        self.used[name] = self.used.get(name, 0) + amount

    def checkpoint(self):
        return clone({"limits": self.limits, "used": self.used})
