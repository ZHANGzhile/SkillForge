"""Publish audited v2 diagnosis without rewriting the rejected v1 report."""
from pathlib import Path

from scripts.coordinator_io import atomic_json
from scripts.evaluate_refund_priority_scoped import prepare, run
from scripts.evaluate_reuse_ablation import read
from scripts.report_boundary_representation import markdown_table


def report():
    audit = run(audit=True)
    _, _, root, _, _, freeze = prepare()
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
    table = {"headers": [stage + " scenario", "Control EOC", "Priority EOC", "Control decision", "Priority decision", "Priority outcomes"], "rows": []}
    for s in data["reports"][stage]["scenarios"].values():
        c, p = s["control"], s["priority"]
        table["rows"].append([s["structure_id"], f"{c['success']}/{c['system_runs']}", f"{p['success']}/{p['system_runs']}",
            f"{c['correct']}/{c['decision_runs']}", f"{p['correct']}/{p['decision_runs']}", str(p["outcomes"])])
    tables.append(table)
    intervals = {"headers": ["Stage", "Metric", "Independent scenarios", "Paired delta", "95% scenario bootstrap", "Improved", "Regressed"], "rows": []}
    for name, result in data["reports"].items():
        for metric, p in result["paired"].items():
            intervals["rows"].append([name, metric, p["independent_scenarios"], round(p["mean_delta"], 6),
                str([round(x, 6) for x in p["ci95"]]), len(p["improved"]), len(p["regressed"])])
    tables.append(intervals)
    text = "\n\n".join(markdown_table(t) for t in tables)
    admitted = data["selection"]["admitted"]
    target = next((s for s in data["reports"].get("diagnostic", {}).get("scenarios", {}).values() if s["structure_id"] == "refund:risk_failed"), None)
    if target:
        c, p = target["control"], target["priority"]
        target_zh = (f"HIGH+FAILED目标：完整EOC {c['success']}/{c['system_runs']}→{p['success']}/{p['system_runs']}；固定候选 {c['correct']}/{c['decision_runs']}→{p['correct']}/{p['decision_runs']}。"
            f"该场景完整任务模型调用 {c['llm_calls']}→{p['llm_calls']}、token {c['tokens']}→{p['tokens']}、工具 {c['tool_calls']}→{p['tool_calls']}、Gate查询 {c['gate_tool_calls']}→{p['gate_tool_calls']}。")
        target_en = (f"HIGH+FAILED target: full EOC {c['success']}/{c['system_runs']}→{p['success']}/{p['system_runs']}; fixed decision {c['correct']}/{c['decision_runs']}→{p['correct']}/{p['decision_runs']}. "
            f"Target full-system calls {c['llm_calls']}→{p['llm_calls']}, tokens {c['tokens']}→{p['tokens']}, tools {c['tool_calls']}→{p['tool_calls']}, Gate queries {c['gate_tool_calls']}→{p['gate_tool_calls']}. ")
    else:
        target_zh, target_en = "后续诊断未获准入，没有目标修复结论。", "Subsequent diagnostics were not admitted; no target-repair conclusion is available. "
    zh = ("# HIGH观察限定的退款优先级v2结果\n\n[English](en/REFUND_PRIORITY_SCOPED_RESULTS.md)\n\n"
        f"完成并审核 {audit['runs']} 条真实模型记录；退款研究准入{'通过' if admitted else '未通过'}。" + target_zh + "\n\n"
        "v1在全部退款输入追加同一提示后，完整validation 22/23→21/23、固定候选15/23→14/23，因此被拒绝。"
        "v2是观察到该失败后的新候选，只在已授权observations明确给出HIGH风险且family=refund时加入原澄清文本。control和priority都保留allowlist显示修复，实际执行同一B。\n\n"
        + text + "\n\n## 范围与归因\n\n"
        "v2只验证全部8个退款validation场景，两臂双评测共32条；它与v1的23场景分母不同，不能把两个总分直接作改善比较。两臂全部新跑，未复用v1 control。"
        "175种枚举组合中仅5种激活；v1真实185个原context中181个逐字不变、4个激活。其他任务族没有新模型回归成绩；逐字不变检查仅证明显示干预不触及它们。\n\n"
        "完整任务按EOC和状态链验收，固定候选仅测Skill/refuse/escalate受限选择。setup read equivalents来自冻结输入的授权读取审计，HTTP重放不重新调用工具，不能与System tools实际调用相加。"
        "正常完成、决策、违规尝试与成本同时报告，所有逐场景退步均保留。bootstrap按8个业务场景重采样；每场景3次不是24个独立场景，区间包含0时不能声称总体可靠提升。\n\n"
        "本次总体模型调用68→66、token191493→186706，但两次少调用全部来自没有激活提示的zero_amount场景（11→9次），不能归因于本提示节省调用。"
        "目标HIGH+FAILED自身仍是3→3次模型调用，token6999→7293，工具6→9，增加的是三次正确转人工写入；三组HIGH场景的提示均增加token。"
        "系统总工具110→111、Gate查询均42。未改变输入的场景仍有执行长度差异，延续了先前的重复性限制。\n\n"
        "这是人工已知policy的条件显示修复，不是从失败轨迹学出新规则，也不修改Gate或模型Action。用户是否正确转人工仍由真实模型决定；包装器不自动纠错。"
        "此前已见test用于诊断，不是新独立泛化证据。未替换main-v3部署，未消除主项目10个test失败或PENDING地址读循环，也不替代69项validation与78项test的产品准入。\n\n"
        "审核：`python -m scripts.evaluate_refund_priority_scoped --audit`。独立结果：results/refund-priority/v2；v1失败证据完整保留。\n")
    en = ("# HIGH-observation-scoped refund priority, v2\n\n[中文](../REFUND_PRIORITY_SCOPED_RESULTS.md)\n\n"
        f"Completed and audited {audit['runs']} real-model records; refund research admission {'passed' if admitted else 'rejected'}. " + target_en + "\n\n"
        "The v1 clarification was appended to every refund input and was rejected: validation EOC 22/23→21/23 and fixed decisions 15/23→14/23. "
        "V2 is a new candidate designed after that failure. It adds the same text only when authorized observations already contain HIGH risk and the family is refund. Both arms retain the allowlist view and execute unchanged B.\n\n"
        + text + "\n\n## Scope and attribution\n\n"
        "V2 validates all eight refund validation scenarios, yielding 32 records across two arms and evaluation levels. This denominator differs from v1's 23 scenarios; their aggregate scores are not directly comparable. "
        "Both arms make new requests. Of 175 enumerated combinations, only five activate the clarification; of 185 original v1 contexts, 181 remain byte-identical and four activate it. "
        "Other task families have no new model regression scores; input identity proves only that the display intervention does not touch them.\n\n"
        "Full tasks are checked against EOC and state chains. Fixed candidates measure constrained Skill/refuse/escalate selection. Setup read equivalents allocate the frozen authorized-read audit per input; HTTP replay does not execute these tools. "
        "They are not added to actual system tool calls. Normal completion, decisions, violation attempts, costs and every scenario regression are retained. Bootstrap resamples eight business scenarios, not 24 independent repetitions; an interval including zero cannot support a reliable population improvement.\n\n"
        "Total model calls fell 68→66 and tokens 191493→186706, but both fewer calls came from zero_amount (11→9), where the clarification never activates. This does not establish prompt-induced efficiency. "
        "The HIGH+FAILED target itself used 3→3 calls, tokens6999→7293 and tools6→9: three additional, required escalation writes. All three HIGH scenarios incur additional prompt tokens. "
        "Total system tools were110→111 and Gate queries42 in both arms. Execution-length variation in an unchanged-input scenario preserves the earlier repeatability limitation.\n\n"
        "This is a conditional display repair of manually known policy, not a learned new rule. Gate and model Actions are unchanged; the real model still selects escalation. "
        "Previously seen test cases provide diagnostics, not independent generalization evidence. Main-v3 deployment, its ten held-out failures and the PENDING-address read loop are not replaced or resolved by this experiment. "
        "It does not substitute for the main 69-case validation and 78-case test product gate.\n\n"
        "Audit: `python -m scripts.evaluate_refund_priority_scoped --audit`. Evidence is isolated in results/refund-priority/v2; all rejected v1 evidence remains available.\n")
    Path("docs/REFUND_PRIORITY_SCOPED_RESULTS.md").write_text(zh, encoding="utf-8")
    Path("docs/en/REFUND_PRIORITY_SCOPED_RESULTS.md").write_text(en, encoding="utf-8")
    atomic_json(root / "workbench.json", {"boundary_tables": tables, "audit": audit,
        "activation_proof": freeze["activation_proof"], "source_input_proof": freeze["source_input_proof"],
        "scope": "V2 after rejected v1; refund-only research admission; manual conditional policy display, not boundary learning or deployment."})
    return audit


if __name__ == "__main__":
    print(report())
