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
| p1-refund_normal-12102029 | withheld | 1 | 1 | 5 | 21792 | 0 |

## 结论边界与成本

原始失败、未加载调用和 primitive 替代保留；调用率不能替代 EOC。Runtime assisted 不直接等于 rescued，缺少关闭 contract 的配对消融时不估计后者。

共享开发账本累计 457,995 tokens / 1677.40 秒，包含既有两轮和加载模型前失败记录。CPU 准备、机会执行及工具内部成本另见原始报告。

下一出口是 P2 的公开工作流与独立 EOC、learn 数据及 Opportunity/TraceCompiler；此 smoke 不是正式 P5 泛化实验或模型比较。

## 未完成部分

本组只完成 1 个完整配对，另有 1 个单臂；单臂不进入配对效应。

原因：`ValueError: shared developmental token budget exhausted before arm`。目前采用启动前预留整任务上限的保守预算检查；剩余额度小于单臂上限时不启动，不能把未执行结果填为成功。

P1 工程观测与已完成诊断可以审计，但本组计划尚未完成；正式准入与研究结论均未通过。下一步先补预算调度/安全续跑与 PrimitiveOnly 基线诊断，再推进 P2 的独立工作流目标。

## 保留的首轮分叉失败

`results/skill-evolution/v1.2/development/p1-main-v3-fork-20261012-v1`：2/4 EOC。

- p1-cancel_normal-12102029 / withheld: budget_exhausted; skill_not_loaded, budget_exhausted:search
- p1-refund_normal-12102029 / withheld: budget_exhausted; skill_not_loaded, budget_exhausted:search

首轮模型把 primitive 工具名输出为 Skill，随后调用零预算搜索。该失败用于公开接口的开发修正，不能把修正前后差异当作新技能学习收益。

`results/skill-evolution/v1.2/development/p1-main-v3-fork-20261012-v2-action-contract`：2/4 EOC。

- p1-cancel_normal-12102029 / withheld: budget_exhausted; skill_not_loaded, budget_exhausted:search
- p1-refund_normal-12102029 / withheld: budget_exhausted; skill_not_loaded, budget_exhausted:search

首轮模型把 primitive 工具名输出为 Skill，随后调用零预算搜索。该失败用于公开接口的开发修正，不能把修正前后差异当作新技能学习收益。
