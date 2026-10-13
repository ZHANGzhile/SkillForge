"""Generate the retrospective report only from fully audited paired evidence."""
import argparse
from pathlib import Path

from scripts.evaluate_reuse_ablation import audit, read
from scripts.coordinator_io import atomic_json
from skillforge.training_data import file_hash
from skillforge.policies import MUTATIONS


def report(plan_path="configs/reuse-ablation.json"):
    result = audit(plan_path)
    pair = result["paired"]
    plan = read(plan_path)
    controls = []
    policy_events = {"B0": [], "B3": []}
    for row in pair["cases"]:
        left = read(Path(plan["output"]) / "tasks" / (row["task_id"] + ".json"))
        right = read(Path(plan["reference"]) / "tasks" / (row["task_id"] + ".json"))
        for label, record in (("B0", left), ("B3", right)):
            for event in record["tool_audit"]:
                if event.get("attempted_policy_violation"):
                    policy_events[label].append({"task_id": row["task_id"], "tool": event["tool_name"],
                        "error": event["error"], "origin": event.get("decision_origin"),
                        "mutation": event["tool_name"] in MUTATIONS, "state_changed": bool(event["state_diff"]),
                        "eoc_passed": record["verification"]["task_success"]})
        if left["steps"] and right["steps"] and left["steps"][0]["context"] == right["steps"][0]["context"]:
            controls.append({"task_id": row["task_id"], "family": row["family"],
                "same_actions": [s.get("action") for s in left["steps"]] == [s.get("action") for s in right["steps"]],
                "same_outcome": left["outcome"] == right["outcome"], "same_eoc": row["b0_passed"] == row["b3_passed"]})
    control_report = {"scope": "Descriptive consistency for exactly equal initial model contexts; not a new randomized experiment or speed comparison",
        "reporter_sha256": file_hash(__file__), "cases": controls}
    atomic_json(Path(plan["output"]) / "transport-controls.json", control_report)
    atomic_json(Path(plan["output"]) / "policy-attempts.json", {
        "scope": "Post-hoc descriptive decomposition of frozen attempted-policy-violation evidence; does not redefine EOC",
        "reporter_sha256": file_hash(__file__), "events": policy_events})
    lines = ["# main-v3 同模型无Skill对照", "",
        "固定同一SFT权重、system prompt、任务初态及工具政策，覆盖全部78个已冻结新实例test。该test此前已被查看，本实验是事后系统消融，不用于训练或部署选优。", "",
        "| 指标 | B0（无Skill） | B3（冻结Skill） |", "|---|---:|---:|"]
    for key, title in (("task_success_rate", "EOC合格率"), ("average_llm_calls", "平均LLM调用"),
                       ("average_tool_calls", "平均工具调用"), ("average_tokens", "平均token"),
                       ("skill_reuse_attempts", "Skill调用"), ("model_attempted_policy_violation_rate", "模型违规尝试率"),
                       ("automatic_gate_violation_attempt_rate", "自动Gate权限尝试率"),
                       ("attempted_policy_violation_rate", "总违规尝试率（旧口径）"),
                       ("actual_policy_violation_rate", "实际违规率")):
        values = [f"{pair[label][key]:.2%}" if key.endswith("_rate") else
                  str(pair[label][key]) if key == "skill_reuse_attempts" else f"{pair[label][key]:.4f}" for label in ("B0", "B3")]
        lines.append(f"| {title} | {values[0]} | {values[1]} |")
    lines += ["", f"合格任务数：B0 {sum(r['b0_passed'] for r in pair['cases'])}/{pair['tasks']}；B3 {sum(r['b3_passed'] for r in pair['cases'])}/{pair['tasks']}。",
        "", "调用/token成本包含失败任务，不仅统计成功案例；自动Gate和Skill内部工具调用也计入。以下为整个配置的成本差异，不是纯执行器收益：", ""]
    for key, title in (("average_llm_calls", "平均LLM调用"), ("average_tool_calls", "平均工具调用"), ("average_tokens", "平均token")):
        base = pair["B0"][key]
        if base:
            change = (pair["B3"][key] - base) / base
            lines.append(f"- {title}相对B0{'增加' if change > 0 else '减少'} {abs(change):.2%}。")
    lines += ["", "## 按任务族分解", "", "| 任务族 | B0合格/总数 | B3合格/总数 | 改善 | 退步 |", "|---|---:|---:|---:|---:|"]
    for family in sorted({row["family"] for row in pair["cases"]}):
        rows = [row for row in pair["cases"] if row["family"] == family]
        lines.append(f"| {family} | {sum(r['b0_passed'] for r in rows)}/{len(rows)} | {sum(r['b3_passed'] for r in rows)}/{len(rows)} | {sum(r['b3_helped'] for r in rows)} | {sum(r['b3_harmed'] for r in rows)} |")
    lines += ["", f"逐任务配对：启用Skill的B3相对B0改善{pair['paired_improvements']}例、退步{pair['paired_regressions']}例。",
        "", f"全任务分母的系统退步率：{pair['skill_enabled_system_regression_rate']:.2%}；B0成功条件下的退步率：{format(pair['regression_given_b0_success'], '.2%') if pair['regression_given_b0_success'] is not None else 'null'}。",
        "", f"退步且实际尝试Skill的任务：{pair['regressions_with_observed_skill_attempt']}。这仍是关联描述；same-context causal NTR保持null。",
        "", "B0移除Skill候选，也同时取消自动Gate补读，因此初始可见状态与后续决策上下文会改变。差值属于整个系统配置的影响，不能全部归因于Skill执行器。B0经真实HTTP服务，B3复用同身份的直接HF检查点；不据此声称严格延迟加速或统计显著性。",
        "", "权限读取失败也属于现有attempted_policy_violation口径。B0中的读取由模型发起，B3中同一检查可能由自动Gate发起；归因变化不等于非法写入倾向增加。须结合总尝试、具体工具审计和实际违规共同解释。",
        "", "成本分母为完整保存并审核的逻辑任务轨迹；未保存的中断请求开销不在其中，因此这些数字不是含服务启动和中断浪费的总运营成本。恢复事件另存resume-*.json；恢复路径复核并复用已完成任务，不通过重跑挑选更好答案。",
        "", "## 原B3失败自动归类", "", "| 证据类型 | 任务数 |", "|---|---:|"]
    for kind, count in sorted(pair["b3_failure_counts"].items()):
        lines.append(f"| {kind} | {count} |")
    lines += ["", "## 违规尝试的事后分解", "", "| 组别 | 被拦截写操作次数 | 其他违规尝试次数 | 曾尝试违规但最终EOC合格的任务 |", "|---|---:|---:|---:|"]
    for label, events in policy_events.items():
        lines.append(f"| {label} | {sum(e['mutation'] for e in events)} | {sum(not e['mutation'] for e in events)} | {len({e['task_id'] for e in events if e['eoc_passed']})} |")
    lines += ["", "EOC检查预期终态与证据，不会自动把所有被工具拦截的尝试都改判任务失败。最终正确拒绝可能发生在一次错误写入尝试之后。此表补充解释既有安全指标，不修改冻结的成功定义；任务、工具、错误、发起者和状态变化详见policy-attempts.json。"]
    lines += ["", "## 所有改善、退步及原B3失败的逐任务对照", "", "| task ID | 任务族 | B0合格 | B3合格 | B3 Skill次数 | B0证据类型 | B3证据类型 |", "|---|---|---|---|---:|---|---|"]
    for row in pair["cases"]:
        if not row["b3_passed"] or row["b3_helped"]:
            lines.append(f"| {row['task_id']} | {row['family']} | {row['b0_passed']} | {row['b3_passed']} | {row['b3_skill_attempts']} | {row['b0_failure_kind'] or '—'} | {row['b3_failure_kind'] or '—'} |")
    lines += ["", "## 相同起始输入的一致性检查", "",
        f"{len(controls)}例具有完全相同的首个模型context；其中动作序列相同{sum(c['same_actions'] for c in controls)}例、结局相同{sum(c['same_outcome'] for c in controls)}例、EOC判定相同{sum(c['same_eoc'] for c in controls)}例。详细任务见transport-controls.json。该检查帮助观察服务路径差异，不证明所有后续上下文或延迟完全相同。",
        "", "证据：configs/reuse-ablation.json预声明范围；results/reuse-ablation/main-v3包含逐任务检查点、身份、汇总与中断记录。重新生成报告会先重算全部检查点与Expected Outcome判定。"]
    Path("docs/REUSE_ABLATION_RESULTS.md").write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    return {"tasks": pair["tasks"], "B0": pair["B0"]["task_success_rate"], "B3": pair["B3"]["task_success_rate"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", default="configs/reuse-ablation.json")
    print(report(parser.parse_args().plan))
