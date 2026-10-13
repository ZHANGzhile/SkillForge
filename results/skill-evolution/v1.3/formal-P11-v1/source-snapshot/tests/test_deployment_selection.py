import json
from pathlib import Path

import pytest

from scripts.select_deployment_model import choose


def test_deployment_uses_validation_and_excludes_actual_violations():
    policy = json.loads(Path("configs/deployment-selection.json").read_text(encoding="utf-8"))
    def result(rate, violations=0, split="validation"):
        return {"split": split, "full_system": {"task_success_rate": rate, "actual_policy_violation_rate": violations, "average_llm_calls": 2},
            "decision_level": [{"cases": [{"correct": True}]}]}
    assert choose({"SFT": result(.7), "DPO": result(.8)}, policy)["label"] == "DPO"
    assert choose({"SFT": result(.7), "DPO": result(.9, violations=.01)}, policy)["label"] == "SFT"
    assert choose({"SFT": result(.7), "DPO": result(.7)}, policy)["label"] == "SFT"
    with pytest.raises(ValueError, match="test scores"):
        choose({"SFT": result(.7), "DPO": result(.8, split="test")}, policy)
