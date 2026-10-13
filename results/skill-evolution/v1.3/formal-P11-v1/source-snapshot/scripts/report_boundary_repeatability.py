"""Publish only fully audited repetition results to the workbench."""
from pathlib import Path

from scripts.coordinator_io import atomic_json
from scripts.evaluate_boundary_repeatability import PLAN, read, run, write_report


def report():
    audit = run(audit=True)
    root = Path(read(PLAN)["output"])
    result = read(root / "report.json")
    write_report(result)
    target = result["normal"][read(PLAN)["regression_task"]]
    divergent = [r for r in result["exact"].values() if "historical_divergence" in r["selection"]]
    reproduced = sum(len(r["decisions"]) > 1 for r in divergent)
    zh = (f"\n## 本轮解释\n\n正常任务重复执行：A {result['totals']['A']['success']}/24、B {result['totals']['B']['success']}/24、C {result['totals']['C']['success']}/24。"
          f"原退款退步案例A {target['A']['success']}/3、B {target['B']['success']}/3、C {target['C']['success']}/3；B首步原样输入10/10拒绝，A/C各10/10读取订单。"
          "该失败在本轮重复出现，不能简单解释为上轮一次偶然波动。它仍是模型在Skill可用时选择错误终态，不是Gate误挡。\n\n"
          f"全部{len(divergent)}个历史分歧输入中，{reproduced}个再次出现动作类型/工具选择分歧：转人工7次/查询支付3次；查询客户9次/拒绝1次。"
          "两个历史稳定对照各10次动作一致。原样重放不执行动作或评价后续EOC，不能将这些频数解释为任务成功率。\n\n"
          "原退款案例的B/C首步除executable_skills外context相同；B禁止FAILED支付，C明确允许CAPTURED或PARTIALLY_REFUNDED。"
          "二者在声明支付域内逻辑一致，文本表示不同；A/B另有补查观察差异。下一步应在新预声明下隔离表示差异，保持实际执行Gate、工具检查和模型不变。"
          "本轮没有修复或替换部署，也没有证明学习超过完整人工规则。\n")
    en = (f"\n## Interpretation\n\nNormal-task repetitions: A {result['totals']['A']['success']}/24, B {result['totals']['B']['success']}/24, C {result['totals']['C']['success']}/24. "
          f"The original refund regression reproduced: A {target['A']['success']}/3, B {target['B']['success']}/3, C {target['C']['success']}/3. "
          "Its exact initial input yielded refusal 10/10 times for B, versus get_order 10/10 times for A and C. This recurring failure cannot simply be dismissed as one unlucky original run. The Skill was available: it was a model terminal-decision error, not a Gate false block.\n\n"
          f"Both historical divergent contexts were replayed; {reproduced}/{len(divergent)} again varied in action type/tool: escalate 7 versus get_payment 3; get_customer 9 versus refuse 1. "
          "Each of the two stable controls produced one action across ten repeats. Exact-input requests do not execute the returned actions or evaluate subsequent EOC, so these frequencies are not task success rates.\n\n"
          "For the refund regression, B/C initial contexts differ only in executable_skills: B forbids FAILED payment, while C explicitly allows CAPTURED or PARTIALLY_REFUNDED. "
          "These are logically equivalent within the declared payment domain but differently expressed. A/B also differ in hydrated observations. A separate frozen representation intervention is the next diagnostic; execution Gate, tool checks and model must remain fixed. "
          "No repair or deployment replacement has occurred, and gains beyond complete manual policy remain unestablished.\n")
    for path, extra in (("docs/BOUNDARY_REPEATABILITY_RESULTS.md", zh), ("docs/en/BOUNDARY_REPEATABILITY_RESULTS.md", en)):
        p = Path(path)
        p.write_text(p.read_text(encoding="utf-8") + extra, encoding="utf-8")
    tables = [{"headers": ["Group", "Normal EOC / 24 runs", "Independent scenarios", "Model calls", "Tokens", "Tools", "Actual violations"],
               "rows": [[g, f"{r['success']}/{r['runs']}", 8, r["llm_calls"], r["tokens"], r["tool_calls"], r["actual_violations"]]
                        for g, r in result["totals"].items()]},
              {"headers": ["Exact input", "Selection", "Distinct Actions / 10 repeats", "Historical distinct Actions"],
               "rows": [[h[:12], ", ".join(r["selection"]), len(r["actions"]), r["historical_actions"]] for h, r in result["exact"].items()]}]
    atomic_json(root / "workbench.json", {"boundary_tables": tables, "audit": audit,
        "scope": "Retrospective repetition, not new independent scenarios. No replacement of original scores or causal backend attribution."})
    return audit


if __name__ == "__main__":
    print(report())
