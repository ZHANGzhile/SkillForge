"""Generate the retrospective report only from fully audited paired evidence."""
import argparse
from pathlib import Path

from scripts.evaluate_reuse_ablation import audit


def report(plan_path="configs/reuse-ablation.json"):
    result = audit(plan_path)
    pair = result["paired"]
    lines = ["# main-v3 同模型无Skill对照", "",
        "固定同一SFT权重、system prompt、任务初态及工具政策，覆盖全部78个已冻结新实例test。该test此前已被查看，本实验是事后系统消融，不用于训练或部署选优。", "",
        "| 指标 | B0（无Skill） | B3（冻结Skill） |", "|---|---:|---:|"]
    for key, title in (("task_success_rate", "EOC合格率"), ("average_llm_calls", "平均LLM调用"),
                       ("average_tool_calls", "平均工具调用"), ("average_tokens", "平均token"),
                       ("skill_reuse_attempts", "Skill调用"), ("model_attempted_policy_violation_rate", "模型违规尝试率"),
                       ("actual_policy_violation_rate", "实际违规率")):
        lines.append(f"| {title} | {pair['B0'][key]:.4f} | {pair['B3'][key]:.4f} |")
    lines += ["", f"逐任务配对：启用Skill的B3相对B0改善{pair['paired_improvements']}例、退步{pair['paired_regressions']}例。",
        "", f"全任务分母的系统退步率：{pair['skill_enabled_system_regression_rate']:.2%}；B0成功条件下的退步率：{pair['regression_given_b0_success'] if pair['regression_given_b0_success'] is not None else 'null'}。",
        "", f"退步且实际尝试Skill的任务：{pair['regressions_with_observed_skill_attempt']}。这仍是关联描述；same-context causal NTR保持null。",
        "", "B0移除Skill候选，也同时取消自动Gate补读，因此初始可见状态与后续决策上下文会改变。差值属于整个系统配置的影响，不能全部归因于Skill执行器。B0经真实HTTP服务，B3复用同身份的直接HF检查点；不据此声称严格延迟加速或统计显著性。",
        "", "## 原B3失败自动归类", "", "| 证据类型 | 任务数 |", "|---|---:|"]
    for kind, count in sorted(pair["b3_failure_counts"].items()):
        lines.append(f"| {kind} | {count} |")
    lines += ["", "## 所有退步及原B3失败的逐任务对照", "", "| task ID | 任务族 | B0合格 | B3合格 | B3 Skill次数 | B0证据类型 | B3证据类型 |", "|---|---|---|---|---:|---|---|"]
    for row in pair["cases"]:
        if not row["b3_passed"] or row["b3_helped"]:
            lines.append(f"| {row['task_id']} | {row['family']} | {row['b0_passed']} | {row['b3_passed']} | {row['b3_skill_attempts']} | {row['b0_failure_kind'] or '—'} | {row['b3_failure_kind'] or '—'} |")
    lines += ["", "证据：configs/reuse-ablation.json预声明范围；results/reuse-ablation/main-v3包含逐任务检查点、身份、汇总与中断记录。重新生成报告会先重算全部检查点与Expected Outcome判定。"]
    Path("docs/REUSE_ABLATION_RESULTS.md").write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    return {"tasks": pair["tasks"], "B0": pair["B0"]["task_success_rate"], "B3": pair["B3"]["task_success_rate"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", default="configs/reuse-ablation.json")
    print(report(parser.parse_args().plan))
