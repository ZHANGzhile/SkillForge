"""Read-only P1 smoke audit. Private labels are used only for evaluation."""
import argparse
import json
from pathlib import Path

from skillforge.evolution_registry import immutable_json
from skillforge.evolution_common.artifacts import system_manifest
from skillforge.evolution_schemas import fingerprint
from skillforge.skill_evolution.catalog import Catalog


def summarize(root):
    root = Path(root)
    report = json.loads((root / "report.json").read_text(encoding="utf-8"))
    tasks = {t["task_id"]: t for t in json.loads((root / "private-dev-tasks.json").read_text(encoding="utf-8"))}
    catalog = Catalog.load(root / "catalog.json")
    registration = json.loads((root / "registration.json").read_text(encoding="utf-8"))
    if (root / "model-identity.json").exists():
        model = json.loads((root / "model-identity.json").read_text(encoding="utf-8"))
        manifest = system_manifest(
            parent_system_id=registration["config"]["baseline"], execution_model=model,
            proposal_model=registration["config"]["proposal_model"],
            tokenizer={"base_revision": model["revision"], "renderer": "Qwen3 ChatML render_prompt"},
            prompt={"version": model["prompt_version"], "sha256": model["prompt_sha256"]},
            action_protocol=registration["protocol"], sources=registration["sources"],
            catalog_hash=catalog.hash, skill_revisions=[e["revision"] for e in catalog.entries()],
            boundary_revisions=[e["boundary_revision"] for e in catalog.entries()],
            retrieval=registration["config"]["retrieval"],
            decoding={"do_sample": model["do_sample"], "max_tokens": model["max_tokens"]},
            data_identity=fingerprint(list(tasks.values())), protocol_identity=fingerprint(registration))
        immutable_json(root / "system-manifest.json", {**manifest,
                       "scope": "P1 development system identity; retrospective binding, not a pre-registered formal protocol"})
    rows = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(root.glob("*/result.json"))]
    counts = {k: 0 for k in ("autonomous_eoc", "runtime_assisted_eoc", "runtime_intervention_tasks",
                             "forced_readback_count", "auto_termination_count", "searches", "relevant_searches",
                             "loads", "skill_calls", "successful_skill_calls", "unloaded_calls", "binding_errors",
                             "model_errors", "retrieval_misses", "gate_applicable", "gate_inapplicable", "gate_unknown")}
    cases = []
    for row in rows:
        agent, task = row["agent"], tasks[row["task_id"]]
        if agent["catalog_hash"] != catalog.hash:
            raise ValueError("mixed catalog identity")
        related = {e["skill_id"] for e in catalog.entries() if e["contract"]["family"] == task["family"]}
        helped = agent["interventions"]["runtime_intervention_count"] > 0
        success = row["verification"]["task_success"]
        counts["autonomous_eoc"] += success and not helped
        counts["runtime_assisted_eoc"] += success and helped
        counts["runtime_intervention_tasks"] += helped
        for key in ("forced_readback_count", "auto_termination_count"):
            counts[key] += agent["interventions"][key]
        for search in agent["search_events"]:
            counts["searches"] += 1
            relevant = bool(related & {r["skill_id"] for r in search["results"]})
            counts["relevant_searches"] += relevant
            counts["retrieval_misses"] += not relevant
        counts["loads"] += len(agent["load_events"])
        for event in agent["skill_events"]:
            counts["skill_calls"] += 1
            counts["successful_skill_calls"] += bool(event["success"])
            counts["gate_" + event["gate_status"].lower()] += 1
        errors = [s["error"] for s in agent["steps"] if s.get("error")]
        counts["unloaded_calls"] += errors.count("skill_not_loaded")
        counts["binding_errors"] += errors.count("skill_input_binding_mismatch")
        counts["model_errors"] += errors.count("model_error")
        chain = any(s["success"] for s in agent["skill_events"]) and bool(agent["search_events"]) and bool(agent["load_events"])
        cases.append({"task_id": row["task_id"], "family": task["family"], "eoc": success,
                      "search_load_successful_use": chain, "runtime_assisted": helped, "outcome": agent["outcome"],
                      "errors": errors, "eoc_reasons": row["verification"]["reason"]})
    complete = report["status"] == "complete" and len(rows) == report["planned"]
    minimal_chain = any(c["search_load_successful_use"] for c in cases)
    audit = {"status": report["status"], "n": len(rows), "counts": counts, "cases": cases,
             "relevance_recall_at_k": counts["relevant_searches"] / counts["searches"] if counts["searches"] else None,
             "minimal_real_chain_demonstrated": minimal_chain,
             "all_three_families_demonstrated": len({c["family"] for c in cases if c["search_load_successful_use"]}) == 3,
             "engineering_passed": complete and minimal_chain and all(c["eoc"] for c in cases) and report["actual_violations"] == 0 and report["attempted_violations"] == 0,
             "research_claim_passed": None, "isolated_activated": False,
             "scope": "dev diagnostic; relevance uses declared family in private scorer only; no comparative research or new program-generation claim"}
    immutable_json(root / "audit.json", audit)
    return audit


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__); p.add_argument("--run", required=True)
    print(json.dumps(summarize(p.parse_args().run), ensure_ascii=False))
