import pytest

from scripts.execution_aware_protocol import design, workload, cost_gate, seed_for
from skillforge.execution_aware.factorial import effects, paired_factorial


def test_complete_workload_includes_lineage_parents_and_independent_decisions():
    config = design()
    plan = workload(config)
    assert plan["full_tasks"] == 9*4*28 + 2*6*28
    assert plan["decision_tasks"] == 9*4*16 + 2*6*16
    assert len(set(config["paired_seeds"])) == 3
    assert config["continual"]["seed"] not in config["paired_seeds"]
    assert seed_for("A-split", 1, "model_validation") != seed_for("A-split", 1, "model_test")


def test_cost_gate_includes_development_and_worst_unknown_retry_tokens():
    config = design()
    strata = [{"world": w, "runtime": r, "bundle": b, "decision_only": d,
               "n": 2, "p95_seconds": 1, "mean_tokens": 100, "max_tokens": 100}
              for w in config["worlds"] for r in ("old", "new") for b in ("old", "proposal") for d in (False, True)]
    gate = cost_gate(config, {"strata": strata}, prior_tokens=1000, prior_seconds=10)
    assert gate["cost_gate_passed"] and not gate["formal_execution_enabled"]
    assert gate["estimates"]["retry_reserved_tokens"] == 2*(16*16384+100)
    assert not cost_gate(config, {"strata": strata}, prior_tokens=20000000)["cost_gate_passed"]
    with pytest.raises(ValueError, match="missing"):
        cost_gate(config, {"strata": strata[1:]})


def test_factorial_definitions_and_cluster_inference():
    arms = {"old_old": .25, "old_proposal": .25, "new_old": .75, "new_proposal": 1.}
    assert effects(arms) == {"runtime_effect": .5, "bundle_effect_under_new_runtime": .25, "interaction": .25}
    rows = [{"world": w, "seed": s, "bundle_scope": "candidate", "complete": True, "arms": arms}
            for w in ("W3", "W5", "W6") for s in (1, 2, 3)]
    result = paired_factorial(rows, replicates=100)
    assert result["world_seed_units"] == 9
    assert result["paired_bootstrap_95"]["interaction"] == [.25, .25]
    with pytest.raises(ValueError, match="independent unit"):
        paired_factorial(rows+[rows[0]], replicates=100)
    with pytest.raises(ValueError, match="separate"):
        paired_factorial([rows[0], {**rows[1], "bundle_scope": "effective"}], replicates=100)
