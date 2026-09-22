import pytest

from skillforge.learning import make_preference
from skillforge.pipeline import engineering_pipeline


def test_full_engineering_pipeline(tmp_path):
    report = engineering_pipeline(tmp_path)
    assert report["engineering_only"]
    assert report["validation"]["positive_success_rate"] == 1
    assert report["validation"]["negative_rejection_rate"] == 1
    assert report["sft_fixture_actions"] > 0
    assert len(report["comparison"]) == 4
    assert report["comparison"][3]["skill_reuse_attempts"] > 0
    assert report["comparison"][3]["average_gate_tool_calls"] > 0


def test_dpo_rejects_different_context_and_test_split():
    good = {"split": "train", "prompt": {"state": "SHIPPED"}, "snapshot_id": "s", "verified_correct": True, "action": "escalate", "evidence_id": "a"}
    bad = {**good, "verified_correct": False, "action": "update", "evidence_id": "b"}
    assert make_preference(good, bad)["context_hash"]
    with pytest.raises(ValueError, match="same context"):
        make_preference(good, {**bad, "prompt": {"state": "NOT_STARTED"}})
    with pytest.raises(ValueError, match="train split"):
        make_preference(good, {**bad, "split": "test"})
