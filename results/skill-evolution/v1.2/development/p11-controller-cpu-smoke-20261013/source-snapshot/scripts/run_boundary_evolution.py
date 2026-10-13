"""Stage 2 preflight / freeze / separate CPU and real Agent execution."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid

from scripts.run_skill_evolution import ROOT, digest_file, preflight as historical_preflight
from scripts.skill_evolution_release import relative
from scripts.continue_skill_evolution_selection import publish
from scripts.boundary_trial_dataset import cpu_specs
from scripts.boundary_trial_agent_plan import agent_stage
from skillforge.skill_evolution.agent_evidence import read
from skillforge.skill_evolution.catalog import Catalog
from skillforge.boundary_evolution.trigger import TriggerPolicy
from skillforge.boundary_lineage.proposal import checked, hashed
from skillforge.evolution_config import LearningOptions
from skillforge.evolution_common.artifacts import SplitLedger
from skillforge.boundary_runtime.runtime import runtime_sources, PROTOCOL
from skillforge.evolution_schemas import fingerprint


def sources():
    values = {relative(p): digest_file(p) for folder in ("skillforge", "scripts", "tests") for p in (ROOT / folder).rglob("*.py")
        if "__pycache__" not in p.parts and "skill_evolution_workbench" not in p.parts}
    return values


def preflight(output):
    output = Path(output).resolve()
    if output.exists(): raise ValueError("fresh preflight root required")
    config = read(ROOT / "configs/skill-evolution-v1.2.context-dev.json")
    old = historical_preflight(config, output / "historical", tests=False)
    copied = ROOT / ".runtime" / ("boundary-preflight-" + uuid.uuid4().hex)
    copied.mkdir(parents=True)
    for name in ("skillforge", "scripts", "tests", "configs"):
        shutil.copytree(ROOT / name, copied / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "model.local.json", "deployment.local.json"))
    shutil.copy2(ROOT / "pyproject.toml", copied / "pyproject.toml")
    # New boundary tests use the actual immutable static program fixture. Its
    # bytes are recorded and copied; no private formal outcomes are supplied.
    fixture = "results/real-v2-frozen/frozen.json"
    target = copied / fixture; target.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / fixture, target)
    env = {k: v for k, v in os.environ.items() if not k.startswith("SKILLFORGE_")}
    env.update(PYTHONPATH=str(copied), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    started = time.perf_counter()
    result = subprocess.run([str(ROOT / ".venv/Scripts/python.exe"), "-m", "pytest", "-q", "--basetemp", str(copied / "tmp")],
        cwd=copied, env=env, capture_output=True, text=True, encoding="utf-8")
    (output / "pytest.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    receipt = hashed({"schema": "continuous-boundary-preflight-v1", "passed": old["passed"] and result.returncode == 0,
        "historical_preflight_hash": fingerprint(old), "sources": sources(), "source_copy": str(copied),
        "fixture": {fixture: digest_file(ROOT / fixture)}, "pytest_exit_code": result.returncode,
        "pytest_log_sha256": digest_file(output / "pytest.log"), "wall_seconds": time.perf_counter() - started,
        "new_model_calls": 0, "new_tokens": 0})
    publish(output / "preflight.json", receipt)
    return receipt


def freeze(output, preflight_root):
    output = Path(output).resolve()
    if output.exists(): raise ValueError("fresh protocol root required")
    pf = read(Path(preflight_root) / "preflight.json"); checked(pf)
    if not pf["passed"] or pf["sources"] != sources(): raise ValueError("passing exact-current-source preflight required")
    stage1 = ROOT / "results/skill-evolution/v1.2/formal-P5-v1"
    smoke_root = ROOT / "results/skill-evolution/v1.2/development/p9-changed-runtime-smoke-20261012"
    prior, audit, prior_protocol = read(smoke_root / "report.json"), read(smoke_root / "independent-audit.json"), read(smoke_root / "protocol.json")
    for value in (prior, audit, prior_protocol): checked(value)
    if not prior["complete"] or not audit["passed"] or audit["report_hash"] != prior["hash"]: raise ValueError("audited complete changed smoke required")
    first = read(stage1 / "stage1-freeze.json"); checked(first)
    for name, sha in first["implementation_sources"].items():
        if digest_file(ROOT / name) != sha: raise ValueError("Stage 1 frozen source changed")
    base = Catalog.load(stage1 / "stage1-catalog.json")
    prior_wall = prior_protocol["prior_wall_seconds"] + prior["collection_wall_seconds"]
    phase_tokens, phase_wall = 17700000, 37800
    if prior["shared_total_tokens"] + phase_tokens > 20000000 or prior_wall + phase_wall > 43200:
        raise ValueError("shared 20M token / 12h conservative wall cap violated")
    protocol = hashed({"schema": "continuous-boundary-formal-engineering-v1", "scale": "ENGINEERING_NOT_RESEARCH_POWERED",
        "stage1_freeze_hash": first["hash"], "preflight_hash": pf["hash"], "catalog_hash": base.hash,
        "sources": sources(), "runtime_protocol": PROTOCOL, "runtime_sources": runtime_sources(),
        "cpu_worlds": ["W1", "W6", "STRUCTURAL3"], "agent_worlds": ["W1", "W6"], "sequence_seeds": [2026101301, 2026101302],
        "stages": ["changed", "unchanged", "restore_original"],
        "cpu_methods": ["no_adapt", "passive", "random", "OriginalActive", "ExistingActiveV2"],
        "agent_methods": ["NoAdapt", "ExistingActive"], "improved_active": "NOT_SELECTED_KEEP_EXISTING",
        "learning": LearningOptions().model_dump(), "trigger_policy": TriggerPolicy().model_dump(),
        "hypothesis_fields": ["customer.risk_level", "order.status", "shipment.status", "payment.status", "request.amount", "payment.remaining_amount"],
        "cpu_counts": {"explore": 60, "validation": 60, "stable_validation": 16, "test": 60, "stable_test": 16},
        "agent_design": {"daily": 3, "fault_only_daily": 1, "primary_validation": 6, "stable_validation": 2, "primary_test": 1, "stable_test": 1},
        "agent_gate": {"min_groups": 6, "alpha": .05}, "agent_gate_primary": "paired EOC; zero stable/task regression; actual violation zero; attempted no increase",
        "limits": {"max_steps": 12, "max_search": 3, "max_load": 3, "max_tokens": 131072},
        "prior_report_hash": prior["hash"], "prior_tokens": prior["shared_total_tokens"], "prior_wall_seconds": prior_wall,
        "phase_tokens": phase_tokens, "phase_wall_seconds": phase_wall, "max_physical_agent_arms": 320,
        "cost_forecast": {"max_smoke_arm_tokens": max(r["tokens"] for r in prior["rows"]), "token_margin": 1.25,
            "forecast_tokens": max(r["tokens"] for r in prior["rows"]) * 320 * 1.25,
            "smoke_mean_wall_per_arm": prior["collection_wall_seconds"] / len(prior["rows"]), "wall_margin": 1.1,
            "forecast_wall_seconds": prior["collection_wall_seconds"] / len(prior["rows"]) * 320 * 1.1,
            "scope": "conservative planning estimate, not a guarantee; every approved request charged, incomplete studies never reported complete"},
        "arm_reuse": "identical private task, faults, actual environment world, fixed model/Runtime and exact Boundary only; report logical and physical costs separately",
        "statistical_unit": "world-sequence (4 real Agent units); tasks/stages nested; no significance claim across independent worlds",
        "stronger_model": "NOT_CONFIGURED", "new_training": False, "deployed": False,
        "stop_rule": "fixed full cohort or predeclared resource/infrastructure stop; never performance-based resizing",
        "structural_scope": "CPU-only predeclared three-factor conjunction outside max-two-predicate language; not a new acquisition method"})
    if protocol["cost_forecast"]["forecast_tokens"] > phase_tokens or protocol["cost_forecast"]["forecast_wall_seconds"] > phase_wall:
        raise ValueError("declared matrix exceeds cost-smoke planning margin")
    publish(output / "protocol.json", protocol); base.save(output / "catalog.json")
    publish(output / "preflight.json", pf)
    ledger = SplitLedger(ROOT / "results/skill-evolution/v1.2/source-ledger")
    for world in protocol["agent_worlds"]:
        for seed in protocol["sequence_seeds"]:
            for stage in range(3):
                folder = output / "datasets" / world / str(seed) / str(stage)
                cases = agent_stage(world, seed, stage)
                publish(folder / "agent-cases.json", cases)
                pool = cpu_specs(world, seed, stage, "explore", protocol["cpu_counts"]["explore"])
                publish(folder / "explore.json", pool)
                for case in cases:
                    spec = case["spec"]
                    partition = "train" if case["partition"] == "daily" else "stable_" + case["partition"] if case["stable"] else case["partition"]
                    ledger.claim(case["source_group"], partition, related_groups=[spec["task_id"], spec["fixture"]["order_id"], spec["fixture"]["customer_id"]])
                for spec in pool:
                    ledger.claim("continuous-agent-explore-" + spec["task_id"], "train", related_groups=[spec["task_id"], spec["fixture"]["order_id"], spec["fixture"]["customer_id"]])
    for name, sha in protocol["sources"].items():
        target = output / "source-snapshot" / name; target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(ROOT / name, target)
        if digest_file(target) != sha: raise ValueError("source changed while freezing")
    publish(ROOT / "results/skill-evolution/v1.2/stage2-formal-budget-ledger" / (fingerprint(relative(output)) + ".json"),
        {"protocol_hash": protocol["hash"], "prior_tokens": protocol["prior_tokens"], "phase_tokens": phase_tokens,
         "prior_wall_seconds": prior_wall, "phase_wall_seconds": phase_wall, "new_training": False})
    return protocol


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["preflight", "freeze", "cpu", "agent"])
    parser.add_argument("--output"); parser.add_argument("--preflight"); parser.add_argument("--run")
    args = parser.parse_args()
    if args.command == "preflight": result = preflight(args.output)
    elif args.command == "freeze": result = freeze(args.output, args.preflight)
    elif args.command == "cpu":
        from scripts.run_boundary_trial_cpu import run
        result = run(args.run)
    else:
        from scripts.run_boundary_trial_agent import run
        result = run(args.run)
    print({k: result.get(k) for k in ("hash", "passed", "complete", "failure", "scale")})
