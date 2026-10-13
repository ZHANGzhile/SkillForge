# 新版 P1 开发验证结果

固定 main-v3；全部结果为 dev。没有生成或激活新 Skill，没有研究收益或显著性主张。

## 自然调用

6/6 EOC；0 违规尝试，0 实际违规。

独立初始完整任务机会漏斗（单位 task-revision，不是全任务分母）：

eligible=3 → searched=2 → retrieved=2 → loaded=2 → gate_applicable=2 → offered=2 → selected=2 → executed=2 → verified=2

自然调用协议：`skill-search-load-use-v1.2-dev3-observable`；最终分叉协议：`skill-search-load-use-v1.2-dev4-action-contract`。两批是独立诊断，不能跨批计算同协议效果。

## 同状态可见性分叉

同一快照、公开读取、历史前缀、模型和预算；仅初始目录加载项不同。两臂均允许后续正常搜索/加载，因此这是初始预加载与自然发现的比较，不是正式 PrimitiveOnly。

| Task | Arm | EOC | Skill calls | Model calls | Tokens | Runtime interventions |
|---|---|---:|---:|---:|---:|---:|
| p1-cancel_normal-12102029 | provided | 1 | 1 | 2 | 10266 | 0 |
| p1-cancel_normal-12102029 | withheld | 1 | 1 | 6 | 24762 | 0 |
| p1-refund_normal-12102029 | provided | 1 | 1 | 2 | 10395 | 0 |
| p1-refund_normal-12102029 | withheld | 1 | 1 | 5 | 21792 | 0 |

本目录继承 3 个已完成臂，只新执行 1 个从未启动的臂。原 partial 报告保持不变；续跑新增成本为 10,395 tokens / 49.32 秒。继承臂不是新增独立样本，也没有重复计费。

续跑身份：`3420ce516cd4b08f786b790b8ae87e45e4706ef8dbf3955df976cec79ee4a4a3`；每次推理在既有 checkpoint ACK 前有不可变预算准入回执。

## 结论边界与成本

原始失败、未加载调用和 primitive 替代保留；调用率不能替代 EOC。Runtime assisted 不直接等于 rescued，缺少关闭 contract 的配对消融时不估计后者。

共享开发账本累计 468,390 tokens / 1726.72 秒，包含既有两轮和加载模型前失败记录。CPU 准备、机会执行及工具内部成本另见原始报告。

下一出口是 P2 的公开工作流与独立 EOC、真实 learn 数据及 Opportunity/TraceCompiler；真实 PrimitiveOnly/StaticLibrary/ExperienceEvolution 公平对照须在 P5 冻结并执行。此 smoke 不是正式 P5 泛化实验或模型比较。

## 保留的历史分叉与停止记录

`results/skill-evolution/v1.2/development/p1-main-v3-fork-20261012-v1`：2/4 EOC。

- p1-cancel_normal-12102029 / withheld: budget_exhausted; skill_not_loaded, budget_exhausted:search
- p1-refund_normal-12102029 / withheld: budget_exhausted; skill_not_loaded, budget_exhausted:search

首轮模型把 primitive 工具名输出为 Skill，随后调用零预算搜索。该失败用于公开接口的开发修正，不能把修正前后差异当作新技能学习收益。

`results/skill-evolution/v1.2/development/p1-main-v3-fork-20261012-v2-action-contract`：2/4 EOC。

- p1-cancel_normal-12102029 / withheld: budget_exhausted; skill_not_loaded, budget_exhausted:search
- p1-refund_normal-12102029 / withheld: budget_exhausted; skill_not_loaded, budget_exhausted:search

首轮模型把 primitive 工具名输出为 Skill，随后调用零预算搜索。该失败用于公开接口的开发修正，不能把修正前后差异当作新技能学习收益。

`results\skill-evolution\v1.2\development\p1-main-v3-fork-20261012-v3-discovery-recovery`：3/3 EOC。

历史报告状态 `blocked_or_incomplete`：`ValueError: shared developmental token budget exhausted before arm`。后续继承完成不改写该报告，也不把继承部分算作另一组独立样本。


首轮模型把 primitive 工具名输出为 Skill，随后调用零预算搜索。该失败用于公开接口的开发修正，不能把修正前后差异当作新技能学习收益。
