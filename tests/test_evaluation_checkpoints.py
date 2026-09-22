import json
import pytest

from skillforge.evaluation_checkpoints import read_checkpoint, save_checkpoint


def test_resume_rejects_changed_results_context_and_task(tmp_path):
    path = tmp_path / "task.json"
    identity = {"model": "frozen", "gate": True}
    row = {"task_id": "test-1", "task_hash": "task-content", "verification": {"task_success": False}}
    save_checkpoint(path, row, identity)
    assert not read_checkpoint(path, identity, "test-1", "task-content")["verification"]["task_success"]
    with pytest.raises(ValueError, match="identity/content"):
        read_checkpoint(path, {**identity, "gate": False}, "test-1")
    with pytest.raises(ValueError, match="task mismatch"):
        read_checkpoint(path, identity, "test-2")
    with pytest.raises(ValueError, match="task mismatch"):
        read_checkpoint(path, identity, "test-1", "changed task")
    altered = json.loads(path.read_text())
    altered["verification"]["task_success"] = True
    path.write_text(json.dumps(altered))
    with pytest.raises(ValueError, match="identity/content"):
        read_checkpoint(path, identity, "test-1")


def test_probe_resume_binds_exact_skill_candidate(tmp_path):
    path = tmp_path / "decision.json"
    identity = {"dataset_hash": "fixed", "skill_id": "refund-v1"}
    save_checkpoint(path, {"task_id": "test-1", "correct": True}, identity)
    with pytest.raises(ValueError, match="identity/content"):
        read_checkpoint(path, {**identity, "skill_id": "cancel-v1"}, "test-1")
