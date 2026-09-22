# 第三轮：退款 Skill 与有界修订

日期：2026-09-10

## 已交付

- 退款 Skill：从成功、业务失败轨迹和 policy 编译，支持全额/部分退款、剩余额限制、高风险边界及写入后累计金额验证。
- 固定领域谓词，缺失信息保持 UNKNOWN；没有引入通用算术 DSL 或新的 Agent。
- 最多两轮的自动修订：先验证，通过失败反馈选择边界或执行段，依据 train＋policy 恢复支持的领域契约。每轮保留独立版本、失败任务、变更字段和源哈希。
- prepare 默认三类 Skill，新增 refine CLI，可选择0/1/2轮预算；测试集不参与修订。

## 验证结果

全套 **43 passed，2 条上游弃用 warning，11.71秒**。定向测试包含非法金额、已有退款余额、响应丢失、耗尽后转人工、无可用修订、预算上限、数据分区及候选不变性。

五组系统配置，每组78个任务重复3次，总计 **1,170次工程执行全部通过**。三类固定候选决策探针：地址21/21、取消12/12、退款15/15；分别显式跳过9、3、3个权限/故障准备案例。

以上均为 **scripted-engineering-only**，LLM调用数为0，不代表真实模型收益。本轮没有训练或部署权重。

## 两轮修订演示

为验证修订机制，明确人为删除退款候选的风控禁止条件，并把后置金额改为-999。该候选是工程故障注入，不是模型生成的失败。

| 版本 | 本轮变更 | 正例成功率 | 反例拒绝率 | 失败案例 |
|---|---|---:|---:|---:|
| v1 | 初始故障候选 | 0% | 66.7% | 12 |
| v2 | 恢复 forbidden_conditions | 0% | 100% | 9 |
| v3 | 恢复 postconditions | 100% | 100% | 0 |

最终 VERIFIED。限制为一轮时，候选 REJECTED；持续基础设施错误且没有支持的契约修复时，返回 no_supported_repair，不继续循环。

这属于有限领域的可审计修订，不是开放域程序发现，也不会通过放宽业务 policy 使测试通过。

## 发现的问题

首次系统对照全部通过，但退款决策探针0/15。根因是脚本策略额外要求无关的物流观察；修复后使用退款所需的订单、客户和支付观察，新增探针回归。首次失败结果保留：`results/round3-comparisons/eb4bffdf-3be8-4cad-bb88-f87f3f1927a8`。

同时补充 Skill result.error 的耗尽处理，确保同一失败退款不会反复被选择。已有退款金额作为 mutation 前的目标计算依据，避免写后再次相加。

## 产物

- 训练源（99条）：`results/round3-sources/52454726-063e-4b8d-a2d1-fdbc549fd9ae/source_trajectories.jsonl`，含69次脚本任务和30次显式失败注入。
- 三类冻结包：`results/round3-frozen/frozen.json`。
- 修订输入及说明：`results/round3-repair-input/`。
- 逐版修订记录：`results/round3-repair-demo/attempt-0.json`、`attempt-1.json`、`attempt-2.json`、`summary.json`。
- 最终对照：`results/round3-comparisons/8a5bee11-0d2c-417f-af8a-2a7245615c89/comparison.json`，同目录包含CSV、分层数据和完整轨迹。

## 下一阶段依赖

真实 Student endpoint 和模型环境仍待接入。正式训练前需要真实 B0–B3 对照、真实轨迹数据审计与偏好样本采集。开放域合成、检索扩展、Skill composition、训练脚本及权重部署仍未完成。
