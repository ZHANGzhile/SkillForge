"""Immutable catalog snapshots and public, deterministic lexical search/load."""
import json
import re
import time
from pathlib import Path

from ..evolution_schemas import fingerprint
from ..schemas import SkillContract
from ..environment import ToolError
from ..evolution_registry import immutable_json
from ..evolution_common.artifacts import clone


def terms(text):
    return re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", text.lower().replace("_", " "))


def public_condition(condition):
    return {k: clone(condition[k]) for k in ("field", "op", "value")}


def revision(skill, *, name, description, support_domain, parent_revision=None, dependencies=()):
    skill = SkillContract.model_validate(skill).model_dump()
    body = {"schema": "skill-revision-v1", "skill_id": skill["skill_id"], "contract": skill,
            "name": name, "description": description, "support_domain": clone(support_domain),
            "parent_revision": parent_revision, "dependencies": clone(list(dependencies)),
            "boundary_revision": fingerprint({"preconditions": skill["preconditions"],
                                               "forbidden_conditions": skill["forbidden_conditions"]})}
    return {**body, "revision": fingerprint(body)}


class Catalog:
    def __init__(self, entries):
        by_ref = {}
        for entry in clone(entries):
            body = {k: v for k, v in entry.items() if k != "revision"}
            if entry["revision"] != fingerprint(body) or entry["schema"] != "skill-revision-v1":
                raise ValueError("catalog content tampered")
            skill = SkillContract.model_validate(entry["contract"])
            if skill.skill_id != entry["skill_id"]:
                raise ValueError("catalog skill identity mismatch")
            key = (entry["skill_id"], entry["revision"])
            if key in by_ref:
                raise ValueError("duplicate catalog revision")
            by_ref[key] = entry
        for entry in by_ref.values():
            for dep in entry["dependencies"]:
                if (dep["skill_id"], dep["revision"]) not in by_ref:
                    raise ValueError("missing catalog dependency")
        def visit(key, active):
            if key in active:
                raise ValueError("cyclic catalog dependency")
            for dep in by_ref[key]["dependencies"]:
                visit((dep["skill_id"], dep["revision"]), active | {key})
        for key in by_ref:
            visit(key, set())
        self._encoded = json.dumps(sorted(by_ref.values(), key=lambda x: (x["skill_id"], x["revision"])),
                                   sort_keys=True, ensure_ascii=False)
        self.hash = fingerprint(json.loads(self._encoded))

    def entries(self):
        return json.loads(self._encoded)

    def save(self, path):
        immutable_json(path, {"schema": "skill-catalog-v1", "hash": self.hash, "entries": self.entries()})

    @classmethod
    def load(cls, path):
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        obj = cls(value["entries"])
        if value["schema"] != "skill-catalog-v1" or obj.hash != value["hash"]:
            raise ValueError("catalog snapshot identity mismatch")
        return obj

    def get(self, skill_id, rev):
        entry = next((e for e in self.entries() if (e["skill_id"], e["revision"]) == (skill_id, rev)), None)
        if entry is None:
            raise ToolError("unknown_skill_revision")
        if entry["contract"]["status"] != "VERIFIED":
            raise ToolError("skill_not_verified")
        return entry

    @staticmethod
    def summary(entry, *, enrich=False):
        skill = entry["contract"]
        result = {"skill_id": entry["skill_id"], "revision": entry["revision"], "content_hash": entry["revision"],
                "name": entry["name"], "description": entry["description"], "inputs": skill["inputs"],
                "applicable_when": [public_condition(c) for c in skill["preconditions"]],
                "forbidden_when": [public_condition(c) for c in skill["forbidden_conditions"]],
                "dependencies": entry["dependencies"], "status": skill["status"]}
        if enrich:
            result.update(required_observations=sorted({c["field"] for c in
                          skill["preconditions"] + skill["forbidden_conditions"]}),
                          required_tools=sorted({n["tool"] for n in skill["procedure"] if n["kind"] == "call"}),
                          kind="executable_skill")
        return result

    def search(self, query, top_k=5):
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 1000 or type(top_k) is not int or not 1 <= top_k <= 5:
            raise ToolError("invalid_search_arguments")
        q = set(terms(query))
        scored = []
        for entry in self.entries():
            if entry["contract"]["status"] != "VERIFIED":
                continue
            # No task.family, fixture, label or hidden router enters this index.
            summary = self.summary(entry)
            text = " ".join([entry["skill_id"], entry["name"], entry["description"], *entry["contract"]["inputs"]])
            overlap = len(q & set(terms(text)))
            if overlap:
                scored.append((overlap, entry["skill_id"], entry["revision"], summary))
        return [row[3] for row in sorted(scored, key=lambda x: (-x[0], x[1], x[2]))[:top_k]]

    def search_audited(self, query, top_k=5):
        """Versioned full-library ranking; diagnostics stay outside model results.

        Keep search() byte-compatible with historical lexical-v1 evidence.
        No observation values, Gate results, task family or private labels rank entries.
        """
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 1000 or type(top_k) is not int or not 1 <= top_k <= 5:
            raise ToolError("invalid_search_arguments")
        started = time.perf_counter()
        q, rows = set(terms(query)), []
        for entry in self.entries():
            if entry["contract"]["status"] != "VERIFIED":
                continue
            public = self.summary(entry, enrich=True)
            fields = {"text": " ".join([entry["skill_id"], entry["name"], entry["description"]]),
                      "inputs": " ".join(public["inputs"]),
                      "observations": " ".join(public["required_observations"]),
                      "tools": " ".join(public["required_tools"])}
            components = {name: len(q & set(terms(value))) for name, value in fields.items()}
            score = 3 * components["text"] + 2 * components["inputs"] + components["observations"] + components["tools"]
            rows.append({"skill_id": entry["skill_id"], "revision": entry["revision"],
                         "score": score, "components": components})
        rows.sort(key=lambda r: (-r["score"], r["skill_id"], r["revision"]))
        matched = [r for r in rows if r["score"] > 0]
        results = [self.summary(self.get(r["skill_id"], r["revision"]), enrich=True) for r in matched[:top_k]]
        audit = {"schema": "catalog-search-audit-v2", "backend": "lexical-metadata-v2",
                 "catalog_hash": self.hash, "query": query, "top_k": top_k,
                 "ranking": rows, "truncated_candidates": matched[top_k:],
                 "returned_refs": [{"skill_id": r["skill_id"], "revision": r["revision"]} for r in results],
                 "latency_ms": (time.perf_counter() - started) * 1000}
        return results, audit

    def public_load(self, skill_id, rev, *, enrich=False):
        entry = self.get(skill_id, rev)
        skill = entry["contract"]
        procedure = clone(skill["procedure"])
        for node in procedure:
            if node.get("condition"):
                node["condition"] = public_condition(node["condition"])
        return {**self.summary(entry, enrich=enrich), "program": procedure, "postconditions": clone(skill["postconditions"]),
                "support_domain": entry["support_domain"], "boundary_revision": entry["boundary_revision"]}


