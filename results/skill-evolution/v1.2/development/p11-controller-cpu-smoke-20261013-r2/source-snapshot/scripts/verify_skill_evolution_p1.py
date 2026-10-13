"""P1 CPU capacity and PrimitiveOnly contract checks. No model evidence."""
import argparse
import copy
import json
from pathlib import Path
import time

from scripts.run_skill_evolution import digest_file, static_catalog
from skillforge.environment import Environment
from skillforge.evolution_registry import immutable_json
from skillforge.evolution_schemas import fingerprint
from skillforge.schemas import Action
from skillforge.skill_evolution.catalog import Catalog, revision
from skillforge.skill_evolution.runtime import run_agent, PROTOCOL, SYSTEM_PROMPT


class EngineeringModel:
    settings = {"model": "scripted-engineering-only", "engineering_only": True}
    tokens = 0
    def __init__(self, actions):
        self.actions = iter(actions)
        self.contexts = []
    def decide(self, context):
        self.contexts.append(copy.deepcopy(context))
        return next(self.actions)


def capacity(catalog, size):
    """Synthetic near-neighbors are index fixtures, never real new capabilities."""
    started = time.perf_counter()
    entries = catalog.entries()
    base = entries[0]["contract"]
    for index in range(size):
        contract = copy.deepcopy(base)
        contract["skill_id"] = f"synthetic_capacity_{index:04d}"
        contract["preconditions"].append({"field": "order.status", "op": "eq", "value": "SYNTHETIC_ONLY",
                                          "evidence": ["scripted:capacity-not-business-capability"]})
        entries.append(revision(contract, name=f"synthetic neighbor {index}",
                                description="order cancellation payment refund shipment address capacity fixture",
                                support_domain={"synthetic_capacity_only": True}))
    large = Catalog(entries)
    query = "order cancellation payment refund shipment address"
    results, audit = large.search_audited(query, top_k=5)
    repeated, replay = large.search_audited(query, top_k=5)
    assert results == repeated and audit["ranking"] == replay["ranking"]
    assert len(audit["ranking"]) == len(entries)
    # All verified index fixtures are ranked: no family prefilter or private
    # applicability signal. Near-neighbor crowding is allowed and reported.
    selected = {(r["skill_id"], r["revision"]) for r in audit["returned_refs"]}
    truncated = {(r["skill_id"], r["revision"]) for r in audit["truncated_candidates"]}
    assert selected.isdisjoint(truncated) and len(selected) == 5
    return {"synthetic_entries": size, "business_skills": len(catalog.entries()), "total_indexed": len(entries),
            "catalog_hash": large.hash, "query": query, "retrieval_audit": audit,
            "deterministic_replay": True, "wall_seconds": time.perf_counter() - started,
            "scope": "synthetic index capacity/determinism; not new verified business capabilities or Recall efficacy"}


def primitive_contract(catalog, *, malformed=False):
    task = {"task_id": "primitive-contract-engineering", "family": "cancel_order",
            "request": "Cancel order ENGINEERING-P1 if permitted.", "parameters": {"order_id": "ENGINEERING-P1"}}
    limits = {"max_steps": 8, "max_search": 3, "max_load": 3, "max_tokens": 45056}
    values = []
    for library in (Catalog([]), catalog):
        env = Environment(fixture={"order_id": task["parameters"]["order_id"]})
        try:
            observed = {}
            for name in ("get_order", "get_customer", "get_shipment"):
                observed.update(env.call(name, task["parameters"]))
            actions = ([Action(type="skill", name="cancel_order", arguments=task["parameters"]), Action(type="refuse")]
                       if malformed else [Action(type="tool", name="cancel_order", arguments=task["parameters"])])
            model = EngineeringModel(actions)
            def tool(name, args, key, source):
                result = env.call(name, args, request_id=key)
                env.audit[-1]["decision_origin"] = source
                return result
            agent = run_agent(model, task, library, tool, public_start={"observations": observed, "loaded_refs": {}}, **limits)
            values.append({"catalog_hash": library.hash, "first_context": model.contexts[0], "agent": agent,
                           "final_order_status": env.snapshot()["order.status"], "tool_audit": env.audit})
        finally:
            env.close()
    left, right = [copy.deepcopy(v["first_context"]) for v in values]
    left["catalog"].pop("snapshot"); right["catalog"].pop("snapshot")
    assert left == right
    assert all(v["agent"]["metrics"]["llm_calls"] == 0 for v in values)
    if malformed:
        assert all(v["final_order_status"] == "CONFIRMED" and v["agent"]["steps"][0]["error"] == "skill_not_loaded" for v in values)
    else:
        assert all(v["agent"]["outcome"] == "completed" and v["final_order_status"] == "CANCELLED" for v in values)
    return {"limits": limits, "protocol": PROTOCOL, "system_prompt_hash": fingerprint(SYSTEM_PROMPT),
            "equal_context_except_catalog_identity": True, "primitive_only_catalog_empty": True,
            "malformed_skill_actions_preserved": malformed, "arms": values,
            "scope": "scripted action dispatch/fairness engineering only; not real-model PrimitiveOnly performance"}


def run(config, output):
    started = time.perf_counter()
    catalog = static_catalog(config)
    report = {"schema": "p1-cpu-contract-capacity-v1", "model": "scripted-engineering-only", "llm_calls": 0,
              "capacity": [capacity(catalog, n) for n in (300, 1000)],
              "primitive_contract": primitive_contract(catalog), "malformed_action_control": primitive_contract(catalog, malformed=True),
              "engineering_passed": True, "real_agent_baseline_evaluated": False,
              "research_claim_passed": None, "isolated_activated": False, "deployed": False,
              "generator_sha256": digest_file(__file__), "wall_seconds": time.perf_counter() - started}
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    immutable_json(output / "report.json", report)
    return {k: report[k] for k in ("engineering_passed", "real_agent_baseline_evaluated", "wall_seconds", "llm_calls")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/skill-evolution-v1.2.fork-recovery-dev.json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(run(json.loads(Path(args.config).read_text(encoding="utf-8")), args.output)), flush=True)
