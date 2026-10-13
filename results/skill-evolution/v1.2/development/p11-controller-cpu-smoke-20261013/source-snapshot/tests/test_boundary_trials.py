"""Continuous study planning, actual domain limitation and public-worker tests."""
import itertools
import json
import subprocess
import sys

import pytest

from scripts.boundary_trial_agent_plan import agent_stage
from scripts.boundary_trial_dataset import cpu_specs, daily_spec
from scripts.boundary_trial_probe import probe
from scripts.boundary_trial_audits import replay_probe
from scripts.run_boundary_trial_cpu import isolated, observations
from scripts.run_skill_evolution import static_catalog
from skillforge.hypothesis import generate_hypotheses
from skillforge.evolution_config import LearningOptions
from skillforge.evolution_schemas import Hypothesis


def contract():
    return next(e["contract"] for e in static_catalog({"static_bundle": "results/real-v2-frozen/frozen.json"}).entries() if e["contract"]["family"] == "refund")


def test_agent_design_budget_bound_and_validation_test_source_separation():
    seen = set()
    for world in ("W1", "W6"):
        for seed in (2026101301, 2026101302):
            for stage in range(3):
                cases = agent_stage(world, seed, stage)
                assert [sum(c["partition"] == part for c in cases) for part in ("daily", "validation", "test")] == [4, 8, 2]
                assert sum(c["stable"] for c in cases if c["partition"] == "validation") == 2
                assert sum(bool(c["faults"]) for c in cases) == 1
                for c in cases:
                    assert c["task"]["task_id"] not in seen
                    seen.add(c["task"]["task_id"])
                    assert c["world"] == (world if stage < 2 else "H0")
    # Stage 0 has an identical H0 daily parent for both methods (4 physical).
    # Later stages may need 8 daily; all stages at most 16 validation + 4 test.
    assert 4 * ((4 + 16 + 4) + 2 * (8 + 16 + 4)) == 320


def test_declared_three_factor_world_is_not_expressible_by_two_predicates():
    skill = contract()
    specs = cpu_specs("STRUCTURAL3", 2026101391, 0, "explore", 60)
    cube = []
    wanted = set(itertools.product(("LOW", "MEDIUM"), ("NOT_STARTED", "PROCESSING"), ("CAPTURED", "PARTIALLY_REFUNDED")))
    for spec in specs:
        f = spec["fixture"]
        key = f["risk"], f["shipment"], f["payment"]
        if key in wanted:
            wanted.remove(key)
            raw = probe(spec, "STRUCTURAL3", skill)
            replay_probe(raw, spec, skill, "STRUCTURAL3")
            cube.append(observations(raw, spec, skill))
    assert not wanted and len(cube) == 8
    hypotheses = generate_hypotheses(["customer.risk_level", "shipment.status", "payment.status"])
    assert not any(h.kind != "other" and all(h.predict(e.observations, e.baseline_prediction, e.guard_prediction) ==
        (e.label == "executable") for e in cube) for h in hypotheses)


def test_guarded_worker_uses_actual_probe_capability_without_private_inputs(tmp_path):
    skill = contract()
    specs = cpu_specs("W1", 2026101392, 0, "explore", 12)
    segment = specs[0]["policy_epoch"]
    seeds = []
    for i in range(3):
        spec = daily_spec("W1", 2026101392, 0, i)
        seeds.append(observations(probe(spec, "W1", skill), spec, skill).model_copy(update={"policy_epoch": segment}))
    from scripts.active_evolution_dataset import public_candidate
    pool = [public_candidate(s, skill) for s in specs]
    hs = [Hypothesis(hypothesis_id="H0", kind="no_change"), Hypothesis(hypothesis_id="R", kind="restrict",
        predicates=[{"field": "shipment.status", "op": "eq", "value": "PROCESSING"}]), Hypothesis(hypothesis_id="OTHER", kind="other")]
    by_id = {s["task_id"]: s for s in specs}
    used = []
    def actual(cid):
        used.append(cid); spec = by_id[cid]
        return observations(probe(spec, "W1", skill), spec, skill)
    result = isolated(tmp_path / "learner", "ExistingActiveV2", seeds, pool, hs, actual, LearningOptions(), 1)
    packet = json.loads((tmp_path / "learner/public-packet.json").read_text(encoding="utf-8"))
    assert not {"fixture", "world", "expected", "validation", "test"} & set(packet)
    assert len(used) == len(result["queries"]) <= 20
    assert result["diagnostic_hypothesis"]["kind"] == "restrict"


def test_original_policy_restore_is_actual_tool_rule_not_gold_override():
    skill = contract(); spec = daily_spec("W1", 2026101393, 2, 0)
    changed = probe(spec, "W1", skill); restored = probe(spec, "H0", skill)
    assert not changed["procedure_success"] and restored["procedure_success"]
    replay_probe(changed, spec, skill, "W1"); replay_probe(restored, spec, skill, "H0")