class LoadedSkills:
    def __init__(self, catalog, refs=None):
        self.catalog, self.refs = catalog, {}
        for sid, ref in (refs or {}).items():
            self.load(sid, ref["revision"])
            if self.refs[sid] != ref:
                raise ValueError("loaded reference identity mismatch")

    def load(self, skill_id, rev):
        entry = self.catalog.get(skill_id, rev)
        if skill_id in self.refs and self.refs[skill_id]["revision"] != rev:
            raise ToolError("skill_revision_conflict")
        self.refs[skill_id] = {"revision": rev, "content_hash": entry["revision"]}
        return self.catalog.public_load(skill_id, rev)

    def contract(self, skill_id):
        if skill_id not in self.refs:
            raise ToolError("skill_not_loaded")
        entry = self.catalog.get(skill_id, self.refs[skill_id]["revision"])
        return SkillContract.model_validate(entry["contract"])


VIRTUAL_TOOLS = [
    {"name": "search_skills", "description": "Find verified reusable procedures; loading is required before use.",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}, "top_k": {"type": "integer", "default": 5}}, "required": ["query"], "additionalProperties": False}, "side_effect": False},
    {"name": "load_skill", "description": "Load an exact skill_id and revision returned by search; this does not establish applicability.",
     "input_schema": {"type": "object", "properties": {"skill_id": {"type": "string"}, "revision": {"type": "string"}}, "required": ["skill_id", "revision"], "additionalProperties": False}, "side_effect": False},
]
