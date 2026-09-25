from test_refund_skill import refund_data

from scripts.prepare_recovery_supervision import RecoveryTeacher
from skillforge.environment import Environment
from skillforge.runtime import Runtime
from skillforge.skills import compile_skill


def test_recovery_teacher_verifies_refund_after_distracting_reads(refund_data):
    records, tasks = refund_data
    skill = compile_skill(records, "refund")
    skill.status = "VERIFIED"
    task = next(t for t in tasks if t.split == "train" and t.family == "refund"
        and t.expected.allowed_outcomes == ["completed"] and not t.fixture.get("faults"))
    teacher = RecoveryTeacher(["get_order", "get_order"], primitive=True, distract_after_write=True)
    env = Environment(fixture=task.fixture)
    try:
        result = Runtime(teacher, skills=[skill]).run(task, env)
    finally:
        env.close()
    assert result["verification"]["task_success"]
    assert len(result["final_state"]["refunds"]) == 1
    assert set(teacher.target_steps).isdisjoint(teacher.injected_steps)
    assert len(teacher.injected_steps) == 4
    targets = [s["action"] for s in result["steps"] if s["step_id"] in teacher.target_steps]
    assert any(a["name"] == "issue_refund" for a in targets)
    assert targets[-2]["name"] == "get_payment" and targets[-1]["type"] == "stop"
    assert result["metrics"]["llm_calls"] == 0


def test_recovery_teacher_does_not_turn_policy_boundary_into_mutation(refund_data):
    records, tasks = refund_data
    skill = compile_skill(records, "refund")
    skill.status = "VERIFIED"
    task = next(t for t in tasks if t.split == "train" and t.family == "refund" and t.fixture.get("risk") == "HIGH")
    teacher = RecoveryTeacher(["get_order", "get_order", "get_payment"])
    env = Environment(fixture=task.fixture)
    try:
        result = Runtime(teacher, skills=[skill]).run(task, env)
    finally:
        env.close()
    assert result["verification"]["task_success"] and result["outcome"] == "escalated"
    assert result["final_state"]["refunds"] == []
    assert not result["verification"]["actual_policy_violation"]
