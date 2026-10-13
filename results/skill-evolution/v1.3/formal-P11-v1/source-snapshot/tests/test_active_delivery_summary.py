import json

from scripts.summarize_active_evolution_delivery import model_groups


def test_delivery_separates_new_world_and_stable_eoc_and_unchanged_admission(tmp_path):
    cache = tmp_path / "model-layer/cache"
    cache.mkdir(parents=True)
    for key, success in [("before-new", False), ("before-stable", True),
                         ("after-new", True), ("after-stable", False)]:
        (cache / (key + ".json")).write_text(json.dumps({"result": {"verification": {"task_success": success}}}))
    protocol = {"config": {"methods": ["active"], "model_layer": {
        "model_validation": 1, "model_stable_validation": 1, "model_test": 1, "model_stable_test": 1}}}
    phase = {k: 0 for k in ("decision_tasks", "decision_correct", "decision_false_allow", "decision_false_block",
                            "decision_unknown", "actual_violations", "attempted_violations", "tokens", "seconds", "tool_calls")}
    rows = [{"stage": stage, "world": "W3", "method": "active", "before_patch": {"kind": "no_change"},
             "effective_patch": {"kind": "no_change"}, "agent_admitted": True, "stable_regressions": 1,
             "before": phase, "after": phase,
             "refs": ["validation"] * 6 + ["before-new", "before-stable", "after-new", "after-stable"] + ["decision"] * 2}
            for stage in ("independent", "epoch-1", "epoch-2")]
    for group in model_groups(tmp_path, rows, protocol):
        assert group["before"]["new_world_eoc"] == {"correct": 0, "tasks": 1}
        assert group["after"]["new_world_eoc"] == {"correct": 1, "tasks": 1}
        assert group["before"]["stable_eoc"] == {"correct": 1, "tasks": 1}
        assert group["after"]["stable_eoc"] == {"correct": 0, "tasks": 1}
        assert group["changed_bundles"] == 0
        assert group["admission_passed"] == 1
