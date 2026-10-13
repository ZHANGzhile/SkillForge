import pytest

from scripts.verify_skill_evolution_p1 import capacity, primitive_contract
from skillforge.skill_evolution.catalog import Catalog
from test_skill_evolution_catalog import entry


@pytest.mark.parametrize("size", [300, 1000])
def test_entire_synthetic_catalog_is_scored_deterministically(size):
    result = capacity(Catalog([entry()]), size)
    assert result["total_indexed"] == size + 1
    assert len(result["retrieval_audit"]["ranking"]) == size + 1
    assert result["deterministic_replay"]


def test_primitive_path_uses_same_runtime_prompt_permissions_and_limits():
    result = primitive_contract(Catalog([entry()]))
    assert result["equal_context_except_catalog_identity"]
    assert all(v["agent"]["interventions"]["forced_readback_count"] == 1 for v in result["arms"])
    assert all(v["agent"]["interventions"]["auto_termination_count"] == 1 for v in result["arms"])


def test_wrong_namespace_is_rejected_without_converting_model_actions():
    result = primitive_contract(Catalog([entry()]), malformed=True)
    assert all(not v["agent"]["skill_events"] for v in result["arms"])
    assert all(v["agent"]["steps"][0]["action"]["type"] == "skill" for v in result["arms"])
