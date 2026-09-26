"""Read-only coverage diagnosis; never exports new optimizer examples."""
import json
from pathlib import Path

from scripts.coordinator_io import atomic_json
from scripts.evaluate_reuse_ablation import prepared, read
from skillforge.dataset import load_dataset
from skillforge.training_data import file_hash, load_training_data


def conditions(task):
    f, p = task.fixture, task.parameters
    remaining = f.get("captured", 10000) - f.get("refunded", 0)
    return {
        "high_risk_and_shipped": f.get("risk") == "HIGH" and f.get("shipment") in {"SHIPPED", "DELIVERED"},
        "invalid_address_with_cancel_fallback": task.workflow == "address_else_cancel_else_escalate" and f.get("invalid_address", False),
        "shipped_with_explicit_human_fallback": task.family == "composite" and f.get("shipment") in {"SHIPPED", "DELIVERED"},
        "refund_above_remaining": task.family == "refund" and p.get("amount", 0) > remaining,
        "refund_exact_remaining": task.family == "refund" and p.get("amount", 0) == remaining,
    }


def audit():
    plan, identity, test, reference = prepared("configs/reuse-ablation.json")
    config = read(plan["training_config"])
    _, original = load_dataset(config["dataset"])
    sft, _, corpus = load_training_data(config["dataset"], config["bundle"], config["real_data"], config["supervision"], config["baseline"])
    train = [t for t in original if t.split == "train"]
    validation = [t for t in original if t.split == "validation"]
    by_order = {t.parameters["order_id"]: t for t in train}
    supervised_tasks = []
    for row in sft:
        context = json.loads(row["messages"][1]["content"])
        supervised_tasks.append(by_order[context["parameters"]["order_id"]])
    rows = []
    for condition in conditions(test[0]):
        matched = [t for t in test if conditions(t)[condition]]
        rows.append({"condition": condition,
            "train_tasks": sum(bool(conditions(t)[condition]) for t in train),
            "validation_tasks": sum(bool(conditions(t)[condition]) for t in validation),
            "unique_sft_action_targets": sum(bool(conditions(t)[condition]) for t in supervised_tasks),
            "inspected_test_tasks": len(matched),
            "b3_test_passed": sum(reference[t.task_id]["verification"]["task_success"] for t in matched),
            "test_task_ids": [t.task_id for t in matched]})
    report = {"scope": "Retrospective coverage diagnosis, not training export or unseen-test evidence. Deliberately held-out conditions are not a data leakage bug.",
        "corpus_hash": corpus["corpus_hash"], "sft_examples": len(sft),
        "reference_identity_hash": identity["reference_identity_hash"], "analyzer_sha256": file_hash(__file__), "conditions": rows}
    output = Path("results/training-diagnostics/main-v3/boundary-coverage.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(output, report)
    lines = ["# main-v3边界覆盖核验", "", "先重新审核全部原训练语料和新实例B3检查点，再统计以下条件。本脚本只读分析，不生成训练样本。", "",
        "| 条件 | train任务 | validation任务 | 去重SFT动作目标 | 已查看test任务 | B3合格 |",
        "|---|---:|---:|---:|---:|---:|"]
    for r in rows:
        lines.append(f"| {r['condition']} | {r['train_tasks']} | {r['validation_tasks']} | {r['unique_sft_action_targets']} | {r['inspected_test_tasks']} | {r['b3_test_passed']} |")
    lines += ["", "复合三分支和风险/物流冲突是原数据设计中的保留条件；没有train样本本身不是实现错误。validation69/69不能外推到这些没有覆盖的组合条件。超额退款在train中已有样本，其失败还需要检查数值比较与多步决策，不能一概解释为训练完全没见过。",
        "", "如后续将这些结构纳入新版本训练，必须明确改变泛化研究范围，重新设计分区与尚未使用的新测试结构；不能把本次test改标为train后继续沿用原独立测试结论。",
        "", "原始记录：results/training-diagnostics/main-v3/boundary-coverage.json。动作目标数量不是独立任务数量。"]
    Path("docs/BOUNDARY_COVERAGE.md").write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    return report


if __name__ == "__main__":
    print(json.dumps(audit(), ensure_ascii=True, indent=2))
