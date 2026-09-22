import copy
import pytest

from test_refund_skill import refund_data
from skillforge.learning import make_preference
from skillforge.skills import compile_skill
from skillforge.supervision import counterfactuals
from skillforge.training import encode_example, render_prompt


def test_counterfactual_refund_clones_same_state_and_preserves_branches(refund_data):
    records, tasks = refund_data
    skill = compile_skill(records, "refund")
    task = next(t for t in tasks if t.split == "train" and t.family == "refund" and t.expected.allowed_outcomes == ["completed"] and not t.fixture.get("faults"))
    branches, reason = counterfactuals(task, skill)
    assert reason is None and len(branches) == 3
    assert len({b["snapshot_id"] for b in branches}) == 1
    assert all(b["prompt"] == branches[0]["prompt"] for b in branches)
    assert all(b["initial_state"] == branches[0]["initial_state"] for b in branches)
    assert all(b["llm_calls"] == 0 for b in branches)
    skill_row, refusal, escalation = branches
    assert skill_row["verified_correct"] and len(skill_row["final_state"]["refunds"]) == 1
    assert not refusal["verified_correct"] and refusal["final_state"]["refunds"] == []
    assert not escalation["verified_correct"] and escalation["final_state"]["refunds"] == []
    assert len(escalation["final_state"]["tickets"]) == 1
    assert make_preference(skill_row, refusal)["snapshot_id"] == skill_row["snapshot_id"]
    changed = copy.deepcopy(refusal)
    changed["prompt"]["parameters"]["amount"] += 1
    with pytest.raises(ValueError, match="same context"):
        make_preference(skill_row, changed)


def test_high_risk_requires_escalation_not_refusal(refund_data):
    records, tasks = refund_data
    skill = compile_skill(records, "refund")
    task = next(t for t in tasks if t.split == "train" and t.family == "refund" and t.fixture.get("risk") == "HIGH")
    branches, _ = counterfactuals(task, skill)
    assert [b["action"]["type"] for b in branches if b["verified_correct"]] == ["escalate"]
    assert branches[0]["skill_event"]["error"] == "precondition_failed"
    assert all(not b["verification"]["actual_policy_violation"] for b in branches)
    assert all(b["final_state"]["refunds"] == [] for b in branches)


def test_counterfactual_rejects_other_splits_and_skips_faults(refund_data):
    records, tasks = refund_data
    skill = compile_skill(records, "refund")
    task = next(t for t in tasks if t.family == "refund" and t.split == "test")
    with pytest.raises(ValueError, match="train only"):
        counterfactuals(task, skill)
    task = next(t for t in tasks if t.family == "refund" and t.split == "train" and t.fixture.get("faults"))
    branches, reason = counterfactuals(task, skill)
    assert not branches and reason == "fault_sequence_requires_runtime_supervision"


def test_completion_mask_matches_serving_prefill_and_never_truncates():
    class Tokenizer:
        def encode(self, text, add_special_tokens=False):
            return [ord(c) for c in text]
    context = [{"role": "system", "content": "policy"}, {"role": "user", "content": "state"}]
    prompt = render_prompt(context)
    assert prompt.endswith("<|im_start|>assistant\n<think>\n\n</think>\n\n")
    row = encode_example(Tokenizer(), context, '{"type":"stop"}', 10000)
    boundary = len(prompt)
    assert row["labels"][:boundary] == [-100] * boundary
    assert row["labels"][boundary:] == row["input_ids"][boundary:]
    assert encode_example(Tokenizer(), context, '{"type":"stop"}', len(row["input_ids"]) - 1) is None
