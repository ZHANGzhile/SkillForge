from skillforge.benchmark import generate_tasks, run_benchmark
from skillforge.model import ScriptedPolicy


def test_24_task_engineering_smoke(tmp_path):
    summary, results = run_benchmark(ScriptedPolicy(), output_root=tmp_path)
    assert summary["tasks"] == 24
    assert summary["task_success_rate"] == 1, [(r["task_id"], r["verification"]["reason"]) for r in results if not r["verification"]["task_success"]]
    assert summary["engineering_only"]
    assert summary["average_llm_calls"] == 0
    assert summary["average_decision_calls"] > 0
    for result in results:
        for step in result["steps"]:
            assert "expected" not in step["context"]
            assert "fixture" not in step["context"]
            assert "initial_state" not in step["context"]


def test_split_ids_disjoint():
    groups = [{t.task_id for t in generate_tasks(s)} for s in ["train", "validation", "test"]]
    assert not groups[0] & groups[1] and not groups[0] & groups[2]
