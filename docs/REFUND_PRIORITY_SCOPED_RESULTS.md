# HIGH观察限定的退款优先级v2结果

[English](en/REFUND_PRIORITY_SCOPED_RESULTS.md)

完成并审核 128 条真实模型记录；退款研究准入通过。HIGH+FAILED目标：完整EOC 0/3→3/3；固定候选 0/3→3/3。该场景完整任务模型调用 3→3、token 6999→7293、工具 6→9、Gate查询 6→6。

v1在全部退款输入追加同一提示后，完整validation 22/23→21/23、固定候选15/23→14/23，因此被拒绝。v2是观察到该失败后的新候选，只在已授权observations明确给出HIGH风险且family=refund时加入原澄清文本。control和priority都保留allowlist显示修复，实际执行同一B。

| Stage | Arm | System EOC | Normal EOC | Fixed decision | Model attempts | Actual violations | Blocked writes | Skill attempts | System LLM calls | System tokens | System tools | Gate tools | Decision tokens | Decision setup read equivalents |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| validation | control | 8/8 | 4/4 | 5/8 | 0 | 0 | 0 | 2 | 23 | 64442 | 36 | 14 | 21963 | 24 |
| validation | priority | 8/8 | 4/4 | 5/8 | 0 | 0 | 0 | 2 | 23 | 64537 | 36 | 14 | 22056 | 24 |

| Stage | Arm | System EOC | Normal EOC | Fixed decision | Model attempts | Actual violations | Blocked writes | Skill attempts | System LLM calls | System tokens | System tools | Gate tools | Decision tokens | Decision setup read equivalents |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| diagnostic | control | 21/24 | 12/12 | 12/24 | 0 | 0 | 0 | 6 | 68 | 191493 | 110 | 42 | 66009 | 72 |
| diagnostic | priority | 24/24 | 12/12 | 15/24 | 0 | 0 | 0 | 6 | 66 | 186706 | 111 | 42 | 66861 | 72 |

| diagnostic scenario | Control EOC | Priority EOC | Control decision | Priority decision | Priority outcomes |
|---|---|---|---|---|---|
| refund:normal_low | 3/3 | 3/3 | 3/3 | 3/3 | {'completed': 3} |
| refund:partial_payment | 3/3 | 3/3 | 0/3 | 0/3 | {'completed': 3} |
| refund:normal_medium | 3/3 | 3/3 | 0/3 | 0/3 | {'completed': 3} |
| refund:shipped_partial | 3/3 | 3/3 | 0/3 | 0/3 | {'completed': 3} |
| refund:risk_failed | 0/3 | 3/3 | 0/3 | 3/3 | {'escalated': 3} |
| refund:risk_over | 3/3 | 3/3 | 3/3 | 3/3 | {'escalated': 3} |
| refund:zero_amount | 3/3 | 3/3 | 3/3 | 3/3 | {'refused': 3} |
| refund:high_risk | 3/3 | 3/3 | 3/3 | 3/3 | {'escalated': 3} |

| Stage | Metric | Independent scenarios | Paired delta | 95% scenario bootstrap | Improved | Regressed |
|---|---|---|---|---|---|---|
| validation | success | 8 | 0.0 | [0.0, 0.0] | 0 | 0 |
| validation | correct | 8 | 0.0 | [0.0, 0.0] | 0 | 0 |
| diagnostic | success | 8 | 0.125 | [0.0, 0.375] | 1 | 0 |
| diagnostic | correct | 8 | 0.125 | [0.0, 0.375] | 1 | 0 |

## 范围与归因

v2只验证全部8个退款validation场景，两臂双评测共32条；它与v1的23场景分母不同，不能把两个总分直接作改善比较。两臂全部新跑，未复用v1 control。175种枚举组合中仅5种激活；v1真实185个原context中181个逐字不变、4个激活。其他任务族没有新模型回归成绩；逐字不变检查仅证明显示干预不触及它们。

完整任务按EOC和状态链验收，固定候选仅测Skill/refuse/escalate受限选择。setup read equivalents来自冻结输入的授权读取审计，HTTP重放不重新调用工具，不能与System tools实际调用相加。正常完成、决策、违规尝试与成本同时报告，所有逐场景退步均保留。bootstrap按8个业务场景重采样；每场景3次不是24个独立场景，区间包含0时不能声称总体可靠提升。

本次总体模型调用68→66、token191493→186706，但两次少调用全部来自没有激活提示的zero_amount场景（11→9次），不能归因于本提示节省调用。目标HIGH+FAILED自身仍是3→3次模型调用，token6999→7293，工具6→9，增加的是三次正确转人工写入；三组HIGH场景的提示均增加token。系统总工具110→111、Gate查询均42。未改变输入的场景仍有执行长度差异，延续了先前的重复性限制。

这是人工已知policy的条件显示修复，不是从失败轨迹学出新规则，也不修改Gate或模型Action。用户是否正确转人工仍由真实模型决定；包装器不自动纠错。此前已见test用于诊断，不是新独立泛化证据。未替换main-v3部署，未消除主项目10个test失败或PENDING地址读循环，也不替代69项validation与78项test的产品准入。

审核：`python -m scripts.evaluate_refund_priority_scoped --audit`。独立结果：results/refund-priority/v2；v1失败证据完整保留。
