"""CPU/scripted controller integration; none of these are research/model runs."""
from contextlib import nullcontext
import copy
import json

import pytest

from test_skill_evolution_learn import SimulatedSession
from scripts import run_skill_evolution_rounds as study
from scripts import execution_aware_gpu_lease
from scripts import skill_evolution_release
from scripts.verify_skill_evolution_p4 import engineering_cases
from skillforge.evolution_common.artifacts import SplitLedger
from skillforge.skill_evolution.catalog import Catalog
from skillforge.skill_evolution.runtime import runtime_sources, SYSTEM_PROMPT, PROTOCOL
from skillforge.skill_evolution.workflows import make_case


def synthetic_study(tmp_path, monkeypatch, *, candidate_round=False):
    """Replace ONLY protocol/model/GPU provenance, keep raw collection/replay."""
    monkeypatch.setattr(study, "ROOT", tmp_path)
    original_relative = study.relative
    monkeypatch.setattr(study, "relative", lambda path, root=None: original_relative(path, root or tmp_path))
    ledger = SplitLedger(tmp_path / study.LEDGER)
    root = tmp_path / "study"; root.mkdir()
    registry = study.ResearchRegistry(root / "r")
    baseline = Catalog([])
    parent = registry.bootstrap(baseline, reason="SCRIPTED-UNIT-ONLY", evidence=study.hashed({"catalog_hash": baseline.hash}))
    rounds = []
    for number in (1, 2, 3):
        goal = "logistics_investigation" if candidate_round and number == 1 else "shipment_summary"
        cases = [make_case(goal, 82000+number*10+index, "train").model_dump() for index in range(3)]
        probes, validation = {}, []
        if candidate_round and number == 1:
            rows = engineering_cases()
            for row in rows:
                row["case"]["split"] = "validation"
            probes[goal] = rows
            validation = [{"case": make_case(goal, 83500+i, "validation").model_dump(), "stable": i >= 6} for i in range(8)]
            for item in rows+validation:
                value = item["case"]
                ledger.claim(value["source_group"], "stable_validation" if item["stable"] else "validation",
                    related_groups=[value["task_id"], value["parameters"]["order_id"], value["authenticated_customer_id"]])
        rounds.append({"round": number, "learn_cases": cases, "program_validation_probes": probes, "agent_validation_cases": validation})
        for case in cases:
            ledger.claim(case["source_group"], "train", related_groups=[case["task_id"], case["parameters"]["order_id"], case["authenticated_customer_id"]])
    test = make_case("shipment_summary", 82199, "test").model_dump()
    settings = {**SimulatedSession.settings, "prompt_sha256": study.fingerprint(SYSTEM_PROMPT), "decision_protocol": PROTOCOL}
    protocol = study.hashed({"schema": "SCRIPTED-UNIT-ONLY-NOT-A-FROZEN-STUDY", "settings": settings,
        "phase_id": "SCRIPTED-UNIT-ONLY",
        "runtime_sources": runtime_sources(), "model_config": {"adapter": skill_evolution_release.ADAPTER,
            "adapter_sha256": skill_evolution_release.ADAPTER_SHA,
            "limits": {"max_steps": 12, "max_search": 3, "max_load": 3, "max_tokens": 65536}},
        "budget": {"prior_tokens": 7654, "prior_wall": 10, "max_tokens": 1000000, "max_wall": 2000},
        "parent_snapshot": parent, "baseline_entries": [], "screen": {"min_sources": 3, "min_model_call_saving": 1},
        "draft": {"rounds": rounds, "final_test_cases": [{"case": test, "stratum": "instance"}]}})
    monkeypatch.setattr(study, "load_protocol", lambda path: copy.deepcopy(protocol))
    class UnitSession(SimulatedSession):
        def __init__(self, *args, **kwargs): super().__init__(); self.settings = settings
        def send(self, packet):
            if packet["type"] == "run": self.extra_search = candidate_round and packet["task"]["family"] == "logistics_investigation"
            super().send(packet)
    monkeypatch.setattr(study, "ModelSession", UnitSession)
    monkeypatch.setattr(execution_aware_gpu_lease, "GPUServiceLease", lambda: nullcontext())
    if candidate_round:
        original_release = skill_evolution_release.AgentRelease
        monkeypatch.setattr(study, "AgentRelease", lambda registry, ledger: original_release(registry, ledger, artifact_root=tmp_path))
        monkeypatch.setattr(skill_evolution_release, "ModelSession", UnitSession)
        monkeypatch.setattr(skill_evolution_release, "fixed_model", lambda settings: None)
    result = study.run(root)
    return root, protocol, result


def test_scripted_three_round_zero_update_chain_final_test_and_independent_audit(tmp_path, monkeypatch):
    root, protocol, result = synthetic_study(tmp_path, monkeypatch)
    assert result["completed_real_rounds"] == 3  # Synthetic collector path only.
    assert result["shared_total_tokens"] == 7654+3600
    assert all(row["n_candidates"] == 0 and row["agent_decision"] == "SKIPPED_NO_CANDIDATE" for row in result["rounds"])
    assert not result["agent_admitted"] and not result["isolated_activated"] and not result["deployed"]
    assert all(item["eoc"] == 1 for item in result["final"]["methods"].values())
    assert result["final"]["paired_C_B"][0]["C_minus_B_eoc"] == 0
    assert study.audit(root)["passed"]
    # Resume cannot issue any additional inference for completed stages.
    monkeypatch.setattr(study, "ModelSession", lambda *args, **kwargs: pytest.fail("completed study must not recollect"))
    assert study.run(root) == result


def test_scripted_candidate_program_provenance_passes_but_agent_tie_retains_parent(tmp_path, monkeypatch):
    root, protocol, result = synthetic_study(tmp_path, monkeypatch, candidate_round=True)
    first = result["rounds"][0]
    assert first["n_candidates"] == 1 and first["program_decision"] == "ADMITTED"
    assert first["agent_decision"] == "INCONCLUSIVE" and not first["agent_admitted"]
    assert first["candidate_snapshot"] != first["selected_snapshot"]
    assert first["parent_catalog_hash"] == first["selected_catalog_hash"]
    assert study.audit(root)["passed"]


@pytest.mark.parametrize("change", ["round_cost", "parent", "report", "raw_context", "orphan"])
def test_round_chain_or_aggregate_tampering_cannot_pass_independent_audit(tmp_path, monkeypatch, change):
    root, protocol, result = synthetic_study(tmp_path, monkeypatch)
    if change in {"round_cost", "parent"}:
        path = root / "r2/start.json"; value = study.read(path)
        value["prior_tokens" if change == "round_cost" else "parent_snapshot"] = 0 if change == "round_cost" else protocol["parent_snapshot"]
        value = study.hashed({key: item for key, item in value.items() if key != "hash"})
    elif change == "report":
        path = root / "report.json"; value = study.read(path); value["shared_total_tokens"] = 0
        value = study.hashed({key: item for key, item in value.items() if key != "hash"})
    elif change == "raw_context":
        path = root / "r1/learn/0/C/result.json"; value = study.read(path)
        value["agent"]["steps"][0]["context"]["raw_trajectories"] = ["future test feedback"]
    else:
        folder = root / "test/99/C"; folder.mkdir(parents=True)
        path = folder / "collection-status.json"; value = {"charged_tokens": 16384}
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError): study.audit(root)
