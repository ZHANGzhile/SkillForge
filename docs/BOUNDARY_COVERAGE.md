# main-v3边界覆盖核验

先重新审核全部原训练语料和新实例B3检查点，再统计以下条件。本脚本只读分析，不生成训练样本。

| 条件 | train任务 | validation任务 | 去重SFT动作目标 | 已查看test任务 | B3合格 |
|---|---:|---:|---:|---:|---:|
| high_risk_and_shipped | 0 | 0 | 0 | 3 | 0 |
| invalid_address_with_cancel_fallback | 0 | 0 | 0 | 3 | 0 |
| shipped_with_explicit_human_fallback | 0 | 0 | 0 | 3 | 0 |
| refund_above_remaining | 3 | 3 | 35 | 3 | 2 |
| refund_exact_remaining | 3 | 3 | 124 | 3 | 3 |

复合三分支和风险/物流冲突是原数据设计中的保留条件；没有train样本本身不是实现错误。validation69/69不能外推到这些没有覆盖的组合条件。超额退款在train中已有样本，其失败还需要检查数值比较与多步决策，不能一概解释为训练完全没见过。

如后续将这些结构纳入新版本训练，必须明确改变泛化研究范围，重新设计分区与尚未使用的新测试结构；不能把本次test改标为train后继续沿用原独立测试结论。

原始记录：results/training-diagnostics/main-v3/boundary-coverage.json。动作目标数量不是独立任务数量。
