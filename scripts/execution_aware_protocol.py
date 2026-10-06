"""Protocol A design and stratified resource planning; no implicit freeze."""
import argparse
import json
from pathlib import Path

from scripts.active_evolution_dataset import generate, audit_splits, coverage_core
from scripts.active_evolution_model_design import model_core
from scripts.prepare_active_evolution import file_hash
from skillforge.evolution_boundary import parent_identity
from skillforge.evolution_registry import immutable_json
from skillforge.evolution_schemas import fingerprint


def seed_for(namespace, *parts):
    return 10000000 + int(fingerprint(["execution-aware-seeds-v1", namespace, *parts])[:12], 16) % 90000000


def design(stable_test=8):
    if stable_test not in {4, 8}:
        raise ValueError("predeclared stable-test sizes are 8, fallback 4")
    return {"version": "execution-aware-v1.1-A", "status": "draft-not-frozen",
            "worlds": ["W3", "W5", "W6"], "paired_seeds": [seed_for("A-independent", i) for i in range(3)],
            "acquisition": "frozen-v1-active", "weights": "fixed-main-v3", "max_steps": 16,
            "model_counts": {"model_validation": 8, "model_stable_validation": 4,
                             "model_test": 8, "model_stable_test": stable_test},
            "cpu_counts": {"seed": 12, "explore": 80, "validation": 40, "stable_validation": 40,
                           "test": 80, "stable_test": 80},
            "continual": {"worlds": ["W3", "W5"], "seed": seed_for("A-continual", 0),
                          "separate_cpu_and_agent_parent_chains": True, "independent_statistical_unit": False},
            "arms": {"runtime": ["old", "new"], "bundle": ["old", "proposal"]},
            "estimands": {
                "runtime_effect": "Y(new,old)-Y(old,old)",
                "bundle_effect_under_new_runtime": "Y(new,proposal)-Y(new,old)",
                "interaction": "[Y(new,proposal)-Y(new,old)]-[Y(old,proposal)-Y(old,old)]"},
            "primary": ["agent_admission_rate", "effective_bundle_new_world_eoc_gain_under_new_runtime"],
            "statistical_unit": "world-seed; tasks and repeated validations are nested",
            "candidate_and_effective_estimands_separate": True,
            "admission": {"actual_violations": 0, "normal_regressions": 0, "stable_regressions": 0,
                          "boundary_false_allow": 0, "boundary_false_block_noninferior": True,
                          "decision_noninferior": True, "full_eoc_noninferior": True},
            "limits": {"shared_gpu_seconds": 43200, "shared_tokens": 20000000,
                       "task_wall_seconds": 180, "global_infrastructure_retries": 2,
                       "per_task_retries": 1, "startup_seconds": 600, "restart_seconds": 240},
            "budget_fallback": "before formal outcomes only: stable_test 8->4; keep 3 seeds/world and all 8 changed-policy strata",
            "scope": "same declared rule families, fresh instances; no unseen-rule generalization claim"}


def workload(config):
    m = config["model_counts"]
    full = sum(m.values()); decision = m["model_validation"] + m["model_test"]
    rows = []
    def add(stage, world, bundles, multiplier):
        for runtime in ("old", "new"):
            for bundle in bundles:
                for mode, n in (("full", full), ("decision", decision)):
                    rows.append({"stage": stage, "world": world, "runtime": runtime,
                                 "bundle": bundle, "mode": mode, "executions": n*multiplier})
    for world in config["worlds"]:
        add("independent", world, ("old", "proposal"), len(config["paired_seeds"]))
    for index, world in enumerate(config["continual"]["worlds"], 1):
        # Reserve each Runtime's actual Agent parent as well as the common CPU
        # parent and candidate. They may differ after an earlier rejection.
        add("epoch-"+str(index), world, ("old", "proposal", "agent_parent"), 1)
    return {"strata": rows, "full_tasks": sum(r["executions"] for r in rows if r["mode"] == "full"),
            "decision_tasks": sum(r["executions"] for r in rows if r["mode"] == "decision"),
            "reuse": "maximum workload reserves all arms; exact-identity aliases may reduce actual charges, never independent sample counts"}


def cost_gate(config, smoke, prior_tokens=0, prior_seconds=0):
    rows = workload(config); measured = smoke["strata"]
    seconds = tokens = 0
    for row in rows["strata"]:
        matches = [r for r in measured if r["world"] == row["world"] and r["runtime"] == row["runtime"]
                   and r["decision_only"] == (row["mode"] == "decision")
                   and (row["bundle"] == "agent_parent" or r["bundle"] == row["bundle"])]
        if not matches or any(r["n"] < 2 for r in matches):
            raise ValueError("missing cost stratum")
        seconds += row["executions"]*max(r["p95_seconds"] for r in matches)
        tokens += row["executions"]*max(r["mean_tokens"] for r in matches)
    limits = config["limits"]; retries = limits["global_infrastructure_retries"]
    # Unknown failed generations charged at their hard per-task token maximum.
    retry_tokens = retries * (16*16384 + max(r["mean_tokens"] for r in measured))
    retry_seconds = retries * (limits["task_wall_seconds"] + limits["restart_seconds"] + max(r["p95_seconds"] for r in measured))
    estimated_seconds = prior_seconds + seconds + retry_seconds + limits["startup_seconds"]
    estimated_tokens = prior_tokens + tokens + retry_tokens
    return {"config_hash": fingerprint(config), "workload": rows, "prior_tokens": prior_tokens, "prior_seconds": prior_seconds,
            "estimates": {"all_in_seconds": estimated_seconds, "all_in_tokens": estimated_tokens,
                          "retry_reserved_tokens": retry_tokens, "retry_reserved_seconds": retry_seconds},
            "cost_gate_passed": estimated_seconds <= limits["shared_gpu_seconds"] and estimated_tokens <= limits["shared_tokens"],
            "formal_execution_enabled": False,
            "scope": "predeclared world/runtime/bundle/mode stratified P95 time and mean tokens; tiny smoke is not a worst-case guarantee; hard dispatch budgets remain mandatory"}


