import pytest
from scripts.evaluate_stability import summarize


def test_all_repeats_requires_every_run_and_preserves_mixed_outcomes():
    plan = {"task_hashes": {"a": "hash-a", "b": "hash-b"}, "repeats": 3,
        "strata": {"a": {"family": "refund", "level": "A"}, "b": {"family": "refund", "level": "E"}}, "scope": "test"}
    def row(key, passed, outcome):
        return {"task_id": key, "task_hash": "hash-" + key, "outcome": outcome, "verification": {"task_success": passed}}
    runs = {"a": [row("a", True, "completed") for _ in range(3)],
        "b": [row("b", True, "escalated"), row("b", False, "refused"), row("b", True, "escalated")]}
    report = summarize(plan, runs)
    assert report["pass_all_repeats"] == .5
    assert report["outcome_consistency_rate"] == .5
    runs["a"].pop()
    with pytest.raises(ValueError, match="repeat/task"):
        summarize(plan, runs)
