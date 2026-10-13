"""Declare P2 goals and CPU-check the independent EOC before learn collection."""
import argparse
import json
from pathlib import Path
import time

from scripts.run_skill_evolution import ROOT, digest_file
from skillforge.environment import Environment
from skillforge.evolution_common.artifacts import SplitLedger
from skillforge.evolution_registry import immutable_json
from skillforge.evolution_schemas import fingerprint
from skillforge.skill_evolution.workflows import GOALS, make_case, private_items, verify_workflow, expressivity


def declare(output):
    started = time.perf_counter()
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    goals = {key: {"goal": goal.model_dump(), "hash": goal.identity} for key, goal in GOALS.items()}
    # Publish goals first, without any candidate program or execution result.
    immutable_json(output / "goals.json", goals)
    cases = [make_case(name, 2026101300 + 10 * i + j, "train") for i, name in enumerate(GOALS) for j in range(3)]
    immutable_json(output / "planned-learn-cases.json", [case.model_dump() for case in cases])
    ledger = SplitLedger(ROOT / "results/skill-evolution/v1.2/source-ledger")
    for case in cases:
        ledger.claim(case.source_group, case.split, related_groups=[case.task_id, case.parameters["order_id"], case.authenticated_customer_id])
    checked = []
    for case in cases:
        env = Environment(fixture=case.fixture)
        try:
            initial, items = env.snapshot(), private_items(env)
            # Scripted schema/validator exercise only. Never presented as learn
            # experience or fed into an opportunity miner/TraceCompiler.
            for name in reversed(list(GOALS[case.workflow_id].required_evidence)):
                env.call(name, case.parameters, case.authenticated_customer_id)
                env.audit[-1]["decision_origin"] = "scripted"
            verdict = verify_workflow(case, initial, env.snapshot(), env.audit, "completed", items, private_items(env))
            assert verdict["task_success"]
            checked.append({"case": case.task_id, "verification": verdict, "tool_audit": env.audit})
        finally:
            env.close()
    sources = {name: digest_file(ROOT / name) for name in
               ("skillforge/skill_evolution/workflows.py", "scripts/declare_skill_evolution_workflows.py",
                "skillforge/environment.py", "skillforge/tool_schemas.py")}
    report = {"schema": "p2-workflow-declaration-v1", "goal_set_hash": fingerprint(goals), "sources": sources,
              "task_contract_passed": True, "scripted_checks": checked, "expressivity": expressivity(),
              "planned_learn_cases": len(cases), "real_learn_trajectories": 0, "llm_calls": 0, "model_tokens": 0,
              "candidate_programs": 0, "program_admitted": False, "agent_admitted": False,
              "research_claim_passed": None, "isolated_activated": False, "deployed": False,
              "wall_seconds": time.perf_counter() - started,
              "scope": "pre-candidate task/EOC declaration; scripted checks excluded from real learn evidence; no heldout generation/freeze"}
    immutable_json(output / "report.json", report)
    return {key: report[key] for key in ("task_contract_passed", "planned_learn_cases", "real_learn_trajectories", "candidate_programs", "wall_seconds")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(declare(args.output)), flush=True)
