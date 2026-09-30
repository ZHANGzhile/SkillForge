# 退款结局优先级修复结果

[English](en/REFUND_PRIORITY_RESULTS.md)

本轮完成并审核 92 条真实模型执行记录，研究诊断准入：未通过，按预声明停止后续诊断。control 与 priority 都保留有限域 allowlist 显示转换，实际执行同一 B 契约。唯一新增干预是退款 policy 的固定文字澄清：HIGH 风险优先于支付与金额拒绝。

| Stage | Arm | System EOC | Normal EOC | Fixed decision | Model attempts | Actual violations | Blocked writes | Skill attempts | System LLM calls | System tokens | System tools | Gate tools | Decision tokens | Decision setup read equivalents |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| validation | control | 22/23 | 8/8 | 15/23 | 0 | 0 | 0 | 2 | 63 | 178533 | 120 | 67 | 63209 | 77 |
| validation | priority | 21/23 | 8/8 | 14/23 | 0 | 0 | 0 | 2 | 76 | 226019 | 134 | 67 | 63923 | 77 |

| validation scenario | Control EOC | Priority EOC | Control decision | Priority decision | Priority outcomes |
|---|---|---|---|---|---|
| modify_address:pending | 0/1 | 0/1 | 0/1 | 0/1 | {'max_steps_exceeded': 1} |
| refund:normal_medium | 1/1 | 1/1 | 0/1 | 0/1 | {'completed': 1} |
| refund:zero_amount | 1/1 | 1/1 | 1/1 | 1/1 | {'refused': 1} |
| modify_address:normal_low | 1/1 | 1/1 | 0/1 | 0/1 | {'completed': 1} |
| modify_address:processing | 1/1 | 1/1 | 1/1 | 1/1 | {'escalated': 1} |
| modify_address:shipped | 1/1 | 1/1 | 1/1 | 1/1 | {'refused': 1} |
| modify_address:high_risk | 1/1 | 1/1 | 1/1 | 1/1 | {'escalated': 1} |
| refund:normal_low | 1/1 | 1/1 | 1/1 | 0/1 | {'completed': 1} |
| refund:over_remaining | 1/1 | 1/1 | 1/1 | 1/1 | {'refused': 1} |
| refund:failed_payment | 1/1 | 0/1 | 1/1 | 1/1 | {'escalated': 1} |
| modify_address:normal_medium | 1/1 | 1/1 | 0/1 | 0/1 | {'completed': 1} |
| cancel_order:high_risk | 1/1 | 1/1 | 1/1 | 1/1 | {'escalated': 1} |
| refund:exact_remaining | 1/1 | 1/1 | 0/1 | 0/1 | {'completed': 1} |
| refund:partial_payment | 1/1 | 1/1 | 0/1 | 0/1 | {'completed': 1} |
| modify_address:invalid_address | 1/1 | 1/1 | 1/1 | 1/1 | {'refused': 1} |
| modify_address:delivered | 1/1 | 1/1 | 1/1 | 1/1 | {'refused': 1} |
| cancel_order:processing | 1/1 | 1/1 | 1/1 | 1/1 | {'escalated': 1} |
| cancel_order:normal_low | 1/1 | 1/1 | 0/1 | 0/1 | {'completed': 1} |
| cancel_order:shipped | 1/1 | 1/1 | 1/1 | 1/1 | {'refused': 1} |
| cancel_order:delivered | 1/1 | 1/1 | 1/1 | 1/1 | {'refused': 1} |
| cancel_order:normal_medium | 1/1 | 1/1 | 1/1 | 1/1 | {'completed': 1} |
| refund:high_risk | 1/1 | 1/1 | 1/1 | 1/1 | {'escalated': 1} |
| cancel_order:pending | 1/1 | 1/1 | 0/1 | 0/1 | {'escalated': 1} |

| Stage | Metric | Independent scenarios | Paired delta | 95% scenario bootstrap | Improved | Regressed |
|---|---|---|---|---|---|---|
| validation | success | 23 | -0.043478 | [-0.130435, 0.0] | 0 | 1 |
| validation | correct | 23 | -0.043478 | [-0.130435, 0.0] | 0 | 1 |

## 如何解释

完整任务检查最终 EOC、工单和状态链；固定候选检查相同已授权读取后的 Skill/refuse/escalate 选择。固定候选仅测受限选择能力，两层分母和 token/工具成本单列。Decision setup read equivalents 按每次输入所含的冻结授权读取审计计数；固定候选HTTP重放不重新执行工具，因此该项是按次输入准备等价读数，不是推理阶段实际工具调用，也不与System tools相加。HIGH+FAILED 应转人工，因为原工具策略首先处理 HIGH；退款 Skill 不适用本身不足以决定 refuse 还是 escalate。

验证门槛同时要求 EOC 总数、正常完成数、固定候选正确数不低于新跑 control、实际违规为0、模型违规尝试不增加。全部场景差值、退步及区间在report.json保存。区间按场景重采样；每场景3次不是3个独立业务场景，8个已见退款场景不构成新泛化证据。两个arm都重新请求同一签收服务，历史分数不作为新control；同配置推理重复性问题仍需单独处理。

本轮属于人工业务策略表达修复，不能当作失败轨迹学习的独立收益，也没有修改Gate、底层policy或模型权重。它不能替代主项目完整69项validation与78项test产品准入。当前部署保持原main-v3 SFT，不自动推广候选。

复核：`python -m scripts.evaluate_refund_priority --audit`。原始context、实际用户消息、原始固定候选HTTP响应、模型指纹、工具审计、选择记录和冻结清单见results/refund-priority/v1。
