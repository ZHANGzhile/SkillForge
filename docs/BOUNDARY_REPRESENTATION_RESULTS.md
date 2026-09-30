# 退款边界表达对照结果

[English](en/BOUNDARY_REPRESENTATION_RESULTS.md)

完成128项：80次首步原样决策、48次完整任务。两臂实际执行原B契约，只有模型可见支付条件的表达/位置不同。已知域内转换；缺失或域外状态（含REFUNDED）保留原文。没有重训或更换部署。

原退款退步场景完整EOC（原文 → 显示转换）：**0/3 → 3/3**；原样首步频数：`{"refuse:": 10} → {"tool:get_order": 10}`。8个场景中，成功次数增加1个、减少0个，其余不变。

| Arm | EOC / runs | Normal EOC / runs | Blocked writes | Actual violations | Skill attempts | Model calls | Tokens | Tools | Gate tools |
|---|---|---|---|---|---|---|---|---|---|
| original | 18/24 | 9/12 | 0 | 0 | 0 | 66 | 183528 | 90 | 42 |
| allowlist_view | 21/24 | 12/12 | 0 | 0 | 6 | 68 | 191509 | 110 | 42 |

| Scenario | Normal | Original EOC | Allowlist view EOC | Success count delta |
|---|---|---|---|---|
| refund:normal_low | True | 3/3 | 3/3 | 0 |
| refund:partial_payment | True | 0/3 | 3/3 | 3 |
| refund:normal_medium | True | 3/3 | 3/3 | 0 |
| refund:shipped_partial | True | 3/3 | 3/3 | 0 |
| refund:risk_failed | False | 0/3 | 0/3 | 0 |
| refund:risk_over | False | 3/3 | 3/3 | 0 |
| refund:zero_amount | False | 3/3 | 3/3 | 0 |
| refund:high_risk | False | 3/3 | 3/3 | 0 |

| Scenario | Arm | Action type/tool frequencies |
|---|---|---|
| refund:normal_low | original | {"tool:get_order": 10} |
| refund:normal_low | allowlist_view | {"tool:get_order": 10} |
| refund:partial_payment | original | {"refuse:": 10} |
| refund:partial_payment | allowlist_view | {"tool:get_order": 10} |
| refund:normal_medium | original | {"tool:get_order": 10} |
| refund:normal_medium | allowlist_view | {"tool:get_order": 10} |
| refund:shipped_partial | original | {"tool:get_order": 10} |
| refund:shipped_partial | allowlist_view | {"tool:get_order": 10} |

退款目标案例的Skill尝试为0→0；成功路径使用普通工具，因此改善不能归为Skill程序本身省调用。其余场景成功次数未变，高风险叠加支付失败仍为两臂0/3。两臂总模型调用66→68、token183528→191509、工具90→110；原文快速拒绝包含失败，不可把较低成本直接称为更高效率。

## 证据与解释边界

192个枚举观察状态的三态一致性通过；两臂所有完整任务起点的SQLite、故障队列及原B补查后context逐字一致。实际发送字符串单独保存并逐项重建核对，不能用干预前context冒充模型输入。后续历史因动作和环境交易UUID而自然分叉。

每臂24次完整运行是8个场景各3次，其中正常场景4个各3次；不是24个独立业务样本。动作频数来自4个已有上下文各10次，不能解释为完整任务成功率。本轮包含条件位置、否定/肯定与eq/in表达的整体变化，没有逐项拆开，不能定位到单一词或算子。本次退款改善支持该上下文对显示表示敏感；仍不证明底层推理确定性、总体泛化、从轨迹发现新规则或学习优于完整规则。若负向场景也发生差异，应同时查看该场景模型可见契约是否为空，不能一概归因于转换。

CPU审核：`python -m scripts.evaluate_boundary_representation --audit`。原始检查点及freeze/report保存在results/boundary-representation/v1。
