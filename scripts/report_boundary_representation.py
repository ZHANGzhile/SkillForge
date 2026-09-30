"""Bilingual report from audited, completed model-view intervention records."""
import json
from pathlib import Path

from scripts.coordinator_io import atomic_json
from scripts.evaluate_boundary_representation import PLAN, prepare, run
from scripts.evaluate_reuse_ablation import read


def markdown_table(table):
    return "\n".join(["| " + " | ".join(table["headers"]) + " |", "|" + "---|" * len(table["headers"]),
                      *["| " + " | ".join(str(v).replace("|", "\\|") for v in row) + " |" for row in table["rows"]]])


def report():
    audit = run(audit=True)
    plan, _, root, tasks, _, frozen = prepare()
    data = read(root / "report.json")
    totals = {"headers": ["Arm", "EOC / runs", "Normal EOC / runs", "Blocked writes", "Actual violations", "Skill attempts", "Model calls", "Tokens", "Tools", "Gate tools"],
              "rows": [[a, f"{r['success']}/{r['runs']}", f"{r['normal_success']}/{r['normal_runs']}", r["blocked_writes"], r["actual_violations"],
                        r["skill_attempts"], r["llm_calls"], r["tokens"], r["tool_calls"], r["gate_tool_calls"]] for a, r in data["totals"].items()]}
    scenarios = {"headers": ["Scenario", "Normal", "Original EOC", "Allowlist view EOC", "Success count delta"],
                 "rows": [[tasks[tid].structure_id, v["original"]["normal"], f"{v['original']['success']}/{v['original']['runs']}",
                           f"{v['allowlist_view']['success']}/{v['allowlist_view']['runs']}", data["scenario_deltas"][tid]] for tid, v in data["system"].items()]}
    decisions = {"headers": ["Scenario", "Arm", "Action type/tool frequencies"],
                 "rows": [[tasks[tid].structure_id, a, json.dumps(r["decisions"], ensure_ascii=False)] for tid, arms in data["exact"].items() for a, r in arms.items()]}
    tables = [totals, scenarios, decisions]
    target = "boundary-27c1d37b2f12d9fd9b18"
    target_system, target_exact = data["system"][target], data["exact"][target]
    target_outcomes = " → ".join(f"{target_system[a]['success']}/{target_system[a]['runs']}" for a in plan["arms"])
    target_actions = " → ".join(json.dumps(target_exact[a]["decisions"], ensure_ascii=False) for a in plan["arms"])
    up = sum(v > 0 for v in data["scenario_deltas"].values())
    down = sum(v < 0 for v in data["scenario_deltas"].values())
    common = "\n\n".join(markdown_table(t) for t in tables)
    zh = ("# 退款边界表达对照结果\n\n[English](en/BOUNDARY_REPRESENTATION_RESULTS.md)\n\n"
          f"完成{audit['runs']}项：80次首步原样决策、48次完整任务。两臂实际执行原B契约，只有模型可见支付条件的表达/位置不同。"
          "已知域内转换；缺失或域外状态（含REFUNDED）保留原文。没有重训或更换部署。\n\n"
          f"原退款退步场景完整EOC（原文 → 显示转换）：**{target_outcomes}**；原样首步频数：`{target_actions}`。"
          f"8个场景中，成功次数增加{up}个、减少{down}个，其余不变。\n\n" + common + "\n\n"
          f"退款目标案例的Skill尝试为{target_system['original']['skill_attempts']}→{target_system['allowlist_view']['skill_attempts']}；"
          "成功路径使用普通工具，因此改善不能归为Skill程序本身省调用。其余场景成功次数未变，高风险叠加支付失败仍为两臂0/3。"
          "两臂总模型调用66→68、token183528→191509、工具90→110；原文快速拒绝包含失败，不可把较低成本直接称为更高效率。\n\n"
          "## 证据与解释边界\n\n"
          f"{frozen['equivalence']['checked']}个枚举观察状态的三态一致性通过；两臂所有完整任务起点的SQLite、故障队列及原B补查后context逐字一致。"
          "实际发送字符串单独保存并逐项重建核对，不能用干预前context冒充模型输入。后续历史因动作和环境交易UUID而自然分叉。\n\n"
          "每臂24次完整运行是8个场景各3次，其中正常场景4个各3次；不是24个独立业务样本。动作频数来自4个已有上下文各10次，不能解释为完整任务成功率。"
          "本轮包含条件位置、否定/肯定与eq/in表达的整体变化，没有逐项拆开，不能定位到单一词或算子。"
          "本次退款改善支持该上下文对显示表示敏感；仍不证明底层推理确定性、总体泛化、从轨迹发现新规则或学习优于完整规则。"
          "若负向场景也发生差异，应同时查看该场景模型可见契约是否为空，不能一概归因于转换。\n\n"
          "CPU审核：`python -m scripts.evaluate_boundary_representation --audit`。原始检查点及freeze/report保存在results/boundary-representation/v1。\n")
    en = ("# Refund boundary representation intervention\n\n[中文](../BOUNDARY_REPRESENTATION_RESULTS.md)\n\n"
          f"Completed {audit['runs']} executions: 80 exact initial decisions and 48 full tasks. Both arms execute the original B contract; only the displayed payment condition syntax/order changes. "
          "Transformation is restricted to the observed declared domain; missing or other states, including REFUNDED, retain the original view. No training or deployment replacement.\n\n"
          f"The original refund regression's full EOC (original → allowlist view): **{target_outcomes}**; exact first-action frequencies: `{target_actions}`. "
          f"Across eight scenarios, success counts increased in {up}, decreased in {down}, and otherwise stayed unchanged.\n\n" + common + "\n\n"
          f"Skill attempts in the target refund case: {target_system['original']['skill_attempts']}→{target_system['allowlist_view']['skill_attempts']}. "
          "Its successful continuation uses primitive tools, so this is not an execution-encapsulation saving. Other scenarios have unchanged success counts; HIGH risk with FAILED payment remains 0/3 in both arms. "
          "Total model calls rise 66→68, tokens 183528→191509 and tools 90→110. Fast refusal includes failures and is not inherently more efficient.\n\n"
          "## Evidence and limits\n\n"
          f"All {frozen['equivalence']['checked']} enumerated observation states preserve three-valued applicability. Initial SQLite/fault snapshots and original B contexts after hydration match exactly across arms. "
          "Actual user-message strings are stored separately and reconstructed during audit. Subsequent histories naturally diverge with actions and generated transaction UUIDs.\n\n"
          "Each arm's 24 full runs represent eight scenarios repeated three times, including four normal scenarios repeated three times. Repeats are not independent business examples. "
          "The four exact-input contexts are each requested ten times per arm; their Action frequencies are not full-task success rates. "
          "The intervention changes condition position, negative/positive wording and eq/in together, so no individual token or operator is causally isolated. "
          "The observed refund improvement supports local representation sensitivity, not deterministic serving, population generalization, novel-rule learning or gains beyond complete manual policy. "
          "Negative-scenario differences also require checking whether the visible contract was empty, in which case no transformation occurred.\n\n"
          "CPU audit: `python -m scripts.evaluate_boundary_representation --audit`. Frozen protocol, checkpoints and report: results/boundary-representation/v1.\n")
    Path("docs/BOUNDARY_REPRESENTATION_RESULTS.md").write_text(zh, encoding="utf-8")
    Path("docs/en/BOUNDARY_REPRESENTATION_RESULTS.md").write_text(en, encoding="utf-8")
    atomic_json(root / "workbench.json", {"boundary_tables": tables, "audit": audit,
        "scope": "Retrospective refund-only model-view intervention. Execution B and tool checks unchanged; repeats are not independent scenarios; deployment unchanged."})
    return audit


if __name__ == "__main__":
    print(report())