def write_split_dataset(root, world, cohort_seed, counts, contract, previous_world=None):
    rows = []; split_seeds = {}
    for split, n in counts.items():
        split_seeds[split] = seed_for("A-split", cohort_seed, split)
        generated = generate(world, split_seeds[split], {split: n*8 if previous_world and "stable" in split else n})
        if previous_world and "stable" in split:
            from scripts.active_evolution_dataset import state_for_policy
            from scripts.active_evolution_worlds import policy
            generated = [r for r in generated if
                         (policy(world, "issue_refund", state_for_policy(r), r["parameters"]) == "allow") ==
                         (policy(previous_world, "issue_refund", state_for_policy(r), r["parameters"]) == "allow")][:n]
            if len(generated) != n:
                raise ValueError("insufficient adjacent-epoch stable support")
        rows.extend(generated)
    if len(set(split_seeds.values())) != len(split_seeds):
        raise ValueError("derived split seed collision")
    audit_splits(rows)
    family = contract["family"]
    requirements = {s: len(model_core(family, stable="stable" in s)) if s.startswith("model_") else len(coverage_core(family))
                    for s in counts if s != "seed" and (s.startswith("model_") or "stable" not in s)}
    manifest = {"format": "execution-aware-A-data-v1", "world": world, "seed": cohort_seed, "split_seeds": split_seeds,
                "policy_epoch": rows[0]["policy_epoch"], "counts": counts, "parent": parent_identity(contract),
                "members": {r["task_id"]: {"hash": fingerprint(r), "split": r["split"]} for r in rows},
                "coverage_requirements": requirements, "partial_coverage_splits": [s for s, n in requirements.items() if counts[s] < n],
                "scope": "disjoint split seeds and objects; same public factor support may recur"}
    if previous_world:
        manifest["previous_world"] = previous_world
    if manifest["partial_coverage_splits"]:
        raise ValueError("declared coverage incomplete")
    for split in counts:
        immutable_json(root/(split+".json"), [r for r in rows if r["split"] == split])
    immutable_json(root/"parent-skill.json", contract); immutable_json(root/"manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("results/active-evolution/v1.1/preparation-A-v1"))
    parser.add_argument("--cost-root", type=Path)
    parser.add_argument("--prepare-data", action="store_true")
    args = parser.parse_args(); config = design()
    immutable_json(args.output/"design-draft.json", config)
    immutable_json(args.output/"workload-draft.json", workload(config))
    if args.cost_root:
        smoke = json.loads((args.cost_root/"summary.json").read_text(encoding="utf-8"))
        prior = json.loads(Path("results/active-evolution/v1.1/development/resource-ledger.json").read_text(encoding="utf-8"))
        invocation = json.loads((args.cost_root/"invocation.json").read_text(encoding="utf-8"))
        if invocation["status"] != "complete":
            raise ValueError("cost smoke incomplete")
        charged_tokens = prior["charged_tokens"] + invocation["charged_tokens"]
        charged_seconds = prior["invocation_seconds"] + invocation["invocation_seconds"]
        plans = [cost_gate(design(n), smoke, charged_tokens, charged_seconds) for n in (8, 4)]
        immutable_json(args.output/"cost-options.json", {"options": plans, "selection": "first passing predeclared option; no quality results consulted"})
        print(json.dumps([{"stable_test": n, **p["estimates"], "passed": p["cost_gate_passed"]} for n, p in zip((8,4), plans)]))
    if args.prepare_data:
        contracts = {s["family"]: s for s in json.loads(Path("results/real-v2-frozen/frozen.json").read_text(encoding="utf-8"))["skills"]}
        seen = set(); receipts = []
        counts = {**config["cpu_counts"], **config["model_counts"]}
        for world in config["worlds"]:
            for seed in config["paired_seeds"]:
                directory = args.output/"datasets"/world/str(seed)
                manifest = write_split_dataset(directory, world, seed, counts, contracts["modify_address" if world == "W6" else "refund"])
                if seen & set(manifest["members"]):
                    raise ValueError("cross-cohort instance collision")
                seen.update(manifest["members"])
                receipts.append({"world": world, "seed": seed, "manifest_hash": file_hash(directory/"manifest.json")})
        immutable_json(args.output/"data-receipt.json", {"datasets": receipts, "instances": len(seen), "test_scored": False})


if __name__ == "__main__":
    main()
