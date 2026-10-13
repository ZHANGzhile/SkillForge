"""Nested tasks cannot manufacture independent Agent admission evidence."""
from skillforge.boundary_trials.admission import clustered_agent_gate
from test_boundary_lineage import validation_fixture


def test_six_task_wins_in_one_sequence_remain_one_cluster():
    _, data = validation_fixture()
    assert data["agent_report"]["decision"] == "AGENT_GATE_PASSED"  # old arithmetic fixture
    new = clustered_agent_gate(data["boundary_report"], data["agent_report"]["pairs"], cluster_id="W1/sequence-a")
    assert new["decision"] == "INCONCLUSIVE"
    assert len(new["cluster_gate"]["source_group_effects"]) == 1
    assert new["cluster_gate"]["sign_p_value"] == .5
    assert not new["agent_admitted"] and not new["activated"]


def test_clustering_preserves_all_safety_and_stable_rejections():
    _, data = validation_fixture()
    data["agent_report"]["pairs"][-1]["candidate"]["eoc"] = False
    new = clustered_agent_gate(data["boundary_report"], data["agent_report"]["pairs"], cluster_id="W1/sequence-a")
    assert new["decision"] == "REJECTED"
    assert new["cluster_gate"]["regressions"] == [data["agent_report"]["pairs"][-1]["task_id"]]
