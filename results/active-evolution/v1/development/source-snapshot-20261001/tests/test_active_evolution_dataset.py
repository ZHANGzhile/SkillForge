import copy

import pytest

from skillforge.evolution_evidence import EvidenceBoundary
from skillforge.evolution_schemas import fingerprint


def source():
    task={"task_id":"t","split":"seed","family":"refund","parameters":{"amount":100}}
    manifest={"policy_epoch":"p","members":{"t":{"split":"seed","hash":fingerprint(task)}}}
    trajectory={"trajectory_id":"r","task_id":"t","policy_epoch":"p","origin":"controlled_procedure", "procedure_success":True,
        "initial_state":{"customer.risk_level":"HIGH"},"expected":{"gold":"secret"},
        "tool_audit":[{"tool_name":"get_payment","result":{"payment.status":"CAPTURED","payment.captured_amount":1000,"payment.refunded_amount":0,"hidden":"secret"},"before_state":{"customer.risk_level":"HIGH"}},
            {"tool_name":"issue_refund","committed":True}, {"tool_name":"get_payment","result":{"payment.refunded_amount":100}}]}
    return task,manifest,trajectory


def test_evidence_uses_read_outputs_only_and_prewrite_values():
    task,manifest,trajectory=source()
    view=EvidenceBoundary(manifest).export(trajectory,task,True)
    assert view.label=="executable"
    assert view.observations["payment.refunded_amount"]==0
    assert view.observations["payment.remaining_amount"]==1000
    assert "customer.risk_level" not in view.observations
    assert "secret" not in view.model_dump_json()
    altered=copy.deepcopy(trajectory)
    altered["initial_state"]={"customer.risk_level":"LOW"}
    assert EvidenceBoundary(manifest).export(altered,task,True)==view


def test_manifest_membership_prevents_relabelling():
    task,manifest,trajectory=source()
    task["split"]="explore"
    with pytest.raises(ValueError,match="member"):
        EvidenceBoundary(manifest).export(trajectory,task,True)
    task["split"]="test"
    manifest["members"]["t"]={"split":"test","hash":fingerprint(task)}
    with pytest.raises(ValueError,match="seed/explore"):
        EvidenceBoundary(manifest).export(trajectory,task,True)


def test_business_refusal_collapses_terminal_detail_and_timeout_unknown():
    task,manifest,trajectory=source()
    trajectory["procedure_success"]=False
    trajectory["tool_audit"]=trajectory["tool_audit"][:1]+[{"tool_name":"issue_refund","error":"business_rule_rejected","error_detail":"escalate"}]
    v=EvidenceBoundary(manifest).export(trajectory,task,True)
    assert v.label=="not_executable" and "escalate" not in v.model_dump_json()
    trajectory["tool_audit"][-1]["error"]="timeout"
    assert EvidenceBoundary(manifest).export(trajectory,task,True).label=="unknown"
