"""Generate bilingual reports only after a complete read-only evidence audit."""
from pathlib import Path

from scripts.coordinator_io import atomic_json
from scripts.evaluate_refund_priority import prepare, run
from scripts.evaluate_reuse_ablation import read
from scripts.report_boundary_representation import markdown_table


def report():
    audit = run(audit=True)
    _, _, root, _, _, _ = prepare()
    data = read(root / "report.json")
    tables = []
    for stage, result in data["reports"].items():
        rows = []
        for arm in ("control", "priority"):
            t = result["totals"][arm]
            rows.append([stage, arm, f"{t['success']}/{t['system_runs']}", f"{t['normal_success']}/{t['normal_runs']}",
                f"{t['correct']}/{t['decision_runs']}", t["model_attempts"], t["actual_violations"], t["blocked_writes"],
                t["skill_attempts"], t["llm_calls"], t["tokens"], t["tool_calls"], t["gate_tool_calls"],
                t["decision_tokens"], t["decision_setup_tools"]])
        tables.append({"headers": ["Stage", "Arm", "System EOC", "Normal EOC", "Fixed decision", "Model attempts", "Actual violations",
            "Blocked writes", "Skill attempts", "System LLM calls", "System tokens", "System tools", "Gate tools", "Decision tokens", "Decision setup read equivalents"], "rows": rows})
    stage = "diagnostic" if "diagnostic" in data["reports"] else "validation"
    scenarios = data["reports"][stage]["scenarios"]
    table = {"headers": [stage + " scenario", "Control EOC", "Priority EOC", "Control decision", "Priority decision", "Priority outcomes"], "rows": []}
    for s in scenarios.values():
        c, p = s["control"], s["priority"]
        table["rows"].append([s["structure_id"], f"{c['success']}/{c['system_runs']}", f"{p['success']}/{p['system_runs']}",
            f"{c['correct']}/{c['decision_runs']}", f"{p['correct']}/{p['decision_runs']}", str(p["outcomes"])])
    tables.append(table)
    intervals = {"headers": ["Stage", "Metric", "Independent scenarios", "Paired delta", "95% scenario bootstrap", "Improved", "Regressed"], "rows": []}
    for stage_name, result in data["reports"].items():
        for metric, p in result["paired"].items():
            intervals["rows"].append([stage_name, metric, p["independent_scenarios"], round(p["mean_delta"], 6),
                str([round(x, 6) for x in p["ci95"]]), len(p["improved"]), len(p["regressed"])])
    tables.append(intervals)
    text = "\n\n".join(markdown_table(t) for t in tables)
    admitted = data["selection"]["admitted"]
    zh = ("# 退款结局优先级修复结果\n\n[English](en/REFUND_PRIORITY_RESULTS.md)\n\n"
        f"本轮完成并审核 {audit['runs']} 条真实模型执行记录，研究诊断准入：{'通过' if admitted else '未通过，按预声明停止后续诊断'}。"
        "control 与 priority 都保留有限域 allowlist 显示转换，实际执行同一 B 契约。唯一新增干预是退款 policy 的固定文字澄清：HIGH 风险优先于支付与金额拒绝。\n\n"
        + text + "\n\n## 如何解释\n\n"
        "完整任务检查最终 EOC、工单和状态链；固定候选检查相同已授权读取后的 Skill/refuse/escalate 选择。固定候选仅测受限选择能力，两层分母和 token/工具成本单列。"
        "Decision setup read equivalents 按每次输入所含的冻结授权读取审计计数；固定候选HTTP重放不重新执行工具，因此该项是按次输入准备等价读数，不是推理阶段实际工具调用，也不与System tools相加。"
        "HIGH+FAILED 应转人工，因为原工具策略首先处理 HIGH；退款 Skill 不适用本身不足以决定 refuse 还是 escalate。\n\n"
        "验证门槛同时要求 EOC 总数、正常完成数、固定候选正确数不低于新跑 control、实际违规为0、模型违规尝试不增加。"
        "全部场景差值、退步及区间在report.json保存。区间按场景重采样；每场景3次不是3个独立业务场景，8个已见退款场景不构成新泛化证据。"
        "两个arm都重新请求同一签收服务，历史分数不作为新control；同配置推理重复性问题仍需单独处理。\n\n"
        "本轮属于人工业务策略表达修复，不能当作失败轨迹学习的独立收益，也没有修改Gate、底层policy或模型权重。"
        "它不能替代主项目完整69项validation与78项test产品准入。当前部署保持原main-v3 SFT，不自动推广候选。\n\n"
        "复核：`python -m scripts.evaluate_refund_priority --audit`。原始context、实际用户消息、原始固定候选HTTP响应、模型指纹、工具审计、选择记录和冻结清单见results/refund-priority/v1。\n")
    en = ("# Refund outcome precedence repair\n\n[中文](../REFUND_PRIORITY_RESULTS.md)\n\n"
        f"Completed and audited {audit['runs']} real-model execution records. Research diagnostic admission: {'passed' if admitted else 'rejected; subsequent diagnostics stopped as declared'}. "
        "Both control and priority retain the bounded allowlist display repair and execute the same B contract. The only additional intervention is a fixed refund-policy clarification: HIGH risk takes precedence over payment/amount refusal.\n\n"
        + text + "\n\n## Interpretation\n\n"
        "Full-system evaluation verifies terminal EOC, tickets and state chains. Fixed-candidate probes check Skill/refuse/escalate choices after identical authorized reads. "
        "They measure constrained selection, with separate denominators and costs. Decision setup read equivalents allocate the frozen authorized-read audit to each probe; HTTP replay does not re-execute tools. "
        "These are per-input setup equivalents, not actual inference-time tool calls, and are not added to System tools. HIGH+FAILED requires escalation under the existing tool policy; Skill inapplicability alone does not select the terminal outcome.\n\n"
        "The validation gate requires no aggregate regression in EOC, normal completion or fixed-candidate correctness, zero actual violations and no increase in model violation attempts. "
        "All scenario gains, regressions and intervals are retained in report.json. Bootstrap resamples business scenarios, not individual repeats. "
        "The eight previously seen refund scenarios provide diagnostic evidence, not a fresh generalization test. Both arms make new requests to the same pinned service; historical scores are not reused. "
        "Previously observed action variability under identical recorded settings remains a separate limitation.\n\n"
        "This is a manually authored business-policy expression repair, not an independent boundary-learning gain. Gate, tool policy and model weights remain unchanged. "
        "It does not replace the main project's 69-case validation and 78-case test product admission. Deployment remains the original main-v3 SFT.\n\n"
        "Audit: `python -m scripts.evaluate_refund_priority --audit`. Original contexts, actual user messages, raw fixed-candidate HTTP responses, fingerprints, tool audits, selection and freeze manifests are in results/refund-priority/v1.\n")
    Path("docs/REFUND_PRIORITY_RESULTS.md").write_text(zh, encoding="utf-8")
    Path("docs/en/REFUND_PRIORITY_RESULTS.md").write_text(en, encoding="utf-8")
    atomic_json(root / "workbench.json", {"boundary_tables": tables, "audit": audit,
        "scope": "Manual outcome-policy expression repair; known synthetic scenarios; not a boundary-learning gain or production deployment."})
    return audit


if __name__ == "__main__":
    print(report())
